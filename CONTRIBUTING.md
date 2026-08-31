# 贡献指南(CONTRIBUTING)

本仓库开发流程的唯一权威规范是 **[docs/dev-workflow.md](docs/dev-workflow.md)**(对人与 AI Agent 一视同仁),流程规则的修改只改那份文档;[AGENTS.md](AGENTS.md) 是面向 Agent 的硬性指令摘要。本文件只保留一分钟速览。

## 一分钟速览

issue(模板 + `type:`/`priority:` 标签, 版本批次挂 milestone)→ 分支 `<type>/<issue号>-<slug>` → 约定式提交 + 中文(`fix(认证): xxx`)→ PR 正文 `Closes #N` → CI 三 job 全绿 → squash 合并;main 受分支保护,禁止直推。版本批次 milestone 全关后按 dev-workflow 的发版清单发版(tag 前跑 `python scripts/check_version.py vX.Y.Z`)。

## 本地开发

环境搭建、测试与前后端启动命令见 [README 本地开发](README.md#本地开发);CI 三件事本地复现(pytest / ruff / 前端 lint+build)见 [docs/dev-workflow.md](docs/dev-workflow.md) 的「PR 与 CI 门禁」。
