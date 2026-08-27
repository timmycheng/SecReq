# -*- coding: utf-8 -*-
"""FastAPI 应用入口。

启动:
    .venv/Scripts/python -m uvicorn main:app --reload --port 8000

- 数据库默认 sqlite:///<项目根>/secreq.db, 可用环境变量 SECREQ_DATABASE_URL 覆盖;
- API 统一前缀 /api, 前端开发服务器(5173)经 Vite 代理访问, 已放开 CORS;
- 若存在 frontend/dist 生产构建产物, 自动静态托管(单进程部署)。
"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from models import init_db, make_engine, make_session_factory
from routers import generate, meta, projects, steps

ROOT_DIR = Path(__file__).resolve().parent

engine = make_engine(f"sqlite:///{ROOT_DIR / 'secreq.db'}")
SessionLocal = make_session_factory(engine)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """建表(幂等)。"""
    init_db(engine)
    yield


app = FastAPI(
    title="SecReq — 安全需求与设计基线生成工具",
    description="结构化收集项目信息, 规则引擎生成安全需求与设计文档基线",
    version="0.3.0",
    lifespan=lifespan,
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
app.include_router(projects.router)
app.include_router(steps.router)
app.include_router(generate.router)

_dist = ROOT_DIR / "frontend" / "dist"
if _dist.exists():  # 生产构建托管: npm run build 后可直接单进程启动
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="frontend")
