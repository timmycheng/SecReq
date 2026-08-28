# -*- coding: utf-8 -*-
"""改造验收用例(批次2): 门禁硬校验、RBAC、哈希链。

对应《改造 Prompt》第四部分验收标准:
5. 需求门禁在 critical 需求未指定责任人时返回 blocked 且 missing 准确;
6. pm 调用审核接口 403; auditor 任何 POST 403;
7. ReviewEvidence 连续 3 条动作后 curr_hash 与链上前序记录一致;
   另覆盖: 两步签核、立项/设计门禁正反向、409 阻断响应口径。
"""
import pytest

from conftest import add_base_project, api_as
from models import (
    DataAsset, GradingSurvey, PlatformUser, ReviewEvidence, SecurityRequirement,
    init_db, make_engine,
)
from rules import RuleEngine
from rules.context import RequirementContext
from services import gate_service
from services.gate_service import (
    GateActionError, append_evidence, evaluate_gate, evidence_hash,
    finalize_gate, get_or_create_gate, review_gate, submit_gate, verify_chain,
)


# ── 服务层门禁硬校验 ─────────────────────────────────────

def _fresh_session():
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    from sqlalchemy.orm import sessionmaker
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()


def _users(session):
    """种子用户 → {username: PlatformUser}。"""
    from services.auth_service import SEED_USERS, ensure_seed_users
    ensure_seed_users(session)
    rows = session.query(PlatformUser).all()
    by_name = {u.username: u for u in rows}
    assert set(by_name) == {u["username"] for u in SEED_USERS}
    return by_name


def _seeded_full_project(session):
    """种子项目 + 全量需求(离线规则引擎), 用于门禁场景。"""
    from services.seed_data import seed_demo_project
    project = seed_demo_project(session)
    RuleEngine.load().generate_and_save(
        RequirementContext.from_db(session, project.id), session)
    return project


def test_requirement_gate_blocked_until_critical_owner_set():
    session = _fresh_session()
    project = _seeded_full_project(session)
    users = _users(session)

    check = evaluate_gate(session, project.id, "requirement")
    assert check["status"] == "blocked"
    assert any("未指定责任人" in m for m in check["missing"]), check["missing"]

    # 全部 critical 指定责任人后放行
    for req in session.query(SecurityRequirement).filter_by(
            project_id=project.id, priority="critical"):
        req.owner = "李开发"
    session.commit()
    check = evaluate_gate(session, project.id, "requirement")
    assert check == {"status": "passed", "missing": []}

    gate = submit_gate(session, project.id, "requirement", users["pm_wang"])
    assert gate.status == "in_review" and gate.version_hash
    session.close()


def test_requirement_gate_blocks_without_requirements():
    session = _fresh_session()
    project = add_base_project(session)
    session.commit()
    check = evaluate_gate(session, project.id, "requirement")
    assert check["status"] == "blocked"
    assert any("尚未生成任何安全需求" in m for m in check["missing"])
    session.close()


def test_initiation_gate_requires_survey_and_regulatory_confirm():
    session = _fresh_session()
    project = _seeded_full_project(session)

    # 无问卷 → blocked
    survey = session.query(GradingSurvey).filter_by(project_id=project.id).first()
    session.delete(survey)
    session.commit()
    check = evaluate_gate(session, project.id, "initiation")
    assert check["status"] == "blocked"
    assert any("定级问卷" in m for m in check["missing"])

    # 恢复问卷 → 报送未确认仍 blocked, missing 列出具体需求号
    session.add(GradingSurvey(
        project_id=project.id, suggested_level="三级", final_level="三级", answers_json=[]))
    session.commit()
    check = evaluate_gate(session, project.id, "initiation")
    assert check["status"] == "blocked"
    assert any(m.startswith("监管报送需求 SEC-REG-") for m in check["missing"])

    # 全部确认 → passed
    for req in session.query(SecurityRequirement).filter_by(
            project_id=project.id, category="监管报送"):
        req.reg_confirmed = True
    session.commit()
    assert evaluate_gate(session, project.id, "initiation")["status"] == "passed"
    session.close()


