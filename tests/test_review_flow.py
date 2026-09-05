# -*- coding: utf-8 -*-
"""评审动作流(#218): 提交/批注/裁定/终审/整改复审全链 + 哈希链防篡改 + 三人约束。

复用 test_api_flow 的生成套路(离线)造需求; 评审动作经 API 端点联调。
"""
import pytest

from conftest import api_as, create_system_api, demo_features, login_as
from services.review_service import verify_chain


@pytest.fixture()
def generated(api):
    """一个已生成需求的评估(离线管线), 返回 (pid, requirements)。"""
    sid = create_system_api(api, "评审系统")["id"]
    pid = api.post("/api/projects", json={
        "name": "评审项目", "system_id": sid}).json()["id"]
    resp = api.post(f"/api/projects/{pid}/features",
                    json=[f.model_dump() for f in demo_features()])
    assert resp.status_code == 200, resp.text
    gen = api.post(f"/api/projects/{pid}/generate", json={"skip_osv": True})
    assert gen.status_code == 200, gen.text
    reqs = api.get(f"/api/projects/{pid}/requirements").json()
    assert reqs
    return pid, reqs


@pytest.fixture()
def reviewers(api):
    """评审员与负责人账号(经管理端创建, 种子默认口令可直接登录)。"""
    sec = api_as(api, "sec_admin")
    for username, role in (("reviewer_u", "security_reviewer"), ("lead_u", "security_lead")):
        resp = sec.post("/api/admin/users", json={
            "username": username, "display_name": username, "role": role})
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
    assert resp.json()["confirmed"] == len(ids), resp.text


def test_submit_passes_stub_gate_before_220(api, generated):
    """门禁校验先桩后接(#220 未落地): 无注册检查时未确认需求也放行进评审。"""
    pid, reqs = generated
    resp = api.post(f"/api/projects/{pid}/review/submit")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "submitted"  # 门禁校验桩: 无注册检查即放行
    state = api.get(f"/api/projects/{pid}/review/state").json()
    assert state["gate"]["status"] == "in_review"
    assert state["gate"]["version_hash"]
    assert state["chain_valid"] is True
    assert state["evidences"][0]["action"] == "submit"


def test_pm_cannot_review_own_submission(api, generated):
    """pm 调评审批注/裁定/终审一律 403(#216 角色白名单), 亦即不能自审。"""
    pid, _ = generated
    assert api.post(f"/api/projects/{pid}/review/submit").status_code == 200
    assert api.post(f"/api/projects/{pid}/review/requirements/SEC-X/annotate",
                    json={"disposition": "approve"}).status_code == 403
    assert api.post(f"/api/projects/{pid}/review/decide",
                    json={"conclusion": "approve"}).status_code == 403
    assert api.post(f"/api/projects/{pid}/review/finalize",
                    json={}).status_code == 403


