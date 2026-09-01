# -*- coding: utf-8 -*-
"""项目生命周期服务: 创建(唯一编码校验)/更新/级联删除/列表与向导状态装配。

种子数据的清理逻辑同样走 delete_project_cascade, 避免两处口径不一致。
"""
from datetime import datetime

from sqlalchemy.orm import Session

from models import (
    ApiEndpoint, AuthConfig, DataAsset, DataField, DataTable, ExternalSystem,
    Feature, GradingSurvey, InfraAsset, PermissionEntry, Project,
    SbomComponent, SecurityRequirement, VulnerabilityRecord, Resource, Role,
    ReviewEvidence, ReviewGate,
)


class ProjectExistsError(Exception):
    """项目编码已被占用。"""


def generate_project_code(session: Session) -> str:
    """自动生成项目编码: {前缀}{可选年份}{自增序号}, 冲突时序号递增(#85)。

    规则存 system_settings(key=project_code_rule), 未配置时回退历史格式
    XM<年份>-<三位序号>(老项目编号不受影响)。prefix 校验为字母数字,
    编码兼作产物输出目录名, 防路径穿越。
    """
    from services.settings_service import get_project_code_rule

    rule = get_project_code_rule(session)
    prefix = rule["prefix"] + (str(datetime.now().year) if rule["include_year"] else "")
    body_prefix = f"{prefix}-"
    used = {
        row[0] for row in session.query(Project.code).filter(Project.code.like(f"{body_prefix}%")).all()
    }
    seq = 1
    while f"{body_prefix}{seq:0{rule['digits']}d}" in used:
        seq += 1
    return f"{body_prefix}{seq:0{rule['digits']}d}"


def create_project(session: Session, data: dict, owner_user_id: int | None = None) -> Project:
    code = (data.get("code") or "").strip() or generate_project_code(session)
    if session.query(Project).filter_by(code=code).first():
        raise ProjectExistsError(f"项目编码已存在: {code}")
    data = {k: v for k, v in data.items() if k != "code"} | {"code": code}
    project = Project(**data, owner_user_id=owner_user_id)
    session.add(project)
    session.commit()
    return project


def populate_project_types(session: Session) -> int:
    """存量项目 types 为空时按单值 type 回填(类型多选改造), 幂等。"""

    rows = session.query(Project).filter(Project.types.is_(None)).all()
    rows += [r for r in session.query(Project).filter(
        Project.types.isnot(None)).all() if not r.types]
    seen = set()
    for project in rows:
        if project.id in seen:
            continue
        seen.add(project.id)
        project.types = [project.type] if project.type else []
        project.type = project.types[0] if project.types else ""
        flag_modified(project)
    if seen:
        session.commit()
    return len(seen)


def flag_modified(instance) -> None:
    """标记 JSON 列已变更(SQLite 存量 NULL 行更新需要)。"""
    from sqlalchemy.orm.attributes import flag_modified as _fm
    _fm(instance, "types")


def assign_legacy_projects(session: Session) -> int:
    """存量无主项目归入第一个有效开发账号(数据权限迁移), 幂等。返回处理数。"""
    from models import PlatformUser

    unowned = session.query(Project).filter(Project.owner_user_id.is_(None)).all()
    if not unowned:
        return 0
    dev = session.query(PlatformUser).filter_by(role="developer", active=True).first()
    target_id = dev.id if dev else None
    for project in unowned:
        project.owner_user_id = target_id
    session.commit()
    return len(unowned)


def update_project(session: Session, project: Project, changes: dict) -> Project:
    for key, value in changes.items():
        setattr(project, key, value)
    session.commit()
    return project


def delete_project_cascade(session: Session, project_id: int) -> None:
    """按外键顺序清空项目全部子表数据(先叶子后主表)。"""
    pid = project_id
    session.query(DataField).filter(
        DataField.table_id.in_(session.query(DataTable.id).filter(
            DataTable.asset_id.in_(session.query(DataAsset.id).filter_by(project_id=pid))
        ))
    ).delete(synchronize_session=False)
    session.query(DataTable).filter(
        DataTable.asset_id.in_(session.query(DataAsset.id).filter_by(project_id=pid))
    ).delete(synchronize_session=False)
    session.query(DataAsset).filter_by(project_id=pid).delete(synchronize_session=False)

    session.query(PermissionEntry).filter(
        PermissionEntry.role_id.in_(session.query(Role.id).filter_by(project_id=pid))
    ).delete(synchronize_session=False)
    session.query(Role).filter_by(project_id=pid).delete(synchronize_session=False)
    session.query(Resource).filter_by(project_id=pid).delete(synchronize_session=False)

    session.query(VulnerabilityRecord).filter(
        VulnerabilityRecord.component_id.in_(
            session.query(SbomComponent.id).filter_by(project_id=pid))
    ).delete(synchronize_session=False)
    session.query(SbomComponent).filter_by(project_id=pid).delete(synchronize_session=False)

    session.query(ApiEndpoint).filter_by(project_id=pid).delete(synchronize_session=False)
    session.query(InfraAsset).filter_by(project_id=pid).delete(synchronize_session=False)
    session.query(ExternalSystem).filter_by(project_id=pid).delete(synchronize_session=False)
    session.query(AuthConfig).filter_by(project_id=pid).delete(synchronize_session=False)
    session.query(GradingSurvey).filter_by(project_id=pid).delete(synchronize_session=False)
    session.query(Feature).filter_by(project_id=pid).delete(synchronize_session=False)
    session.query(SecurityRequirement).filter_by(project_id=pid).delete(synchronize_session=False)

    session.query(ReviewEvidence).filter(
        ReviewEvidence.gate_id.in_(session.query(ReviewGate.id).filter_by(project_id=pid))
    ).delete(synchronize_session=False)
    session.query(ReviewGate).filter_by(project_id=pid).delete(synchronize_session=False)

    session.query(Project).filter_by(id=pid).delete(synchronize_session=False)
    session.commit()


def project_counts(session: Session, project_id: int) -> dict[str, int]:
    """列表卡片用的各步骤条目数。"""
    pid = project_id
    return {
        "features": session.query(Feature).filter_by(project_id=pid).count(),
        "data_assets": session.query(DataAsset).filter_by(project_id=pid).count(),
        "roles": session.query(Role).filter_by(project_id=pid).count(),
        "resources": session.query(Resource).filter_by(project_id=pid).count(),
        "permission_entries": session.query(PermissionEntry).join(
            Role, PermissionEntry.role_id == Role.id
        ).filter(Role.project_id == pid).count(),
        "components": session.query(SbomComponent).filter_by(project_id=pid).count(),
        "api_endpoints": session.query(ApiEndpoint).filter_by(project_id=pid).count(),
        "infra_assets": session.query(InfraAsset).filter_by(project_id=pid).count(),
        "external_systems": session.query(ExternalSystem).filter_by(project_id=pid).count(),
        "requirements": session.query(SecurityRequirement).filter_by(project_id=pid).count(),
        "vulnerabilities": session.query(VulnerabilityRecord).join(
            SbomComponent, VulnerabilityRecord.component_id == SbomComponent.id
        ).filter(SbomComponent.project_id == pid).count(),
    }


def effective_level(session: Session, project_id: int) -> str:
    survey = session.query(GradingSurvey).filter_by(project_id=project_id).first()
    return survey.effective_level() if survey else ""
