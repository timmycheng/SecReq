# 测试审计报告

- 审计日期: 2026-09-04(首轮, 基于 main @ 783add9)
- 审计范围: 后端 pytest 套件(`tests/`, 30 文件)与前端 E2E(`frontend/e2e/`); 不修改任何业务代码, 全部改动仅限测试文件与本报告
- 本轮结论速览: 套件整体健康(282 条全绿、0 skip、无伪断言、无孤儿用例), 无 P0 问题; 债务集中在 `api` 夹具逐用例重建的性能开销、`test_api_flow.py` 的巨型端到端用例、少量跨文件重复构造与三处端点级覆盖缺口

## 1. 本次盘点统计

### 框架与运行命令

| 层 | 框架 | 命令 | 备注 |
|---|---|---|---|
| 后端单测/集成 | pytest 9.x(uv 管理) | `uv run --frozen pytest tests -q` | CI 后端检查 job 同口径(.github/workflows/ci.yml:72) |
| 后端 lint | ruff | `uv run ruff check .` | 只拦 E4/E7/E9/F |
| 前端单测 | 无 | — | package.json 无 vitest/jest, 前端检查 job 仅 oxlint + tsc |
| 前端 E2E | Playwright 1.62 | `cd frontend && npx playwright test` | 仅 PR 触发的 CI job, 依赖后端 uvicorn 起 webServer |

### 用例分布(后端 30 文件 / 274 个测试函数 / 282 条用例, 含 8 条参数化展开)

| 文件 | 用例数 | 被测对象 |
|---|---|---|
| test_vulndb.py | 31 | services/vulndb.py + scripts/build_vuln_db.py 端到端 |
| test_admin.py | 30 | routers/admin.py(知识库/题库/策略/用户/漏洞库页/LLM/审计) |
| test_netbox.py | 21 | routers/netbox.py + services/netbox.py |
| test_osv.py | 17 | services/osv.py(MockTransport, 不出网) |
| test_systems.py | 13 | routers/systems.py + services/system_service.py |
| test_auth_rbac.py | 12 | routers/auth.py + 全局 auth_guard 二元角色 |
| test_regulatory_upgrade.py | 11 | 监管基线升级迁移 |
| test_seed_demo.py | 10 | services/seed_data.py |
| test_sbom.py / test_loader.py / test_grading.py / test_engine_auth_policy.py / test_audit_coverage.py | 各 8 | services/sbom.py、rules/loader.py、services/grading.py、认证策略规则、审计留痕 |
| 其余 18 个文件 | 3~7 | 引擎各维度/向导/继承/导出/Schema 升级等 |

- 运行耗时: 首轮冷跑 40.7s; 优化后同负载对比见第 3 节(36.5s → 33.0s)
- 耗时结构(`--durations=0` 聚合): setup 合计 18.6s > 断言执行合计 13.7s, 建库/种子/登录夹具开销超过一半; 单文件最重 test_admin.py 9.2s、test_netbox.py 3.5s、test_auth_rbac.py 3.0s
- skip/xfail: 0 条; 断言恒真/空断言: 0 处; 孤儿用例: 0 处(全绿意味着无引用已删除代码)
- 稳定性模式扫描: 无真实网络调用(osv/netbox 均为 MockTransport/Fake)、无 random、无依赖执行顺序(全部函数级独立内存库); 仅 test_osv.py:348,368 两处 `asyncio.sleep` 位于 MockTransport handler 内模拟慢网络, 属合理用法

## 2. 问题清单

### P0(无效/伪测试/系统性风险)

未发现。无 skip 无说明用例、无恒真断言、无孤儿测试、无出网/时序依赖。

### P1(建议尽快处理)

