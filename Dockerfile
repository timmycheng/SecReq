# syntax=docker/dockerfile:1

# ── 阶段一: 前端构建(React 19 + Vite, 产物由 FastAPI 单进程托管) ──────────
FROM node:22-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ── 阶段二: 运行镜像 ────────────────────────────────────────────────────────
FROM python:3.12-slim
WORKDIR /app

# 时区: slim 镜像不保证自带 tzdata, 缺了 TZ 环境变量不生效,
# 会导致确认时间/审计时间/导出时间整体按 UTC 显示(差 8 小时)
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai \
    SECREQ_DATABASE_URL=sqlite:////app/data/secreq.db

# 依赖安装: uv 按锁文件精确复现依赖树(#68), 任何时点构建结果一致。
# uv 大版本与 CI 的 setup-uv 保持一致; pytest 在 dev 组, --no-dev 不进运行镜像;
# cache mount 只加速重复构建, 不会把缓存带进镜像层。
# uv sync 不支持 --system(uv 0.7 实测): 走标准 venv, PATH 指向 venv 的解释器。
ENV UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"
COPY --from=ghcr.io/astral-sh/uv:0.7 /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

COPY main.py ./
# 更新日志页数据源(#55); 文件缺失时接口返回空列表兜底
COPY CHANGELOG.md ./
COPY models/ models/
COPY schemas/ schemas/
COPY routers/ routers/
COPY rules/ rules/
COPY services/ services/
COPY shared/ shared/
COPY scripts/ scripts/
COPY --from=frontend /build/dist/ frontend/dist/

# ── 阶段三: 漏洞库基线(可选) ────────────────────────────────────────────────
# 由 CI 用 oras 拉取基线库后放入构建上下文; 未拉取到时 CI 会放一个空文件占位,
# 应用识别为"无漏洞库", 漏洞查询标注「无法判定」而非「未发现漏洞」。
#
# 内置的是**基线库**而非完整库: 完整库走 docker-compose 挂载覆盖, 日常更新
# 只替换文件 + 重启容器, 不必重建镜像走内网镜像入库流程(紧急漏洞分钟级生效)。
COPY vulndb.sqlite* /app/data/

# /app/data 存 SQLite 数据库与漏洞库, /app/output 存生成产物, 均建议挂载卷
RUN mkdir -p /app/data /app/output
VOLUME ["/app/data", "/app/output"]
ENV SECREQ_DATA_DIR=/app/data

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)"]

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
