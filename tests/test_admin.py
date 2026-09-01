# -*- coding: utf-8 -*-
"""系统管理端点(走查整改): 仅安全角色可访问; 知识库/题库写回带校验;
策略基线可配置; 用户管理与审计留痕。"""
import shutil
import uuid

import pytest

from conftest import api_as
from services.auth_service import SEED_DEFAULT_PASSWORD


@pytest.fixture()
def sec(api):
    """安全角色客户端。"""
    return api_as(api, "sec_chen")


@pytest.fixture()
def kb_files(tmp_path, monkeypatch):
    """知识库/题库文件替换为临时副本, 避免测试污染真实文件。"""
    import services.kb_admin as kb

    kb_copy = tmp_path / "knowledge_base.yml"
    q_copy = tmp_path / "grading_questions.yml"
    shutil.copy(kb.DEFAULT_KB_PATH, kb_copy)
    shutil.copy(kb.QUESTION_BANK_PATH, q_copy)
    monkeypatch.setattr(kb, "DEFAULT_KB_PATH", kb_copy)
    monkeypatch.setattr(kb, "QUESTION_BANK_PATH", q_copy)
    yield {"kb": kb_copy, "questions": q_copy}


def test_admin_requires_security_role(api, sec):
    assert api.get("/api/admin/users").status_code == 403          # 开发角色
    assert sec.get("/api/admin/users").status_code == 200          # 安全角色


def test_knowledge_base_list_and_toggle(sec, kb_files):
    rows = sec.get("/api/admin/knowledge-base").json()["templates"]
    assert len(rows) >= 60
    target = rows[0]["id"]

    resp = sec.put(f"/api/admin/knowledge-base/{target}", json={"enabled": False})
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False

    # 停用后的模板从清单中仍可见但 enabled=False; 引擎加载时跳过
    from rules.loader import load_knowledge_base
    from services.kb_admin import DEFAULT_KB_PATH
    kb = load_knowledge_base(DEFAULT_KB_PATH)
    tpl = next(t for t in kb.templates if t.id == target)
    assert tpl.enabled is False

    sec.put(f"/api/admin/knowledge-base/{target}", json={"enabled": True})


def test_knowledge_base_invalid_trigger_rolls_back(sec, kb_files):
    rows = sec.get("/api/admin/knowledge-base").json()["templates"]
    target = rows[0]["id"]
    before = (r for r in rows if r["id"] == target)
    resp = sec.put(f"/api/admin/knowledge-base/{target}", json={"trigger": {"type": "bad_type"}})
    assert resp.status_code == 400
    assert "回滚" in resp.json()["detail"]
    assert next(before)["id"] == target  # 原数据仍可读
    # 文件内容未损坏(校验器能通过)
    from rules.loader import load_knowledge_base
    from services.kb_admin import DEFAULT_KB_PATH
    assert len(load_knowledge_base(DEFAULT_KB_PATH).templates) >= 60


def test_question_bank_roundtrip(sec, kb_files):
    bank = sec.get("/api/admin/grading-questions").json()
    assert bank["questions"]
    bank["questions"][0]["options"][0]["score"] = 9
    assert sec.put("/api/admin/grading-questions", json=bank).status_code == 200
    fresh = sec.get("/api/admin/grading-questions").json()
    assert fresh["questions"][0]["options"][0]["score"] == 9


def test_policy_baselines_effect_on_grading_baseline(sec, api):
    resp = sec.put("/api/admin/policy-baselines", json={
        "baselines": {
            "一级": {"pwd_min_length": 8, "pwd_complexity": 3, "pwd_valid_days": 180},
            "二级": {"pwd_min_length": 8, "pwd_complexity": 3, "pwd_valid_days": 90},
            "三级": {"pwd_min_length": 12, "pwd_complexity": 4, "pwd_valid_days": 60},
        },
        "lockout_threshold": 5,
        "session_timeout_min": 15,
    })
    assert resp.status_code == 200, resp.text

    pid = api.post("/api/projects", json={
        "name": "策略基线项目", "type": "web", "user_scale": "1k_to_100k"}).json()["id"]
    api.post(f"/api/projects/{pid}/survey", json={"answers": [], "final_level": "三级"})
    baseline = api.get(f"/api/projects/{pid}/grading-baseline").json()
    assert baseline["pwd_defaults"]["pwd_min_length"] == "12"  # 覆盖值生效