def test_full_chain_submit_approve_finalize(api, generated, reviewers):
    """提交 → 逐条批注 → 裁定 approve → 终审 → passed; 需求全部 reviewed; 哈希链完整。"""
    pid, reqs = generated
    _confirm_all(api, pid, reqs)
    assert api.post(f"/api/projects/{pid}/review/submit").json()["status"] == "submitted"

    reviewer = _client(api, "reviewer_u")
    lead = _client(api, "lead_u")

    # 提交人自审拒绝: reviewer_u 不是提交人可批注; 提交人(dev_admin)已被角色层拦截
    for r in reqs:
        resp = reviewer.post(
            f"/api/projects/{pid}/review/requirements/{r['req_id']}/annotate",
            json={"disposition": "approve", "comment": "没问题"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["review_status"] == "reviewed"

    # 裁定 approve → 待终审
    resp = reviewer.post(f"/api/projects/{pid}/review/decide",
                         json={"conclusion": "approve", "comment": "整体通过"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["gate_status"] == "in_review"
    state = api.get(f"/api/projects/{pid}/review/state").json()
    assert state["gate"]["status_verb"] == "评审员已通过, 待负责人终审"

    # 终审 → passed, 未批注的需求(如有)随终审整体推为 reviewed
    resp = lead.post(f"/api/projects/{pid}/review/finalize", json={"comment": "同意"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["gate_status"] == "passed"

    after = api.get(f"/api/projects/{pid}/requirements").json()
    assert all(r["review_status"] == "reviewed" for r in after)

    state = api.get(f"/api/projects/{pid}/review/state").json()
    assert state["gate"]["status"] == "passed"
    assert state["chain_valid"] is True
    actions = [e["action"] for e in state["evidences"]]
    assert actions[0] == "submit" and actions[-1] == "sign"
    assert len(state["evidences"]) >= len(reqs) + 3  # submit + N 批注 + decide + sign


def test_evidence_chain_tamper_detection(api, generated, reviewers):
    """哈希链 3 条记录完整性: 篡改任一字段校验失败(#218 验收)。"""
    pid, reqs = generated
    _confirm_all(api, pid, reqs)
    api.post(f"/api/projects/{pid}/review/submit")
    reviewer = _client(api, "reviewer_u")
    reviewer.post(f"/api/projects/{pid}/review/requirements/{reqs[0]['req_id']}/annotate",
                  json={"disposition": "approve"})
    reviewer.post(f"/api/projects/{pid}/review/requirements/{reqs[1]['req_id']}/annotate",
                  json={"disposition": "object", "comment": "描述需补充"})

    db = api.session_factory()
    try:
        from models import ReviewEvidence
        evidences = db.query(ReviewEvidence).order_by(ReviewEvidence.id).all()
        assert len(evidences) >= 3  # submit + 批注 + 异议 ≥ 3 条
        gate = _gate(db)
        assert verify_chain(db, gate) is True
        # 篡改一条历史意见 → 链校验失败
        evidences[1].comment = "被篡改的意见"
        db.commit()
        assert verify_chain(db, gate) is False
    finally:
        db.close()


def _gate(db):
    from models import ReviewGate
    return db.query(ReviewGate).first()


def test_request_change_rectify_and_resubmit_loop(api, generated, reviewers):
    """退回整改闭环: 裁定 request_change → rectifying → 整改确认 → 重新提交。"""
    pid, reqs = generated
    _confirm_all(api, pid, reqs)
    api.post(f"/api/projects/{pid}/review/submit")

    reviewer = _client(api, "reviewer_u")
    # 逐条退回第一条(需求状态 confirmed → rectifying)
    resp = reviewer.post(
        f"/api/projects/{pid}/review/requirements/{reqs[0]['req_id']}/annotate",
        json={"disposition": "return", "comment": "验收标准不完整"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["review_status"] == "rectifying"

    resp = reviewer.post(f"/api/projects/{pid}/review/decide",
                         json={"conclusion": "request_change", "comment": "补充后重提"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["gate_status"] == "rectifying"

    # 整改: pm 重新确认(状态机 reconfirm: rectifying → confirmed)
    resp = api.post(f"/api/projects/{pid}/requirements/{reqs[0]['req_id']}/confirm")
    assert resp.status_code == 200, resp.text
    assert resp.json()["review_status"] == "confirmed"

    # 重新提交 → in_review, 评审结论清空
    resp = api.post(f"/api/projects/{pid}/review/submit")
    assert resp.status_code == 200, resp.text
    state = api.get(f"/api/projects/{pid}/review/state").json()
    assert state["gate"]["status"] == "in_review"
    assert state["gate"]["reviewer_conclusion"] is None
    assert [e["action"] for e in state["evidences"]].count("submit") == 2
    assert state["chain_valid"] is True


def test_finalize_order_not_skippable(api, generated, reviewers):
    """两步签核顺序: 评审员未 approve 时终审 409; 审批中重复提交 409。"""
    pid, reqs = generated
    _confirm_all(api, pid, reqs)
    api.post(f"/api/projects/{pid}/review/submit")

    lead = _client(api, "lead_u")
    # 评审员未裁定 → 终审拒绝
    resp = lead.post(f"/api/projects/{pid}/review/finalize", json={})
    assert resp.status_code == 409, resp.text

    reviewer = _client(api, "reviewer_u")
    reviewer.post(f"/api/projects/{pid}/review/decide",
                  json={"conclusion": "approve"})
    # 评审员身份不能终审自己的裁定(三人约束: 评审员≠终审人)
    resp = reviewer.post(f"/api/projects/{pid}/review/finalize", json={})
    assert resp.status_code == 403, resp.text
    # lead 终审成功
    resp = lead.post(f"/api/projects/{pid}/review/finalize", json={"comment": "通过"})
    assert resp.status_code == 200, resp.text
    # passed 是终态: 重复提交 409(重评请新建评估轮次)
    resp = api.post(f"/api/projects/{pid}/review/submit")
    assert resp.status_code == 409, resp.text


def test_submitter_cannot_annotate_even_with_security_role(api, generated):
    """提交人自审拦截在角色之外仍然生效: security_lead 提交后不能自己批注。"""
    pid, reqs = generated
    _confirm_all(api, pid, reqs)
    sec = _client(api, "sec_admin")
    resp = sec.post(f"/api/projects/{pid}/review/submit")
    assert resp.status_code == 200, resp.text
    # sec_admin 是 security_lead, 角色白名单通过, 但提交人=自己 → 服务层 403
    resp = sec.post(
        f"/api/projects/{pid}/review/requirements/{reqs[0]['req_id']}/annotate",
        json={"disposition": "approve"})
    assert resp.status_code == 403, resp.text
    resp = sec.post(f"/api/projects/{pid}/review/decide", json={"conclusion": "approve"})
    assert resp.status_code == 403, resp.text


def test_annotate_on_pending_gate_409(api, generated, reviewers):
    """未提交评审(无门禁)时批注 → 409。"""
    pid, reqs = generated
    reviewer = _client(api, "reviewer_u")
    resp = reviewer.post(
        f"/api/projects/{pid}/review/requirements/{reqs[0]['req_id']}/annotate",
        json={"disposition": "approve"})
    assert resp.status_code == 409, resp.text


def test_unknown_disposition_rejected(api, generated, reviewers):
    pid, reqs = generated
    api.post(f"/api/projects/{pid}/review/submit")
    reviewer = _client(api, "reviewer_u")
    resp = reviewer.post(
        f"/api/projects/{pid}/review/requirements/{reqs[0]['req_id']}/annotate",
        json={"disposition": "nonsense"})
    assert resp.status_code == 409, resp.text
