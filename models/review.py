# -*- coding: utf-8 -*-
"""评审流程与门禁(改造点4/5): 平台用户 + 评审门禁 + 链式哈希留痕。

ReviewGate: 每项目每门禁类型一行(UNIQUE), 两步签核
    提交(pm/developer) → 评审员审核(security_reviewer) → 负责人终审(security_lead)。
ReviewEvidence: 门禁上的动作流水, curr_hash = SHA256(prev_hash + 动作字段),
    同一门禁内链式防篡改; 创世 prev_hash 为 64 个 0。
"""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.database import Base

GENESIS_HASH = "0" * 64


class PlatformUser(Base):
    """平台侧用户(与项目内权限矩阵的 Role 无关)。

    MVP 阶段用户由种子数据维护(见 services.auth_service), 登录仅校验用户名存在,
    请求通过 X-Auth-User 头携带身份; 电子签章以「姓名+工号+时间戳+哈希」代替。
    """

    __tablename__ = "platform_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, comment="登录名")
    display_name: Mapped[str] = mapped_column(String(50), comment="姓名(签章展示用)")
    employee_id: Mapped[str | None] = mapped_column(String(30), comment="工号(签章展示用)")
    role: Mapped[str] = mapped_column(String(30), comment="平台角色, 见 PLATFORM_ROLES")
    active: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否启用")


class ReviewGate(Base):
    """评审门禁: 立项/需求/设计(本期), POC/上线仅建数据结构。"""

    __tablename__ = "review_gates"
    __table_args__ = (UniqueConstraint("project_id", "gate_type", name="uq_gate_project_type"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("projects.id"), index=True)
    gate_type: Mapped[str] = mapped_column(String(20), comment="initiation/requirement/design/poc/launch")
    status: Mapped[str] = mapped_column(
        String(20), default="pending", comment="pending/in_review/passed/rejected/rectifying"
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, comment="提交评审时间")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, comment="评审员审核时间")
    submitter_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("platform_users.id"), comment="提交人(评审人不得为同一人)"
    )
    reviewer_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("platform_users.id"), comment="评审员(第一步)"
    )
    reviewer_opinion: Mapped[str | None] = mapped_column(Text, comment="评审意见")
    reviewer_conclusion: Mapped[str | None] = mapped_column(
        String(20), comment="approve/reject/request_change"
    )
    final_reviewer_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("platform_users.id"), comment="终审人(security_lead)"
    )
    final_opinion: Mapped[str | None] = mapped_column(Text, comment="终审意见")
    final_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, comment="终审时间")
    conclusion_attachments: Mapped[list] = mapped_column(
        JSON, default=list, comment="结论附件路径列表"
    )
    version_hash: Mapped[str | None] = mapped_column(
        String(64), comment="提交时全部交付物的 SHA256 快照"
    )

    project: Mapped["Project"] = relationship(back_populates="review_gates")  # noqa: F821
    evidences: Mapped[list["ReviewEvidence"]] = relationship(
        back_populates="gate", cascade="all, delete-orphan", order_by="ReviewEvidence.id"
    )

    def latest_status_verb(self) -> str:
        """评审记录页展示: 当前推进到哪一步。"""
        if self.status == "passed":
            return "终审通过"
        if self.status == "rejected":
            return "已否决"
        if self.status == "rectifying":
            return "退回整改中"
        if self.reviewer_conclusion == "approve":
            return "评审员已通过, 待负责人终审"
        if self.status == "in_review":
            return "待评审员审核"
        return "待提交"


class ReviewEvidence(Base):
    """评审留痕: 链式哈希防篡改。curr_hash 覆盖前序哈希与本次动作全部字段。"""

    __tablename__ = "review_evidences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    gate_id: Mapped[int] = mapped_column(Integer, ForeignKey("review_gates.id"), index=True)
    actor_id: Mapped[int] = mapped_column(Integer, ForeignKey("platform_users.id"), comment="动作人")
    action: Mapped[str] = mapped_column(String(20), comment="submit/approve/reject/request_change/sign")
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, comment="动作时间")
    ip: Mapped[str | None] = mapped_column(String(64), comment="来源IP")
    comment: Mapped[str | None] = mapped_column(Text, comment="意见/备注")
    payload: Mapped[dict] = mapped_column(JSON, default=dict, comment="动作快照(状态/结论等)")
    prev_hash: Mapped[str] = mapped_column(String(64), comment="前序记录哈希(创世为64个0)")
    curr_hash: Mapped[str] = mapped_column(String(64), comment="本记录哈希")

    gate: Mapped[ReviewGate] = relationship(back_populates="evidences")
