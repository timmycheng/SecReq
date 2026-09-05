# -*- coding: utf-8 -*-
"""评审动作流(#218): 门禁推进 + 链式哈希留痕 + 交付物快照。

把 models/review.py 休眠的 ReviewGate(两步签核)/ReviewEvidence(链式哈希)跑起来:
    提交(pm) → 评审员批注/裁定(security_reviewer) → 负责人终审会签(security_lead),
    request_change/reject → rectifying, 整改后重新提交形成闭环。

硬约束: 提交人/评审员/终审人三者不得为同一人; 两步签核顺序不可跳过。
门禁硬校验通过 GATE_CHECKS 注册表挂接(#220 需求门禁 / #222 设计门禁), 本层只汇总契约。
"""
import hashlib
import json
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from models import PlatformUser, Project, ReviewEvidence, ReviewGate, SecurityRequirement
from routers.common import ensure_project_access
from services.requirement_lifecycle import (
    RequirementTransitionError, transition_requirement,
)
from services.review_gates import requirement_gate_checks

GENESIS_HASH = "0" * 64


class ReviewFlowError(ValueError):
    """评审流程非法推进(路由层转 409)。"""


class ReviewForbidden(PermissionError):
    """评审动作越权(提交人自审等, 路由层转 403)。"""


# ── 门禁校验注册表(#220 需求门禁已挂; #222 设计门禁待接) ──
# checker(db, project) -> list[str]: 返回缺项描述列表, 空列表=通过。
GATE_CHECKS: dict[str, list] = {
    "requirement": [requirement_gate_checks],
    "design": [],
}


def collect_gate_missing(db: Session, project: Project) -> list[str]:
    """提交评审时的全部硬校验: 一次给出全部缺项(blocked 契约的 missing 列表)。"""
    missing: list[str] = []
    for checkers in GATE_CHECKS.values():
        for checker in checkers:
            missing.extend(checker(db, project))
    return missing


# ── 快照与哈希链 ──────────────────────────────────────


