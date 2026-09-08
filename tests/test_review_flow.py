# -*- coding: utf-8 -*-
"""评审动作流(#218, #309 单步化): 提交/批注/裁定/整改复审全链 + 哈希链防篡改 + 提交人约束。

复用 test_api_flow 的生成套路(离线)造需求; 评审动作经 API 端点联调。
单步评审: 提交(pm/dev_admin) → 安全管理员批注/裁定, 通过即 passed 并落盘。
"""
import pytest

from conftest import api_as, create_system_api, demo_features, login_as
from models import Project
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
    from conftest import satisfy_design_gate
    satisfy_design_gate(api, sid, pid)
    reqs = api.get(f"/api/projects/{pid}/requirements").json()
    assert reqs
    return pid, reqs


@pytest.fixture()
def reviewers(api):
    """安全管理员账号(经管理端创建, 种子默认口令可直接登录; #309 单步评审一名即可)。"""
    sec = api_as(api, "sec_admin")
    resp = sec.post("/api/admin/users", json={
        "username": "seca_u", "display_name": "seca_u", "role": "security_admin"})
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


def test_project_list_carries_review_gate_status(api, generated):
    """评审队列数据源: 项目列表带需求门禁状态(#219)。"""
    pid, reqs = generated
    rows = {r["id"]: r for r in api.get("/api/projects").json()}
    assert rows[pid]["review_gate_status"] is None  # 未提交
    _confirm_all(api, pid, reqs)
    api.post(f"/api/projects/{pid}/review/submit")
    rows = {r["id"]: r for r in api.get("/api/projects").json()}
    assert rows[pid]["review_gate_status"] == "in_review"


def test_security_admin_cannot_submit_or_withdraw(api, generated):
    """评估操作属开发侧(#309): 安全管理员提交/撤回评审一律 403(角色白名单)。"""
    pid, _ = generated
    seca = _client(api, "sec_admin")
    assert seca.post(f"/api/projects/{pid}/review/submit").status_code == 403
    assert seca.post(f"/api/projects/{pid}/review/withdraw").status_code == 403


def test_pm_cannot_review_own_submission(api, generated, reviewers):
    """pm 调评审批注/裁定一律 403(#216 角色白名单), 亦即不能自审。"""
    pid, _ = generated
    assert api.post(f"/api/projects/{pid}/review/submit").status_code == 200
    assert api.post(f"/api/projects/{pid}/review/requirements/SEC-X/annotate",
                    json={"disposition": "approve"}).status_code == 403
    assert api.post(f"/api/projects/{pid}/review/decide",
                    json={"conclusion": "approve"}).status_code == 403


