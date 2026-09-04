# -*- coding: utf-8 -*-
"""系统台账: 定级备案(对外备案主体)与被评估系统。

业务层级: 备案(定级事实来源, 少数) → 系统(以备案"子系统"形式存在, 继承备案定级)
→ 项目(一次评估 = 一个时点快照)。会变化的信息(基础设施/数据字典等)留在项目轮次内,
系统与备案只承载身份与定级事实, 保证轮次间增量对比与历史报告输入不被就地污染。
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.database import Base


class Filing(Base):
    """等保定级备案主体: 对外备案与测评的对象, 全库仅少数几条。"""

    __tablename__ = "filings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, comment="备案名称")
    code: Mapped[str | None] = mapped_column(
        String(64), unique=True, comment="备案编号(备案证明上的编号, 可空)"
    )
    level: Mapped[str] = mapped_column(String(10), comment="备案定级, 见 GRADING_LEVELS")
    note: Mapped[str | None] = mapped_column(Text, comment="备注(如备案日期/测评机构)")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    systems: Mapped[list["System"]] = relationship(back_populates="filing")


class System(Base):
    """被评估系统: 实际业务系统以某备案"子系统"形式归属备案; 项目挂系统之下。"""

    __tablename__ = "systems"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, comment="系统名称")
    code: Mapped[str | None] = mapped_column(
        String(64), unique=True, comment="系统编号(内部台账编号, 可空)"
    )
    filing_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("filings.id"), index=True, comment="所属定级备案(空=未备案)"
    )
    owner_name: Mapped[str | None] = mapped_column(String(50), comment="系统负责人")
    owner_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("platform_users.id"), index=True,
        comment="创建人(数据权限: 开发仅见本人系统)",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    filing: Mapped["Filing | None"] = relationship(back_populates="systems")
    projects: Mapped[list["Project"]] = relationship(back_populates="system")  # noqa: F821
