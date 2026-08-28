# 安全需求管理平台(SecReq)

面向银行软件项目的**开发**与**安全**两类角色:
通过 8 步向导采集项目信息(支持粘贴需求段落自动生成功能点、数据字典自动分级),
按知识库规则引擎自动生成安全需求清单(产物以 Web 展示 + 一键复制到 Word)。

整体设计见 `DESIGN.md`。当前进度:**基线三批 + v2.0 平台化改造 + v2.1 走查整改交付**。

## v2.1 走查整改(2026-08)

| # | 整改点 | 落地 |
| - | ------ | ---- |
| 1 | 账号密码登录 | `PlatformUser.password_hash`(pbkdf2) + `user_sessions` 表; 登录页签发 Bearer token(12h), 全接口鉴权(读写都拦); 登录失败 5 次锁定 5 分钟; 右上角可改密 |
| 2 | 角色精简为 开发/安全 | `PLATFORM_ROLES = {developer, security}`; 存量 6 角色自动迁移(风管/审计账号停用); 数据权限: **开发只能看到/操作自己创建的项目, 安全全量可见**(越权一律 404) |
| 3 | 门禁下线 | 评审路由/页面/服务摘除, 项目状态机简化; 数据权限(见上)替代门禁的准入控制 |
| 4 | Dashboard 布局 | 左侧菜单(项目管理/系统管理) + 顶栏用户区; 标题改为「安全需求管理平台」 |
| 5 | 向导重构为 8 步 | 新建项目**去弹窗**直通第 1 步, 项目编码自动生成(`XM2026-001`); 第 1 步合并原 1/2/6(基本信息+外部系统连接清单+定级问卷内联/可直接指定+定级后即时预览策略与合规基线); 原权限矩阵去掉"角色数量"并可**从功能清单导入资源**; 组件按层级分组点选(自带默认许可证与风险提示); API 接口与基础设施拆为两步, 服务器填规格(CPU/内存/OS/磁盘/数量), 网络设备设计期地址可预留 |
| 6 | 智能录入 | 功能清单**粘贴需求段落自动生成**候选功能点(OpenAI 兼容大模型优先, 未配置/失败降级关键词规则); 数据字典**粘贴/上传自动解析分级**(字段名模式库推断 JR/T 五级/PII/脱敏建议, 确认后入库) |
| 7 | 产物 Web 化 | **Word 生成整体移除**(docgen 下线); 产物页改为 Web 视图: 需求清单**平铺全文**(不再折叠/截断), 来源中文化(`source_label`, 替代 `data_asset#3`), **去责任人、统一确认动作 + 批量确认**; 「复制到 Word」按钮(HTML 剪贴板, 粘贴即保留标题/表格/标红); 保留 SBOM JSON 与 Jira Excel 跟踪表 |
| 8 | 系统管理(安全角色) | 知识库可视化配置(列表/搜索/启用停用/编辑, 写回 YAML 自动备份+全量校验); 定级题库编辑; 密码策略基线按定级可配置; OpenAI 兼容大模型接入配置; 用户管理(新增/重置密码/启停); 审计日志(登录/生成/确认/管理变更) |
- 基线第一批: 后端数据模型 + 知识库 YAML + 规则引擎 + pytest 测试;
- 基线第二批: SBOM(CycloneDX 1.5)生成、OSV.dev 漏洞查询(24h缓存/失败降级)、
  Word 文档生成与全流程编排(`services/pipeline.py`);
- 基线第三批: FastAPI 路由与文档/Excel 下载 API + React 8 步向导前端
  (权限矩阵交叉表格)+ 定级问卷打分 + SBOM 文件导入 + Jira 跟踪表。

## v2.0 改造点清单(安全准入管理平台)

