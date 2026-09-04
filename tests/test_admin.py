# -*- coding: utf-8 -*-
"""系统管理端点(走查整改): 仅安全角色可访问; 知识库/题库写回带校验;
策略基线可配置; 用户管理与审计留痕。"""
import base64
import shutil
import uuid

import pytest

from conftest import api_as, create_system_api
from services.auth_service import SEED_DEFAULT_PASSWORD


@pytest.fixture()
def sec(api):
    """安全角色客户端。"""
    return api_as(api, "sec_admin")


@pytest.fixture()
def kb_files(tmp_path, monkeypatch):
    """知识库/题库文件替换为临时副本, 避免测试污染真实文件。

    两条读取路径都要指向副本: kb_admin(编辑写回)与 rules.loader(列表展示),
    生产环境两者指向同一文件, 测试里若只 patch 一边, 编辑后经 GET 读取的
    断言会读到真实文件而非副本。
    """
    import rules.loader as loader
    import services.kb_admin as kb

    kb_copy = tmp_path / "knowledge_base.yml"
    q_copy = tmp_path / "grading_questions.yml"
    shutil.copy(kb.DEFAULT_KB_PATH, kb_copy)
    shutil.copy(kb.QUESTION_BANK_PATH, q_copy)
    monkeypatch.setattr(kb, "DEFAULT_KB_PATH", kb_copy)
    monkeypatch.setattr(loader, "DEFAULT_KB_PATH", kb_copy)
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


def test_knowledge_base_update_regulatory_ref(sec, kb_files):
    """编辑弹窗补齐监管出处能力(#80): 修改生效, 非法结构被回滚。"""
    target = sec.get("/api/admin/knowledge-base").json()["templates"][0]["id"]

    new_ref = [{"file": "JR/T 0197-2020", "clause": "7.1.3",
                "summary": "测试出处", "note": "待合规部门确认"}]
    resp = sec.put(f"/api/admin/knowledge-base/{target}", json={"regulatory_ref": new_ref})
    assert resp.status_code == 200, resp.text
    assert resp.json()["regulatory_ref"] == new_ref

    # 重新读取回显正确(写回 YAML 后经 loader 全量校验)
    rows = sec.get("/api/admin/knowledge-base").json()["templates"]
    assert next(r for r in rows if r["id"] == target)["regulatory_ref"] == new_ref

    # 缺 file 的条目被 loader 判为整组非法 → 必填校验失败 → 保存回滚
    resp = sec.put(f"/api/admin/knowledge-base/{target}",
                   json={"regulatory_ref": [{"clause": "7.1.3"}]})
    assert resp.status_code == 400
    assert "回滚" in resp.json()["detail"]
    rows = sec.get("/api/admin/knowledge-base").json()["templates"]
    assert next(r for r in rows if r["id"] == target)["regulatory_ref"] == new_ref


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

    sid = create_system_api(api, f"基线系统-{uuid.uuid4().hex[:6]}")["id"]
    pid = api.post("/api/projects", json={
        "name": "策略基线项目", "system_id": sid}).json()["id"]
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

def test_user_update_and_guards(sec):
    """用户编辑(#63): 资料可改, username 不可改, 角色变更留审计。"""
    sec.post("/api/admin/users", json={
        "username": "dev_edit", "display_name": "待编辑", "role": "developer"})

    resp = sec.put("/api/admin/users/dev_edit", json={
        "display_name": "已编辑", "employee_id": "E9001", "role": "security"})
    assert resp.status_code == 200, resp.text
    rows = {r["username"]: r for r in sec.get("/api/admin/users").json()}
    assert rows["dev_edit"]["display_name"] == "已编辑"
    assert rows["dev_edit"]["employee_id"] == "E9001"
    assert rows["dev_edit"]["role"] == "security"

    # 不能修改自己的角色(防止最后一个安全账号自降锁死系统管理)
    resp = sec.put("/api/admin/users/sec_admin", json={"role": "developer"})
    assert resp.status_code == 400
    # 未知角色拒绝
    resp = sec.put("/api/admin/users/dev_edit", json={"role": "admin"})
    assert resp.status_code == 400
    # 不存在的用户 404
    assert sec.put("/api/admin/users/nobody", json={"display_name": "x"}).status_code == 404
    # 审计留痕
    actions = [r["action"] for r in sec.get("/api/admin/audit-logs").json()]
    assert "user_update" in actions


