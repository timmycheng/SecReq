# -*- coding: utf-8 -*-
"""溯源稳定性护栏(v2.3.0 uid 迁移落地, #66)。

锁定两个 P0 缺陷的修复效果:
- P0-1 生成改 upsert: 重新生成不再清空确认记录, 输入消失的需求标 obsolete;
- P0-2 保存改按 uid 的整卷 upsert: 未改动的行主键不漂移, 溯源不断链。
"""
from conftest import add_base_project
from models import ApiEndpoint, DataAsset, Feature, SecurityRequirement
from rules import RuleEngine, load_knowledge_base
from rules.context import RequirementContext
from schemas.data_dictionary import DataAssetIn, DataFieldIn, DataTableIn
from schemas.feature import FeatureIn
from services.step_store import replace_data_assets, replace_features


def _features():
    return [
        FeatureIn(name="登录", module="用户中心", categories=["auth_login"]),
        FeatureIn(name="转账", module="支付模块", categories=["payment"],
                  sensitivity="confidential", involves_payment=True),
        FeatureIn(name="账单查询", module="支付模块", categories=["search"]),
    ]


def _saved_features_as_in(session, project_id):
    """把库中已有功能行还原成 FeatureIn(带 uid), 模拟新版前端回传(#66)。"""
    return [
        FeatureIn(
            uid=f.uid, name=f.name, module=f.module, description=f.description,
            categories=f.categories, sensitivity=f.sensitivity,
            involves_payment=f.involves_payment, exposed_to_internet=f.exposed_to_internet,
        )
        for f in session.query(Feature).filter_by(project_id=project_id).order_by(Feature.id)
    ]


def _feature_ids_by_name(session, project_id):
    return {
        f.name: f.id
        for f in session.query(Feature).filter_by(project_id=project_id)
    }


def test_regenerate_preserves_confirmation(session):
    """确认过的需求在重新生成后应保持已确认状态(P0-1 修复护栏)。"""
    project = add_base_project(session)
    replace_features(session, project.id, _features())

    engine = RuleEngine(load_knowledge_base())
    first = engine.generate_and_save(RequirementContext.from_db(session, project.id), session)
    assert first, "前置条件: 首轮应生成需求"

    for req in first:
        req.reg_confirmed = True
        req.confirmed_by = "测试安全"
    session.commit()
    confirmed_ids = {r.req_id for r in first}
    assert len(confirmed_ids) > 1, "前置条件: 应有多个需求可供确认"

    # 回到向导补录一个功能(uid 原样回传 + 一条新增), 然后重新生成
    replace_features(session, project.id, _saved_features_as_in(session, project.id) + [
        FeatureIn(name="导出对账单", module="支付模块", categories=["export_data"]),
    ])
    engine.generate_and_save(RequirementContext.from_db(session, project.id), session)

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


def test_saving_step_keeps_traceability(session):
    """保存向导步骤后, 已生成需求仍应能解析到正确的来源实体(P0-2 修复护栏)。"""
    project = add_base_project(session)
    replace_features(session, project.id, _features())

    engine = RuleEngine(load_knowledge_base())
    engine.generate_and_save(RequirementContext.from_db(session, project.id), session)

    def labels():
        return {
            r.req_id: r.source_label
            for r in session.query(SecurityRequirement)
            .filter_by(project_id=project.id, source_entity_type="feature")
        }

    before = labels()
    assert before, "前置条件: 应有来源于功能的需求"

    # 追加一个功能并保存(uid 原样回传 + 一条新增)
    replace_features(session, project.id, _saved_features_as_in(session, project.id) + [
        FeatureIn(name="导出对账单", module="支付模块", categories=["export_data"]),
    ])

    # 溯源文本应保持不变: 追加功能不应让既有需求指向别的功能
    assert labels() == before


def test_regenerate_marks_removed_input_obsolete(session):
    """输入实体被删除后, 对应需求本轮未命中 → 标 obsolete 而非硬删(#66)。"""
    project = add_base_project(session)
    replace_features(session, project.id, _features())
    engine = RuleEngine(load_knowledge_base())
    first = engine.generate_and_save(RequirementContext.from_db(session, project.id), session)
    removed_req_ids = {
        r.req_id for r in first
        if r.source_entity_type == "feature"
        and r.source_label and "登录" in r.source_label
    }
    assert removed_req_ids, "前置条件: 被删功能应有对应需求"

    # 删除"登录"后重新生成
    remaining = [f for f in _saved_features_as_in(session, project.id) if f.name != "登录"]
    replace_features(session, project.id, remaining)
    engine.generate_and_save(RequirementContext.from_db(session, project.id), session)

    obsolete = (
        session.query(SecurityRequirement)
        .filter_by(project_id=project.id, status="obsolete")
        .all()
    )
    assert {r.req_id for r in obsolete} == removed_req_ids
    # req_id 唯一约束不被 obsolete 行破坏
    ids = [r.req_id for r in session.query(SecurityRequirement)
           .filter_by(project_id=project.id).all()]
    assert len(ids) == len(set(ids))


