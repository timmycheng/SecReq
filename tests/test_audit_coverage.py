# -*- coding: utf-8 -*-
"""审计覆盖: 敏感动作必须留痕。

安全合规产品的门面 —— 登录失败、建项、删项、向导步骤保存、产物导出
这几类动作若缺失留痕, 事后无法追溯"谁在什么时候动过什么"。
"""
from conftest import api_as


def _actions(api) -> list[str]:
    """以安全角色读取审计日志, 返回动作列表(按 id 倒序)。"""
    resp = api_as(api, "sec_chen").get("/api/admin/audit-logs")
    assert resp.status_code == 200, resp.text
    return [row["action"] for row in resp.json()]


def _new_project(api) -> int:
    resp = api.post("/api/projects", json={"name": "审计测试项目"})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_login_failure_is_audited(api):
    resp = api.post("/api/auth/login",
                    json={"username": "dev_li", "password": "definitely-wrong"})
    assert resp.status_code == 401
    assert "login_failed" in _actions(api)


def test_project_create_is_audited(api):
    _new_project(api)
    assert "project_create" in _actions(api)


def test_project_delete_is_audited(api):
    pid = _new_project(api)
    resp = api.delete(f"/api/projects/{pid}")
    assert resp.status_code == 204, resp.text
    assert "project_delete" in _actions(api)


def test_step_save_is_audited(api):
    pid = _new_project(api)
    resp = api.post(f"/api/projects/{pid}/features", json=[{
        "name": "转账", "module": "支付模块", "categories": ["payment"],
        "sensitivity": "confidential", "involves_payment": True,
    }])
    assert resp.status_code == 200, resp.text
    assert "step_save" in _actions(api)


def test_step_save_records_step_name_and_count(api):
    """留痕内容应含步骤名与条目数, 不含全量数据(避免审计库膨胀)。"""
    pid = _new_project(api)
    api.post(f"/api/projects/{pid}/features", json=[
        {"name": "登录", "categories": ["auth_login"]},
        {"name": "转账", "categories": ["payment"]},
    ])
    rows = api_as(api, "sec_chen").get("/api/admin/audit-logs").json()
    entry = next(r for r in rows if r["action"] == "step_save")
    assert entry["detail"]["step"] == "features"
    assert entry["detail"]["count"] == 2
    assert entry["detail"]["project_id"] == pid
    # 只存统计, 不存功能名等明细
    assert "登录" not in str(entry["detail"])


def test_export_requires_generated_baseline(api):
    """导出受 409 保护: 未生成基线时不能外带数据(同时确认不会留下 export 痕迹)。"""
    pid = _new_project(api)
    resp = api.get(f"/api/projects/{pid}/export/xlsx")
    assert resp.status_code == 409
    assert "export" not in _actions(api)


def test_audit_rows_carry_label_and_summary(api):
    """端点统一下发中文标签与明细摘要(#65): 前端不自映射, 存量未知动作回退原文。"""
    pid = _new_project(api)
    resp = api.post(f"/api/projects/{pid}/features", json=[{
        "name": "转账", "module": "支付模块", "categories": ["payment"],
        "sensitivity": "confidential", "involves_payment": True,
    }])
    assert resp.status_code == 200, resp.text
    rows = api_as(api, "sec_chen").get("/api/admin/audit-logs").json()

    step_row = next(r for r in rows if r["action"] == "step_save")
    assert step_row["action_label"] == "保存向导步骤"
    assert step_row["summary"] == f"项目 #{pid} 保存功能清单, 共 1 条"

    create_row = next(r for r in rows if r["action"] == "project_create"
                      and r["detail"].get("project_id") == pid)
    assert create_row["action_label"] == "创建项目"
    assert "审计测试项目" in (create_row["summary"] or "")


def test_audit_label_and_summary_fallback_for_unknown_action():
    """未注册的存量 action: 标签回退原始 code, 摘要为 None(前端回退原文)。"""
    from services.audit_service import action_label, summarize_detail
    assert action_label("legacy_action") == "legacy_action"
    assert summarize_detail("legacy_action", {"k": 1}) is None
