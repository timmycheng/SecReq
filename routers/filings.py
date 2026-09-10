# -*- coding: utf-8 -*-
"""定级备案 CRUD 与 CSV 批量导入(DESIGN: 备案管理增加批量导入)。

备案是对外备案测评的少数主体, 定级事实由安全侧权威维护(#192):
登录即可读(开发侧选择挂靠备案必须能看到清单), 写操作仅安全角色。
"""
import csv
import io

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

import shared.constants as C
from models import Filing, PlatformUser
from routers.common import (
    client_ip, decode_upload_csv, get_db, read_upload_limited, require_login,
    require_write_roles,
)
from schemas.system import FilingCreate, FilingDetail, FilingOut, FilingUpdate
from services.audit_service import audit
from services.system_service import (
    InUseError, NameConflictError, create_filing, delete_filing,
    filings_ledger, update_filing,
)

router = APIRouter(prefix="/api/filings", tags=["filings"])

_writable = Depends(require_write_roles(*C.PLATFORM_ADMIN_ROLES))


def _detail(filing: Filing, system_count: int = 0, latest_round: dict | None = None) -> FilingDetail:
    return FilingDetail(
        **FilingOut.model_validate(filing).model_dump(),
        system_count=system_count, latest_round=latest_round,
    )


@router.get("", response_model=list[FilingDetail])
def list_all(db: Session = Depends(get_db), user: PlatformUser = Depends(require_login)):
    """备案台账(含下挂系统数与最新评估概况; 评估概况按数据权限裁剪 #330)。"""
    return filings_ledger(db, user)


@router.post("", response_model=FilingDetail, status_code=201, dependencies=[_writable])
def create(payload: FilingCreate, request: Request, db: Session = Depends(get_db),
           user: PlatformUser = Depends(require_write_roles(*C.PLATFORM_ADMIN_ROLES))):
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
          user: PlatformUser = Depends(require_write_roles(*C.PLATFORM_ADMIN_ROLES))):
    filing = db.get(Filing, filing_id)
    if filing is None:
        raise HTTPException(status_code=404, detail=f"备案不存在: id={filing_id}")
    try:
        filing = update_filing(db, filing, payload.model_dump(exclude_unset=True))
    except NameConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    audit(db, user.username, "filing_update",
          {"filing_id": filing.id, "name": filing.name}, client_ip(request))
    row = next((r for r in filings_ledger(db, user) if r["id"] == filing.id), None)
    return _detail(filing, row["system_count"], row["latest_round"]) if row else _detail(filing)


@router.delete("/{filing_id}", status_code=204, dependencies=[_writable])
def remove(filing_id: int, request: Request, db: Session = Depends(get_db),
           user: PlatformUser = Depends(require_write_roles(*C.PLATFORM_ADMIN_ROLES))):
    filing = db.get(Filing, filing_id)
    if filing is None:
        raise HTTPException(status_code=404, detail=f"备案不存在: id={filing_id}")
    try:
        delete_filing(db, filing_id)
    except InUseError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    audit(db, user.username, "filing_delete",
          {"filing_id": filing_id, "name": filing.name}, client_ip(request))


#: CSV 表头别名 → 字段(兼容 Excel 导出的中文表头)
_CSV_HEADER_ALIASES = {
    "name": "name", "名称": "name",
    "level": "level", "定级": "level", "等级": "level",
    "code": "code", "编号": "code",
    "note": "note", "备注": "note",
}
_CSV_MAX_ROWS = 1000


@router.post("/import", status_code=201, dependencies=[_writable])
async def import_csv(request: Request, file: UploadFile = File(...),
                     db: Session = Depends(get_db),
                     user: PlatformUser = Depends(
                         require_write_roles(*C.PLATFORM_ADMIN_ROLES))):
    """CSV 批量导入备案: 表头 name,level[,code,note](中英文表头均可)。

    逐行校验: name/level 必填, level 须为有效定级, 名称/编号冲突整行跳过;
    返回逐行跳过原因, 有效行即使夹杂坏行也照常入库。
    """
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="请上传 .csv 文件")
    raw = await read_upload_limited(file)
    reader = csv.DictReader(io.StringIO(decode_upload_csv(raw)))
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV 文件为空")
    fields = {_CSV_HEADER_ALIASES.get(str(h).strip().lower()): str(h).strip()
              for h in reader.fieldnames}
    missing = [f for f in ("name", "level") if f not in fields]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"CSV 缺少必需列: {', '.join(missing)}(表头需含 名称/定级 或 name/level)")

    created, skipped = 0, []
    for line, row in enumerate(reader, start=2):  # 第 1 行是表头
        if line > _CSV_MAX_ROWS + 1:
            skipped.append({"row": line, "name": "", "reason": f"超过单次 {_CSV_MAX_ROWS} 行上限"})
            continue
        data = {key: (row.get(header) or "").strip() for key, header in fields.items() if key}
        name = data.get("name", "")
        level = data.get("level", "")
        if not name:
            skipped.append({"row": line, "name": "", "reason": "名称为空"})
            continue
        if level not in C.GRADING_LEVELS:
            skipped.append({"row": line, "name": name,
                            "reason": f"定级须为 {'、'.join(C.GRADING_LEVELS)} 之一"})
            continue
        try:
            create_filing(db, {"name": name, "level": level,
                               "code": data.get("code") or None,
                               "note": data.get("note") or None})
        except NameConflictError as exc:
            skipped.append({"row": line, "name": name, "reason": str(exc)})
            continue
        created += 1
    audit(db, user.username, "filing_import",
          {"created": created, "skipped": len(skipped)}, client_ip(request))
    return {"created": created, "skipped": skipped}