def test_user_management_and_audit(api, sec):
    # 创建
    resp = sec.post("/api/admin/users", json={
        "username": "dev_new", "display_name": "新开发", "role": "developer"})
    assert resp.status_code == 201
    assert resp.json()["initial_password"] == SEED_DEFAULT_PASSWORD
    # 重复创建 409
    assert sec.post("/api/admin/users", json={
        "username": "dev_new", "display_name": "重复", "role": "developer"}).status_code == 409
    # 停用/启用
    toggle = sec.post("/api/admin/users/dev_new/toggle-active")
    assert toggle.status_code == 200 and toggle.json()["active"] is False
    assert sec.post("/api/admin/users/dev_new/toggle-active").json()["active"] is True
    # 重置密码(显式指定随机生成的口令, 测试内不明文写死凭据)
    explicit_password = "Reset-" + uuid.uuid4().hex[:10]
    assert sec.post("/api/admin/users/dev_new/reset-password",
                    json={"password": explicit_password}).status_code == 200
    # 重置密码(缺省时后端生成随机密码并在响应中返回, 且可直接登录)
    reset = sec.post("/api/admin/users/dev_new/reset-password", json={})
    assert reset.status_code == 200
    generated = reset.json()["password"]
    assert generated and len(generated) >= 8
    assert generated != explicit_password
    login = api.post("/api/auth/login", json={"username": "dev_new", "password": generated})
    assert login.status_code == 200, login.text
    # 审计日志包含以上动作
    logs = sec.get("/api/admin/audit-logs").json()
    actions = {log["action"] for log in logs}
    assert {"user_create", "user_toggle", "user_reset_password"} <= actions


def test_llm_config_roundtrip_masks_key(sec):
    assert sec.put("/api/admin/llm-config", json={
        "base_url": "https://llm.example.com/v1", "api_key": "sk-secret-1234", "model": "glm-4",
    }).status_code == 200
    cfg = sec.get("/api/admin/llm-config").json()
    assert cfg["configured"] is True
    assert "sk-secret-1234" not in (cfg.get("api_key") or "")


# ── 离线漏洞库(v2.2.0) ────────────────────────────────

def test_vuln_db_requires_security_role(api, sec):
    assert api.get("/api/admin/vuln-db").status_code == 403
    assert sec.get("/api/admin/vuln-db").status_code == 200


def test_vuln_db_reports_missing_library_clearly(sec, monkeypatch, tmp_path):
    """库缺失时必须报 available=False, 不能伪装成"已覆盖、未发现漏洞"。"""
    monkeypatch.setenv("SECREQ_VULNDB_PATH", str(tmp_path / "nope.sqlite"))
    body = sec.get("/api/admin/vuln-db").json()
    assert body["available"] is False
    assert body["reason"]
    # 数据源状态照常上报, 便于运维定位
    assert {row["code"] for row in body["sources"]} == {"local", "online", "sca"}


def test_vuln_db_reports_ecosystems_and_gaps(sec, monkeypatch, vulndb_file):
    import services.cnnvd as cnnvd

    monkeypatch.setenv("SECREQ_VULNDB_PATH", vulndb_file)
    monkeypatch.setattr(cnnvd, "stats", lambda path=None: {"available": False, "total": 0})
    body = sec.get("/api/admin/vuln-db").json()

    assert body["available"] is True
    assert body["total"] == 4
    assert set(body["imported_ecosystems"]) == {"bitnami", "alpine", "npm", "maven"}
    # 覆盖缺口必须明确交代, 不能隐身
    codes = {gap["code"] for gap in body["gaps"]}
    assert {"kylin", "k8s"} <= codes
    kylin = next(g for g in body["gaps"] if g["code"] == "kylin")
    assert "麒麟官方安全公告" in kylin["note"]
    # 未导入生态要单列出来, 与"未纳入覆盖"区分开
    missing = {m["code"] for m in body["missing_ecosystems"]}
    assert "openeuler" in missing and "pypi" in missing


def test_vuln_db_verify_matches_and_is_audited(sec, monkeypatch, vulndb_file):
    """校验和从 sidecar 文件读取: 写进库里会改变文件本身, 写入即失效。"""
    import pathlib

    import scripts.build_vuln_db as builder

    monkeypatch.setenv("SECREQ_VULNDB_PATH", vulndb_file)
    digest = builder.sha256_of(pathlib.Path(vulndb_file))
    pathlib.Path(vulndb_file + ".sha256").write_text(
        f"{digest}  {pathlib.Path(vulndb_file).name}\n", encoding="utf-8")

    resp = sec.post("/api/admin/vuln-db/verify")
    assert resp.status_code == 200
    body = resp.json()
    assert body["sha256"] == digest and body["match"] is True

    logs = sec.get("/api/admin/audit-logs").json()
    assert any(log["action"] == "vulndb_verify" for log in logs)