def test_legacy_demo_accounts_deactivated_and_projects_reassigned(session):
    """存量库收敛(#63): 旧演示账号停用, 名下项目转归 dev_admin。"""
    from models import PlatformUser, Project
    from services.auth_service import ensure_seed_users

    legacy = PlatformUser(
        username="dev_li", display_name="李开发", employee_id="E1002",
        role="developer", password_hash="legacy-hash",
    )
    session.add(legacy)
    session.flush()
    project = Project(
        name="存量项目", code="PRJ-OLD1", type="web",
        user_scale="1k_to_100k", deploy_env=["private_cloud"], is_public=False,
        owner_user_id=legacy.id,
    )
    session.add(project)
    session.flush()

    ensure_seed_users(session)

    users = {u.username: u for u in session.query(PlatformUser).all()}
    assert users["dev_li"].active is False
    assert users["dev_admin"].active is True
    assert users["sec_admin"].active is True
    assert project.owner_user_id == users["dev_admin"].id


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


@pytest.fixture(scope="module")
def _vulndb_built(tmp_path_factory):
    """四生态小库整个模块只构建一次(build ~0.35s, 5 个用例共享产物)。"""
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
        path = tmp_path_factory.mktemp("admin-vulndb-zips") / f"{eco}.zip"
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr(f"{vuln['id']}.json", json.dumps(vuln))
        zips.append((eco, path))

    out = tmp_path_factory.mktemp("admin-vulndb") / "vulndb.sqlite"
    build(zips, out, slim=False, compress=True)
    return out


@pytest.fixture()
def vulndb_file(tmp_path, _vulndb_built):
    """每用例一份独立副本: verify 用例会在同目录写/删 .sha256 副件,
    私有目录互不干扰(不能像 test_vulndb 那样模块级共享单文件)。"""
    dst = tmp_path / "vulndb.sqlite"
    shutil.copy(_vulndb_built, dst)
    return str(dst)


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


def test_llm_test_connection_requires_key(api, sec):
    """api_key 留空且无已保存配置时, 测试连接直接 400(#62)。"""
    resp = sec.post("/api/admin/llm-config/test", json={
        "base_url": "https://llm-gate.corp.example.com/v1", "api_key": "", "model": "glm-4"})
    assert resp.status_code == 400
    assert "API Key" in resp.json()["detail"]


