# -*- coding: utf-8 -*-
"""平台审计日志(走查整改: 系统自身安全功能到位)。"""
from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from models.database import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), index=True, comment="操作人")
    action: Mapped[str] = mapped_column(String(50), index=True, comment="login/generate/confirm/kb_update/...")
    detail: Mapped[dict] = mapped_column(JSON, default=dict, comment="动作明细")
    ip: Mapped[str | None] = mapped_column(String(64), comment="来源IP")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
