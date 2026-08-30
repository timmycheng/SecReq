# -*- coding: utf-8 -*-
"""数据库基础设施: 引擎/会话工厂/声明基类。

SQLite 开发, 模型全部使用可移植类型(JSON 代替 ARRAY), 兼容 PostgreSQL 迁移。
"""
import os

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    """全项目 ORM 声明基类。"""


@event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):  # noqa: ARG001
    """SQLite 连接级 PRAGMA(非 SQLite 连接直接跳过)。

    默认 rollback journal 模式下读阻塞写、写阻塞读; 而向导保存是整表
    delete+insert 的大事务, 几个用户并发点保存就会抛 "database is locked"。
    - journal_mode=WAL   读写不互斥
    - busy_timeout=5000  锁等待 5s 而非立即报错
    - synchronous=NORMAL WAL 模式下的合理选择
    """
    if dbapi_connection.__class__.__module__.split(".")[0] != "sqlite3":
        return
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA synchronous=NORMAL")
    finally:
        cursor.close()


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
