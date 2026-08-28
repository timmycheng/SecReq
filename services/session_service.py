# -*- coding: utf-8 -*-
"""登录会话服务: token 签发/校验/吊销 + 简单的登录失败锁定。

- token 为 secrets.token_urlsafe 随机串, 库内只存 sha256 指纹;
- 会话有效期 SESSION_TTL_HOURS, 过期即视为未登录;
- 登录失败锁定为进程内计数(重启即清零), 达到阈值后要求等待 LOCKOUT_SECONDS。
"""
import hashlib
import secrets
from datetime import datetime, timedelta
from threading import Lock

from sqlalchemy.orm import Session

from models import PlatformUser, UserSession

SESSION_TTL_HOURS = 12
LOCKOUT_THRESHOLD = 5
LOCKOUT_SECONDS = 300

_failed: dict[str, list[float]] = {}
_failed_lock = Lock()


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(db: Session, user: PlatformUser, ip: str | None = None) -> str:
    token = secrets.token_urlsafe(32)
    db.add(UserSession(
        token_hash=_token_hash(token),
        username=user.username,
        expires_at=datetime.now() + timedelta(hours=SESSION_TTL_HOURS),
        ip=ip,
    ))
    db.commit()
    return token


def resolve_session(db: Session, token: str | None) -> PlatformUser | None:
    """token → 当前用户; 无效/过期/用户停用返回 None。顺带清理本人过期会话。"""
    if not token:
        return None
    row = db.query(UserSession).filter_by(token_hash=_token_hash(token)).first()
    if row is None:
        return None
    if row.expires_at < datetime.now():
        db.delete(row)
        db.commit()
        return None
    return db.query(PlatformUser).filter_by(username=row.username, active=True).first()


def revoke_session(db: Session, token: str | None) -> None:
    if not token:
        return
    db.query(UserSession).filter_by(token_hash=_token_hash(token)).delete()
    db.commit()


def revoke_user_sessions(db: Session, username: str) -> None:
    """改密/停用时吊销该用户全部会话。"""
    db.query(UserSession).filter_by(username=username).delete()
    db.commit()


# ── 登录失败锁定(进程内) ──────────────────────────────
def _prune_failed(now: float) -> None:
    cutoff = now - LOCKOUT_SECONDS
    for key in [k for k, stamps in _failed.items() if not stamps or stamps[-1] < cutoff]:
        _failed.pop(key, None)


def login_locked(username: str) -> bool:
    """该账号当前是否处于锁定窗口。"""
    now = datetime.now().timestamp()
    with _failed_lock:
        _prune_failed(now)
        stamps = _failed.get(username, [])
        return len(stamps) >= LOCKOUT_THRESHOLD and now - stamps[-1] < LOCKOUT_SECONDS


def record_login_failure(username: str) -> None:
    now = datetime.now().timestamp()
    with _failed_lock:
        _prune_failed(now)
        _failed.setdefault(username, []).append(now)


def clear_login_failures(username: str) -> None:
    with _failed_lock:
        _failed.pop(username, None)
