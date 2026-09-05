# -*- coding: utf-8 -*-
"""评审动作流端点(#218): 提交/批注/裁定/终审/状态与时间线。

角色口径(#216): 提交=pm/安全负责人; 批注与裁定=安全侧(评审员/负责人);
终审=仅安全负责人。提交人不得自审, 评审员不得终审自己的裁定(服务层硬约束)。
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from models import PlatformUser, Project, ReviewGate, SecurityRequirement
from routers.common import (
    client_ip, ensure_project_access, get_db, require_login, require_write_roles,
)
from services.audit_service import audit
from services.review_service import (
    ReviewFlowError, ReviewForbidden, annotate_requirement, decide_review,
    finalize_review, get_or_create_gate, review_state, submit_review,
)

import shared.constants as C

router = APIRouter(prefix="/api/projects/{project_id}/review", tags=["review"])


class ProjectUserCtx:
    def __init__(self, project: Project, user: PlatformUser):
        self.project = project
        self.user = user


def _write_ctx(*roles: str):
    """项目装载 + 角色白名单 + 归属校验的组合依赖(评审端点通用)。"""
    def dependency(
        project_id: int,
        request: Request,
        db: Session = Depends(get_db),
        user: PlatformUser = Depends(require_write_roles(*roles)),
    ) -> ProjectUserCtx:
        project = db.get(Project, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail=f"评估不存在: id={project_id}")
        ensure_project_access(user, project)
        return ProjectUserCtx(project, user)

    return dependency


def _gate_or_404(ctx: ProjectUserCtx, db: Session,
                 gate_type: str = "requirement") -> ReviewGate:
    return get_or_create_gate(db, ctx.project, gate_type)


def _requirement_or_404(ctx: ProjectUserCtx, db: Session, req_id: str) -> SecurityRequirement:
    req = db.query(SecurityRequirement).filter_by(
        project_id=ctx.project.id, req_id=req_id).first()
    if req is None:
        raise HTTPException(status_code=404, detail=f"需求不存在: {req_id}")
    return req


# ── 请求体 ────────────────────────────────────────────


class ReviewOpinionIn(BaseModel):
    comment: str | None = Field(default=None, max_length=2000)


class AnnotateIn(BaseModel):
    disposition: str = Field(description="approve/object/return")
    comment: str | None = Field(default=None, max_length=2000)


class DecideIn(BaseModel):
    conclusion: str = Field(description="approve/request_change/reject")
    comment: str | None = Field(default=None, max_length=2000)


# ── 端点 ──────────────────────────────────────────────


@router.post("/submit")
def submit(ctx: ProjectUserCtx = Depends(_write_ctx("pm", "security_lead")),
           db: Session = Depends(get_db),
           request: Request = None):
    """提交评审(#218): 硬校验未过返回 blocked 契约; 通过则门禁进入 in_review。"""
    try:
        gate, missing = submit_review(db, ctx.project, ctx.user)
    except ReviewFlowError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if missing:
        db.commit()
        audit(db, ctx.user.username, "review_submit_blocked",
              {"project_id": ctx.project.id, "missing": missing}, client_ip(request))
        return {"status": "blocked", "missing": missing}
    db.commit()
    audit(db, ctx.user.username, "review_submit",
          {"project_id": ctx.project.id, "gate_id": gate.id}, client_ip(request))
    return {"status": "submitted", "gate_status": gate.status,
            "version_hash": gate.version_hash}


@router.post("/requirements/{req_id}/annotate")
def annotate(req_id: str, payload: AnnotateIn,
             ctx: ProjectUserCtx = Depends(_write_ctx(*C.SECURITY_SIDE_ROLES)),
             db: Session = Depends(get_db),
             request: Request = None):
    """评审员逐条批注(#218): approve=通过 / return=退回整改 / object=异议留痕。"""
    gate = _gate_or_404(ctx, db)
    req = _requirement_or_404(ctx, db, req_id)
    try:
        annotate_requirement(db, ctx.project, gate, req, ctx.user,
                             payload.disposition, payload.comment)
    except (ReviewFlowError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ReviewForbidden as exc:
        db.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    db.commit()
    audit(db, ctx.user.username, "review_annotate",
          {"project_id": ctx.project.id, "req_id": req_id,
           "disposition": payload.disposition}, client_ip(request))
    return {"status": "ok", "req_id": req_id,
            "review_status": req.review_status}


@router.post("/decide")
def decide(payload: DecideIn,
           ctx: ProjectUserCtx = Depends(_write_ctx(*C.SECURITY_SIDE_ROLES)),
           db: Session = Depends(get_db),
           request: Request = None):
    """评审员整体裁定(#218): approve=待终审 / request_change=退回整改 / reject=否决。"""
    gate = _gate_or_404(ctx, db)
    try:
        decide_review(db, ctx.project, gate, ctx.user,
                      payload.conclusion, payload.comment)
    except ReviewFlowError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ReviewForbidden as exc:
        db.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    db.commit()
    audit(db, ctx.user.username, "review_decide",
          {"project_id": ctx.project.id, "conclusion": payload.conclusion},
          client_ip(request))
    return {"status": "ok", "gate_status": gate.status}


@router.post("/finalize")
def finalize(payload: ReviewOpinionIn,
             ctx: ProjectUserCtx = Depends(_write_ctx("security_lead")),
             db: Session = Depends(get_db),
             request: Request = None):
    """终审会签(#218): 仅评审员 approve 后可终审; 通过 → passed(基线写回触发源)。"""
    gate = _gate_or_404(ctx, db)
    try:
        finalize_review(db, ctx.project, gate, ctx.user, payload.comment)
    except ReviewFlowError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ReviewForbidden as exc:
        db.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    db.commit()
    audit(db, ctx.user.username, "review_finalize",
          {"project_id": ctx.project.id, "gate_status": gate.status},
          client_ip(request))
    return {"status": "ok", "gate_status": gate.status}


@router.get("/state")
def state(project_id: int,
          user: PlatformUser = Depends(require_login),
          db: Session = Depends(get_db)):
    """门禁状态 + 留痕时间线 + 需求状态汇总(前端评审视图数据源)。"""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"评估不存在: id={project_id}")
    ensure_project_access(user, project)
    return review_state(db, project, user)
