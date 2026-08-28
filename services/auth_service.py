# -*- coding: utf-8 -*-
"""平台用户与认证。

走查整改口径: 账号+密码登录, 角色精简为 开发(developer)/安全(security)。
- 密码仅存 pbkdf2_hmac 哈希(标准库实现, 无新增依赖);
- 种子账号默认密码 SEED_DEFAULT_PASSWORD, 首次登录后可在右上角修改;
- ensure_seed_users 同时负责存量库的角色迁移(旧6角色 → 2角色, 幂等)。
"""
import hashlib
import secrets

from sqlalchemy.orm import Session

import shared.constants as C
from models import PlatformUser

SEED_DEFAULT_PASSWORD = "Sec123456"
_PBKDF2_ITERATIONS = 120_000

# 演示用户: 开发 2 人(项目创建/填报), 安全 2 人(全量可见)
SEED_USERS = [
    {"username": "dev_li", "display_name": "李开发", "employee_id": "E1002", "role": "developer"},
    {"username": "dev_zhang", "display_name": "张开发", "employee_id": "E1003", "role": "developer"},
    {"username": "sec_chen", "display_name": "陈安全", "employee_id": "E2001", "role": "security"},
    {"username": "sec_zhao", "display_name": "赵安全", "employee_id": "E2002", "role": "security"},
]

# 存量库旧角色 → 新角色(不走映射的旧角色账号直接停用)
_LEGACY_ROLE_MAP = {
    "pm": "developer",
    "developer": "developer",
    "security_reviewer": "security",
    "security_lead": "security",
}


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("ascii"), _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        algorithm, iterations, salt, expected = stored.split("$")
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("ascii"), int(iterations))
    return secrets.compare_digest(digest.hex(), expected)


def ensure_seed_users(session: Session) -> None:
    """种子用户补齐 + 存量数据迁移, 幂等可重复执行。

    - 缺失的种子用户按默认密码创建;
    - 存量用户 password_hash 为空(旧无口令库)时补设默认密码;
    - 旧角色按映射表迁移, 无法映射的(风管/审计)停用账号;
    - 已停用的旧演示账号(risk_liu/audit_sun)保持停用。
    """
    migrated = False
    for user in session.query(PlatformUser).all():
        if user.role not in C.PLATFORM_ROLES:
            new_role = _LEGACY_ROLE_MAP.get(user.role)
            if new_role:
                user.role = new_role
            else:
                user.active = False
            migrated = True
        if not user.password_hash:
            user.password_hash = hash_password(SEED_DEFAULT_PASSWORD)
            migrated = True
    existing = {u.username for u in session.query(PlatformUser).all()}
    for row in SEED_USERS:
        if row["username"] in existing:
            continue
        session.add(PlatformUser(**row, password_hash=hash_password(SEED_DEFAULT_PASSWORD)))
        migrated = True
    if migrated:
        session.commit()


def get_user(session: Session, username: str | None) -> PlatformUser | None:
    if not username:
        return None
    return session.query(PlatformUser).filter_by(username=username, active=True).first()


def role_label(user: PlatformUser | None) -> str:
    return C.label(C.PLATFORM_ROLES, user.role) if user else "未登录"


def sign_text(user: PlatformUser) -> str:
    """电子签章代替方案: 姓名+工号+时间戳+哈希(由需求确认记录承担哈希)。"""
    from datetime import datetime

    return f"{user.display_name}({user.employee_id or '无工号'}) {datetime.now():%Y-%m-%d %H:%M:%S}"
