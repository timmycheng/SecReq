# AGENTS.md — 仓库协作约定(对人与 Agent 均生效)

## 开发流程(硬性约定)

本仓库所有改动一律走 GitHub 标准流程, **禁止直推 main**(分支保护对管理员同样生效):先开 issue(模板 + `type:`/`priority:` 标签, 版本批次挂对应 milestone)→ 从最新 main 切分支, 命名 `<type>/<issue号>-<slug>`(如 `fix/18-schema-upgrade`)→ 提交与 PR 标题用约定式前缀 + 中文描述(如 `fix(认证): 初始密码环境变量化`)→ PR 正文写 `Closes #N` → 等 CI 三个 job(后端测试 / 后端 Lint / 前端检查)全绿后 squash 合并。

发版仅由 tag 触发:打 tag 前必须跑 `python scripts/check_version.py vX.Y.Z`, 保证 tag、`main.py` 的 version、CHANGELOG 章节三者一致;版本批次以 milestone 管理,milestone 全部关闭才具备发版条件。

**完整细则以 [docs/dev-workflow.md](docs/dev-workflow.md) 为唯一权威来源**(issue/分支/提交/PR/CI/发版/依赖更新的全部规则),执行流程前先读它;CI 红了看日志修复,不绕过门禁。

## Markdown 排版

写入本仓库的 Markdown 文档(CHANGELOG.md、docs/、README.md 等),正文**一条/一段独占一行**,不做段内硬换行;长段落由编辑器软换行,不要手动在固定列宽处折行。

原因:CHANGELOG.md 的对应版本章节会被 `.github/workflows/release.yml` 原样抽取为 GitHub Release 正文,而 GitHub Release 页把段内单个换行渲染成真实断行,中文句子会在任意词组处被切断(仓库的文件视图会合并软换行,所以只有 Release 页暴露此问题)。

不受此约束的内容:表格行、列表的每个条目、代码块内部、标题。