def test_design_gate_requires_sbom_and_level_and_sod_rectification():
    session = _fresh_session()
    project = _seeded_full_project(session)

    # 种子项目存在 SoD 冲突: 移除整改需求后设计门禁必须阻断
    for req in session.query(SecurityRequirement).filter_by(
            project_id=project.id, template_id="SEC-V4-003"):
        session.delete(req)
    session.commit()
    check = evaluate_gate(session, project.id, "design")
    assert check["status"] == "blocked"
    assert any("SoD 冲突" in m for m in check["missing"]), check["missing"]

    # 重新生成整改需求(SEC-V4-003) + 数据字典分级齐全 → 放行
    RuleEngine.load().generate_and_save(
        RequirementContext.from_db(session, project.id), session)
    for asset in session.query(DataAsset).filter_by(project_id=project.id):
        assert gate_service.C.level_rank(asset.classification) > 0
    assert evaluate_gate(session, project.id, "design")["status"] == "passed"
    session.close()


def test_submit_blocked_returns_block_payload():
    """硬校验: 阻断在接口层, GateActionError 承载 409 语义。"""
    session = _fresh_session()
    project = add_base_project(session)
    session.commit()
    users = _users(session)
    with pytest.raises(GateActionError) as excinfo:
        submit_gate(session, project.id, "design", users["pm_wang"])
    assert "禁止提交" in str(excinfo.value)

    # POC 门禁本期只留数据结构
    check = evaluate_gate(session, project.id, "poc")
    assert check["status"] == "not_available"
    session.close()


# ── 验收7: 哈希链 ─────────────────────────────────────────

def _set_critical_owners(session, project_id: int, owner: str = "李开发") -> None:
    for req in session.query(SecurityRequirement).filter_by(
            project_id=project_id, priority="critical"):
        req.owner = owner
    session.commit()


def test_evidence_hash_chain_over_three_actions():
    session = _fresh_session()
    project = _seeded_full_project(session)
    users = _users(session)
    _set_critical_owners(session, project.id)

    pm, reviewer, lead = users["pm_wang"], users["sec_chen"], users["sec_zhao"]
    gate = submit_gate(session, project.id, "requirement", pm)         # 动作1 submit
    review_gate(session, gate.id, reviewer, "approve", "需求覆盖完整")   # 动作2 approve
    finalize_gate(session, gate.id, lead, "sign", "同意放行")           # 动作3 sign

    rows = (
        session.query(ReviewEvidence)
        .filter_by(gate_id=gate.id)
        .order_by(ReviewEvidence.id)
        .all()
    )
    assert [r.action for r in rows] == ["submit", "approve", "sign"]
    assert rows[0].prev_hash == gate_service.GENESIS_HASH
    for prev_row, curr in zip(rows, rows[1:]):
        assert curr.prev_hash == prev_row.curr_hash, "链上前序哈希必须一致"
    for row in rows:
        assert evidence_hash(row, row.prev_hash) == row.curr_hash

    result = verify_chain(session, gate.id)
    assert result == {"valid": True, "count": 3, "broken_at": None}
    session.close()


def test_chain_detects_tampering():
    session = _fresh_session()
    project = _seeded_full_project(session)
    users = _users(session)
    _set_critical_owners(session, project.id)
    pm, reviewer = users["pm_wang"], users["sec_chen"]
    gate = submit_gate(session, project.id, "requirement", pm)
    review_gate(session, gate.id, reviewer, "approve", "ok")

    rows = (
        session.query(ReviewEvidence)
        .filter_by(gate_id=gate.id)
        .order_by(ReviewEvidence.id)
        .all()
    )
    rows[0].comment = "被篡改的意见"
    result = verify_chain(session, gate.id)
    assert result["valid"] is False and result["broken_at"] == rows[0].id
    session.close()


# ── 两步签核状态机 ────────────────────────────────────────

def test_two_step_signoff_constraints():
    session = _fresh_session()
    project = _seeded_full_project(session)
    users = _users(session)
    pm, reviewer, lead = users["pm_wang"], users["sec_chen"], users["sec_zhao"]
    _set_critical_owners(session, project.id)

    gate = submit_gate(session, project.id, "requirement", pm)

    # 负责人不能越过评审员直接终审
    with pytest.raises(GateActionError) as excinfo:
        finalize_gate(session, gate.id, lead, "sign", "抢跑")
    assert "两步签核" in str(excinfo.value)

    # 评审员通过后 → 待终审
    review_gate(session, gate.id, reviewer, "approve", "通过")
    assert gate.reviewer_conclusion == "approve" and gate.status == "in_review"

    # 终审人不得与第一步评审人相同(评审员提交则由负责人终审, 反之亦然)
    with pytest.raises(GateActionError):
        finalize_gate(session, gate.id, reviewer, "sign", "自审自签")

    finalize_gate(session, gate.id, lead, "sign", "终审通过")
    assert gate.status == "passed"
    session.close()


