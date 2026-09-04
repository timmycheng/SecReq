## 改动说明

<!-- 一段话说清做了什么、为什么这么做 -->

## 关联 issue

<!-- 合并后自动关闭用 Closes #N; 仅建立关联用 Refs #N; 无 issue 的杂项可删去本节 -->

Closes #

## 自测记录

<!-- 本地跑过什么, 例如: python -m pytest tests -q(186 通过) / cd frontend && npm run lint && npm run build -->

## 检查清单

- [ ] CI 必查 job 全绿(后端检查 / 前端检查; docs-only 改动被跳过时显示 skipped, 视同通过)
- [ ] 涉及用户可见变更时, 已在 CHANGELOG.md 对应版本章节补充(遵守一条/一段独占一行)
- [ ] 版本号影响已评估; main.py version 与 CHANGELOG 章节仅在打 tag 发版时同步, 并会被 CI 校验
- [ ] 涉及部署/配置变更时, 已同步更新 README 或 .env.example
