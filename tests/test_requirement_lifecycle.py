# -*- coding: utf-8 -*-
"""需求评审生命周期(#217): 状态机合法/非法路径、流转留痕、存量数据迁移。

状态机: open → confirmed → reviewed(终态); confirmed → rectifying → 重新确认。
非法跳转(如 open 直接到 reviewed、reviewed 再流转)一律 409。
"""
import pytest

from conftest import create_system_api
from models import PlatformUser, RequirementTransition, SecurityRequirement
from services.requirement_lifecycle import (
    RequirementTransitionError, backfill_review_statuses, transition_requirement,
)


def _mk_req(project_id: int, req_id: str, **kw) -> SecurityRequirement:
    defaults = dict(
        project_id=project_id, req_id=req_id, template_id="T-1",
        title="需求", description="d", category="合规要求", priority="high",
        acceptance_criteria="ac", suggested_phase="design",
        source_entity_type="feature", source_entity_id=1, trigger_reason="r",
    )
    defaults.update(kw)
    return SecurityRequirement(**defaults)


def _operator(db) -> PlatformUser:
    """取(或建)一个操作人: session 夹具是纯净库, 不含种子用户。"""
    user = db.query(PlatformUser).filter_by(username="dev_admin").first()
    if user is None:
        user = PlatformUser(username="dev_admin", display_name="开发管理员", role="pm")
        db.add(user)
        db.flush()
    return user


# ── 状态机单测 ────────────────────────────────────────


def test_legal_paths_full_matrix(session):
    """全部合法路径: open→confirmed→reviewed / confirmed→rectifying→confirmed。"""
    from models import Project
    project = Project(name="状态机项目", code="PRJ-SM1", type="web")
    session.add(project)
    session.flush()
    req = _mk_req(project.id, "SEC-T-001")
    session.add(req)
    session.flush()
    user = _operator(session)

    assert req.review_status == "open"
    transition_requirement(session, req, "confirm", user)
    assert req.review_status == "confirmed"
    assert req.reg_confirmed is True and req.confirmed_by == user.display_name

    transition_requirement(session, req, "review_pass", user, opinion="通过")
    assert req.review_status == "reviewed"

    # reviewed 是终态: 任何动作都非法
    for action in ("confirm", "reconfirm", "review_pass", "request_change"):
        with pytest.raises(RequirementTransitionError):
            transition_requirement(session, req, action, user)


def test_request_change_then_reconfirm_loop(session):
    """退回整改闭环: confirmed → rectifying → 重新确认 → 可再次进入评审。"""
    from models import Project
    project = Project(name="整改项目", code="PRJ-SM2", type="web")
    session.add(project)
    session.flush()
    req = _mk_req(project.id, "SEC-T-002")
    session.add(req)
    session.flush()
    pm = _operator(session)

    transition_requirement(session, req, "confirm", pm)
    transition_requirement(session, req, "request_change", pm, opinion="描述不清")
    assert req.review_status == "rectifying"

    # rectifying 上直接评审通过 = 跳过整改确认, 非法
    with pytest.raises(RequirementTransitionError):
        transition_requirement(session, req, "review_pass", pm)

    transition_requirement(session, req, "reconfirm", pm, opinion="已补描述")
    assert req.review_status == "confirmed"
    transition_requirement(session, req, "review_pass", pm)
    assert req.review_status == "reviewed"


def test_confirm_idempotent_no_duplicate_record(session):
    """已确认需求重复确认幂等: 刷新确认口径, 不新增流转记录。"""
    from models import Project
    project = Project(name="幂等项目", code="PRJ-SM3", type="web")
    session.add(project)
    session.flush()
    req = _mk_req(project.id, "SEC-T-003")
    session.add(req)
    session.flush()
    user = _operator(session)

    assert transition_requirement(session, req, "confirm", user) is not None
    assert transition_requirement(session, req, "confirm", user) is None
    session.flush()  # autoflush=False, 统计前显式落
    assert session.query(RequirementTransition).filter_by(
        requirement_id=req.id).count() == 1


def test_unknown_action_rejected(session):
    from models import Project
    project = Project(name="未知动作项目", code="PRJ-SM4", type="web")
    session.add(project)
    session.flush()
    req = _mk_req(project.id, "SEC-T-004")
    session.add(req)
    session.flush()
    with pytest.raises(RequirementTransitionError):
        transition_requirement(session, req, "nonsense", _operator(session))


# ── 存量数据迁移 ──────────────────────────────────────


_LEGACY_REQ_DDL = """
    CREATE TABLE security_requirements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        req_id VARCHAR(40) NOT NULL,
        template_id VARCHAR(40) NOT NULL,
        title VARCHAR(300) NOT NULL,
        description TEXT NOT NULL,
        category VARCHAR(30) NOT NULL,
        priority VARCHAR(10) NOT NULL,
        asvs_ref VARCHAR(50),
        acceptance_criteria TEXT NOT NULL,
        suggested_phase VARCHAR(20) NOT NULL,
        source_entity_type VARCHAR(40) NOT NULL,
        source_entity_id INTEGER NOT NULL,
        source_entity_uid VARCHAR(64),
        source_label VARCHAR(200),
        trigger_reason TEXT NOT NULL,
        status VARCHAR(20),
        regulatory_ref JSON,
        owner VARCHAR(50),
        reg_confirmed BOOLEAN,
        confirmed_by VARCHAR(50),
        confirmed_at DATETIME
    )
"""


