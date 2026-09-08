# -*- coding: utf-8 -*-
"""系统设置服务: 键值读写 + LLM/NetBox 接入配置解析。

LLM 配置优先取库内 system_settings(key=llm), 未配置时回退环境变量:
    SECREQ_LLM_BASE_URL / SECREQ_LLM_API_KEY / SECREQ_LLM_MODEL
接口为 OpenAI 兼容 /chat/completions(内网大模型网关或公有云均可)。

NetBox 配置(#152)同口径: 库内 system_settings(key=netbox) 优先,
回退 SECREQ_NETBOX_URL / SECREQ_NETBOX_TOKEN / SECREQ_NETBOX_SYSTEM_SLUG。
"""
import os

from sqlalchemy.orm import Session

import shared.constants as C
from models import SystemSetting

LLM_KEY = "llm"
NETBOX_KEY = "netbox"
#: NetBox system 对象的 custom-objects 类型 slug 默认值(#154)
DEFAULT_NETBOX_FIELD_MAP = {"name": "name", "code": "code", "owner": "owner"}


def get_setting(session: Session, key: str, default: dict | None = None) -> dict:
    row = session.query(SystemSetting).filter_by(key=key).first()
    return row.value if row and isinstance(row.value, dict) else (default or {})


def set_setting(session: Session, key: str, value: dict) -> dict:
    row = session.query(SystemSetting).filter_by(key=key).first()
    if row is None:
        row = SystemSetting(key=key, value=value)
        session.add(row)
    else:
        row.value = value
    session.commit()
    return value


def get_llm_config(session: Session) -> dict:
    """解析 LLM 配置: {base_url, api_key, model} 或 {}(未配置)。"""
    cfg = get_setting(session, LLM_KEY)
    base_url = (cfg.get("base_url") or os.environ.get("SECREQ_LLM_BASE_URL") or "").rstrip("/")
    api_key = cfg.get("api_key") or os.environ.get("SECREQ_LLM_API_KEY") or ""
    model = cfg.get("model") or os.environ.get("SECREQ_LLM_MODEL") or ""
    if base_url and api_key and model:
        return {"base_url": base_url, "api_key": api_key, "model": model}
    return {}


def get_netbox_config(session: Session) -> dict:
    """解析 NetBox 配置(#152): {base_url, token, system_slug, field_map} 或 {}(未配置)。

    库内优先, 环境变量回退; system_slug/field_map 有默认值, 地址与 token 齐全才算已配置。
    """
    cfg = get_setting(session, NETBOX_KEY)
    base_url = (cfg.get("base_url") or os.environ.get("SECREQ_NETBOX_URL") or "").rstrip("/")
    token = cfg.get("token") or os.environ.get("SECREQ_NETBOX_TOKEN") or ""
    if not (base_url and token):
        return {}
    system_slug = cfg.get("system_slug") or os.environ.get("SECREQ_NETBOX_SYSTEM_SLUG") or "system"
    field_map = cfg.get("field_map")
    if not isinstance(field_map, dict) or not field_map:
        field_map = dict(DEFAULT_NETBOX_FIELD_MAP)
    return {
        "base_url": base_url,
        "token": token,
        "system_slug": system_slug,
        "field_map": field_map,
    }


#: 定时同步默认周期(小时): 默认每天一次
DEFAULT_NETBOX_SYNC_INTERVAL_HOURS = 24


def get_netbox_schedule(session: Session) -> dict:
    """读取定时同步调度配置(#271): {enabled, interval_hours}。未配置时关闭。"""
    cfg = get_setting(session, NETBOX_KEY)
    raw_interval = cfg.get("sync_interval_hours")
    interval = raw_interval if isinstance(raw_interval, int) else None
    if not interval or not (1 <= interval <= 720):
        interval = DEFAULT_NETBOX_SYNC_INTERVAL_HOURS
    return {"enabled": bool(cfg.get("sync_enabled")), "interval_hours": interval}


PROJECT_CODE_RULE_KEY = "project_code_rule"
#: 与前端预览一致的默认格式: XM2026-001(#85)
DEFAULT_PROJECT_CODE_RULE = {"prefix": "XM", "include_year": True, "digits": 3}


def get_project_code_rule(session: Session) -> dict:
    """读取项目编号规则, 未配置或字段非法时逐项回退默认(老库零影响)。"""
    raw = get_setting(session, PROJECT_CODE_RULE_KEY)
    prefix = raw.get("prefix") if isinstance(raw.get("prefix"), str) else None
    if not prefix or not prefix.isalnum() or not (1 <= len(prefix) <= 10):
        prefix = DEFAULT_PROJECT_CODE_RULE["prefix"]
    include_year = raw.get("include_year")
    if not isinstance(include_year, bool):
        include_year = DEFAULT_PROJECT_CODE_RULE["include_year"]
    digits = raw.get("digits")
    if not isinstance(digits, int) or not (1 <= digits <= 6):
        digits = DEFAULT_PROJECT_CODE_RULE["digits"]
    return {"prefix": prefix, "include_year": include_year, "digits": digits}


INFRA_ENVS_KEY = "infra_envs"#: 基础资源环境默认值(DESIGN: 分环境可配置); 存量库无此配置时零影响
DEFAULT_INFRA_ENVS = [
    {"code": "dev", "name": "开发环境"},
    {"code": "test", "name": "测试环境"},
    {"code": "prod", "name": "生产环境"},
]


def get_infra_envs(session: Session) -> list[dict]:
    """基础资源环境列表(code+name), 未配置或配置非法时回退默认三环境。"""
    raw = get_setting(session, INFRA_ENVS_KEY).get("envs")
    if not isinstance(raw, list):
        return [dict(e) for e in DEFAULT_INFRA_ENVS]
    envs: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        code = item.get("code")
        name = item.get("name")
        if not (isinstance(code, str) and code.strip() and len(code) <= 20):
            continue
        if not (isinstance(name, str) and name.strip() and len(name) <= 30):
            continue
        if any(e["code"] == code for e in envs):
            continue
        envs.append({"code": code.strip(), "name": name.strip()})
    return envs or [dict(e) for e in DEFAULT_INFRA_ENVS]

SYSTEM_DICTS_KEY = "system_dicts"
#: 系统标签字典默认值(DESIGN: 标签如 重要信息系统/人行上报, 系统管理内自定义)
DEFAULT_SYSTEM_TAGS = ["重要信息系统", "人行上报"]


def get_system_dicts(session: Session) -> dict:
    """系统字典(系统管理维护): {tags: [str], types: {code: label}}。

    types 未配置时回退常量 PROJECT_TYPES; 形态不合法的配置逐项忽略。
    """
    raw = get_setting(session, SYSTEM_DICTS_KEY)
    tags = raw.get("tags")
    if not isinstance(tags, list):
        tags = list(DEFAULT_SYSTEM_TAGS)
    tags = [t for t in tags if isinstance(t, str) and t.strip()]

    types = raw.get("types")
    if not isinstance(types, dict) or not types:
        types = dict(C.PROJECT_TYPES)
    else:
        types = {
            code: label for code, label in types.items()
            if isinstance(code, str) and code.strip() and isinstance(label, str) and label.strip()
        } or dict(C.PROJECT_TYPES)
    return {"tags": tags, "types": types}
