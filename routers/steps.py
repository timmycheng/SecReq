# -*- coding: utf-8 -*-
"""向导各步骤数据路由(Step2~Step8)。

统一语义: POST 为该步骤整卷保存(整体替换)并返回落库后的最新实体;
GET 读取当前值。枚举选项一律由 /api/meta/constants 提供, 本文件不重复定义。
"""
import base64
import logging
import re

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import shared.constants as C
from models import (
    ApiEndpoint, AuthConfig, DataAsset, ExternalSystem, Feature, GradingSurvey,
    InfraArchImage, InfraAsset, PermissionEntry, PlatformUser, Project, Resource, Role,
    SbomComponent,
)
from routers.common import (
    asset_to_out, component_to_out, get_accessible_project, get_db,
    get_writable_project, require_login, survey_to_out,
)
from services.audit_service import audit
from schemas.auth import AuthConfigIn, AuthConfigOut, AuthDefaultsOut
from schemas.component import ComponentsSaveIn, ComponentOut, SbomImportResult
from schemas.data_dictionary import DataAssetOut
from schemas.feature import FeatureOut
from schemas.inventory import (
    ApiEndpointIn, ApiEndpointOut, InfraArchImageIn, InfraArchImageOut,
    InfraAssetListIn, InfraAssetOut,
)
from schemas.project import ExternalSystemIn, ExternalSystemOut
from schemas.permission import PermissionMatrixIn, PermissionMatrixOut
from schemas.survey import SurveySubmitIn
from services.errors import server_error
from services.feature_extract import FeatureExtractionError, extract_candidates
from services.grading import GradingError, grade_survey
from services.sbom_import import SbomParseError, import_sbom_file
from services.settings_service import get_llm_config
from services.step_store import (
    MatrixIndexError, replace_api_endpoints, replace_components,
    UidContinuityError,
    replace_data_assets, replace_external_systems, replace_features,
    replace_infra_assets, replace_permission_matrix, upsert_auth_config,
)

logger = logging.getLogger(__name__)

# 上传文件体积上限; 按块读取并在累计超限时立刻 413, 避免一次性载入内存
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
_CHUNK_SIZE = 64 * 1024
# 架构图(#164)原始图片体积上限(base64 后随 JSON 走, 存库不落盘)
MAX_ARCH_IMAGE_BYTES = 2 * 1024 * 1024
_ARCH_ENVS = ("test", "prod", "dev")
_ARCH_DATA_URL_RE = re.compile(r"data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/=]+)")


