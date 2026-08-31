# SecReq 优化实施方案

基于 [OPTIMIZATION_REVIEW.md](OPTIMIZATION_REVIEW.md) · 版本基线 v2.1.2 · 2026-08-30

**已确认的三个决策**
1. 范围: 全量(P0 + P1 + P2)
2. 溯源修复路线: **稳定业务键 uid**
3. 执行方式: 本方案经 review 通过后再动代码

---

## 总体策略

分 5 个阶段, 每阶段独立可发布、独立可回滚。**阶段顺序刻意把"低风险补丁"排在"数据迁移"之前** ——
先用一批零结构变更的改动把安全面和运行风险降下来, 再动最重的 uid 迁移,
这样迁移出问题时前面已经有一批稳定的可回滚成果垫底。

| 阶段 | 主题 | 涉及文件数 | 结构变更 | 可独立发布 |
| ---- | ---- | ---------- | -------- | ---------- |
| 0 | 测试护栏(先写失败测试) | 2 | 无 | 否(是后续阶段的验收依据) |
| 1 | 低风险安全与质量补丁 | 8 | 无 | 是 |
| 2 | 并发性能与部署基建 | 6 | 无 | 是 |
| 3 | 数据一致性(uid 迁移) | 22 | **有** | 是(需跑迁移脚本) |
| 4 | 前端工程化与 CI | 9 | 无 | 是 |

---

## 阶段 0 · 测试护栏

**先写会失败的测试, 再改代码。** 阶段 3 的两个 P0 都是行为契约变更, 没有测试锁定的话改完无法证明改对了。

新增 `tests/test_traceability_stability.py`:

```
test_regenerate_preserves_confirmation
    生成 → 批量确认 N 条 → 修改功能清单 → 重新生成
    断言: 原 N 条 reg_confirmed 仍为 True, confirmed_by / confirmed_at 未丢失

test_saving_step_keeps_traceability
    生成 → 记录每条需求的 source_entity_uid → 回 Step3 追加一个功能并保存
    断言: 已有需求的 uid 仍能在功能表中解析到同名实体

test_replacing_one_row_keeps_other_ids
    3 条功能 → 只改第 2 条的名称 → 保存
    断言: 第 1、3 条主键 uid 未变

test_sensitive_asset_link_survives_asset_resave
    接口关联数据资产 → 重新保存数据字典 → 断言关联仍指向同一资产
```

新增 `tests/test_osv_concurrency.py`:

```
test_sync_runs_concurrently      用 MockTransport + 可观测的 sleep 断言并发度 > 1
test_sync_respects_total_budget  全部组件超时时, 总耗时不超过设定预算
```

**验收**: 新测试全部失败(红灯), 既有 137 个用例保持通过(绿灯)。

---

## 阶段 1 · 低风险安全与质量补丁

零结构变更, 改完即可发布。

### 1.1 异常脱敏 (P2-1)

| 文件 | 改动 |
| ---- | ---- |
| `routers/generate.py:105-106` | `logger.exception(...)` 记录完整栈, 对客户端返回 `{"detail": "生成失败", "trace_id": ...}` |
| `routers/steps.py:233` | `f"Excel 解析失败: {exc}"` → 通用文案, 原文进日志 |
| 新增 `services/trace.py` | 生成 trace_id(8 位短码), 日志与响应共用, 便于用户报障时比对 |

### 1.2 拆除 `saas_finance` 定时炸弹 (P2-2b)

`rules/engine.py:476` docstring 声明了该规则但 `_match_regulatory_triggers` 未实现。
当前 61 条模板未用到所以不炸, 但管理页一旦按文档建模板就会让整个生成 500。

**二选一, 建议选前者**:
- 补实现(部署环境含外采 SaaS 且业务属金融);
- 或删掉 docstring 中该行, 并在 `_match_regulatory_triggers` 末尾的 `raise` 分支里
  把错误信息改成"未知规则, 请检查知识库配置"并跳过而非中断整轮生成。

> 顺带建议: 引擎遇到单个模板的 rule_key 未知时, 记录错误并**跳过该模板**,
> 而不是让整个生成失败。一条坏配置不该拖垮全部 61 条。

### 1.3 上传大小限制 (P2-3)

