# -*- coding: utf-8 -*-
"""系统台账服务: 定级备案/被评估系统 CRUD 与台账聚合。

"当前有效基线"动态计算 = 系统下最新一轮 status="generated" 的项目, 不做状态转移:
生成新轮次无需回写旧轮次, 且不存在多处状态不一致的问题。
"""
from datetime import datetime

from sqlalchemy.orm import Session

import shared.constants as C
from models import (
    Filing, GradingSurvey, Project, SecurityRequirement, System,
    SystemBaseline, SystemBaselineHistory,
)


class NameConflictError(Exception):
    """备案/系统名称或编码已被占用。"""


class InUseError(Exception):
    """仍被下级实体引用, 不允许删除。"""


def _check_filing_unique(db: Session, *, name: str, code: str | None,
                         exclude_id: int | None = None) -> None:
    query = db.query(Filing)
    if exclude_id:
        query = query.filter(Filing.id != exclude_id)
    if query.filter_by(name=name).first():
        raise NameConflictError(f"备案名称已存在: {name}")
    if code and query.filter_by(code=code).first():
        raise NameConflictError(f"备案编号已存在: {code}")


def _check_system_unique(db: Session, *, name: str, code: str | None,
                         exclude_id: int | None = None) -> None:
    query = db.query(System)
    if exclude_id:
        query = query.filter(System.id != exclude_id)
    if query.filter_by(name=name).first():
        raise NameConflictError(f"系统名称已存在: {name}")
    if code and query.filter_by(code=code).first():
        raise NameConflictError(f"系统编号已存在: {code}")


def ensure_filing_exists(db: Session, filing_id: int | None) -> None:
    if filing_id is not None and db.get(Filing, filing_id) is None:
        raise NameConflictError(f"备案不存在: id={filing_id}")


# ── 备案 ─────────────────────────────────────────────


def create_filing(db: Session, data: dict) -> Filing:
    _check_filing_unique(db, name=data["name"], code=data.get("code"))
    filing = Filing(**data)
    db.add(filing)
    db.commit()
    return filing


def update_filing(db: Session, filing: Filing, changes: dict) -> Filing:
    _check_filing_unique(db, exclude_id=filing.id,
                         name=changes.get("name", filing.name),
                         code=changes.get("code", filing.code))
    for key, value in changes.items():
        setattr(filing, key, value)
    db.commit()
    return filing


def delete_filing(db: Session, filing_id: int) -> None:
    if db.query(System).filter_by(filing_id=filing_id).count():
        raise InUseError("备案下仍挂有系统, 请先解除关联后再删除")
    db.query(Filing).filter_by(id=filing_id).delete()
    db.commit()


def list_filings(db: Session) -> list[Filing]:
    return db.query(Filing).order_by(Filing.id).all()


def filings_ledger(db: Session) -> list[dict]:
    """备案视角台账: 备案 × 下挂系统数 × 最新一轮评估概况。"""
    items = []
    for filing in list_filings(db):
        systems = db.query(System).filter_by(filing_id=filing.id).all()
        latest = None
        for system in systems:
            round_ = latest_round_of(db, system.id)
            if round_ and (latest is None or round_["created_at"] > latest["created_at"]):
                latest = round_
        items.append({
            "id": filing.id, "name": filing.name, "code": filing.code,
            "level": filing.level, "note": filing.note,
            "system_count": len(systems),
            "latest_round": latest,
        })
    return items


# ── 系统 ─────────────────────────────────────────────


def create_system(db: Session, data: dict, owner_user_id: int | None = None) -> System:
    ensure_filing_exists(db, data.get("filing_id"))
    _check_system_unique(db, name=data["name"], code=data.get("code"))
    system = System(**data, owner_user_id=owner_user_id)
    db.add(system)
    db.commit()
    return system


def update_system(db: Session, system: System, changes: dict) -> System:
    if "filing_id" in changes:
        ensure_filing_exists(db, changes["filing_id"])
    _check_system_unique(db, exclude_id=system.id,
                         name=changes.get("name", system.name),
                         code=changes.get("code", system.code))
    for key, value in changes.items():
        setattr(system, key, value)
    db.commit()
    return system


def delete_system(db: Session, system_id: int) -> None:
    if db.query(Project).filter_by(system_id=system_id).count():
        raise InUseError("系统下仍有关联项目, 请先处理项目归属后再删除")
    # 清单随系统一并清理(#194): 先删漏洞记录再删组件, 避免孤儿行
    from models import InfraArchImage, InfraAsset, SbomComponent, VulnerabilityRecord
    component_ids = db.query(SbomComponent.id).filter_by(system_id=system_id)
    db.query(VulnerabilityRecord).filter(
        VulnerabilityRecord.component_id.in_(component_ids)
    ).delete(synchronize_session=False)
    db.query(SbomComponent).filter_by(system_id=system_id).delete(synchronize_session=False)
    db.query(InfraAsset).filter_by(system_id=system_id).delete(synchronize_session=False)
    db.query(InfraArchImage).filter_by(system_id=system_id).delete(synchronize_session=False)
    db.query(System).filter_by(id=system_id).delete()
    db.commit()


def visible_systems_query(db: Session, user):
    """数据权限与项目一致: 开发仅见本人创建的系统, 安全全量。"""
    query = db.query(System)
    if user.role not in C.FULL_VISIBILITY_ROLES:
        query = query.filter(System.owner_user_id == user.id)
    return query.order_by(System.created_at.desc(), System.id.desc())


