# -*- coding: utf-8 -*-
"""评审中心(#307): 跨项目评审进度总览端点 —— 产生时机/字段/数据权限。"""
import pytest
from fastapi.testclient import TestClient

from conftest import api_as, create_system_api, demo_features, login_as


@pytest.fixture()
def generated(api):
    """一个已生成需求的评估(离线管线), 返回 (pid, requirements)。"""
    sid = create_system_api(api, "总览系统")["id"]
    pid = api.post("/api/projects", json={
        "name": "总览项目", "system_id": sid}).json()["id"]
    resp = api.post(f"/api/projects/{pid}/features",
                    json=[f.model_dump() for f in demo_features()])
    assert resp.status_code == 200, resp.text
    gen = api.post(f"/api/projects/{pid}/generate", json={"skip_osv": True})
    assert gen.status_code == 200, gen.text
    from conftest import satisfy_design_gate
    satisfy_design_gate(api, sid, pid)
    reqs = api.get(f"/api/projects/{pid}/requirements").json()
    assert reqs
    return pid, reqs


@pytest.fixture()
def reviewers(api):
    """安全管理员账号(经管理端创建, 种子默认口令可直接登录; #309 单步评审只需一个)。"""
    sec = api_as(api, "sec_admin")
    resp = sec.post("/api/admin/users", json={
        "username": "seca_u", "display_name": "seca_u", "role": "security_admin"})
    assert resp.status_code == 201, resp.text
    return True


def _client(api, username):
    return login_as(TestClient(api.app), username)


def _confirm_all(api, pid, reqs):
    resp = api.post(f"/api/projects/{pid}/requirements/batch-confirm",
                    json={"req_ids": [r["req_id"] for r in reqs]})
    assert resp.status_code == 200, resp.text


def test_overview_only_after_submit(api, generated):
    """评审中心条目在评估提交后才产生; 未提交不出现。"""
    pid, reqs = generated
    assert api.get("/api/reviews").json() == []
    _confirm_all(api, pid, reqs)
    assert api.post(f"/api/projects/{pid}/review/submit").json()["status"] == "submitted"

    rows = api.get("/api/reviews").json()
    assert len(rows) == 1
    row = rows[0]
    assert row["project_id"] == pid
    assert row["project_code"] is not None
    assert row["gate_status"] == "in_review"
    assert row["status_verb"] == "待安全管理员评审"
    assert row["submitter_name"]  # 提交人为当前开发身份
    assert row["requirement_summary"]["confirmed"] == len(reqs)
    assert row["last_activity_at"]


def test_overview_updates_with_review_actions(api, generated, reviewers):
    """评审推进后条目状态与汇总同步更新(#309 单步: 裁定通过即 passed)。"""
    pid, reqs = generated
    _confirm_all(api, pid, reqs)
    api.post(f"/api/projects/{pid}/review/submit")

    seca = _client(api, "seca_u")
    resp = seca.post(f"/api/projects/{pid}/review/decide",
                     json={"conclusion": "approve", "comment": "通过"})
    assert resp.status_code == 200, resp.text

    rows = api.get("/api/reviews").json()
    assert len(rows) == 1
    row = rows[0]
    assert row["gate_status"] == "passed"
    assert row["status_verb"] == "评审通过"
    assert row["requirement_summary"]["reviewed"] == len(reqs)
    assert row["reviewer_name"] and row["final_reviewer_name"]


def test_overview_data_permission(api, generated):
    """pm 仅见本人项目的评审; 全量可见角色见全部。"""
    sec = api_as(api, "sec_admin")
    # 另一位 pm 用户: 建自己的系统/评估并提交评审
    resp = sec.post("/api/admin/users", json={
        "username": "pm_b", "display_name": "开发乙", "role": "pm"})
    assert resp.status_code == 201, resp.text
    pm_b = login_as(TestClient(api.app), "pm_b")
    sid = create_system_api(pm_b, "乙的系统")["id"]
    pid_b = pm_b.post("/api/projects", json={"name": "乙的评估", "system_id": sid}).json()["id"]
    resp = pm_b.post(f"/api/projects/{pid_b}/features",
                     json=[f.model_dump() for f in demo_features()])
    assert resp.status_code == 200, resp.text
    assert pm_b.post(f"/api/projects/{pid_b}/generate", json={"skip_osv": True}).status_code == 200
    from conftest import satisfy_design_gate
    satisfy_design_gate(api, sid, pid_b)  # 库为共享内存库, 走 api 夹具的 session_factory
    reqs_b = pm_b.get(f"/api/projects/{pid_b}/requirements").json()
    pm_b.post(f"/api/projects/{pid_b}/requirements/batch-confirm",
              json={"req_ids": [r["req_id"] for r in reqs_b]})
    pm_b.post(f"/api/projects/{pid_b}/review/submit")

    # 第一位 pm(dev_admin): 只见本人项目 —— 乙提交的评审对 dev_admin 不可见
    rows = api.get("/api/reviews").json()
    assert all(r["project_id"] != pid_b for r in rows)

    # sec_admin(全量可见): 乙的评审可见
    rows_all = sec.get("/api/reviews").json()
    assert pid_b in {r["project_id"] for r in rows_all}
