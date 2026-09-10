# -*- coding: utf-8 -*-
"""删除级联完整性(#323): 流转/耗时/基线随删, 复制失败不留半成品。"""
import pytest

from conftest import add_base_project, demo_features
from models import (
    Feature, Project, RequirementTransition, SecurityRequirement, StepDuration,
    System, SystemBaseline, SystemBaselineHistory,
)
from rules import RuleEngine, load_knowledge_base
from rules.context import RequirementContext
from schemas.feature import FeatureIn
from services.project_service import delete_project_cascade
from services.step_store import replace_features
from services.system_service import delete_system


def _project_with_requirement(session):
    """生成一条真实需求的完整项目(复用引擎, 避免手填非空列)。"""
    project = add_base_project(session)
    replace_features(session, project.id, demo_features())
    engine = RuleEngine(load_knowledge_base())
    first = engine.generate_and_save(
        RequirementContext.from_db(session, project.id), session)
    assert first, "前置条件: 应生成需求"
    return project, first[0]


def test_delete_project_clears_transitions_and_durations(session):
    """删除项目后流转/耗时无孤儿行(#323): 主键复用不再把旧历史挂到新需求。"""
    project, req = _project_with_requirement(session)
    session.add(RequirementTransition(
        requirement_id=req.id, action="confirm", from_status="open",
        to_status="confirmed", operator_name="测试人", opinion=None))
    session.add(StepDuration(project_id=project.id, step="features",
                             duration_seconds=3.5, operator_name="测试人"))
    session.add(StepDuration(project_id=project.id, step="survey",
                             duration_seconds=1.0))
    session.commit()
    assert session.query(RequirementTransition).count() == 1
    assert session.query(StepDuration).count() == 2

    delete_project_cascade(session, project.id)

    assert session.query(RequirementTransition).count() == 0
    assert session.query(StepDuration).count() == 0
    assert session.query(SecurityRequirement).filter_by(project_id=project.id).count() == 0


def test_delete_project_invalidates_sourced_baseline(session):
    """删除基线来源轮次后基线同步失效(#323), 履历保留审计。"""
    project, _ = _project_with_requirement(session)
    system_id = project.system_id
    session.add(SystemBaseline(
        system_id=system_id, source_project_id=project.id,
        baseline_json={"data_assets": []}, summary="基线摘要"))
    session.add(SystemBaselineHistory(
        system_id=system_id, project_id=project.id, summary="写入基线"))
    session.commit()

    delete_project_cascade(session, project.id)

    assert session.query(SystemBaseline).filter_by(system_id=system_id).count() == 0
    assert session.query(SystemBaselineHistory).filter_by(system_id=system_id).count() == 1


def test_delete_system_clears_baselines_and_history(session):
    """删除系统一并清理基线与履历(#323): id 复用不再「继承」旧基线。"""
    system = System(name="待删系统", user_scale="1k_to_100k", is_public=False)
    session.add(system)
    session.flush()
    session.add(SystemBaseline(
        system_id=system.id, source_project_id=None,
        baseline_json={}, summary=None))
    session.add(SystemBaselineHistory(system_id=system.id, summary="写入基线"))
    session.commit()

    delete_system(session, system.id)

    assert session.query(SystemBaseline).filter_by(system_id=system.id).count() == 0
    assert session.query(SystemBaselineHistory).filter_by(system_id=system.id).count() == 0


def test_copy_from_failure_rolls_back_reset(session, api, monkeypatch):
    """复制中途失败整体回滚(#323): 原有输入不丢失(先清后拷不再半途落库)。"""
    dev = api
    system = dev.post("/api/systems", json={"name": "级联系统"}).json()
    target = dev.post("/api/projects", json={
        "name": "目标", "system_id": system["id"]}).json()
    source = dev.post("/api/projects", json={
        "name": "来源", "system_id": system["id"]}).json()

    def _save(pid, name):
        db = api.session_factory()
        try:
            replace_features(db, pid, [FeatureIn(name=name, module="m", categories=["search"])])
        finally:
            db.close()

    _save(target["id"], "目标原有功能")
    _save(source["id"], "来源功能")

    def _boom(db, src, dst):
        raise RuntimeError("模拟复制中途异常")

    # copy_from 走模块级导入, create 走函数内导入: 两处绑定都要打桩
    monkeypatch.setattr("services.project_copy.copy_wizard_data", _boom)
    monkeypatch.setattr("routers.projects.copy_wizard_data", _boom)
    with pytest.raises(RuntimeError):
        dev.post(f"/api/projects/{target['id']}/copy-from",
                 json={"from_project_id": source["id"]})

    db = api.session_factory()
    try:
        names = [f.name for f in db.query(Feature).filter_by(project_id=target["id"]).all()]
    finally:
        db.close()
    assert names == ["目标原有功能"], f"复制失败后原有输入丢失: {names}"


def test_create_with_copy_failure_rolls_back_new_project(session, api, monkeypatch):
    """建号+复制同一事务(#323): 复制失败时不残留已落库的空评估。"""
    dev = api
    system = dev.post("/api/systems", json={"name": "级联系统二"}).json()
    source = dev.post("/api/projects", json={
        "name": "来源", "system_id": system["id"]}).json()
    db = api.session_factory()
    try:
        replace_features(db, source["id"],
                         [FeatureIn(name="来源功能", module="m", categories=["search"])])
    finally:
        db.close()

    def _boom(db, src, dst):
        raise RuntimeError("模拟复制中途异常")

    monkeypatch.setattr("services.project_copy.copy_wizard_data", _boom)
    monkeypatch.setattr("routers.projects.copy_wizard_data", _boom)
    before = dev.get("/api/projects").json()
    with pytest.raises(RuntimeError):
        dev.post("/api/projects", json={
            "name": "半成品", "system_id": system["id"],
            "from_project_id": source["id"]})

    db = api.session_factory()
    try:
        after_names = {p.name for p in db.query(Project).all()}
    finally:
        db.close()
    assert "半成品" not in after_names
    assert len(after_names) == len({p["name"] for p in before})
