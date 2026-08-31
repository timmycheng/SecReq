# 历史文档归档

此前各 agent 在本地工作目录(均在 .gitignore 中)生成的方案与记录, 已按开发管理逻辑收敛: 仍有效的工作项拆为独立 issue 跟踪, 现行总纲同步至 [../master-plan.md](../master-plan.md), 其余按原样归档于此。

**归档原则**: 文件内容原样保留(仅按来源重命名, 段内换行未重排), 不作为现行规范 —— 事实口径以 README / CHANGELOG / 代码为准, 流程以 [../dev-workflow.md](../dev-workflow.md) 为准, 完成状态以 issue / milestone 为准。

从历史文档中拆出的工作项: #66(数据一致性 uid 迁移)、#67(漏洞库配置 B 全量构建)、#68(依赖锁定)、#69(麒麟数据源)、#70(SCA 对接)、#71(OSV 在线模式异步化)、#72(E2E 主链路)、#73(功能路线图跟踪)。

| 文件 | 内容 | 状态与去向 |
| ---- | ---- | ---------- |
| agents-initial-design.md | 项目初始设计 prompt: 8 步向导 / 规则引擎 / SBOM / 文档生成的原始需求与数据模型 | 已实现, 事实口径以 README 与代码为准 |
| agents-upgrade-prompt-20260828.md | 评审视角升级 prompt: JR/T 0197 五级分级 / regulatory_ref / 评审门禁 / 角色扩展 | 已实现(v2.0); 门禁流程后经走查决策下线, 表结构保留 |
| agents-walkthrough-todo.md | 界面走查问题清单(用户体系 / 向导 / 产物 / 门禁 / 系统管理) | 已按 v2.1.x 走查整改落地; 新的界面反馈请开新 issue |
| agents-plan-walkthrough-rectification.md | 走查整改开发计划(5 阶段, 现状结论 + 决策记录) | 已实施(v2.1.0 / v2.1.2) |
| agents-plan-frontend-ux.md | 前端易用性改进方案(保存安全 / 新手引导 / 术语解释) | 已实施(9e608a8) |
| agents-plan-review-verification.md | 评审核实结论归档计划 | 已执行(见优化评审附录) |
| agents-optimization-review.md | v2.1.2 全量优化评审(P0/P1/P2 评级与逐项验证证据) | 已修项见 v2.1.3 / v2.2.1; 未修项 → #66 / #68 / #71 |
| agents-implementation-plan.md | 五阶段实施方案(文件级改动清单与 uid 迁移详案) | 阶段 0-2、4 已完成; 阶段 3(uid 迁移) → #66 |
| agents-offline-vuln-db-plan.md | 离线漏洞库方案 v2(OSV 数据源实测数据 / 麒麟缺口 / SCA 核查清单) | v2.2.0 已落地; 收尾项 → #67 / #69 / #70 |
| agents-memory-index.md | agent 长期记忆: 硬约束 / 踩坑 / 环境怪癖 / 版本路线 | 参考价值; 项目约定已上移至 AGENTS.md 与 dev-workflow.md |
| agents-log-2026-08-30.md | 2026-08-30 工作日志(评审 / 方案 / 实施 / 发版全程记录) | 存档 |
