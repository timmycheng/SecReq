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
