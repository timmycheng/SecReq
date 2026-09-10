# -*- coding: utf-8 -*-
"""被评估系统 CRUD 与台账: 系统列表(台账视角) / 详情(评估时间线) / 系统清单维护。

数据权限与项目一致: 开发(developer)仅见/操作本人创建的系统, 安全(security)全量;
越权访问按 404 处理, 不泄露存在性。#194 起基础设施/组件/架构图挂系统维护,
与向导内的项目路由(/api/projects/{id}/...)同源同权限, 只是入口不同。
"""
import csv
import io
import re

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from sqlalchemy.orm import Session

import shared.constants as C
from pydantic import BaseModel

from models import ExternalSystem, Feature, Filing, InfraAsset, PlatformUser, SbomComponent, System, SystemBaseline
from routers.common import (
    client_ip, component_to_out, decode_upload_csv, get_db, read_upload_limited,
    require_login, require_write_roles,
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

_writable = Depends(require_write_roles(*C.SYSTEM_WRITE_ROLES))


def _arch_envs(db: Session) -> list[str]:
    """架构图可用环境(#289): 由系统设置 infra_envs 动态决定, 不再硬编码。"""
    from services.settings_service import get_infra_envs
    return [e["code"] for e in get_infra_envs(db)]


def _get_accessible_system(system_id: int, db: Session, user: PlatformUser) -> System:
    """归属口径与列表一致(#327): 无主系统不对普通角色放行, 仅 FULL_VISIBILITY 可见。"""
    system = db.get(System, system_id)
    if system is None or (
        user.role not in C.FULL_VISIBILITY_ROLES and system.owner_user_id != user.id
    ):
        raise HTTPException(status_code=404, detail=f"系统不存在: id={system_id}")
    return system


@router.get("/ledger")
def ledger(db: Session = Depends(get_db), user: PlatformUser = Depends(require_login),
           keyword: str | None = None, filing_id: int | None = None,
           importance: str | None = None, tag: str | None = None,
           page: int | None = Query(default=None, ge=1),
           page_size: int = Query(default=20, ge=1, le=100)):
    """系统视角台账: 系统 × 所属备案/定级 × 最新轮次结论 × 遗留未闭环 × 当前基线。

    带 page 时返回 {items, total} 信封(#283 item9), 不带 page 返回全量列表。
    """
    return systems_ledger(db, user, keyword=keyword, filing_id=filing_id,
                          importance=importance, tag=tag, page=page, page_size=page_size)


@router.get("", response_model=list[SystemDetail])
def list_all(db: Session = Depends(get_db), user: PlatformUser = Depends(require_login)):
    """系统列表(含所属备案与定级, 供下拉选择与台账)。"""
    items = []
    for system in visible_systems_query(db, user).all():
        items.append(SystemDetail(**system_detail(db, user, system)))
    return items


@router.post("", response_model=SystemDetail, status_code=201, dependencies=[_writable])
def create(payload: SystemCreate, request: Request, db: Session = Depends(get_db),
           user: PlatformUser = Depends(require_write_roles(*C.SYSTEM_WRITE_ROLES))):
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
          user: PlatformUser = Depends(require_write_roles(*C.SYSTEM_WRITE_ROLES))):
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
           user: PlatformUser = Depends(require_write_roles(*C.SYSTEM_WRITE_ROLES))):
    system = _get_accessible_system(system_id, db, user)
    try:
        delete_system(db, system.id)
    except InUseError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    audit(db, user.username, "system_delete",
          {"system_id": system_id, "name": system.name}, client_ip(request))


# ── 系统批量导入(#346): 仅系统/开发/安全管理员 ──

