# -*- coding: utf-8 -*-
"""向导各步骤数据路由(Step2~Step8)。

统一语义: POST 为该步骤整卷保存(整体替换)并返回落库后的最新实体;
GET 读取当前值。枚举选项一律由 /api/meta/constants 提供, 本文件不重复定义。
"""
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

import shared.constants as C
from models import (
    ApiEndpoint, AuthConfig, DataAsset, Feature, GradingSurvey,
    InfraAsset, PermissionEntry, Project, Resource, Role, SbomComponent,
)
from routers.common import (
    asset_to_out, component_to_out, get_db, get_project_or_404,
    require_write_roles, survey_to_out,
)
from schemas.auth import AuthConfigIn, AuthConfigOut, AuthDefaultsOut
from schemas.component import ComponentsSaveIn, ComponentOut, SbomImportResult
from schemas.data_dictionary import DataAssetOut
from schemas.feature import FeatureOut
from schemas.inventory import ApiEndpointOut, InfraAssetOut, InventorySaveIn
from schemas.permission import PermissionMatrixIn, PermissionMatrixOut
from schemas.survey import SurveySubmitIn
from services.grading import GradingError, grade_survey
from services.sbom_import import SbomParseError, import_sbom_file
from services.step_store import (
    MatrixIndexError, replace_components, replace_data_assets,
    replace_features, replace_inventory, replace_permission_matrix, upsert_auth_config,
)

router = APIRouter(
    prefix="/api/projects/{project_id}", tags=["wizard-steps"],
    dependencies=[Depends(require_write_roles("pm", "developer"))],  # 写接口限项目经理/开发中心
)


# ── Step2 定级问卷 ────────────────────────────────────
@router.post("/survey")
def submit_survey(payload: SurveySubmitIn, project: Project = Depends(get_project_or_404),
                  db: Session = Depends(get_db)):
    """整卷提交 → 打分 → 落库建议定级, 返回建议与判定理由。"""
    if payload.final_level is not None and payload.final_level not in C.GRADING_LEVELS:
        raise HTTPException(status_code=400, detail=f"定级必须是 {'、'.join(C.GRADING_LEVELS)}")
    try:
        result = grade_survey([a.model_dump() for a in payload.answers])
    except GradingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    survey = db.query(GradingSurvey).filter_by(project_id=project.id).first()
    if survey is None:
        survey = GradingSurvey(project_id=project.id)
        db.add(survey)
    survey.answers_json = [a.model_dump() for a in payload.answers]
    survey.suggested_level = result.suggested_level
    survey.suggested_reason = result.suggested_reason
    # 人工修正仅在本次显式提交时生效; 只改答案视为推翻旧修正(以新答案的建议值为准)
    survey.final_level = payload.final_level
    survey.manual_adjust_note = payload.manual_adjust_note
    db.commit()
    out = survey_to_out(survey, project.id).model_dump()
    out["total_score"] = result.total_score
    out["max_score"] = result.max_score
    return out


@router.get("/survey")
def get_survey(project: Project = Depends(get_project_or_404), db: Session = Depends(get_db)):
    survey = db.query(GradingSurvey).filter_by(project_id=project.id).first()
    return survey_to_out(survey, project.id)


# ── Step3 功能清单 ────────────────────────────────────
@router.post("/features", response_model=list[FeatureOut])
def save_features(payload: list[dict], project: Project = Depends(get_project_or_404),
                  db: Session = Depends(get_db)):
    from schemas.feature import FeatureIn
    items = [FeatureIn(**row) for row in payload]
    replace_features(db, project.id, items)
    rows = db.query(Feature).filter_by(project_id=project.id).order_by(Feature.id).all()
    return [FeatureOut.model_validate(f) for f in rows]


@router.get("/features", response_model=list[FeatureOut])
def get_features(project: Project = Depends(get_project_or_404), db: Session = Depends(get_db)):
    rows = db.query(Feature).filter_by(project_id=project.id).order_by(Feature.id).all()
    return [FeatureOut.model_validate(f) for f in rows]


# ── Step4 数据字典 ────────────────────────────────────
@router.post("/data-assets", response_model=list[DataAssetOut])
def save_data_assets(payload: list[dict], project: Project = Depends(get_project_or_404),
                     db: Session = Depends(get_db)):
    from schemas.data_dictionary import DataAssetIn
    items = [DataAssetIn(**row) for row in payload]
    replace_data_assets(db, project.id, items)
    assets = db.query(DataAsset).filter_by(project_id=project.id).order_by(DataAsset.id).all()
    return [asset_to_out(a) for a in assets]


