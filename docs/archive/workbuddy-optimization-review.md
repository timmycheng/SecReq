# SecReq v2.1.2 优化评审

评审时间: 2026-08-30 · 评审范围: 后端全量(models/routers/services/rules) + 前端 26 文件 5237 行
基线: `pytest tests -q` → 137 passed / 1 failed(环境问题, 见附录)

分级说明: P0 = 会造成数据错误或生产事故; P1 = 架构与运维风险; P2 = 代码质量与安全加固。

---

## P0-1 重新生成会清空全部确认记录

**位置**: `rules/engine.py:169-175` `generate_and_save`

```python
session.query(SecurityRequirement).filter_by(project_id=ctx.project.id).delete()
requirements = self.generate(ctx)
```

先全删再全插, 新记录的 `reg_confirmed=False / confirmed_by=None / confirmed_at=None`。

**触发场景**: 安全人员在产物页批量确认 40 条 → 开发回到 Step3 补一个功能 → 重新生成 → 40 条确认全部归零。

**修法**: 改成按 `(project_id, template_id, source_entity_id)` 的 upsert。已存在的记录只更新
title/description/priority 等派生字段, 保留 `reg_confirmed/confirmed_by/confirmed_at`;
新增的置 False; 本轮未再命中的不要硬删, 标记 `status="obsolete"` 留档(也便于统计"整改后消失的风险")。

---

## P0-2 向导"整表替换"使需求溯源 ID 失效

**位置**: `services/step_store.py:25-241`

`replace_features / replace_data_assets / replace_api_endpoints / replace_components /
replace_infra_assets / replace_external_systems` 全部是 `delete-all + insert-all`, 主键自增 ID 全部变化。
而 `SecurityRequirement.source_entity_id` 存的就是这些表的主键。

**后果**: 生成需求后再修改任一步骤, 已有需求的 `source_label` 与实际实体对不上,
再次生成时 `trigger_reason` 会指向完全不相干的实体。这直接削弱了"每条需求可追溯到输入"这一核心卖点。

**修法(推荐顺序)**:
1. 给各实体表加稳定业务键(如 `uid` UUID 或 `name+version` 的自然键), 需求表关联业务键而非自增主键;
2. 或把 replace_* 改成 diff upsert —— 按业务键比对, 未变更的行保留原主键, 只增删改差异部分;
3. 退一步的兜底: 保存步骤时若该项目已有生成记录, 提示用户"修改后需重新生成, 已确认状态将保留/失效"。

---

## P0-3 OSV 串行同步会占满线程池

**位置**: `services/osv.py:326-346` + `routers/generate.py:92`

`sync_vulnerabilities` 对每个组件**串行**发一个 HTTP 请求, 单请求 timeout 10s。30 个组件最坏 300s。
路由声明为 `def`(非 async), FastAPI 会丢进默认 40 线程的线程池; Docker 里是单 uvicorn worker。

**后果**: 几个人同时点"生成安全基线", 线程池即被打满, **整个服务包括登录页全部无响应**。

**修法**:
- 首选: `OsvClient` 改用 `httpx.AsyncClient`, 路由改 `async def`, 用 `asyncio.gather`
  配 `asyncio.Semaphore(5~10)` 并发(限流保护 OSV.dev, 别把对方打爆);
- 或: 生成任务丢 BackgroundTasks / 独立 worker, 前端轮询进度或走 SSE;
- 无论哪种, 建议给整轮同步加总超时(如 60s), 超时即降级, 不要让单个请求拖死整个流程。

---

## P1-1 没有数据库迁移工具

`init_db(create_all)` + 手写 `ensure_schema_upgrade` 补列。能跑, 但无法回滚、无法审计变更、
多环境一致性靠运气。README 明确写了可指向 PostgreSQL —— 一上 PG, `create_all` 不会补齐后续的结构变更。

**建议**: 引入 Alembic, 把 `ensure_schema_upgrade` 里的补列逻辑迁成正式 revision,
启动时只保留"若非最新版本则告警"而不自动 DDL。

---

