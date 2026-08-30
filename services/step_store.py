# -*- coding: utf-8 -*-
"""向导各步骤数据保存(整体替换语义)。

前端每次提交该步骤的完整列表, 本模块按外键顺序清旧写新, 保证幂等:
同一项目反复保存不会产生重复行。定时级问卷在同文件 services/grading.py。
"""
from sqlalchemy.orm import Session

from models import (
    ApiEndpoint, AuthConfig, DataAsset, DataField, DataTable, Feature,
    InfraAsset, PermissionEntry, SbomComponent, VulnerabilityRecord,
    Resource, Role,
)
from schemas.component import ComponentIn
from schemas.data_dictionary import DataAssetIn
from schemas.feature import FeatureIn
from schemas.inventory import ApiEndpointIn, InfraAssetIn
from schemas.permission import PermissionMatrixIn
from services.sbom import ecosystem_from_purl


class MatrixIndexError(Exception):
    """权限矩阵 entry 引用了不存在的角色/资源下标。"""


def replace_features(session: Session, project_id: int, items: list[FeatureIn]) -> int:
    session.query(Feature).filter_by(project_id=project_id).delete()
    session.add_all(
        Feature(
            project_id=project_id,
            name=f.name,
            module=f.module,
            description=f.description,
            categories=f.categories,
            sensitivity=f.sensitivity,
            involves_payment=f.involves_payment,
            exposed_to_internet=f.exposed_to_internet,
        )
        for f in items
    )
    session.commit()
    return len(items)


def replace_data_assets(session: Session, project_id: int, items: list[DataAssetIn]) -> int:
    asset_ids = [a.id for a in session.query(DataAsset.id).filter_by(project_id=project_id)]
    if asset_ids:
        session.query(DataField).filter(
            DataField.table_id.in_(session.query(DataTable.id).filter(
                DataTable.asset_id.in_(asset_ids)))
        ).delete(synchronize_session=False)
        session.query(DataTable).filter(DataTable.asset_id.in_(asset_ids)).delete(
            synchronize_session=False)
        session.query(DataAsset).filter_by(project_id=project_id).delete(
            synchronize_session=False)

    total_tables = 0
    for a in items:
        asset = DataAsset(
            project_id=project_id,
            name=a.name, data_type=a.data_type, classification=a.classification,
            c3_tag=a.c3_tag,
            is_pii=a.is_pii, is_sensitive_pii=a.is_sensitive_pii,
            storage_envs=a.storage_envs, cross_border_transfer=a.cross_border_transfer,
        )
        session.add(asset)
        session.flush()
        for t in a.tables:
            table = DataTable(asset_id=asset.id, table_name=t.table_name)
            session.add(table)
            session.flush()
            total_tables += 1
            session.add_all(
                DataField(
                    table_id=table.id, field_name=fd.field_name, field_type=fd.field_type,
                    need_encrypt=fd.need_encrypt, need_mask=fd.need_mask,
                    mask_rule=fd.mask_rule,
                )
                for fd in t.fields
            )
    session.commit()
    return total_tables


def replace_permission_matrix(session: Session, project_id: int, matrix: PermissionMatrixIn) -> dict:
    """整体替换角色/资源/授权单元格。entry 用提交体下标定位角色与资源。"""
    old_role_ids = [r.id for r in session.query(Role.id).filter_by(project_id=project_id)]
    if old_role_ids:
        session.query(PermissionEntry).filter(
            PermissionEntry.role_id.in_(old_role_ids)).delete(synchronize_session=False)
    session.query(Role).filter_by(project_id=project_id).delete(synchronize_session=False)
    session.query(Resource).filter_by(project_id=project_id).delete(synchronize_session=False)

    roles = [
        Role(project_id=project_id, name=r.name, role_type=r.role_type,
             user_count_estimate=r.user_count_estimate)
        for r in matrix.roles
    ]
    resources = [
        Resource(project_id=project_id, name=r.name, resource_type=r.resource_type,
                 criticality=r.criticality)
        for r in matrix.resources
    ]
    session.add_all(roles + resources)
    session.flush()

    n_roles, n_res = len(roles), len(resources)
    entries = []
    for e in matrix.entries:
        if e.role_index >= n_roles or e.resource_index >= n_res:
            raise MatrixIndexError(
                f"授权单元格引用越界: role_index={e.role_index}, resource_index={e.resource_index}")
        entries.append(PermissionEntry(
            role_id=roles[e.role_index].id,
            resource_id=resources[e.resource_index].id,
            action=e.action,
            requires_approval=e.requires_approval,
        ))
    # 同格子同操作去重(后端兜底, 数据库另有 UNIQUE 约束)
    unique = {(p.role_id, p.resource_id, p.action): p for p in entries}
    session.add_all(unique.values())
    session.commit()
    return {"roles": n_roles, "resources": n_res, "entries": len(unique)}


