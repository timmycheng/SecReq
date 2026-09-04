# -*- coding: utf-8 -*-
"""项目主表与等保定级问卷。"""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.database import Base, UidMixin


class Project(Base):
    """项目基本信息(向导 Step1) + 合规目标。"""

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), comment="项目名称")
    code: Mapped[str] = mapped_column(String(64), unique=True, comment="项目编码")
    type: Mapped[str] = mapped_column(String(32), default="", comment="主项目类型(兼容保留), 见 PROJECT_TYPES")
    types: Mapped[list] = mapped_column(
        JSON, default=list, comment="项目类型多选(已停用, #194 起真相在 systems.types, 兼容回退用)"
    )
    industry: Mapped[str | None] = mapped_column(String(100), comment="所属业务条目(已停用, 兼容保留)")
    user_scale: Mapped[str] = mapped_column(
        String(32), default="", comment="用户规模(已停用, #194 起真相在 systems.user_scale, 兼容回退用)"
    )
    deploy_env: Mapped[list] = mapped_column(JSON, default=list, comment="部署环境(已停用, 兼容保留)")
    is_public: Mapped[bool] = mapped_column(
        Boolean, default=False, comment="是否涉及公网访问(已停用, #194 起真相在 systems.is_public)"
    )
    offshore_vendor: Mapped[bool] = mapped_column(
        Boolean, default=False, comment="境外外包(已停用, #194 起真相在 systems.offshore_vendor)"
    )
    pm_name: Mapped[str | None] = mapped_column(String(50), comment="项目经理")
    dev_lead_name: Mapped[str | None] = mapped_column(String(50), comment="开发负责人")
    sec_contact_name: Mapped[str | None] = mapped_column(String(50), comment="安全对接人")
    compliance_targets: Mapped[list] = mapped_column(
        JSON, default=list, comment="合规目标, 见 COMPLIANCE_TARGETS"
    )
    owner_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("platform_users.id"), index=True,
        comment="创建人(数据权限: 开发仅见本人项目)",
    )
    system_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("systems.id"), index=True,
        comment="所属系统(空=未归属, 存量项目可后补)",
    )
    status: Mapped[str] = mapped_column(String(20), default="draft", comment="项目状态")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    # 关联关系
    survey: Mapped["GradingSurvey | None"] = relationship(back_populates="project", uselist=False)
    features: Mapped[list["Feature"]] = relationship(back_populates="project")  # noqa: F821
    data_assets: Mapped[list["DataAsset"]] = relationship(back_populates="project")  # noqa: F821
    roles: Mapped[list["Role"]] = relationship(back_populates="project")  # noqa: F821
    resources: Mapped[list["Resource"]] = relationship(back_populates="project")  # noqa: F821
    auth_config: Mapped["AuthConfig | None"] = relationship(back_populates="project", uselist=False)  # noqa: F821
    api_endpoints: Mapped[list["ApiEndpoint"]] = relationship(back_populates="project")  # noqa: F821
    requirements: Mapped[list["SecurityRequirement"]] = relationship(back_populates="project")  # noqa: F821
    review_gates: Mapped[list["ReviewGate"]] = relationship(back_populates="project")  # noqa: F821
    external_systems: Mapped[list["ExternalSystem"]] = relationship(back_populates="project")
    system: Mapped["System | None"] = relationship(back_populates="projects")  # noqa: F821

    # ── 系统字段解析器(#194): 真相在挂靠系统, 未归属/未填时回退本项目遗留列 ──

    def effective_user_scale(self) -> str:
        if self.system is not None and self.system.user_scale:
            return self.system.user_scale
        return self.user_scale or ""

    def effective_types(self) -> list:
        if self.system is not None and self.system.types:
            return self.system.types
        return self.types or []

    def effective_is_public(self) -> bool:
        if self.system is not None:
            return bool(self.system.is_public)
        return bool(self.is_public)

    def effective_offshore_vendor(self) -> bool:
        if self.system is not None:
            return bool(self.system.offshore_vendor)
        return bool(self.offshore_vendor)


class GradingSurvey(Base):
    """Step2 等保定级问卷答案与定级结论。"""

    __tablename__ = "grading_surveys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id"), index=True, comment="所属项目"
    )
    answers_json: Mapped[list] = mapped_column(JSON, default=list, comment="问卷答案[{question_id, option_id, score...}]")
    suggested_level: Mapped[str | None] = mapped_column(String(10), comment="系统建议定级: 一级/二级/三级")
    suggested_reason: Mapped[str | None] = mapped_column(Text, comment="建议判定理由文字")
    final_level: Mapped[str | None] = mapped_column(String(10), comment="人工修正后最终定级")
    manual_adjust_note: Mapped[str | None] = mapped_column(Text, comment="人工修正说明")

    project: Mapped[Project] = relationship(back_populates="survey")

    def effective_level(self) -> str:
        """规则引擎使用: 最终定级优先, 无人工修正则取建议定级。"""
        return self.final_level or self.suggested_level or ""


class ExternalSystem(Base, UidMixin):
    """Step1 采集: 与本项目交互的外部系统清单(驱动外部交互类安全需求)。"""

    __tablename__ = "external_systems"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id"), index=True, comment="所属项目"
    )
    name: Mapped[str] = mapped_column(String(200), comment="外部系统名称")
    purpose: Mapped[str | None] = mapped_column(String(500), comment="对接内容/业务用途")
    direction: Mapped[str] = mapped_column(
        String(20), default="bidirectional", comment="数据方向, 见 EXTERNAL_SYSTEM_DIRECTIONS"
    )
    involves_sensitive: Mapped[bool] = mapped_column(
        Boolean, default=False, comment="是否传输敏感数据"
    )

    project: Mapped[Project] = relationship(back_populates="external_systems")
