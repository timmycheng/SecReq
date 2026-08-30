# -*- coding: utf-8 -*-
"""路由公共件: 会话依赖 / 项目装载 / RBAC / ORM→API 模型序列化。"""
from collections.abc import Callable, Generator

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from models import (
    ApiEndpoint, AuthConfig, DataAsset, DataField, DataTable, ExternalSystem,
    Feature, GradingSurvey, InfraAsset, PermissionEntry, PlatformUser, Project,
    SbomComponent, VulnerabilityRecord, Resource, Role,
)
from schemas.component import ComponentOut, ComponentVulnInline
from schemas.data_dictionary import DataAssetOut, DataFieldOut, DataTableOut
from schemas.survey import SurveyOut

import shared.constants as C

# 身份经 Authorization: Bearer <token> 携带(登录后签发, 见 routers/auth.py)
OPEN_API_PREFIXES = ("/api/health", "/api/meta", "/api/auth/login")
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖: 每请求一个会话(测试通过 dependency_overrides 替换)。"""
    from main import SessionLocal
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _bearer_token(request: Request) -> str | None:
    auth = request.headers.get("Authorization") or ""
    if auth.startswith("Bearer "):
        return auth[len("Bearer "):].strip() or None
    return None


def get_current_user(request: Request, db: Session = Depends(get_db)) -> PlatformUser | None:
    """按 Bearer token 解析平台用户; 未携带或会话失效返回 None。"""
    from services.session_service import resolve_session

    return resolve_session(db, _bearer_token(request))


def auth_guard(
    request: Request, user: PlatformUser | None = Depends(get_current_user),
) -> None:
    """全局认证拦截(挂载于 app 级依赖):

    - 开放路径(健康检查/枚举常量/登录)直接放行;
    - 其余路径一律要求登录(读写都拦): 平台自身存储敏感数据, 不做匿名读。
    """
    path = request.url.path
    if any(path.startswith(prefix) for prefix in OPEN_API_PREFIXES):
        return
    if user is None:
        raise HTTPException(status_code=401, detail="未登录或会话已过期, 请重新登录")


def require_write_roles(*roles: str) -> Callable:
    """业务写接口的角色白名单依赖(读操作不拦)。"""

    def dependency(
        request: Request, user: PlatformUser | None = Depends(get_current_user),
    ) -> PlatformUser:
        if request.method not in WRITE_METHODS:
            return user  # type: ignore[return-value]
        if user is None:
            raise HTTPException(status_code=401, detail="未登录或会话已过期, 请重新登录")
        if user.role not in roles:
            role_names = "、".join(C.label(C.PLATFORM_ROLES, r) for r in roles)
            raise HTTPException(
                status_code=403,
                detail=f"当前角色「{C.label(C.PLATFORM_ROLES, user.role)}」无权执行该操作, "
                       f"仅允许: {role_names}")
        return user

    return dependency


def require_login(user: PlatformUser | None = Depends(get_current_user)) -> PlatformUser:
    """读接口也要登录(项目数据按身份过滤, 不做匿名读)。"""
    if user is None:
        raise HTTPException(status_code=401, detail="未登录或会话已过期, 请重新登录")
    return user


def visible_projects_query(db: Session, user: PlatformUser):
    """数据权限: 开发只看自己创建的项目, 安全看全部。"""
    query = db.query(Project)
    if user.role != "security":
        query = query.filter(Project.owner_user_id == user.id)
    return query.order_by(Project.created_at.desc(), Project.id.desc())


def ensure_project_access(user: PlatformUser, project: Project) -> None:
    """单项目访问口径: 安全全量可见, 开发仅限本人创建; 越权返回 404(不泄露存在性)。"""
    if user.role != "security" and project.owner_user_id not in (None, user.id):
        raise HTTPException(status_code=404, detail=f"项目不存在: id={project.id}")


def get_project_or_404(project_id: int, db: Session = Depends(get_db)) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"项目不存在: id={project_id}")
    return project


def get_accessible_project(
    project: Project = Depends(get_project_or_404),
    user: PlatformUser = Depends(require_login),
) -> Project:
    """读场景: 装载项目并做归属校验。"""
    ensure_project_access(user, project)
    return project


def get_writable_project(
    project: Project = Depends(get_project_or_404),
    user: PlatformUser = Depends(require_write_roles(*C.WRITE_WIZARD_ROLES)),
) -> Project:
    """写场景: 装载项目 + 角色白名单 + 归属校验。"""
    ensure_project_access(user, project)
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
        ecosystem=comp.ecosystem,
        distro=comp.distro,
        vuln_status=comp.vuln_status,
        vuln_status_note=comp.vuln_status_note,
        vulnerabilities=[
            ComponentVulnInline(
                cve_id=v.cve_id, severity=v.severity, cvss_score=v.cvss_score,
                affected_range=v.affected_range, fix_version=v.fix_version, summary=v.summary,
                cnnvd_id=v.cnnvd_id, cn_severity=v.cn_severity,
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
        legacy_classification=asset.legacy_classification,
        c3_tag=bool(asset.c3_tag),
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
        "external_systems": [
            {"id": e.id, "name": e.name, "purpose": e.purpose,
             "direction": e.direction, "involves_sensitive": bool(e.involves_sensitive)}
            for e in db.query(ExternalSystem).filter_by(project_id=pid).order_by(ExternalSystem.id).all()
        ],
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