## P1-2 SQLite 未开 WAL, 并发写会锁死

**位置**: `models/database.py:21-27`

只设了 `check_same_thread: False`, 未配置任何 PRAGMA。默认 rollback journal 模式下
"读阻塞写、写阻塞读"; 而向导保存是整表 delete+insert 的大事务, 几个用户并发点保存就会
`database is locked`。

**建议**: 加 SQLAlchemy event listener:
`PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000; PRAGMA synchronous=NORMAL;`。
多人使用还是推 PostgreSQL(README 已留 `SECREQ_DATABASE_URL` 口子)。

顺带: `models/database.py:16-18` 的 `_sqlite_kwargs()` 是死代码(从未被调用), 删掉。

---

## P1-3 依赖未锁版本, 镜像不可复现

`requirements.txt` 全是 `>=`。今天 build 与三个月后 build 的依赖树可能完全不同,
某个大版本 breaking 就会让 CI 莫名变红。

**建议**: `pip-compile` 生成 `requirements.lock`(或用 uv / poetry), Dockerfile 装锁文件。
前端这块是对的 —— 有 `package-lock.json` 且 Dockerfile 用 `npm ci`。

---

## P2-1 内部异常细节直接回显给客户端

- `routers/generate.py:105-106`: `raise HTTPException(500, f"生成失败: {exc}")` —— 会把 SQL 语句、
  文件路径、知识库结构等内部信息吐给前端。
- `routers/steps.py:233`: `f"Excel 解析失败: {exc}"` 同理。

**建议**: 服务端 `logger.exception(...)` 记录完整栈, 对客户端只回通用文案 + 一个 trace_id 便于排查。

---

## P2-2 规则引擎两处可维护性债务

1. **热路径上的线性扫描**: `rules/context.py:102-110` 的 `resource_by_id / role_actions_on /
   entries_of_role`, 以及 `rules/engine.py:135-167` 的 `_source_label`, 都用 `next(生成器)` 线性查找。
   `_source_label` 对**每条**需求调用一次 → O(需求数 × 实体数)。61 个模板多实例命中,
   项目一大就是几万次无用遍历。在 `RequirementContext` 里预建 `{id: entity}` 字典即可, 几行代码。

2. **`saas_finance` 是个定时炸弹**: `rules/engine.py:476` 的 docstring 声明了该报送规则,
   但 `_match_regulatory_triggers` 里没有对应分支 → 命中即 `raise RuleEngineError`, 整个生成 500。
   当前 61 条模板未用到(所以现在不炸), 但只要有人在管理页按文档建一个就会炸。
   要么补实现, 要么删文档。

3. `_match_regulatory_triggers` 是 8 个 `if key == ...` 的长链, 而同文件 `_handlers`
   已经是注册表模式了 —— 统一一下更好维护。

---

## P2-3 文件上传无大小限制

`routers/steps.py:221` 与 `routers/steps.py:334` 直接 `await file.read()` 载入内存,
文本长度校验发生在读取**之后**。建议加 Starlette 的 `max_upload_size` 中间件,
或流式读取并限流。

---

## P2-4 审计日志覆盖不全

目前覆盖: generate / confirm / batch_confirm / kb_* / user_* / policy / llm。
缺失: **登录失败、项目删除、导出下载(Word/Excel 数据外带)、组件清单变更**。

这是个安全合规产品, 审计完整性就是门面。建议至少补上"项目删除"与"导出下载"。

---

## P2-5 前端工程化

- **组件粒度偏粗**: `Step4DataAssets.tsx` 536 行、 `AdminPage.tsx` 527 行、
  `Step1ProjectInfo.tsx` 471 行。没有任何状态管理(WizardPage 靠 props/callback 层层传递)。
  建议按"表单区 / 列表区 / 弹窗区"拆子组件, 并充分利用 AntD Form 的校验与联动。
- **无代码分割**: 首屏要加载完整 AntD + React 19。建议在 vite 配 `manualChunks` 拆 antd,
  或用 `React.lazy` 按页加载。
