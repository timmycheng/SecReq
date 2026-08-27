# -*- coding: utf-8 -*-
"""Step3 功能清单模型。"""
from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.database import Base
from models.project import Project


class Feature(Base):
    """功能条目。categories 为受控枚举多选(FEATURE_CATEGORIES), 规则引擎按交集匹配。"""

    __tablename__ = "features"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(200), comment="功能名称")
    module: Mapped[str | None] = mapped_column(String(100), comment="所属模块")
    categories: Mapped[list] = mapped_column(JSON, default=list, comment="功能分类 code 列表")
    sensitivity: Mapped[str] = mapped_column(String(20), default="internal", comment="敏感级别")
    involves_payment: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否涉及资金")
    exposed_to_internet: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否公网暴露")

    project: Mapped[Project] = relationship(back_populates="features")

    def matches_any_category(self, category: str) -> bool:
        return category in (self.categories or [])
