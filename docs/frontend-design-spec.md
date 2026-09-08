# secreq 前端设计规范(每次生成界面代码前必读)

本规范约束一切界面代码的生成, 与 [AGENTS.md](../AGENTS.md) 项目速览对齐; 状态色与文案用词是全局唯一来源, 各页面不得自造。v3.0 评审闭环(#219)等新页面一律遵循本规范。

## 技术栈(不得偏离)

- React 19 + TypeScript + antd 6(与仓库实际一致, 生成代码时不得按记忆写成 React 18/antd 5)
- 路由: 自研 hash 路由 `frontend/src/router.ts`, 侧边菜单在 `frontend/src/App.tsx`; **不引入 React Router**
- 状态管理用现有方案; 请求一律走 `frontend/src/api.ts` 的 `request<T>()`(统一携带 Bearer), 禁止新引请求库
- 禁止引入新 UI 组件库, 禁止混用 Element/MUI, 不引入 ProComponents(表格用 antd Table)

## 布局模式(页面只允许这几种, 按内容选)

1. 列表页: PageHeader(标题+主操作按钮) + 筛选卡 + 表格卡(body 无内边距)
2. 表单页: 分步 Steps(向导类) / 分组卡片锚点导航(长表单类)
3. 详情页: 左侧锚点导航 + 右侧内容卡片; 关键操作固定在页头; 系统详情页的时间线卡片固定在左栏栏目链接下方, 与栏目链接一起 sticky(#280)
4. 评审/审批页: 内容区 + 右侧固定「评审操作面板」(提交评审/裁定/终审/意见输入)——产物页与评审页一律用这个模式
5. 工作台: 指标卡 + 图表 + 最近评估 + 快捷入口, 数据走 `/api/meta/dashboard` 聚合端点(#280)

> 外壳与菜单(#280): 应用外壳在 `App.tsx` —— 深蓝分组侧边菜单(工作台/安全管理/平台设置) + 顶部面包屑与用户区, 内容区 `maxWidth: 1440` 居中。「平台设置」组(系统设置/漏洞库/备案管理/知识库管理/用户管理/LDAP 对接/LLM/Netbox/日志审计/更新日志)仅安全角色可见; 新增页面 = `ui/` 下新组件 + `App.tsx` MENUS/路由注册 + `api.ts` 方法 + 后端端点。

> 归属说明(#234, #285 更新): 原系统管理 Tab 容器(`ui/AdminPage.tsx`)已拆分为 系统设置(/admin) 与 漏洞库(/vulndb) 两个独立页面, 内容组件在 `ui/admin/`(React.lazy); 页面外壳与其他平台设置页一致(PageHeader + 内容区), 403 由 App 外壳统一兜底。

## 页头与容器(#268)

- 页头一律用 `ui/PageHeader.tsx`(标题/描述/extra 操作区/可选返回), 不得再各页面自拼「返回按钮 + Typography.Title」; 列表页主操作按钮放 PageHeader 的 extra。
- 页面容器统一 `padding: 24`; 品牌主题(ConfigProvider token、PRIMARY 常量、登录页渐变)唯一来源是 `ui/theme.ts`, 页面不得自建 ConfigProvider 或写品牌色字面量。
- 正文次级文案用 `Typography` 语义色(`type="secondary"`), 不自造灰阶 hex; 排版用底色/边框灰(如代码块、表格斑马纹)不受 tokens 约束。
- 数据表格行内操作列用链接按钮(`type="link" size="small"`, `Space split={<Divider type="vertical"/>}` 分隔), 危险操作(删除/停用)加 `danger`; 图标按钮(行内编辑 ✎ 等)可保留 `size="small"` 形态。

## 表格规则

- 列数 > 8 或行高不定时: 表头吸顶 + 横向滚动, 禁止双滚动条嵌套
- 状态列一律用 antd Tag, 状态色映射全局统一(见下方 tokens)
- 分页固定: 每页 10/20/50, 默认 20; 表格空态必须给出「去新增」引导
- 例外(#235): 向导步骤内嵌套小表/弹窗表/系统详情子清单 `pagination=false`(父级已是分页页面或条目天然有限); NetBox 导入弹窗为远端分页(服务端切片), 保留 current/pageSize/total
- 4级/5级资产列表水印「内部数据」已落地: 向导数据字典(Step4)主表按行分级条件渲染(antd Watermark)

## 表单规则

- 必填星号 + label 不换行; 长表单每卡不超过 8 个字段
- 校验后置: 填写过程只在字段失焦时红字提示, 不阻断下一步——这是 v3.0 填报提速的硬要求(#228), 不要加即时阻断
- 所有向导步骤标题后标注预估耗时, 如「数据资产(约 5 分钟)」

## 状态与文案 tokens(全局唯一来源, 不允许各页面自造)

- 色值唯一来源是 `frontend/src/ui/tokens.ts`(Tag 用 antd 预设色名, style 场景用其 HEX 常量, CSS 场景用 index.css 顶部变量); 页面内不得再定义同义映射或写状态语义 hex(#234); 角色标签色 `ROLE_COLOR` 同样在此(#268)
- 品牌色唯一来源是 `frontend/src/ui/theme.ts`(PRIMARY/BRAND_GRADIENT/themeConfig), 与状态 tokens 分工: 品牌归 theme, 语义归 tokens(#268)
- 等保定级(#234 定夺留痕): 一级=灰 / 二级=蓝 / 三级=黄, 与数据分级同 ramp——等保级别表达合规强度而非风险警示, 不用红色; 未来扩到四级/五级续接火山橙/红
- 需求状态: open=灰 / confirmed=蓝 / reviewed=绿 / rectifying=橙(状态机见 v3.0 #217)
- 门禁: pending=灰 / in_review=蓝 / blocked=红 / passed=绿 / rejected=红 / rectifying=橙(in_review/rejected 是 ReviewGate 既有枚举的补充, blocked 为提交校验返回态)
- 数据分级 L1-L5: 1级=灰 / 2级=蓝 / 3级=黄 / 4级=橙 / 5级=红
- 操作按钮: 主操作=页面唯一 primary, 其余 default/danger
- 中文文案统一用词: 「提交评审」「退回整改」「复审通过」, 禁止同义混用(不要出现「送审」「打回」「过审」)

## 敏感信息展示

- 身份证/卡号/手机号列表页默认掩码(前3后4), 详情页点击可见
- 4级/5级资产数据列表必须带水印提示「内部数据」

## 生成自检清单(每次输出界面代码后自查)

- [ ] 用的是四种布局模式之一, 没有发明新布局
- [ ] 状态颜色取自 tokens, 没有自定义色值
- [ ] 没有嵌套双滚动条、没有列宽挤压
- [ ] 空态/加载态/错误态三态都有
- [ ] 主操作按钮全页唯一
