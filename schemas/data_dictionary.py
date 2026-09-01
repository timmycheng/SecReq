# -*- coding: utf-8 -*-
"""Step4 数据字典三级结构: 资产 → 表 → 字段。"""
from pydantic import BaseModel, ConfigDict, Field, field_validator

import shared.constants as C


class DataFieldIn(BaseModel):
    field_name: str = Field(min_length=1, max_length=128)
    field_type: str = Field(default="varchar", max_length=64)
    need_encrypt: bool = False
    need_mask: bool = False
    mask_rule: str | None = None


class DataTableIn(BaseModel):
    table_name: str = Field(min_length=1, max_length=128)
    fields: list[DataFieldIn] = Field(default_factory=list)


class DataAssetIn(BaseModel):
    uid: str | None = Field(default=None, max_length=36, description="稳定标识; 新增行留空由后端生成(#66)")
    name: str = Field(min_length=1, max_length=200)
    data_type: str
    classification: str = "2级_C1次要信息"
    c3_tag: bool = False
    is_pii: bool = False
    is_sensitive_pii: bool = False
    storage_envs: list[str] = Field(default_factory=list)
    cross_border_transfer: bool = False
    tables: list[DataTableIn] = Field(default_factory=list)

    @field_validator("classification")
    @classmethod
    def _check_level(cls, v: str) -> str:
        if v not in C.DATA_LEVELS and v not in C.LEGACY_CLASSIFICATION_MAP:
            raise ValueError(f"分级必须是 JR/T 0197 五级之一: {'、'.join(C.DATA_LEVELS)}")
        # 老 4 级值兼容: 落库前统一折算为新 5 级 code
        return C.LEGACY_CLASSIFICATION_MAP.get(v, v)


class DataAssetListIn(BaseModel):
    assets: list[DataAssetIn] = Field(default_factory=list)


class DataFieldOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    field_name: str
    field_type: str
    need_encrypt: bool
    need_mask: bool
    mask_rule: str | None


class DataTableOut(BaseModel):
    id: int
    table_name: str
    fields: list[DataFieldOut] = []


class DataAssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    uid: str
    name: str
    data_type: str
    classification: str
    legacy_classification: str | None = None
    c3_tag: bool = False
    is_pii: bool
    is_sensitive_pii: bool
    storage_envs: list[str]
    cross_border_transfer: bool
    tables: list[DataTableOut] = []
