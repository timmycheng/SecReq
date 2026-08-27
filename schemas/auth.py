# -*- coding: utf-8 -*-
"""Step6 认证方式与密码/会话策略模型。"""
from pydantic import BaseModel, ConfigDict, Field


class AuthConfigIn(BaseModel):
    """密码策略字段可为空: 空值表示沿用按定级推导的默认基线。"""

    auth_methods: list[str] = Field(default_factory=list)
    pwd_min_length: int | None = Field(default=None, ge=6, le=64)
    pwd_complexity: int | None = Field(default=None, ge=1, le=4)
    pwd_valid_days: int | None = Field(default=None, ge=1, le=3650)
    lockout_threshold: int | None = Field(default=None, ge=1, le=100)
    pwd_history_limit: int | None = Field(default=None, ge=0, le=24)
    force_2fa: bool = False
    session_timeout_min: int | None = Field(default=None, ge=1, le=1440)
    concurrent_limit: int | None = Field(default=None, ge=1, le=99)


class AuthConfigOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    auth_methods: list[str]
    pwd_min_length: int | None
    pwd_complexity: int | None
    pwd_valid_days: int | None
    lockout_threshold: int | None
    pwd_history_limit: int | None
    force_2fa: bool
    session_timeout_min: int | None
    concurrent_limit: int | None


class AuthDefaultsOut(BaseModel):
    """按有效定级推导的策略默认值(Step6 设计器预填)。"""

    grading_level: str
    defaults: dict[str, int]
