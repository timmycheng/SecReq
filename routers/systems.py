# -*- coding: utf-8 -*-
"""被评估系统 CRUD 与台账: 系统列表(台账视角) / 详情(评估时间线) / 系统清单维护。

数据权限与项目一致: 开发(developer)仅见/操作本人创建的系统, 安全(security)全量;
越权访问按 404 处理, 不泄露存在性。#194 起基础设施/组件/架构图挂系统维护,
与向导内的项目路由(/api/projects/{id}/...)同源同权限, 只是入口不同。
"""
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

from models import InfraAsset, PlatformUser, SbomComponent, System
from routers.common import (
    client_ip, component_to_out, get_db, read_upload_limited, require_login,
    require_write_roles,
)
from schemas.component import ComponentsSaveIn, ComponentOut, SbomImportResult
from schemas.inventory import (
    InfraArchImageIn, InfraArchImageOut, InfraAssetListIn, InfraAssetOut,
)
from schemas.system import SystemCreate, SystemDetail, SystemUpdate
from services.audit_service import audit
from services.sbom_import import SbomParseError, import_sbom_file
from services.step_store import (
    ArchImageError, UidContinuityError, delete_arch_image, list_arch_images,
    replace_components, replace_infra_assets, upsert_arch_image,
)
from services.system_service import (
    InUseError, NameConflictError, create_system, delete_system,
    system_detail, systems_ledger, update_system, visible_systems_query,
)

router = APIRouter(prefix="/api/systems", tags=["systems"])

_writable = Depends(require_write_roles("developer", "security"))

_ARCH_ENVS = ("test", "prod", "dev")


def _get_accessible_system(system_id: int, db: Session, user: PlatformUser) -> System:
    system = db.get(System, system_id)
    if system is None or (
        user.role != "security" and system.owner_user_id not in (None, user.id)
    ):
        raise HTTPException(status_code=404, detail=f"系统不存在: id={system_id}")
    return system


@router.get("/ledger")
def ledger(db: Session = Depends(get_db), user: PlatformUser = Depends(require_login)):
    """系统视角台账: 系统 × 所属备案/定级 × 最新轮次结论 × 遗留未闭环 × 当前基线。"""
    return systems_ledger(db, user)


@router.get("", response_model=list[SystemDetail])
def list_all(db: Session = Depends(get_db), user: PlatformUser = Depends(require_login)):
    """系统列表(含所属备案与定级, 供下拉选择与台账)。"""
    items = []
    for system in visible_systems_query(db, user).all():
        items.append(SystemDetail(**system_detail(db, user, system)))
    return items


@router.post("", response_model=SystemDetail, status_code=201, dependencies=[_writable])
def create(payload: SystemCreate, request: Request, db: Session = Depends(get_db),
           user: PlatformUser = Depends(require_write_roles("developer", "security"))):
    try:
        system = create_system(db, payload.model_dump(), owner_user_id=user.id)
    except NameConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    audit(db, user.username, "system_create",
          {"system_id": system.id, "name": system.name}, client_ip(request))
    return SystemDetail(**system_detail(db, user, system))


@router.get("/{system_id}", response_model=SystemDetail)
def get_one(system_id: int, db: Session = Depends(get_db),
            user: PlatformUser = Depends(require_login)):
    system = _get_accessible_system(system_id, db, user)
    return SystemDetail(**system_detail(db, user, system))


@router.patch("/{system_id}", response_model=SystemDetail, dependencies=[_writable])
def patch(payload: SystemUpdate, system_id: int, request: Request,
          db: Session = Depends(get_db),
          user: PlatformUser = Depends(require_write_roles("developer", "security"))):
    system = _get_accessible_system(system_id, db, user)
    try:
        system = update_system(db, system, payload.model_dump(exclude_unset=True))
    except NameConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    audit(db, user.username, "system_update",
          {"system_id": system.id, "name": system.name}, client_ip(request))
    return SystemDetail(**system_detail(db, user, system))


@router.delete("/{system_id}", status_code=204, dependencies=[_writable])
def remove(system_id: int, request: Request,
           db: Session = Depends(get_db),
           user: PlatformUser = Depends(require_write_roles("developer", "security"))):
    system = _get_accessible_system(system_id, db, user)
    try:
        delete_system(db, system.id)
    except InUseError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    audit(db, user.username, "system_delete",
          {"system_id": system_id, "name": system.name}, client_ip(request))


# ── 系统清单(#194): 基础设施 / 组件 / 架构图, 挂系统维护 ──


def _writable_system(system_id: int, db: Session, user: PlatformUser) -> System:
    return _get_accessible_system(system_id, db, user)