def test_backfill_review_statuses_mapping():
    """存量映射(#217): 真实补列路径 —— 旧表缺列 → 补列 NULL → 按规则回填; 幂等。

    reg_confirmed 或任务推进过(in_progress/done/risk_accepted) → confirmed; 其余 → open。
    """
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from models import init_db
    from services.classification_migration import ensure_schema_upgrade

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as conn:
        conn.execute(text(_LEGACY_REQ_DDL))
        conn.execute(text(
            "INSERT INTO security_requirements (project_id, req_id, template_id, title,"
            " description, category, priority, acceptance_criteria, suggested_phase,"
            " source_entity_type, source_entity_id, trigger_reason, status, reg_confirmed)"
            " VALUES (1, 'SEC-T-010', 'T', 'x', 'd', 'c', 'high', 'ac', 'design',"
            " 'feature', 1, 'r', 'open', 1),"
            " (1, 'SEC-T-011', 'T', 'x', 'd', 'c', 'high', 'ac', 'design',"
            " 'feature', 2, 'r', 'done', 0),"
            " (1, 'SEC-T-012', 'T', 'x', 'd', 'c', 'high', 'ac', 'design',"
            " 'feature', 3, 'r', 'risk_accepted', 0),"
            " (1, 'SEC-T-013', 'T', 'x', 'd', 'c', 'high', 'ac', 'design',"
            " 'feature', 4, 'r', 'open', 0)"))
    init_db(engine)
    added = ensure_schema_upgrade(engine)
    assert added == {"security_requirements": ["review_status"]}

    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db = factory()
    try:
        assert backfill_review_statuses(db) == 4
        db.commit()  # 调用方负责提交(main.py lifespan 同口径)
        rows = {r.req_id: r.review_status for r in db.query(SecurityRequirement).all()}
        assert rows == {"SEC-T-010": "confirmed", "SEC-T-011": "confirmed",
                        "SEC-T-012": "confirmed", "SEC-T-013": "open"}
        # 幂等: 无 NULL 行后不再改动
        assert backfill_review_statuses(db) == 0
    finally:
        db.close()


# ── 端点联测 ──────────────────────────────────────────


def _generated_project(api) -> tuple[int, list[dict]]:
    """经 API 生成一个带需求的项目(离线, 与 test_api_flow 同套路)。"""
    sid = create_system_api(api, "生命周期系统")["id"]
    pid = api.post("/api/projects", json={
        "name": "生命周期项目", "system_id": sid}).json()["id"]
    from conftest import demo_features
    resp = api.post(f"/api/projects/{pid}/features",
                    json=[f.model_dump() for f in demo_features()])
    assert resp.status_code == 200, resp.text
    gen = api.post(f"/api/projects/{pid}/generate", json={"skip_osv": True})
    assert gen.status_code == 200, gen.text
    reqs = api.get(f"/api/projects/{pid}/requirements").json()
    assert reqs
    return pid, reqs


def test_confirm_endpoint_writes_transition(api):
    """确认端点走状态机: 流转记录含动作/操作人/状态对; 重复确认不重复留痕。"""
    pid, reqs = _generated_project(api)
    target = reqs[0]
    assert target["review_status"] == "open"

    resp = api.post(f"/api/projects/{pid}/requirements/{target['req_id']}/confirm")
    assert resp.status_code == 200, resp.text
    assert resp.json()["review_status"] == "confirmed"

    transitions = api.get(
        f"/api/projects/{pid}/requirements/{target['req_id']}/transitions").json()
    assert len(transitions) == 1
    record = transitions[0]
    assert record["action"] == "confirm"
    assert record["from_status"] == "open" and record["to_status"] == "confirmed"
    assert record["operator_name"] == "开发管理员"
    assert record["created_at"]

    # 幂等确认: 状态与记录数都不变
    assert api.post(
        f"/api/projects/{pid}/requirements/{target['req_id']}/confirm").status_code == 200
    assert len(api.get(
        f"/api/projects/{pid}/requirements/{target['req_id']}/transitions").json()) == 1


def test_reviewed_requirement_confirm_rejected_409(api):
    """reviewed 终态再确认 → 409; open 需求直接请求评审动作类动作 → 409。"""
    pid, reqs = _generated_project(api)
    db = api.session_factory()
    try:
        target = next(r for r in reqs if r["review_status"] == "open")
        req_id = target["req_id"]
        # 直接把需求置为 reviewed(模拟 #218 评审通过的落库结果)
        row = db.query(SecurityRequirement).filter_by(project_id=pid, req_id=req_id).first()
        row.review_status = "reviewed"
        db.commit()

        resp = api.post(f"/api/projects/{pid}/requirements/{req_id}/confirm")
        assert resp.status_code == 409, resp.text
        assert "不允许" in resp.json()["detail"]
        # 流转记录未被污染
        assert api.get(
            f"/api/projects/{pid}/requirements/{req_id}/transitions").json() == []
    finally:
        db.close()


def test_transitions_endpoint_404_for_missing_req(api):
    pid, _ = _generated_project(api)
    resp = api.get(f"/api/projects/{pid}/requirements/SEC-NOPE/transitions")
    assert resp.status_code == 404


def test_batch_confirm_reports_skipped(api):
    """批量确认遇 reviewed 终态行: 计入 skipped 不整体失败。"""
    pid, reqs = _generated_project(api)
    db = api.session_factory()
    try:
        reviewed_id = reqs[0]["req_id"]
        row = db.query(SecurityRequirement).filter_by(
            project_id=pid, req_id=reviewed_id).first()
        row.review_status = "reviewed"
        db.commit()
    finally:
        db.close()
    others = [r["req_id"] for r in reqs[1:4]]
    resp = api.post(f"/api/projects/{pid}/requirements/batch-confirm",
                    json={"req_ids": [reviewed_id] + others})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["confirmed"] == len(others)
    assert body["skipped"] == [reviewed_id]
