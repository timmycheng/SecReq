# -*- coding: utf-8 -*-
"""评审门禁服务(改造点4): 硬校验 + 交付物快照 + 链式哈希留痕 + 两步签核。

门禁硬校验在接口层强制: 不满足条件的提交直接 409 阻断并返回 missing 清单,
不允许"提示后仍可提交"。校验口径:

- 立项门禁: 定级问卷已提交且存在有效定级; 监管报送类需求已全部确认。
- 需求门禁: 已生成安全需求数 ≥ 1; 每条需求 source_entity_id 非空;
  无 critical 级需求未指定责任人。
- 设计门禁: SBOM 已生成; SoD 冲突 = 0 或已生成整改需求(SEC-V4-003);
  数据字典字段 100% 关联到 L1-L5 分级(每个资产都有合法分级)。
- POC/上线门禁: 本期仅保留数据结构, 不开放流程。
"""
import hashlib
import json
from datetime import datetime

from sqlalchemy.orm import Session

import shared.constants as C
from models import (
    GENESIS_HASH, GradingSurvey, PlatformUser, ReviewEvidence, ReviewGate,
    SbomComponent, SecurityRequirement,
)
from rules.context import RequirementContext

SOD_TEMPLATE_ID = "SEC-V4-003"


class GateActionError(Exception):
    """非法的门禁动作(状态机不允许/角色不允许), message 面向用户。"""

    def __init__(self, message: str, status_code: int = 409):
        super().__init__(message)
        self.status_code = status_code


# ────────────────────────── 硬校验 ──────────────────────────

def evaluate_gate(session: Session, project_id: int, gate_type: str) -> dict:
    """返回 {"status": "passed"|"blocked"|"not_available", "missing": [...]}。"""
    if gate_type not in C.GATE_ENABLED_TYPES:
        return {
            "status": "not_available",
            "missing": ["该门禁类型本期仅保留数据结构, 流程暂未启用"],
        }

    missing: list[str] = []

    if gate_type == "initiation":
        survey = session.query(GradingSurvey).filter_by(project_id=project_id).first()
        if survey is None or not survey.effective_level():
            missing.append("定级问卷尚未提交或缺少有效定级")
        unconfirmed = session.query(SecurityRequirement).filter_by(
            project_id=project_id, category="监管报送", reg_confirmed=False,
        ).all()
        for req in unconfirmed:
            missing.append(f"监管报送需求 {req.req_id}《{req.title}》尚未确认")

    elif gate_type == "requirement":
        requirements = session.query(SecurityRequirement).filter_by(project_id=project_id).all()
        if len(requirements) < 1:
            missing.append("尚未生成任何安全需求(请先执行『生成安全基线』)")
        for req in requirements:
            if req.source_entity_id is None:
                missing.append(f"需求 {req.req_id} 缺少来源实体(source_entity_id)")
            if req.priority == "critical" and not (req.owner or "").strip():
                missing.append(f"critical 需求 {req.req_id}《{req.title}》未指定责任人")

    elif gate_type == "design":
        has_sbom = session.query(SbomComponent).filter_by(project_id=project_id).count() > 0
        if not has_sbom:
            missing.append("SBOM 尚未生成(软件/框架清单为空)")
        sod_count = count_sod_conflicts(session, project_id)
        if sod_count > 0:
            rectified = session.query(SecurityRequirement).filter_by(
                project_id=project_id, template_id=SOD_TEMPLATE_ID,
            ).count() > 0
            if not rectified:
                missing.append(
                    f"权限矩阵存在 {sod_count} 处 SoD 冲突且未生成整改需求({SOD_TEMPLATE_ID})"
                )
        bad_assets = [
            a.name for a in _project_data_assets(session, project_id)
            if C.level_rank(a.classification) <= 0
        ]
        if bad_assets:
            missing.append(f"以下资产未关联 L1-L5 分级: {'、'.join(bad_assets)}")

    return {"status": "blocked" if missing else "passed", "missing": missing}


def count_sod_conflicts(session: Session, project_id: int) -> int:
    """与规则引擎同口径: 统计 high/critical 资源上的 SoD 互斥组合数(按角色×资源)。"""
    from models import PermissionEntry, Resource, Role

    entries = (
        session.query(PermissionEntry)
        .join(Role, PermissionEntry.role_id == Role.id)
        .filter(Role.project_id == project_id)
        .all()
    )
    resources = {r.id: r for r in session.query(Resource).filter_by(project_id=project_id)}
    pairs: set[tuple[int, int]] = set()
    for entry in entries:
        resource = resources.get(entry.resource_id)
        if resource is None or resource.criticality not in ("high", "critical"):
            continue
        actions = {
            e.action for e in entries
            if e.role_id == entry.role_id and e.resource_id == entry.resource_id
        }
        for left, right in C.SOD_CONFLICT_PAIRS:
            if left in actions and right in actions:
                pairs.add((entry.role_id, entry.resource_id))
    return len(pairs)


