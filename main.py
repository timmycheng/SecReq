# -*- coding: utf-8 -*-
"""FastAPI 应用入口。

启动:
    .venv/Scripts/python -m uvicorn main:app --reload --port 8000

- 数据库默认 sqlite:///<项目根>/secreq.db, 可用环境变量 SECREQ_DATABASE_URL 覆盖;
- API 统一前缀 /api, 前端开发服务器(5173)经 Vite 代理访问, 已放开 CORS;
- 若存在 frontend/dist 生产构建产物, 自动静态托管(单进程部署);
- 启动时自动补齐存量库新列(JR/T 五级改造)并执行老四级数据迁移 + 种子用户写入,
  与 scripts/migrate_classification.py 共用同一实现(services/classification_migration)。
"""
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from models import init_db, make_engine, make_session_factory
from routers import admin, auth, filings, generate, review, meta, netbox, projects, steps, systems
from routers.common import auth_guard

# 统一日志出口: 容器部署时全部走 stdout 便于采集。
# root 已配置过 handler 时 basicConfig 是空操作, 不会覆盖 uvicorn 的日志配置。
logging.basicConfig(
    level=os.environ.get("SECREQ_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("secreq")

ROOT_DIR = Path(__file__).resolve().parent

# 数据库连接: 默认 sqlite:///<项目根>/secreq.db, 容器部署经 SECREQ_DATABASE_URL 指向挂载卷
engine = make_engine()
SessionLocal = make_session_factory(engine)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """建表(幂等) + 存量库升级 + 数据迁移 + 种子用户。"""
    from services.auth_service import ensure_seed_users
    from services.classification_migration import (
        ensure_schema_upgrade, migrate_legacy_classification,
    )
    from services.project_service import assign_legacy_projects, populate_project_types

    init_db(engine)
    ensure_schema_upgrade(engine)
    from services.entity_uid_migration import migrate_entity_uids
    db = SessionLocal()
    try:
        from services.requirement_lifecycle import backfill_review_statuses
        backfilled = backfill_review_statuses(db)
        if backfilled:
            db.commit()
            logger.info("存量需求评审状态已回填(#217): %d 行", backfilled)
        stats = migrate_legacy_classification(db)
        if stats["migrated"]:
            logger.info("老四级分级已迁移为 JR/T 0197 五级: %s", stats)
        uid_stats = migrate_entity_uids(db)
        if uid_stats.get("uid_backfilled") or uid_stats.get("mapped") or uid_stats.get("obsolete"):
            logger.info("实体 uid 迁移(回填/重映射/断链标记): %s", uid_stats)
        ensure_seed_users(db)
        populate_project_types(db)
        moved = assign_legacy_projects(db)
        if moved:
            logger.info("%d 个存量项目已归入默认开发账号", moved)
        # 复制项目组件的漏洞缓存自愈(#169): 带缓存状态却无漏洞记录的组件清缓存,
        # 使其下次生成强制重查(修复已复制出来的受影响项目)
        from services.project_copy import repair_stale_component_cache
        repaired = repair_stale_component_cache(db)
        if repaired:
            logger.info("已修复 %d 个组件的过期漏洞查询缓存(评估继承 #169 自愈)", repaired)
        from routers.admin import _apply_policy_settings
        _apply_policy_settings(db)
    finally:
        db.close()
    _log_vuln_source_status()
    yield


def _log_vuln_source_status() -> None:
    """启动时交代漏洞数据源状态。

    内网部署最常见的事故是"漏洞库忘了挂载", 页面上每个组件都显示无法判定却没人知道原因。
    启动日志里说清楚, 运维一眼能定位。
    """
    from services.vuln_source import VulnSourceUnavailable, describe_sources

    try:
        from services.vuln_source import get_vuln_source
        source, skipped = get_vuln_source()
        if skipped:
            logger.warning("漏洞数据源降级: %s", "; ".join(skipped))
        logger.info("漏洞数据源: %s", source.available()[1])
    except VulnSourceUnavailable:
        logger.error(
            "无可用漏洞数据源, 组件漏洞查询将全部标注为「无法判定」。"
            "内网部署请确认已挂载 vulndb.sqlite, 或调整 SECREQ_VULN_SOURCE"
        )
        for row in describe_sources():
            logger.error("  数据源 %s: 可用=%s, %s", row["code"], row["available"], row["reason"] or "")


app = FastAPI(
    title="安全需求管理平台",
    description="面向开发与安全两角色的安全需求管理平台: JR/T 0197 五级数据分级、"
                "监管合规基线映射、安全需求清单生成与确认",
    version="3.0.0",
    lifespan=lifespan,
    dependencies=[Depends(auth_guard)],  # 全局认证: 开放路径外一律要求登录
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173", "http://127.0.0.1:5173",  # Vite 开发服务器
    ],
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


app.include_router(meta.router)
app.include_router(auth.router)
app.include_router(projects.router)
app.include_router(filings.router)
app.include_router(systems.router)
app.include_router(steps.router)
app.include_router(generate.router)
app.include_router(review.router)
app.include_router(admin.router)
app.include_router(netbox.router)

_dist = ROOT_DIR / "frontend" / "dist"
if _dist.exists():  # 生产构建托管: npm run build 后可直接单进程启动
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="frontend")

    @app.middleware("http")
    async def _html_no_cache(request, call_next):
        """index.html 禁缓存(#228): 版本升级后浏览器必须拿到新 bundle,
        否则缓存的旧 index.html 引用已删除的旧 hash 资源, 表现为页面打不开。"""
        response = await call_next(request)
        if "text/html" in response.headers.get("content-type", ""):
            response.headers["Cache-Control"] = "no-cache"
        return response