def latest_round_of(db: Session, system_id: int) -> dict | None:
    """系统下最新一轮已生成评估的概况(未生成过返回 None)。"""
    project = (
        db.query(Project)
        .filter_by(system_id=system_id, status="generated")
        .order_by(Project.created_at.desc(), Project.id.desc())
        .first()
    )
    if project is None:
        return None
    return round_summary(db, project)


def round_summary(db: Session, project: Project) -> dict:
    """评估时间线/台账用的单轮概况。"""
    survey = db.query(GradingSurvey).filter_by(project_id=project.id).first()
    total = db.query(SecurityRequirement).filter_by(project_id=project.id).count()
    open_total = db.query(SecurityRequirement).filter_by(
        project_id=project.id, status="open").count()
    return {
        "project_id": project.id,
        "project_name": project.name,
        "project_code": project.code,
        "status": project.status,
        "created_at": project.created_at.isoformat() if project.created_at else None,
        "grading_level": survey.effective_level() if survey else "",
        "requirements_total": total,
        "requirements_open": open_total,
    }


def current_baseline_id(db: Session, system_id: int) -> int | None:
    project = (
        db.query(Project.id)
        .filter_by(system_id=system_id, status="generated")
        .order_by(Project.created_at.desc(), Project.id.desc())
        .first()
    )
    return project[0] if project else None


def systems_ledger(db: Session, user) -> list[dict]:
    """系统视角台账: 系统 × 所属备案/定级 × 最新轮次结论 × 遗留未闭环数 × 当前基线。"""
    items = []
    for system in visible_systems_query(db, user).all():
        filing = db.get(Filing, system.filing_id) if system.filing_id else None
        latest = latest_round_of(db, system.id)
        items.append({
            "id": system.id,
            "name": system.name,
            "code": system.code,
            "owner_name": system.owner_name,
            "netbox_object_id": system.netbox_object_id,
            "filing_id": system.filing_id,
            "filing_name": filing.name if filing else None,
            "filing_level": filing.level if filing else None,
            "latest_round": latest,
            "current_baseline_project_id": current_baseline_id(db, system.id),
            "created_at": format_created_at(system.created_at),
        })
    return items


def baseline_summary(baseline: SystemBaseline | None) -> dict | None:
    """D 区基线概要计数(#223): 各基线分区的条目数。"""
    if baseline is None:
        return None
    data = baseline.baseline_json or {}
    assets = data.get("data_assets") or []
    return {
        "data_assets": len(assets),
        "data_tables": sum(len(a.get("tables") or []) for a in assets),
        "roles": len(data.get("roles") or []),
        "resources": len(data.get("resources") or []),
        "permission_entries": len(data.get("permission_entries") or []),
        "api_endpoints": len(data.get("api_endpoints") or []),
    }


def baseline_histories_of(db: Session, system_id: int) -> list[dict]:
    """基线变更履历(时间倒序): 谁/何时/依据哪次评审/变更摘要。"""
    rows = (
        db.query(SystemBaselineHistory)
        .filter_by(system_id=system_id)
        .order_by(SystemBaselineHistory.id.desc())
        .all()
    )
    return [
        {
            "id": h.id,
            "project_id": h.project_id,
            "gate_id": h.gate_id,
            "summary": h.summary,
            "operator_name": h.operator_name,
            "created_at": format_created_at(h.created_at),
        }
        for h in rows
    ]


def system_detail(db: Session, user, system: System) -> dict:
    """系统详情 + 评估时间线(轮次按创建倒序, 未生成的草稿轮也列出便于续填)。"""
    filing = db.get(Filing, system.filing_id) if system.filing_id else None
    query = db.query(Project).filter_by(system_id=system.id)
    if user.role not in C.FULL_VISIBILITY_ROLES:  # 数据权限与项目一致: 开发仅见本人项目
        query = query.filter(Project.owner_user_id == user.id)
    rounds = [
        round_summary(db, project)
        for project in query.order_by(Project.created_at.desc(), Project.id.desc()).all()
    ]
    return {
        "id": system.id,
        "name": system.name,
        "code": system.code,
        "owner_name": system.owner_name,
        "netbox_object_id": system.netbox_object_id,
        "user_scale": system.user_scale,
        "types": system.types or [],
        "is_public": bool(system.is_public),
        "filing_id": system.filing_id,
        "filing_name": filing.name if filing else None,
        "filing_level": filing.level if filing else None,
        "created_at": format_created_at(system.created_at),
        "current_baseline_project_id": current_baseline_id(db, system.id),
        "baseline": _baseline_out(db, system),
        "baseline_histories": baseline_histories_of(db, system.id),
        "rounds": rounds,
    }


def _baseline_out(db: Session, system: System) -> dict | None:
    baseline = db.query(SystemBaseline).filter_by(system_id=system.id).first()
    if baseline is None:
        return None
    from services.baseline_inheritance import baseline_uid_index
    return {
        "summary": baseline_summary(baseline),
        "source_project_id": baseline.source_project_id,
        "source_gate_id": baseline.source_gate_id,
        "summary_text": baseline.summary,
        "updated_by": baseline.updated_by,
        "updated_at": format_created_at(baseline.updated_at),
        "uid_index": baseline_uid_index(baseline),
        "pending_level_confirmation": baseline.pending_level_confirmation,
    }


def format_created_at(value: datetime | None) -> str | None:
    return value.isoformat() if value else None
