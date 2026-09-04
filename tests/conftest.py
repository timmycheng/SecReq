# -*- coding: utf-8 -*-
"""pytest 公共夹具: 内存库会话 + 小型场景构造器。"""
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from models import (
    Project, System, init_db, make_engine,
)
from rules import RuleEngine


@pytest.fixture(scope="session")
def engine():
    """整个会话共享一个 RuleEngine(知识库 YAML 只解析一次, ~44ms/次)。

    共享安全性: generate() 入口即重置 self.skipped(rules/engine.py),
    _handlers 为静态映射, 用例对 fixture 只调 generate() 与读 skipped,
    无跨用例累积状态; 需要注入坏模板的容错用例自建引擎, 不用本 fixture。
    """
    return RuleEngine.load()


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
    """最小可用项目(无任何子数据, 已挂靠系统), 用例按需补充维度输入。

    #194 起评估强制挂靠系统(基本信息/基础设施/组件都在系统上), 夹具同步:
    系统携带默认规模, 组件/基础设施用例以 project.system_id 归属。
    """
    n = session.query(System).count() + 1
    system = System(name=f"测试系统{n:02d}", user_scale="1k_to_100k", is_public=False)
    session.add(system)
    session.flush()
    project = Project(
        name="测试项目", code="PRJ-T001", type="web",
        deploy_env=["private_cloud"], system_id=system.id,
    )
    session.add(project)
    session.flush()
    return project


def create_system_api(client, name: str) -> dict:
    """经 API 建一个系统(挂靠系统是写清单类用例的前置, #194)。"""
    resp = client.post("/api/systems", json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()


def gen_for(session, project, engine):
    """flush 后针对指定项目执行规则引擎的统一辅助入口。"""
    from rules.context import RequirementContext
    session.flush()
    return engine.generate(RequirementContext.from_db(session, project.id))


def cleanup_output(code: str) -> None:
    """删除仓库根 output/<code> 产物目录(生成/导出用例的兜底清理)。"""
    out_dir = Path(__file__).resolve().parent.parent / "output" / code
    shutil.rmtree(out_dir, ignore_errors=True)


def demo_features():
    """三条标准功能种子(登录/转账/账单查询): uid 稳定性与轮次继承测试共用。"""
    from schemas.feature import FeatureIn
    return [
        FeatureIn(name="登录", module="用户中心", categories=["auth_login"]),
        FeatureIn(name="转账", module="支付模块", categories=["payment"],
                  sensitivity="confidential", involves_payment=True),
        FeatureIn(name="账单查询", module="支付模块", categories=["search"]),
    ]


# ── 第三批: API 层公共夹具 ──────────────────────────────


@pytest.fixture()
def api(tmp_path):
    """TestClient + 独立内存库(覆盖 get_db), 不触碰根目录 secreq.db。

    TestClient 在独立线程执行请求, 内存库须用 StaticPool 共享单连接,
    否则每个线程各见一个空库。
    默认身份为开发 dev_admin(存量用例的写操作均以其执行);
    需要其他身份时用 api_as(api, "sec_admin") 取对应身份的客户端。
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    import main
    from models import init_db
    from routers.common import get_db
    from services.auth_service import ensure_seed_users

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_db(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    seed_session = TestingSession()
    ensure_seed_users(seed_session)
    seed_session.close()

    def _override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    main.app.dependency_overrides[get_db] = _override_get_db
    client = login_as(TestClient(main.app), "dev_admin")
    yield client
    main.app.dependency_overrides.clear()


def login_as(client: TestClient, username: str) -> TestClient:
    """以种子默认密码登录并携带 Bearer token 的新 TestClient(共享同一测试库)。"""
    from services.auth_service import SEED_DEFAULT_PASSWORD

    resp = client.post(
        "/api/auth/login",
        json={"username": username, "password": SEED_DEFAULT_PASSWORD},
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["token"]
    return TestClient(client.app, headers={"Authorization": f"Bearer {token}"})


def api_as(api, username: str):
    """以指定平台用户身份发起请求的 TestClient(共享同一测试库)。"""
    return login_as(TestClient(api.app), username)
