# -*- coding: utf-8 -*-
"""Step4 数据字典三级结构: 资产 → 表 → 字段。"""
from pydantic import BaseModel, ConfigDict, Field


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
    name: str = Field(min_length=1, max_length=200)
    data_type: str
    classification: str = "内部"
    is_pii: bool = False
    is_sensitive_pii: bool = False
    storage_envs: list[str] = Field(default_factory=list)
    cross_border_transfer: bool = False
    tables: list[DataTableIn] = Field(default_factory=list)


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
    name: str
    data_type: str
    classification: str
    is_pii: bool
    is_sensitive_pii: bool
    storage_envs: list[str]
    cross_border_transfer: bool
    tables: list[DataTableOut] = []
