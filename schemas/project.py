# -*- coding: utf-8 -*-
"""Step1 项目基本信息与整卷向导状态模型。"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ExternalSystemIn(BaseModel):
    uid: str | None = Field(default=None, max_length=36, description="稳定标识; 新增行留空由后端生成(#66)")
    name: str = Field(min_length=1, max_length=200)
    purpose: str | None = Field(default=None, max_length=500)
    direction: str = "bidirectional"
    involves_sensitive: bool = False


class ExternalSystemOut(ExternalSystemIn):
    model_config = ConfigDict(from_attributes=True)

    id: int
    uid: str


class ProjectCreate(BaseModel):
    """创建项目: 新建流程只传 name(直通向导第一步), 其余字段后续 PATCH 补充。
    code 缺省时由后端自动生成。"""

    name: str = Field(min_length=1, max_length=200)
    code: str | None = Field(default=None, max_length=64, description="项目编码, 全局唯一; 不传自动生成")
    system_id: int | None = Field(default=None, description="所属系统; 不传=未归属")
    type: str | None = None
    types: list[str] = Field(default_factory=list)
    user_scale: str | None = None
    is_public: bool = False
    offshore_vendor: bool = False
    pm_name: str | None = Field(default=None, max_length=50)
    dev_lead_name: str | None = Field(default=None, max_length=50)
    sec_contact_name: str | None = Field(default=None, max_length=50)
    compliance_targets: list[str] = Field(default_factory=list)

    @field_validator("code")
    @classmethod
    def _code_reject_path_chars(cls, v):
        """编码会用作产物输出目录名, 拒绝路径分隔符与相对路径片段(防穿越)。"""
        if v and ("/" in v or "\\" in v or ":" in v or ".." in v):
            raise ValueError("项目编码不能包含路径分隔符或相对路径片段( / \\ : .. )")
        return v


class ProjectUpdate(BaseModel):
    """更新 Step1(全部可选, 未传字段不覆盖)。code 仅用于拦截修改, 不会落库。"""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    code: str | None = Field(default=None, max_length=64, description="仅用于返回400: 编码不允许修改")
    system_id: int | None = Field(default=None, description="所属系统; 传 null 解除归属")
    type: str | None = None
    types: list[str] | None = None
    user_scale: str | None = None
    is_public: bool | None = None
    offshore_vendor: bool | None = None
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
    types: list[str] = []

    @field_validator("types", mode="before")
    @classmethod
    def _empty_types_to_list(cls, v):
        """存量库 types 列可能为 NULL, 统一折算为空列表(serialize 阶段再回退 [type])。"""
        return v if isinstance(v, list) else []
    user_scale: str
    is_public: bool
    offshore_vendor: bool = False
    pm_name: str | None
    dev_lead_name: str | None
    sec_contact_name: str | None
    compliance_targets: list[str]
    owner_user_id: int | None = None
    system_id: int | None = None
    status: str
    created_at: datetime | None = None


class ProjectDetail(ProjectOut):
    """列表页卡片信息: 各步骤填写进度 + 有效定级 + 创建人。"""

    has_survey: bool = False
    grading_level: str | None = None
    owner_name: str | None = None
    counts: dict[str, int] = {}
    system_name: str | None = None
    filing_name: str | None = None
    filing_level: str | None = None
    is_current_baseline: bool = False


def serialize_project(project) -> ProjectOut:
    out = ProjectOut.model_validate(project)
    # 类型多选: 兼容存量单值数据(types 为空时回退 [type])
    if not out.types and out.type:
        out.types = [out.type]
    if out.types and not out.type:
        out.type = out.types[0]
    return out


# ── 向导一次性加载(编辑已建项目时减少请求数) ────────────

class WizardState(BaseModel):
    project: ProjectOut
    survey: object | None = None
    external_systems: list[object] = []
    features: list[object] = []
    data_assets: list[object] = []      # 含 tables→fields 三级嵌套
    roles: list[object] = []
    resources: list[object] = []
    permission_entries: list[object] = []
    auth_config: object | None = None
    components: list[object] = []       # 含已命中的 vulnerabilities
    api_endpoints: list[object] = []
    infra_assets: list[object] = []