| # | 改造点 | 落地 |
| - | ------ | ---- |
| 1 | 数据分级替换为 JR/T 0197-2020 五级 | `shared/constants.py` `DATA_LEVELS` 五级 + 典型举例(附录A节选); `DataAsset` 新增 `legacy_classification`/`c3_tag`; 存量库迁移见 `scripts/migrate_classification.py`(公开→1级、内部→2级、敏感→3级、机密→4级; 机密且生物识别类且敏感PII → 附加 C3 标签; 原值留痕; 幂等, 启动时自动执行) |
| 2 | 安全需求新增"合规出处" | `SecurityRequirement.regulatory_ref`(JSON); 知识库全部模板必填 `regulatory_ref`(loader 强校验), 条款号不确定的一律写"参考《文件》+待合规部门确认", **不编造条款号** |
| 3 | 监管报送触发器 | 新 trigger 类型 `regulatory_trigger` 8 条(SEC-REG-001~008): L5重要数据目录备案 / 出境评估申报(含境外外包) / 外包风险评定(SaaS+金融) / 移动应用台账 / 金融科技申报(AI) / 三级投产变更报告 / 敏感PII的PIA / 三级等保测评备案; 命中即**置顶**生成"监管报送"类需求, 须项目经理逐条确认后立项门禁才放行 |
| 4 | 评审门禁与留痕 | `ReviewGate` + `ReviewEvidence`(链式SHA256哈希防篡改, 创世64个0); 门禁**硬校验**在接口层: 不满足返回 `409 {"gate","status":"blocked","missing":[...]}`, 不允许"提示后仍可提交"; POC/上线门禁仅建数据结构 |
| 5 | 6 角色RBAC | `PlatformUser`(pm/developer/security_reviewer/security_lead/risk_manager/auditor); `X-Auth-User` 头携带身份; 审计只读(任何业务 POST 403); pm 不能审自己提交的门禁; 评审员通过后负责人才能终审(两步签核, 且终审人≠第一步评审人) |
| 6 | 文档模板升级 | 《需求规格说明书》按"监管报送类/等保条款类/通用安全类"三组排序 + **合规依据列** + 评审记录页(签字栏); 《总体设计说明书》数据字典改 JR/T 五级表述 + 新增"监管报送事项清单"章节; 《系统定级建议书》新增"判定依据"(GB/T 22240 / JR/T 0071 / 公通字〔2007〕43号 / 网安法21条)与"安全中心复核意见"栏; **新增第5份文档《项目安全评审表》**(门禁状态/需求覆盖统计/漏洞概况/遗留问题, 评审会材料) |

### 平台角色与演示账号

| 账号 | 角色 | 权限 |
| ---- | ---- | ---- |
| dev_li / dev_zhang | 开发 | 新建项目(仅可见自己创建的)、填报向导、生成基线、确认需求 |
| sec_chen / sec_zhao | 安全 | 查看全部项目、系统管理(知识库/题库/策略/用户/审计/LLM) |

初始密码统一 `Sec123456`(登录后可在右上角修改)。存量库旧角色自动迁移:
pm/developer → 开发; security_reviewer/security_lead → 安全; 风管/审计账号停用;
存量项目自动归入第一个开发账号。

### 存量数据迁移

```bash
.venv/Scripts/python scripts/migrate_classification.py --dry-run  # 预览
.venv/Scripts/python scripts/migrate_classification.py            # 执行(幂等)
```

应用启动时也会自动执行同一迁移(`main.py` lifespan 与脚本共用
`services/classification_migration.py`, 口径唯一)。

### 演示走查(代替录屏)

