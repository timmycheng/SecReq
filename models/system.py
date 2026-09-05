# -*- coding: utf-8 -*-
"""系统台账: 定级备案(对外备案主体)与被评估系统。

业务层级: 备案(定级事实来源, 少数) → 系统(以备案"子系统"形式存在, 继承备案定级)
→ 项目(一次评估 = 一个时点快照)。#194 起系统承载稳定事实: 基本信息(规模/形态/公网)、
定级(挂靠备案)、基础设施(资产+架构图)与组件(SBOM); 评估轮次只承载
评估过程数据(功能/数据/权限/接口/定级复核), 保证轮次间增量对比不被冗余副本干扰。
"""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
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
    """被评估系统: 稳定事实的单一来源(基本信息/定级/基础设施/组件)。"""

    __tablename__ = "systems"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, comment="系统名称")
    code: Mapped[str | None] = mapped_column(
        String(64), unique=True, comment="系统编号(内部台账编号, 可空)"
    )
    netbox_object_id: Mapped[str | None] = mapped_column(
        String(32), comment="NetBox custom-objects 对象 id(互通推送后回填, #154)"
    )
    filing_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("filings.id"), index=True, comment="所属定级备案(空=未备案)"
    )
    owner_name: Mapped[str | None] = mapped_column(String(50), comment="系统负责人")
    owner_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("platform_users.id"), index=True,
        comment="创建人(数据权限: 开发仅见本人系统)",
    )
    # ── 基本信息(#194 自项目上收; projects 同名列转为已停用的兼容回退) ──
    user_scale: Mapped[str] = mapped_column(
        String(32), default="", comment="用户规模, 见 USER_SCALES(引擎 force_2fa 大规模判定)"
    )
    types: Mapped[list] = mapped_column(JSON, default=list, comment="系统业务形态多选, 见 PROJECT_TYPES")
    is_public: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否涉及公网访问")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    filing: Mapped["Filing | None"] = relationship(back_populates="systems")
    projects: Mapped[list["Project"]] = relationship(back_populates="system")  # noqa: F821
    infra_assets: Mapped[list["InfraAsset"]] = relationship(back_populates="system")  # noqa: F821
    arch_images: Mapped[list["InfraArchImage"]] = relationship(back_populates="system")  # noqa: F821
    components: Mapped[list["SbomComponent"]] = relationship(back_populates="system")  # noqa: F821
