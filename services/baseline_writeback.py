# -*- coding: utf-8 -*-
"""评审通过触发基线写回(#225): 本轮评估快照写回系统安全基线(D 区)。

只有评审通过的快照才能写回系统基线 —— 评审流程就是资产数据的质检器:
终审(ReviewGate passed)事件 → 快照 资产/字典/权限矩阵/API 清单 落 system_baselines,
并追加基线变更履历; 评估建议级与系统备案级不一致时挂「级别变更确认」待办,
由安全侧人工定夺(采纳评估级覆盖备案, 或维持备案级留痕), 两条路径都留痕。

写回失败不阻塞评审结论: 异常吞掉并记审计告警, 由调用方(评审动作流)保证事务边界。
"""
import logging
from datetime import datetime

from sqlalchemy.orm import Session

from models import (
    ApiEndpoint, DataAsset, Filing, GradingSurvey, PermissionEntry, Project,
    Resource, Role, System, SystemBaseline, SystemBaselineHistory,
)

logger = logging.getLogger(__name__)


def _baseline_json_of(db: Session, project: Project) -> dict:
    """从项目轮次收集 D 区快照: 形态与 services.baseline_inheritance 预填约定一致。"""
    assets = (
        db.query(DataAsset).filter_by(project_id=project.id).order_by(DataAsset.id).all()
    )
    data_assets = [
        {
            "uid": a.uid,
            "name": a.name,
            "data_type": a.data_type,
            "classification": a.classification,
            "legacy_classification": a.legacy_classification,
            "c3_tag": bool(a.c3_tag),
            "is_pii": bool(a.is_pii),
            "is_sensitive_pii": bool(a.is_sensitive_pii),
            "storage_envs": a.storage_envs or [],
            "cross_border_transfer": bool(a.cross_border_transfer),
            "tables": [
                {
                    "table_name": t.table_name,
                    "fields": [
                        {
                            "field_name": f.field_name,
                            "field_type": f.field_type,
                            "need_encrypt": bool(f.need_encrypt),
                            "need_mask": bool(f.need_mask),
                            "mask_rule": f.mask_rule,
                        }
                        for f in (t.fields or [])
                    ],
                }
                for t in (a.tables or [])
            ],
        }
        for a in assets
    ]

    roles = [
        {"uid": r.uid, "name": r.name, "role_type": r.role_type or "",
         "user_count_estimate": r.user_count_estimate}
        for r in db.query(Role).filter_by(project_id=project.id).order_by(Role.id).all()
    ]
    resources = [
        {"uid": r.uid, "name": r.name, "resource_type": r.resource_type or "",
         "criticality": r.criticality or ""}
        for r in db.query(Resource).filter_by(project_id=project.id).order_by(Resource.id).all()
    ]
    entries = (
        db.query(PermissionEntry)
        .join(Role, PermissionEntry.role_id == Role.id)
        .filter(Role.project_id == project.id)
        .order_by(PermissionEntry.id).all()
    )
    role_uid = {r.id: r.uid for r in db.query(Role).filter_by(project_id=project.id)}
    resource_uid = {r.id: r.uid for r in db.query(Resource).filter_by(project_id=project.id)}
    permission_entries = [
        {
            "role_uid": role_uid.get(e.role_id),
            "resource_uid": resource_uid.get(e.resource_id),
            "action": e.action,
            "requires_approval": bool(e.requires_approval),
        }
        for e in entries
    ]
    api_endpoints = [
        {
            "uid": ep.uid, "name": ep.name, "path": ep.path, "method": ep.method,
            "auth_required": bool(ep.auth_required), "public_exposed": bool(ep.public_exposed),
            "sensitive_asset_uids": ep.sensitive_asset_uids or [],
            "rate_limit": ep.rate_limit,
        }
        for ep in db.query(ApiEndpoint).filter_by(project_id=project.id).order_by(ApiEndpoint.id).all()
    ]
    return {
        "data_assets": data_assets,
        "roles": roles,
        "resources": resources,
        "permission_entries": permission_entries,
        "api_endpoints": api_endpoints,
    }


def _summary_counts(data: dict) -> str:
    return (f"资产 {len(data.get('data_assets') or [])}/"
            f"角色 {len(data.get('roles') or [])}/"
            f"资源 {len(data.get('resources') or [])}/"
            f"授权 {len(data.get('permission_entries') or [])}/"
            f"接口 {len(data.get('api_endpoints') or [])}")


def writeback_baseline(db: Session, project: Project, gate, actor) -> SystemBaseline | None:
    """终审通过后的基线写回: 快照落库 + 履历留痕 + 级别双轨待办。

    调用方(终审动作)在独立事务中调用本函数并自行 commit; 返回 None 表示
    写回失败(已记审计告警), 评审结论不受影响。
    """
    try:
        system = db.get(System, project.system_id) if project.system_id else None
        if system is None:
            raise ValueError(f"评估未挂靠系统, 无法写回基线: project={project.id}")

        data = _baseline_json_of(db, project)
        baseline = db.query(SystemBaseline).filter_by(system_id=system.id).first()
        if baseline is None:
            baseline = SystemBaseline(system_id=system.id)
            db.add(baseline)
            db.flush()
        baseline.baseline_json = data
        baseline.source_project_id = project.id
        baseline.source_gate_id = gate.id
        baseline.summary = _summary_counts(data)
        baseline.updated_by = actor.display_name
        baseline.updated_at = datetime.now()

        # 等保级别双轨(#225 定夺): 不一致 → 挂「级别变更确认」待办, 安全侧人工定夺
        filing = db.get(Filing, system.filing_id) if system.filing_id else None
        filing_level = filing.level if filing else None
        survey = db.query(GradingSurvey).filter_by(project_id=project.id).first()
        suggested = survey.effective_level() if survey else ""
        if filing_level and suggested and filing_level != suggested:
            baseline.pending_level_confirmation = {
                "suggested_level": suggested,
                "filing_level": filing_level,
                "project_id": project.id,
            }
        else:
            baseline.pending_level_confirmation = None

        db.add(SystemBaselineHistory(
            system_id=system.id,
            baseline_id=baseline.id,
            project_id=project.id,
            gate_id=gate.id,
            summary=f"终审通过写回基线: {baseline.summary}"
                    + (f"; 级别待确认(备案 {filing_level}/评估 {suggested})"
                       if baseline.pending_level_confirmation else ""),
            operator_id=actor.id,
            operator_name=actor.display_name,
        ))
        db.commit()
        return baseline
    except Exception as exc:  # noqa: BLE001 — 写回失败不阻塞评审结论
        db.rollback()
        logger.error("基线写回失败(project=%s): %s", project.id, exc)
        from services.audit_service import audit
        audit(db, actor.username, "baseline_writeback_failed",
              {"project_id": project.id, "error": str(exc)[:300]})
        db.commit()
        return None