def _project_data_assets(session: Session, project_id: int):
    from models import DataAsset

    return session.query(DataAsset).filter_by(project_id=project_id).all()


# ────────────────────────── 交付物快照 ──────────────────────────

def compute_version_hash(session: Session, project_id: int) -> str:
    """提交时对全部交付物做 SHA256 快照(需求/问卷/资产/组件/接口/资产清单)。"""
    from models import ApiEndpoint, DataAsset, Feature, InfraAsset

    ctx = RequirementContext.from_db(session, project_id)
    snapshot = {
        "project": {
            "code": ctx.project.code, "type": ctx.project.type,
            "deploy_env": sorted(ctx.project.deploy_env or []),
            "compliance_targets": sorted(ctx.project.compliance_targets or []),
        },
        "grading": {
            "suggested": ctx.survey.suggested_level if ctx.survey else None,
            "final": ctx.survey.final_level if ctx.survey else None,
        },
        "features": sorted(f.name for f in ctx.features),
        "data_assets": sorted(
            f"{a.name}|{a.classification}|c3={bool(a.c3_tag)}|xb={bool(a.cross_border_transfer)}"
            for a in ctx.data_assets
        ),
        "components": sorted(f"{c.name}@{c.version}" for c in ctx.components),
        "api_endpoints": sorted(f"{e.method} {e.path}" for e in ctx.api_endpoints),
        "infra_assets": sorted(f"{a.name}@{a.env}" for a in ctx.infra_assets),
        "requirements": sorted(
            f"{r.req_id}|{r.title}|{r.priority}|{r.status}|{r.owner or ''}"
            for r in session.query(SecurityRequirement).filter_by(project_id=project_id)
        ),
    }
    payload = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ────────────────────────── 留痕哈希链 ──────────────────────────

def append_evidence(
    session: Session, gate: ReviewGate, actor: PlatformUser, action: str,
    ip: str | None = None, comment: str | None = None, payload: dict | None = None,
) -> ReviewEvidence:
    """向门禁追加一条动作留痕, 自动接续链式哈希。须在写入方同事务内调用。"""
    last = (
        session.query(ReviewEvidence)
        .filter_by(gate_id=gate.id)
        .order_by(ReviewEvidence.id.desc())
        .first()
    )
    prev_hash = last.curr_hash if last else GENESIS_HASH
    now = datetime.now()
    evidence = ReviewEvidence(
        gate_id=gate.id, actor_id=actor.id, action=action,
        timestamp=now, ip=ip, comment=comment, payload=payload or {},
        prev_hash=prev_hash, curr_hash="",
    )
    session.add(evidence)
    session.flush()  # 取得自增 id 与字段默认值后再计算哈希
    evidence.curr_hash = evidence_hash(evidence, prev_hash)
    session.flush()
    return evidence


def evidence_hash(evidence: ReviewEvidence, prev_hash: str) -> str:
    """curr_hash = SHA256(链上字段规范化拼接); 字段顺序固定保证可复算。"""
    material = "|".join([
        str(evidence.gate_id),
        prev_hash,
        str(evidence.actor_id),
        evidence.action or "",
        evidence.timestamp.isoformat(sep=" ") if evidence.timestamp else "",
        evidence.ip or "",
        evidence.comment or "",
        json.dumps(evidence.payload or {}, ensure_ascii=False, sort_keys=True),
        str(evidence.id),
    ])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def verify_chain(session: Session, gate_id: int) -> dict:
    """复算整条哈希链, 返回 {"valid": bool, "count": n, "broken_at": id|None}。"""
    rows = (
        session.query(ReviewEvidence)
        .filter_by(gate_id=gate_id)
        .order_by(ReviewEvidence.id)
        .all()
    )
    prev = GENESIS_HASH
    for row in rows:
        if row.prev_hash != prev or evidence_hash(row, row.prev_hash) != row.curr_hash:
            return {"valid": False, "count": len(rows), "broken_at": row.id}
        prev = row.curr_hash
    return {"valid": True, "count": len(rows), "broken_at": None}


