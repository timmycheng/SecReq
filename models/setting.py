# -*- coding: utf-8 -*-
"""系统级键值设置(知识库外的可配置项: LLM 接入、策略基线等)。"""
from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from models.database import Base


class SystemSetting(Base):
    __tablename__ = "system_settings"
    __table_args__ = (UniqueConstraint("key", name="uq_setting_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(100), comment="设置键, 如 llm")
    value: Mapped[dict] = mapped_column(JSON, default=dict, comment="设置值(JSON)")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)
