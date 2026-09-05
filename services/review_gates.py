# -*- coding: utf-8 -*-
"""门禁硬校验(#220 需求门禁 / #222 设计门禁): 提交评审时的 blocked 契约来源。

校验只发生在提交评审时, 填写过程永不阻断; 一次给出全部缺项(missing 列表)。
各 checker(db, project) -> list[str], 在 services/review_service.GATE_CHECKS 注册。
"""
from sqlalchemy.orm import Session

import shared.constants as C
from models import (
    DataAsset,
    PermissionEntry,
    Project,
    Resource,
    Role,
    SbomComponent,
    SecurityRequirement,
)

# 监管报送类需求的中文名(需求行 category 存展示标签, 与列表筛选口径一致)
_REGULATORY_LABEL = C.label(C.TRIGGER_CATEGORY_LABELS, "regulatory_trigger")

# 视为"已确认"的生命周期状态
_CONFIRMED_STATUSES = ("confirmed", "reviewed")


def _active_requirements(db: Session, project: Project) -> list[SecurityRequirement]:
    """参与门禁的需求行: 排除输入已变更而标记 obsolete 的行。"""
    return (
        db.query(SecurityRequirement)
        .filter(SecurityRequirement.project_id == project.id,
                SecurityRequirement.status != "obsolete")
        .order_by(SecurityRequirement.req_id)
        .all()
    )


def design_gate_checks(db: Session, project: Project) -> list[str]:
    """设计门禁 4 项硬校验(#222): SBOM / SoD / 数据字典 / 漏填检测。"""
    from services.omission_check import run_omission_checks

    missing: list[str] = []

    # 1) SBOM 已生成(组件挂系统, #194)
    if project.system_id is None:
        missing.append("设计门禁: 评估未挂靠系统, 无法核对组件清单(SBOM)")
    else:
        comp_count = (
            db.query(SbomComponent).filter_by(system_id=project.system_id).count())
        if comp_count == 0:
            missing.append("设计门禁: SBOM 未生成, 请先在系统台账维护组件清单")

    # 2) SoD 冲突 = 0 或已生成整改需求(互斥对判定与规则引擎算法2一致)
    conflicts = _sod_conflicts(db, project)
    if conflicts and not _sod_requirement_generated(db, project, conflicts):
        role_names = "、".join(sorted({role_name for role_name, _ in conflicts}))
        missing.append(
            f"设计门禁: 存在未整改的 SoD 冲突(角色: {role_names}), "
            "请先重新生成安全需求以产出整改项")

    # 3) 涉及 C2/C3(3级及以上)的资产已建数据字典表
    from services.omission_check import C3_PLUS_LEVELS  # noqa: PLC0415
    assets = _project_assets(db, project)
    for asset in assets:
        if asset.classification in C3_PLUS_LEVELS and not (asset.tables or []):
            missing.append(
                f"设计门禁: 资产「{asset.name}」({asset.classification})尚未建立数据字典表")

    # 4) 漏填检测通过(#221)
    missing.extend(run_omission_checks(db, project))
    return missing


def _project_assets(db: Session, project: Project):
    return db.query(DataAsset).filter_by(project_id=project.id).all()


def _sod_conflicts(db: Session, project: Project) -> list[tuple[str, str]]:
    """当前权限矩阵的 SoD 冲突: [(角色名, 资源名)], 判定口径同 rules/engine 算法2。"""
    roles = db.query(Role).filter_by(project_id=project.id).all()
    resources = {
        r.id: r for r in db.query(Resource).filter_by(project_id=project.id).all()
    }
    entries = (
        db.query(PermissionEntry)
        .join(Role, PermissionEntry.role_id == Role.id)
        .filter(Role.project_id == project.id)
        .all()
    )
    actions: dict[tuple[int, int], set[str]] = {}
    for e in entries:
        actions.setdefault((e.role_id, e.resource_id), set()).add(e.action)
    conflicts: list[tuple[str, str]] = []
    for role in roles:
        for resource_id, resource in resources.items():
            if resource.criticality not in ("high", "critical"):
                continue
            acts = actions.get((role.id, resource_id), set())
            for left, right in C.SOD_CONFLICT_PAIRS:
                if left in acts and right in acts:
                    conflicts.append((role.name, resource.name))
                    break
    return conflicts


def _sod_requirement_generated(db: Session, project: Project,
                               conflicts: list[tuple[str, str]]) -> bool:
    """命中冲突的角色是否已有对应的 SoD 整改需求(未过期的)。"""
    conflict_role_names = {name for name, _ in conflicts}
    uids = {
        row[0] for row in (
            db.query(Role.uid)
            .filter(Role.project_id == project.id,
                    Role.name.in_(conflict_role_names))
            .all()
        )
        if row[0]
    }
    if not uids:
        return False
    return (
        db.query(SecurityRequirement)
        .filter(
            SecurityRequirement.project_id == project.id,
            SecurityRequirement.source_entity_type == "role",
            SecurityRequirement.source_entity_uid.in_(uids),
            SecurityRequirement.status != "obsolete",
        )
        .count() > 0
    )


def requirement_gate_checks(db: Session, project: Project) -> list[str]:
    """需求门禁 4 条硬校验(#220): 数量/溯源/关键确认/报送确认。"""
    missing: list[str] = []
    reqs = _active_requirements(db, project)
    if not reqs:
        return ["安全需求清单为空: 至少需要生成 1 条安全需求才能提交评审"]

    # 1) 溯源约束: 每条需求必须可追溯到输入实体 —— uid 为权威口径(#66);
    #    source_entity_id=0 是 permission_entry 复合键的设计内取值, 不算缺失
    for req in reqs:
        if not req.source_entity_uid and not req.source_entity_id:
            missing.append(
                f"需求 {req.req_id}「{req.title}」缺少来源实体, 无法追溯")

    # 2) critical 需求必须已确认(高风险项不允许带未确认状态上会)
    for req in reqs:
        if req.priority == "critical" and req.review_status not in _CONFIRMED_STATUSES:
            missing.append(
                f"critical 需求 {req.req_id}「{req.title}」尚未确认")

    # 3) 监管报送类需求必须全部确认
    for req in reqs:
        if req.category == _REGULATORY_LABEL and req.review_status not in _CONFIRMED_STATUSES:
            missing.append(
                f"监管报送类需求 {req.req_id}「{req.title}」尚未确认")

    return missing