# ────────────────────────── 状态机动作 ──────────────────────────

def get_or_create_gate(session: Session, project_id: int, gate_type: str) -> ReviewGate:
    gate = session.query(ReviewGate).filter_by(
        project_id=project_id, gate_type=gate_type,
    ).first()
    if gate is None:
        gate = ReviewGate(project_id=project_id, gate_type=gate_type, status="pending")
        session.add(gate)
        session.flush()
    return gate


def submit_gate(session: Session, project_id: int, gate_type: str, actor: PlatformUser,
                ip: str | None = None) -> ReviewGate:
    """提交评审: 先硬校验, 阻断则抛 GateActionError(409 + missing)。"""
    check = evaluate_gate(session, project_id, gate_type)
    if check["status"] == "not_available":
        raise GateActionError(f"{C.label(C.GATE_TYPES, gate_type)}: {check['missing'][0]}")
    if check["status"] == "blocked":
        raise GateActionError(
            f"门禁校验未通过, 禁止提交: {'; '.join(check['missing'])}",
        )
    gate = get_or_create_gate(session, project_id, gate_type)
    if gate.status == "passed":
        raise GateActionError("该门禁已通过, 无需重复提交")
    gate.status = "in_review"
    gate.submitted_at = datetime.now()
    gate.submitter_id = actor.id
    gate.reviewer_id = None
    gate.reviewer_conclusion = None
    gate.reviewer_opinion = None
    gate.final_reviewer_id = None
    gate.final_opinion = None
    gate.final_reviewed_at = None
    gate.version_hash = compute_version_hash(session, project_id)
    append_evidence(
        session, gate, actor, "submit", ip=ip,
        payload={"status": gate.status, "version_hash": gate.version_hash},
    )
    session.commit()
    return gate


def review_gate(session: Session, gate_id: int, actor: PlatformUser, action: str,
                opinion: str, ip: str | None = None) -> ReviewGate:
    """评审员第一步: approve(待终审) / request_change(整改) / reject(否决)。"""
    gate = session.get(ReviewGate, gate_id)
    if gate is None:
        raise GateActionError("门禁不存在", status_code=404)
    if gate.status != "in_review":
        raise GateActionError(f"门禁当前状态为「{C.label(C.GATE_STATUSES, gate.status)}」, 不能审核")
    if gate.submitter_id == actor.id:
        raise GateActionError("不能审核自己提交的门禁(回避要求)")
    if action == "approve":
        gate.reviewer_conclusion = "approve"
        gate.reviewer_id = actor.id
        gate.reviewer_opinion = opinion
        gate.reviewed_at = datetime.now()
    elif action in ("request_change", "reject"):
        gate.reviewer_conclusion = action
        gate.reviewer_id = actor.id
        gate.reviewer_opinion = opinion
        gate.reviewed_at = datetime.now()
        gate.status = "rectifying" if action == "request_change" else "rejected"
    else:
        raise GateActionError(f"评审员不支持的动作: {action}", status_code=400)
    append_evidence(
        session, gate, actor, action, ip=ip, comment=opinion,
        payload={"status": gate.status, "conclusion": gate.reviewer_conclusion},
    )
    session.commit()
    return gate


def finalize_gate(session: Session, gate_id: int, actor: PlatformUser, action: str,
                  opinion: str, ip: str | None = None) -> ReviewGate:
    """负责人终审: 必须先经评审员 approve; sign → passed / reject → rejected。"""
    gate = session.get(ReviewGate, gate_id)
    if gate is None:
        raise GateActionError("门禁不存在", status_code=404)
    if gate.status != "in_review" or gate.reviewer_conclusion != "approve":
        raise GateActionError("评审员尚未通过, 负责人不能终审(两步签核约束)")
    if gate.reviewer_id == actor.id:
        raise GateActionError("终审人不得与第一步评审人为同一人")
    if action == "sign":
        gate.status = "passed"
        gate.final_reviewer_id = actor.id
        gate.final_opinion = opinion
        gate.final_reviewed_at = datetime.now()
        verb = "sign"
    elif action == "reject":
        gate.status = "rejected"
        gate.final_reviewer_id = actor.id
        gate.final_opinion = opinion
        gate.final_reviewed_at = datetime.now()
        verb = "reject"
    else:
        raise GateActionError(f"终审不支持的动作: {action}", status_code=400)
    append_evidence(
        session, gate, actor, verb, ip=ip, comment=opinion,
        payload={"status": gate.status, "final": True},
    )
    session.commit()
    return gate