1. **`api` 夹具逐用例重建是最大性能开销** — tests/conftest.py:80。每次 create_engine + init_db + ensure_seed_users(含口令散列) + 登录往返, 单次约 0.14s, 全套件约 130 处使用、贡献了 setup 18.6s 的主要部分。建议: 下一轮评估"模块级共享库 + 每用例事务回滚(SAVEPOINT 嵌套事务)"模式, 预计可再省 8~12s; 属侵入式改造, 需要单独一批验证。
2. **巨型端到端用例** — tests/test_api_flow.py:41 `test_full_wizard_flow_and_generate_offline`, 约 290 行串联向导 8 步 + 预览 + 生成 + 筛选 + 三种导出 + 确认 + wizard-state + PATCH/DELETE, 覆盖约 20 个关注点。失败时定位成本高, 无法单独重跑某一步。建议: 以"已填充项目"模块级夹具为底座按步骤拆成 6~8 条用例。
3. **生成/导出用例真实写仓库根 `output/`** — services/pipeline.py:87 默认 `Path("output")`, 由 test_api_flow.py:43,321(cleanup_output 兜底删除)与 test_systems.py:107 消费。断言中途失败即残留目录, 且并行化后必然互踩。根治需 pipeline 支持 out_dir 注入(业务代码改动, 本轮禁区), 建议开 issue 排期。
4. **端点级覆盖缺口**(service 层已覆盖, 仅缺 HTTP 胶水断言):
   - `POST /api/projects/{id}/data-assets/parse-dictionary` 与 `import-dictionary`(routers/steps.py:266,280) — services/dictionary_import.py 已有 test_dictionary_import.py 直接测, 但端点的鉴权/入参校验/审计留痕无 API 用例;
   - `GET /api/projects/{id}/requirements/diff`(routers/generate.py:208) — diff_requirements/find_previous_round 已在 test_assessment_inheritance.py:47-135 直测, 但端点的 `comparable=False` 分支与 `against` 参数无 API 用例;
   - `services/entity_uid_migration.py`(144 行, 由 main.py:52 lifespan 与 scripts/migrate_entity_uid.py 调用) — 测试目录无任何直接引用, uid 迁移(v2.3.0 主线)只有间接覆盖。
5. **test_regulatory_upgrade.py 五处 session 样板** — 行 46,75,115,138 各自内联 `make_engine + init_db + sessionmaker`, 行 182 `_make_session_with_asset` 是第五份包装; conftest 的 `session` 夹具(conftest.py:31)完全等价。建议统一改用夹具, 纯机械替换。

### P2(择机清理)

6. 跨文件重复种子/夹具: test_seed_demo.py:13 与 test_regulatory_upgrade.py:136 各自维护 `seed_demo_project + RuleEngine.generate` 的模块级种子; test_auth_rbac.py:19 `dev_b` 夹具与 test_systems.py:135-137 内联 `dev_ledger` 是同构的"安全角色开第二个开发账号"构造; 建议沉淀到 conftest。
7. "DB 行还原成带 uid 的 In 模型"逻辑三处实现: tests/test_traceability_stability.py:17(`_saved_features_as_in`)、test_assessment_inheritance.py:70,109(两处内联复制)、test_traceability_stability.py 同文件还有 DataAsset 手写变体; 可参数化为 conftest 通用 helper。
8. 重复覆盖: 重复 code 建项目返回 409 在 test_api_flow.py:33-36 与 test_auth_rbac.py:156-161 测了两遍(保留后者即可); `ensure_schema_upgrade` 幂等断言在 test_systems.py:173 与 test_schema_upgrade.py 重复。
9. 结构错位: test_systems.py:173 `test_schema_upgrade_adds_system_id` 属 Schema 升级主题却放在台账文件, 且声明的 `monkeypatch` 参数未使用; 建议迁入 test_schema_upgrade.py 并删死参数。
10. 命名与单用例多事: test_regulatory_upgrade.py:228 `test_regulatory_trigger_extra_cases` 无行为语义且内含 App 台账 + 境外供应商两件事; test_auth_rbac.py:76 `test_change_password_requires_old_password` 实际验证 5 件事(错旧密码/成功改密/会话吊销/旧密码拒/新密码通), 可拆。
11. 薄弱断言: test_tracking_export.py:58-60 `test_bytes_roundtrip` 仅查 `data[:2] == b"PK"` 不验证内容可解析回; test_systems.py:123 `filing_id=999` 的 409 不区分成因(可补 detail 文案断言)。
12. 魔法值: test_api_flow.py:92 硬编码主键 `[1, 2, 3]`(隐含依赖全新库自增从 1 起); test_api_flow.py:292 `reqs[:5]` 的 5 无解释。
13. 相对时间依赖(低风险): test_assessment_inheritance.py:32,127,132 用 `datetime.now() + timedelta` 构造轮次先后, 均为相对偏移, 目前无 flaky 记录, 仅备案。
14. 前端无单测: frontend/src(含 router.ts、api.ts 等纯逻辑)仅有 1 条 Playwright 主链路 E2E 兜底; 若前端逻辑继续膨胀建议引入 vitest(需加依赖, 本轮禁区, 先备案)。
15. E2E 未在本轮审计中本地执行(需 `npx playwright install chromium` 与构建产物), 质量以 CI 的 e2e job 为准; 本轮改动未触碰 frontend/。

## 3. 本轮已完成的优化