async def _read_limited(file: UploadFile, limit: int = MAX_UPLOAD_BYTES) -> bytes:
    """按块读取上传文件; 累计超过 limit 立即抛 413。"""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise HTTPException(
                status_code=413,
                detail=f"上传文件过大, 上限 {limit // (1024 * 1024)} MB",
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _audit_step(db: Session, user: PlatformUser, project: Project,
                step: str, count: int) -> None:
    """向导步骤保存留痕: 只记步骤名与条目数, 不记全量数据(避免审计库膨胀)。"""
    audit(db, user.username, "step_save",
          {"project_id": project.id, "step": step, "count": count})


router = APIRouter(
    prefix="/api/projects/{project_id}", tags=["wizard-steps"],
    # 各端点经 get_writable_project(写) / get_accessible_project(读) 做角色+归属校验
)


# ── Step1 定级(问卷内联/直接指定) ─────────────────────
@router.post("/survey")
def submit_survey(payload: SurveySubmitIn, project: Project = Depends(get_writable_project),
                  db: Session = Depends(get_db)):
    """整卷提交 → 打分 → 落库建议定级, 返回建议与判定理由。

    显式给出 final_level 且未答完问卷时视为"直接指定定级", 跳过打分。
    """
    from services.grading import load_questions

    if payload.final_level is not None and payload.final_level not in C.GRADING_LEVELS:
        raise HTTPException(status_code=400, detail=f"定级必须是 {'、'.join(C.GRADING_LEVELS)}")

    answers = [a.model_dump() for a in payload.answers]
    direct_grading = (
        payload.final_level is not None
        and len(answers) < len(load_questions())
    )

    survey = db.query(GradingSurvey).filter_by(project_id=project.id).first()
    if survey is None:
        survey = GradingSurvey(project_id=project.id)
        db.add(survey)
    survey.answers_json = answers
    survey.manual_adjust_note = payload.manual_adjust_note

    if direct_grading:
        survey.suggested_level = None
        survey.suggested_reason = "由填报人直接指定定级(未使用定级问卷)"
        survey.final_level = payload.final_level
        db.commit()
        return survey_to_out(survey, project.id).model_dump()

    try:
        result = grade_survey(answers)
    except GradingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    survey.suggested_level = result.suggested_level
    survey.suggested_reason = result.suggested_reason
    # 人工修正仅在本次显式提交时生效; 只改答案视为推翻旧修正(以新答案的建议值为准)
    survey.final_level = payload.final_level
    db.commit()
    out = survey_to_out(survey, project.id).model_dump()
    out["total_score"] = result.total_score
    out["max_score"] = result.max_score
    return out


@router.get("/survey")
def get_survey(project: Project = Depends(get_accessible_project), db: Session = Depends(get_db)):
    survey = db.query(GradingSurvey).filter_by(project_id=project.id).first()
    return survey_to_out(survey, project.id)


# ── Step1 外部系统连接清单 ────────────────────────────
@router.post("/external-systems", response_model=list[ExternalSystemOut])
def save_external_systems(payload: list[ExternalSystemIn],
                          project: Project = Depends(get_writable_project),
                          db: Session = Depends(get_db),
                          user: PlatformUser = Depends(require_login)):
    try:
        replace_external_systems(db, project.id, payload)
    except UidContinuityError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    rows = db.query(ExternalSystem).filter_by(project_id=project.id).order_by(ExternalSystem.id).all()
    _audit_step(db, user, project, "external_systems", len(rows))
    return [ExternalSystemOut.model_validate(r) for r in rows]


@router.get("/external-systems", response_model=list[ExternalSystemOut])
def get_external_systems(project: Project = Depends(get_accessible_project),
                         db: Session = Depends(get_db)):
    rows = db.query(ExternalSystem).filter_by(project_id=project.id).order_by(ExternalSystem.id).all()
    return [ExternalSystemOut.model_validate(r) for r in rows]


# ── Step1 定级基线预览 ────────────────────────────────
@router.get("/grading-baseline")
def grading_baseline(project: Project = Depends(get_accessible_project),
                     db: Session = Depends(get_db)):
    """定级后的即时反馈: 按当前输入干跑规则引擎, 返回合规/策略/报送类要求标题。"""
    from rules import RuleEngine
    from rules.context import RequirementContext
    from rules.policy import effective_password_policy

    ctx = RequirementContext.from_db(db, project.id)
    pending = RuleEngine.load().generate(ctx)
    baseline_categories = {
        C.label(C.TRIGGER_CATEGORY_LABELS, t)
        for t in ("compliance", "regulatory_trigger", "policy_baseline")
    }
    rows = [
        {
            "req_id": r.req_id,
            "title": r.title,
            "description": r.description,
            "category": r.category,
            "priority": r.priority,
            "reg_confirmed": r.reg_confirmed,
        }
        for r in pending if r.category in baseline_categories
    ]
    return {
        "grading_level": ctx.grading_level or "",
        "grading_text": ctx.grading_text,
        "pwd_defaults": effective_password_policy(ctx),
        "requirements": rows,
    }


# ── Step3 功能清单 ────────────────────────────────────
@router.post("/features", response_model=list[FeatureOut])
def save_features(payload: list[dict], project: Project = Depends(get_writable_project),
                  db: Session = Depends(get_db),
                  user: PlatformUser = Depends(require_login)):
    from schemas.feature import FeatureIn
    items = [FeatureIn(**row) for row in payload]
    try:
        replace_features(db, project.id, items)
    except UidContinuityError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    rows = db.query(Feature).filter_by(project_id=project.id).order_by(Feature.id).all()
    _audit_step(db, user, project, "features", len(rows))
    return [FeatureOut.model_validate(f) for f in rows]


@router.get("/features", response_model=list[FeatureOut])
def get_features(project: Project = Depends(get_accessible_project), db: Session = Depends(get_db)):
    rows = db.query(Feature).filter_by(project_id=project.id).order_by(Feature.id).all()
    return [FeatureOut.model_validate(f) for f in rows]


class FeatureExtractIn(BaseModel):
    text: str = Field(min_length=1, max_length=20000)


@router.post("/features/extract")
def extract_feature_candidates(payload: FeatureExtractIn,
                               project: Project = Depends(get_writable_project),
                               db: Session = Depends(get_db)):
    """粘贴业务需求段落 → 候选功能点(LLM 优先, 未配置/失败降级关键词规则)。只建议, 不落库。"""
    try:
        candidates, mode, note = extract_candidates(payload.text, get_llm_config(db))
    except FeatureExtractionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"mode": mode, "note": note, "candidates": candidates}


