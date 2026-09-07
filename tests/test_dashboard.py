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
    """pm 只统计本人项目; 安全侧全量可见。"""
    sid = create_system_api(api, "权限系统")["id"]
    _mk_project(api, sid, "dev 的评估")

    sec = api_as(api, "sec_admin")
    sec_sid = create_system_api(sec, "安全侧系统")["id"]
    _mk_project(sec, sec_sid, "sec 的评估")

    mine = api.get("/api/meta/dashboard").json()
    assert mine["eval_total"] == 1
    theirs = sec.get("/api/meta/dashboard").json()
    assert theirs["eval_total"] == 2


def test_dashboard_requires_login():
    """未登录访问工作台聚合 → 401(全局认证守卫覆盖)。"""
    from fastapi.testclient import TestClient

    import main
    client = TestClient(main.app)
    assert client.get("/api/meta/dashboard").status_code == 401