@router.get("/data-assets", response_model=list[DataAssetOut])
def get_data_assets(project: Project = Depends(get_project_or_404), db: Session = Depends(get_db)):
    assets = db.query(DataAsset).filter_by(project_id=project.id).order_by(DataAsset.id).all()
    return [asset_to_out(a) for a in assets]


# ── Step5 权限矩阵 ────────────────────────────────────
@router.post("/matrix")
def save_matrix(payload: PermissionMatrixIn, project: Project = Depends(get_project_or_404),
                db: Session = Depends(get_db)):
    try:
        stats = replace_permission_matrix(db, project.id, payload)
    except MatrixIndexError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _matrix_out(db, project.id, extra=stats)


@router.get("/matrix")
def get_matrix(project: Project = Depends(get_project_or_404), db: Session = Depends(get_db)):
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
        roles=[{"id": r.id, "name": r.name, "role_type": r.role_type,
                "user_count_estimate": r.user_count_estimate} for r in roles],
        resources=[{"id": r.id, "name": r.name, "resource_type": r.resource_type,
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
def save_auth_config(payload: AuthConfigIn, project: Project = Depends(get_project_or_404),
                     db: Session = Depends(get_db)):
    cfg = upsert_auth_config(db, project.id, payload)
    return AuthConfigOut.model_validate(cfg)


@router.get("/auth-config")
def get_auth_config(project: Project = Depends(get_project_or_404), db: Session = Depends(get_db)):
    cfg = db.query(AuthConfig).filter_by(project_id=project.id).first()
    return None if cfg is None else AuthConfigOut.model_validate(cfg).model_dump()


@router.get("/auth-defaults", response_model=AuthDefaultsOut)
def get_auth_defaults(project: Project = Depends(get_project_or_404), db: Session = Depends(get_db)):
    """Step6 设计器预填值: 未配置项按有效定级推导(policy.py 同口径)。"""
    from rules.context import RequirementContext
    from rules.policy import effective_password_policy

    ctx = RequirementContext.from_db(db, project.id)
    numeric = {k: int(v) for k, v in effective_password_policy(ctx).items()}
    level = ctx.grading_text.replace("等保", "") or "未定级"
    return AuthDefaultsOut(grading_level=level, defaults=numeric)


# ── Step7 软件/框架清单(SBOM 来源) ────────────────────
@router.get("/components", response_model=list[ComponentOut])
def get_components(project: Project = Depends(get_project_or_404), db: Session = Depends(get_db)):
    comps = db.query(SbomComponent).filter_by(project_id=project.id).order_by(SbomComponent.id).all()
    return [component_to_out(c) for c in comps]


@router.post("/components", response_model=list[ComponentOut])
def save_components(payload: ComponentsSaveIn, project: Project = Depends(get_project_or_404),
                    db: Session = Depends(get_db)):
    replace_components(db, project.id, payload.components)
    comps = db.query(SbomComponent).filter_by(project_id=project.id).order_by(SbomComponent.id).all()
    return [component_to_out(c) for c in comps]


@router.post("/components/import-sbom", response_model=SbomImportResult)
async def import_sbom_file_route(project: Project = Depends(get_project_or_404),
                                 db: Session = Depends(get_db),
                                 file: UploadFile = File(...)):
    """上传 CycloneDX/SPDX 格式 SBOM 文件批量导入(source_type=sbom_file)。"""
    if not file.filename or not file.filename.lower().endswith(
            (".json", ".spdx", ".cdx.json")):
        raise HTTPException(status_code=400, detail="请上传 .json(CycloneDX/SPDX JSON) 或 .spdx 文件")
    payload = await file.read()
    try:
        return import_sbom_file(db, project.id, file.filename, payload)
    except SbomParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ── Step8 接口清单与资产清单 ──────────────────────────
@router.post("/inventory")
def save_inventory(payload: InventorySaveIn, project: Project = Depends(get_project_or_404),
                   db: Session = Depends(get_db)):
    saved = replace_inventory(db, project.id, payload.api_endpoints, payload.infra_assets)
    body = get_inventory_body(db, project.id)
    body["saved"] = saved
    return body


@router.get("/inventory")
def get_inventory(project: Project = Depends(get_project_or_404), db: Session = Depends(get_db)):
    return get_inventory_body(db, project.id)


def get_inventory_body(db: Session, pid: int) -> dict:
    endpoints = db.query(ApiEndpoint).filter_by(project_id=pid).order_by(ApiEndpoint.id).all()
    infra = db.query(InfraAsset).filter_by(project_id=pid).order_by(InfraAsset.id).all()
    return {
        "api_endpoints": [ApiEndpointOut.model_validate(e).model_dump() for e in endpoints],
        "infra_assets": [InfraAssetOut.model_validate(a).model_dump() for a in infra],
    }