#: CSV 表头别名 → 字段(兼容中英文表头)
_IMPORT_HEADER_ALIASES = {
    "name": "name", "系统名称": "name", "名称": "name",
    "code": "code", "系统编号": "code", "编号": "code",
    "filing": "filing", "挂靠备案": "filing", "备案名称": "filing", "备案": "filing",
    "user_scale": "user_scale", "用户规模": "user_scale", "规模": "user_scale",
    "is_public": "is_public", "是否公网": "is_public", "是否涉及公网访问": "is_public",
    "types": "types", "业务类型": "types", "系统类型": "types", "业务形态": "types",
    "compliance_targets": "compliance_targets", "合规目标": "compliance_targets",
    "department": "department", "归属部门": "department",
    "importance": "importance", "重要程度": "importance",
    "tags": "tags", "标签": "tags",
    "owner_dev_name": "owner_dev_name", "开发侧责任人": "owner_dev_name",
    "owner_ops_name": "owner_ops_name", "运维侧责任人": "owner_ops_name",
    "owner_biz_name": "owner_biz_name", "业务侧责任人": "owner_biz_name",
}
_IMPORT_MAX_ROWS = 1000
#: 多值列分隔符: 顿号/中英文逗号/中英文分号
_MULTI_SPLIT_RE = re.compile(r"[、,，;；]+")


def _split_multi(value: str) -> list[str]:
    """多值列按分隔符拆分并去空去重, 保序。"""
    seen: list[str] = []
    for token in _MULTI_SPLIT_RE.split(value or ""):
        token = token.strip()
        if token and token not in seen:
            seen.append(token)
    return seen


def _lookup_by_label_or_code(value: str, mapping: dict) -> str | None:
    """枚举列取值: 接受 code 或中文标签, 命中返回 code。"""
    value = value.strip()
    if value in mapping:
        return value
    for code, label in mapping.items():
        if label == value:
            return code
    return None


def _parse_public_flag(value: str) -> bool | None:
    value = value.strip().lower()
    if value in ("是", "y", "yes", "true", "1"):
        return True
    if value in ("否", "n", "no", "false", "0"):
        return False
    return None


