# -*- coding: utf-8 -*-
"""规则引擎产物: 安全需求记录。

约束: source_entity_id 必填, 需求必须可追溯到输入(DESIGN.md 第七节)。
template_id 保留知识库模板 id; 同一模板命中多个实例时 req_id 追加序号后缀保证唯一。
"""
from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.database import Base
from models.project import Project


class SecurityRequirement(Base):
    __tablename__ = "security_requirements"
    __table_args__ = (UniqueConstraint("project_id", "req_id", name="uq_req_project_reqid"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("projects.id"), index=True)
    req_id: Mapped[str] = mapped_column(String(40), index=True, comment="如 SEC-V12-001-02(模板id+实例序号)")
    template_id: Mapped[str] = mapped_column(String(40), comment="命中的知识库模板 id")
    title: Mapped[str] = mapped_column(String(300), comment="需求标题")
    description: Mapped[str] = mapped_column(Text, comment="需求描述(占位符已渲染)")
    category: Mapped[str] = mapped_column(String(30), comment="业务归类, 见 TRIGGER_CATEGORY_LABELS")
    priority: Mapped[str] = mapped_column(String(10), comment="critical/high/medium/low")
    asvs_ref: Mapped[str | None] = mapped_column(String(50), comment="OWASP ASVS 条款编号")
    acceptance_criteria: Mapped[str] = mapped_column(Text, comment="验收标准")
    suggested_phase: Mapped[str] = mapped_column(String(20), comment="design/development/test")
    source_entity_type: Mapped[str] = mapped_column(
        String(40), comment="来源实体类型(feature/data_asset/api_endpoint/vulnerability等)"
    )
    source_entity_id: Mapped[int] = mapped_column(Integer, comment="来源实体主键")
    trigger_reason: Mapped[str] = mapped_column(Text, comment="触发了哪条输入(可回溯)")
    status: Mapped[str] = mapped_column(String(20), default="open", comment="open/in_progress/done/risk_accepted")

    project: Mapped[Project] = relationship(back_populates="requirements")