def test_vuln_db_verify_detects_corruption(sec, monkeypatch, vulndb_file):
    import pathlib

    monkeypatch.setenv("SECREQ_VULNDB_PATH", vulndb_file)
    pathlib.Path(vulndb_file + ".sha256").write_text("0" * 64, encoding="utf-8")

    body = sec.post("/api/admin/vuln-db/verify").json()
    assert body["match"] is False
    assert body["expected"] == "0" * 64
    assert pathlib.Path(vulndb_file).is_file()


@pytest.fixture()
def vulndb_file(tmp_path):
    """产出一个四生态小库供漏洞库页测试使用。"""
    import json
    import zipfile

    from scripts.build_vuln_db import build

    sample = {
        "id": "BIT-redis-2021-31294",
        "aliases": ["CVE-2021-31294"],
        "database_specific": {"severity": "CRITICAL"},
        "affected": [{
            "package": {"name": "redis", "ecosystem": "Bitnami"},
            "ranges": [{"type": "SEMVER", "events": [{"introduced": "0"}, {"fixed": "6.2.0"}]}],
        }],
    }
    alp = dict(sample, id="ALPINE-x", affected=[{
        "package": {"name": "openssl", "ecosystem": "Alpine:v3.4"},
        "ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "0"}, {"fixed": "1.0.2h-r0"}]}],
    }])
    npm = dict(sample, id="GHSA-npm", affected=[{
        "package": {"name": "lodash", "ecosystem": "npm"},
        "ranges": [{"type": "SEMVER", "events": [{"introduced": "0"}, {"fixed": "4.17.19"}]}],
    }])
    mvn = dict(sample, id="GHSA-mvn", affected=[{
        "package": {"name": "log4j-core", "ecosystem": "Maven"},
        "ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "0"}, {"fixed": "2.15.0"}]}],
    }])

    zips = []
    for eco, vuln in (("Bitnami", sample), ("Alpine", alp), ("npm", npm), ("Maven", mvn)):
        path = tmp_path / f"{eco}.zip"
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr(f"{vuln['id']}.json", json.dumps(vuln))
        zips.append((eco, path))

    out = tmp_path / "vulndb.sqlite"
    build(zips, out, slim=False, compress=True)
    return str(out)


def test_vuln_db_per_ecosystem_keys_normalized(sec, monkeypatch, vulndb_file):
    """生态记录数按平台 code 读取: 新库 key 已归一化, 旧库 OSV 原始名也要兜底(#61)。"""
    import json
    import sqlite3

    import services.cnnvd as cnnvd

    monkeypatch.setenv("SECREQ_VULNDB_PATH", vulndb_file)
    monkeypatch.setattr(cnnvd, "stats", lambda path=None: {"available": False, "total": 0})

    def declared_records():
        body = sec.get("/api/admin/vuln-db").json()
        return {row["code"]: row["records"] for row in body["declared_ecosystems"]}

    # 新库: 构建端已写平台 code, 各生态记录数可见
    assert declared_records() == {"bitnami": 1, "alpine": 1, "npm": 1, "maven": 1}

    # 存量库: meta 里是 OSV 原始名(PyPI/crates.io…), 读取端按别名表兜底归一化
    legacy = json.dumps({"PyPI": 10, "Maven": 20, "crates.io": 30, "npm": 40})
    with sqlite3.connect(vulndb_file) as conn:
        conn.execute("UPDATE meta SET value = ? WHERE key = 'per_ecosystem'", (legacy,))
        conn.commit()
    records = declared_records()
    # declared 生态以库的 ecosystems 字段为准: pypi/crates 未声明, 不出现在列表
    assert records["maven"] == 20 and records["npm"] == 40
    assert "pypi" not in records and "crates" not in records


def test_vuln_db_verify_without_sidecar_reports_null_match(sec, monkeypatch, vulndb_file):
    """无 sidecar 校验文件时 match 为 null(无可比对), 不再冒充"校验和一致"(#22)。"""
    monkeypatch.setenv("SECREQ_VULNDB_PATH", vulndb_file)

    body = sec.post("/api/admin/vuln-db/verify").json()
    assert body["match"] is None
    assert body["expected"] is None
    assert body["sha256"]


def test_vuln_db_missing_ecosystems_excludes_other(sec, monkeypatch, vulndb_file):
    """「未导入生态」清单不含 other —— 该生态本就不可导入, 列进去配指引是误导(#31)。"""
    import services.cnnvd as cnnvd

    monkeypatch.setenv("SECREQ_VULNDB_PATH", vulndb_file)
    monkeypatch.setattr(cnnvd, "stats", lambda path=None: {"available": False, "total": 0})

    body = sec.get("/api/admin/vuln-db").json()
    assert "other" not in {m["code"] for m in body["missing_ecosystems"]}