`routers/steps.py:221` / `:334` 的 `await file.read()` 前没有体积闸门。
建议: 加 Starlette 的 `max_upload_size`(建议 5 MB), 或改为按块读取并累计超限即 413。

### 1.4 审计补全 (P2-4)

`services/audit_service.py` 当前覆盖 generate / confirm / kb_* / user_* / policy / llm。
补充以下埋点:

| 位置 | 动作 |
| ---- | ---- |
| `routers/auth.py` 登录失败 | `login_failed`(含 username, **不记密码**) |
| `routers/projects.py` 删除项目 | `project_delete` |
| `routers/generate.py` export_docx / export_xlsx | `export`(数据外带必须留痕) |
| `routers/steps.py` 各 save_* | `step_save`(记录项目与步骤名即可, 不记全量数据) |

### 1.5 清理死代码

`models/database.py:16-18` 的 `_sqlite_kwargs()` 从未被调用, 删除。

**验收**: 137 + 新增用例通过; 手工验证 `/generate` 在知识库故意配错时返回脱敏文案且日志有栈。

---

## 阶段 2 · 并发性能与部署基建

### 2.1 OSV 异步化 (P0-3)

现状: `services/osv.py:326-346` 逐组件串行, 单请求 10s; 路由是同步 `def`,
Docker 单 worker + 默认 40 线程池 → 几人同时点"生成"即打满线程池, 连登录都挂。

改动:

1. `services/osv.py` — `OsvClient` 改用 `httpx.AsyncClient`:
   - 新增 `async def query_purl_async(purl)`;
   - 保留同步 `query_purl` 供 `scripts/run_seed_demo.py` 与既有测试复用,
     内部实现改为共享同一套 `normalize` 逻辑(不重复代码);
   - 新增 `async def sync_vulnerabilities_async(session, components, ...)`,
     用 `asyncio.gather` + `asyncio.Semaphore(8)` 并发;
   - **整轮总超时预算 60s**(`asyncio.wait_for`), 超时即把剩余组件计入 `failed` 降级,
     不让单个慢请求拖死整轮。
2. `routers/generate.py:92` — `def generate` 改 `async def`, 调用 async 版本。
3. `services/pipeline.py` — `run_full_pipeline` 增加 async 版本;
   同步版本保留给脚本(`run_seed_demo.py`)与测试。

> 注意: `_replace_component_vulns` 依赖 `session.flush()` 的顺序语义,
> 异步并发下**不能并发写库**。正确做法: 并发只做网络查询, 拿到结果后**串行**写库。
> 这样既拿到并发收益, 又不动 ORM 的线程安全边界。

### 2.2 SQLite 并发参数 (P1-2)

`models/database.py` 的 `make_engine` 中, 对 SQLite 增加 event listener:

```python
PRAGMA journal_mode=WAL;    # 读写不互斥
PRAGMA busy_timeout=5000;   # 锁等待 5s 而非立即报错
PRAGMA synchronous=NORMAL;  # WAL 下的合理选择
```

同时把 `pool_size` / `max_overflow` 显式化, 避免依赖默认值的隐式行为。

### 2.3 依赖锁版本 (P1-3)

- `pip-compile requirements.in -o requirements.lock`(或改用 uv / poetry);
- `Dockerfile` 改为 `pip install --no-cache-dir -r requirements.lock`;
- 保留 `requirements.txt` 作为可读的顶层依赖声明。

### 2.4 部署形态建议

`Dockerfile` 目前是单 uvicorn worker。2.1 之后同步阻塞缓解了, 但仍建议:
`CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]`
—— 多 worker 下需注意 `rules/admin._apply_policy_settings` 是进程内缓存,
多 worker 之间策略更新不同步, 需要在管理端保存策略时广播或改为读库。
**若不想引入这个复杂度, 保持单 worker 也可接受**, 2.1 已解决主要阻塞点。

**验收**: `tests/test_osv.py` 全绿; 人工用 20+ 组件项目点生成, 观察耗时从"逐个累加"降到"接近单个最慢请求";
压测: 3 个并发生成请求期间, `/api/health` 与登录仍可响应。

---

## 阶段 3 · 数据一致性(核心)

**这是整个方案的重心, 也是唯一带结构变更的阶段。建议单独发一个版本。**

