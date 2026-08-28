# -*- coding: utf-8 -*-
"""项目主表与等保定级问卷。"""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.database import Base


class Project(Base):
    """项目基本信息(向导 Step1) + 合规目标。"""

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), comment="项目名称")
    code: Mapped[str] = mapped_column(String(64), unique=True, comment="项目编码")
    type: Mapped[str] = mapped_column(String(32), comment="项目类型, 见 PROJECT_TYPES")
    industry: Mapped[str] = mapped_column(String(100), default="银行业", comment="所属业务条目")
    user_scale: Mapped[str] = mapped_column(String(32), comment="用户规模, 见 USER_SCALES")
    deploy_env: Mapped[list] = mapped_column(JSON, default=list, comment="部署环境多选")
    is_public: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否涉及公网访问")
    offshore_vendor: Mapped[bool] = mapped_column(
        Boolean, default=False, comment="是否存在境外外包/境外供应商"
    )
    pm_name: Mapped[str | None] = mapped_column(String(50), comment="项目经理")
    dev_lead_name: Mapped[str | None] = mapped_column(String(50), comment="开发负责人")
    sec_contact_name: Mapped[str | None] = mapped_column(String(50), comment="安全对接人")
    compliance_targets: Mapped[list] = mapped_column(
        JSON, default=list, comment="合规目标, 见 COMPLIANCE_TARGETS"
    )
    status: Mapped[str] = mapped_column(String(20), default="draft", comment="项目状态")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    # 关联关系
    survey: Mapped["GradingSurvey | None"] = relationship(back_populates="project", uselist=False)
    features: Mapped[list["Feature"]] = relationship(back_populates="project")  # noqa: F821
    data_assets: Mapped[list["DataAsset"]] = relationship(back_populates="project")  # noqa: F821
    roles: Mapped[list["Role"]] = relationship(back_populates="project")  # noqa: F821
    resources: Mapped[list["Resource"]] = relationship(back_populates="project")  # noqa: F821
    auth_config: Mapped["AuthConfig | None"] = relationship(back_populates="project", uselist=False)
    components: Mapped[list["SbomComponent"]] = relationship(back_populates="project")  # noqa: F821
    api_endpoints: Mapped[list["ApiEndpoint"]] = relationship(back_populates="project")  # noqa: F821
    infra_assets: Mapped[list["InfraAsset"]] = relationship(back_populates="project")  # noqa: F821
    requirements: Mapped[list["SecurityRequirement"]] = relationship(back_populates="project")
    review_gates: Mapped[list["ReviewGate"]] = relationship(back_populates="project")  # noqa: F821


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