def test_deleting_one_row_keeps_other_ids(session):
    """删除中间某一行后, 其余行的主键不应漂移(P0-2 修复护栏)。"""
    project = add_base_project(session)
    replace_features(session, project.id, _features())
    ids_before = _feature_ids_by_name(session, project.id)

    # 删除首行"登录", 保留其余两条(uid 原样回传)
    remaining = [f for f in _saved_features_as_in(session, project.id) if f.name != "登录"]
    replace_features(session, project.id, remaining)

    ids_after = _feature_ids_by_name(session, project.id)
    for name in ("转账", "账单查询"):
        assert ids_before[name] == ids_after[name], (
            f"未修改的功能『{name}』主键发生漂移: "
            f"{ids_before[name]} → {ids_after[name]}"
        )


def test_requirement_still_points_to_same_feature_after_deletion(session):
    """删除一个功能后, 其余功能对应的需求仍应溯源到同名功能(P0-2 修复护栏)。"""
    project = add_base_project(session)
    replace_features(session, project.id, _features())

    engine = RuleEngine(load_knowledge_base())
    engine.generate_and_save(RequirementContext.from_db(session, project.id), session)

    reqs = (
        session.query(SecurityRequirement)
        .filter_by(project_id=project.id, source_entity_type="feature")
        .all()
    )
    assert reqs, "前置条件: 应有来源于功能的需求"
    # req_id → 来源功能名(按 uid 解析)
    features_by_uid = {f.uid: f for f in session.query(Feature).all()}
    before = {
        r.req_id: (features_by_uid.get(r.source_entity_uid).name
                   if features_by_uid.get(r.source_entity_uid) else None)
        for r in reqs
    }

    # 删除首行"登录"(uid 原样回传其余行)
    replace_features(session, project.id,
                     [f for f in _saved_features_as_in(session, project.id) if f.name != "登录"])

    after = {
        r.req_id: (features_by_uid.get(r.source_entity_uid).name
                   if features_by_uid.get(r.source_entity_uid) else None)
        for r in session.query(SecurityRequirement)
        .filter_by(project_id=project.id, source_entity_type="feature")
    }
    # 仍然存活的功能(转账/账单查询)对应的需求, 溯源结果不应改变
    survivors = {k: v for k, v in before.items() if v != "登录"}
    assert {k: after.get(k) for k in survivors} == survivors


def test_sensitive_asset_link_survives_asset_resave(session):
    """接口关联的数据资产, 在数据字典重新保存后仍应指向同一资产(P0-2 修复护栏)。"""
    project = add_base_project(session)
    assets = [
        DataAssetIn(name="客户信息表", data_type="customer_data",
                    classification="4级_C3鉴别信息", is_pii=True),
        DataAssetIn(name="交易流水表", data_type="transaction_data",
                    classification="3级_C2主要信息"),
    ]
    replace_data_assets(session, project.id, assets)
    target = (session.query(DataAsset)
              .filter_by(project_id=project.id, name="客户信息表").first())

    session.add(ApiEndpoint(
        project_id=project.id, name="查询客户", path="/api/customer", method="GET",
        auth_required=True, public_exposed=False, sensitive_asset_uids=[target.uid],
    ))
    session.commit()

    # 追加一张表后重新保存数据字典(已有资产 uid 原样回传)
    saved = session.query(DataAsset).filter_by(project_id=project.id).order_by(DataAsset.id)
    saved_in = [
        DataAssetIn(
            uid=a.uid, name=a.name, data_type=a.data_type, classification=a.classification,
            is_pii=a.is_pii, is_sensitive_pii=a.is_sensitive_pii,
            tables=[
                DataTableIn(table_name=t.table_name, fields=[
                    DataFieldIn(field_name=fd.field_name, field_type=fd.field_type,
                                need_encrypt=fd.need_encrypt, need_mask=fd.need_mask,
                                mask_rule=fd.mask_rule)
                    for fd in t.fields
                ])
                for t in a.tables
            ],
        )
        for a in saved
    ]
    replace_data_assets(session, project.id, saved_in + [
        DataAssetIn(name="操作日志表", data_type="log_data",
                    classification="2级_C1次要信息",
                    tables=[DataTableIn(table_name="t_audit_log")]),
    ])

    ep = session.query(ApiEndpoint).filter_by(project_id=project.id).first()
    linked = session.query(DataAsset).filter(
        DataAsset.project_id == project.id,
        DataAsset.uid.in_(ep.sensitive_asset_uids or []),
    ).all()
    assert [a.name for a in linked] == ["客户信息表"], (
        f"接口关联漂移到了: {[a.name for a in linked]}"
    )