def test_pm_cannot_review_own_submission():
    session = _fresh_session()
    project = _seeded_full_project(session)
    users = _users(session)
    _set_critical_owners(session, project.id)
    gate = submit_gate(session, project.id, "requirement", users["pm_wang"])
    # 直接以服务层验证回避规则(接口层角色拦截见 API 用例)
    with pytest.raises(GateActionError):
        review_gate(session, gate.id, users["pm_wang"], "approve", "自己审自己")
    session.close()


# ── 验收6: API 层 RBAC ───────────────────────────────────

@pytest.fixture()
def gate_env(api):
    """通过 API 构造种子项目并生成基线; 返回 (client, project_id, 用户名映射)。"""
    resp = api.post("/api/projects", json={
        "name": "门禁验收项目", "code": "PRJ-GATE-1", "type": "web",
        "user_scale": "over_1m", "deploy_env": ["private_cloud"],
        "compliance_targets": ["djcp_l3"],
    })
    assert resp.status_code == 201, resp.text
    pid = resp.json()["id"]

    api.post(f"/api/projects/{pid}/survey", json={
        "answers": [
            {"question_id": "Q1", "option_id": "C"},
            {"question_id": "Q2", "option_id": "C"},
            {"question_id": "Q3", "option_id": "C"},
            {"question_id": "Q4", "option_id": "D"},
            {"question_id": "Q5", "option_id": "B"},
        ],
        "final_level": "三级", "manual_adjust_note": "确认三级",
    })
    api.post(f"/api/projects/{pid}/data-assets", json=[{
        "name": "账户数据", "data_type": "financial_account",
        "classification": "4级_C3鉴别信息", "is_pii": True, "is_sensitive_pii": True,
        "storage_envs": ["db"], "tables": [{"table_name": "t_acc", "fields": []}],
    }])
    resp = api.post(f"/api/projects/{pid}/generate", json={"skip_osv": True})
    assert resp.status_code == 200, resp.text
    for r in api.get(f"/api/projects/{pid}/requirements").json():
        if r["priority"] == "critical":
            resp = api.post(f"/api/projects/{pid}/requirements/{r['req_id']}/owner",
                            json={"owner": "王建国"})
            assert resp.status_code == 200
    return api, pid


def test_api_pm_cannot_call_review_endpoints(gate_env):
    api, pid = gate_env

    # pm 提交可以, 审核 403
    resp = api.post(f"/api/projects/{pid}/gates/requirement/submit")
    assert resp.status_code == 200, resp.text
    gate_id = resp.json()["id"]

    as_pm = api_as(api, "pm_wang")
    resp = as_pm.post(f"/api/projects/{pid}/gates/{gate_id}/review",
                      json={"action": "approve", "opinion": "试越权"})
    assert resp.status_code == 403
    resp = as_pm.post(f"/api/projects/{pid}/gates/{gate_id}/final",
                      json={"action": "sign", "opinion": "试越权"})
    assert resp.status_code == 403


def test_api_auditor_any_post_forbidden(gate_env):
    api, pid = gate_env
    as_auditor = api_as(api, "audit_sun")

    # 业务写接口
    assert as_auditor.post("/api/projects", json={
        "name": "x", "code": "PRJ-AUD", "type": "web", "user_scale": "under_1k",
    }).status_code == 403
    assert as_auditor.post(f"/api/projects/{pid}/generate").status_code == 403
    assert as_auditor.post(f"/api/projects/{pid}/gates/requirement/submit").status_code == 403
    assert as_auditor.post(
        f"/api/projects/{pid}/requirements/SEC-V1-001/owner", json={"owner": "x"},
    ).status_code == 403
    # 只读不受限
    assert as_auditor.get(f"/api/projects/{pid}/gates").status_code == 200
    assert as_auditor.get(f"/api/projects/{pid}/requirements").status_code == 200


def test_api_developer_cannot_review_but_can_write_wizard(gate_env):
    api, pid = gate_env
    as_dev = api_as(api, "dev_li")
    api.post(f"/api/projects/{pid}/gates/requirement/submit")
    resp = api.post(f"/api/projects/{pid}/gates/requirement/submit")  # 幂等重复提交
    assert resp.status_code == 200
    gate_id = resp.json()["id"]
    assert as_dev.post(f"/api/projects/{pid}/gates/{gate_id}/review",
                       json={"action": "approve", "opinion": "越权"}).status_code == 403
    # 开发中心可以维护向导数据
    assert as_dev.post(f"/api/projects/{pid}/features", json=[]).status_code == 200