def compute_version_hash(db: Session, project: Project) -> str:
    """提交时全部交付物的 SHA256 快照: 需求清单 + 门禁相关向导数据。"""
    requirements = [
        {
            "req_id": r.req_id, "title": r.title, "priority": r.priority,
            "description": r.description, "category": r.category,
            "review_status": r.review_status,
        }
        for r in db.query(SecurityRequirement)
        .filter_by(project_id=project.id).order_by(SecurityRequirement.req_id).all()
    ]
    snapshot = {
        "project": {"code": project.code, "name": project.name,
                    "status": project.status},
        "requirements": requirements,
    }
    canonical = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _evidence_hash(prev_hash: str, gate_id: int, actor_id: int | None, action: str,
                   timestamp: datetime, payload: dict, comment: str | None) -> str:
    canonical = json.dumps({
        "prev_hash": prev_hash, "gate_id": gate_id, "actor_id": actor_id,
        "action": action, "timestamp": timestamp.isoformat(),
        "payload": payload, "comment": comment,
    }, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def append_evidence(db: Session, gate: ReviewGate, action: str,
                    actor: PlatformUser, comment: str | None = None,
                    payload: dict | None = None) -> ReviewEvidence:
    """追加一条评审留痕: curr_hash = SHA256(prev_hash + 动作字段), 链式防篡改。"""
    prev_hash = GENESIS_HASH
    last = (
        db.query(ReviewEvidence)
        .filter_by(gate_id=gate.id)
        .order_by(ReviewEvidence.id.desc())
        .first()
    )
    if last is not None:
        prev_hash = last.curr_hash
    timestamp = datetime.now()
    payload = payload or {}
    record = ReviewEvidence(
        gate_id=gate.id,
        actor_id=actor.id,
        action=action,
        timestamp=timestamp,
        comment=comment,
        payload=payload,
        prev_hash=prev_hash,
        curr_hash=_evidence_hash(
            prev_hash, gate.id, actor.id, action, timestamp, payload, comment),
    )
    db.add(record)
    return record


def verify_chain(db: Session, gate: ReviewGate) -> bool:
    """重放哈希链校验完整性: 任一记录字段被篡改即失败。"""
    prev_hash = GENESIS_HASH
    for ev in db.query(ReviewEvidence).filter_by(gate_id=gate.id).order_by(ReviewEvidence.id):
        expected = _evidence_hash(
            prev_hash, ev.gate_id, ev.actor_id, ev.action, ev.timestamp,
            ev.payload or {}, ev.comment)
        if ev.prev_hash != prev_hash or ev.curr_hash != expected:
            return False
        prev_hash = ev.curr_hash
    return True


# ── 门禁装载与流转 ────────────────────────────────────


def get_or_create_gate(db: Session, project: Project,
                       gate_type: str = "requirement") -> ReviewGate:
    gate = db.query(ReviewGate).filter_by(
        project_id=project.id, gate_type=gate_type).first()
    if gate is None:
        gate = ReviewGate(project_id=project.id, gate_type=gate_type)
        db.add(gate)
        db.flush()
    return gate


def _ensure_actor_can_review(gate: ReviewGate, actor: PlatformUser, step: str) -> None:
    """提交人/评审员/终审人三者不得为同一人(PM 不能自审)。"""
    if gate.submitter_id == actor.id:
        raise ReviewForbidden(f"提交人不能担任{step}")
    if step == "终审" and gate.reviewer_id == actor.id:
        raise ReviewForbidden("评审员不能同时担任终审人")


def submit_review(db: Session, project: Project, actor: PlatformUser,
                  gate_type: str = "requirement") -> tuple[ReviewGate, list[str]]:
    """提交评审: 硬校验 → blocked 契约; 通过则门禁进入 in_review 并做交付物快照。

    可提交状态: pending(首次)/rectifying(整改后)/rejected(否决后重开);
    in_review 重复提交 409(评审员正在看); passed 409(已通过, 重评请新建评估轮次)。
    """
    gate = get_or_create_gate(db, project, gate_type)
    if gate.status == "in_review":
        raise ReviewFlowError("评审正在进行中, 不能重复提交")
    if gate.status == "passed":
        raise ReviewFlowError("评审已通过, 如需重新评审请新建评估轮次")
    missing = collect_gate_missing(db, project)
    if missing:
        return gate, missing
    was_resubmit = gate.submitted_at is not None
    gate.status = "in_review"
    gate.submitted_at = datetime.now()
    gate.submitter_id = actor.id
    gate.reviewer_id = None
    gate.reviewer_conclusion = None
    gate.reviewer_opinion = None
    gate.version_hash = compute_version_hash(db, project)
    append_evidence(db, gate, "submit", actor,
                    payload={"version_hash": gate.version_hash,
                             "resubmit": was_resubmit})
    return gate, []


def annotate_requirement(db: Session, project: Project, gate: ReviewGate,
                         req: SecurityRequirement, actor: PlatformUser,
                         disposition: str, comment: str | None = None) -> None:
    """评审员逐条批注: approve(通过→reviewed)/return(退回→rectifying)/object(异议留痕)。"""
    if gate.status != "in_review":
        raise ReviewFlowError("评审未在进行中, 不能批注")
    _ensure_actor_can_review(gate, actor, "评审员")
    if disposition == "approve":
        transition_requirement(db, req, "review_pass", actor, opinion=comment)
    elif disposition == "return":
        transition_requirement(db, req, "request_change", actor, opinion=comment)
    elif disposition == "object":
        pass  # 异议不改需求状态, 仅留痕
    else:
        raise ReviewFlowError(f"未知批注意见: {disposition}")
    append_evidence(db, gate, "annotate", actor, comment=comment,
                    payload={"req_id": req.req_id, "disposition": disposition})


def decide_review(db: Session, project: Project, gate: ReviewGate,
                  actor: PlatformUser, conclusion: str,
                  comment: str | None = None) -> None:
    """评审员整体裁定: approve(待终审)/request_change(→rectifying)/reject(→rejected)。"""
    if gate.status != "in_review":
        raise ReviewFlowError("评审未在进行中, 不能裁定")
    _ensure_actor_can_review(gate, actor, "评审员")
    if conclusion not in ("approve", "reject", "request_change"):
        raise ReviewFlowError(f"未知裁定结论: {conclusion}")
    gate.reviewer_id = actor.id
    gate.reviewer_conclusion = conclusion
    gate.reviewer_opinion = comment
    gate.reviewed_at = datetime.now()
    if conclusion == "approve":
        pass  # 等待负责人终审, 状态保持 in_review
    elif conclusion == "request_change":
        gate.status = "rectifying"
    else:
        gate.status = "rejected"
    append_evidence(db, gate, conclusion, actor, comment=comment,
                    payload={"gate_status": gate.status})


def finalize_review(db: Session, project: Project, gate: ReviewGate,
                    actor: PlatformUser, comment: str | None = None) -> None:
    """终审会签: 仅评审员 approve 后可终审; 通过 → passed 并把已确认需求整体推为 reviewed。"""
    if gate.status != "in_review":
        raise ReviewFlowError("评审未在进行中, 不能终审")
    if gate.reviewer_conclusion != "approve":
        raise ReviewFlowError("评审员尚未通过, 不能终审(两步签核顺序不可跳过)")
    _ensure_actor_can_review(gate, actor, "终审")
    rectifying = (
        db.query(SecurityRequirement)
        .filter_by(project_id=project.id, review_status="rectifying")
        .count()
    )
    if rectifying:
        raise ReviewFlowError(f"仍有 {rectifying} 条需求处于整改中, 不能终审通过")
    gate.final_reviewer_id = actor.id
    gate.final_opinion = comment
    gate.final_reviewed_at = datetime.now()
    gate.status = "passed"
    append_evidence(db, gate, "sign", actor, comment=comment,
                    payload={"gate_status": "passed"})
    # 未被逐条批注通过的已确认需求, 随项目门禁通过整体推为 reviewed(终审事件)
    pending = (
        db.query(SecurityRequirement)
        .filter_by(project_id=project.id, review_status="confirmed")
        .all()
    )
    for req in pending:
        try:
            transition_requirement(db, req, "review_pass", actor,
                                   opinion="终审通过, 随项目门禁整体通过")
        except RequirementTransitionError:
            pass  # 单条异常不阻塞终审结论


def review_state(db: Session, project: Project, user: PlatformUser,
                 gate_type: str = "requirement") -> dict:
    """门禁状态 + 留痕时间线 + 需求状态汇总(评审工作台/时间线展示数据源)。"""
    gate = db.query(ReviewGate).filter_by(
        project_id=project.id, gate_type=gate_type).first()
    summary = {"open": 0, "confirmed": 0, "reviewed": 0, "rectifying": 0}
    for status, count in (
        db.query(SecurityRequirement.review_status, func.count())
        .filter(SecurityRequirement.project_id == project.id)
        .group_by(SecurityRequirement.review_status)
        .all()
    ):
        if status in summary:
            summary[status] = count
    result = {
        "gate": None,
        "evidences": [],
        "chain_valid": True,
        "requirement_summary": summary,
    }
    if gate is None:
        return result
    result["gate"] = {
        "gate_type": gate.gate_type,
        "status": gate.status,
        "status_verb": gate.latest_status_verb(),
        "submitted_at": gate.submitted_at.isoformat() if gate.submitted_at else None,
        "reviewed_at": gate.reviewed_at.isoformat() if gate.reviewed_at else None,
        "submitter_id": gate.submitter_id,
        "reviewer_id": gate.reviewer_id,
        "reviewer_conclusion": gate.reviewer_conclusion,
        "reviewer_opinion": gate.reviewer_opinion,
        "final_reviewer_id": gate.final_reviewer_id,
        "final_opinion": gate.final_opinion,
        "final_reviewed_at": (
            gate.final_reviewed_at.isoformat() if gate.final_reviewed_at else None),
        "version_hash": gate.version_hash,
    }
    result["evidences"] = [
        {
            "id": ev.id,
            "action": ev.action,
            "actor_id": ev.actor_id,
            "timestamp": ev.timestamp.isoformat(),
            "comment": ev.comment,
            "payload": ev.payload or {},
            "prev_hash": ev.prev_hash,
            "curr_hash": ev.curr_hash,
        }
        for ev in db.query(ReviewEvidence).filter_by(gate_id=gate.id)
        .order_by(ReviewEvidence.id).all()
    ]
    result["chain_valid"] = verify_chain(db, gate)
    return result


def accessible_gate_project(project: Project, user: PlatformUser) -> None:
    """评审端点共用: 复用全局项目数据权限口径(pm 仅本人项目)。"""
    ensure_project_access(user, project)
