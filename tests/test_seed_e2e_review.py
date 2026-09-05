# -*- coding: utf-8 -*-
"""种子项目全流程 E2E 验收(#231): v3.0 评审闭环端到端收口。

链路: 种子项目 → 提交 → blocked(缺责任人确认) → 补齐 → 复提交 → 评审退回 1 条
→ 整改 → 复审通过 → 系统基线写回。权限断言: pm 调评审接口 403; auditor 写 403;
pm 不能自审。回归底线: 规则引擎测试全绿(全仓 pytest 保证)。
"""
import pytest

from conftest import api_as, login_as
from fastapi.testclient import TestClient
from services.auth_service import SEED_DEFAULT_PASSWORD
from services.seed_data import seed_demo_project


@pytest.fixture()
def seeded_api(api):
    """种子项目(个人网银系统) + 评审员/负责人/审计账号。"""
    db = api.session_factory()
    try:
        project = seed_demo_project(db)
        pid = project.id
        system_id = project.system_id
    finally:
        db.close()
    # 种子只造输入; 经真实管线生成需求与产物(#231 验收要求全流程真实走通)
    resp = api.post(f"/api/projects/{pid}/generate", json={"skip_osv": True})
    assert resp.status_code == 200, resp.text
    assert (api.get(f"/api/projects/{pid}").json()["system_id"]) == system_id
    sec = api_as(api, "sec_admin")
    for username, role in (("e2e_reviewer", "security_reviewer"),
                           ("e2e_lead", "security_lead"),
                           ("e2e_auditor", "auditor")):
        resp = sec.post("/api/admin/users", json={
            "username": username, "display_name": username, "role": role})
        assert resp.status_code == 201, resp.text
    return pid


def _client(api, username: str) -> TestClient:
    return login_as(TestClient(api.app), username)


def _confirm_all(api, pid: int) -> None:
    reqs = api.get(f"/api/projects/{pid}/requirements").json()
    assert reqs
    ids = [r["req_id"] for r in reqs]
    resp = api.post(f"/api/projects/{pid}/requirements/batch-confirm",
                    json={"req_ids": ids})
    assert resp.status_code == 200, resp.text
    assert resp.json()["confirmed"] == len(ids)


