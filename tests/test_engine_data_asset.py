# -*- coding: utf-8 -*-
"""数据资产/数据字典维度规则测试。"""
from conftest import add_base_project, gen_for
from models import DataAsset, DataField, DataTable


def _add_asset(session, project, **kwargs) -> DataAsset:
    fields = kwargs.pop("fields", [])
    asset = DataAsset(project_id=project.id, **kwargs)
    session.add(asset)
    session.flush()
    table = DataTable(asset_id=asset.id, table_name="t_demo")
    session.add(table)
    session.flush()
    for f_name, f_type in fields:
        session.add(DataField(table_id=table.id, field_name=f_name, field_type=f_type))
    return asset


def test_confidential_classification_triggers_triple_protection(session, engine):
    project = add_base_project(session)
    a1 = _add_asset(session, project, name="银行卡账户", data_type="financial_account",
                    classification="机密")
    _add_asset(session, project, name="产品介绍", data_type="business_data",
               classification="公开")

    reqs = [r for r in gen_for(session, project, engine) if r.template_id == "SEC-V6-001"]
    assert len(reqs) == 1
    assert "银行卡账户" in reqs[0].description
    assert reqs[0].source_entity_id == a1.id


def test_sensitive_pii_triggers_consent_rule(session, engine):
    project = add_base_project(session)
    _add_asset(session, project, name="健康档案", data_type="health_medical",
               classification="敏感", is_pii=True, is_sensitive_pii=True)

    reqs = [r for r in gen_for(session, project, engine) if r.template_id == "SEC-V8-403"]
    assert len(reqs) == 1
    assert "单独同意" in reqs[0].description


def test_mask_field_regex_match_by_field_name(session, engine):
    """字段名含手机/证件/卡号 → 脱敏需求。"""
    project = add_base_project(session)
    asset = _add_asset(
        session, project,
        name="客户联系方式", data_type="basic_personal_info", classification="内部",
        fields=[("mobile_number", "varchar(16)"), ("address", "varchar(200)")],
    )

    reqs = [r for r in gen_for(session, project, engine) if r.template_id == "SEC-V5-105"]
    assert len(reqs) == 1
    assert reqs[0].source_entity_id == asset.id


def test_mask_field_no_false_positive_on_plain_fields(session, engine):
    project = add_base_project(session)
    _add_asset(
        session, project,
        name="字典表", data_type="business_data", classification="公开",
        fields=[("status_code", "int"), ("remark", "varchar(50)")],
    )
    reqs = [r for r in gen_for(session, project, engine) if r.template_id == "SEC-V5-105"]
    assert not reqs


def test_log_storage_leakage_risk(session, engine):
    project = add_base_project(session)
    _add_asset(session, project, name="埋点日志", data_type="behavior_log",
               classification="内部", storage_envs=["db", "log"])

    reqs = [r for r in gen_for(session, project, engine) if r.template_id == "SEC-V7-002"]
    assert len(reqs) == 1
    assert "埋点日志" in reqs[0].description


def test_cross_border_rule(session, engine):
    project = add_base_project(session)
    _add_asset(session, project, name="海外推介数据", data_type="business_data",
               classification="敏感", cross_border_transfer=True)

    reqs = [r for r in gen_for(session, project, engine) if r.template_id == "SEC-V8-404"]
    assert len(reqs) == 1
    assert reqs[0].priority == "critical"


def test_each_hit_is_separate_requirement(session, engine):
    """两份机密资产 → 两条独立需求, 分别可追溯。"""
    project = add_base_project(session)
    a1 = _add_asset(session, project, name="资产A", data_type="identity_info", classification="机密")
    a2 = _add_asset(session, project, name="资产B", data_type="financial_account", classification="机密")

    reqs = [r for r in gen_for(session, project, engine) if r.template_id == "SEC-V6-001"]
    assert {r.source_entity_id for r in reqs} == {a1.id, a2.id}
    assert len({r.req_id for r in reqs}) == 2