# ── Step4 数据字典 ────────────────────────────────────
@router.post("/data-assets", response_model=list[DataAssetOut])
def save_data_assets(payload: list[dict], project: Project = Depends(get_writable_project),
                     db: Session = Depends(get_db),
                     user: PlatformUser = Depends(require_login)):
    from schemas.data_dictionary import DataAssetIn
    items = [DataAssetIn(**row) for row in payload]
    try:
        replace_data_assets(db, project.id, items)
    except UidContinuityError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    assets = db.query(DataAsset).filter_by(project_id=project.id).order_by(DataAsset.id).all()
    _audit_step(db, user, project, "data_assets", len(assets))
    return [asset_to_out(a) for a in assets]


@router.get("/data-assets", response_model=list[DataAssetOut])
def get_data_assets(project: Project = Depends(get_accessible_project), db: Session = Depends(get_db)):
    assets = db.query(DataAsset).filter_by(project_id=project.id).order_by(DataAsset.id).all()
    return [asset_to_out(a) for a in assets]


class DictionaryParseIn(BaseModel):
    content: str = Field(min_length=1, max_length=200_000)


@router.post("/data-assets/parse-dictionary")
def parse_dictionary(payload: DictionaryParseIn,
                     project: Project = Depends(get_writable_project)):
    """粘贴数据字典文本(表/字段清单) → 解析并自动分级。只返回建议, 不落库。"""
    from services.dictionary_import import build_asset_suggestions, parse_dictionary_text
    rows = parse_dictionary_text(payload.content)
    if not rows:
        raise HTTPException(status_code=400, detail="未能从文本中解析出任何 行, 请检查分隔符(Tab/逗号/竖线)")
    return {
        "row_count": len(rows),
        "assets": build_asset_suggestions(rows),
    }


@router.post("/data-assets/import-dictionary")
async def import_dictionary_file(project: Project = Depends(get_writable_project),
                                 file: UploadFile = File(...)):
    """上传数据字典文件(.xlsx/.csv/.txt/.tsv) → 解析并自动分级。只返回建议, 不落库。"""
    from services.dictionary_import import (
        build_asset_suggestions, parse_dictionary_text, parse_dictionary_xlsx,
    )
    name = (file.filename or "").lower()
    payload = await _read_limited(file)
    if name.endswith((".xlsx", ".xlsm")):
        try:
            rows = parse_dictionary_xlsx(payload)
        except Exception as exc:  # openpyxl 内部异常, 原文可能含路径等内部信息
            raise server_error(logger, exc, "Excel 解析失败",
                               project_id=project.id, filename=file.filename,
                               status_code=400) from exc
    elif name.endswith((".csv", ".txt", ".tsv")):
        text = None
        for encoding in ("utf-8-sig", "gbk"):
            try:
                text = payload.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            raise HTTPException(status_code=400, detail="文件编码不支持, 请使用 UTF-8 或 GBK")
        rows = parse_dictionary_text(text)
    else:
        raise HTTPException(status_code=400, detail="请上传 .xlsx / .csv / .tsv / .txt 文件")
    if not rows:
        raise HTTPException(status_code=400, detail="文件中没有解析到数据行(需要 表名/字段名 两列)")
    return {"row_count": len(rows), "assets": build_asset_suggestions(rows)}


