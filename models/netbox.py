# -*- coding: utf-8 -*-
"""NetBox 同步日志(#271): ETL 同步作为后台任务, 每次执行留一条可追溯记录。

同步方向是单向推送(SecReq → NetBox), NetBox 只是后备资产库;
失败不回滚业务数据, 每轮同步的逐条错误明细落在 errors JSON 里供管理端展开查看。
"""
from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from models.database import Base


class NetboxSyncLog(Base):
    """一轮 NetBox 同步的执行记录(append-only)。"""

    __tablename__ = "netbox_sync_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trigger: Mapped[str] = mapped_column(String(20), comment="触发方式: manual / scheduled")
    status: Mapped[str] = mapped_column(
        String(20), default="running", comment="running / success / partial / failed")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    stats: Mapped[dict] = mapped_column(
        JSON, default=dict,
        comment="分类统计: {systems: {created,updated,skipped,failed}, devices: {...}, ips: {...}}")
    errors: Mapped[list] = mapped_column(
        JSON, default=list, comment="逐条失败明细(对象名 + 可读原因), 不中断整轮同步")
