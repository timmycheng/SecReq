# 开发流程规范(Dev Workflow)

本仓库所有改动 —— 无论人还是 AI Agent —— 一律遵循本规范。[AGENTS.md](../AGENTS.md) 面向 Agent 的硬性指令与 [CONTRIBUTING.md](../CONTRIBUTING.md) 的入口速览均以本文为唯一权威来源, 修改流程规则只改这里。

核心原则: **main 始终处于可发布状态**。main 受分支保护(禁止直推、必须 PR、CI 必须通过、仅允许 squash 合并、线性历史、对管理员同样生效), 所有改动经 issue → 分支 → PR → CI → squash 合并进入 main。

```text
开 issue(模板 + type:/priority: 标签, 版本批次挂 milestone)
  → git pull 最新 main, 切分支 <type>/<issue号>-<slug>
  → 开发 + 本地自测(质量门禁三件事本地先跑绿)
  → 开 PR(自动套模板, 正文 Closes #N)
  → CI 四个 job 全绿(后端测试 / 后端 Lint / E2E 主链路 / 前端检查)
  → 自审后 squash 合并, 删分支, issue 自动关闭
  → 版本批次全部关闭后, 按下文「版本与发版」清单发版
```

## Issue 管理

- 缺陷用「缺陷报告」模板, 功能建议用「功能建议」模板, 流程/任务类杂项用空白 issue; 开 issue 前先检索是否已有同类。
- 标签两组: `type: bug / feature / docs / chore / ci` 标性质, `priority: P0 / P1 / P2` 标优先级(P0 阻塞项先修)。
- 每个功能/修复原则上一个 issue, 粒度以"一个分支能闭合"为准; 代码审查产出的修复批量按项拆分(参考 milestone v2.2.1 对 docs/fix-plan-v2.2.1.md 的拆解), 审查方案文档降级为存档与改法细则, 完成状态以 issue/milestone 为准。
- 版本批次挂对应版本 milestone(如 v2.2.1); **milestone 全部关闭即具备该版本发版条件**。
- PR 正文用 `Closes #N` 关联 issue, 合并即自动关闭; 仅建立关联用 `Refs #N`。

## 分支规范

- 从最新 main 切出(先 `git pull`), 命名 `<type>/<issue号>-<slug>`, type 与提交前缀一致: `feat/`、`fix/`、`docs/`、`chore/`、`ci/`; slug 用小写英文短横线, 如 `fix/18-schema-upgrade`。
- 合并后删除分支; 禁止在 main 上直接提交。

## 提交信息规范

约定式提交(Conventional Commits) + 中文描述, 格式 `<type>(<scope>): <一句话概述>`, scope 用模块中文名。

| type | 用途 | 示例 |
| --- | --- | --- |
| feat | 新功能 | `feat(漏洞库): 支持 Bitnami 生态版本归一化` |
| fix | 缺陷修复 | `fix(认证): 初始密码环境变量化并随机回退` |
| docs | 文档 | `docs(README): 更新内网部署说明` |
| refactor | 重构(不改行为) | `refactor(规则引擎): 抽取上下文构造器` |
| chore | 工程杂项 | `chore(依赖): 升级 fastapi 至 0.115` |
| ci | 流水线 | `ci: 前端 job 增加 npm 缓存` |

- PR 内多个提交无需完美, squash 合并时以 PR 标题为准压成一个提交, PR 标题同样遵循本格式。
- 历史提交(2026-08 之前)未采用本规范, 不做追溯改写。

## PR 与 CI 门禁

- PR 自动套模板: 改动说明 / 关联 issue / 自测记录 / 检查清单(CI、CHANGELOG、版本影响、部署文档), 逐项如实勾选。
- `ci.yml` 在 PR 与 push main 时触发, 四个 job 必须全绿; 同分支新提交自动取消旧运行。
- CI 红了看日志修复, 不绕过门禁(分支保护也不允许绕过)。

本地复现 CI(E2E 可本地跑, 其余三件事建议每次提交前必跑):

```bash
uv run pytest tests -q         # 环境来自 uv sync(按 uv.lock 精确安装)
uv run ruff check .            # 宽松口径见 ruff.toml
cd frontend && npm run lint && npm run build   # build 内含 tsc 类型检查
npm run e2e                    # E2E 主链路(首次先 npx playwright install chromium; webServer 自动拉起后端)
```

## 版本与发版

SemVer: 新功能升 MINOR, 缺陷修复升 PATCH, 不兼容变更升 MAJOR。发版清单:

1. 确认对应版本 milestone 已全部关闭, main CI 全绿。
2. 修改 `main.py` 中 FastAPI 的 `version="X.Y.Z"` 与 `pyproject.toml` 的 `project.version`。
3. 在 `CHANGELOG.md` 顶部新增 `## [X.Y.Z] - 日期` 章节, 遵守一条/一段独占一行(会被 release.yml 原样抽取为 Release 正文)。
4. 本地校验: `python scripts/check_version.py vX.Y.Z`(tag ↔ main.py 版本 ↔ pyproject.toml 版本 ↔ CHANGELOG 章节四者一致, CI 在 tag 推送后会再校验一次)。
5. 打 tag 并推送: `git tag vX.Y.Z && git push origin vX.Y.Z`。
6. release.yml 自动跑测试 → 构建 GHCR 镜像(`X.Y.Z`/`X.Y`/`latest` 三标签)→ 创建 GitHub Release(正文取 CHANGELOG 对应章节)并附离线镜像包。

README 不维护硬编码版本号, 以 CHANGELOG 顶部章节为准。

## 依赖更新(Dependabot)

- 后端依赖经 uv 锁定(#68): 顶层声明在 `pyproject.toml`, 全量依赖树锁在 `uv.lock`(入库)。**改声明必须重新锁** —— `uv lock` 后连锁文件一起提交, CI 的 `uv lock --check` 会拦截只改声明忘记重锁的变更。本地环境入口是 `uv sync`, 运行命令用 `uv run <cmd>`。
- Dependabot 现管 frontend npm 与 github-actions 两处 weekly, minor+patch 分组降噪; PR 开出即自动跑 CI。npm 锁文件是 `package-lock.json`(`npm ci` 安装)。
- 处理套路: CI 绿的看一眼 diff 即合; 红的点开失败 job 看日志。同类依赖 PR 互相冲突无需处理, 合掉一个后 Dependabot 自动 rebase 其余。
- 两类多想一步: CI 测不到运行层的升级(如 uvicorn 的 HTTP 层)合并后补本地冒烟; 与运行时绑定的依赖(如 @types/node 应跟随实际 Node 大版本)不符合策略就带理由关闭。

## 文档排版

遵守 [AGENTS.md](../AGENTS.md) 的 Markdown 排版规则: 正文一条/一段独占一行, 不做段内硬换行(CHANGELOG 章节会被抽取为 Release 正文, 段内换行在 Release 页渲染成断行)。
