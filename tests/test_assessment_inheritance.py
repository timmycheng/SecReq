# -*- coding: utf-8 -*-
"""评估轮次继承: 整卷复制(uid 不变)与两轮需求增量对比。

关键回归点: 复制出的轮次在输入未变时重新生成, diff 应为空 ——
这同时验证"复制保留实体 uid"与"需求按 (template_id, source_entity_uid) 对齐"。
"""
from conftest import add_base_project
from models import (
    ApiEndpoint, DataAsset, Feature, NetworkZone, PermissionEntry, Project,
    SecurityRequirement,
)
from rules import RuleEngine, load_knowledge_base
from rules.context import RequirementContext
from schemas.feature import FeatureIn
from services.project_copy import copy_wizard_data
from services.project_service import create_project
from services.requirement_diff import diff_requirements, find_previous_round
from services.step_store import replace_features

from datetime import datetime, timedelta


def _features():
    return [
        FeatureIn(name="登录", module="用户中心", categories=["auth_login"]),
        FeatureIn(name="转账", module="支付模块", categories=["payment"],
                  sensitivity="confidential", involves_payment=True),
        FeatureIn(name="账单查询", module="支付模块", categories=["search"]),
    ]


def _engine():
    return RuleEngine(load_knowledge_base())


def _new_round(session, source: Project, name: str, hours_later: float) -> Project:
    """模拟下一轮: 独立项目 + 继承系统 + 晚于上一轮的创建时间。"""
    round_ = create_project(session, {
        "name": name, "code": f"PRJ-{name}", "system_id": source.system_id,
    })
    round_.created_at = datetime.now() + timedelta(hours=hours_later)
    session.commit()
    copy_wizard_data(session, source, round_)
    return round_


def test_copy_preserves_uids_and_unchanged_inputs_diff_empty(session):
    """整卷复制后输入未变 → 重新生成需求应与上一轮完全对齐(diff 为空)。"""
    project = add_base_project(session)
    replace_features(session, project.id, _features())
    _engine().generate_and_save(RequirementContext.from_db(session, project.id), session)
    base_reqs = session.query(SecurityRequirement).filter_by(project_id=project.id).all()
    assert base_reqs, "前置条件: 首轮应生成需求"

    nxt = _new_round(session, project, "R2", 1.0)
    src_features = session.query(Feature).filter_by(project_id=project.id).all()
    dst_features = session.query(Feature).filter_by(project_id=nxt.id).all()
    assert {f.uid for f in src_features} == {f.uid for f in dst_features}
    assert len(dst_features) == len(src_features)

    _engine().generate_and_save(RequirementContext.from_db(session, nxt.id), session)

    result = diff_requirements(session, nxt, project)
    assert result["summary"]["added"] == 0, result["summary"]
    assert result["summary"]["removed"] == 0
    assert result["summary"]["changed"] == 0
    assert result["summary"]["current_total"] == len(base_reqs)


def test_diff_detects_added_and_changed(session):
    """新增功能 → added; 同 uid 功能改名(描述渲染变化) → changed。"""
    project = add_base_project(session)
    replace_features(session, project.id, _features())
    _engine().generate_and_save(RequirementContext.from_db(session, project.id), session)

    nxt = _new_round(session, project, "R2", 1.0)
    saved = [
        FeatureIn(uid=f.uid, name=f.name, module=f.module, description=f.description,
                  categories=f.categories, sensitivity=f.sensitivity,
                  involves_payment=f.involves_payment,
                  exposed_to_internet=f.exposed_to_internet)
        for f in session.query(Feature).filter_by(project_id=nxt.id).order_by(Feature.id)
    ]
    renamed = [FeatureIn(**{**f.model_dump(), "name": "大额转账"}) if f.name == "转账" else f for f in saved]
    replace_features(session, nxt.id, renamed + [
        FeatureIn(name="导出对账单", module="支付模块", categories=["export_data"]),
    ])
    _engine().generate_and_save(RequirementContext.from_db(session, nxt.id), session)

    result = diff_requirements(session, nxt, project)
    assert result["summary"]["added"] >= 1
    assert any(r["req_id"].startswith("SEC-EXP") or "导出" in r["title"] for r in result["added"])
    assert result["summary"]["changed"] >= 1
    assert result["summary"]["removed"] == 0


