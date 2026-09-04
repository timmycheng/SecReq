# -*- coding: utf-8 -*-
"""向导各步骤数据保存(按稳定 uid 的整卷 upsert, #66)。

前端每次提交该步骤的完整列表; 提交行带 uid 且库中存在 → 原行更新(主键不变),
无 uid → 新建, 库中有而提交缺失 → 删除。这样反复保存与增删改都不再让自增主键
漂移, 已生成需求的 source_entity_uid 溯源保持稳定。

配套守卫: 项目已生成需求、提交行却全部无 uid 时抛 UidContinuityError(路由层转
409) —— 静默接受会把"新增"当成"整卷替换", 溯源再次断裂, 宁可失败。

数据资产三级结构(资产→表→字段): 资产按 uid 匹配, 资产内按 table_name、
表内按 field_name 匹配, 同样"匹配则更新、缺失则删、新增则建"。
定时级问卷在同文件 services/grading.py。
"""

import base64
import re

from sqlalchemy.orm import Session

from models import (
    ApiEndpoint, AuthConfig, DataAsset, DataField, DataTable, Feature,
    InfraArchImage, InfraAsset, PermissionEntry, Project, SecurityRequirement,
    SbomComponent, VulnerabilityRecord, Resource, Role,
)
from models.database import gen_uid
from schemas.component import ComponentIn
from schemas.data_dictionary import DataAssetIn
from schemas.feature import FeatureIn
from schemas.inventory import ApiEndpointIn, InfraAssetIn
from schemas.permission import PermissionMatrixIn
from services.sbom import ecosystem_from_purl


class MatrixIndexError(Exception):
    """权限矩阵 entry 引用了不存在的角色/资源下标。"""


class UidContinuityError(Exception):
    """项目已有生成记录, 但提交行全部缺少 uid(前端版本过旧或数据被手工篡改)。"""


def _guard_uid_continuity(session: Session, project_id: int, items: list, uid_of) -> None:
    """已有生成记录 + 提交行全无 uid → 拒绝(路由层转 409), 不静默断链(#66)。"""
    if not items:
        return
    if any(uid_of(item) for item in items):
        return
    has_generated = (
        session.query(SecurityRequirement.id)
        .filter_by(project_id=project_id)
        .first()
        is not None
    )
    if has_generated:
        raise UidContinuityError(
            "项目已生成需求, 但本次提交的全部行都缺少稳定标识(uid): "
            "可能是页面版本过旧, 请刷新页面重新打开向导后再保存"
        )


def _guard_system_uid_continuity(session: Session, system_id: int, items: list, uid_of) -> None:
    """系统清单版守卫(#194): 该系统下任一轮已生成需求 + 提交行全无 uid → 拒绝。

    系统清单(基础设施/组件)被多轮生成的需求以 source_entity_uid 溯源,
    整卷替换语义下静默接受无 uid 提交会与轮次守卫同样地断裂溯源。
    """
    if not items:
        return
    if any(uid_of(item) for item in items):
        return
    has_generated = (
        session.query(SecurityRequirement.id)
        .join(Project, SecurityRequirement.project_id == Project.id)
        .filter(Project.system_id == system_id)
        .first()
        is not None
    )
    if has_generated:
        raise UidContinuityError(
            "该系统已有评估生成过需求, 但本次提交的全部行都缺少稳定标识(uid): "
            "可能是页面版本过旧, 请刷新页面后重试"
        )


