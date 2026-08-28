# -*- coding: utf-8 -*-
"""密码与会话策略生效值计算。

规则引擎的 policy_baseline 模板占位符与 Word 文档《登录与密码策略设计说明》
使用同一份取值逻辑: 项目显式配置(AuthConfig)优先, 未配置项按定级推导默认基线。
"""
import shared.constants as C
from rules.context import RequirementContext

# 定级缺省兜底(未定级或未知等级时)
_FALLBACK_BASELINE = {"pwd_min_length": 8, "pwd_complexity": 3, "pwd_valid_days": 180}

# 管理端覆盖(系统管理→策略基线; None 时用 shared.constants 内置默认)
_baseline_override: dict | None = None


def get_policy_baselines() -> dict:
    """按等级的默认密码基线(内置默认或管理端覆盖)。"""
    return _baseline_override or C.DEFAULT_PWD_POLICY_BY_LEVEL


def set_policy_baselines(value: dict | None) -> None:
    """管理端保存后注入(进程内生效); value=None 恢复内置默认。"""
    global _baseline_override
    _baseline_override = value


def effective_password_policy(ctx: RequirementContext) -> dict[str, str]:
    """返回全部策略键的字符串形态值(占位符渲染与文档表格直接可用)。"""
    defaults = get_policy_baselines().get(ctx.grading_level, _FALLBACK_BASELINE)
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
