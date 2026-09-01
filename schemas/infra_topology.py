# -*- coding: utf-8 -*-
"""基础设施拓扑画布一期(#93): 区域/连线/布局的保存与读取模型。

布局 JSON 不进规则引擎, 仅服务画布还原; 设备(InfraAsset)沿用既有清单契约。
"""
from pydantic import BaseModel, Field


class ZoneIn(BaseModel):
    uid: str = Field(min_length=8, max_length=36)
    name: str = Field(min_length=1, max_length=100)


class LinkIn(BaseModel):
    source_uid: str = Field(min_length=8, max_length=36)
    target_uid: str = Field(min_length=8, max_length=36)
    label: str | None = Field(default=None, max_length=200)


class TopologySaveIn(BaseModel):
    """按环境整卷保存: 设备清单 + 区域 + 连线 + 布局。env 仅支持 test/prod。"""

    env: str = Field(pattern=r"^(test|prod)$")
    zones: list[ZoneIn] = Field(default_factory=list)
    links: list[LinkIn] = Field(default_factory=list)
    layout: dict = Field(default_factory=dict)
    assets: list[dict] = Field(default_factory=list, description="该环境的设备清单(InfraAssetIn 形态 + zone_uid)")


class TopologyOut(BaseModel):
    env: str
    zones: list[dict] = []
    links: list[dict] = []
    layout: dict = {}