def upsert_auth_config(session: Session, project_id: int, cfg_in) -> AuthConfig:
    """Step6 为单行 upsert; 传 None 值表示该项回退定级默认基线(policy.py 口径)。"""
    cfg = session.query(AuthConfig).filter_by(project_id=project_id).first()
    fields = cfg_in.model_dump() if hasattr(cfg_in, "model_dump") else dict(cfg_in)
    if cfg is None:
        cfg = AuthConfig(project_id=project_id, **fields)
        session.add(cfg)
    else:
        for key, value in fields.items():
            setattr(cfg, key, value)
    session.commit()
    return cfg


def _purge_components(session: Session, component_ids: list[int]) -> None:
    if not component_ids:
        return
    session.query(VulnerabilityRecord).filter(
        VulnerabilityRecord.component_id.in_(component_ids)
    ).delete(synchronize_session=False)


def replace_components(
    session: Session, project_id: int, items: list[ComponentIn], source_type: str = "manual_input",
) -> int:
    old_ids = [c.id for c in session.query(SbomComponent.id).filter_by(project_id=project_id)]
    _purge_components(session, old_ids)
    session.query(SbomComponent).filter_by(project_id=project_id).delete(
        synchronize_session=False)
    session.add_all(
        SbomComponent(
            project_id=project_id, layer=c.layer, name=c.name, version=c.version,
            purl=c.purl or None, license=c.license or None, source_type=source_type,
            ecosystem=c.ecosystem or None, distro=c.distro or None,
        )
        for c in items
    )
    session.commit()
    return len(items)


def append_components(
    session: Session, project_id: int, rows: list[dict],
) -> tuple[int, int]:
    """SBOM 文件导入走追加语义: 按 组件名+版本 去重跳过已有条目。

    返回 (新增数, 跳过的重复数)。rows 形态见 services/sbom_import.parse_sbom_file。
    """
    existing = {
        (c.name.casefold(), c.version)
        for c in session.query(SbomComponent).filter_by(project_id=project_id)
    }
    added = skipped = 0
    for row in rows:
        key = (str(row["name"]).casefold(), row["version"])
        if key in existing:
            skipped += 1
            continue
        existing.add(key)
        session.add(SbomComponent(
            project_id=project_id,
            layer=row.get("layer") or "library",
            name=row["name"],
            version=row["version"],
            purl=row.get("purl") or None,
            license=row.get("license") or None,
            source_type="sbom_file",
            # SBOM 文件里的 purl 是权威坐标, 优先从它反推生态,
            # 避免导入的组件落到"未指定生态"而只能走模糊匹配
            ecosystem=row.get("ecosystem") or ecosystem_from_purl(row.get("purl")),
        ))
        added += 1
    session.commit()
    return added, skipped


def replace_external_systems(
    session: Session, project_id: int, items: list,
) -> int:
    """Step1 外部系统连接清单(整体替换)。items 为 schemas.project.ExternalSystemIn。"""
    from models import ExternalSystem

    session.query(ExternalSystem).filter_by(project_id=project_id).delete()
    session.add_all(
        ExternalSystem(
            project_id=project_id, name=e.name, purpose=e.purpose,
            direction=e.direction, involves_sensitive=e.involves_sensitive,
        )
        for e in items
    )
    session.commit()
    return len(items)


def replace_api_endpoints(session: Session, project_id: int, endpoints: list[ApiEndpointIn]) -> int:
    session.query(ApiEndpoint).filter_by(project_id=project_id).delete()
    session.add_all(
        ApiEndpoint(
            project_id=project_id, name=e.name, path=e.path, method=e.method,
            auth_required=e.auth_required, public_exposed=e.public_exposed,
            sensitive_asset_ids=e.sensitive_asset_ids, rate_limit=e.rate_limit,
        )
        for e in endpoints
    )
    session.commit()
    return len(endpoints)


def replace_infra_assets(session: Session, project_id: int, infra_assets: list[InfraAssetIn]) -> int:
    session.query(InfraAsset).filter_by(project_id=project_id).delete()
    session.add_all(
        InfraAsset(
            project_id=project_id, asset_type=a.asset_type, name=a.name, env=a.env,
            ip=a.ip, owner=a.owner, holds_sensitive=a.holds_sensitive,
            cpu_cores=a.cpu_cores, memory_gb=a.memory_gb, disk_gb=a.disk_gb,
            os=a.os, quantity=a.quantity, purpose=a.purpose,
        )
        for a in infra_assets
    )
    session.commit()
    return len(infra_assets)
