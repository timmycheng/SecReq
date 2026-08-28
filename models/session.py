# -*- coding: utf-8 -*-
"""登录会话: Bearer token → 用户的映射, 服务端可吊销。"""
from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from models.database import Base


class UserSession(Base):
    """一次登录一条记录; 库存 sha256(token), 明文 token 只出现在响应里。"""

    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, comment="sha256(token)")
    username: Mapped[str] = mapped_column(String(50), index=True, comment="登录名")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    expires_at: Mapped[datetime] = mapped_column(DateTime, comment="过期时间")
    ip: Mapped[str | None] = mapped_column(String(64), comment="登录来源IP")
