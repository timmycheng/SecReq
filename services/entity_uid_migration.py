# -*- coding: utf-8 -*-
"""实体稳定 uid 迁移(v2.3.0, #66): 回填 uid + 存量需求溯源重映射。

发版口径(单向不可逆):
- 执行前必须备份 secreq.db(代码回退需连库一起回退);
- 幂等可重复执行: 已有 uid 的行跳过, 已映射的需求不重复处理;
- 与 lifespan 共用本模块, 容器化部署启动时自动完成, 无感升级。

诚实处理存量脏数据: 整表替换时代已断链的需求(实体已被重建, 按主键找不到
对应实体)不伪造映射 —— 保留 source_label 文本, source_entity_uid 置空,
status 标为 obsolete, 让"整改后消失的风险"可统计、可追溯。
"""
import logging

from sqlalchemy.orm import Session

from models import (
    ApiEndpoint, DataAsset, ExternalSystem, Feature, InfraAsset,
    PermissionEntry, Resource, Role, SbomComponent, SecurityRequirement,
)
from models.database import gen_uid

logger = logging.getLogger(__name__)

# 加了 uid 列且参与溯源重映射的 8 个整表替换实体: type → 模型
_UID_ENTITIES: dict[str, type] = {
    "feature": Feature,
    "data_asset": DataAsset,
    "sbom_component": SbomComponent,
    "role": Role,
    "resource": Resource,
    "api_endpoint": ApiEndpoint,
    "infra_asset": InfraAsset,
    "external_system": ExternalSystem,
}


def _backfill_uids(session: Session) -> dict[str, int]:
    """给 uid 为空的存量行回填 UUID4。返回 {表: 回填行数}。"""
    stats: dict[str, int] = {}
    for etype, model in _UID_ENTITIES.items():
        rows = session.query(model).filter(model.uid.is_(None)).all()
        for row in rows:
            row.uid = gen_uid()
        if rows:
            stats[etype] = len(rows)
    return stats


def _build_id_to_uid(session: Session) -> dict[str, dict[int, str]]:
    """{实体类型: {主键: uid}} 索引, 供需求溯源重映射。"""
    index: dict[str, dict[int, str]] = {}
    for etype, model in _UID_ENTITIES.items():
        index[etype] = {
            row.id: row.uid
            for row in session.query(model).all()
            if row.uid
        }
    return index


def _remap_requirements(session: Session) -> dict[str, int]:
    """把存量需求的 source_entity_id 映射为 source_entity_uid。

    permission_entry 的稳定标识是 (role_uid, resource_uid, action) 复合键;
    角色/资源已随整表替换重建而无法解析的, 按断链处理(标 obsolete)。
    """
    stats = {"mapped": 0, "obsolete": 0, "skipped": 0}
    id_to_uid = _build_id_to_uid(session)
    roles = {r.id: r for r in session.query(Role).all() if r.uid}
    resources = {r.id: r for r in session.query(Resource).all() if r.uid}
    for req in session.query(SecurityRequirement).all():
        if req.source_entity_uid or req.status == "obsolete":
            stats["skipped"] += 1
            continue
        etype = req.source_entity_type
        entity_id = req.source_entity_id
        uid: str | None = None
        if etype == "permission_entry":
            entry = session.get(PermissionEntry, entity_id)
            role = roles.get(entry.role_id) if entry else None
            res = resources.get(entry.resource_id) if entry else None
            if role and res and entry:
                uid = f"{role.uid}|{res.uid}|{entry.action}"
        elif etype in id_to_uid:
            uid = id_to_uid[etype].get(entity_id)
        if uid:
            req.source_entity_uid = uid
            stats["mapped"] += 1
        else:
            # 断链: 实体已随整表替换消失。不伪造映射, 诚实标 obsolete。
            req.source_entity_uid = None
            req.status = "obsolete"
            stats["obsolete"] += 1
    return stats


def _remap_asset_links(session: Session) -> dict[str, int]:
    """ApiEndpoint.sensitive_asset_ids(主键数组) → sensitive_asset_uids。"""
    stats = {"mapped": 0, "dropped": 0}
    asset_uid = {
        a.id: a.uid
        for a in session.query(DataAsset).all()
        if a.uid
    }
    for ep in session.query(ApiEndpoint).all():
        if ep.sensitive_asset_uids:
            continue
        mapped: list[str] = []
        for aid in ep.sensitive_asset_ids or []:
            uid = asset_uid.get(aid)
            if uid:
                mapped.append(uid)
            else:
                stats["dropped"] += 1
        ep.sensitive_asset_uids = mapped
        if mapped:
            stats["mapped"] += 1
    return stats


def migrate_entity_uids(session: Session, dry_run: bool = False) -> dict:
    """执行 uid 回填与溯源重映射, 返回统计报告; 幂等可重复执行。"""
    stats: dict = {"dry_run": dry_run}
    if dry_run:
        # 干跑只统计, 不写任何属性
        pending_uid = sum(
            session.query(model).filter(model.uid.is_(None)).count()
            for model in _UID_ENTITIES.values()
        )
        pending_reqs = (
            session.query(SecurityRequirement)
            .filter(SecurityRequirement.source_entity_uid.is_(None))
            .count()
        )
        stats["rows_without_uid"] = pending_uid
        stats["requirements_pending_remap"] = pending_reqs
        return stats
    stats["uid_backfilled"] = _backfill_uids(session)
    stats.update(_remap_requirements(session))
    stats["asset_links"] = _remap_asset_links(session)
    session.commit()
    logger.info("实体 uid 迁移完成: %s", stats)
    return stats