@router.get("/{system_id}/infra-assets", response_model=list[InfraAssetOut])
def get_infra_assets(system_id: int, db: Session = Depends(get_db),
                     user: PlatformUser = Depends(require_login)):
    system = _get_accessible_system(system_id, db, user)
    rows = (db.query(InfraAsset).filter_by(system_id=system.id)
            .order_by(InfraAsset.id).all())
    return [InfraAssetOut.model_validate(a) for a in rows]


@router.post("/{system_id}/infra-assets", response_model=list[InfraAssetOut])
def save_infra_assets(system_id: int, payload: InfraAssetListIn, request: Request,
                      db: Session = Depends(get_db),
                      user: PlatformUser = Depends(require_write_roles("developer", "security"))):
    system = _writable_system(system_id, db, user)
    try:
        replace_infra_assets(db, system.id, payload.assets)
    except UidContinuityError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    audit(db, user.username, "system_infra_save",
          {"system_id": system.id, "count": len(payload.assets)}, client_ip(request))
    rows = (db.query(InfraAsset).filter_by(system_id=system.id)
            .order_by(InfraAsset.id).all())
    return [InfraAssetOut.model_validate(a) for a in rows]


@router.get("/{system_id}/components", response_model=list[ComponentOut])
def get_components(system_id: int, db: Session = Depends(get_db),
                   user: PlatformUser = Depends(require_login)):
    system = _get_accessible_system(system_id, db, user)
    comps = (db.query(SbomComponent).filter_by(system_id=system.id)
             .order_by(SbomComponent.id).all())
    return [component_to_out(c) for c in comps]


@router.post("/{system_id}/components", response_model=list[ComponentOut])
def save_components(system_id: int, payload: ComponentsSaveIn, request: Request,
                    db: Session = Depends(get_db),
                    user: PlatformUser = Depends(require_write_roles("developer", "security"))):
    system = _writable_system(system_id, db, user)
    try:
        replace_components(db, system.id, payload.components)
    except UidContinuityError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    audit(db, user.username, "system_components_save",
          {"system_id": system.id, "count": len(payload.components)}, client_ip(request))
    comps = (db.query(SbomComponent).filter_by(system_id=system.id)
             .order_by(SbomComponent.id).all())
    return [component_to_out(c) for c in comps]


@router.post("/{system_id}/components/import-sbom", response_model=SbomImportResult)
async def import_sbom(system_id: int, request: Request,
                      db: Session = Depends(get_db),
                      file: UploadFile = File(...),
                      user: PlatformUser = Depends(require_write_roles("developer", "security"))):
    """上传 CycloneDX/SPDX 格式 SBOM 文件批量导入(挂系统清单)。"""
    system = _writable_system(system_id, db, user)
    if not file.filename or not file.filename.lower().endswith(
            (".json", ".spdx", ".cdx.json")):
        raise HTTPException(status_code=400, detail="请上传 .json(CycloneDX/SPDX JSON) 或 .spdx 文件")
    payload = await read_upload_limited(file)
    try:
        result = import_sbom_file(db, system.id, file.filename, payload)
    except SbomParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit(db, user.username, "system_sbom_import",
          {"system_id": system.id, "added": result.added}, client_ip(request))
    return result


@router.get("/{system_id}/arch-images", response_model=list[InfraArchImageOut])
def get_arch_images(system_id: int, db: Session = Depends(get_db),
                    user: PlatformUser = Depends(require_login)):
    system = _get_accessible_system(system_id, db, user)
    return [InfraArchImageOut.model_validate(r) for r in list_arch_images(db, system.id)]


@router.put("/{system_id}/arch-images/{env}", response_model=InfraArchImageOut)
def upload_arch_image(system_id: int, env: str, payload: InfraArchImageIn, request: Request,
                      db: Session = Depends(get_db),
                      user: PlatformUser = Depends(require_write_roles("developer", "security"))):
    system = _writable_system(system_id, db, user)
    if env not in _ARCH_ENVS:
        raise HTTPException(status_code=404, detail=f"未知环境: {env}")
    try:
        row = upsert_arch_image(db, system.id, env, payload.image_data_url)
    except ArchImageError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    audit(db, user.username, "system_arch_image",
          {"system_id": system.id, "env": env}, client_ip(request))
    return InfraArchImageOut.model_validate(row)


@router.delete("/{system_id}/arch-images/{env}")
def remove_arch_image(system_id: int, env: str, request: Request,
                      db: Session = Depends(get_db),
                      user: PlatformUser = Depends(require_write_roles("developer", "security"))):
    system = _writable_system(system_id, db, user)
    if env not in _ARCH_ENVS:
        raise HTTPException(status_code=404, detail=f"未知环境: {env}")
    if delete_arch_image(db, system.id, env):
        audit(db, user.username, "system_arch_image_delete",
              {"system_id": system.id, "env": env}, client_ip(request))
    return {"ok": True}
