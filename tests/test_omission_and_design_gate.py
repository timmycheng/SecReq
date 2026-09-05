# -*- coding: utf-8 -*-
"""漏填检测服务(#221)与设计门禁(#222): 5 条规则正反例 + 4 项校验放行/拦截。"""

from conftest import add_base_project
from models import (
    ApiEndpoint, DataAsset, DataField, DataTable, Feature, PermissionEntry,
    Resource, Role, SbomComponent, SecurityRequirement,
)
from services.omission_check import run_omission_checks
from services.review_gates import design_gate_checks


def _mk_asset(db, project_id: int, name: str, classification: str, tables=()) -> DataAsset:
    asset = DataAsset(
        project_id=project_id, uid=f"uid-{name}", name=name, data_type="business_data",
        classification=classification, is_pii=False, is_sensitive_pii=False,
        storage_envs=["db"], cross_border_transfer=False,
    )
    db.add(asset)
    db.flush()
    for table_name, fields in tables:
        table = DataTable(asset_id=asset.id, table_name=table_name)
        db.add(table)
        db.flush()
        for fname, enc, mask in fields:
            db.add(DataField(
                table_id=table.id, field_name=fname, field_type="string",
                need_encrypt=enc, need_mask=mask, mask_rule=None))
    db.flush()
    return asset


def _mk_feature(db, project_id: int, name: str, categories: list[str]) -> None:
    db.add(Feature(
        project_id=project_id, uid=f"f-{name}", name=name, module="模块",
        categories=categories, description="",
        sensitivity="internal", involves_payment="payment" in categories,
    ))


def _mk_endpoint(db, project_id: int, name: str, path: str, *,
                 sensitive_uids=(), public=False, rate_limit=None) -> None:
    db.add(ApiEndpoint(
        project_id=project_id, uid=f"ep-{name}", name=name, path=path, method="GET",
        auth_required=True, public_exposed=public, sensitive_asset_ids=[],
        sensitive_asset_uids=list(sensitive_uids), rate_limit=rate_limit,
    ))
    db.flush()


def test_rule1_sensitive_endpoint_unlinked_asset(session):
    """规则1: 接口命中敏感语义但未关联敏感资产 → 命中; 关联后 → 通过。"""
    project = add_base_project(session)
    _mk_endpoint(session, project.id, "身份证查验", "/api/idcard/query")
    missing = run_omission_checks(session, project)
    assert any("身份证查验" in m and "未关联敏感" in m for m in missing)

    _mk_endpoint(session, project.id, "身份证查验2", "/api/idcard/query2",
                 sensitive_uids=["uid-客户信息"])
    missing = run_omission_checks(session, project)
    assert not any("idcard/query2" in m for m in missing)


def test_rule2_sensitive_field_without_protection(session):
    """规则2: 敏感字段未配置加密/脱敏 → 命中; 配置任一 → 通过。"""
    project = add_base_project(session)
    _mk_asset(session, project.id, "客户信息", "3级_C2主要信息", tables=[
        ("customers", [("phone", False, False), ("id_card", True, False)]),
    ])
    missing = run_omission_checks(session, project)
    assert any("「phone」" in m and "加密或脱敏" in m for m in missing)
    assert not any("「id_card」" in m and "加密或脱敏" in m for m in missing)


def test_rule3_low_classification_with_sensitive_field(session):
    """规则3(分级疑似偏低): 敏感字段挂 2 级资产 → 命中; 挂 3 级 → 通过。"""
    project = add_base_project(session)
    _mk_asset(session, project.id, "日志表", "2级_C1次要信息", tables=[
        ("logs", [("bank_card", True, True)]),
    ])
    missing = run_omission_checks(session, project)
    assert any("「日志表」" in m and "疑似分级偏低" in m for m in missing)

    _mk_asset(session, project.id, "账户表", "3级_C2主要信息", tables=[
        ("accounts", [("bank_card_no", True, True)]),
    ])
    missing = run_omission_checks(session, project)
    assert not any("「账户表」" in m and "疑似分级偏低" in m for m in missing)


