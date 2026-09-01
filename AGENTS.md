# AGENTS.md — 仓库协作约定(对人与 Agent 均生效)

## 项目速览(架构索引)

给新会话与新人的背景索引, 一次沉淀、免重复探索; 架构有变时顺手更新本节, 事实陈述避免会漂移的细节(如 Tab 数量、版本号)。

- 后端 FastAPI 在仓库根: 入口 `main.py`(FastAPI `version` 字段在此, 仅发版时改), 分层 `routers/`(API)→ `services/`(业务)→ `models/`(ORM)→ `schemas/`、`shared/`(常量)、`rules/`(知识库与规则引擎); 默认库 SQLite `secreq.db`, 可用 `SECREQ_DATABASE_URL` 覆盖。
- 前端在 `frontend/`: React 19 + TypeScript + Vite + antd 6; **无路由库**, 自研 hash 路由 `frontend/src/router.ts`, 侧边菜单硬编码在 `frontend/src/App.tsx`; API 层是单文件 `frontend/src/api.ts`(`request<T>()` 统一携带 Bearer)。
- 系统管理(仅安全角色)是单页 Tabs: 外壳 `frontend/src/ui/AdminPage.tsx`, 各 Tab 组件在 `frontend/src/ui/admin/`(React.lazy 按需加载)。新增一个 Tab = admin/ 下新组件 + AdminPage 注册 + `api.ts` 加方法 + `routers/admin.py` 加端点(挂 `Depends(require_security)`), 前端没有权限注册步骤。
- 平台鉴权只有二元角色 developer/security, 无权限点/权限表(`models/permission.py` 是项目内"权限矩阵"设计器的产物, 不是平台 RBAC); 全局 auth_guard 挂在 `main.py`, 开放前缀与 `require_login`/`require_write_roles` 在 `routers/common.py`。
- `CHANGELOG.md` 版本章节格式 `## [X.Y.Z] - YYYY-MM-DD`(无 v 前缀), 与 `main.py` version、`pyproject.toml` version、git tag 四者由 `scripts/check_version.py` 校验一致; 版本章节在打 tag 发版时一并更新(见 dev-workflow「版本与发版」清单)。
- 质量门禁本地命令: `uv run pytest tests -q`、`uv run ruff check .`、`cd frontend && npm run lint && npm run build`(build 含 tsc 类型检查); 后端依赖经 uv 锁定(`pyproject.toml` 声明 + `uv.lock` 锁树入库, 改声明必须 `uv lock` 连锁文件一起提交), 测试夹具在 `tests/conftest.py`: `api` 默认开发身份, `api_as(api, "sec_admin")` 切安全身份。
- 部署: Dockerfile 多阶段构建, 前端产物由 FastAPI 单进程托管, 数据/产物走 `/app/data`、`/app/output` 卷; 依赖仓库根静态文件的功能要注意该文件是否 COPY 进了镜像(如 CHANGELOG.md 目前没有)。

## 开发流程(硬性约定)

本仓库所有改动一律走 GitHub 标准流程, **禁止直推 main**(分支保护对管理员同样生效):先开 issue(模板 + `type:`/`priority:` 标签, 版本批次挂对应 milestone)→ 从最新 main 切分支, 命名 `<type>/<issue号>-<slug>`(如 `fix/18-schema-upgrade`)→ 提交与 PR 标题用约定式前缀 + 中文描述(如 `fix(认证): 初始密码环境变量化`)→ PR 正文写 `Closes #N` → 等 CI 三个 job(后端测试 / 后端 Lint / 前端检查)全绿后 squash 合并。

发版仅由 tag 触发:打 tag 前必须跑 `python scripts/check_version.py vX.Y.Z`, 保证 tag、`main.py` 的 version、`pyproject.toml` 的 version、CHANGELOG 章节四者一致;版本批次以 milestone 管理,milestone 全部关闭才具备发版条件。

**完整细则以 [docs/dev-workflow.md](docs/dev-workflow.md) 为唯一权威来源**(issue/分支/提交/PR/CI/发版/依赖更新的全部规则),执行流程前先读它;CI 红了看日志修复,不绕过门禁。

## Markdown 排版

写入本仓库的 Markdown 文档(CHANGELOG.md、docs/、README.md 等),正文**一条/一段独占一行**,不做段内硬换行;长段落由编辑器软换行,不要手动在固定列宽处折行。

原因:CHANGELOG.md 的对应版本章节会被 `.github/workflows/release.yml` 原样抽取为 GitHub Release 正文,而 GitHub Release 页把段内单个换行渲染成真实断行,中文句子会在任意词组处被切断(仓库的文件视图会合并软换行,所以只有 Release 页暴露此问题)。

不受此约束的内容:表格行、列表的每个条目、代码块内部、标题。
