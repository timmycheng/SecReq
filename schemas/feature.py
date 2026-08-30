# -*- coding: utf-8 -*-
"""Step3 功能清单模型。"""
from pydantic import BaseModel, ConfigDict, Field


class FeatureIn(BaseModel):
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
    name: str
    module: str | None
    description: str | None
    categories: list[str]
    sensitivity: str
    involves_payment: bool
    exposed_to_internet: bool