- **CI 只覆盖后端**: `.github/workflows/release.yml` 仅在 push tag 时跑 pytest + 构建镜像。
  建议补 PR 触发的 CI(主要分支): `pytest` + `oxlint` + `tsc -b` + 前端 build。
- **无 e2e 测试**: 8 步向导的回归目前靠手点。Playwright 覆盖"建项目→走完向导→生成→确认"
  这条主链路的投入产出比很高。

---

## 其他小项

- **API 无版本前缀**: `/api/...` 建议加 `/api/v1`, 否则以后改契约很痛。
- **静态资源不鉴权**: `app.mount` 的 `Mount` 不是 `APIRoute`, 不受 app 级
  `dependencies=[Depends(auth_guard)]` 约束 —— 前端代码包对匿名访客可见。
  这对登录页是必要放行(否则页面都加载不了), 但需知晓这个边界。
- **遗留表 `models/review.py`**: README 自述为遗留, `gate_type` 枚举与 `ReviewGate` 表在路线图里。
  要么用起来, 要么删掉减少认知负担。
- **前端缺 401 兜底**: `api.ts` 的 401 广播只覆盖 fetch 请求, 静态资源不走 fetch。
  未登录直接访问深层路由时不会跳登录页(会由 SPA 路由接管, 需确认行为符合预期)。

---

## 做得好的地方(别改)

- **`shared/constants.py` 单一枚举源** + `/api/meta/constants` 供前端 —— 前后端枚举不会漂移, 这是对的。
- **占位符渲染的白名单实现**(`rules/engine.py:36-49`): 只匹配 `{{word}}`、查字典、字面插入,
  不走 `str.format` / Jinja, 天然免疫 SSTI。注释还专门写明了这个安全口径, 很好。
- **数据权限统一收口在 `routers/common.py`**, 越权一律 404 不泄露存在性, 没有散落在各路由里。
- **YAML 写回带自动备份 + 全量校验 + 失败回滚**(`services/kb_admin.py`), 管理端改知识库不怕改坏。
- **OSV 的多坐标过滤**(`services/osv.py:201-226`): 精确 purl → 全限定名 → 裸名 → 兜底,
  能挡住 guicedee/pax-logging 这类派生包污染。这块想得很细。
- **初始密码环境变量化 + 随机回退**, 源码内无固定口令。

---

## 附录: 测试基线

```
137 passed, 1 failed, 3 warnings in 12.63s
FAILED tests/test_sbom.py::test_write_cyclonedx_file_keeps_utf8_chinese - OSError
```

唯一失败项是沙箱环境无法清理 pytest 临时目录导致的(`[safe-delete] windows-sandbox-recycle-bin-unavailable`),
非代码缺陷, 正常环境下应通过。

另有一条 `StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated;
install httpx2 instead` —— 升级 httpx 时需留意 `TestClient` 的兼容变化。

---

## 附录: 核实结论 (2026-08-30)

以上全部论断已逐条对照代码验证: **仅 1 处与代码不符、1 处程度夸大, 其余全部属实**。
处理决定: 暂不修复, 结论归档备用; `IMPLEMENTATION_PLAN.md` 五阶段方案经核实技术路线无误, 保留待用。

### 与代码不符的 1 处

- **P2-4 "缺失登录失败审计"不成立**: `routers/auth.py:48` 已有 `audit(db, username, "login_failed", ...)` 埋点。
  但该项其余缺口确认属实: 项目删除(`routers/projects.py:79` DELETE 无审计)、
  导出下载(`routers/generate.py` export_docx/export_xlsx 均无审计)、组件清单变更(`routers/steps.py` 全文件无审计)。

### 程度夸大的 1 处

- **P0-3 "线程池打满、登录页全挂"**: 默认线程池 40 线程, 需约 40 个并发生成请求才能占满。
  但风险本身真实且更隐蔽——`sync_vulnerabilities` 串行查询期间 Session 持有 SQLite 读事务,
  而项目未配置 `busy_timeout`(默认 0 即立即失败), 一个 30 组件的生成请求即可令其他用户的写操作报
  `database is locked`。P0-3 与 P1-2 是叠加放大关系, 修复时应一并处理。

