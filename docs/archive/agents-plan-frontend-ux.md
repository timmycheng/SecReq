## 计划: 评审核实结论归档(不改代码)

用户已确认: 暂不修复, 仅保留核实结论。

### 唯一改动
在 `OPTIMIZATION_REVIEW.md` 末尾追加一节 **「附录: 核实结论 (2026-08-30)」**, 内容:

1. **总体结论**: 30 余条论断逐条对照代码验证, 仅 1 处与代码不符、1 处程度夸大, 其余全部属实。
2. **修正 P2-4**: 登录失败审计已存在 (`routers/auth.py:48` 已有 `login_failed` 埋点); 该项其余缺口 (项目删除 `projects.py:79`、导出 `export_docx`/`export_xlsx`、组件清单变更) 确认属实。
3. **补充 P0-3**: "40 线程打满"表述夸大 (需约 40 个并发生成请求), 但风险真实且更隐蔽——串行查询期间 Session 持有 SQLite 读事务且无 `busy_timeout`, 一个长生成请求即可令他人写操作报 `database is locked`; 与 P1-2 需一并修复。
4. **补充 P0-1/P0-2 依赖关系**: 不引入稳定 uid 前, P0-1 的 upsert 只能按 `(template_id, source_entity_id)` 匹配, 仅保护"未改步骤直接重新生成"场景; 完整解法依赖 P0-2 的 uid 迁移。
5. 其余各项的验证证据行号一览 (engine.py:171/130、step_store.py 7 处 replace、osv.py:326、database.py、requirements.txt 等), 供后续修复直接定位。

### 不做的事
- 不修改任何代码、配置或 `IMPLEMENTATION_PLAN.md` (该方案本身经核实无误, 保留待后续使用)。
- 不运行 pytest (评审附录的测试基线留待实施阶段首步复跑确认)。