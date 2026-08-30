# -*- coding: utf-8 -*-
"""溯源稳定性护栏(目标行为: v2.3.0 uid 迁移)。

这 4 个测试锁定的都是当前**尚未修复**的缺陷, 因此标记为 xfail(strict=True):
- 现在跑: 失败 → 记为 XFAIL, 套件保持绿灯;
- v2.3.0 修好后: 通过 → strict 模式下记为 XPASS 失败, 提醒移除标记。

对应缺陷:
- P0-1 `rules/engine.py:171` 全删全插 → 重新生成清空所有确认记录
- P0-2 `services/step_store.py` 整表替换 → 主键变化使已生成需求的溯源断链
"""
import pytest
from conftest import add_base_project
from models import ApiEndpoint, DataAsset, Feature, SecurityRequirement
from rules import RuleEngine, load_knowledge_base
from rules.context import RequirementContext
from schemas.data_dictionary import DataAssetIn, DataTableIn
from schemas.feature import FeatureIn
from services.step_store import replace_data_assets, replace_features


def _features():
    return [
        FeatureIn(name="登录", module="用户中心", categories=["auth_login"]),
        FeatureIn(name="转账", module="支付模块", categories=["payment"],
                  sensitivity="confidential", involves_payment=True),
        FeatureIn(name="账单查询", module="支付模块", categories=["search"]),
    ]


def _feature_ids_by_name(session, project_id):
    return {
        f.name: f.id
        for f in session.query(Feature).filter_by(project_id=project_id)
    }


@pytest.mark.xfail(strict=True, reason="P0-1: 重新生成会清空确认记录(待 v2.3.0 修复)")
def test_regenerate_preserves_confirmation(session):
    """确认过的需求在重新生成后应保持已确认状态。"""
    project = add_base_project(session)
    replace_features(session, project.id, _features())

    engine = RuleEngine(load_knowledge_base())
    first = engine.generate_and_save(RequirementContext.from_db(session, project.id))
    assert first, "前置条件: 首轮应生成需求"

    for req in first:
        req.reg_confirmed = True
        req.confirmed_by = "测试安全"
    session.commit()
    confirmed_ids = {r.req_id for r in first}
    assert len(confirmed_ids) > 1, "前置条件: 应有多个需求可供确认"

    # 回到向导补录一个功能, 然后重新生成
    replace_features(session, project.id, _features() + [
        FeatureIn(name="导出对账单", module="支付模块", categories=["export_data"]),
    ])
    engine.generate_and_save(RequirementContext.from_db(session, project.id))

    kept = (
        session.query(SecurityRequirement)
        .filter(SecurityRequirement.project_id == project.id,
                SecurityRequirement.req_id.in_(confirmed_ids),
                SecurityRequirement.reg_confirmed.is_(True))
        .all()
    )
    assert len(kept) == len(confirmed_ids), (
        f"重新生成后确认状态丢失: 原 {len(confirmed_ids)} 条, "
        f"仅剩 {len(kept)} 条仍为已确认"
    )


@pytest.mark.xfail(strict=True, reason="P0-2: 整表替换使 source_entity_id 断链(待 v2.3.0 修复)")
def test_saving_step_keeps_traceability(session):
    """保存向导步骤后, 已生成需求仍应能解析到正确的来源实体。"""
    project = add_base_project(session)
    replace_features(session, project.id, _features())

    engine = RuleEngine(load_knowledge_base())
    engine.generate_and_save(RequirementContext.from_db(session, project.id))

    def labels():
        return {
            r.req_id: r.source_label
            for r in session.query(SecurityRequirement)
            .filter_by(project_id=project.id, source_entity_type="feature")
        }

    before = labels()
    assert before, "前置条件: 应有来源于功能的需求"

    # 追加一个功能并保存(整卷替换)
    replace_features(session, project.id, _features() + [
        FeatureIn(name="导出对账单", module="支付模块", categories=["export_data"]),
    ])

    # 溯源文本应保持不变: 追加功能不应让既有需求指向别的功能
    assert labels() == before


