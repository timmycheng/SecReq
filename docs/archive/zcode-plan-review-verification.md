# SecReq 前端易用性全面改进方案

**目标**：降低学习成本、提升易用性。**纯前端改动**（`frontend/src`，后端 API 契约不动），保持 React 18 + TS + AntD + 现有 hash 路由。

## 1. 向导骨架与保存安全（最高优先级：当前切换步骤会静默丢弃未保存修改）

**WizardPage.tsx 重构 + 新增小型组件：**

- 新增 **StepHandle 机制**：每个步骤组件通过 Context 向容器注册 `{ save(): Promise<boolean>, isDirty(): boolean }`。各步保留自己的本地状态与保存 API 调用，只是把"保存并下一步"按钮上收到容器统一渲染。
- **共享吸底操作条**：`上一步` / `保存并下一步`（最后一步 ConfirmStep 保留内部"生成"按钮不变）。校验失败时 save() 返回 false，停留本步并展示已有错误提示。
- **统一脏拦截 `confirmLeave()`**：点步骤条跳步、上一步、返回列表、点顶部 logo 时，若当前步有未保存修改 → `Modal.confirm`：保存并继续 / 放弃修改 / 取消。
- **步骤条增强**：每步加 description（一句话：收集什么、喂给下游什么）；已保存过数据的步打勾（依据 ws 各切片非空推断）。
- **位置记忆**：localStorage 记住 `secreq.wizard.<id>.step`，再次进入回到上次步骤。
- **上下文**：向导内显示项目名称 + 返回列表入口（带脏确认）；脏状态时挂 `beforeunload` 保护关页。
- App.tsx 的 logo 点击改为经全局 dirty-guard registry 询问（模块级导出 setDirtyGuard，向导挂载时注册）。

## 2. 新手引导

- 向导首次进入显示可关闭的流程说明 Alert（8 步收集 → 确认页试算 → 生成需求/SBOM/4 份 Word），localStorage 记住已读。
- ProjectListPage 空状态：Empty 组件 + 一句话工具定位 + 「新建第一个项目」CTA（替换 antd 默认"暂无数据"）。
- 补齐缺失步骤的顶部说明（一句话目标 + 数据用途），格式统一。

## 3. 术语悬浮解释（新增 `ui/GlossaryTip.tsx`）

内联文字 + "?"图标 Tooltip 术语卡，文案在前端维护（解释性文案，不违反"枚举唯一来源 /api/meta/constants"约束）。覆盖：SBOM、CycloneDX/SPDX、OSV.dev、purl、SoD 职责分离、免审批、ASVS、CVE/CVSS、敏感PII、2FA、QPS、等保定级、试算（原"干跑"）。应用到 Step5/6/7/8、ConfirmStep、ResultPage 对应位置。

## 4. 各步骤细节修复

- **Step2 问卷**：建议定级横幅改为始终显示（修改答案时标注"以提交后重算为准"，而非现在修改后消失）；显示答题进度 x/y；提交按钮禁用时 Tooltip 说明未答题目。
- **Step3 功能清单**：功能分类选项增加说明（前端 hints 映射：该分类会触发哪类需求）；rowKey 修复（name 重复冲突）。
- **Step4 数据字典**：字段编辑从第三层堆叠弹窗改为资产编辑弹窗内的行内编辑（最多两层）；修复脱敏规则下拉不回显（`value={undefined}` 硬编码）；合并 onOk/footer 两处重复保存逻辑。
- **Step5 权限矩阵**：警告面板改 antd Alert 列表 + 通俗文案 + 术语 gloss；矩阵上方加图例（`*` = 需审批）；rowKey 修复。
- **Step6 认证密码策略**：「恢复默认基线」改名「清空手动覆盖（生成时按定级默认取值）」，文案与"清空"行为对齐。
- **Step7 组件清单**：上传区加说明（SBOM 是什么/从哪来/没有文件可手动添加或跳过）；导入逻辑改用统一 api 封装；rowKey 修复。
- **Step8 接口清单**：敏感资产下拉为空时提示"先在 Step4 录入"；按钮统一为「保存并下一步」；"匿名"tag 加解释。
- **ConfirmStep**：OSV 开关去掉双反逻辑（正向绑定"在线查询"）；汇总各行加「去修改」跳转对应步骤；生成前完整性检查（问卷未完成/功能 0/组件 0 → 警告 + 跳转链接，不强制阻断）；"干跑"改"试算预览"。
- **ProjectListPage**：修复删除失败仍提示成功的 bug；展开行"授权单元格"改"权限授权项"。
- **ResultPage**：顶部加返回向导/列表导航；需求为 0 时空态 CTA「前往向导生成基线」；漏洞加载失败显示错误 Alert（现在静默清空）；ASVS/CVE/CVSS 表头 gloss。

## 5. 验证

- `npm run build` 通过（TS 无错）。
- 用运行中的 Vite 开发服务器（5173，HMR 生效）浏览器走查：种子项目向导全流程、脏拦截弹窗各路径、Step5 矩阵/警告、Step4 两层编辑、ConfirmStep 试算与生成、结果页下载与空态。

## 改动范围

`frontend/src` 约 16 个文件：WizardPage、App、ProjectListPage、ResultPage、9 个 step 组件，新增 GlossaryTip 与步骤注册 Context（约 2 个新文件）。后端、测试、文档不动。