### 3.1 现状盘点

`source_entity_type` 共 11 种, 逐个判断是否需要稳定标识:

| source_entity_type | 当前存的值 | 是否被整表替换 | 处理 |
| ------------------ | ---------- | -------------- | ---- |
| `feature` | `Feature.id` | **是** | 加 uid |
| `data_asset` | `DataAsset.id` | **是** | 加 uid |
| `api_endpoint` | `ApiEndpoint.id` | **是** | 加 uid |
| `external_system` | `ExternalSystem.id` | **是** | 加 uid |
| `sbom_component` | `SbomComponent.id` | **是** | 加 uid(漏洞与许可证风险共用) |
| `role` | `Role.id` | **是** | 加 uid |
| `permission_entry` | `PermissionEntry.id` | **是** | **不加列**, 用 `(role_uid, resource_uid, action)` 复合键 |
| `project` | `Project.id` | 否 | 无需改动 |
| `compliance_target` | `Project.id` | 否 | 无需改动 |
| `auth_config` | `AuthConfig.id` | 否(单行 upsert 保留主键) | 无需改动 |
| `policy_baseline` | `AuthConfig.id` 或 `Project.id` | 否 | 无需改动 |

> `permission_entry` 用复合键是刻意的选择: 它的语义本来就是"某角色对某资源的某操作",
> 三者确定后条目即确定, 不需要额外再背一个 uid 列。

另外 `ApiEndpoint.sensitive_asset_ids` 存的是 `DataAsset.id` 数组 ——
**这是同一类隐患的第二处**, 必须一并治理, 否则数据字典重存后接口与资产的关联就断了。

### 3.2 模型改动

给 **8 个模型** 各加一列:

```python
uid: Mapped[str] = mapped_column(String(36), index=True, comment="稳定业务标识(UUID4), 跨保存保持不变")
```

涉及: `Feature` / `DataAsset` / `SbomComponent` / `Role` / `Resource` /
`ApiEndpoint` / `InfraAsset` / `ExternalSystem`

配套约束:

```python
# 各表 table_args 追加(示例为 features)
UniqueConstraint("project_id", "uid", name="uq_feature_project_uid")
```

> `InfraAsset` 当前不参与溯源, 但同样被整表替换, 一并加列以保持一致性与后续扩展空间。
> `DataTable` / `DataField` 跟随 `DataAsset` 的 cascade 重建, 不需要 uid。

`models/requirement.py` 字段调整:

```python
source_entity_uid: Mapped[str | None] = mapped_column(String(64), comment="来源实体稳定标识")
# source_entity_id 保留为 Integer 但标记 deprecated, 一个版本后删除
```

`models/inventory.py` 字段调整:

```python
sensitive_asset_uids: Mapped[list] = mapped_column(JSON, default=list, comment="关联敏感数据资产 uid 列表")
# sensitive_asset_ids 同上, 标记 deprecated
```

### 3.3 迁移脚本

新建 `scripts/migrate_entity_uid.py`, 沿用 `scripts/migrate_classification.py` 的既有约定
(**支持 `--dry-run`、幂等、与 `services/` 共用实现**):

1. 加列并回填 UUID4;
2. 按 `(project_id, source_entity_type, source_entity_id)` 把存量需求的 `source_entity_id`
   映射为 `source_entity_uid`;
3. `sensitive_asset_ids` → `sensitive_asset_uids`;
4. **诚实处理存量脏数据**: 实体已被替换导致映射不到的需求,
   保留 `source_label` 文本, `source_entity_uid` 置空, `status` 标为 `obsolete`。
   不要伪造映射 —— 这些记录本来就已经断链了。

> 应用启动时同样自动执行(与 `classification_migration` 一致的口径),
> 保证容器化部署无感升级。

### 3.4 引擎改动

`rules/engine.py`:

1. `Match` dataclass: `source_entity_id: int` → `source_entity_uid: str`;
2. 各处 `source_entity_id=feature.id` → `=feature.uid`(7 处, 见评审附录清单);
3. `_source_label` 改为**查预建索引**而非线性扫描(顺带解决 P2-2a 性能问题);
4. `permission_entry` 的 uid 由 `(role.uid, resource.uid, action)` 拼成。

