# -*- coding: utf-8 -*-
"""步骤级耗时埋点(#229): 试点汇报用数据, 判断 45 分钟红线达成度。

埋点口径: 前端在「保存并下一步」成功时上报本步停留秒数(duration_seconds),
后端落库 projects/step/操作人/耗时; 择后端记录而非前端打点上传第三方,
内网友好零外部依赖。写场景只有向导保存端点一处触发, 对填报性能无可感知影响。
"""
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from models.database import Base


class StepDuration(Base):
    """步骤耗时记录: 每次成功保存一步一条。"""

    __tablename__ = "step_durations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id"), index=True)
    system_id: Mapped[int | None] = mapped_column(
        Integer, index=True, comment="所属系统(按系统/轮次聚合用)")
    step: Mapped[str] = mapped_column(String(40), comment="步骤 code, 见向导 STEPS")
    duration_seconds: Mapped[float] = mapped_column(Float, comment="本步停留秒数")
    operator_name: Mapped[str | None] = mapped_column(String(50), comment="填报人姓名")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, comment="保存完成时间")
