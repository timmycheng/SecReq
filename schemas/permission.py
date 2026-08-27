# -*- coding: utf-8 -*-
"""Step5 用户权限矩阵: 角色 × 资源 × 操作(含审批标记)。"""
from pydantic import BaseModel, ConfigDict, Field


class RoleIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    role_type: str = "normal"
    user_count_estimate: int = Field(default=0, ge=0)


class ResourceIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    resource_type: str
    criticality: str = "medium"


class MatrixEntryIn(BaseModel):
    """单元格授权。role_index/resource_index 指本次提交体中的下标(矩阵整体替换)。"""

    role_index: int = Field(ge=0)
    resource_index: int = Field(ge=0)
    action: str
    requires_approval: bool = False


class PermissionMatrixIn(BaseModel):
    roles: list[RoleIn]
    resources: list[ResourceIn]
    entries: list[MatrixEntryIn] = Field(default_factory=list)


class RoleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    role_type: str
    user_count_estimate: int


class ResourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    resource_type: str
    criticality: str


class MatrixEntryOut(BaseModel):
    id: int
    role_id: int
    resource_id: int
    action: str
    requires_approval: bool


class PermissionMatrixOut(BaseModel):
    roles: list[RoleOut]
    resources: list[ResourceOut]
    entries: list[MatrixEntryOut]