`rules/context.py`:

1. 预建 `{uid: entity}` 字典索引, 替代 `resource_by_id` / `_source_label` 里的 `next(生成器)`;
2. `entries_of_role` / `role_actions_on` 同样改为索引查询;
3. `sensitive_asset_names` 接收 uid 列表。

### 3.5 保存逻辑改为 upsert(P0-2 的另一半)

只加 uid 不够 —— 还必须让"替换"时复用已有行的 uid。这是关键的一步。

**契约变更**: 前端保存步骤时**回传 uid**。新增行的 `uid` 为空, 由后端生成。

`services/step_store.py` 的各 `replace_*` 统一改为:

```
提交行有 uid 且库中存在 → 更新该行(主键不变)
提交行无 uid           → 新建(UUID4)
库中有、提交中缺失      → 删除
```

`replace_data_assets` 需要特殊处理: 它是 资产→表→字段 三级结构,
按 `asset.uid` 匹配资产, 资产内按 `table_name` 匹配表, 表内按 `field_name` 匹配字段,
沿用同样的"匹配则更新、缺失则删、新增则建"逻辑。

### 3.6 生成逻辑改为 upsert(P0-1)

`rules/engine.py:169-175` `generate_and_save`:

```
1. 按 (project_id, template_id, source_entity_uid) 建立现有需求索引
2. 命中且已存在 → 更新 title/description/priority/trigger_reason 等派生字段,
                  保留 reg_confirmed / confirmed_by / confirmed_at / status
3. 命中且不存在 → 新建, reg_confirmed 置 False
4. 本轮未命中    → 不硬删, status 标为 obsolete(便于统计"整改后消失的风险")
```

### 3.7 前端改动

| 文件 | 改动 |
| ---- | ---- |
| `frontend/src/types.ts` | FeatureRow / DataAssetRow / ComponentRow / RoleRow / ResourceRow / ApiEndpointRow / InfraAssetRow / ExternalSystemRow 各加 `uid: string`; `RequirementRow.source_entity_id: number` → `source_entity_uid: string`; `ApiEndpointRow.sensitive_asset_ids: number[]` → `sensitive_asset_uids: string[]` |
| 各 `steps/Step*.tsx` | 新增行时 `uid: ''`; 编辑/删除时不得改写已有行的 uid; 保存时整行回传 |
| `Step6ApiList.tsx:82,155` | 资产关联选择器改为按 uid 取值(下拉的 value 从 id 换 uid, 展示仍用 name) |
| `ResultPage.tsx` | 无实质改动(展示走 `source_label`), 但需确认 obsolete 需求的展示样式 |

> **风险点**: 前端若漏传 uid, 后端会当成"全部新增" → uid 全变 → 溯源再次断裂。
> 建议在后端加一道**断言式保护**: 保存时若某项目已有生成记录,
> 且提交行全部无 uid, 则返回 409 提示前端版本过旧需刷新。宁可失败也不要静默断链。

### 3.8 验收标准

- 阶段 0 的 4 个测试全部转绿;
- 既有 137 个用例中, 涉及实体 id 断言的用例需同步更新(预计 `test_api_flow.py`、
  `test_engine_api_compliance_vuln.py`、`test_seed_demo.py` 等 6-8 个文件);
- 手工回归: 建项目 → 走完 8 步 → 生成 → 确认若干条 → 回 Step3/Step4 各改一处 →
  重新生成 → **确认状态保留、溯源仍指向正确实体**;
- 存量库升级: 用当前 `secreq.db` 副本跑 `--dry-run` 确认映射率, 再执行。

### 3.9 风险与回滚

| 风险 | 应对 |
| ---- | ---- |
| 存量需求溯源已断, 迁移后暴露出来 | 标 `obsolete` 而非伪造映射; 迁移前 `--dry-run` 先给出断链比例报告 |
| 前端漏传 uid 导致静默断链 | 后端 409 保护(见 3.7) |
| 迁移中断留下半截状态 | 迁移脚本幂等, 可重复执行; 执行前强制备份 db 文件 |
| 字段双写期(source_entity_id 与 uid 并存) | 保留一个版本, 下个版本删除旧列并再跑一次清理迁移 |

