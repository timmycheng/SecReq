# -*- coding: utf-8 -*-
"""平台认证 API 模型(登录/改密)。"""
from pydantic import BaseModel, Field


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=128)


class LoginOut(BaseModel):
    username: str
    display_name: str
    employee_id: str | None
    role: str
    role_label: str
    token: str | None = None  # 仅登录响应携带


class ChangePasswordIn(BaseModel):
    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class PasswordChangeResult(BaseModel):
    message: str