```bash


## 目录结构

```
SecReq/
├─ DESIGN.md              # 需求与设计文档
├─ main.py                # FastAPI 入口(启动时自动补列+迁移+种子用户+策略注入; 兼管前端构建托管)
├─ shared/constants.py    # 前后端共享枚举(JR/T 五级/平台角色/许可证风险库/常用组件目录, 经 /api/meta/constants 供数)
├─ models/                # SQLAlchemy 2.0 模型(project/feature/data_dictionary/permission/auth/sbom/
│                         #   inventory/requirement/review(遗留表)/session/setting/audit)
├─ schemas/               # Pydantic 请求/响应模型(API 契约层)
├─ routers/               # projects/steps/generate/meta/auth/admin(common.py 含 Bearer 认证与数据权限依赖)
├─ rules/
│  ├─ knowledge_base.yml  # 安全需求知识库(61条模板, 全部含 regulatory_ref, 支持 enabled 停用)
│  ├─ grading_questions.yml # 定级问卷题库(分值/判定依据文案, 系统管理页可编辑)
│  ├─ loader.py           # YAML 加载与完整性校验(regulatory_ref 必填)
│  ├─ context.py          # 规则引擎输入上下文(项目输入数据快照)
│  ├─ policy.py           # 密码/会话策略生效值计算(默认基线可在系统管理页覆盖)
│  └─ engine.py           # 规则引擎: 模板匹配 → 占位符渲染 → SecurityRequirement(报送类置顶, 停用模板跳过)
├─ services/
│  ├─ grading.py          # 问卷加权打分 → 建议定级 + 判定理由
│  ├─ project_service.py  # 项目 CRUD / 数据权限 / 存量归属与类型回填 / 级联删除
│  ├─ step_store.py       # 向导各步骤整卷保存(整体替换, 幂等)
│  ├─ feature_extract.py  # 粘贴需求段落 → 候选功能点(LLM 优先, 关键词规则降级)
│  ├─ dictionary_import.py# 数据字典粘贴/上传解析 + 字段自动分级(JR/T 五级/PII/脱敏建议)
│  ├─ seed_data.py        # 种子数据「个人网银系统」(JR/T 五级 + C3 标签)
│  ├─ sbom.py / sbom_import.py / osv.py   # SBOM 构建/导入/OSV 查询
│  ├─ tracking_export.py  # openpyxl 需求跟踪表(含合规依据列)
│  ├─ pipeline.py         # 全流程编排: 漏洞同步→规则引擎→SBOM JSON 落盘
│  ├─ session_service.py  # Bearer 会话签发/校验/吊销 + 登录失败锁定
│  ├─ auth_service.py     # 账密哈希(pbkdf2)/种子用户/存量角色迁移
│  ├─ kb_admin.py         # 知识库/题库写回 YAML(自动备份+全量校验+失败回滚)
│  ├─ settings_service.py # 系统级键值设置(LLM 接入/策略基线)
│  ├─ audit_service.py    # 审计留痕(登录/生成/确认/管理变更)
│  └─ classification_migration.py  # 存量库升级(补列+老4级迁移+角色/归属/类型迁移)
├─ frontend/              # React 19 + TS + AntD(登录页 + dashboard 布局 + 8步向导 + 产物Web页 + 系统管理)
├─ scripts/
│  ├─ run_seed_demo.py         # 一键验证: 建库 → 种子 → 漏洞同步 → 生成 → 打印清单
│  └─ migrate_classification.py # 老四级分级迁移脚本(交付物)
├─ output/<项目编码>/       # 每次生成的 SBOM JSON 落盘位置
└─ tests/                 # pytest(126个用例: 认证与数据权限/智能录入/管理端/五级联动/报送触发等)
```

## 快速开始

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # Linux/macOS 用 .venv/bin/pip

# 运行全部测试(OSV 查询使用 MockTransport, 不出网)
.venv/Scripts/python -m pytest tests -q

# 种子数据演示(在线): 调用真实 OSV.dev, 种子中故意保留的旧版组件会命中真实 CVE
.venv/Scripts/python scripts/run_seed_demo.py

# 种子数据演示(离线): 跳过网络, 走降级路径"漏洞查询暂不可用"
.venv/Scripts/python scripts/run_seed_demo.py --offline

# ── 第三批: 启动 Web 应用 ─────────────────────────────
# 后端 API(默认 sqlite:///项目根/secreq.db, 可用 SECREQ_DATABASE_URL 覆盖)
.venv/Scripts/python -m uvicorn main:app --reload --port 8000

# 前端开发服务器(Vite, 已代理 /api → 127.0.0.1:8000)
cd frontend && npm install && npm run dev   # http://localhost:5173

# 或生产模式: 构建后由 FastAPI 单进程托管(npm run build 后重启 uvicorn 即可)
cd frontend && npm run build
```

产物统一写入 `output/PRJ-IBANK-2026/`: `sbom.cdx.json`(CycloneDX 1.5) 与
`系统定级建议书 / 需求规格说明书_安全需求章节 / 总体设计说明书_安全设计章节 /
SBOM及漏洞清单 / 项目安全评审表` 五份可直接打开的 Word。

## 第一批实现说明

