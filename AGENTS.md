# AGENTS.md — 仓库写作约定

## Markdown 排版

写入本仓库的 Markdown 文档(CHANGELOG.md、docs/、README.md 等),正文**一条/一段独占一行**,不做段内硬换行;长段落由编辑器软换行,不要手动在固定列宽处折行。

原因:CHANGELOG.md 的对应版本章节会被 `.github/workflows/release.yml` 原样抽取为 GitHub Release 正文,而 GitHub Release 页把段内单个换行渲染成真实断行,中文句子会在任意词组处被切断(仓库的文件视图会合并软换行,所以只有 Release 页暴露此问题)。

不受此约束的内容:表格行、列表的每个条目、代码块内部、标题。