def test_full_chain_submit_annotate_decide_pass(api, generated, reviewers):
    """提交 → 逐条批注 → 裁定 approve → passed; 需求全部 reviewed; 哈希链完整。"""
    pid, reqs = generated
    _confirm_all(api, pid, reqs)
    assert api.post(f"/api/projects/{pid}/review/submit").json()["status"] == "submitted"

    seca = _client(api, "seca_u")

    # 提交人自审拒绝: seca_u 不是提交人可批注; 提交人(dev_admin)已被角色层拦截
    for r in reqs:
        resp = seca.post(
            f"/api/projects/{pid}/review/requirements/{r['req_id']}/annotate",
            json={"disposition": "approve", "comment": "没问题"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["review_status"] == "reviewed"

    # 裁定 approve → 单步评审直接 passed(#309), 随裁定触发基线写回
    resp = seca.post(f"/api/projects/{pid}/review/decide",
                     json={"conclusion": "approve", "comment": "整体通过"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["gate_status"] == "passed"
    assert resp.json()["baseline_written"] is True

    after = api.get(f"/api/projects/{pid}/requirements").json()
    assert all(r["review_status"] == "reviewed" for r in after)

    state = api.get(f"/api/projects/{pid}/review/state").json()
    assert state["gate"]["status"] == "passed"
    assert state["gate"]["status_verb"] == "评审通过"
    assert state["chain_valid"] is True
    actions = [e["action"] for e in state["evidences"]]
    assert actions[0] == "submit" and actions[-1] == "approve"
    assert len(state["evidences"]) >= len(reqs) + 2  # submit + N 批注 + decide


def test_decide_without_annotate_passes_confirmed_requirements(api, generated, reviewers):
    """未逐条批注时裁定通过: 剩余已确认需求随门禁整体推为 reviewed(仅确认的落盘)。"""
    pid, reqs = generated
    _confirm_all(api, pid, reqs)
    api.post(f"/api/projects/{pid}/review/submit")
    seca = _client(api, "seca_u")
    resp = seca.post(f"/api/projects/{pid}/review/decide", json={"conclusion": "approve"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["gate_status"] == "passed"

    after = api.get(f"/api/projects/{pid}/requirements").json()
    assert all(r["review_status"] == "reviewed" for r in after)


def test_evidence_chain_tamper_detection(api, generated, reviewers):
    """哈希链 3 条记录完整性: 篡改任一字段校验失败(#218 验收)。"""
    pid, reqs = generated
    _confirm_all(api, pid, reqs)
    api.post(f"/api/projects/{pid}/review/submit")
    seca = _client(api, "seca_u")
    seca.post(f"/api/projects/{pid}/review/requirements/{reqs[0]['req_id']}/annotate",
              json={"disposition": "approve"})
    seca.post(f"/api/projects/{pid}/review/requirements/{reqs[1]['req_id']}/annotate",
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

    seca = _client(api, "seca_u")
    # 逐条退回第一条(需求状态 confirmed → rectifying)
    resp = seca.post(
        f"/api/projects/{pid}/review/requirements/{reqs[0]['req_id']}/annotate",
        json={"disposition": "return", "comment": "验收标准不完整"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["review_status"] == "rectifying"

    resp = seca.post(f"/api/projects/{pid}/review/decide",
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


def test_repeat_submit_and_repass_are_rejected(api, generated, reviewers):
    """审批中重复提交 409(安全管理员正在看); 通过后是终态, 重提 409(重评请新建轮次)。"""
    pid, reqs = generated
    _confirm_all(api, pid, reqs)
    api.post(f"/api/projects/{pid}/review/submit")
    # in_review 重复提交
    assert api.post(f"/api/projects/{pid}/review/submit").status_code == 409

    seca = _client(api, "seca_u")
    resp = seca.post(f"/api/projects/{pid}/review/decide", json={"conclusion": "approve"})
    assert resp.status_code == 200, resp.text
    # passed 是终态: 重复提交 409
    assert api.post(f"/api/projects/{pid}/review/submit").status_code == 409
    # 已通过的评审不能再次裁定
    resp = seca.post(f"/api/projects/{pid}/review/decide", json={"conclusion": "approve"})
    assert resp.status_code == 409, resp.text


def test_submitter_cannot_annotate_even_with_security_role(api, generated):
    """安全管理员不能提交/撤回评审(#309: 评估操作属开发侧, 角色层拦截)。"""
    pid, _ = generated
    sec = _client(api, "sec_admin")
    resp = sec.post(f"/api/projects/{pid}/review/submit")
    assert resp.status_code == 403, resp.text


def test_annotate_on_pending_gate_409(api, generated, reviewers):
    """未提交评审(无门禁)时批注 → 409。"""
    pid, reqs = generated
    seca = _client(api, "seca_u")
    resp = seca.post(
        f"/api/projects/{pid}/review/requirements/{reqs[0]['req_id']}/annotate",
        json={"disposition": "approve"})
    assert resp.status_code == 409, resp.text


def test_unknown_disposition_rejected(api, generated, reviewers):
    pid, reqs = generated
    api.post(f"/api/projects/{pid}/review/submit")
    seca = _client(api, "seca_u")
    resp = seca.post(
        f"/api/projects/{pid}/review/requirements/{reqs[0]['req_id']}/annotate",
        json={"disposition": "nonsense"})
    assert resp.status_code == 409, resp.text


# ── 基线写回(#225, #309 起随裁定 approve 触发) ──────────


def test_decide_approve_writes_back_baseline_with_level_confirmation(api, generated, reviewers):
    """评审通过 → 基线写回 + 履历; 备案级与评估级不一致 → 挂级别变更确认待办。"""
    sec = api_as(api, "sec_admin")
    pid, reqs = generated
    _confirm_all(api, pid, reqs)
    assert api.post(f"/api/projects/{pid}/review/submit").json()["status"] == "submitted"
    # 给项目挂定级问卷(评估建议级=二级), 系统备案级=三级 → 不一致
    db = api.session_factory()
    try:
        from models import GradingSurvey, System
        project = db.query(Project).get(pid) if hasattr(Project, "query") else db.get(Project, pid)
        system = db.get(System, project.system_id)
        system.filing_id = _mk_filing(db)
        db.add(GradingSurvey(project_id=pid, suggested_level="二级", final_level="二级"))
        db.commit()
        system_id = system.id
    finally:
        db.close()

    seca = _client(api, "seca_u")
    for r in reqs:
        seca.post(f"/api/projects/{pid}/review/requirements/{r['req_id']}/annotate",
                  json={"disposition": "approve"})
    resp = seca.post(f"/api/projects/{pid}/review/decide", json={"conclusion": "approve"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["baseline_written"] is True

    # 系统详情: 基线写回 + 待办挂起
    detail = sec.get(f"/api/systems/{system_id}").json()
    baseline = detail["baseline"]
    assert baseline is not None and baseline["source_project_id"] == pid
    assert baseline["summary"]["data_assets"] >= 0
    assert baseline["pending_level_confirmation"] == {
        "suggested_level": "二级", "filing_level": "三级", "project_id": pid}
    assert any("评审通过写回基线" in h["summary"] for h in detail["baseline_histories"])

    # 级别确认: 采纳评估建议 → 备案级被覆盖, 待办清除, 履历留痕
    resp = sec.post(f"/api/systems/{system_id}/baseline/confirm-level",
                    json={"decision": "adopt_suggested"})
    assert resp.status_code == 200, resp.text
    detail = sec.get(f"/api/systems/{system_id}").json()
    assert detail["baseline"]["pending_level_confirmation"] is None
    assert detail["filing_level"] == "二级"
    assert any("级别变更" in h["summary"] for h in detail["baseline_histories"])


def _mk_filing(db):
    from models import Filing
    filing = Filing(name=f"写回备案{db.query(Filing).count() + 1}", code=f"BA-WB-{db.query(Filing).count() + 1}", level="三级")
    db.add(filing)
    db.flush()
    return filing.id


def test_keep_filing_decision_leaves_trace(api, generated, reviewers):
    """维持备案级留痕: 待办清除、备案级不变、履历记录。"""
    sec = api_as(api, "sec_admin")
    pid, reqs = generated
    _confirm_all(api, pid, reqs)
    assert api.post(f"/api/projects/{pid}/review/submit").json()["status"] == "submitted"
    db = api.session_factory()
    try:
        from models import Filing, GradingSurvey, System
        project = db.get(Project, pid)
        system = db.get(System, project.system_id)
        filing = Filing(name="维持备案", code="BA-KEEP", level="三级")
        db.add(filing)
        db.flush()
        system.filing_id = filing.id
        db.add(GradingSurvey(project_id=pid, suggested_level="一级", final_level="一级"))
        db.commit()
        system_id = system.id
    finally:
        db.close()

    seca = _client(api, "seca_u")
    for r in reqs:
        seca.post(f"/api/projects/{pid}/review/requirements/{r['req_id']}/annotate",
                  json={"disposition": "approve"})
    resp = seca.post(f"/api/projects/{pid}/review/decide", json={"conclusion": "approve"})
    assert resp.status_code == 200, resp.text

    resp = sec.post(f"/api/systems/{system_id}/baseline/confirm-level",
                    json={"decision": "keep_filing", "note": "备案数据暂不动"})
    assert resp.status_code == 200, resp.text
    detail = sec.get(f"/api/systems/{system_id}").json()
    assert detail["baseline"]["pending_level_confirmation"] is None
    assert detail["filing_level"] == "三级"
    assert any("维持备案定级" in h["summary"] for h in detail["baseline_histories"])


def test_inherited_baseline_prefills_new_round_after_writeback(api, generated, reviewers):
    """#224+225 闭环: 评审通过写回基线后, 新建轮次自动预填基线数据。"""
    pid, reqs = generated
    _confirm_all(api, pid, reqs)
    db = api.session_factory()
    try:
        from models import DataTable, DataAsset  # noqa: F401
        from models import System as SystemModel
        project = db.get(Project, pid)
        system = db.get(SystemModel, project.system_id)
        system_id = system.id
    finally:
        db.close()
    # 本轮追加一条资产(向导 Step4 保存端点, 整卷替换语义): 提交评审后内容锁定,
    # 须在提交前写入; C3 资产须带数据字典表, 否则设计门禁拦截提交
    ws_now = api.get(f"/api/projects/{pid}/wizard-state").json()
    resp = api.post(f"/api/projects/{pid}/data-assets", json=ws_now["data_assets"] + [{
        "uid": "asset-wb-1", "name": "客户信息", "data_type": "business_data",
        "classification": "3级_C2主要信息", "is_pii": True, "is_sensitive_pii": False,
        "storage_envs": ["db"], "cross_border_transfer": False,
        "tables": [{"table_name": "customer_info", "fields": []}],
    }])
    assert resp.status_code == 200, resp.text
    assert api.post(f"/api/projects/{pid}/review/submit").json()["status"] == "submitted"

    seca = _client(api, "seca_u")
    for r in reqs:
        seca.post(f"/api/projects/{pid}/review/requirements/{r['req_id']}/annotate",
                  json={"disposition": "approve"})
    resp = seca.post(f"/api/projects/{pid}/review/decide", json={"conclusion": "approve"})
    assert resp.status_code == 200, resp.text

    # 新一轮评估 → 基线预填
    second = api.post("/api/projects", json={"name": "继承轮", "system_id": system_id}).json()
    ws = api.get(f"/api/projects/{second['id']}/wizard-state").json()
    assert [a["name"] for a in ws["data_assets"]] == ["交易流水", "客户信息"]


def test_review_sheet_export(api, generated, reviewers):
    """#230 评审表: 门禁推进后导出 Word, 含门禁状态与签字栏; 未提交 409。"""
    pid, reqs = generated
    # 未提交 → 409
    assert api.get(f"/api/projects/{pid}/review/export/review-sheet").status_code == 409

    _confirm_all(api, pid, reqs)
    assert api.post(f"/api/projects/{pid}/review/submit").json()["status"] == "submitted"
    seca = _client(api, "seca_u")
    for r in reqs:
        seca.post(f"/api/projects/{pid}/review/requirements/{r['req_id']}/annotate",
                  json={"disposition": "approve"})
    resp = seca.post(f"/api/projects/{pid}/review/decide", json={"conclusion": "approve"})
    assert resp.status_code == 200, resp.text

    resp = api.get(f"/api/projects/{pid}/review/export/review-sheet")
    assert resp.status_code == 200, resp.text
    assert resp.content[:2] == b"PK"  # docx = zip
    # docx 内正文含关键字段
    import io
    import zipfile
    from lxml import etree  # noqa: F401  (确保依赖在场, 与 doc_export 同源)
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
    assert "项目安全评审表" in xml
    assert "评审通过" in xml
    assert "评审动作留痕" in xml
    assert "评审意见与签字栏" in xml
    assert "项目经理" in xml and "安全管理员" in xml
