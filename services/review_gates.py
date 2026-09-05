# -*- coding: utf-8 -*-
"""门禁硬校验(#220 需求门禁 / #222 设计门禁): 提交评审时的 blocked 契约来源。

校验只发生在提交评审时, 填写过程永不阻断; 一次给出全部缺项(missing 列表)。
各 checker(db, project) -> list[str], 在 services/review_service.GATE_CHECKS 注册。
"""
from sqlalchemy.orm import Session

import shared.constants as C
from models import Project, SecurityRequirement

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


def requirement_gate_checks(db: Session, project: Project) -> list[str]:
    """需求门禁 4 条硬校验(#220): 数量/溯源/关键确认/报送确认。"""
    missing: list[str] = []
    reqs = _active_requirements(db, project)
    if not reqs:
        return ["安全需求清单为空: 至少需要生成 1 条安全需求才能提交评审"]

    # 1) 溯源约束: 每条需求必须可追溯到输入实体(source_entity_id 非空)
    for req in reqs:
        if not req.source_entity_id:
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
