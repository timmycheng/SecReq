# -*- coding: utf-8 -*-
"""项目 CRUD 路由(Step1 + 向导状态装载)。

数据权限: 开发(developer)只能看到/操作自己创建的项目, 安全(security)全量可见;
越权访问一律按 404 处理, 不泄露项目存在性。
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from models import Filing, GradingSurvey, PlatformUser, Project, System  # noqa: F401 (类型标注用)
from routers.common import (
    client_ip, get_db, get_project_or_404, require_login,
    require_write_roles, visible_projects_query, wizard_state,
)
from schemas.project import (
    ProjectCreate, ProjectDetail, ProjectUpdate, serialize_project,
)
from services.audit_service import audit
from services.project_copy import copy_wizard_data, reset_wizard_data
from services.project_service import ProjectExistsError, create_project, project_counts, update_project
from services.system_service import current_baseline_id

router = APIRouter(prefix="/api/projects", tags=["projects"])

_writable = Depends(require_write_roles("developer", "security"))


def _resolve_system(db: Session, user: PlatformUser, system_id: int | None) -> None:
    """归属校验: 系统须存在且在数据权限内(开发仅可关联本人系统)。"""
    if system_id is None:
        return
    system = db.get(System, system_id)
    if system is None or (
        user.role != "security" and system.owner_user_id not in (None, user.id)
    ):
        raise HTTPException(status_code=400, detail=f"所属系统不存在或无权关联: id={system_id}")


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
    if project.system_id:
        system = db.get(System, project.system_id)
        if system:
            detail.system_name = system.name
            filing = db.get(Filing, system.filing_id) if system.filing_id else None
            if filing:
                detail.filing_name = filing.name
                detail.filing_level = filing.level
            detail.is_current_baseline = current_baseline_id(db, system.id) == project.id
    return detail


@router.post("", response_model=ProjectDetail, status_code=201, dependencies=[_writable])
def create(payload: ProjectCreate, request: Request, db: Session = Depends(get_db),
           user: PlatformUser = Depends(require_write_roles("developer", "security"))):
    _resolve_system(db, user, payload.system_id)
    source: Project | None = None
    if payload.from_project_id:
        source = db.get(Project, payload.from_project_id)
        if source is None:
            raise HTTPException(status_code=404, detail=f"来源项目不存在: id={payload.from_project_id}")
        from routers.common import ensure_project_access
        ensure_project_access(user, source)
        _resolve_system(db, user, source.system_id)
    data = payload.model_dump()
    if source is not None and "system_id" not in payload.model_dump(exclude_unset=True):
        data["system_id"] = source.system_id  # 评估继承: 未显式指定时沿用来源项目的系统
    try:
        project = create_project(db, data, owner_user_id=user.id)
    except ProjectExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if source is not None:
        from services.project_copy import copy_wizard_data
        copy_wizard_data(db, source, project)
    audit(db, user.username, "project_create",
          {"project_id": project.id, "code": project.code, "name": project.name,
           **({"copied_from": source.id} if source else {})},
          client_ip(request))
    return _detail(db, project)


class CopyFromIn(BaseModel):
    from_project_id: int


@router.post("/{project_id}/copy-from", response_model=ProjectDetail,
             dependencies=[_writable])
def copy_from(project_id: int, payload: CopyFromIn, request: Request,
              db: Session = Depends(get_db),
              user: PlatformUser = Depends(require_write_roles("developer", "security"))):
    """从来源项目整卷复制向导数据到**已落库**的当前项目(#172, Step1 就地复制)。

    先清后拷(整卷替换语义, 与向导各步保存一致): 当前项目已有输入会被覆盖,
    不会因重复 uid 叠加成脏数据。
    """
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"项目不存在: id={project_id}")
    from routers.common import ensure_project_access
    ensure_project_access(user, project)
    source = db.get(Project, payload.from_project_id)
    if source is None:
        raise HTTPException(status_code=404, detail=f"来源项目不存在: id={payload.from_project_id}")
    ensure_project_access(user, source)
    if source.id == project.id:
        raise HTTPException(status_code=400, detail="不能从项目自身复制")
    reset_wizard_data(db, project.id)
    copy_wizard_data(db, source, project)
    audit(db, user.username, "project_copy_from",
          {"project_id": project.id, "copied_from": source.id}, client_ip(request))
    return _detail(db, project)


@router.post("/{project_id}/reset-wizard", response_model=ProjectDetail,
             dependencies=[_writable])
def reset_wizard(project_id: int, request: Request,
                 db: Session = Depends(get_db),
                 user: PlatformUser = Depends(require_write_roles("developer", "security"))):
    """一键清空当前项目全部向导输入(#172), 相当于回到空白模板; 生成产出不动。"""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"项目不存在: id={project_id}")
    from routers.common import ensure_project_access
    ensure_project_access(user, project)
    reset_wizard_data(db, project.id)
    audit(db, user.username, "project_reset_wizard",
          {"project_id": project.id}, client_ip(request))
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
    if "system_id" in changes:
        _resolve_system(db, user, changes["system_id"])
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
    audit(db, user.username, "project_delete", snapshot, client_ip(request))


@router.get("/{project_id}/wizard-state")
def load_wizard_state(project: Project = Depends(get_project_or_404),
                      db: Session = Depends(get_db),
                      user: PlatformUser = Depends(require_login)):
    """一次拉取向导全部步骤数据(编辑既有项目用)。"""
    from routers.common import ensure_project_access
    ensure_project_access(user, project)
    return wizard_state(db, project)