# ── Step5 权限矩阵 ────────────────────────────────────
@router.post("/matrix")
def save_matrix(payload: PermissionMatrixIn, project: Project = Depends(get_writable_project),
                db: Session = Depends(get_db),
                user: PlatformUser = Depends(require_login)):
    try:
        stats = replace_permission_matrix(db, project.id, payload)
    except MatrixIndexError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except UidContinuityError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _audit_step(db, user, project, "permission_matrix", stats.get("entries", 0))
    return _matrix_out(db, project.id, extra=stats)


@router.get("/matrix")
def get_matrix(project: Project = Depends(get_accessible_project), db: Session = Depends(get_db)):
    return _matrix_out(db, project.id)


def _matrix_out(db: Session, pid: int, extra: dict | None = None) -> dict:
    roles = db.query(Role).filter_by(project_id=pid).order_by(Role.id).all()
    resources = db.query(Resource).filter_by(project_id=pid).order_by(Resource.id).all()
    entries = (
        db.query(PermissionEntry)
        .join(Role, PermissionEntry.role_id == Role.id)
        .filter(Role.project_id == pid)
        .order_by(PermissionEntry.id).all()
    )
    body = PermissionMatrixOut(
        roles=[{"id": r.id, "uid": r.uid, "name": r.name, "role_type": r.role_type,
                "user_count_estimate": r.user_count_estimate} for r in roles],
        resources=[{"id": r.id, "uid": r.uid, "name": r.name, "resource_type": r.resource_type,
                    "criticality": r.criticality} for r in resources],
        entries=[{"id": e.id, "role_id": e.role_id, "resource_id": e.resource_id,
                  "action": e.action, "requires_approval": bool(e.requires_approval)}
                 for e in entries],
    )
    out = body.model_dump()
    if extra is not None:
        out["saved"] = extra
    return out


# ── Step6 认证与密码策略 ──────────────────────────────
@router.post("/auth-config", response_model=AuthConfigOut)
def save_auth_config(payload: AuthConfigIn, project: Project = Depends(get_writable_project),
                     db: Session = Depends(get_db),
                     user: PlatformUser = Depends(require_login)):
    cfg = upsert_auth_config(db, project.id, payload)
    _audit_step(db, user, project, "auth_config", 1)
    return AuthConfigOut.model_validate(cfg)


@router.get("/auth-config")
def get_auth_config(project: Project = Depends(get_accessible_project), db: Session = Depends(get_db)):
    cfg = db.query(AuthConfig).filter_by(project_id=project.id).first()
    return None if cfg is None else AuthConfigOut.model_validate(cfg).model_dump()


@router.get("/auth-defaults", response_model=AuthDefaultsOut)
def get_auth_defaults(project: Project = Depends(get_accessible_project), db: Session = Depends(get_db)):
    """Step6 设计器预填值: 未配置项按有效定级推导(policy.py 同口径)。"""
    from rules.context import RequirementContext
    from rules.policy import effective_password_policy

    ctx = RequirementContext.from_db(db, project.id)
    numeric = {k: int(v) for k, v in effective_password_policy(ctx).items()}
    level = ctx.grading_text.replace("等保", "") or "未定级"
    return AuthDefaultsOut(grading_level=level, defaults=numeric)


