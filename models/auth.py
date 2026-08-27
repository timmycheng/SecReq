# -*- coding: utf-8 -*-
"""Step6 身份认证与密码/会话策略(与项目一对一)。"""
from sqlalchemy import Boolean, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.database import Base
from models.project import Project


class AuthConfig(Base):
    """认证方式与密码策略设计器输出。

    各策略字段允许为空: 引擎按定级推导默认值(shared.constants.DEFAULT_PWD_POLICY_BY_LEVEL)。
    """

    __tablename__ = "auth_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id"), unique=True, index=True
    )
    auth_methods: Mapped[list] = mapped_column(JSON, default=list, comment="认证方式多选, 见 AUTH_METHODS")
    pwd_min_length: Mapped[int | None] = mapped_column(Integer, comment="最小长度")
    pwd_complexity: Mapped[int | None] = mapped_column(Integer, comment="复杂度类别数(3或4)")
    pwd_valid_days: Mapped[int | None] = mapped_column(Integer, comment="有效期天数")
    lockout_threshold: Mapped[int | None] = mapped_column(Integer, comment="错误锁定阈值(次)")
    pwd_history_limit: Mapped[int | None] = mapped_column(Integer, comment="历史密码重复限制(次)")
    force_2fa: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否强制2FA")
    session_timeout_min: Mapped[int | None] = mapped_column(Integer, comment="会话超时(分钟)")
    concurrent_limit: Mapped[int | None] = mapped_column(Integer, comment="单点登录并发限制")

    project: Mapped[Project] = relationship(back_populates="auth_config")
