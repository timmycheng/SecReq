# -*- coding: utf-8 -*-
"""工作台聚合端点(#280): 指标卡/步骤耗时/趋势/最近评估, 数据权限按角色过滤。"""

from conftest import api_as, create_system_api


def _mk_project(api, system_id: int, name: str) -> dict:
    return api.post("/api/projects", json={"name": name, "system_id": system_id}).json()


def _inject_requirement(api, project_id: int, priority: str, seq: int) -> None:
    """直接注入一条需求(绕过整链路生成), 供趋势聚合断言。"""
    db = api.session_factory()
    try:
        from models import SecurityRequirement
        db.add(SecurityRequirement(
            project_id=project_id, req_id=f"SEC-T-001-{seq:02d}",
            template_id="SEC-T-001", title="t", description="d",
            category="auth", priority=priority, acceptance_criteria="a",
            suggested_phase="design", source_entity_type="feature",
            source_entity_id=0, trigger_reason="r",
        ))
        db.commit()
    finally:
        db.close()


def test_dashboard_counts_and_recent(api):
    """指标卡口径: 系统数/评估总数/评估中(草稿)/已完成(已生成); 最近评估含系统名。"""
    sid = create_system_api(api, "工作台系统")["id"]
    first = _mk_project(api, sid, "首轮评估")
    _mk_project(api, sid, "第二轮评估")

    data = api.get("/api/meta/dashboard").json()
    assert data["system_count"] == 1
    assert data["eval_total"] == 2
    assert data["eval_active"] == 2
    assert data["eval_done"] == 0
    recent = {r["name"]: r for r in data["recent"]}
    assert recent["首轮评估"]["system_name"] == "工作台系统"
    assert recent["首轮评估"]["code"] == first["code"]
    assert set(data["req_trend"][0].keys()) == {"month", "high", "mid", "low"}
    assert len(data["req_trend"]) == 6


def test_dashboard_trend_counts_by_month(api):
    """需求按评估创建月聚合计数: critical→高 / high→中 / medium·low→低。"""
    sid = create_system_api(api, "趋势系统")["id"]
    project = _mk_project(api, sid, "趋势评估")
    for seq, priority in enumerate(
            ("critical", "high", "medium", "low", "low"), start=1):
        _inject_requirement(api, project["id"], priority, seq)

    data = api.get("/api/meta/dashboard").json()
    current = data["req_trend"][-1]
    assert (current["high"], current["mid"], current["low"]) == (1, 1, 3)


def test_dashboard_visible_scope_for_pm(api):
    """pm 只统计本人项目; 全量可见角色(dev_admin/安全管理员)统计全部; 安全管理员不能建评估(#309)。"""
    sid = create_system_api(api, "权限系统")["id"]
    _mk_project(api, sid, "dev 的评估")

    sec = api_as(api, "sec_admin")
    sec_sid = create_system_api(sec, "安全侧系统")["id"]
    # 安全管理员对评估仅查看: 创建被角色层拦截(#309)
    assert sec.post("/api/projects", json={
        "name": "sec 的评估", "system_id": sec_sid}).status_code == 403

    lead = api_as(api, "dev_lead")
    lead_sid = create_system_api(lead, "开发侧系统")["id"]
    _mk_project(lead, lead_sid, "lead 的评估")

    mine = api.get("/api/meta/dashboard").json()
    assert mine["eval_total"] == 1
    theirs = lead.get("/api/meta/dashboard").json()
    assert theirs["eval_total"] == 2


def test_dashboard_requires_login():
    """未登录访问工作台聚合 → 401(全局认证守卫覆盖)。"""
    from fastapi.testclient import TestClient

    import main
    client = TestClient(main.app)
    assert client.get("/api/meta/dashboard").status_code == 401


def test_dashboard_scopes_system_count_and_step_metrics(api):
    """#330: pm 工作台的系统数与步骤耗时按数据权限过滤, 不再泄露全平台数据。"""
    from models import PlatformUser, Project, StepDuration, System

    sid = create_system_api(api, "我的工作台系统")["id"]
    pid = _mk_project(api, sid, "我的评估")["id"]

    db = api.session_factory()
    try:
        sec_id = db.query(PlatformUser).filter_by(username="sec_admin").first().id
        foreign_system = System(name="他人系统", user_scale="1k_to_100k",
                                is_public=False, owner_user_id=sec_id)
        db.add(foreign_system)
        db.flush()
        foreign_project = Project(name="他人评估", code="PRJ-F001", type="web",
                                  system_id=foreign_system.id, owner_user_id=sec_id,
                                  status="draft")
        db.add(foreign_project)
        db.flush()
        db.add(StepDuration(project_id=pid, step="features",
                            duration_seconds=600, operator_name="我"))
        db.add(StepDuration(project_id=foreign_project.id, step="survey",
                            duration_seconds=6000, operator_name="他人"))
        db.commit()
    finally:
        db.close()

    data = api.get("/api/meta/dashboard").json()
    assert data["system_count"] == 1, "pm 看到了他人系统"
    assert [s["step"] for s in data["step_minutes"]] == ["功能清单"], "pm 看到了他人轮次耗时"
    assert data["step_minutes"][0]["min"] == 10.0
    assert data["avg_minutes"] == 10.0

    # 全量可见角色不受影响
    sec = api_as(api, "sec_admin")
    data_sec = sec.get("/api/meta/dashboard").json()
    assert data_sec["system_count"] == 2
    assert {s["step"] for s in data_sec["step_minutes"]} == {"功能清单", "survey"}


def test_filings_ledger_scopes_latest_round_for_pm(api):
    """#330: 备案清单保持登录可读, 但评估概况按数据权限裁剪。"""
    sec = api_as(api, "sec_admin")
    filing = sec.post("/api/filings", json={
        "name": "口径备案", "level": "三级"}).json()
    assert filing["id"]

    # pm 建系统挂同备案并生成一轮评估
    mine = api.post("/api/systems", json={
        "name": "我的挂靠系统", "filing_id": filing["id"]}).json()
    pid = _mk_project(api, mine["id"], "我的挂靠评估")["id"]
    gen = api.post(f"/api/projects/{pid}/generate", json={"skip_osv": True})
    assert gen.status_code == 200, gen.text

    # 安全侧再建一个系统挂同备案(无生成轮次, 仅验证计数归属)
    sec_sid = sec.post("/api/systems", json={
        "name": "安全侧挂靠系统", "filing_id": filing["id"]}).json()
    assert sec_sid["id"]

    rows = {r["name"]: r for r in api.get("/api/filings").json()}
    row = rows["口径备案"]
    assert row["system_count"] == 1, "pm 看到了他人系统"
    assert row["latest_round"] is not None
    assert row["latest_round"]["project_name"] == "我的挂靠评估"

    rows_sec = {r["name"]: r for r in sec.get("/api/filings").json()}
    row_sec = rows_sec["口径备案"]
    assert row_sec["system_count"] == 2
    assert row_sec["latest_round"]["project_name"] == "我的挂靠评估"


def test_docs_routes_disabled_by_default(api):
    """#330: /docs 三路由默认关闭 —— Starlette 路由不经过 auth_guard,
    开着就等于匿名公开完整 API 结构。"""
    for path in ("/docs", "/redoc", "/openapi.json"):
        resp = api.get(path)
        assert resp.status_code == 404, f"{path} 匿名可访问: {resp.status_code}"