@router.post("/import", status_code=201)
async def import_systems(request: Request, file: UploadFile = File(...),
                         db: Session = Depends(get_db),
                         user: PlatformUser = Depends(
                             require_write_roles(*C.SYSTEM_IMPORT_ROLES))):
    """CSV 批量导入系统(#346): 仅系统管理员/开发管理员/安全管理员, 其余角色 403。

    表头中英文均可: 名称(必填)/编号/挂靠备案/用户规模/是否公网/业务类型/合规目标/
    归属部门/重要程度/标签/开发侧责任人/运维侧责任人/业务侧责任人。
    逐行校验, 冲突或非法行整行跳过并给可读原因, 有效行即使夹杂坏行也照常入库;
    导入人成为系统归属人(数据权限与单条新建一致)。
    """
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="请上传 .csv 文件")
    raw = await read_upload_limited(file)
    reader = csv.DictReader(io.StringIO(decode_upload_csv(raw)))
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV 文件为空")
    fields = {_IMPORT_HEADER_ALIASES.get(str(h).strip().lower()): str(h).strip()
              for h in reader.fieldnames}
    if "name" not in fields:
        raise HTTPException(
            status_code=400,
            detail="CSV 缺少必需列: name(表头需含 系统名称 或 name)")

    from services.settings_service import get_system_dicts
    type_map = get_system_dicts(db)["types"]                 # code → label
    scale_labels = {label: code for code, label in C.USER_SCALES.items()}
    filing_ids = {f.name: f.id for f in db.query(Filing).all()}

    created, skipped = 0, []
    seen_names: set[str] = set()
    seen_codes: set[str] = set()
    for line, row in enumerate(reader, start=2):  # 第 1 行是表头
        if line > _IMPORT_MAX_ROWS + 1:
            skipped.append({"row": line, "name": "", "reason": f"超过单次 {_IMPORT_MAX_ROWS} 行上限"})
            continue
        data = {key: (row.get(header) or "").strip() for key, header in fields.items() if key}
        name = data.get("name", "")
        code = data.get("code") or None

        def _skip(reason: str, *, row_no: int = line, row_name: str = name) -> None:
            skipped.append({"row": row_no, "name": row_name, "reason": reason})

        if not name:
            _skip("名称为空")
            continue
        if name in seen_names or (code and code in seen_codes):
            _skip("与本文件内前面的行重名或编号重复")
            continue
        filing_id = None
        if data.get("filing"):
            filing_id = filing_ids.get(data["filing"])
            if filing_id is None:
                _skip(f"备案不存在: {data['filing']}")
                continue
        scale = None
        if data.get("user_scale"):
            scale = C.USER_SCALES.get(data["user_scale"]) or scale_labels.get(data["user_scale"])
            if scale is None:
                _skip(f"用户规模须为 {'、'.join(C.USER_SCALES.values())} 之一")
                continue
        is_public = False
        if data.get("is_public"):
            is_public = _parse_public_flag(data["is_public"])
            if is_public is None:
                _skip("是否公网请填 是/否")
                continue
        types: list[str] = []
        if data.get("types"):
            types = _split_multi(data["types"])
            unknown = [t for t in types if _lookup_by_label_or_code(t, type_map) is None]
            if unknown:
                _skip(f"业务类型无法识别: {'、'.join(unknown)}")
                continue
            types = [_lookup_by_label_or_code(t, type_map) or t for t in types]
        targets: list[str] = []
        if data.get("compliance_targets"):
            targets = _split_multi(data["compliance_targets"])
            unknown = [t for t in targets
                       if _lookup_by_label_or_code(t, C.COMPLIANCE_TARGETS) is None]
            if unknown:
                _skip(f"合规目标无法识别: {'、'.join(unknown)}")
                continue
            targets = [_lookup_by_label_or_code(t, C.COMPLIANCE_TARGETS) or t
                       for t in targets]
        importance = data.get("importance") or None
        if importance and importance not in C.IMPORTANCE_LEVELS:
            _skip(f"重要程度须为 {'、'.join(C.IMPORTANCE_LEVELS)} 之一")
            continue

        try:
            create_system(db, {
                "name": name, "code": code, "filing_id": filing_id,
                "user_scale": scale or "", "types": types, "is_public": is_public,
                "compliance_targets": targets,
                "department": data.get("department") or None,
                "importance": importance,
                "tags": _split_multi(data.get("tags", "")),
                "owner_dev_name": data.get("owner_dev_name") or None,
                "owner_ops_name": data.get("owner_ops_name") or None,
                "owner_biz_name": data.get("owner_biz_name") or None,
            }, owner_user_id=user.id)
        except NameConflictError as exc:
            _skip(str(exc))
            continue
        seen_names.add(name)
        if code:
            seen_codes.add(code)
        created += 1
    audit(db, user.username, "system_import",
          {"created": created, "skipped": len(skipped)}, client_ip(request))
    return {"created": created, "skipped": skipped}


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
                      user: PlatformUser = Depends(require_write_roles(*C.SYSTEM_WRITE_ROLES))):
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
                    user: PlatformUser = Depends(require_write_roles(*C.SYSTEM_WRITE_ROLES))):
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
                      user: PlatformUser = Depends(require_write_roles(*C.SYSTEM_WRITE_ROLES))):
    """上传 CycloneDX/SPDX 或构建文件(pom.xml/package.json/requirements.txt)批量导入。"""
    system = _writable_system(system_id, db, user)
    if not file.filename or not file.filename.lower().endswith(
            (".json", ".spdx", ".cdx.json",
             ".xml", ".txt")):  # #226 构建文件: pom.xml / requirements.txt
        raise HTTPException(status_code=400,
                            detail="请上传 .json(CycloneDX/SPDX) / .spdx 或构建文件(.xml/.txt)")
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
                      user: PlatformUser = Depends(require_write_roles(*C.SYSTEM_WRITE_ROLES))):
    system = _writable_system(system_id, db, user)
    if env not in _arch_envs(db):
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
                      user: PlatformUser = Depends(require_write_roles(*C.SYSTEM_WRITE_ROLES))):
    system = _writable_system(system_id, db, user)
    if env not in _arch_envs(db):
        raise HTTPException(status_code=404, detail=f"未知环境: {env}")
    if delete_arch_image(db, system.id, env):
        audit(db, user.username, "system_arch_image_delete",
              {"system_id": system.id, "env": env}, client_ip(request))
    return {"ok": True}


class LevelConfirmIn(BaseModel):
    """等保级别变更确认(#225): 采纳评估建议级覆盖备案, 或维持备案级留痕。"""
    decision: str  # adopt_suggested / keep_filing
    note: str | None = None


