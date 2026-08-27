# -*- coding: utf-8 -*-
"""Step1 项目基本信息与整卷向导状态模型。"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ProjectCreate(BaseModel):
    """创建项目(仅必填主干, 其余走 PATCH 补充)。"""

    name: str = Field(min_length=1, max_length=200)
    code: str = Field(min_length=1, max_length=64, description="项目编码, 全局唯一")
    type: str
    industry: str | None = None
    user_scale: str
    deploy_env: list[str] = Field(default_factory=list)
    is_public: bool = False
    pm_name: str | None = Field(default=None, max_length=50)
    dev_lead_name: str | None = Field(default=None, max_length=50)
    sec_contact_name: str | None = Field(default=None, max_length=50)
    compliance_targets: list[str] = Field(default_factory=list)


class ProjectUpdate(BaseModel):
    """更新 Step1(全部可选, 未传字段不覆盖)。"""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    type: str | None = None
    industry: str | None = None
    user_scale: str | None = None
    deploy_env: list[str] | None = None
    is_public: bool | None = None
    pm_name: str | None = Field(default=None, max_length=50)
    dev_lead_name: str | None = Field(default=None, max_length=50)
    sec_contact_name: str | None = Field(default=None, max_length=50)
    compliance_targets: list[str] | None = None


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    code: str
    type: str
    industry: str | None
    user_scale: str
    deploy_env: list[str]
    is_public: bool
    pm_name: str | None
    dev_lead_name: str | None
    sec_contact_name: str | None
    compliance_targets: list[str]
    status: str
    created_at: datetime | None = None


class ProjectDetail(ProjectOut):
    """列表页卡片信息: 各步骤填写进度 + 有效定级。"""

    has_survey: bool = False
    grading_level: str | None = None
    counts: dict[str, int] = {}


def serialize_project(project) -> ProjectOut:
    return ProjectOut.model_validate(project)


# ── 向导一次性加载(编辑已建项目时减少请求数) ────────────

class WizardState(BaseModel):
    project: ProjectOut
    survey: object | None = None
    features: list[object] = []
    data_assets: list[object] = []      # 含 tables→fields 三级嵌套
    roles: list[object] = []
    resources: list[object] = []
    permission_entries: list[object] = []
    auth_config: object | None = None
    components: list[object] = []       # 含已命中的 vulnerabilities
    api_endpoints: list[object] = []
    infra_assets: list[object] = []