def _sync_rows(session: Session, scope_id: int, model, items: list, fields_of,
               uid_of, scope_field: str = "project_id") -> tuple[int, list]:
    """通用 uid upsert: 返回 (保留/更新的已有行, 全部落库后的实体行)。

    items 为空时表示清空该步骤(合法操作, 不受 uid 守卫约束)。
    scope_field 决定挂靠外键: 轮次实体用 project_id, 系统清单(#194)用 system_id。
    """
    if scope_field == "system_id":
        _guard_system_uid_continuity(session, scope_id, items, uid_of)
    else:
        _guard_uid_continuity(session, scope_id, items, uid_of)
    existing = {
        row.uid: row
        for row in session.query(model).filter_by(**{scope_field: scope_id})
    }
    submitted_uids: set[str] = set()
    kept: list = []
    for item in items:
        uid = uid_of(item)
        if uid and uid in existing:
            row = existing[uid]
            for key, value in fields_of(item).items():
                setattr(row, key, value)
            submitted_uids.add(uid)
            kept.append(row)
        else:
            row = model(**{scope_field: scope_id}, uid=uid or gen_uid(), **fields_of(item))
            session.add(row)
            kept.append(row)
            if uid:
                # 提交了 uid 但库中不存在: 视为用户新增时自带标识, 保留之
                submitted_uids.add(uid)
    removed = [row for uid, row in existing.items() if uid not in submitted_uids]
    for row in removed:
        session.delete(row)
    return kept, removed


def replace_features(session: Session, project_id: int, items: list[FeatureIn]) -> int:
    def uid_of(item: FeatureIn):
        return item.uid

    def fields_of(item: FeatureIn):
        return {
            "name": item.name, "module": item.module, "description": item.description,
            "categories": item.categories, "sensitivity": item.sensitivity,
            "involves_payment": item.involves_payment,
            "exposed_to_internet": item.exposed_to_internet,
        }

    _sync_rows(session, project_id, Feature, items, fields_of, uid_of)
    session.commit()
    return len(items)


def replace_data_assets(session: Session, project_id: int, items: list[DataAssetIn]) -> int:
    """资产按 uid 匹配; 表按 table_name、字段按 field_name 在各自父级内匹配。"""
    _guard_uid_continuity(session, project_id, items, lambda a: a.uid)
    existing_assets = {
        a.uid: a for a in session.query(DataAsset).filter_by(project_id=project_id)
    }
    submitted_asset_uids: set[str] = set()
    total_tables = 0

    for a in items:
        asset_fields = {
            "name": a.name, "data_type": a.data_type, "classification": a.classification,
            "c3_tag": a.c3_tag, "is_pii": a.is_pii, "is_sensitive_pii": a.is_sensitive_pii,
            "storage_envs": a.storage_envs, "cross_border_transfer": a.cross_border_transfer,
        }
        if a.uid and a.uid in existing_assets:
            asset = existing_assets[a.uid]
            for key, value in asset_fields.items():
                setattr(asset, key, value)
        else:
            asset = DataAsset(project_id=project_id, uid=a.uid or gen_uid(), **asset_fields)
            session.add(asset)
            session.flush()
        submitted_asset_uids.add(asset.uid)

        # ── 表: 按 table_name 匹配 ──
        existing_tables = {t.table_name: t for t in asset.tables}
        submitted_tables: set[str] = set()
        for t in a.tables:
            table = existing_tables.get(t.table_name)
            if table is None:
                table = DataTable(asset_id=asset.id, table_name=t.table_name)
                session.add(table)
                session.flush()
            submitted_tables.add(t.table_name)
            total_tables += 1

            # ── 字段: 按 field_name 匹配 ──
            existing_fields = {f.field_name: f for f in table.fields}
            submitted_fields: set[str] = set()
            for fd in t.fields:
                field = existing_fields.get(fd.field_name)
                field_attrs = {
                    "field_type": fd.field_type, "need_encrypt": fd.need_encrypt,
                    "need_mask": fd.need_mask, "mask_rule": fd.mask_rule,
                }
                if field is None:
                    session.add(DataField(table_id=table.id, field_name=fd.field_name, **field_attrs))
                else:
                    for key, value in field_attrs.items():
                        setattr(field, key, value)
                submitted_fields.add(fd.field_name)
            for name, field in existing_fields.items():
                if name not in submitted_fields:
                    session.delete(field)

        for name, table in existing_tables.items():
            if name not in submitted_tables:
                session.delete(table)

    # 删除提交中缺失的资产(cascade 清理其表/字段)
    removed_assets = [
        a for uid, a in existing_assets.items() if uid not in submitted_asset_uids
    ]
    for asset in removed_assets:
        session.delete(asset)
    session.commit()
    return total_tables