def test_diff_detects_removed(session):
    """删掉一个功能后重新生成 → 对应需求在上一轮存在、本轮移除。"""
    project = add_base_project(session)
    replace_features(session, project.id, _features())
    _engine().generate_and_save(RequirementContext.from_db(session, project.id), session)

    nxt = _new_round(session, project, "R2", 1.0)
    kept = [
        FeatureIn(uid=f.uid, name=f.name, module=f.module, description=f.description,
                  categories=f.categories, sensitivity=f.sensitivity,
                  involves_payment=f.involves_payment,
                  exposed_to_internet=f.exposed_to_internet)
        for f in session.query(Feature).filter_by(project_id=nxt.id).order_by(Feature.id)
        if f.name != "转账"
    ]
    replace_features(session, nxt.id, kept)
    _engine().generate_and_save(RequirementContext.from_db(session, nxt.id), session)

    result = diff_requirements(session, nxt, project)
    assert result["summary"]["removed"] >= 1
    assert result["summary"]["added"] == 0


def test_find_previous_round_ordering(session):
    """自动定位: 早于本轮的最近已生成项目; 草稿轮不参与, 显式 against 校验同系统。"""
    project = add_base_project(session)
    project.system_id = 1  # 直接挂系统(系统行不必存在: diff 只比较 system_id)
    project.created_at = datetime.now()
    session.commit()

    def make(code, hours, status="generated"):
        p = create_project(session, {"name": code, "code": code, "system_id": 1})
        p.created_at = datetime.now() + timedelta(hours=hours)
        p.status = status
        session.commit()
        return p

    round1 = make("R1", 1)
    draft = make("RD", 2, status="draft")
    round2 = make("R2", 3)

    assert find_previous_round(session, round2) == round1
    assert find_previous_round(session, draft) == round1  # 按时间序, 草稿(+2h)的上一轮是 R1(+1h)
    assert find_previous_round(session, round1) is None
    assert find_previous_round(session, round2, against=round1.id) == round1
    assert find_previous_round(session, round2, against=round2.id) is None
    other = create_project(session, {"name": "X", "code": "X1", "system_id": 2})
    assert find_previous_round(session, round2, against=other.id) is None


def test_copy_remaps_fks_and_cleans_stale_ids(session):
    """复制重排外键: 权限条目挂新角色/资源, 拓扑区域重映射, 接口旧资产主键置空。"""
    from models import Resource, Role

    project = add_base_project(session)
    zone = NetworkZone(project_id=project.id, env="prod", name="DMZ")
    session.add(zone)
    session.flush()
    asset = DataAsset(project_id=project.id, name="客户信息表", data_type="corporate",
                      classification="3级_C2主要信息")
    session.add(asset)
    session.flush()
    role = Role(project_id=project.id, name="管理员", role_type="privileged")
    resource = Resource(project_id=project.id, name="账户", resource_type="api",
                        criticality="high")
    session.add_all([role, resource])
    session.flush()
    session.add(PermissionEntry(role_id=role.id, resource_id=resource.id, action="create"))
    session.add(ApiEndpoint(
        project_id=project.id, name="查询账单", path="/api/bills", method="GET",
        sensitive_asset_ids=[asset.id], sensitive_asset_uids=[asset.uid],
    ))
    session.commit()

    nxt = _new_round(session, project, "R2", 1.0)
    new_asset = session.query(DataAsset).filter_by(project_id=nxt.id).one()
    new_ep = session.query(ApiEndpoint).filter_by(project_id=nxt.id).one()
    assert new_ep.sensitive_asset_uids == [asset.uid]  # uid 引用原样保留
    assert new_ep.sensitive_asset_ids == []            # 旧主键引用置空防悬挂
    new_entry = session.query(PermissionEntry).join(
        Role, PermissionEntry.role_id == Role.id
    ).filter(Role.project_id == nxt.id).one()
    new_zone = session.query(NetworkZone).filter_by(project_id=nxt.id).one()
    assert new_zone.uid == zone.uid and new_zone.id != zone.id
    assert new_entry.role_id != role.id and new_entry.resource_id != resource.id
    assert new_asset.uid == asset.uid and new_asset.id != asset.id