# ── Step7 软件/框架清单(SBOM 来源) ────────────────────
@router.get("/components", response_model=list[ComponentOut])
def get_components(project: Project = Depends(get_accessible_project), db: Session = Depends(get_db)):
    comps = db.query(SbomComponent).filter_by(project_id=project.id).order_by(SbomComponent.id).all()
    return [component_to_out(c) for c in comps]


@router.post("/components", response_model=list[ComponentOut])
def save_components(payload: ComponentsSaveIn, project: Project = Depends(get_writable_project),
                    db: Session = Depends(get_db),
                    user: PlatformUser = Depends(require_login)):
    try:
        replace_components(db, project.id, payload.components)
    except UidContinuityError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    comps = db.query(SbomComponent).filter_by(project_id=project.id).order_by(SbomComponent.id).all()
    _audit_step(db, user, project, "components", len(comps))
    return [component_to_out(c) for c in comps]


@router.post("/components/import-sbom", response_model=SbomImportResult)
async def import_sbom_file_route(project: Project = Depends(get_writable_project),
                                 db: Session = Depends(get_db),
                                 file: UploadFile = File(...),
                                 user: PlatformUser = Depends(require_login)):
    """上传 CycloneDX/SPDX 格式 SBOM 文件批量导入(source_type=sbom_file)。"""
    if not file.filename or not file.filename.lower().endswith(
            (".json", ".spdx", ".cdx.json")):
        raise HTTPException(status_code=400, detail="请上传 .json(CycloneDX/SPDX JSON) 或 .spdx 文件")
    payload = await _read_limited(file)
    try:
        result = import_sbom_file(db, project.id, file.filename, payload)
    except SbomParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _audit_step(db, user, project, "sbom_import", result.added)
    return result


# ── API 接口清单(独立步骤) ────────────────────────────
class ApiImportTextIn(BaseModel):
    """粘贴文本批量导入: 每行 名称,方法,路径[,需要认证,公网暴露](#92)。"""

    text: str = Field(max_length=200_000)


@router.post("/api-endpoints/parse")
async def parse_api_endpoints(project: Project = Depends(get_writable_project),
                              db: Session = Depends(get_db),
                              user: PlatformUser = Depends(require_login),
                              file: UploadFile | None = File(None),
                              text: str | None = Form(None)):
    """批量导入第一段: 解析预览, 不落库(#92)。

    统一 multipart: file(xlsx/csv/txt)或 text 字段(粘贴文本)二选一;
    返回逐行数组, 非法行标 error 不阻塞合法行; 确认导入由前端合并后走既有整体保存。
    """
    from services.api_import import parse_text, parse_upload

    rows: list[dict] = []
    if file is not None and file.filename:
        content = await _read_limited(file)
        rows = parse_upload(file.filename, content)
    elif text and text.strip():
        rows = parse_text(text)
    else:
        raise HTTPException(status_code=400, detail="请上传 xlsx/csv 文件或提供粘贴文本")
    invalid = sum(1 for r in rows if r.get("error"))
    _audit_step(db, user, project, "api_import", len(rows))
    return {"total": len(rows), "invalid": invalid, "rows": rows}


@router.post("/api-endpoints", response_model=list[ApiEndpointOut])
def save_api_endpoints(payload: list[ApiEndpointIn],
                       project: Project = Depends(get_writable_project),
                       db: Session = Depends(get_db),
                       user: PlatformUser = Depends(require_login)):
    try:
        replace_api_endpoints(db, project.id, payload)
    except UidContinuityError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    rows = db.query(ApiEndpoint).filter_by(project_id=project.id).order_by(ApiEndpoint.id).all()
    _audit_step(db, user, project, "api_endpoints", len(rows))
    return [ApiEndpointOut.model_validate(e) for e in rows]


@router.get("/api-endpoints", response_model=list[ApiEndpointOut])
def get_api_endpoints(project: Project = Depends(get_accessible_project),
                      db: Session = Depends(get_db)):
    rows = db.query(ApiEndpoint).filter_by(project_id=project.id).order_by(ApiEndpoint.id).all()
    return [ApiEndpointOut.model_validate(e) for e in rows]


