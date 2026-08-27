# SecReq — 安全需求与设计基线生成工具

面向银行软件项目的项目经理与开发人员: 通过结构化表单收集项目信息,
按知识库规则引擎自动生成符合行内模板的安全需求与设计文档章节, 实现安全左移。

整体设计见 `DESIGN.md`。当前进度:**三批全部交付**。
- 第一批: 后端数据模型 + 知识库 YAML + 规则引擎 + pytest 测试;
- 第二批: SBOM(CycloneDX 1.5)生成、OSV.dev 漏洞查询(24h缓存/失败降级)、
  4 份 Word 文档生成与全流程编排(`services/pipeline.py`);
- 第三批: FastAPI 路由与文档/Excel 下载 API + React 8 步向导前端
  (权限矩阵交叉表格)+ 定级问卷打分 + SBOM 文件导入 + Jira 跟踪表。

## 目录结构

```
SecReq/
├─ DESIGN.md              # 需求与设计文档
├─ main.py                # FastAPI 入口(uvicorn main:app 启动, 兼管前端构建产物托管)
├─ shared/constants.py    # 前后端共享枚举(经 /api/meta/constants 供数, 前端不硬编码)
├─ models/                # SQLAlchemy 2.0 数据模型(SQLite 开发, 兼容 PostgreSQL)
├─ schemas/               # Pydantic 请求/响应模型(API 契约层)
├─ routers/               # 路由: projects/steps/generate/meta
├─ rules/
│  ├─ knowledge_base.yml  # 安全需求知识库(44条模板, 数据文件可独立维护)
│  ├─ grading_questions.yml # 定级问卷题库(分值/判定依据文案, 安全中心维护)
│  ├─ loader.py           # YAML 加载与完整性校验
│  ├─ context.py          # 规则引擎输入上下文(项目输入数据快照)
│  ├─ policy.py           # 密码/会话策略生效值计算(引擎与文档共用口径)
│  └─ engine.py           # 规则引擎: 模板匹配 → 占位符渲染 → SecurityRequirement
├─ services/
│  ├─ grading.py          # 问卷加权打分 → 建议定级 + 判定理由
│  ├─ project_service.py  # 项目 CRUD / 级联删除 / 列表计数装配
│  ├─ step_store.py       # 向导各步骤整卷保存(整体替换, 幂等)
│  ├─ seed_data.py        # 种子数据「个人网银系统」+ 需求清单汇总输出
│  ├─ sbom.py             # CycloneDX 1.5 SBOM 构建(JSON 输出、purl 自动补齐)
│  ├─ sbom_import.py      # SBOM 文件导入解析(CycloneDX JSON / SPDX JSON / tag-value)
│  ├─ osv.py              # OSV.dev 查询客户端: 结果规范化/24h缓存/失败降级
│  ├─ docgen.py           # python-docx 生成 4 份 Word(封面/表格/高危标红)
│  ├─ tracking_export.py  # openpyxl 需求跟踪表(Jira 导入字段映射说明 Sheet)
│  └─ pipeline.py         # 全流程编排: 漏洞同步→规则引擎→SBOM+文档落盘
├─ docs/templates/doc_style.yml  # 文档版式参数(字体/标红色/底纹), 安全中心可维护替换
├─ frontend/              # React 18 + TS + AntD 8 步向导(Vite, 见 frontend/README 段落)
├─ scripts/run_seed_demo.py  # 一键验证: 建库 → 种子 → 漏洞同步 → 生成 → 打印清单
├─ output/<项目编码>/       # 每次生成的 SBOM JSON 与 4 份 Word 落盘位置
└─ tests/                 # pytest(105个用例: 规则命中/SBOM/API全流程/导入/导出/文档断言)
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
SBOM及漏洞清单` 四份可直接打开的 Word。

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
下载接口: `GET /export/docx/{grading|requirement|design|sbom_vuln}` 按库内最新
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
4 份 Word + 跟踪表 Excel + SBOM JSON 下载。

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

- 后续可选增强: 需求状态流转界面(跟踪表已含 status 字段)、知识库编辑界面、
  多用户与审批流、`services/llm_rewriter.py` LLM 润色接入(MVP 预留空实现)。

