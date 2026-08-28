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
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from models import init_db, make_engine, make_session_factory
from routers import auth, generate, meta, projects, review, steps
from routers.common import auth_guard

ROOT_DIR = Path(__file__).resolve().parent

engine = make_engine(f"sqlite:///{ROOT_DIR / 'secreq.db'}")
SessionLocal = make_session_factory(engine)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """建表(幂等) + 存量库升级 + 数据迁移 + 种子用户。"""
    from services.auth_service import ensure_seed_users
    from services.classification_migration import (
        ensure_schema_upgrade, migrate_legacy_classification,
    )

    init_db(engine)
    ensure_schema_upgrade(engine)
    db = SessionLocal()
    try:
        stats = migrate_legacy_classification(db)
        if stats["migrated"]:
            print(f"[SecReq] 老四级分级已迁移为 JR/T 0197 五级: {stats}")
        ensure_seed_users(db)
    finally:
        db.close()
    yield


app = FastAPI(
    title="SecReq — 安全准入管理平台(需求+设计阶段)",
    description="嵌入行内项目评审流程的安全准入平台: JR/T 0197 五级数据分级、"
                "监管合规基线映射、评审门禁与留痕",
    version="1.0.0",
    lifespan=lifespan,
    dependencies=[Depends(auth_guard)],  # 全局 RBAC: 业务写接口需身份, 审计角色只读
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

engine = make_engine(f"sqlite:///{ROOT_DIR / 'secreq.db'}")
SessionLocal = make_session_factory(engine)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


app.include_router(meta.router)
app.include_router(auth.router)
app.include_router(projects.router)
app.include_router(steps.router)
app.include_router(generate.router)
app.include_router(review.router)

_dist = ROOT_DIR / "frontend" / "dist"
if _dist.exists():  # 生产构建托管: npm run build 后可直接单进程启动
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="frontend")
