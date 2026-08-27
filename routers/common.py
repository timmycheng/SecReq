# -*- coding: utf-8 -*-
"""路由公共件: 会话依赖 / 项目装载 / ORM→API 模型序列化。"""
from collections.abc import Generator

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from models import (
    ApiEndpoint, AuthConfig, DataAsset, DataField, DataTable, Feature,
    GradingSurvey, InfraAsset, PermissionEntry, Project,
    SbomComponent, VulnerabilityRecord, Resource, Role,
)
from schemas.component import ComponentOut, ComponentVulnInline
from schemas.data_dictionary import DataAssetOut, DataFieldOut, DataTableOut
from schemas.survey import SurveyOut

import shared.constants as C


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖: 每请求一个会话(测试通过 dependency_overrides 替换)。"""
    from main import SessionLocal
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_project_or_404(project_id: int, db: Session = Depends(get_db)) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"项目不存在: id={project_id}")
    return project


# ── 序列化 ────────────────────────────────────────────

def survey_to_out(survey: GradingSurvey | None, project_id: int) -> SurveyOut | None:
    if survey is None:
        return None
    return SurveyOut(
        project_id=project_id,
        answers_json=survey.answers_json or [],
        suggested_level=survey.suggested_level,
        suggested_reason=survey.suggested_reason,
        final_level=survey.final_level,
        manual_adjust_note=survey.manual_adjust_note,
        effective_level=survey.effective_level(),
    )


def _severity_sort_key(v: VulnerabilityRecord):
    return C.SEVERITY_ORDER.get(v.severity, 9)


def component_to_out(comp: SbomComponent) -> ComponentOut:
    return ComponentOut(
        id=comp.id,
        layer=comp.layer,
        name=comp.name,
        version=comp.version,
        purl=comp.purl,
        license=comp.license,
        source_type=comp.source_type,
        vulnerabilities=[
            ComponentVulnInline(
                cve_id=v.cve_id, severity=v.severity, cvss_score=v.cvss_score,
                affected_range=v.affected_range, fix_version=v.fix_version, summary=v.summary,
            )
            for v in sorted(comp.vulnerabilities or [], key=_severity_sort_key)
        ],
    )


def asset_to_out(asset: DataAsset) -> DataAssetOut:
    return DataAssetOut(
        id=asset.id,
        name=asset.name,
        data_type=asset.data_type,
        classification=asset.classification,
        is_pii=asset.is_pii,
        is_sensitive_pii=asset.is_sensitive_pii,
        storage_envs=asset.storage_envs or [],
        cross_border_transfer=asset.cross_border_transfer,
        tables=[
            DataTableOut(
                id=t.id,
                table_name=t.table_name,
                fields=[DataFieldOut.model_validate(f) for f in t.fields or []],
            )
            for t in asset.tables or []
        ],
    )


def wizard_state(db: Session, project: Project) -> dict:
    """向导整卷状态(前端打开既有项目时一次拉全)。"""
    pid = project.id
    survey = db.query(GradingSurvey).filter_by(project_id=pid).first()
    assets = (
        db.query(DataAsset)
        .filter_by(project_id=pid)
        .order_by(DataAsset.id)
        .all()
    )

    def _plain(obj):
        if hasattr(obj, "model_dump"):
            return obj.model_dump()
        return obj

    roles = db.query(Role).filter_by(project_id=pid).order_by(Role.id).all()
    resource_rows = db.query(Resource).filter_by(project_id=pid).order_by(Resource.id).all()
    entries = (
        db.query(PermissionEntry)
        .join(Role, PermissionEntry.role_id == Role.id)
        .filter(Role.project_id == pid)
        .order_by(PermissionEntry.id).all()
    )
    return {
        "project": _plain_project(project),
        "survey": _plain(survey_to_out(survey, pid)),
        "features": [
            _plain_feature(f) for f in db.query(Feature).filter_by(project_id=pid).order_by(Feature.id).all()
        ],
        "data_assets": [_plain(asset_to_out(a)) for a in assets],
        "roles": [
            {"id": r.id, "name": r.name, "role_type": r.role_type,
             "user_count_estimate": r.user_count_estimate}
            for r in roles
        ],
        "resources": [
            {"id": r.id, "name": r.name, "resource_type": r.resource_type,
             "criticality": r.criticality}
            for r in resource_rows
        ],
        "permission_entries": [
            {"id": e.id, "role_id": e.role_id, "resource_id": e.resource_id,
             "action": e.action, "requires_approval": bool(e.requires_approval)}
            for e in entries
        ],
        "auth_config": _plain_auth_config(
            db.query(AuthConfig).filter_by(project_id=pid).first(), pid),
        "components": [_plain(component_to_out(c))
                       for c in db.query(SbomComponent).filter_by(project_id=pid).all()],
        "api_endpoints": [
            {"id": e.id, "name": e.name, "path": e.path, "method": e.method,
             "auth_required": e.auth_required, "public_exposed": e.public_exposed,
             "sensitive_asset_ids": e.sensitive_asset_ids or [], "rate_limit": e.rate_limit}
            for e in db.query(ApiEndpoint).filter_by(project_id=pid).order_by(ApiEndpoint.id).all()
        ],
        "infra_assets": [
            {"id": a.id, "asset_type": a.asset_type, "name": a.name, "env": a.env,
             "ip": a.ip, "owner": a.owner, "holds_sensitive": a.holds_sensitive}
            for a in db.query(InfraAsset).filter_by(project_id=pid).order_by(InfraAsset.id).all()
        ],
    }


def _plain_project(project: Project) -> dict:
    from schemas.project import ProjectOut, serialize_project
    return serialize_project(project).model_dump()


def _plain_feature(feature: Feature) -> dict:
    from schemas.feature import FeatureOut
    return FeatureOut.model_validate(feature).model_dump()


def _plain_auth_config(cfg: AuthConfig | None, project_id: int) -> dict | None:
    from schemas.auth import AuthConfigOut
    return None if cfg is None else AuthConfigOut.model_validate(cfg).model_dump()
