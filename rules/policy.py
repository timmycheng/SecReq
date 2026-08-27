# -*- coding: utf-8 -*-
"""密码与会话策略生效值计算。

规则引擎的 policy_baseline 模板占位符与 Word 文档《登录与密码策略设计说明》
使用同一份取值逻辑: 项目显式配置(AuthConfig)优先, 未配置项按定级推导默认基线。
"""
import shared.constants as C
from rules.context import RequirementContext

# 定级缺省兜底(未定级或未知等级时)
_FALLBACK_BASELINE = {"pwd_min_length": 8, "pwd_complexity": 3, "pwd_valid_days": 180}


def effective_password_policy(ctx: RequirementContext) -> dict[str, str]:
    """返回全部策略键的字符串形态值(占位符渲染与文档表格直接可用)。"""
    defaults = C.DEFAULT_PWD_POLICY_BY_LEVEL.get(ctx.grading_level, _FALLBACK_BASELINE)
    cfg = ctx.auth_config

    def pick(key: str, fallback) -> str:
        value = getattr(cfg, key, None) if cfg else None
        return str(value if value is not None else fallback)

    return {
        "pwd_min_length": pick("pwd_min_length", defaults["pwd_min_length"]),
        "pwd_complexity": pick("pwd_complexity", defaults["pwd_complexity"]),
        "pwd_valid_days": pick("pwd_valid_days", defaults["pwd_valid_days"]),
        "pwd_history_limit": pick("pwd_history_limit", 3),
        "lockout_threshold": pick("lockout_threshold", C.DEFAULT_LOCKOUT_THRESHOLD),
        "session_timeout_min": pick("session_timeout_min", C.DEFAULT_SESSION_TIMEOUT_MIN),
        "concurrent_limit": pick("concurrent_limit", 1),
    }
