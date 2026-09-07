# -*- coding: utf-8 -*-
"""LDAP/AD 对接(#280): 统一身份认证 + 目录用户导入。

配置存 system_settings(key=ldap), 口径与 LLM/NetBox 配置一致:
- 密码只写不读: GET 下发 has_password 标志, PUT 时留空表示沿用已存密码;
- 登录流程本地优先: 本地账密校验失败且 LDAP 启用时, 按 filter 搜索用户 DN 后
  以该用户凭据 bind 验证; 通过则自动开通同名本地账号(默认 pm 角色);
- allow_local_fallback 控制「LDAP 启用后本地账号是否还可登录」:
  False 时本地账号校验失败不再回落本地(防绕过), True 时两者都试。

ldap3 为可选运行时依赖: 未安装时认证/测试明确报错, 不静默当登录失败。
"""
import logging
import time
from typing import Any

from sqlalchemy.orm import Session

from models import PlatformUser
from services.auth_service import hash_password
from services.settings_service import get_setting, set_setting

logger = logging.getLogger(__name__)

LDAP_KEY = "ldap"

#: 字段缺省值(逐项合并, 老库零影响)
LDAP_DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "host": "",
    "port": 389,
    "use_ssl": False,
    "base_dn": "",
    "bind_dn": "",
    "bind_password": "",
    "user_filter": "(objectClass=person)",
    "attr_username": "uid",
    "attr_display_name": "cn",
    "attr_email": "mail",
    "allow_local_fallback": True,
}

#: 数值字段白名单(防脏数据落库)
_INT_FIELDS = ("port",)


def get_ldap_config(session: Session) -> dict:
    """合并默认值后的完整配置; bind_password 不外发, 以 has_password 代替。"""
    stored = get_setting(session, LDAP_KEY)
    cfg = {**LDAP_DEFAULTS}
    for key in LDAP_DEFAULTS:
        if key in stored and stored[key] is not None:
            cfg[key] = stored[key]
    for key in _INT_FIELDS:
        try:
            cfg[key] = int(cfg[key])
        except (TypeError, ValueError):
            cfg[key] = LDAP_DEFAULTS[key]
    cfg["has_password"] = bool(cfg.pop("bind_password"))
    return cfg


def save_ldap_config(session: Session, payload: dict) -> dict:
    """保存配置; bind_password 为空字符串/缺失时沿用已存密码。"""
    stored = get_setting(session, LDAP_KEY)
    merged: dict[str, Any] = {**LDAP_DEFAULTS, **stored}
    for key in LDAP_DEFAULTS:
        if key not in payload or key == "bind_password":
            continue
        value = payload[key]
        if key in _INT_FIELDS:
            try:
                value = int(value)
            except (TypeError, ValueError):
                raise ValueError(f"{key} 必须是整数") from None
        merged[key] = value
    password = payload.get("bind_password")
    if password:
        merged["bind_password"] = password
    elif "bind_password" not in payload and stored.get("bind_password"):
        merged["bind_password"] = stored["bind_password"]
    return set_setting(session, LDAP_KEY, merged)


def _runtime_config(session: Session, override: dict | None = None) -> dict | None:
    """内部用完整配置(含密码); override 里的空密码回退已存值。未启用返回 None。"""
    stored = get_setting(session, LDAP_KEY)
    cfg = get_ldap_config(session)
    cfg["bind_password"] = stored.get("bind_password") or ""
    if override:
        for key, value in override.items():
            if value not in (None, "") or key != "bind_password":
                cfg[key] = value
            else:
                cfg[key] = cfg.get(key) or ""
    if not (cfg["enabled"] and cfg["host"] and cfg["base_dn"]):
        return None
    return cfg


def _require_ldap3():
    try:
        import ldap3
        from ldap3 import ALL, SUBTREE
        from ldap3.utils.conv import escape_filter_chars
    except ImportError as exc:  # pragma: no cover - 依赖声明后常规环境都有
        raise RuntimeError("ldap3 依赖未安装, 无法对接 LDAP/AD") from exc
    return ldap3, ALL, SUBTREE, escape_filter_chars


def _connect(cfg: dict, bind_dn: str | None = None, bind_password: str | None = None):
    """建立连接: bind_dn 为 None 时匿名/服务账号按配置决定。"""
    ldap3, ALL, _, _ = _require_ldap3()
    server = ldap3.Server(
        cfg["host"], port=int(cfg["port"]), use_ssl=bool(cfg.get("use_ssl")),
        get_info=ALL, connect_timeout=5)
    return ldap3.Connection(
        server, user=bind_dn, password=bind_password, auto_bind=True,
        receive_timeout=10)


def test_connection(session: Session, override: dict | None = None) -> dict:
    """连通性测试: 服务账号 bind + 按 filter 探测用户数; 只测不存。"""
    cfg = _runtime_config(session, override)
    if cfg is None:
        return {"ok": False, "reason": "LDAP 未启用或服务器地址/Base DN 未配置"}
    started = time.perf_counter()
    try:
        conn = _connect(cfg, cfg["bind_dn"] or None, cfg["bind_password"] or None)
    except Exception as exc:
        logger.warning("LDAP 连接测试失败: %s", exc)
        return {"ok": False, "reason": f"连接失败: {exc}"}
    try:
        _, _, SUBTREE, _ = _require_ldap3()
        username_attr = cfg["attr_username"] or "uid"
        ok = conn.search(
            search_base=cfg["base_dn"],
            search_filter=f"(&{cfg['user_filter']}({username_attr}=*))",
            search_scope=SUBTREE, attributes=[username_attr], size_limit=1000)
        latency = round((time.perf_counter() - started) * 1000)
        if not ok:
            return {"ok": False, "reason": f"目录搜索失败: {conn.result.get('description', '')}"}
        return {"ok": True, "latency_ms": latency, "user_count": len(conn.entries)}
    finally:
        conn.unbind()