def replace_permission_matrix(session: Session, project_id: int, matrix: PermissionMatrixIn) -> dict:
    """整卷 upsert 角色/资源(按 uid)与授权单元格(身份= (role_uid, resource_uid, action))。

    entry 仍用提交体下标定位角色与资源; 角色与资源行按 uid 复用,
    因此 PermissionEntry.role_id/resource_id 外键对已生成需求保持稳定。
    """
    _guard_uid_continuity(session, project_id, matrix.roles, lambda r: r.uid)
    _guard_uid_continuity(session, project_id, matrix.resources, lambda r: r.uid)

    def _upsert(model, items, fields_of):
        existing = {r.uid: r for r in session.query(model).filter_by(project_id=project_id)}
        submitted: set[str] = set()
        rows: list = []
        for item in items:
            attrs = fields_of(item)
            if item.uid and item.uid in existing:
                row = existing[item.uid]
                for key, value in attrs.items():
                    setattr(row, key, value)
            else:
                row = model(project_id=project_id, uid=item.uid or gen_uid(), **attrs)
                session.add(row)
            submitted.add(row.uid)
            rows.append(row)
        for uid, row in existing.items():
            if uid not in submitted:
                session.delete(row)
        session.flush()
        return rows

    roles = _upsert(Role, matrix.roles, lambda r: {
        "name": r.name, "role_type": r.role_type,
        "user_count_estimate": r.user_count_estimate,
    })
    resources = _upsert(Resource, matrix.resources, lambda r: {
        "name": r.name, "resource_type": r.resource_type, "criticality": r.criticality,
    })

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
    # 单元格身份 = (角色uid, 资源uid, action): 重建 entries 不影响溯源复合键
    old_role_ids = [r.id for r in roles] + [
        r.id for r in session.query(Role).filter_by(project_id=project_id)
    ]
    session.query(PermissionEntry).filter(
        PermissionEntry.role_id.in_(old_role_ids)).delete(synchronize_session=False)
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
    session: Session, system_id: int, items: list[ComponentIn], source_type: str = "manual_input",
) -> int:
    """组件按 uid upsert(#194 起挂系统); 被移除组件的漏洞记录随之清理, 保留组件的漏洞缓存不动。"""

    def uid_of(item: ComponentIn):
        return item.uid

    def fields_of(item: ComponentIn):
        return {
            "layer": item.layer, "name": item.name, "version": item.version,
            "purl": item.purl or None, "license": item.license or None,
            "ecosystem": item.ecosystem or None, "distro": item.distro or None,
            "source_type": source_type,
        }

    kept, removed = _sync_rows(
        session, system_id, SbomComponent, items, fields_of, uid_of, scope_field="system_id")
    session.flush()
    _purge_components(session, [row.id for row in removed])
    session.commit()
    return len(items)


