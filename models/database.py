# -*- coding: utf-8 -*-
"""数据库基础设施: 引擎/会话工厂/声明基类。

SQLite 开发, 模型全部使用可移植类型(JSON 代替 ARRAY), 兼容 PostgreSQL 迁移。
"""
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    """全项目 ORM 声明基类。"""


def _sqlite_kwargs() -> dict:
    """SQLite 连接参数: 关闭同线程检查, 复用单连接(配合内存库测试)。"""
    return {"connect_args": {"check_same_thread": False}, "poolclass": None}


def make_engine(url: str | None = None):
    """创建 SQLAlchemy 引擎。默认 sqlite:///./secreq.db, 可用环境变量覆盖。"""
    url = url or os.environ.get("SECREQ_DATABASE_URL", "sqlite:///./secreq.db")
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False})
    # PostgreSQL 等其他库使用默认连接池
    return create_engine(url, pool_pre_ping=True)


def make_session_factory(engine) -> sessionmaker:
    """构建会话工厂。"""
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db(engine) -> None:
    """按当前模型注册表建表(开发模式用)。"""
    # 确保所有模型模块已被导入注册到 Base.metadata
    import models  # noqa: F401
    Base.metadata.create_all(engine)
