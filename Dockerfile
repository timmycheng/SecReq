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
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SECREQ_DATABASE_URL=sqlite:////app/data/secreq.db

COPY requirements.txt ./
# 先升级工具链: 基础镜像自带的 pip/setuptools 版本较旧, 存在已知漏洞通告
RUN pip install --no-cache-dir --upgrade pip setuptools \
    && pip install --no-cache-dir -r requirements.txt

COPY main.py ./
COPY models/ models/
COPY schemas/ schemas/
COPY routers/ routers/
COPY rules/ rules/
COPY services/ services/
COPY shared/ shared/
COPY scripts/ scripts/
COPY --from=frontend /build/dist/ frontend/dist/

# /app/data 存 SQLite 数据库, /app/output 存生成产物, 均建议挂载卷
RUN mkdir -p /app/data /app/output
VOLUME ["/app/data", "/app/output"]

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)"]

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