@pytest.mark.xfail(strict=True, reason="P0-2: 删除一行会让后续行主键前移(待 v2.3.0 修复)")
def test_deleting_one_row_keeps_other_ids(session):
    """删除中间某一行后, 其余行的主键不应漂移。

    只在末尾追加时 SQLite 会复用 rowid, 恰好掩盖了问题;
    真正暴露缺陷的是删除 —— 后续行整体前移, 已生成需求会指向错误的实体。
    """
    project = add_base_project(session)
    replace_features(session, project.id, _features())
    ids_before = _feature_ids_by_name(session, project.id)

    # 删除首行"登录", 保留其余两条
    remaining = [f for f in _features() if f.name != "登录"]
    replace_features(session, project.id, remaining)

    ids_after = _feature_ids_by_name(session, project.id)
    for name in ("转账", "账单查询"):
        assert ids_before[name] == ids_after[name], (
            f"未修改的功能『{name}』主键发生漂移: "
            f"{ids_before[name]} → {ids_after[name]}"
        )


@pytest.mark.xfail(strict=True, reason="P0-2: 主键前移后需求指向了错误的实体(待 v2.3.0 修复)")
def test_requirement_still_points_to_same_feature_after_deletion(session):
    """删除一个功能后, 其余功能对应的需求仍应溯源到同名功能。"""
    project = add_base_project(session)
    replace_features(session, project.id, _features())

    engine = RuleEngine(load_knowledge_base())
    engine.generate_and_save(RequirementContext.from_db(session, project.id))

    reqs = (
        session.query(SecurityRequirement)
        .filter_by(project_id=project.id, source_entity_type="feature")
        .all()
    )
    assert reqs, "前置条件: 应有来源于功能的需求"
    # req_id → 来源功能名(按当前主键解析)
    before = {
        r.req_id: (session.get(Feature, r.source_entity_id).name
                   if session.get(Feature, r.source_entity_id) else None)
        for r in reqs
    }

    # 删除首行"登录"
    replace_features(session, project.id, [f for f in _features() if f.name != "登录"])

    after = {
        r.req_id: (session.get(Feature, r.source_entity_id).name
                   if session.get(Feature, r.source_entity_id) else None)
        for r in session.query(SecurityRequirement)
        .filter_by(project_id=project.id, source_entity_type="feature")
    }
    # 仍然存活的功能(转账/账单查询)对应的需求, 溯源结果不应改变
    survivors = {k: v for k, v in before.items() if v != "登录"}
    assert {k: after.get(k) for k in survivors} == survivors


@pytest.mark.xfail(strict=True, reason="P0-2: 敏感资产关联同样因整表替换失效(待 v2.3.0 修复)")
def test_sensitive_asset_link_survives_asset_resave(session):
    """接口关联的数据资产, 在数据字典重新保存后仍应指向同一资产。"""
    project = add_base_project(session)
    assets = [
        DataAssetIn(name="客户信息表", data_type="customer_data",
                    classification="4级_C3鉴别信息", is_pii=True),
        DataAssetIn(name="交易流水表", data_type="transaction_data",
                    classification="3级_C2重要信息"),
    ]
    replace_data_assets(session, project.id, assets)
    target = (session.query(DataAsset)
              .filter_by(project_id=project.id, name="客户信息表").first())

    session.add(ApiEndpoint(
        project_id=project.id, name="查询客户", path="/api/customer", method="GET",
        auth_required=True, public_exposed=False, sensitive_asset_ids=[target.id],
    ))
    session.commit()

    # 追加一张表后重新保存数据字典(整卷替换)
    replace_data_assets(session, project.id, assets + [
        DataAssetIn(name="操作日志表", data_type="log_data",
                    classification="2级_C1次要信息",
                    tables=[DataTableIn(table_name="t_audit_log")]),
    ])

    ep = session.query(ApiEndpoint).filter_by(project_id=project.id).first()
    linked = session.query(DataAsset).filter(
        DataAsset.project_id == project.id,
        DataAsset.id.in_(ep.sensitive_asset_ids or []),
    ).all()
    assert [a.name for a in linked] == ["客户信息表"], (
        f"接口关联漂移到了: {[a.name for a in linked]}"
    )
