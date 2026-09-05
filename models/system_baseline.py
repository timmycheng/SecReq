# -*- coding: utf-8 -*-
"""系统安全基线(D 区)(#223): 评审通过后的基线快照与变更履历。

「系统档案卡 = 事实基线」: 评估轮次的项目级数据(资产/字典/权限矩阵/API 清单)
经评审通过(#225 终审 passed)后写回系统, 成为本系统的权威基线;
下一轮评估(#224)按基线预填、只填增量。project 级模型保持不动, 本表只是承接位。

SystemBaseline: 每系统一行(UNIQUE)的当前基线快照。
SystemBaselineHistory: 每次写回一条履历(谁/何时/依据哪次评审/变更摘要)。
"""
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.database import Base


class SystemBaseline(Base):
    """系统当前安全基线(D 区): 资产目录/数据字典/权限矩阵/API 清单的快照。"""

    __tablename__ = "system_baselines"
    __table_args__ = (UniqueConstraint("system_id", name="uq_baseline_system"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    system_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("systems.id"), index=True)
    baseline_json: Mapped[dict] = mapped_column(
        JSON, default=dict,
        comment="基线快照: {data_assets, roles, resources, permission_entries, api_endpoints}")
    source_project_id: Mapped[int | None] = mapped_column(
        Integer, comment="来源评估轮次(项目 id)")
    source_gate_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("review_gates.id"), comment="依据哪次评审(ReviewGate)")
    summary: Mapped[str | None] = mapped_column(Text, comment="最近一次写回的变更内容摘要")
    pending_level_confirmation: Mapped[dict | None] = mapped_column(
        JSON, nullable=True,
        comment="等保级别变更确认待办(#225): {suggested_level, filing_level, project_id}; 人工确认后置空")
    updated_by: Mapped[str | None] = mapped_column(String(50), comment="写回操作人姓名")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    histories: Mapped[list["SystemBaselineHistory"]] = relationship(
        back_populates="baseline", cascade="all, delete-orphan",
        order_by="SystemBaselineHistory.id.desc()",
    )


class SystemBaselineHistory(Base):
    """基线变更履历: 谁/何时/依据哪次评审/变更内容摘要(append-only)。"""

    __tablename__ = "system_baseline_histories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    system_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("systems.id"), index=True)
    baseline_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("system_baselines.id"), comment="所属基线行")
    project_id: Mapped[int | None] = mapped_column(Integer, comment="来源评估轮次")
    gate_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("review_gates.id"), comment="依据的评审门禁")
    summary: Mapped[str] = mapped_column(Text, comment="变更内容摘要")
    operator_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("platform_users.id"), comment="写回操作人")
    operator_name: Mapped[str | None] = mapped_column(String(50), comment="操作人姓名")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    baseline: Mapped[SystemBaseline | None] = relationship(back_populates="histories")