def _search_user(conn, cfg: dict, username: str) -> dict | None:
    """按 user_filter + 用户名属性定位目录用户, 返回属性字典。"""
    _, _, SUBTREE, escape_filter_chars = _require_ldap3()
    username_attr = cfg["attr_username"] or "uid"
    safe = escape_filter_chars(username)
    if not conn.search(
            search_base=cfg["base_dn"],
            search_filter=f"(&{cfg['user_filter']}({username_attr}={safe}))",
            search_scope=SUBTREE,
            attributes=[username_attr, cfg["attr_display_name"], cfg["attr_email"]]):
        return None
    if len(conn.entries) != 1:
        return None
    entry = conn.entries[0]

    def attr(name: str) -> str:
        value = entry[name].value if name in entry else None
        return str(value) if value else ""

    return {
        "dn": entry.entry_dn,
        "username": attr(username_attr) or username,
        "display_name": attr(cfg["attr_display_name"]) or username,
        "email": attr(cfg["attr_email"]),
    }


def authenticate(session: Session, username: str, password: str) -> PlatformUser | None:
    """LDAP 认证: 搜索用户 DN → 以用户凭据 bind → 自动开通/复用本地账号。

    仅当配置启用时尝试; 任何 LDAP 侧失败返回 None(调用方继续本地逻辑或报错)。
    """
    cfg = _runtime_config(session)
    if cfg is None or not username or not password:
        return None
    try:
        service_conn = _connect(cfg, cfg["bind_dn"] or None, cfg["bind_password"] or None)
    except Exception as exc:
        logger.warning("LDAP 服务账号 bind 失败: %s", exc)
        return None
    try:
        found = _search_user(service_conn, cfg, username)
    finally:
        service_conn.unbind()
    if found is None:
        return None
    try:
        user_conn = _connect(cfg, found["dn"], password)
    except Exception as exc:
        logger.info("LDAP 用户 bind 失败(%s): %s", username, exc)
        return None
    user_conn.unbind()

    user = session.query(PlatformUser).filter_by(username=username).first()
    if user is None:
        user = PlatformUser(
            username=username, display_name=found["display_name"],
            employee_id=None, role="pm", active=True,
            password_hash=hash_password(_provision_password()),
        )
        session.add(user)
        session.commit()
        logger.info("LDAP 登录自动开通本地账号: %s(pm)", username)
    elif not user.active:
        logger.info("LDAP 认证通过但本地账号已停用: %s", username)
        return None
    return user


def _provision_password() -> str:
    """自动开通账号的本地密码: 随机值(登录走 LDAP, 本地密码仅占位)。"""
    import secrets
    return secrets.token_urlsafe(16)


def sync_users(session: Session, operator: str) -> dict:
    """目录用户导入: 按 filter 全量拉取, 已存在跳过, 新增默认 pm 角色。

    返回 {total, created, skipped}; 导入的账号本地密码为随机值, 日常登录走 LDAP。
    """
    cfg = _runtime_config(session)
    if cfg is None:
        raise ValueError("LDAP 未启用或未配置完整, 请先保存配置并通过连接测试")
    conn = _connect(cfg, cfg["bind_dn"] or None, cfg["bind_password"] or None)
    try:
        _, _, SUBTREE, _ = _require_ldap3()
        username_attr = cfg["attr_username"] or "uid"
        if not conn.search(
                search_base=cfg["base_dn"],
                search_filter=f"(&{cfg['user_filter']}({username_attr}=*))",
                search_scope=SUBTREE, size_limit=2000,
                attributes=[username_attr, cfg["attr_display_name"], cfg["attr_email"]]):
            raise ValueError(f"目录搜索失败: {conn.result.get('description', '')}")
        entries = [
            {
                "username": (str(e[username_attr].value) if username_attr in e and e[username_attr].value else ""),
                "display_name": (str(e[cfg["attr_display_name"]].value)
                                 if cfg["attr_display_name"] in e and e[cfg["attr_display_name"]].value else ""),
            }
            for e in conn.entries
        ]
    finally:
        conn.unbind()

    existing = {u.username for u in session.query(PlatformUser).all()}
    created = 0
    for row in entries:
        if not row["username"] or row["username"] in existing:
            continue
        session.add(PlatformUser(
            username=row["username"],
            display_name=row["display_name"] or row["username"],
            employee_id=None, role="pm", active=True,
            password_hash=hash_password(_provision_password()),
        ))
        existing.add(row["username"])
        created += 1
    session.commit()
    logger.info("LDAP 用户导入完成(%s): 总数 %d, 新增 %d", operator, len(entries), created)
    return {"total": len(entries), "created": created,
            "skipped": len(entries) - created}


def local_login_allowed(session: Session) -> bool:
    """本地账密是否可用: LDAP 未启用, 或允许本地兜底。"""
    cfg = _runtime_config(session)
    if cfg is None:
        return True
    return bool(cfg.get("allow_local_fallback", True))
