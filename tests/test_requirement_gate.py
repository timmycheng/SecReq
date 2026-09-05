# -*- coding: utf-8 -*-
"""需求门禁(#220): 提交评审硬校验与 blocked 契约。

4 条硬校验: 需求数≥1 / 溯源非空 / critical 已确认 / 报送类全部确认;
只在提交评审时校验, 一次给出全部缺项; 各项正反例单测。
"""
import pytest

from conftest import create_system_api, demo_features
from models import SecurityRequirement


@pytest.fixture()
def generated(api):
    """一个已生成需求的评估(离线管线), 返回 (pid, requirements)。"""
    sid = create_system_api(api, "门禁系统")["id"]
    pid = api.post("/api/projects", json={
        "name": "门禁项目", "system_id": sid}).json()["id"]
    resp = api.post(f"/api/projects/{pid}/features",
                    json=[f.model_dump() for f in demo_features()])
    assert resp.status_code == 200, resp.text
    gen = api.post(f"/api/projects/{pid}/generate", json={"skip_osv": True})
    assert gen.status_code == 200, gen.text
    reqs = api.get(f"/api/projects/{pid}/requirements").json()
    assert reqs
    return pid, reqs


def _submit(api, pid):
    resp = api.post(f"/api/projects/{pid}/review/submit")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _patch_req(api, pid, req_id: str, **fields):
    """经同库会话调整需求行(构造门禁反例数据)。"""
    db = api.session_factory()
    try:
        row = db.query(SecurityRequirement).filter_by(
            project_id=pid, req_id=req_id).first()
        assert row is not None
        for key, value in fields.items():
            setattr(row, key, value)
        db.commit()
    finally:
        db.close()


def _add_req(api, pid: int, req_id: str, **fields) -> None:
    db = api.session_factory()
    try:
        defaults = dict(
            project_id=pid, req_id=req_id, template_id="T-GATE",
            title="门禁用需求", description="d", category="监管报送", priority="high",
            acceptance_criteria="ac", suggested_phase="design",
            source_entity_type="feature", source_entity_id=1, trigger_reason="r",
        )
        defaults.update(fields)
        db.add(SecurityRequirement(**defaults))
        db.commit()
    finally:
        db.close()


def test_submit_blocked_lists_all_missing_items(api, generated):
    """一次给全缺项: critical 未确认 + 报送类未确认 同时出现在 missing。"""
    pid, reqs = generated
    # 挑两条未确认需求: 一条升为 critical, 一条改为监管报送类
    _patch_req(api, pid, reqs[0]["req_id"], priority="critical")
    _patch_req(api, pid, reqs[1]["req_id"], category="监管报送")

    body = _submit(api, pid)
    assert body["status"] == "blocked"
    assert any(reqs[0]["req_id"] in m and "critical" in m for m in body["missing"])
    assert any(reqs[1]["req_id"] in m and "监管报送" in m for m in body["missing"])
    # 门禁未推进
    state = api.get(f"/api/projects/{pid}/review/state").json()
    assert state["gate"] is None or state["gate"]["status"] == "pending"


def test_submit_blocked_when_no_requirements(api):
    """安全需求数 ≥ 1: 空清单提交 blocked。"""
    sid = create_system_api(api, "空需求系统")["id"]
    pid = api.post("/api/projects", json={
        "name": "空需求项目", "system_id": sid}).json()["id"]
    body = _submit(api, pid)
    assert body["status"] == "blocked"
    assert any("安全需求清单为空" in m for m in body["missing"])


def test_submit_blocked_on_broken_traceability(api, generated):
    """溯源约束: source_entity_id 为空(0)的需求让提交 blocked。"""
    pid, _ = generated
    _add_req(api, pid, "SEC-GATE-001", source_entity_id=0)
    body = _submit(api, pid)
    assert body["status"] == "blocked"
    assert any("SEC-GATE-001" in m and "来源实体" in m for m in body["missing"])


def test_obsolete_requirements_excluded_from_gate(api, generated):
    """obsolete 行(输入已变更)不参与门禁校验。"""
    pid, reqs = generated
    _patch_req(api, pid, reqs[0]["req_id"], priority="critical", status="obsolete")
    # 其余需求全部确认后应放行(obsolete 的 critical 不再拦截)
    others = [r["req_id"] for r in reqs if r["req_id"] != reqs[0]["req_id"]]
    resp = api.post(f"/api/projects/{pid}/requirements/batch-confirm",
                    json={"req_ids": others})
    assert resp.status_code == 200, resp.text
    body = _submit(api, pid)
    assert body["status"] == "submitted", body


def test_submit_passes_after_confirm(api, generated):
    """补齐后复提交通过, 门禁状态推进(#220 验收)。"""
    pid, reqs = generated
    _patch_req(api, pid, reqs[0]["req_id"], priority="critical")
    first = _submit(api, pid)
    assert first["status"] == "blocked"

    # 补齐(确认全部需求)后复提交 → 通过, 门禁进入 in_review
    ids = [r["req_id"] for r in reqs]
    resp = api.post(f"/api/projects/{pid}/requirements/batch-confirm",
                    json={"req_ids": ids})
    assert resp.status_code == 200, resp.text
    second = _submit(api, pid)
    assert second["status"] == "submitted"
    state = api.get(f"/api/projects/{pid}/review/state").json()
    assert state["gate"]["status"] == "in_review"
    assert state["gate"]["version_hash"]
