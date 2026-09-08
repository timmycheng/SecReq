# -*- coding: utf-8 -*-
"""评估状态机收口(DESIGN): 审批态内容锁定 + 开发侧撤回 + 清单耗时输出 + 种子四角色。

撤回语义: 审批中(in_review)提交人可撤回, 门禁回 pending、项目回草稿、数据全保留,
重提后哈希链续写不断链。
"""
import pytest

from conftest import api_as, create_system_api, demo_features, login_as


@pytest.fixture()
def generated(api):
    """一个已生成需求且满足门禁的评估, 返回 (pid, system_id, requirements)。"""
    sid = create_system_api(api, "撤回系统")["id"]
    pid = api.post("/api/projects", json={
        "name": "撤回项目", "system_id": sid}).json()["id"]
    resp = api.post(f"/api/projects/{pid}/features",
                    json=[f.model_dump() for f in demo_features()])
    assert resp.status_code == 200, resp.text
    gen = api.post(f"/api/projects/{pid}/generate", json={"skip_osv": True})
    assert gen.status_code == 200, gen.text
    from conftest import satisfy_design_gate
    satisfy_design_gate(api, sid, pid)
    reqs = api.get(f"/api/projects/{pid}/requirements").json()
    assert reqs
    return pid, sid, reqs


@pytest.fixture()
def reviewers(api):
    sec = api_as(api, "sec_admin")
    resp = sec.post("/api/admin/users", json={
        "username": "wd_reviewer", "display_name": "wd_reviewer",
        "role": "security_reviewer"})
    assert resp.status_code == 201, resp.text
    return True


def _client(api, username):
    from fastapi.testclient import TestClient
    return login_as(TestClient(api.app), username)


def _confirm_all(api, pid, reqs):
    ids = [r["req_id"] for r in reqs]
    resp = api.post(f"/api/projects/{pid}/requirements/batch-confirm",
                    json={"req_ids": ids})
    assert resp.status_code == 200, resp.text


def test_in_review_locks_content_writes(api, generated):
    """审批中各项信息不可修改: 向导写端点/Step1/一键清空一律 409, 撤回后恢复。"""
    pid, _, reqs = generated
    _confirm_all(api, pid, reqs)
    assert api.post(f"/api/projects/{pid}/review/submit").json()["status"] == "submitted"

    resp = api.post(f"/api/projects/{pid}/features", json=[
        f.model_dump() for f in demo_features()])
    assert resp.status_code == 409, resp.text
    assert "撤回" in resp.json()["detail"]
    assert api.patch(f"/api/projects/{pid}", json={"name": "改名"}).status_code == 409
    assert api.post(f"/api/projects/{pid}/reset-wizard").status_code == 409
    # 审批中也不能整卷删除
    assert api.delete(f"/api/projects/{pid}").status_code == 409
    # 读不受影响
    assert api.get(f"/api/projects/{pid}/wizard-state").status_code == 200

    # 撤回后回到可编辑(重存已有行, uid 连续性要求保留稳定标识)
    assert api.post(f"/api/projects/{pid}/review/withdraw").json()["gate_status"] == "pending"
    rows = {r["id"]: r for r in api.get("/api/projects").json()}
    assert rows[pid]["status"] == "draft"
    existing = api.get(f"/api/projects/{pid}/features").json()
    assert api.post(f"/api/projects/{pid}/features", json=existing).status_code == 200