每批改动后均运行受影响文件, 最终全量 282 passed + `uv run ruff check .` 通过。同负载对比(stash 基线 vs 优化版各跑两次): **36.55s/36.49s → 32.58s/33.65s, 约快 10%**; 用例数 282 不变(无删减, 仅一条用例内新增断言)。

| 文件 | 改动 |
|---|---|
| tests/conftest.py | 新增 session 级 `engine` 夹具(知识库 YAML 只解析一次, 原 5 份函数级副本 ×44ms/次; 共享安全性依据: generate() 入口重置 self.skipped、_handlers 静态, 见夹具 docstring); 新增 `cleanup_output()` 与 `demo_features()` 公共 helper |
| tests/test_engine_features.py / test_engine_data_asset.py / test_engine_auth_policy.py / test_engine_permission.py | 删除与 conftest 重复的本地 `engine` 夹具及随之无用的 `import pytest` / `from rules import RuleEngine` |
| tests/test_engine_api_compliance_vuln.py | 同上删除本地夹具(保留 `import pytest`, 文件内 pytest.raises 仍在用) |
| tests/test_admin.py | `vulndb_file` 改为模块级 `_vulndb_built` 一次构建 + 每用例 `shutil.copy` 独立副本: 构建成本从 5×0.35s 降为 1 次, 复制保留 .sha256 副件隔离(verify 用例会在同目录写副件, 不能像 test_vulndb 那样只读共享) |
| tests/test_api_flow.py | 改用 conftest `cleanup_output`(删本地副本); `assert resp.status_code == 400 or 422` 收紧为 `== 400`(依据 routers/steps.py 文件名白名单必返 400), 并补一条 `.json` 后缀 + 垃圾内容走 SbomParseError 分支同样 400 的断言 |
| tests/test_systems.py | 改用 conftest `cleanup_output`, 删本地副本与 shutil/Path import |
| tests/test_traceability_stability.py / test_assessment_inheritance.py | 删除两份逐字节相同的 `_features()`, 统一引用 conftest `demo_features()` |
| tests/test_auth_rbac.py | 删除 `test_change_password_requires_old_password` 末尾"恢复默认密码避免影响其他用例"死代码(api 夹具每用例全新内存库, 恢复无意义), 同时把正向断言"新密码可登录"保留为独立两行 |
| tests/test_sbom.py | `test_write_cyclonedx_file_keeps_utf8_chinese` 从写 CWD 相对路径 `output_test/` + 手工 unlink/rmdir(失败即泄漏目录)改为 pytest `tmp_path`, 删除手工清理 |

未删除任何用例; 未修改生产代码、依赖声明与 CI 配置。

## 4. 遗留事项(下次运行起点)

1. P1-1 `api` 夹具事务回滚改造(预估收益 8~12s, 需单独验证批)。
2. P1-2 拆分 test_api_flow.py 巨型用例(先建模块级"已填充项目"夹具)。
3. P1-3 pipeline out_dir 注入(业务代码, 需开 issue 走正常流程, 连带消除 output/ 真实写盘)。
4. P1-4 三处端点/迁移覆盖缺口补 API 用例(parse-dictionary、import-dictionary、requirements/diff 的 comparable=False 分支、entity_uid_migration)。
5. P1-5 test_regulatory_upgrade.py 五处 session 样板换 conftest `session` 夹具。
6. P2 清单(第 2 节 6~14 条)按顺手原则渐进处理; 其中 P2-6/P2-7 优先(重复种子与 uid 还原 helper 收敛)。

### 给人工 review 的建议

- 重点看 conftest.py 的 session 级 `engine` 夹具 docstring 里写的共享安全性论证是否成立(已验证: 5 个消费文件只调 `generate()` 与读 `skipped`, 容错用例自建引擎)。
- test_admin.py 的 `_vulndb_built`/`vulndb_file` 拆分注意读注释: 为什么不能像 test_vulndb.py:158 那样直接模块级共享单文件(verify 用例写 .sha256 副件需要目录隔离)。
- test_api_flow.py 的 400 断言收紧与新增 SbomParseError 分支断言, 建议对照 routers/steps.py:406-420 确认口径。

## 5. 本轮变更文件清单(供 review 后决定提交)

- docs/test-audit.md(新增, 本报告)
- tests/conftest.py
- tests/test_admin.py
- tests/test_api_flow.py
- tests/test_assessment_inheritance.py
- tests/test_auth_rbac.py
- tests/test_engine_api_compliance_vuln.py
- tests/test_engine_auth_policy.py
- tests/test_engine_data_asset.py
- tests/test_engine_features.py
- tests/test_engine_permission.py
- tests/test_sbom.py
- tests/test_systems.py
- tests/test_traceability_stability.py
