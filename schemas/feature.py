# -*- coding: utf-8 -*-
"""Step3 功能清单模型。"""
from pydantic import BaseModel, ConfigDict, Field


class FeatureIn(BaseModel):
    uid: str | None = Field(default=None, max_length=36, description="稳定标识; 新增行留空由后端生成(#66)")
    name: str = Field(min_length=1, max_length=200)
    module: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    categories: list[str] = Field(default_factory=list)
    sensitivity: str = "internal"
    involves_payment: bool = False
    exposed_to_internet: bool = False


class FeatureOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    uid: str
    name: str
    module: str | None
    description: str | None
    categories: list[str]
    sensitivity: str
    involves_payment: bool
    exposed_to_internet: bool
