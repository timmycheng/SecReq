# -*- coding: utf-8 -*-
"""被评估系统 CRUD 与台账: 系统列表(台账视角) / 详情(评估时间线)。

数据权限与项目一致: 开发(developer)仅见/操作本人创建的系统, 安全(security)全量;
越权访问按 404 处理, 不泄露存在性。
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from models import PlatformUser, System
from routers.common import client_ip, get_db, require_login, require_write_roles
from schemas.system import SystemCreate, SystemDetail, SystemUpdate
from services.audit_service import audit
from services.system_service import (
    InUseError, NameConflictError, create_system, delete_system,
    system_detail, systems_ledger, update_system, visible_systems_query,
)

router = APIRouter(prefix="/api/systems", tags=["systems"])

_writable = Depends(require_write_roles("developer", "security"))


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
def remove(system_id: int, request: Request, db: Session = Depends(get_db),
           user: PlatformUser = Depends(require_write_roles("developer", "security"))):
    system = _get_accessible_system(system_id, db, user)
    try:
        delete_system(db, system.id)
    except InUseError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    audit(db, user.username, "system_delete",
          {"system_id": system_id, "name": system.name}, client_ip(request))
