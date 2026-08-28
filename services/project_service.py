# -*- coding: utf-8 -*-
"""项目生命周期服务: 创建(唯一编码校验)/更新/级联删除/列表与向导状态装配。

种子数据的清理逻辑同样走 delete_project_cascade, 避免两处口径不一致。
"""
from sqlalchemy.orm import Session

import shared.constants as C
from models import (
    ApiEndpoint, AuthConfig, DataAsset, DataField, DataTable, Feature,
    GradingSurvey, InfraAsset, PermissionEntry, Project,
    SbomComponent, SecurityRequirement, VulnerabilityRecord, Resource, Role,
    ReviewEvidence, ReviewGate,
)


class ProjectExistsError(Exception):
    """项目编码已被占用。"""


def create_project(session: Session, data: dict) -> Project:
    code = (data.get("code") or "").strip()
    if session.query(Project).filter_by(code=code).first():
        raise ProjectExistsError(f"项目编码已存在: {code}")
    project = Project(**data)
    session.add(project)
    session.commit()
    return project


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
        "requirements": session.query(SecurityRequirement).filter_by(project_id=pid).count(),
        "vulnerabilities": session.query(VulnerabilityRecord).join(
            SbomComponent, VulnerabilityRecord.component_id == SbomComponent.id
        ).filter(SbomComponent.project_id == pid).count(),
    }


def effective_level(session: Session, project_id: int) -> str:
    survey = session.query(GradingSurvey).filter_by(project_id=project_id).first()
    return survey.effective_level() if survey else ""