def test_rule4_payment_feature_without_account_asset(session):
    """规则4: 支付类功能存在但无账户/支付类资产 → 命中; 补资产 → 通过。"""
    project = add_base_project(session)
    _mk_feature(session, project.id, "转账", ["payment"])
    _mk_asset(session, project.id, "营销素材", "1级_公开数据")
    missing = run_omission_checks(session, project)
    assert any("支付/退款类功能" in m for m in missing)

    _mk_asset(session, project.id, "交易流水", "3级_C2主要信息")
    missing = run_omission_checks(session, project)
    assert not any("支付/退款类功能" in m for m in missing)


def test_rule5_public_endpoint_without_rate_limit(session):
    """规则5: 公网暴露接口未配置限流 → 命中; 配置后 → 通过。"""
    project = add_base_project(session)
    _mk_endpoint(session, project.id, "开放查询", "/api/open/search",
                 public=True)
    missing = run_omission_checks(session, project)
    assert any("「开放查询」" in m and "限流" in m for m in missing)

    _mk_endpoint(session, project.id, "开放查询2", "/api/open/search2",
                 public=True, rate_limit="100/min")
    missing = run_omission_checks(session, project)
    assert not any("search2" in m and "限流" in m for m in missing)


# ── 设计门禁(#222) ────────────────────────────────────


def _seed_matrix_with_conflict(db, project_id: int) -> None:
    """构造一个 SoD 冲突: 角色在高危资源上同时持有 create+approve。"""
    role = Role(project_id=project_id, uid="role-sod", name="运营角色", role_type="internal")
    resource = Resource(project_id=project_id, uid="res-sod", name="订单服务",
                        resource_type="api", criticality="critical")
    db.add_all([role, resource])
    db.flush()
    db.add_all([
        PermissionEntry(role_id=role.id, resource_id=resource.id, action="create"),
        PermissionEntry(role_id=role.id, resource_id=resource.id, action="approve"),
    ])
    db.flush()


def test_design_gate_blocked_on_all_four(session):
    """四项全缺: SBOM 未生成 + SoD 未整改 + C3 资产无字典 + 漏填命中。"""
    project = add_base_project(session)
    _mk_asset(session, project.id, "客户信息", "3级_C2主要信息")  # 无表 → 字典缺
    _mk_feature(session, project.id, "开放搜索", ["search"])
    _mk_endpoint(session, project.id, "开放查询", "/api/open", public=True)  # 漏填: 无限流
    _seed_matrix_with_conflict(session, project.id)

    missing = design_gate_checks(session, project)
    assert any("SBOM 未生成" in m for m in missing)
    assert any("SoD 冲突" in m and "运营角色" in m for m in missing)
    assert any("尚未建立数据字典" in m and "客户信息" in m for m in missing)
    assert any("漏填检测" in m for m in missing)


def test_design_gate_passes_when_all_satisfied(session):
    """全部满足: SBOM 有组件 + SoD 已生成整改需求 + C3 资产有字典 + 无漏填 → 放行。"""
    project = add_base_project(session)
    system_id = project.system_id
    db = session
    # SBOM
    db.add(SbomComponent(system_id=system_id, layer="library", name="log4j-core",
                         version="2.14.1", source_type="manual_input"))
    # C3 资产带字典表 + 敏感字段已配置脱敏
    _mk_asset(db, project.id, "账户信息", "3级_C2主要信息", tables=[
        ("accounts", [("phone", False, True)]),
    ])
    # 账户类资产(支付规则) + 公网接口带限流 + 非敏感接口
    _mk_feature(db, project.id, "转账", ["payment"])
    _mk_endpoint(db, project.id, "账户查询", "/api/accounts", public=True,
                 rate_limit="60/min", sensitive_uids=["uid-账户信息"])
    # SoD 冲突角色已有整改需求
    _seed_matrix_with_conflict(db, project.id)
    role = db.query(Role).filter_by(project_id=project.id).first()
    db.add(SecurityRequirement(
        project_id=project.id, req_id="SEC-SOD-001", template_id="T-SOD",
        title="SoD 整改", description="d", category="权限安全", priority="critical",
        acceptance_criteria="ac", suggested_phase="design",
        source_entity_type="role", source_entity_id=role.id,
        source_entity_uid=role.uid, trigger_reason="r",
    ))
    db.commit()

    missing = design_gate_checks(db, project)
    assert missing == [], missing
