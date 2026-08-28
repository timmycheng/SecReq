# -*- coding: utf-8 -*-
"""项目 CRUD 路由(Step1 + 向导状态装载)。写操作仅项目经理(pm)。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import shared.constants as C
from models import GradingSurvey, Project  # noqa: F401 (Project 供类型标注)
from routers.common import (
    get_db, get_project_or_404, require_write_roles, wizard_state,
)
from schemas.project import (
    ProjectCreate, ProjectDetail, ProjectUpdate, serialize_project,
)
from services.project_service import ProjectExistsError, create_project, project_counts, update_project

router = APIRouter(prefix="/api/projects", tags=["projects"])

_pm_only = Depends(require_write_roles("pm"))


@router.post("", response_model=ProjectDetail, status_code=201, dependencies=[_pm_only])
def create(payload: ProjectCreate, db: Session = Depends(get_db)):
    try:
        project = create_project(db, payload.model_dump())
    except ProjectExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    detail = ProjectDetail(**serialize_project(project).model_dump())
    detail.counts = project_counts(db, project.id)
    return detail


@router.get("", response_model=list[ProjectDetail])
def list_all(db: Session = Depends(get_db)):
    items: list[ProjectDetail] = []
    for project in db.query(Project).order_by(Project.created_at.desc(), Project.id.desc()).all():
        survey = db.query(GradingSurvey).filter_by(project_id=project.id).first()
        detail = ProjectDetail(
            **serialize_project(project).model_dump(),
            has_survey=survey is not None,
            grading_level=survey.effective_level() if survey else None,
            counts=project_counts(db, project.id),
        )
        items.append(detail)
    return items


@router.get("/{project_id}", response_model=ProjectDetail)
def get_one(project: Project = Depends(get_project_or_404), db: Session = Depends(get_db)):
    survey = db.query(GradingSurvey).filter_by(project_id=project.id).first()
    detail = ProjectDetail(
        **serialize_project(project).model_dump(),
        has_survey=survey is not None,
        grading_level=survey.effective_level() if survey else None,
        counts=project_counts(db, project.id),
    )
    return detail


@router.patch("/{project_id}", response_model=ProjectDetail, dependencies=[_pm_only])
def patch(payload: ProjectUpdate, project: Project = Depends(get_project_or_404),
          db: Session = Depends(get_db)):
    changes = payload.model_dump(exclude_unset=True)
    if "code" in changes:
        raise HTTPException(status_code=400, detail="项目编码不允许修改")
    project = update_project(db, project, changes)
    return ProjectDetail(**serialize_project(project).model_dump())


@router.delete("/{project_id}", status_code=204, dependencies=[_pm_only])
def remove(project: Project = Depends(get_project_or_404), db: Session = Depends(get_db)):
    from services.project_service import delete_project_cascade
    delete_project_cascade(db, project.id)


@router.get("/{project_id}/wizard-state")
def load_wizard_state(project: Project = Depends(get_project_or_404),
                      db: Session = Depends(get_db)):
    """一次拉取向导全部步骤数据(编辑既有项目用)。"""
    return wizard_state(db, project)
