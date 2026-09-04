# -*- coding: utf-8 -*-
"""评估轮次继承: 从上一轮项目整卷复制向导输入数据。

复制原则:
- 实体 uid 原样保留 —— 同一系统同一实体, 轮次间按 (template_id, source_entity_uid)
  对齐做增量对比正依赖这一点(与 UidContinuityGuard 的设计哲学一致);
- 主键/外键全部重排: 权限条目重挂新角色/资源, 资产关联以 uid 为准,
  旧主键引用(sensitive_asset_ids)置空防悬挂;
- 组件漏洞记录不复制, 生成流水线会按组件重新查询; 复制时同时清空组件上的
  漏洞查询缓存字段, 否则「TTL 内指纹未变→跳过查询」会让新轮次永远查不到漏洞(#169)。
"""
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session

from models import (
    ApiEndpoint, DataAsset, ExternalSystem,
    Feature, InfraArchImage, InfraAsset,
    PermissionEntry, Project, Resource, Role, SbomComponent, VulnerabilityRecord,
)


def _clone(instance, **overrides):
    """按列名复制一行(跳过 id/project_id), 支持 id 重映射覆盖。"""
    exclude = {"id", "project_id"}
    cols = {c.name for c in sa_inspect(type(instance)).columns} - exclude
    kwargs = {name: getattr(instance, name) for name in cols}
    kwargs.update(overrides)
    return type(instance)(**kwargs)


def copy_wizard_data(db: Session, source: Project, target: Project) -> None:
    """把 source 的全部向导步骤数据复制到 target(双方须已落库)。"""
    src, dst = source.id, target.id

    if source.survey:
        db.add(_clone(source.survey, project_id=dst))

    for row in db.query(Feature).filter_by(project_id=src).all():
        db.add(_clone(row, project_id=dst))

    # 数据字典三级: 资产 → 表 → 字段
    asset_id_map: dict[int, int] = {}
    for asset in db.query(DataAsset).filter_by(project_id=src).all():
        tables = asset.tables or []
        db.flush()
        new_asset = _clone(asset, project_id=dst)
        db.add(new_asset)
        db.flush()
        asset_id_map[asset.id] = new_asset.id
        for table in tables:
            fields = table.fields or []
            new_table = _clone(table, asset_id=new_asset.id)
            db.add(new_table)
            db.flush()
            for field in fields:
                db.add(_clone(field, table_id=new_table.id))

    # 权限矩阵: 角色/资源重挂新主键
    role_id_map: dict[int, int] = {}
    for role in db.query(Role).filter_by(project_id=src).all():
        db.add(role_clone := _clone(role, project_id=dst))
        db.flush()
        role_id_map[role.id] = role_clone.id
    resource_id_map: dict[int, int] = {}
    for res in db.query(Resource).filter_by(project_id=src).all():
        db.add(res_clone := _clone(res, project_id=dst))
        db.flush()
        resource_id_map[res.id] = res_clone.id
    entries = (
        db.query(PermissionEntry)
        .join(Role, PermissionEntry.role_id == Role.id)
        .filter(Role.project_id == src)
        .all()
    )
    for entry in entries:
        db.add(_clone(
            entry,
            role_id=role_id_map[entry.role_id],
            resource_id=resource_id_map[entry.resource_id],
        ))

    if source.auth_config:
        db.add(_clone(source.auth_config, project_id=dst))

    # 基础设施清单与架构图(#164): 拓扑回退后清单整卷复制, 架构图 data URL 随库走
    for asset in db.query(InfraAsset).filter_by(project_id=src).all():
        db.add(_clone(asset, project_id=dst))
    for img in db.query(InfraArchImage).filter_by(project_id=src).all():
        db.add(_clone(img, project_id=dst))

    # 组件与接口(旧资产主键引用置空, 以 uids 为准)。
    # 组件必须清空漏洞查询缓存四件套: 漏洞记录按 component_id 挂表、复制时不带,
    # 若缓存字段原样带过来, sync_vulnerabilities 的「TTL 内且指纹未变→跳过查询」
    # 会立刻命中, 新轮次的漏洞将永远查不到(#169)
    for comp in db.query(SbomComponent).filter_by(project_id=src).all():
        db.add(_clone(
            comp, project_id=dst,
            last_osv_query_at=None, osv_query_fingerprint=None,
            vuln_status=None, vuln_status_note=None,
        ))
    for ep in db.query(ApiEndpoint).filter_by(project_id=src).all():
        db.add(_clone(ep, project_id=dst, sensitive_asset_ids=[]))

    for ext in db.query(ExternalSystem).filter_by(project_id=src).all():
        db.add(_clone(ext, project_id=dst))

    db.commit()


def repair_stale_component_cache(db: Session) -> int:
    """启动自愈(#169): 已复制出来的项目组件带缓存但名下无漏洞记录 → 清缓存强制重查。

    判定「有缓存状态但零漏洞记录」: 正常查过且确无漏洞的组件(status=not_found)被
    清掉也只是多查一次, 无副作用; 而复制受害组件(status=hit 却无记录)由此恢复。
    幂等, 返回修复的组件数。
    """
    cached = (
        db.query(SbomComponent)
        .filter(SbomComponent.last_osv_query_at.isnot(None))
        .all()
    )
    if not cached:
        return 0
    ids_with_records = {
        row[0] for row in db.query(VulnerabilityRecord.component_id).distinct().all()
    }
    repaired = 0
    for comp in cached:
        if comp.id in ids_with_records:
            continue
        comp.last_osv_query_at = None
        comp.osv_query_fingerprint = None
        comp.vuln_status = None
        comp.vuln_status_note = None
        repaired += 1
    db.commit()
    return repaired
