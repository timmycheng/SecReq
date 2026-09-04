# -*- coding: utf-8 -*-
"""Step8 API 接口清单与基础设施资产模型。"""
from pydantic import BaseModel, ConfigDict, Field


class ApiEndpointIn(BaseModel):
    uid: str | None = Field(default=None, max_length=36, description="稳定标识; 新增行留空由后端生成(#66)")
    name: str = Field(min_length=1, max_length=200)
    path: str = Field(min_length=1, max_length=300)
    method: str
    auth_required: bool = True
    public_exposed: bool = False
    sensitive_asset_ids: list[int] = Field(default_factory=list)
    # 敏感资产关联的稳定形态(#66): 保存时前端回传 uid, 后端按 uid 关联
    sensitive_asset_uids: list[str] = Field(default_factory=list)
    rate_limit: str | None = Field(default=None, max_length=50)


class InfraAssetIn(BaseModel):
    uid: str | None = Field(default=None, max_length=36, description="稳定标识; 新增行留空由后端生成(#66)")
    asset_type: str
    name: str = Field(min_length=1, max_length=200)
    env: str = "prod"
    ip: str | None = Field(default=None, max_length=64)
    owner: str | None = Field(default=None, max_length=50)
    holds_sensitive: bool = False
    cpu_cores: int | None = Field(default=None, ge=1, le=4096)
    memory_gb: int | None = Field(default=None, ge=1, le=65536)
    disk_gb: int | None = Field(default=None, ge=1, le=10_000_000)
    os: str | None = Field(default=None, max_length=100)
    quantity: int | None = Field(default=None, ge=1, le=10_000)
    purpose: str | None = Field(default=None, max_length=300)


class InfraAssetListIn(BaseModel):
    assets: list[InfraAssetIn] = Field(default_factory=list)


class InventorySaveIn(BaseModel):
    api_endpoints: list[ApiEndpointIn] = Field(default_factory=list)
    infra_assets: list[InfraAssetIn] = Field(default_factory=list)


class ApiEndpointOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    uid: str
    name: str
    path: str
    method: str
    auth_required: bool
    public_exposed: bool
    sensitive_asset_ids: list[int]
    sensitive_asset_uids: list[str] = []
    rate_limit: str | None


class InfraAssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    uid: str
    asset_type: str
    name: str
    env: str
    ip: str | None
    owner: str | None
    holds_sensitive: bool
    cpu_cores: int | None = None
    memory_gb: int | None = None
    disk_gb: int | None = None
    os: str | None = None
    quantity: int | None = None
    purpose: str | None = None


class InfraArchImageIn(BaseModel):
    """架构图上传(#164): data URL 形态(base64), 每环境一张。"""

    image_data_url: str = Field(min_length=32, max_length=2_800_000)


class InfraArchImageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    env: str
    image_data_url: str
