# -*- coding: utf-8 -*-
"""系统台账(定级备案 + 被评估系统)的 API 模型。"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

import shared.constants as C


def _validate_level(v: str | None) -> str | None:
    if v is not None and v not in C.GRADING_LEVELS:
        raise ValueError(f"定级必须是 {('、'.join(C.GRADING_LEVELS))} 之一")
    return v


class FilingCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    code: str | None = Field(default=None, max_length=64)
    level: str
    note: str | None = None

    @field_validator("level")
    @classmethod
    def _level(cls, v):
        return _validate_level(v)


class FilingUpdate(BaseModel):
    """全部可选, 未传字段不覆盖。"""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    code: str | None = Field(default=None, max_length=64)
    level: str | None = None
    note: str | None = None

    @field_validator("level")
    @classmethod
    def _level(cls, v):
        return _validate_level(v)


class FilingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    code: str | None = None
    level: str
    note: str | None = None
    created_at: datetime | None = None


class FilingDetail(FilingOut):
    """台账行: 附下挂系统数与最新一轮评估概况。"""

    system_count: int = 0
    latest_round: dict | None = None


class SystemCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    code: str | None = Field(default=None, max_length=64)
    netbox_object_id: str | None = Field(default=None, max_length=32)
    filing_id: int | None = None
    owner_name: str | None = Field(default=None, max_length=50)
    # ── 基本信息(#194 自项目上收) ──
    user_scale: str | None = Field(default=None, max_length=32)
    types: list[str] = Field(default_factory=list)
    is_public: bool = False


class SystemUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    code: str | None = Field(default=None, max_length=64)
    filing_id: int | None = None
    owner_name: str | None = Field(default=None, max_length=50)
    user_scale: str | None = Field(default=None, max_length=32)
    types: list[str] | None = None
    is_public: bool | None = None


class SystemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    code: str | None = None
    netbox_object_id: str | None = None
    filing_id: int | None = None
    owner_name: str | None = None
    user_scale: str | None = None
    types: list[str] = Field(default_factory=list)
    is_public: bool = False
    created_at: datetime | None = None


class SystemDetail(SystemOut):
    """系统详情: 备案定级事实 + 评估时间线。"""

    filing_name: str | None = None
    filing_level: str | None = None
    current_baseline_project_id: int | None = None
    rounds: list[dict] = []