**知识库** `rules/knowledge_base.yml`: 触发器 trigger 分八类——功能分类 /
权限矩阵分析 / 认证方式 / 密码策略基线 / 数据资产 / API接口 / 合规目标 /
SBOM漏洞联动。每条模板含 req_id(按 ASVS 4.0.3 章节分组)、中文描述、优先级、
验收标准、建议阶段、trigger_reason 与 `{{占位符}}`。
安全中心可直接修改此文件扩充规则, 无需改代码; 加载器对 id 格式、必填字段、
未知触发类型做完整性校验, 出错时汇总报告全部问题。

**规则引擎消费方式**: 遍历全部模板按 trigger.type 分派判定函数, 条件满足即实例化;
同类规则命中多个实例时生成多条独立需求并分别关联各自 source_entity_id,
满足"无来源的需求不允许存在"的追溯约束。占位符渲染为严格模式, 缺值即报错,
用于在开发期暴露知识库缺陷。权限矩阵内置三种扫描算法:
关键资源高危操作免审批检测、SoD 职责分离冲突检测、super_admin 特权账号检测。

**种子数据**(`services/seed_data.py`): 个人网银系统 —— 12 功能(覆盖支付/上传/
导出/第三方登录等)、6 数据资产(含机密级金融账户与生物识别)、5角色×8资源权限矩阵
(故意构造免审批违规与 SoD 冲突)、10 技术栈组件(故意保留 log4j-core 2.14.1 供
第二批漏洞演示)、4 API 接口(含匿名公网接口)。

## 第二批实现说明

**SBOM**(`services/sbom.py`): 从组件清单构建 CycloneDX 1.5 JSON, 层级映射为
标准 component.type(library/application/container), 录入层级与来源保留在
`secreq:*` 自定义 properties; 未填 purl 的组件自动补 `pkg:generic/<名>@<版本>`
并回写数据库。许可证按 SPDX id 形态校验, 无法识别的自由文本写入 `license.name`。

**OSV 漏洞查询**(`services/osv.py`): POST `api.osv.dev/v1/query` 按 purl 逐个查询,
结果规范化后落库 `vulnerabilities` 表(唯一约束防重复)。几个关键工程细节:
- 事件解析兼容 OSV 单键事件形态(`{"introduced":..},{"fixed":..}`), 多组
  introduced→fixed 序列切分为多个受影响窗口;
- **坐标过滤**: 同一漏洞常列出多个派生包坐标(如 log4shell 的 guicedee/pax 分支),
  按精确 purl > 全限定名 > 裸名的优先级锁定本组件条目, 避免分支包污染修复建议;
- **修复版选取**: 优先取"包含目标版本"窗口的 fixed 端点(log4j 2.14.1 → 升级到
  2.15.0), 多线并存时兜底取数值最高的修复版;
- severity 取 GHSA `database_specific`(含 MODERATE 别名归一), 缺失时按 CVSS
  分数划档(≥9 critical / ≥7 high / ≥4 medium);
- 缓存: 组件维度 24h TTL(`last_osv_query_at`), 未过期直接沿用库内记录;
- 降级: 网络/HTTP 异常仅记入 failed 并保留旧记录, 不阻塞规则引擎与文档生成。

**Word 文档**(`services/docgen.py`, 版式参数见 `docs/templates/doc_style.yml`):
四份文档均含封面(项目名/编码/生成时间/编制人/审核人签字栏)与页码页脚——
《系统定级建议书》(问卷答案表→定级结论→判定理由→人工修正留白栏);
《需求规格说明书-安全需求章节》(按 ASVS 4.0.3 章节分组的需求表, 紧急级行标红,
附录A 为角色×资源权限矩阵交叉表, 需审批操作加 * 标注); 《总体设计说明书-安全
设计章节》(软件版本清单、资产→表→字段三级数据字典、API 安全属性表、基础设施
资产清单、参数化登录与密码策略说明、认证方式逐项设计说明); 《SBOM及漏洞清单》
(高危置顶整行标红, 并列出漏洞整改联动的需求编号)。密码策略文案与规则引擎共用
`rules/policy.py` 的生效值口径, 两处永不打架。