# ── 基础设施清单(独立步骤) ────────────────────────────
@router.post("/infra-assets", response_model=list[InfraAssetOut])
def save_infra_assets(payload: InfraAssetListIn,
                      project: Project = Depends(get_writable_project),
                      db: Session = Depends(get_db),
                      user: PlatformUser = Depends(require_login)):
    try:
        replace_infra_assets(db, project.id, payload.assets)
    except UidContinuityError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    rows = db.query(InfraAsset).filter_by(project_id=project.id).order_by(InfraAsset.id).all()
    _audit_step(db, user, project, "infra_assets", len(rows))
    return [InfraAssetOut.model_validate(a) for a in rows]


# ── 架构图(#164): 拓扑画布回退后, 每环境一张图 + 清单手填 ──
@router.get("/arch-images", response_model=list[InfraArchImageOut])
def get_arch_images(project: Project = Depends(get_accessible_project),
                    db: Session = Depends(get_db)):
    rows = db.query(InfraArchImage).filter_by(project_id=project.id).all()
    return [InfraArchImageOut.model_validate(r) for r in rows]


@router.put("/arch-images/{env}", response_model=InfraArchImageOut)
def upload_arch_image(env: str, payload: InfraArchImageIn,
                      project: Project = Depends(get_writable_project),
                      db: Session = Depends(get_db),
                      user: PlatformUser = Depends(require_login)):
    if env not in _ARCH_ENVS:
        raise HTTPException(status_code=404, detail=f"未知环境: {env}")
    m = _ARCH_DATA_URL_RE.fullmatch(payload.image_data_url)
    if not m:
        raise HTTPException(status_code=400, detail="仅支持 png/jpg/webp 图片的 data URL")
    try:
        raw = base64.b64decode(m.group(2), validate=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="图片 base64 编码无效") from exc
    if len(raw) > MAX_ARCH_IMAGE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"架构图过大, 上限 {MAX_ARCH_IMAGE_BYTES // (1024 * 1024)} MB",
        )
    row = db.query(InfraArchImage).filter_by(project_id=project.id, env=env).first()
    if row is None:
        row = InfraArchImage(project_id=project.id, env=env, image_data_url=payload.image_data_url)
        db.add(row)
    else:
        row.image_data_url = payload.image_data_url
    db.commit()
    _audit_step(db, user, project, f"arch_image_{env}", 1)
    return InfraArchImageOut.model_validate(row)


@router.delete("/arch-images/{env}")
def delete_arch_image(env: str,
                      project: Project = Depends(get_writable_project),
                      db: Session = Depends(get_db),
                      user: PlatformUser = Depends(require_login)):
    row = db.query(InfraArchImage).filter_by(project_id=project.id, env=env).first()
    if row is not None:
        db.delete(row)
        db.commit()
        _audit_step(db, user, project, f"arch_image_{env}_delete", 1)
    return {"ok": True}


@router.get("/infra-assets", response_model=list[InfraAssetOut])
def get_infra_assets(project: Project = Depends(get_accessible_project),
                     db: Session = Depends(get_db)):
    rows = db.query(InfraAsset).filter_by(project_id=project.id).order_by(InfraAsset.id).all()
    return [InfraAssetOut.model_validate(a) for a in rows]


def get_inventory_body(db: Session, pid: int) -> dict:
    endpoints = db.query(ApiEndpoint).filter_by(project_id=pid).order_by(ApiEndpoint.id).all()
    infra = db.query(InfraAsset).filter_by(project_id=pid).order_by(InfraAsset.id).all()
    return {
        "api_endpoints": [ApiEndpointOut.model_validate(e).model_dump() for e in endpoints],
        "infra_assets": [InfraAssetOut.model_validate(a).model_dump() for a in infra],
    }