def test_api_gate_blocked_payload_and_full_review_flow(gate_env):
    api, pid = gate_env
    # 立项门禁: 报送未确认 → 409 + blocked 口径
    resp = api.post(f"/api/projects/{pid}/gates/initiation/submit")
    assert resp.status_code == 409
    body = resp.json()
    assert body["gate"] == "initiation" and body["status"] == "blocked"
    assert isinstance(body["missing"], list) and body["missing"]

    # 确认全部报送事项 → 提交成功
    reqs = api.get(f"/api/projects/{pid}/requirements").json()
    reg = [r for r in reqs if r["category"] == "监管报送"]
    assert reg, "三级项目应触发报送类需求"
    for r in reg:
        resp = api.post(f"/api/projects/{pid}/requirements/{r['req_id']}/confirm")
        assert resp.status_code == 200
    resp = api.post(f"/api/projects/{pid}/gates/initiation/submit")
    assert resp.status_code == 200
    initiation_id = resp.json()["id"]

    # 两步签核走查: 评审员通过 → 负责人终审
    as_reviewer = api_as(api, "sec_chen")
    as_lead = api_as(api, "sec_zhao")
    resp = as_reviewer.post(f"/api/projects/{pid}/gates/{initiation_id}/review",
                            json={"action": "approve", "opinion": "报送事项齐备"})
    assert resp.status_code == 200
    # 负责人终审前不能通过评审员身份签核
    assert as_reviewer.post(f"/api/projects/{pid}/gates/{initiation_id}/final",
                            json={"action": "sign", "opinion": "越权"}).status_code == 403
    resp = as_lead.post(f"/api/projects/{pid}/gates/{initiation_id}/final",
                        json={"action": "sign", "opinion": "同意立项"})
    assert resp.status_code == 200 and resp.json()["status"] == "passed"

    # 留痕链可校验
    resp = api.get(f"/api/projects/{pid}/gates/{initiation_id}/evidence")
    actions = [e["action"] for e in resp.json()]
    assert actions == ["submit", "approve", "sign"]
    resp = api.get(f"/api/projects/{pid}/gates/{initiation_id}/evidence/verify")
    assert resp.json() == {"gate_id": initiation_id, "valid": True, "count": 3,
                           "broken_at": None}


def test_api_gate_submit_blocked_on_requirement_gate(gate_env):
    api, _ = gate_env
    # 新项目不带责任人 → 需求门禁阻断
    pid = api.post("/api/projects", json={
        "name": "阻断口径项目", "code": "PRJ-GATE-2", "type": "web",
        "user_scale": "over_1m",
    }).json()["id"]
    api.post(f"/api/projects/{pid}/survey", json={
        "answers": [{"question_id": "Q1", "option_id": "C"}]})
    api.post(f"/api/projects/{pid}/data-assets", json=[{
        "name": "账户数据", "data_type": "financial_account",
        "classification": "4级_C3鉴别信息", "is_pii": True, "is_sensitive_pii": True,
        "tables": [{"table_name": "t_acc", "fields": []}],
    }])
    api.post(f"/api/projects/{pid}/generate", json={"skip_osv": True})
    resp = api.post(f"/api/projects/{pid}/gates/requirement/submit")
    assert resp.status_code == 409
    body = resp.json()
    assert body["gate"] == "requirement" and body["status"] == "blocked"
    assert any("未指定责任人" in m for m in body["missing"])

    # 补齐责任人 → 通过
    reqs = api.get(f"/api/projects/{pid}/requirements").json()
    for r in reqs:
        if r["priority"] == "critical":
            resp = api.post(f"/api/projects/{pid}/requirements/{r['req_id']}/owner",
                            json={"owner": "王建国"})
            assert resp.status_code == 200
    assert api.post(f"/api/projects/{pid}/gates/requirement/submit").status_code == 200
    assert api_as(api, "audit_sun").get(f"/api/projects/{pid}/gates").status_code == 200


def test_api_version_hash_changes_with_data():
    """提交快照随交付物变化(抽验 version_hash 语义)。"""
    api = None
    from fastapi.testclient import TestClient
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    from sqlalchemy.orm import sessionmaker
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    from services.seed_data import seed_demo_project
    project = seed_demo_project(session)
    h1 = gate_service.compute_version_hash(session, project.id)
    asset = session.query(DataAsset).filter_by(project_id=project.id).first()
    asset.name = asset.name + "X"
    session.commit()
    h2 = gate_service.compute_version_hash(session, project.id)
    assert h1 != h2 and len(h1) == 64
    _ = TestClient, api
    session.close()