def test_llm_test_connection_reports_gateway_error(sec, monkeypatch):
    """只测不存: 网关 4xx 归类为可读原因, 不落盘配置(#62)。"""
    import httpx

    def fake_post(url, **kwargs):
        return httpx.Response(401, request=httpx.Request("POST", url), json={"error": "bad key"})

    monkeypatch.setattr(httpx, "post", fake_post)
    resp = sec.post("/api/admin/llm-config/test", json={
        "base_url": "https://llm-gate.corp.example.com/v1", "api_key": "sk-x", "model": "glm-4"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False and "凭据无效" in body["reason"]


def test_llm_test_connection_success(sec, monkeypatch):
    import httpx

    def fake_post(url, **kwargs):
        return httpx.Response(200, request=httpx.Request("POST", url), json={
            "choices": [{"message": {"content": "pong"}}]})

    monkeypatch.setattr(httpx, "post", fake_post)
    resp = sec.post("/api/admin/llm-config/test", json={
        "base_url": "https://llm-gate/v1", "api_key": "sk-x", "model": "glm-4"})
    body = resp.json()
    assert body["ok"] is True and body["reply"] == "pong"
    assert body["latency_ms"] >= 0


def test_project_code_rule_roundtrip_and_generation(sec, api):
    """编号规则可配置(#85): 保存→按新格式生成; 非法前缀拒绝; 审计留痕。"""
    resp = sec.put("/api/admin/project-code-rule", json={
        "prefix": "PRJ", "include_year": False, "digits": 4})
    assert resp.status_code == 200
    assert resp.json() == {"prefix": "PRJ", "include_year": False, "digits": 4}

    sid = create_system_api(api, f"编号系统A-{uuid.uuid4().hex[:6]}")["id"]
    resp = api.post("/api/projects", json={"name": "自定义编号项目", "system_id": sid})
    assert resp.status_code == 201
    assert resp.json()["code"].startswith("PRJ-") and len(resp.json()["code"].split("-")[1]) == 4

    # 非法前缀(含路径字符)被拦截
    resp = sec.put("/api/admin/project-code-rule", json={
        "prefix": "../etc", "include_year": False, "digits": 3})
    assert resp.status_code == 422  # pydantic pattern 校验
    # 审计
    actions = [r["action"] for r in sec.get("/api/admin/audit-logs").json()]
    assert "code_rule_update" in actions


def test_project_code_rule_fallback_defaults(sec, api):
    """未配置规则时回退历史格式 XM<年份>-<三位序号>(#85 回退路径)。"""
    import re

    sid = create_system_api(api, f"编号系统B-{uuid.uuid4().hex[:6]}")["id"]
    resp = api.post("/api/projects", json={"name": "默认格式项目", "system_id": sid})
    assert resp.status_code == 201
    code = resp.json()["code"]
    assert re.fullmatch(r"XM\d{4}-\d{3}", code), f"默认格式不符: {code}"


def test_changelog_endpoint_versions_descending(sec):
    """更新日志页数据源(#55): 按版本章节解析, 新版本在前。"""
    rows = sec.get("/api/admin/changelog").json()
    assert rows, "应解析出至少一个版本章节"
    # 版本号解析为可比较的三段, 新版本在前(发版后顶部章节会变, 不硬编码具体版本)
    versions = [tuple(int(x) for x in r["version"].split(".")) for r in rows]
    assert versions == sorted(versions, reverse=True)
    dates = [r["date"] for r in rows]
    assert dates == sorted(dates, reverse=True)
    # 结构化块: 最新版本应有正文块(小标题/段落/列表)
    kinds = {b["kind"] for b in rows[0]["blocks"]}
    assert kinds & {"h3", "para", "list_item"}


def test_api_import_parse_text_and_file(api, sec):
    """#92: 批量导入解析 —— 文本/xlsx 两段式, 非法行不阻塞合法行。"""
    import io

    from openpyxl import Workbook

    sid = create_system_api(api, f"导入系统-{uuid.uuid4().hex[:6]}")["id"]
    pid = api.post("/api/projects", json={"name": "导入项目", "system_id": sid}).json()["id"]

    # 文本: 合法行 + 布尔容错 + 非法行
    text = "\n".join([
        "# 注释行跳过",
        "转账接口,POST,/api/v1/transfers,是,是",
        "牌价查询,GET,/api/v1/rates,true,0",
        "坏行,PUTT,/x,,",
    ])
    resp = sec.post(f"/api/projects/{pid}/api-endpoints/parse",
                    files={"text": (None, text)})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 3 and body["invalid"] == 1
    good = [r for r in body["rows"] if not r["error"]]
    assert len(good) == 2
    assert good[0]["method"] == "POST" and good[0]["public_exposed"] is True
    assert good[1]["auth_required"] is True and good[1]["public_exposed"] is False
    assert "/api/v1" in (body["rows"][2]["error"] or "") or "PUTT" in (body["rows"][2]["error"] or "")

    # xlsx: 表头自动跳过
    wb = Workbook()
    ws = wb.active
    ws.append(["名称", "方法", "路径", "需要认证", "公网暴露"])
    ws.append(["客户查询", "GET", "/api/v1/customers", "是", "否"])
    buf = io.BytesIO()
    wb.save(buf)
    resp = sec.post(f"/api/projects/{pid}/api-endpoints/parse",
                    files={"file": ("apis.xlsx", buf.getvalue(),
                                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert resp.status_code == 200, resp.text
    rows = resp.json()["rows"]
    assert len(rows) == 1 and rows[0]["name"] == "客户查询" and rows[0]["auth_required"] is True

    # 确认导入: 合法行走既有整体保存
    save = api.post(f"/api/projects/{pid}/api-endpoints", json=[
        {"name": g["name"], "method": g["method"], "path": g["path"],
         "auth_required": g["auth_required"], "public_exposed": g["public_exposed"]}
        for g in good
    ])
    assert save.status_code == 200, save.text
    assert len(save.json()) == 2


def test_api_import_parse_requires_input(sec, api):
    sid = create_system_api(api, f"空导入系统-{uuid.uuid4().hex[:6]}")["id"]
    pid = api.post("/api/projects", json={"name": "空导入项目", "system_id": sid}).json()["id"]
    resp = sec.post(f"/api/projects/{pid}/api-endpoints/parse",
                    files={"text": (None, "   ")})
    assert resp.status_code == 400


def test_arch_image_roundtrip(api, sec):
    """架构图(#164): 每环境一张 data URL, PUT 幂等覆盖, 类型/编码/大小校验, 删除幂等。"""
    system = create_system_api(api, "架构图系统")
    pid = api.post("/api/projects", json={
        "name": "架构图项目", "system_id": system["id"]}).json()["id"]
    assert sec.get(f"/api/projects/{pid}/arch-images").json() == []

    png = "data:image/png;base64," + base64.b64encode(b"png-bytes").decode()
    resp = sec.put(f"/api/projects/{pid}/arch-images/prod", json={"image_data_url": png})
    assert resp.status_code == 200, resp.text
    assert resp.json()["env"] == "prod"

    # 同环境重复上传 → 覆盖而非新增; 多环境互相独立
    assert sec.put(f"/api/projects/{pid}/arch-images/prod", json={"image_data_url": png}).status_code == 200
    webp = "data:image/webp;base64," + base64.b64encode(b"webp-bytes").decode()
    assert sec.put(f"/api/projects/{pid}/arch-images/test", json={"image_data_url": webp}).status_code == 200
    rows = sec.get(f"/api/projects/{pid}/arch-images").json()
    assert {r["env"] for r in rows} == {"prod", "test"}

    # 非图片类型 / base64 编码无效 / 超过 2MB
    bad_type = sec.put(f"/api/projects/{pid}/arch-images/dev",
                       json={"image_data_url": "data:image/gif;base64,R0lGODlhAQABAAAAADs="})
    assert bad_type.status_code == 400
    bad_b64 = sec.put(f"/api/projects/{pid}/arch-images/dev",
                      json={"image_data_url": "data:image/png;base64,AAAAAAAAAAA"})
    assert bad_b64.status_code == 400
    big = "data:image/png;base64," + base64.b64encode(b"x" * (2 * 1024 * 1024 + 1)).decode()
    assert sec.put(f"/api/projects/{pid}/arch-images/dev", json={"image_data_url": big}).status_code == 413

    # 删除与幂等删除
    assert sec.delete(f"/api/projects/{pid}/arch-images/prod").json() == {"ok": True}
    assert sec.delete(f"/api/projects/{pid}/arch-images/prod").json() == {"ok": True}
    assert {r["env"] for r in sec.get(f"/api/projects/{pid}/arch-images").json()} == {"test"}

def test_kb_create_template_and_duplicate(sec, kb_files):
    """新增模板(#165): POST 落盘可读; 重复 id 与缺必填字段被拦截。"""
    payload = {
        "id": "SEC-TST-901",
        "title": "测试新增模板",
        "description": "测试描述正文",
        "priority": "high",
        "suggested_phase": "design",
        "acceptance_criteria": "测试验收标准",
        "trigger_reason": "测试触发原因",
        "trigger": {"type": "feature_category", "condition": {"category": "auth_login"}},
        "regulatory_ref": [{"file": "测试文件", "clause": "第1条", "summary": "测试"}],
        "asvs_ref": "V1.1.1",
    }
    resp = sec.post("/api/admin/knowledge-base", json=payload)
    assert resp.status_code == 201, resp.text
    rows = sec.get("/api/admin/knowledge-base").json()["templates"]
    created = next(r for r in rows if r["id"] == "SEC-TST-901")
    assert created["title"] == "测试新增模板"

    dup = sec.post("/api/admin/knowledge-base", json=payload)
    assert dup.status_code == 400

    missing = {k: v for k, v in payload.items() if k != "acceptance_criteria"}
    assert sec.post("/api/admin/knowledge-base", json=missing).status_code == 400


def test_kb_update_saves_asvs_ref(sec, kb_files):
    """修复(#165): asvs_ref 此前不在路由模型里, 编辑弹窗该输入框存不进去。"""
    rows = sec.get("/api/admin/knowledge-base").json()["templates"]
    target = rows[0]["id"]
    resp = sec.put(f"/api/admin/knowledge-base/{target}", json={"asvs_ref": "V9.9.9"})
    assert resp.status_code == 200, resp.text
    rows = sec.get("/api/admin/knowledge-base").json()["templates"]
    assert next(r for r in rows if r["id"] == target)["asvs_ref"] == "V9.9.9"


def test_kb_rejects_unknown_condition_key_and_rule_key(sec, kb_files):
    """防呆(#165): 条件键/rule_key 写错保存时报错, 而非生成时静默不命中。"""
    base = {
        "id": "SEC-TST-902",
        "title": "条件键防呆", "description": "d", "priority": "high",
        "suggested_phase": "design", "acceptance_criteria": "a",
        "trigger_reason": "r",
        "regulatory_ref": [{"file": "测试文件", "clause": "", "summary": ""}],
    }
    bad_key = {**base, "trigger": {"type": "feature_category",
                                   "condition": {"catagory": "auth_login"}}}  # 拼写错误
    resp = sec.post("/api/admin/knowledge-base", json=bad_key)
    assert resp.status_code == 400 and "catagory" in resp.json()["detail"]

    bad_rule = {**base, "id": "SEC-TST-903",
                "trigger": {"type": "permission_rule",
                            "condition": {"rule_key": "super_admin"}}}  # 引擎键是 super_admin_exists
    resp = sec.post("/api/admin/knowledge-base", json=bad_rule)
    assert resp.status_code == 400 and "super_admin_exists" in resp.json()["detail"]

    # 编辑已有模板时同样拦截
    rows = sec.get("/api/admin/knowledge-base").json()["templates"]
    target = rows[0]["id"]
    resp = sec.put(f"/api/admin/knowledge-base/{target}",
                   json={"trigger": {"type": "data_asset",
                                     "condition": {"nonsense_key": True}}})
    assert resp.status_code == 400 and "nonsense_key" in resp.json()["detail"]
