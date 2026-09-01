# -*- coding: utf-8 -*-
"""系统设置服务: 键值读写 + LLM 接入配置解析。

LLM 配置优先取库内 system_settings(key=llm), 未配置时回退环境变量:
    SECREQ_LLM_BASE_URL / SECREQ_LLM_API_KEY / SECREQ_LLM_MODEL
接口为 OpenAI 兼容 /chat/completions(内网大模型网关或公有云均可)。
"""
import os

from sqlalchemy.orm import Session

from models import SystemSetting

LLM_KEY = "llm"


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
