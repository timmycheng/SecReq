# -*- coding: utf-8 -*-
"""需求评审生命周期(#217, #310 属实性确认): 需求条目级状态机与流转留痕。

与任务型 status(开卷开发进度)分离; 项目级整体评审见 models/review.py 的 ReviewGate。
状态机(open → confirmed/invalid → reviewed; 退回 rectifying → 重新确认)在
shared.constants.REQUIREMENT_REVIEW_TRANSITIONS 集中声明, 本层只执行与留痕。
#310: 开发侧确认语义为「属实性确认」—— 属实确认(confirmed) / 不属实标记(invalid,
必填原因, 保留记录不删除); 评审全部通过后仅 confirmed 落盘为 reviewed。
"""
from datetime import datetime

from sqlalchemy.orm import Session

import shared.constants as C
from models import PlatformUser, RequirementTransition, SecurityRequirement


class RequirementTransitionError(ValueError):
    """非法生命周期流转(路由层转 409)。"""


def can_transition(req: SecurityRequirement, action: str) -> bool:
    """流转合法性预检(批量场景先筛后改, 避免中途 rollback 误伤已改行)。"""
    if action not in C.REQUIREMENT_TRANSITION_ACTIONS:
        return False
    target = C.REQUIREMENT_TRANSITION_ACTIONS[action][0]
    if req.review_status == "confirmed" and target == "confirmed":
        return True  # 幂等确认
    return target in C.REQUIREMENT_REVIEW_TRANSITIONS.get(req.review_status, [])


def transition_requirement(
    db: Session, req: SecurityRequirement, action: str,
    operator: PlatformUser, opinion: str | None = None,
) -> RequirementTransition | None:
    """执行一次生命周期流转: 校验合法性 → 改状态 → 写流转记录。

    - confirm 对已确认需求幂等(仅刷新确认人/时间, 不重复留痕), 返回 None;
    - mark_invalid 必须携带不属实原因(opinion), 落 invalid_reason 字段;
      恢复确认(invalid → confirmed)时清空 invalid_reason(原因留痕在流转记录);
    - 非法跳转(如 open 直接到 reviewed、reviewed 终态再流转)抛 RequirementTransitionError;
    - 不在此处 commit, 由调用方决定事务边界。
    """
    if action not in C.REQUIREMENT_TRANSITION_ACTIONS:
        raise RequirementTransitionError(f"未知流转动作: {action}")
    target = C.REQUIREMENT_TRANSITION_ACTIONS[action][0]
    allowed = C.REQUIREMENT_REVIEW_TRANSITIONS.get(req.review_status, [])
    if req.review_status == "confirmed" and target == "confirmed":
        # 重复确认幂等: 刷新确认口径, 不产生新流转记录
        req.reg_confirmed = True
        req.confirmed_by = operator.display_name
        req.confirmed_at = datetime.now()
        return None
    if action == "mark_invalid" and not (opinion or "").strip():
        raise RequirementTransitionError("标记不属实必须填写原因")
    if target not in allowed:
        raise RequirementTransitionError(
            f"需求 {req.req_id} 当前状态「{C.label(C.REQUIREMENT_REVIEW_STATUSES, req.review_status)}」"
            f"不允许执行「{C.label(C.REQUIREMENT_TRANSITION_ACTIONS, action, action)}」")
    record = RequirementTransition(
        requirement_id=req.id,
        action=action,
        from_status=req.review_status,
        to_status=target,
        operator_id=operator.id,
        operator_name=operator.display_name,
        opinion=opinion,
    )
    db.add(record)
    req.review_status = target
    if target == "confirmed":
        req.reg_confirmed = True
        req.confirmed_by = operator.display_name
        req.confirmed_at = datetime.now()
        if req.invalid_reason:
            req.invalid_reason = None  # 恢复确认: 行上原因清空, 历史留痕在流转记录
    if target == "invalid":
        req.invalid_reason = opinion
        req.reg_confirmed = False
        req.confirmed_by = None  # #328: 标记不属实即撤回确认, 确认人/时间不再残留
        req.confirmed_at = None
    return record


def backfill_review_statuses(db: Session) -> int:
    """存量需求行 review_status 回填(#217), 幂等(仅处理 NULL 行)。

    映射规则: 已确认(reg_confirmed)或任务已推进(in_progress/done/risk_accepted)
    的存量行 → confirmed; 其余 → open。语义不破坏: PM 已确认过的需求在升级后
    仍处于已确认态, 可直接进入评审。
    """
    rows = (
        db.query(SecurityRequirement)
        .filter(SecurityRequirement.review_status.is_(None))
        .all()
    )
    migrated = {"confirmed": 0, "open": 0}
    for req in rows:
        if req.reg_confirmed or req.status in ("in_progress", "done", "risk_accepted"):
            req.review_status = "confirmed"
            migrated["confirmed"] += 1
        else:
            req.review_status = "open"
            migrated["open"] += 1
    return sum(migrated.values())
