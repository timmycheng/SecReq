# 贡献指南(CONTRIBUTING)

本仓库虽然是单人维护, 但按 GitHub 标准协作流程运作: 所有改动经 issue → 分支 → PR → CI → squash 合并进入 main, main 始终处于可发布状态。文档排版遵循 [AGENTS.md](AGENTS.md) 的约定(正文一条/一段独占一行)。

## 流程总览

```text
开 issue(选模板, 打 type:/priority: 标签)
  → 建分支 <type>/<issue号>-<slug>, 如 fix/12-path-traversal
  → 本地开发并自测(见下「质量门禁」)
  → 开 PR(自动套模板), 正文写 Closes #N
  → CI 三个 job 全绿(后端测试 / 后端 Lint / 前端检查)
  → 自审后 squash 合并, 删除分支, issue 自动关闭
  → 需要发版时走「版本与发版」清单
```

## 分支规范

- 命名格式 `<type>/<issue号>-<slug>`, type 与提交前缀一致: `feat/`、`fix/`、`docs/`、`chore/`、`ci/`。
- slug 用小写英文短横线, 从最新 main 切出; 合并后删除。
- main 受分支保护: 禁止直推, 必须 PR 且 CI 通过(squash 合并保持线性历史)。

## 提交信息规范

采用约定式提交(Conventional Commits) + 中文描述, 格式 `<type>(<scope>): <一句话概述>`,scope 用模块中文名。

| type | 用途 | 示例 |
| --- | --- | --- |
| feat | 新功能 | `feat(漏洞库): 支持 Bitnami 生态版本归一化` |
| fix | 缺陷修复 | `fix(认证): 初始密码环境变量化并随机回退` |
| docs | 文档 | `docs(README): 更新内网部署说明` |
| refactor | 重构(不改行为) | `refactor(规则引擎): 抽取上下文构造器` |
| chore | 工程杂项 | `chore(依赖): 升级 fastapi 至 0.115` |
| ci | 流水线 | `ci: 前端 job 增加 npm 缓存` |

- 提交即被 CI 检查, 一个 PR 内多个提交无需完美, squash 合并时以 PR 标题为准压成一个提交。
- PR 标题同样遵循上述格式; 正文用 `Closes #N` 关联 issue, 合并即自动关闭。
- 历史提交(2026-08 之前)未采用本规范, 不做追溯改写。

## Issue 规范

- 缺陷用「缺陷报告」模板, 功能建议用「功能建议」模板, 流程/任务类杂项可用空白 issue。
- 标签两组: `type: bug / feature / docs / chore / ci` 标性质, `priority: P0 / P1 / P2` 标优先级(P0 阻塞项先修, 与 docs/ 下修复方案文档的优先级口径一致)。
- 每个功能/修复原则上对应一个 issue; 小改动可以先建分支, 开 PR 时补 issue。

## 质量门禁

PR 与 push main 触发 `ci.yml`, 三个 job 必须全绿:

- **后端测试**: `python -m pytest tests -q`, 与发版流水线同一口径(OSV 走 MockTransport 不出网)。
- **后端 Lint**: ruff, 宽松口径见 `ruff.toml`(只拦真实错误类, 不做行宽与风格审判)。
- **前端检查**: `npm run lint`(oxlint) + `npm run build`(内含 tsc 全量类型检查)。

本地对应命令:

```bash
.venv/Scripts/python -m pytest tests -q        # Linux/macOS 用 .venv/bin/python
.venv/Scripts/python -m ruff check .
cd frontend && npm run lint && npm run build
```

## 版本与发版

遵循 SemVer: 新功能升 MINOR, 缺陷修复升 PATCH, 不兼容变更升 MAJOR。发版清单:

1. 确认 main CI 全绿, 将发内容都已合并。
2. 修改 `main.py` 中 FastAPI 的 `version="X.Y.Z"`。
3. 在 `CHANGELOG.md` 顶部新增 `## [X.Y.Z] - 日期` 章节, 内容遵守一条/一段独占一行(该章节会被 release.yml 原样抽取为 Release 正文, 段内换行会被 GitHub 渲染成断行)。
4. 本地校验: `python scripts/check_version.py vX.Y.Z`(校验 tag ↔ main.py 版本 ↔ CHANGELOG 章节三者一致)。
5. 打 tag 并推送: `git tag vX.Y.Z && git push origin vX.Y.Z`, release.yml 自动跑测试 → 构建 GHCR 镜像(`X.Y.Z`/`X.Y`/`latest` 三标签) → 创建 GitHub Release 并附离线镜像包。
6. README 不再维护硬编码版本号, 以 CHANGELOG 顶部章节为准。

## 依赖更新

Dependabot 每周对 pip(`requirements.txt`)、npm(`frontend/`)、GitHub Actions 各开一批更新 PR, minor+patch 已分组降噪。处理原则: CI 绿 + CHANGELOG 无感知的直接合并; 跨大版本或涉及安全组件(uvicorn/sqlalchemy 等)的, 看 changelog 后单独评估。
