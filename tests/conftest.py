# -*- coding: utf-8 -*-
"""pytest 公共夹具: 内存库会话 + 小型场景构造器。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from sqlalchemy.orm import sessionmaker

from models import (
    ApiEndpoint, AuthConfig, DataAsset, DataField, DataTable, Feature,
    GradingSurvey, PermissionEntry, Project, Resource, Role, SbomComponent,
    VulnerabilityRecord, init_db, make_engine,
)
from rules import RuleEngine


@pytest.fixture()
def session():
    """每个用例独立的内存数据库会话。"""
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db = factory()
    yield db
    db.close()


def add_base_project(session) -> Project:
    """最小可用项目(无任何子数据), 用例按需补充维度输入。"""
    project = Project(
        name="测试项目", code="PRJ-T001", type="web",
        user_scale="1k_to_100k", deploy_env=["private_cloud"], is_public=False,
    )
    session.add(project)
    session.flush()
    return project


def gen_for(session, project, engine):
    """flush 后针对指定项目执行规则引擎的统一辅助入口。"""
    from rules.context import RequirementContext
    session.flush()
    return engine.generate(RequirementContext.from_db(session, project.id))


# ── 第三批: API 层公共夹具 ──────────────────────────────
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def api(tmp_path):
    """TestClient + 独立内存库(覆盖 get_db), 不触碰根目录 secreq.db。

    TestClient 在独立线程执行请求, 内存库须用 StaticPool 共享单连接,
    否则每个线程各见一个空库。
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    import main
    from models import init_db
    from routers.common import get_db

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_db(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def _override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    main.app.dependency_overrides[get_db] = _override_get_db
    client = TestClient(main.app)
    yield client
    main.app.dependency_overrides.clear()
