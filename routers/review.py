# -*- coding: utf-8 -*-
"""评审门禁路由(改造点4/5): 状态查询/提交/两步签核/留痕链查询与校验。

角色约束(接口层强制):
- 提交评审: 项目经理/开发中心;
- 第一步评审: 仅安全中心评审员, 且不得审自己提交的门禁;
- 终审: 仅安全中心负责人, 必须在评审员通过之后, 且不得与第一步评审人相同;
- 不满足门禁条件的提交返回 409 {"gate": ..., "status": "blocked", "missing": [...]}。
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

import shared.constants as C
from models import PlatformUser, Project, ReviewGate
from routers.common import get_db, get_project_or_404, require_write_roles
from schemas.review import (
    ChainVerifyOut, EvidenceOut, GateOut, ReviewActionIn,
)
from services.gate_service import (
    GateActionError, append_evidence, evaluate_gate, finalize_gate,
    get_or_create_gate, review_gate, submit_gate, verify_chain,
)

router = APIRouter(prefix="/api/projects/{project_id}/gates", tags=["review-gates"])


def _name_of(db: Session, user_id: int | None) -> str | None:
    if user_id is None:
        return None
    user = db.get(PlatformUser, user_id)
    return user.display_name if user else None


def _gate_out(db: Session, gate: ReviewGate) -> GateOut:
    check = evaluate_gate(db, gate.project_id, gate.gate_type)
    return GateOut(
        id=gate.id,
        gate_type=gate.gate_type,
        gate_label=C.label(C.GATE_TYPES, gate.gate_type),
        status=gate.status,
        status_label=C.label(C.GATE_STATUSES, gate.status),
        latest_verb=gate.latest_status_verb(),
        submitted_at=gate.submitted_at,
        reviewed_at=gate.reviewed_at,
        submitter=_name_of(db, gate.submitter_id),
        reviewer=_name_of(db, gate.reviewer_id),
        reviewer_conclusion=gate.reviewer_conclusion,
        reviewer_opinion=gate.reviewer_opinion,
        final_reviewer=_name_of(db, gate.final_reviewer_id),
        final_opinion=gate.final_opinion,
        final_reviewed_at=gate.final_reviewed_at,
        version_hash=gate.version_hash,
        check=check,
        evidence_count=len(gate.evidences or []),
    )


@router.get("", response_model=list[GateOut])
def list_gates(project: Project = Depends(get_project_or_404),
               db: Session = Depends(get_db)):
    """全部门禁(含预留类型)的状态 + 实时硬校验结果。"""
    out = []
    for gate_type in C.GATE_TYPES:
        gate = db.query(ReviewGate).filter_by(
            project_id=project.id, gate_type=gate_type,
        ).first()
        if gate is None:
            out.append(GateOut(
                id=0, gate_type=gate_type,
                gate_label=C.label(C.GATE_TYPES, gate_type),
                status="pending", status_label="待提交",
                latest_verb="待提交", check=evaluate_gate(db, project.id, gate_type),
            ))
        else:
            out.append(_gate_out(db, gate))
    return out


@router.post("/{gate_type}/submit", response_model=GateOut)
def submit(gate_type: str, request: Request,
           project: Project = Depends(get_project_or_404),
           db: Session = Depends(get_db),
           user: PlatformUser = Depends(require_write_roles("pm", "developer"))):
    """提交评审(硬校验失败返回 409, 响应体即 {"gate","status","missing"} 口径)。"""
    if gate_type not in C.GATE_TYPES:
        raise HTTPException(status_code=404, detail=f"未知门禁类型: {gate_type}")
    try:
        gate = submit_gate(db, project.id, gate_type, user,
                           ip=request.client.host if request.client else None)
    except GateActionError as exc:
        check = evaluate_gate(db, project.id, gate_type)
        return JSONResponse(
            status_code=409,
            content={"gate": gate_type, "status": "blocked",
                     "missing": check["missing"], "message": str(exc)},
        )
    return _gate_out(db, gate)


@router.post("/{gate_id}/review", response_model=GateOut)
def review(gate_id: int, payload: ReviewActionIn, request: Request,
           project: Project = Depends(get_project_or_404),
           db: Session = Depends(get_db),
           user: PlatformUser = Depends(require_write_roles("security_reviewer"))):
    """评审员第一步审核(approve/reject/request_change)。"""
    try:
        gate = review_gate(db, gate_id, user, payload.action, payload.opinion,
                           ip=request.client.host if request.client else None)
    except GateActionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return _gate_out(db, gate)


@router.post("/{gate_id}/final", response_model=GateOut)
def final(gate_id: int, payload: ReviewActionIn, request: Request,
          project: Project = Depends(get_project_or_404),
          db: Session = Depends(get_db),
          user: PlatformUser = Depends(require_write_roles("security_lead"))):
    """负责人终审(sign → passed / reject → rejected), 须评审员已通过。"""
    try:
        gate = finalize_gate(db, gate_id, user, payload.action, payload.opinion,
                             ip=request.client.host if request.client else None)
    except GateActionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return _gate_out(db, gate)


@router.get("/{gate_id}/evidence", response_model=list[EvidenceOut])
def evidence(gate_id: int, project: Project = Depends(get_project_or_404),
             db: Session = Depends(get_db)):
    gate = db.get(ReviewGate, gate_id)
    if gate is None or gate.project_id != project.id:
        raise HTTPException(status_code=404, detail="门禁不存在")
    return [
        EvidenceOut(
            id=e.id,
            actor=(u.display_name if (u := db.get(PlatformUser, e.actor_id)) else str(e.actor_id)),
            actor_role=C.label(C.PLATFORM_ROLES, u.role) if u else "",
            action=e.action,
            action_label=C.label(C.REVIEW_ACTIONS, e.action),
            timestamp=e.timestamp,
            ip=e.ip,
            comment=e.comment,
            prev_hash=e.prev_hash,
            curr_hash=e.curr_hash,
        )
        for e in gate.evidences
    ]


@router.get("/{gate_id}/evidence/verify", response_model=ChainVerifyOut)
def evidence_verify(gate_id: int, project: Project = Depends(get_project_or_404),
                    db: Session = Depends(get_db)):
    """复算链式哈希(审计导出用)。"""
    gate = db.get(ReviewGate, gate_id)
    if gate is None or gate.project_id != project.id:
        raise HTTPException(status_code=404, detail="门禁不存在")
    result = verify_chain(db, gate_id)
    return ChainVerifyOut(gate_id=gate_id, **result)


@router.post("/{gate_type}/note")
def append_note(gate_type: str, payload: ReviewActionIn,
                project: Project = Depends(get_project_or_404),
                db: Session = Depends(get_db),
                user: PlatformUser = Depends(require_write_roles("security_reviewer", "security_lead"))):
    """评审/终审阶段补充意见(不改状态, 仅追加留痕)。"""
    gate = get_or_create_gate(db, project.id, gate_type)
    append_evidence(
        db, gate, user, "comment",
        ip=None, comment=payload.opinion, payload={"note": True},
    )
    db.commit()
    return {"ok": True, "evidence_count": len(gate.evidences)}
