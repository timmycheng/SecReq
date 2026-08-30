# -*- coding: utf-8 -*-
"""项目 CRUD 路由(Step1 + 向导状态装载)。

数据权限: 开发(developer)只能看到/操作自己创建的项目, 安全(security)全量可见;
越权访问一律按 404 处理, 不泄露项目存在性。
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from models import GradingSurvey, PlatformUser, Project  # noqa: F401 (类型标注用)
from routers.common import (
    get_db, get_project_or_404, require_login,
    require_write_roles, visible_projects_query, wizard_state,
)
from schemas.project import (
    ProjectCreate, ProjectDetail, ProjectUpdate, serialize_project,
)
from services.audit_service import audit
from services.project_service import ProjectExistsError, create_project, project_counts, update_project

router = APIRouter(prefix="/api/projects", tags=["projects"])

_writable = Depends(require_write_roles("developer", "security"))


def _detail(db: Session, project: Project) -> ProjectDetail:
    survey = db.query(GradingSurvey).filter_by(project_id=project.id).first()
    detail = ProjectDetail(
        **serialize_project(project).model_dump(),
        has_survey=survey is not None,
        grading_level=survey.effective_level() if survey else None,
        counts=project_counts(db, project.id),
    )
    if project.owner_user_id:
        owner = db.get(PlatformUser, project.owner_user_id)
        detail.owner_name = owner.display_name if owner else None
    return detail


@router.post("", response_model=ProjectDetail, status_code=201, dependencies=[_writable])
def create(payload: ProjectCreate, db: Session = Depends(get_db),
           user: PlatformUser = Depends(require_write_roles("developer", "security"))):
    try:
        project = create_project(db, payload.model_dump(), owner_user_id=user.id)
    except ProjectExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    audit(db, user.username, "project_create",
          {"project_id": project.id, "code": project.code, "name": project.name})
    return _detail(db, project)


@router.get("", response_model=list[ProjectDetail])
def list_all(db: Session = Depends(get_db), user: PlatformUser = Depends(require_login)):
    items: list[ProjectDetail] = []
    for project in visible_projects_query(db, user).all():
        items.append(_detail(db, project))
    return items


@router.get("/{project_id}", response_model=ProjectDetail)
def get_one(project: Project = Depends(get_project_or_404),
            db: Session = Depends(get_db),
            user: PlatformUser = Depends(require_login)):
    from routers.common import ensure_project_access
    ensure_project_access(user, project)
    return _detail(db, project)


@router.patch("/{project_id}", response_model=ProjectDetail, dependencies=[_writable])
def patch(payload: ProjectUpdate, project: Project = Depends(get_project_or_404),
          db: Session = Depends(get_db),
          user: PlatformUser = Depends(require_write_roles("developer", "security"))):
    from routers.common import ensure_project_access
    ensure_project_access(user, project)
    changes = payload.model_dump(exclude_unset=True)
    if "code" in changes and changes["code"] != project.code:
        raise HTTPException(status_code=400, detail="项目编码不允许修改")
    project = update_project(db, project, changes)
    return _detail(db, project)


@router.delete("/{project_id}", status_code=204, dependencies=[_writable])
def remove(request: Request, project: Project = Depends(get_project_or_404),
           db: Session = Depends(get_db),
           user: PlatformUser = Depends(require_write_roles("developer", "security"))):
    from routers.common import ensure_project_access
    from services.project_service import delete_project_cascade
    ensure_project_access(user, project)
    # 先取出标识再删, 删完再留痕(确保记录的是"已发生的删除")
    snapshot = {"project_id": project.id, "code": project.code, "name": project.name}
    delete_project_cascade(db, project.id)
    audit(db, user.username, "project_delete", snapshot,
          request.client.host if request.client else None)


@router.get("/{project_id}/wizard-state")
def load_wizard_state(project: Project = Depends(get_project_or_404),
                      db: Session = Depends(get_db),
                      user: PlatformUser = Depends(require_login)):
    """一次拉取向导全部步骤数据(编辑既有项目用)。"""
    from routers.common import ensure_project_access
    ensure_project_access(user, project)
    return wizard_state(db, project)
