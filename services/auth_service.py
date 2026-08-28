# -*- coding: utf-8 -*-
"""平台用户与认证(改造点5)。

MVP 口径: 无口令, 用户由种子数据维护; 请求经 X-Auth-User 头标识身份,
登录接口仅校验用户名存在并回显角色。RBAC 拦截规则见 routers/common.py。
"""
from sqlalchemy.orm import Session

import shared.constants as C
from models import PlatformUser

# 演示用户: 覆盖 6 类平台角色(工号同时用作电子签章要素)
SEED_USERS = [
    {"username": "pm_wang", "display_name": "王建国", "employee_id": "E1001", "role": "pm"},
    {"username": "dev_li", "display_name": "李开发", "employee_id": "E1002", "role": "developer"},
    {"username": "sec_chen", "display_name": "陈评审", "employee_id": "E2001", "role": "security_reviewer"},
    {"username": "sec_zhao", "display_name": "赵负责人", "employee_id": "E2002", "role": "security_lead"},
    {"username": "risk_liu", "display_name": "刘风险", "employee_id": "E3001", "role": "risk_manager"},
    {"username": "audit_sun", "display_name": "孙审计", "employee_id": "E4001", "role": "auditor"},
]


def ensure_seed_users(session: Session) -> None:
    """按用户名补齐种子用户(已存在的不覆盖), 幂等可重复执行。"""
    existing = {u.username for u in session.query(PlatformUser).all()}
    created = False
    for row in SEED_USERS:
        if row["username"] in existing:
            continue
        session.add(PlatformUser(**row))
        created = True
    if created:
        session.commit()


def get_user(session: Session, username: str | None) -> PlatformUser | None:
    if not username:
        return None
    return session.query(PlatformUser).filter_by(username=username, active=True).first()


def role_label(user: PlatformUser | None) -> str:
    return C.label(C.PLATFORM_ROLES, user.role) if user else "未登录"


def sign_text(user: PlatformUser) -> str:
    """电子签章代替方案: 姓名+工号+时间戳+哈希(由 ReviewEvidence.curr_hash 承担哈希)。"""
    from datetime import datetime

    return f"{user.display_name}({user.employee_id or '无工号'}) {datetime.now():%Y-%m-%d %H:%M:%S}"
