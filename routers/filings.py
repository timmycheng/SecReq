# -*- coding: utf-8 -*-
"""定级备案 CRUD。

备案是对外备案测评的少数主体, 属共享台账数据: 登录即可读, 写操作按
向导白名单角色(developer/security)控制, 不做 owner 过滤——开发在建项目
时就地新建备案后, 其他账号也要能选到它。
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from models import Filing, PlatformUser
from routers.common import client_ip, get_db, require_login, require_write_roles
from schemas.system import FilingCreate, FilingDetail, FilingOut, FilingUpdate
from services.audit_service import audit
from services.system_service import (
    InUseError, NameConflictError, create_filing, delete_filing,
    filings_ledger, update_filing,
)

router = APIRouter(prefix="/api/filings", tags=["filings"])

_writable = Depends(require_write_roles("developer", "security"))


def _detail(filing: Filing, system_count: int = 0, latest_round: dict | None = None) -> FilingDetail:
    return FilingDetail(
        **FilingOut.model_validate(filing).model_dump(),
        system_count=system_count, latest_round=latest_round,
    )


@router.get("", response_model=list[FilingDetail])
def list_all(db: Session = Depends(get_db), user: PlatformUser = Depends(require_login)):
    """备案台账(含下挂系统数与最新评估概况)。"""
    return filings_ledger(db)


@router.post("", response_model=FilingDetail, status_code=201, dependencies=[_writable])
def create(payload: FilingCreate, request: Request, db: Session = Depends(get_db),
           user: PlatformUser = Depends(require_write_roles("developer", "security"))):
    try:
        filing = create_filing(db, payload.model_dump())
    except NameConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    audit(db, user.username, "filing_create",
          {"filing_id": filing.id, "name": filing.name, "level": filing.level},
          client_ip(request))
    return _detail(filing)


@router.patch("/{filing_id}", response_model=FilingDetail, dependencies=[_writable])
def patch(payload: FilingUpdate, filing_id: int, request: Request,
          db: Session = Depends(get_db),
          user: PlatformUser = Depends(require_write_roles("developer", "security"))):
    filing = db.get(Filing, filing_id)
    if filing is None:
        raise HTTPException(status_code=404, detail=f"备案不存在: id={filing_id}")
    try:
        filing = update_filing(db, filing, payload.model_dump(exclude_unset=True))
    except NameConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    audit(db, user.username, "filing_update",
          {"filing_id": filing.id, "name": filing.name}, client_ip(request))
    row = next((r for r in filings_ledger(db) if r["id"] == filing.id), None)
    return _detail(filing, row["system_count"], row["latest_round"]) if row else _detail(filing)


@router.delete("/{filing_id}", status_code=204, dependencies=[_writable])
def remove(filing_id: int, request: Request, db: Session = Depends(get_db),
           user: PlatformUser = Depends(require_write_roles("developer", "security"))):
    filing = db.get(Filing, filing_id)
    if filing is None:
        raise HTTPException(status_code=404, detail=f"备案不存在: id={filing_id}")
    try:
        delete_filing(db, filing_id)
    except InUseError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    audit(db, user.username, "filing_delete",
          {"filing_id": filing_id, "name": filing.name}, client_ip(request))