def test_withdraw_only_by_submitter_and_only_in_review(api, generated, reviewers):
    """非提交人撤回 403; 非审批中撤回 409; 撤回留痕进哈希链且链完整。"""
    pid, _, reqs = generated
    _confirm_all(api, pid, reqs)
    assert api.post(f"/api/projects/{pid}/review/submit").json()["status"] == "submitted"

    # 非提交人撤回 → 403(sec_admin 是全量可见的安全负责人, 但不是提交人)
    sec = api_as(api, "sec_admin")
    assert sec.post(f"/api/projects/{pid}/review/withdraw").status_code == 403

    state = api.get(f"/api/projects/{pid}/review/state").json()
    assert state["gate"]["status"] == "in_review"

    assert api.post(f"/api/projects/{pid}/review/withdraw").status_code == 200
    assert api.post(f"/api/projects/{pid}/review/withdraw").status_code == 409

    state = api.get(f"/api/projects/{pid}/review/state").json()
    assert state["chain_valid"] is True
    assert state["evidences"][-1]["action"] == "withdraw"

    # 撤回后重提不受历史批注影响(链续写), 全链路可再次走通
    assert api.post(f"/api/projects/{pid}/review/submit").json()["status"] == "submitted"
    state = api.get(f"/api/projects/{pid}/review/state").json()
    assert state["chain_valid"] is True


def test_passed_locks_content_but_allows_cleanup(api, generated, reviewers):
    """终审通过后内容锁定(已落盘); 删除不再拦(允许清理历史轮次)。"""
    pid, _, reqs = generated
    _confirm_all(api, pid, reqs)
    api.post(f"/api/projects/{pid}/review/submit")
    reviewer = _client(api, "wd_reviewer")
    lead = _client(api, "sec_admin")
    for r in reqs:
        reviewer.post(f"/api/projects/{pid}/review/requirements/{r['req_id']}/annotate",
                      json={"disposition": "approve"})
    reviewer.post(f"/api/projects/{pid}/review/decide", json={"conclusion": "approve"})
    resp = lead.post(f"/api/projects/{pid}/review/finalize", json={})
    assert resp.status_code == 200, resp.text

    assert api.post(f"/api/projects/{pid}/features",
                    json=[f.model_dump() for f in demo_features()]).status_code == 409
    assert api.patch(f"/api/projects/{pid}", json={"name": "x"}).status_code == 409


def test_project_list_outputs_duration_seconds(api, generated):
    """评估清单耗时(DESIGN): 步骤埋点秒数在清单接口聚合输出。"""
    pid, _, _ = generated
    rows = {r["id"]: r for r in api.get("/api/projects").json()}
    assert rows[pid]["duration_seconds"] is None
    existing = api.get(f"/api/projects/{pid}/features").json()
    resp = api.post(f"/api/projects/{pid}/features?duration_seconds=42", json=existing)
    assert resp.status_code == 200, resp.text
    rows = {r["id"]: r for r in api.get("/api/projects").json()}
    assert rows[pid]["duration_seconds"] == 42.0


def test_seed_users_cover_all_four_roles(api):
    """DESIGN: 默认各角色用户各设置一个 —— 四角色种子账号均可登录。"""
    from services.auth_service import SEED_DEFAULT_PASSWORD
    from fastapi.testclient import TestClient
    for username, role in (("dev_admin", "pm"), ("sec_admin", "security_lead"),
                           ("sec_reviewer", "security_reviewer"), ("auditor", "auditor")):
        resp = TestClient(api.app).post("/api/auth/login", json={
            "username": username, "password": SEED_DEFAULT_PASSWORD})
        assert resp.status_code == 200, resp.text
        assert resp.json()["role"] == role


def test_review_actions_carry_chinese_audit_labels(api, generated):
    """日志审计中文化(DESIGN): 评审/撤回动作下发中文标签与摘要, 不再回退英文 code。"""
    pid, _, reqs = generated
    _confirm_all(api, pid, reqs)
    api.post(f"/api/projects/{pid}/review/submit")
    api.post(f"/api/projects/{pid}/review/withdraw")

    rows = api_as(api, "sec_admin").get("/api/admin/audit-logs").json()
    by_action = {r["action"]: r for r in rows}
    submit_row = by_action["review_submit"]
    assert submit_row["action_label"] == "提交评审"
    assert f"#{pid}" in (submit_row["summary"] or "")
    withdraw_row = by_action["project_withdraw"]
    assert withdraw_row["action_label"] == "撤回评审"
    assert "数据保留" in (withdraw_row["summary"] or "")