@router.post("/{system_id}/baseline/confirm-level")
def confirm_baseline_level(system_id: int, payload: LevelConfirmIn,
                           request: Request,
                           db: Session = Depends(get_db),
                           user: PlatformUser = Depends(
                               require_write_roles(*C.SECURITY_SIDE_ROLES))):
    """安全侧人工定夺「级别变更确认」待办(#225): 两条路径都写履历留痕。"""
    from models import SystemBaselineHistory

    system = _get_accessible_system(system_id, db, user)
    baseline = db.query(SystemBaseline).filter_by(system_id=system.id).first()
    pending = baseline.pending_level_confirmation if baseline else None
    if not pending:
        raise HTTPException(status_code=409, detail="该系统没有待确认的级别变更")
    suggested = pending.get("suggested_level")
    filing_level = pending.get("filing_level")
    filing = db.get(Filing, system.filing_id) if system.filing_id else None

    if payload.decision == "adopt_suggested":
        if filing is None:
            raise HTTPException(status_code=409, detail="系统未备案, 无法采纳评估建议级")
        old_level = filing.level
        filing.level = suggested
        summary = (f"级别变更: 备案定级 {old_level} → {suggested}"
                   f"(采纳第 {pending.get('project_id')} 轮评估建议)"
                   + (f"; {payload.note}" if payload.note else ""))
    elif payload.decision == "keep_filing":
        summary = (f"维持备案定级 {filing_level}, 评估建议 {suggested} 留痕"
                   f"(第 {pending.get('project_id')} 轮)"
                   + (f"; {payload.note}" if payload.note else ""))
    else:
        raise HTTPException(status_code=400, detail=f"未知确认决定: {payload.decision}")

    baseline.pending_level_confirmation = None
    db.add(SystemBaselineHistory(
        system_id=system.id, baseline_id=baseline.id,
        project_id=pending.get("project_id"),
        summary=summary, operator_id=user.id, operator_name=user.display_name,
    ))
    db.commit()
    audit(db, user.username, "baseline_level_confirm",
          {"system_id": system.id, "decision": payload.decision}, client_ip(request))
    return {"status": "ok", "summary": summary}


# ── 系统详情 Tab 数据(#272): 详情页按 Tab 展示系统事实 ──

@router.get("/{system_id}/detail-section")
def detail_section(system_id: int, section: str,
                   db: Session = Depends(get_db),
                   user: PlatformUser = Depends(require_login)):
    """系统详情页分 Tab 出数(#272)。

    - features: 功能清单不进基线快照, 读当前基线来源轮次的项目数据;
    - data_assets / permissions / apis: 读 system_baselines.baseline_json 快照;
    - 尚未写回基线时 rows 为空并带 has_baseline=False, 前端据此给引导文案。
    """
    system = _get_accessible_system(system_id, db, user)
    baseline = db.query(SystemBaseline).filter_by(system_id=system.id).first()
    data = (baseline.baseline_json or {}) if baseline else {}
    meta = {
        "has_baseline": baseline is not None,
        "source_project_id": baseline.source_project_id if baseline else None,
        "updated_at": baseline.updated_at.isoformat() if baseline and baseline.updated_at else None,
        "summary": baseline.summary if baseline else None,
    }
    if section == "features":
        pid = meta["source_project_id"]
        rows = ([] if pid is None
                else db.query(Feature).filter_by(project_id=pid).order_by(Feature.id).all())
        return {**meta, "rows": [{
            "uid": f.uid, "name": f.name, "module": f.module,
            "description": f.description, "categories": f.categories or [],
            "sensitivity": f.sensitivity,
            "involves_payment": bool(f.involves_payment),
            "exposed_to_internet": bool(f.exposed_to_internet),
        } for f in rows]}
    if section == "data_assets":
        return {**meta, "rows": data.get("data_assets") or []}
    if section == "permissions":
        return {**meta, "rows": {
            "roles": data.get("roles") or [],
            "resources": data.get("resources") or [],
            "permission_entries": data.get("permission_entries") or [],
        }}
    if section == "apis":
        return {**meta, "rows": data.get("api_endpoints") or []}
    if section == "external_systems":
        pid = meta["source_project_id"]
        rows = ([] if pid is None
                else db.query(ExternalSystem).filter_by(project_id=pid)
                .order_by(ExternalSystem.id).all())
        return {**meta, "rows": [{
            "uid": e.uid, "name": e.name, "purpose": e.purpose,
            "direction": e.direction, "involves_sensitive": bool(e.involves_sensitive),
        } for e in rows]}
    raise HTTPException(status_code=400, detail=f"未知 section: {section}")