def append_components(
    session: Session, system_id: int, rows: list[dict],
) -> tuple[int, int]:
    """SBOM 文件导入走追加语义: 按 组件名+版本 去重跳过已有条目(#194 起挂系统)。

    返回 (新增数, 跳过的重复数)。rows 形态见 services/sbom_import.parse_sbom_file。
    新行 uid 由模型默认值(UUID4)生成。
    """
    existing = {
        (c.name.casefold(), c.version)
        for c in session.query(SbomComponent).filter_by(system_id=system_id)
    }
    added = skipped = 0
    for row in rows:
        key = (str(row["name"]).casefold(), row["version"])
        if key in existing:
            skipped += 1
            continue
        existing.add(key)
        session.add(SbomComponent(
            system_id=system_id,
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
    """Step1 外部系统连接清单(按 uid 整卷 upsert)。items 为 schemas.project.ExternalSystemIn。"""
    from models import ExternalSystem

    def fields_of(item):
        return {
            "name": item.name, "purpose": item.purpose,
            "direction": item.direction, "involves_sensitive": item.involves_sensitive,
        }

    _sync_rows(session, project_id, ExternalSystem, items, fields_of, lambda i: i.uid)
    session.commit()
    return len(items)


def replace_api_endpoints(session: Session, project_id: int, endpoints: list[ApiEndpointIn]) -> int:
    def fields_of(item: ApiEndpointIn):
        return {
            "name": item.name, "path": item.path, "method": item.method,
            "auth_required": item.auth_required, "public_exposed": item.public_exposed,
            "sensitive_asset_ids": item.sensitive_asset_ids,
            "sensitive_asset_uids": item.sensitive_asset_uids,
            "rate_limit": item.rate_limit,
        }

    _sync_rows(session, project_id, ApiEndpoint, endpoints, fields_of, lambda i: i.uid)
    session.commit()
    return len(endpoints)


def replace_infra_assets(session: Session, system_id: int, infra_assets: list[InfraAssetIn]) -> int:
    """基础设施清单整卷保存(#194 起挂系统, 多轮共享)。"""
    def fields_of(item: InfraAssetIn):
        return {
            "asset_type": item.asset_type, "name": item.name, "env": item.env,
            "ip": item.ip, "owner": item.owner, "holds_sensitive": item.holds_sensitive,
            "cpu_cores": item.cpu_cores, "memory_gb": item.memory_gb,
            "disk_gb": item.disk_gb, "os": item.os, "quantity": item.quantity,
            "purpose": item.purpose,
            "netbox_ref_type": item.netbox_ref_type, "netbox_ref_id": item.netbox_ref_id,
        }

    _sync_rows(session, system_id, InfraAsset, infra_assets, fields_of,
               lambda i: i.uid, scope_field="system_id")
    session.commit()
    return len(infra_assets)


# ── 架构图(#164, #194 起挂系统): 校验与落库收口到本模块, 供向导/系统双路由共用 ──
_ARCH_DATA_URL_RE = re.compile(r"data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/=]+)")
MAX_ARCH_IMAGE_BYTES = 2 * 1024 * 1024


class ArchImageError(Exception):
    """架构图 data URL 非法或超限(路由层转 400/413)。"""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def validate_arch_image_data_url(data_url: str) -> None:
    """仅接受 png/jpg/webp 的 base64 data URL, 原图 ≤2MB。"""
    m = _ARCH_DATA_URL_RE.fullmatch(data_url or "")
    if not m:
        raise ArchImageError("仅支持 png/jpg/webp 图片的 data URL")
    try:
        raw = base64.b64decode(m.group(2), validate=True)
    except ValueError as exc:
        raise ArchImageError("图片 base64 编码无效") from exc
    if len(raw) > MAX_ARCH_IMAGE_BYTES:
        raise ArchImageError(
            f"架构图过大, 上限 {MAX_ARCH_IMAGE_BYTES // (1024 * 1024)} MB", status_code=413)


def list_arch_images(session: Session, system_id: int) -> list:
    return session.query(InfraArchImage).filter_by(system_id=system_id).all()


def upsert_arch_image(session: Session, system_id: int, env: str, image_data_url: str):
    """每环境一张(唯一约束兜底), 已有则覆盖。"""
    validate_arch_image_data_url(image_data_url)
    row = session.query(InfraArchImage).filter_by(system_id=system_id, env=env).first()
    if row is None:
        row = InfraArchImage(system_id=system_id, env=env, image_data_url=image_data_url)
        session.add(row)
    else:
        row.image_data_url = image_data_url
    session.commit()
    return row


def delete_arch_image(session: Session, system_id: int, env: str) -> bool:
    row = session.query(InfraArchImage).filter_by(system_id=system_id, env=env).first()
    if row is None:
        return False
    session.delete(row)
    session.commit()
    return True