### 依赖关系提醒

- **P0-1 依赖 P0-2**: 不引入稳定 uid 前, P0-1 的 upsert 只能按 `(template_id, source_entity_id)` 匹配;
  步骤一经修改实体 id 即变, 匹配失效、确认状态照样丢失。轻量版仅保护"未改步骤直接重新生成"场景
  (如 OSV 数据刷新后重跑), 完整解法必须先做 P0-2 的 uid 迁移。

### 逐项验证证据

| 评审项 | 结论 | 关键证据 |
| ------ | ---- | -------- |
| P0-1 重新生成清空确认 | 属实 | `rules/engine.py:171` 先全删再生成; 新记录 `reg_confirmed=False`(`rules/engine.py:130`) |
| P0-2 整表替换断溯源 | 属实 | 7 个 `replace_*` 均删除重建(`services/step_store.py`); 最实锤: `ApiEndpoint.sensitive_asset_ids` 存 DataAsset 自增 id(`step_store.py:221`), 数据字典重存后静默断链, 重新生成也无法修复 |
| P0-3 OSV 串行阻塞 | 方向属实 | `services/osv.py:326` 串行循环、timeout 10s(:78); `routers/generate.py:93` 同步 def; Dockerfile CMD 单 worker |
| P1-1 无迁移工具 | 属实 | 仅 `init_db(create_all)` + `services/classification_migration.py` 手写补列; 全仓库无 Alembic |
| P1-2 SQLite 无 PRAGMA | 属实 | `models/database.py:21-27` 仅 check_same_thread; `_sqlite_kwargs`(:16-18)无任何调用方, 确认死代码 |
| P1-3 依赖未锁 | 属实 | `requirements.txt` 全 `>=`; 前端已用 `package-lock.json` + `npm ci`(Dockerfile:6-7) |
| P2-1 异常回显 | 属实 | `routers/generate.py:106` `f"生成失败: {exc}"` 进 500 响应; `routers/steps.py:233` 较轻(用户自己文件的解析错误) |
| P2-2a 线性扫描 | 属实 | `_source_label`(`rules/engine.py:135-167`)每条需求线性扫描; `_scan_sod_conflict` 为 O(角色×资源×条目) |
| P2-2b saas_finance | 属实 | 全仓库仅 `rules/engine.py:476` docstring 提到; 61 条模板(已清点)未使用; 命中即 `raise RuleEngineError`(:549) → 生成 500 |
| P2-3 上传无大小限制 | 属实 | `routers/steps.py:228`、`:341` 先 `await file.read()` 后校验; 全项目无 max_upload_size |
| P2-4 审计不全 | 大体属实 | 实测已有: login/login_failed/confirm/confirm_batch/generate/kb_*/user_*/policy_update/questions_update/llm_update; 缺: 项目删除、导出、组件变更 |
| P2-5 前端工程化 | 属实 | 行数精确吻合(Step4DataAssets 536 / AdminPage 527 / Step1ProjectInfo 471); 无 manualChunks、无 React.lazy; `.github/workflows/release.yml` 仅 push tag 触发且只跑 pytest; package.json 无 Playwright |
| 小项: 无版本前缀 | 属实 | 各路由均为 `/api/...` |
| 小项: 静态资源不鉴权 | 属实 | `main.py:93` `app.mount("/")` 绕过 app 级 `dependencies=[Depends(auth_guard)]`; 登录页必需的放行, 属知情边界 |
| 小项: review.py 遗留 | 属实 | README:125 自述遗留表; README:169 列入路线图 |
| 小项: 401 兜底 | 描述准确 | `frontend/src/api.ts:64/83` 仅对 fetch 广播 AUTH_EXPIRED_EVENT; 属告知性说明 |

测试基线(137 passed / 1 failed)系评审环境所跑, 本地未复跑; 失败项归因于评审沙箱临时目录清理,
实施阶段首步应先复跑 pytest 确认基线。
