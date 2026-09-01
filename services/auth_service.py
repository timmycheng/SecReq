# -*- coding: utf-8 -*-
"""平台用户与认证。

走查整改口径: 账号+密码登录, 角色精简为 开发(developer)/安全(security)。
- 密码仅存 pbkdf2_hmac 哈希(标准库实现, 无新增依赖);
- 种子账号初始密码优先取环境变量 SECREQ_SEED_PASSWORD, 未设置时每次启动随机生成并打印到日志,
  避免源码中出现固定凭据; 首次登录后可在右上角修改;
- ensure_seed_users 同时负责存量库的角色迁移(旧6角色 → 2角色, 幂等)。
"""
import hashlib
import logging
import os
import secrets

from sqlalchemy.orm import Session

import shared.constants as C
from models import PlatformUser

logger = logging.getLogger(__name__)

SEED_PASSWORD_ENV = "SECREQ_SEED_PASSWORD"


def _initial_seed_password() -> str:
    """初始密码: 环境变量优先; 未配置时进程内随机生成(仅影响本次新建/补设的账号)。"""
    from_env = os.environ.get(SEED_PASSWORD_ENV, "").strip()
    if from_env:
        return from_env
    generated = secrets.token_urlsafe(12)
    logger.warning(
        "未设置 %s, 本次启动的账号初始密码为随机值: %s (仅对本次新建或补设密码的账号生效, "
        "生产部署请通过环境变量固定)", SEED_PASSWORD_ENV, generated)
    return generated


SEED_DEFAULT_PASSWORD = _initial_seed_password()
_PBKDF2_ITERATIONS = 120_000

# 种子账号: 开发/安全各一名管理员, 账号语义清晰不残留演示痕迹(#63)
SEED_USERS = [
    {"username": "dev_admin", "display_name": "开发管理员", "employee_id": "E1001", "role": "developer"},
    {"username": "sec_admin", "display_name": "安全管理员", "employee_id": "E2001", "role": "security"},
]

# 存量库旧角色 → 新角色(不走映射的旧角色账号直接停用)
_LEGACY_ROLE_MAP = {
    "pm": "developer",
    "developer": "developer",
    "security_reviewer": "security",
    "security_lead": "security",
}

# 历史演示账号(旧版本种子创建): ensure_seed_users 幂等停用并转出其名下项目,
# 存量库一次性收敛为 dev_admin/sec_admin 口径(#63)
_LEGACY_DEMO_ACCOUNTS = ("dev_li", "dev_zhang", "sec_chen", "sec_zhao", "risk_liu", "audit_sun")


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
    - 历史演示账号(dev_li 等)一次性停用, 名下项目转归有效开发账号(#63)。
    """
    migrated = False
    legacy_to_reassign: list[int] = []
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
        if user.username in _LEGACY_DEMO_ACCOUNTS and user.active:
            user.active = False
            legacy_to_reassign.append(user.id)
            migrated = True
    existing = {u.username for u in session.query(PlatformUser).all()}
    for row in SEED_USERS:
        if row["username"] in existing:
            continue
        session.add(PlatformUser(**row, password_hash=hash_password(SEED_DEFAULT_PASSWORD)))
        migrated = True
    # 转项目必须在种子账号补齐之后: 否则 dev_admin 尚不存在, 停用账号名下项目找不到归属。
    # 显式 flush: 会话可能配置 autoflush=False, 不 flush 则停用状态与新账号对查询不可见
    session.flush()
    for uid in legacy_to_reassign:
        _reassign_owned_projects(session, uid)
    if migrated:
        session.commit()


def _reassign_owned_projects(session: Session, owner_user_id: int) -> None:
    """停用账号名下项目转归第一个有效开发账号(幂等; 无有效开发账号则保持原状)。

    启动链路上 ensure_seed_users 先于 assign_legacy_projects 执行, dev_admin
    此时已补齐, 正常总有归属目标; 保留无目标时不动数据的保守兜底。
    """
    from models import Project

    target = (
        session.query(PlatformUser)
        .filter(
            PlatformUser.role == "developer",
            PlatformUser.active.is_(True),
            PlatformUser.id != owner_user_id,
        )
        .order_by(PlatformUser.id)
        .first()
    )
    if target is None:
        return
    session.query(Project).filter(Project.owner_user_id == owner_user_id).update(
        {"owner_user_id": target.id}
    )


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