已知取舍: OSV 部分记录只提供 CVSS 向量串无数值分, 文档 CVSS 列以"—"占位,
严重程度以等级列(database_specific 档位)为准。

## 第三批实现说明

**API 层**(`main.py` + `routers/` + `schemas/`): 项目 CRUD、定级问卷(题库来自
`rules/grading_questions.yml`, 加权打分 + 组合规则如"敏感个人信息+资金交易直接
三级")、向导 Step2~Step8 各数据面的整卷保存(整体替换幂等, 权限矩阵 entry 以
提交体下标定位)、`/generate` 全流程编排(成功后项目状态置 generated)、
`/requirements/preview` 规则引擎干跑(确认页"已触发 XX 条"不落库)。
下载接口: `GET /export/docx/{grading|requirement|design|sbom_vuln|review}` 按库内最新
数据即时重渲染 Word; `GET /export/xlsx` 输出 Jira 可导入的需求跟踪表
(req_id/需求描述/优先级/责任方/建议阶段/验收标准/状态/备注, 第二 Sheet 附字段
映射说明); `GET /sbom` 实时构建 CycloneDX JSON。枚举唯一来源为
`GET /api/meta/constants`, 满足前后端共享一份常量定义的约束。

**前端**(`frontend/`, React 18 + TS + Vite + AntD): 8 步向导——基本信息表单 /
问卷(Radio+分值展示+人工修正)/ 功能与组件动态增删行 / 数据字典资产→表→字段
三级嵌套编辑 / **权限矩阵交叉表格**(角色行×资源列, 单元格 Popover 勾选 7 类操作,
高危操作可挂"需审批"以 * 标注, 前端实时提示免审批违规与 SoD 冲突)/ 认证与密码
策略设计器(按定级预填默认基线, 留空项生成时自动取 `policy.py` 同口径默认)/
SBOM 文件上传导入(CycloneDX/SPDX)+ 常用组件自动补全 / 接口清单关联敏感数据资产。
确认页汇总全部输入并干跑预览触发规模, 一键生成后跳转产物页: 需求清单(类目/
优先级筛选、紧急行标红、展开看验收标准与触发原因)、漏洞清单(严重度排序)、
5 份 Word + 跟踪表 Excel + SBOM JSON 下载; 顶部「评审门禁与签核」进入门禁页
(硬校验缺失明细/提交/两步签核/留痕哈希链), 顶栏可切换平台身份。

**种子数据实际运行结果片段(GUI)**: 向导确认页显示「已触发 58 条安全需求」
(功能安全22 / 数据安全11 / 权限7 / 接口7 / 口令策略4 / 合规3 / 组件风险3 /
认证1), 与命令行演示口径一致。

## 种子数据实际运行结果片段

```text
[SBOM] CycloneDX 1.5 已输出: output/PRJ-IBANK-2026/sbom.cdx.json
[OSV] OSV查询: 已更新10, 缓存命中0; 共命中 14 条记录, 严重度最高:
      CVE-2021-44228(严重)、CVE-2021-45046(严重)、CVE-2026-16723(严重)…
共生成 58 条安全需求: 功能安全22 / 权限与访问控制7 / 口令与会话策略6 /
数据安全10 / 合规要求9 … 其中【第三方组件风险】3 条(log4j-core/fastjson/lodash)

漏洞表摘录(SBOM及漏洞清单.docx, 高危整行标红):
  [严重] CVE-2021-44228  log4j-core@2.14.1   ≥2.13.0 且 <2.15.0  → 修复版 2.15.0
  [严重] CVE-2021-45046  log4j-core@2.14.1   ≥2.13.0 且 <2.16.0  → 修复版 2.16.0
  [高危] CVE-2022-25845  fastjson@1.2.70     ≥1.2.25 且 <1.2.83  → 修复版 1.2.83
```

## 路线图

- POC/上线门禁流程启用(数据结构已就绪: `gate_type` 枚举与 `ReviewGate` 表)、
  厂商门户与外部系统对接(OA/4A/SIEM)、电子签章接入(现为"姓名+工号+时间戳+哈希")、
  需求状态流转界面、知识库编辑界面、LLM 润色接入(均按本期范围外约定暂缓)。

