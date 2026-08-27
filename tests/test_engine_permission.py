# -*- coding: utf-8 -*-
"""权限矩阵三种扫描算法测试。"""
import pytest

from conftest import add_base_project, gen_for
from models import PermissionEntry, Resource, Role
from rules import RuleEngine


@pytest.fixture()
def engine():
    return RuleEngine.load()


def _build(session, project, role_specs, resource_specs, entries):
    """构造权限矩阵。entries: (role_name, resource_name, action, needs_approval)"""
    roles = {}
    for name, rtype, count in role_specs:
        role = Role(project_id=project.id, name=name, role_type=rtype, user_count_estimate=count)
        session.add(role)
        roles[name] = role
    resources = {}
    for name, rtype, crit in resource_specs:
        res = Resource(project_id=project.id, name=name, resource_type=rtype, criticality=crit)
        session.add(res)
        resources[name] = res
    session.flush()
    for role_name, res_name, action, need_appr in entries:
        session.add(
            PermissionEntry(
                role_id=roles[role_name].id,
                resource_id=resources[res_name].id,
                action=action,
                requires_approval=need_appr,
            )
        )
    session.flush()


ROLES = [("超级管理员", "super_admin", 2), ("运营管理员", "privileged", 5)]
RESOURCES = [
    ("客户账户记录", "data_record", "critical"),
    ("参数配置", "system_config", "critical"),
]
ENTRIES = [
    # 违规1: critical 资源 delete 免审批
    ("超级管理员", "客户账户记录", "delete", False),
    # 违规2: critical 资源 export 免审批
    ("运营管理员", "客户账户记录", "export", False),
    # 合规对照: read 不属高危动作; 已挂审批的 config_change/approve 不违规
    ("运营管理员", "客户账户记录", "read", False),
    ("运营管理员", "参数配置", "config_change", True),
    # SoD 冲突: 运营管理员同时持有 create+approve 于同一 critical 资源
    ("运营管理员", "参数配置", "create", True),
    ("运营管理员", "参数配置", "approve", True),
]


def test_missing_approval_scan(engine, session):
    project = add_base_project(session)
    _build(session, project, ROLES, RESOURCES, ENTRIES)

    reqs = [r for r in gen_for(session, project, engine) if r.template_id == "SEC-V4-002"]
    assert len(reqs) == 2  # 仅两条免审批高危操作违规
    joined = "".join(r.description + r.trigger_reason for r in reqs)
    assert "删除" in joined and "导出" in joined
    assert all(r.priority == "critical" for r in reqs)


def test_sod_conflict_scan(engine, session):
    project = add_base_project(session)
    _build(session, project, ROLES, RESOURCES, ENTRIES)

    reqs = [r for r in gen_for(session, project, engine) if r.template_id == "SEC-V4-003"]
    assert len(reqs) == 1
    assert "运营管理员" in reqs[0].description
    assert "创建" in reqs[0].description and "审批" in reqs[0].description
    assert reqs[0].source_entity_type == "role"


def test_sod_not_triggered_on_low_criticality(engine, session):
    """low/medium 资源上的互斥操作不算 SoD 冲突, 避免误报刷屏。"""
    project = add_base_project(session)
    _build(
        session, project,
        ROLES[:1],
        [("公告栏", "page_menu", "low")],
        [("超级管理员", "公告栏", "create", False),
         ("超级管理员", "公告栏", "approve", False)],
    )
    reqs = [r for r in gen_for(session, project, engine) if r.template_id == "SEC-V4-003"]
    assert not reqs


def test_super_admin_scan(engine, session):
    project = add_base_project(session)
    _build(session, project, ROLES, RESOURCES, ENTRIES[:1])

    reqs = [r for r in gen_for(session, project, engine) if r.template_id == "SEC-V4-004"]
    assert len(reqs) == 1
    assert "2" in reqs[0].description  # 预估人数渲染进描述
    assert reqs[0].priority == "high"


def test_always_rule_emits_once_per_matrix(engine, session):
    project = add_base_project(session)
    _build(session, project, ROLES[:1], RESOURCES[:1],
           [("超级管理员", "客户账户记录", "read", False)])

    reqs = [r for r in gen_for(session, project, engine) if r.template_id == "SEC-V1-001"]
    assert len(reqs) == 1  # 有矩阵即出一条集中式访问控制需求


def test_empty_matrix_no_permission_rules(engine, session):
    project = add_base_project(session)  # 不添加任何角色与授权
    perm_ids = {"SEC-V4-002", "SEC-V4-003", "SEC-V4-004", "SEC-V1-001"}
    reqs = gen_for(session, project, engine)
    assert not any(r.template_id in perm_ids for r in reqs)


def test_source_entity_ids_are_filled(engine, session):
    """可追溯性约束: 全部需求 source_entity_id 必填。"""
    project = add_base_project(session)
    _build(session, project, ROLES, RESOURCES, ENTRIES)

    reqs = gen_for(session, project, engine)
    assert reqs
    assert all(r.source_entity_id is not None for r in reqs)