**回滚方案**: 保留迁移前的 `secreq.db` 备份 + 代码回退到上一 tag。
注意 uid 迁移是**单向**的(旧代码读不懂新列), 回滚必须连数据库一起回退。

---

## 阶段 4 · 前端工程化与 CI

### 4.1 组件拆分

三个文件超 470 行, 按"表单区 / 列表区 / 弹窗区"拆子组件:

| 文件 | 行数 | 建议拆分 |
| ---- | ---- | -------- |
| `steps/Step4DataAssets.tsx` | 536 | 资产表单 / 表字段树 / 字典导入弹窗 / 自动分级预览 |
| `ui/AdminPage.tsx` | 527 | 知识库 / 题库 / 策略 / LLM / 用户 / 审计 六个 Tab 各自成文件 |
| `steps/Step1ProjectInfo.tsx` | 471 | 基本信息 / 外部系统清单 / 定级问卷 / 基线预览 |

并充分利用 AntD Form 的校验与联动, 替代目前手写的状态与校验逻辑。

`AdminPage` 的六个 Tab 相互独立, 拆分收益最高、风险最低, **建议先拆它**。

### 4.2 代码分割

首屏要加载完整 AntD + React 19。在 `vite.config.ts` 配 `manualChunks` 拆出 antd,
或用 `React.lazy` 按页加载(WizardPage / AdminPage / ResultPage 三块最重)。

### 4.3 CI 补全

`.github/workflows/release.yml` 目前只在 push tag 时跑 pytest + 构建镜像。
新增 `.github/workflows/ci.yml`(PR 与主要分支触发):

- 后端: `pytest`(可加覆盖率门槛, 建议先设 70% 不卡门, 观察后再提)
- 前端: `oxlint` + `tsc -b` + `npm run build`
- 依赖锁文件与实际安装的一致性检查

### 4.4 E2E(建议, 可后置)

8 步向导目前回归靠手点。Playwright 覆盖一条主链路
"建项目 → 走完 8 步 → 生成 → 批量确认 → 导出"的投入产出比很高,
尤其在阶段 3 改了保存契约之后。

---

## 不建议改动的清单

评审里单列过, 这里重申以免误伤:

- `rules/engine.py:36-49` 占位符白名单渲染(天然免疫 SSTI)
- `services/osv.py:201-226` 多坐标过滤(挡派生包污染)
- `routers/common.py` 数据权限统一收口 + 越权 404
- `services/kb_admin.py` YAML 写回的备份/校验/回滚
- `shared/constants.py` 单一枚举源 + `/api/meta/constants` 供数

---

## 建议的发版节奏

> ⚠️ **本节已被 `MASTER_PLAN.md` 第三节取代。** 下表未包含离线漏洞库,
> 且未严格区分 PATCH / MINOR。版本编排请以 MASTER_PLAN 为准,
> 本节保留仅作为"阶段 0-4"到版本的旧映射参考。

| MASTER_PLAN 版本 | 对应本文阶段 |
| ---------------- | ------------ |
| **v2.1.3** (PATCH) | 阶段 1(低风险补丁)+ 阶段 2 的并发修复部分 |
| **v2.2.0** (MINOR) | 离线漏洞库(见 `OFFLINE_VULN_DB_PLAN.md`) |
| **v2.3.0** (MINOR) | 阶段 3(uid 迁移)—— 单独发版, 配迁移说明 |
| 不占版本号 | 阶段 4(前端与 CI) |
| **v2.4.0** (MINOR) | SCA 对接 |

阶段 3 必须单独发版: 它是唯一带数据迁移的改动, 出问题时要能精确定位到这一次变更。

---

## 需要你确认的开放问题

1. **`saas_finance`(1.2)**: 补实现, 还是删文档 + 引擎改为"跳过坏模板"?
2. **多 worker(2.4)**: 是否接受"策略缓存在多进程间不同步"这一约束?
   若不能接受, 策略保存需改为读库或加广播, 会增加一块工作量。
3. **obsolete 需求的前端展示(3.6)**: 需求不再命中时是隐藏、置灰、
   还是保留并标注"该项风险已消除"?
4. **旧列清理(3.2)**: `source_entity_id` 与 `sensitive_asset_ids`
   保留一个版本后删除, 还是保留更久?