def test_full_review_loop_e2e(api, seeded_api):
    """提交→blocked→补齐→复审→退回整改→复审通过→基线写回 全链。"""
    pid = seeded_api
    sec = api_as(api, "sec_admin")
    reviewer = _client(api, "e2e_reviewer")
    lead = _client(api, "e2e_lead")

    # ── 1. 首次提交: 需求门禁 blocked(缺责任人确认) ──
    body = api.post(f"/api/projects/{pid}/review/submit").json()
    assert body["status"] == "blocked", body
    assert body["missing"], "blocked 契约必须给出缺项清单"

    # ── 2. 补齐确认后复提交 → in_review ──
    _confirm_all(api, pid)
    body = api.post(f"/api/projects/{pid}/review/submit").json()
    assert body["status"] == "submitted", body
    state = api.get(f"/api/projects/{pid}/review/state").json()
    assert state["gate"]["status"] == "in_review"
    assert state["chain_valid"] is True

    # ── 3. 评审员退回 1 条 → rectifying, 整体裁定 request_change ──
    reqs = api.get(f"/api/projects/{pid}/requirements").json()
    returned = reqs[0]
    resp = reviewer.post(
        f"/api/projects/{pid}/review/requirements/{returned['req_id']}/annotate",
        json={"disposition": "return", "comment": "验收标准需补充量化指标"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["review_status"] == "rectifying"
    resp = reviewer.post(f"/api/projects/{pid}/review/decide",
                         json={"conclusion": "request_change", "comment": "补充后重提"})
    assert resp.status_code == 200
    assert resp.json()["gate_status"] == "rectifying"

    # ── 4. PM 整改 → 重新确认 → 重新提交 ──
    resp = api.post(f"/api/projects/{pid}/requirements/{returned['req_id']}/confirm")
    assert resp.status_code == 200
    assert resp.json()["review_status"] == "confirmed"
    resp = api.post(f"/api/projects/{pid}/review/submit")
    assert resp.json()["status"] == "submitted"

    # ── 5. 复审: 逐条通过 → approve → 终审 → passed ──
    reqs = api.get(f"/api/projects/{pid}/requirements").json()
    for r in reqs:
        resp = reviewer.post(
            f"/api/projects/{pid}/review/requirements/{r['req_id']}/annotate",
            json={"disposition": "approve", "comment": "整改到位"})
        assert resp.status_code == 200
    resp = reviewer.post(f"/api/projects/{pid}/review/decide",
                         json={"conclusion": "approve"})
    assert resp.status_code == 200
    resp = lead.post(f"/api/projects/{pid}/review/finalize",
                     json={"comment": "复审通过, 同意归档"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["gate_status"] == "passed"

    # ── 6. 需求全部 reviewed; 哈希链完整 ──
    after = api.get(f"/api/projects/{pid}/requirements").json()
    assert all(r["review_status"] == "reviewed" for r in after)
    state = api.get(f"/api/projects/{pid}/review/state").json()
    assert state["chain_valid"] is True
    actions = [e["action"] for e in state["evidences"]]
    assert actions.count("submit") == 2  # 首提 + 整改重提

    # ── 7. 系统基线写回 + 履历(种子系统挂靠了备案, 评估定级一致则无级别待办) ──
    system_id = api.get(f"/api/projects/{pid}").json()["system_id"]
    detail = sec.get(f"/api/systems/{system_id}").json()
    assert detail["baseline"] is not None
    assert detail["baseline"]["source_project_id"] == pid
    assert any("终审通过写回基线" in h["summary"] for h in detail["baseline_histories"])

    # ── 8. 写回后新建轮次: 基线预填(#224 闭环) ──
    nxt = api.post("/api/projects", json={
        "name": "个人网银 第二轮", "system_id": system_id}).json()
    ws = api.get(f"/api/projects/{nxt['id']}/wizard-state").json()
    assert isinstance(ws["data_assets"], list)

    # ── 9. 评审表导出(#230 收尾) ──
    resp = api.get(f"/api/projects/{pid}/review/export/review-sheet")
    assert resp.status_code == 200 and resp.content[:2] == b"PK"


def test_permission_assertions_pm_auditor(api, seeded_api):
    """权限断言: pm 评审动作 403; auditor 任何写 403; 提交人不能批注。"""
    pid = seeded_api
    sec = api_as(api, "sec_admin")
    _client(api, "e2e_reviewer")
    auditor = _client(api, "e2e_auditor")

    # auditor 全量可见但写一律 403
    assert auditor.get(f"/api/projects/{pid}/review/state").status_code == 200
    assert auditor.post(f"/api/projects/{pid}/review/submit").status_code == 403
    assert auditor.post(f"/api/projects/{pid}/review/decide",
                        json={"conclusion": "approve"}).status_code == 403
    assert auditor.post(f"/api/projects/{pid}/review/finalize", json={}).status_code == 403
    assert auditor.post("/api/systems", json={"name": "x"}).status_code == 403
    assert auditor.post("/api/admin/users", json={
        "username": "nope", "display_name": "n", "role": "pm"}).status_code == 403

    # pm 提交后不能自审(角色白名单与服务层双重拦截)
    _confirm_all(api, pid)
    assert api.post(f"/api/projects/{pid}/review/submit").json()["status"] == "submitted"
    reqs = api.get(f"/api/projects/{pid}/requirements").json()
    assert api.post(
        f"/api/projects/{pid}/review/requirements/{reqs[0]['req_id']}/annotate",
        json={"disposition": "approve"}).status_code == 403
    assert api.post(f"/api/projects/{pid}/review/decide",
                    json={"conclusion": "approve"}).status_code == 403
    assert api.post(f"/api/projects/{pid}/review/finalize", json={}).status_code == 403

    # 耗时埋点报表可输出(#229 验收)
    existing = api.get(f"/api/projects/{pid}/features").json()
    resp = api.post(f"/api/projects/{pid}/features?duration_seconds=99",
                    json=existing[:1] + [{"uid": "feat-metric-1", "name": "埋点探针功能",
                                          "module": "用户中心",
                                          "categories": ["auth_login"]}])
    assert resp.status_code == 200
    report = sec.get("/api/admin/step-metrics",
                     params={"project_id": pid}).json()
    assert any(s["step"] == "features" and s["avg_seconds"] == 99.0
               for s in report["steps"])


def test_migrated_accounts_login_and_permissions(api):
    """存量账号升级后可登录且权限不回退(#216 回归底线)。"""
    for username, role in (("dev_admin", "pm"), ("sec_admin", "security_lead")):
        resp = TestClient(api.app).post("/api/auth/login", json={
            "username": username, "password": SEED_DEFAULT_PASSWORD})
        assert resp.status_code == 200
        assert resp.json()["role"] == role
