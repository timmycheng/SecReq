# 给 Agent 的开发 Prompt（需求+设计阶段版）

以下内容可直接复制给 Agent，建议按文末“分批交付策略”发出
---

## 一、角色与目标

你是一名资深全栈工程师。请开发一个 **“安全需求与设计基线生成工具”** 的 Web 应用，面向银行软件项目的项目经理与开发人员，在 **需求阶段和设计阶段** 使用。
**业务背景**：我行开发流程中，安全需求普遍是“豆腐块”式空泛描述，设计文档中软件清单不细、缺数据字典、缺API接口文档、缺权限矩阵、缺登录密码策略说明。本工具通过**结构化表单收集项目信息，自动生成符合行内模板的安全需求与设计文档章节**，实现安全左移。
**输入**：项目基本信息、等保定级问卷答案、功能清单、数据字典、用户权限矩阵、身份认证方式、软件/框架清单、API接口清单、资产清单。
**输出**：

1. 《系统定级建议书》（Word）
2. 《需求规格说明书》安全需求章节（Word）
3. 《总体设计说明书》安全设计章节，含：软件/框架版本清单、数据字典、API接口文档、资产清单、登录与密码策略设计说明（Word）
4. SBOM 清单（CycloneDX JSON）+ 漏洞清单
5. 安全需求跟踪表

## 二、技术栈

- 后端：Python 3.11 + FastAPI + SQLAlchemy 2.0 + SQLite（模型设计需兼容 PostgreSQL 迁移）
- 前端：React 18 + TypeScript + Ant Design 5，表单向导用 Steps 组件
- 文档生成：python-docx 生成 Word；openpyxl 生成 Excel
- 漏洞查询：OSV.dev 公开 API（<https://api.osv.dev/v1/query，POST> {package:{purl}}）
- 目录结构：`models/ schemas/ routers/ services/ rules/ docs/`

## 三、功能模块

### 模块1：项目信息向导（前端 8 步表单）

**Step1 项目基本信息**
项目名称、项目编码、项目类型（web/mobile_app/api_service/desktop/mini_program）、所属业务条目、用户规模（<1k/1k-10w/10w-100w/>100w）、部署环境（多选：行内私有云/托管云/外采SaaS）、是否涉及公网访问、项目经理、开发负责人、安全对接人。
**Step2 等保定级问卷**（5 题，安全中心维护判定依据文案）

- Q1 系统是否处理公民个人信息？是否含敏感个人信息（金融账户/生物识别/身份信息）？
- Q2 系统是否涉及资金交易或直接影响客户资金安全？
- Q3 系统服务对象是否为社会公众/企业客户/仅内部员工？
- Q4 系统受攻击或破坏后影响范围（无影响/单业务受影响/全行受影响/影响社会秩序）？
- Q5 系统是否为其他重要系统的依赖底座？
每题选项带分值，加权计算输出：**建议定级（一级/二级/三级）+ 判定理由文字**，允许人工修正最终定级。定级结果作为后续密码策略、加密策略的默认基线。
**Step3 功能清单**
动态增删行：功能名称、所属模块、功能分类（受控枚举多选：auth_login/password_mgmt/file_upload/file_download/payment/refund/order/export_data/message_push/comment_ugc/api_open/admin_console/third_auth/ai_feature/audit_log/search/sms_email）、敏感级别、是否涉及资金、是否公网暴露。
**Step4 数据字典与数据资产**
两级结构：先建“数据资产”（如“客户账户信息”，选择分类：个人基本信息/身份信息/金融账户/生物识别/健康医疗/位置轨迹/行为日志/业务数据；分级：公开/内部/敏感/机密；是否敏感PII），再在资产下建“数据表”，表下建“字段”（字段名、类型、是否脱敏展示、是否加密存储、脱敏规则建议）。
**Step5 用户权限矩阵**
交互：左侧角色行 × 顶部资源列交叉表格。先维护角色（名称、类型：normal/privileged/super_admin、预估人数）和资源（名称、类型：data_record/api_endpoint/page_menu/system_config、关键性：low/medium/high/critical），再在矩阵单元格勾选操作：create/read/update/delete/export/approve/config_change，并可勾选“该操作需审批”。
**Step6 身份认证与密码策略**
- 认证方式（多选）：账密 / 短信验证码 / OTP动态口令 / 第三方OAuth / 行内SSO / 生物识别
- 密码策略设计器：根据 Step2 定级结果给出默认值并允许调整——最小长度（三级默认10、二级默认8）、复杂度类别数（3/4）、有效期天数（60/90）、错误锁定阈值（5次）、历史密码重复限制、是否强制2FA
- 会话策略：会话超时时长、单点登录并发限制、登录失败处理方式
**Step7 软件/框架清单（SBOM 来源）**
动态增删行：层级（frontend/backend/database/middleware/library/infra）、组件名（带自动补全下拉，内置常见组件库：Spring Boot/MySQL/Redis/Nginx/Vue/React/lodash/log4j/fastjson等50个）、版本号（必填）、许可证。同时支持**上传 CycloneDX/SPDX 格式 SBOM 文件**批量导入，两种来源标记 `manual_input` / `sbom_file`。
**Step8 API接口清单与资产清单**
- 接口清单：接口名、路径、HTTP方法、是否需要认证、是否公网暴露、请求/响应是否含敏感数据（关联Step4数据资产）、限流配置
- 资产清单：资产类型（server/database/middleware）、名称、环境（dev/test/prod）、IP、负责人、是否承载敏感数据
**确认页**：汇总所有输入，显示“已触发 XX 条安全需求”，点击“生成安全基线”。

### 模块2：安全需求知识库与规则引擎（核心）

知识库存放 `rules/knowledge_base.yaml`，结构：条件 → 需求模板列表。需求模板字段：req_id（SEC-V2-001 格式，按 ASVS 章节分组）、title、description、priority、asvs_ref、acceptance_criteria、suggested_phase（design/development/test）、trigger_reason（触发了哪条输入，用于回溯）。
**规则维度与示例**（知识库至少包含以下规则的完整模板，每条需求有完整中文描述和验收标准）：

1. **功能触发规则**（约25条）：`category=file_upload → [文件类型白名单、大小限制、存储路径隔离、上传文件病毒扫描]`；`category=payment → [交易幂等性、防重复提交、金额服务端校验、交易流水完整性]`；`category=export_data → [导出审批、导出脱敏、导出日志审计、导出量限制]`；`category=third_auth → [OAuth state防CSRF、回调白名单、token校验]`；以此类推覆盖全部功能分类
2. **权限矩阵分析规则**：
   - critical 资源的 delete/export/approve 操作未勾选需审批 → 生成“增加审批流”需求（高优先级）
   - 存在 super_admin 角色 → 生成“最小权限原则、特权账号审计”需求
   - 生成《权限矩阵》附录表格
3. **认证方式规则**：勾选短信验证码 → 短信防轰炸/验证码有效期/防重放；勾选第三方OAuth → CSRF防护/回调域校验；用户规模>10w → 强制2FA建议
4. **密码策略规则**：按定级输出对应强度需求
5. **数据资产规则**：`classification=机密 → 存储加密+传输加密+访问审计+脱敏展示`；`is_sensitive_pii=true → 单独同意机制+收集最小化`；字段含身份证/手机号 → 脱敏规则需求
6. **API接口规则**：公网接口 → 限流/防重放/输入校验/WAF建议；无需认证的接口 → 强提示“匿名接口安全评估”
7. **合规映射规则**：等保三级 → 安全审计/入侵防范/恶意代码防范/数据备份恢复 等保条款需求集；个保法 → 敏感PII相关条款

### 模块3：SBOM 生成与漏洞匹配

- 从 Step7 生成 CycloneDX 1.5 格式 SBOM JSON（含组件名、版本、purl、许可证、来源）
- 构造 purl 后批量调用 OSV.dev 查询漏洞，输出：CVE编号、CVSS分数与等级、受影响版本范围、修复版本、简述
- 高危/严重漏洞在生成结果中**标红置顶**，并在安全需求中自动追加一条“第三方组件高危漏洞整改”需求，关联到具体组件
- OSV 调用失败时降级为“漏洞查询暂不可用”，不阻塞其他流程
- 漏洞查询结果缓存 24h，避免重复请求

### 模块4：文档生成（python-docx）

按行内模板生成 4 份文档，均为中文、含封面（项目名/编码/生成时间/编制人/审核人签字栏）：

1. **《系统定级建议书》**：问卷答案表 → 定级结论 → 判定理由 → 人工修正栏
2. **《需求规格说明书-安全需求章节》**：按 ASVS 章节分组的需求表格（req_id/需求描述/优先级/来源/验收标准），含权限矩阵附录
3. **《总体设计说明书-安全设计章节》**：软件/框架版本清单表、数据字典表（资产→表→字段三级，含分类分级）、API接口安全属性表、资产清单表、登录与密码策略设计说明（参数化完整描述）、认证方式设计说明
4. **《SBOM及漏洞清单》**：SBOM组件表 + 漏洞表（高危标红）
模板文件存 `docs/templates/`，允许后续由安全中心维护替换。

### 模块5：Excel 需求跟踪表

导出字段：req_id、需求描述、优先级、责任方、建议阶段、验收标准、状态（默认open）、备注。可直接导入 Jira。

## 四、核心数据模型（摘要）

```
Project(id, name, code, type, industry, user_scale, deploy_env[], is_public, 
        pm_name, dev_lead_name, sec_contact_name, status, created_at)
GradingSurvey(project_id, answers_json, suggested_level, suggested_reason, 
              final_level, manual_adjust_note)
Feature(id, project_id, name, module, categories[], sensitivity, 
        involves_payment, exposed_to_internet)
DataAsset(id, project_id, name, data_type, classification, is_pii, 
          is_sensitive_pii)
DataTable(id, asset_id, table_name)
DataField(id, table_id, field_name, field_type, need_encrypt, 
          need_mask, mask_rule)
Role(id, project_id, name, role_type, user_count_estimate)
Resource(id, project_id, name, resource_type, criticality)
PermissionEntry(id, role_id, resource_id, action, requires_approval)  
  UNIQUE(role_id, resource_id, action)
AuthConfig(project_id, auth_methods[], pwd_min_length, pwd_complexity, 
           pwd_valid_days, lockout_threshold, pwd_history_limit, 
           force_2fa, session_timeout_min, concurrent_limit)
SbomComponent(id, project_id, layer, name, version, purl, license, 
              source_type)
VulnerabilityRecord(id, component_id, cve_id, severity, cvss_score, 
                    affected_range, fix_version, summary)
ApiEndpoint(id, project_id, name, path, method, auth_required, 
            public_exposed, sensitive_asset_ids[], rate_limit)
InfraAsset(id, project_id, asset_type, name, env, ip, owner, 
           holds_sensitive)
SecurityRequirement(id, project_id, req_id, title, description, 
                    category, priority, asvs_ref, acceptance_criteria, 
                    suggested_phase, source_entity_type, source_entity_id, 
                    trigger_reason, status)
```

## 五、关键 API 设计

```
POST /api/projects                        创建项目
POST /api/projects/{id}/survey            提交定级问卷 → 返回定级建议
POST /api/projects/{id}/generate          触发规则引擎 → 生成需求+SBOM+漏洞
GET  /api/projects/{id}/requirements      需求列表（支持按category/priority筛选）
GET  /api/projects/{id}/sbom              SBOM JSON
GET  /api/projects/{id}/vulnerabilities   漏洞清单
GET  /api/projects/{id}/export/docx/{doc_type}  下载四类文档
GET  /api/projects/{id}/export/xlsx       需求跟踪表
```

## 六、交付物与验收标准

1. 完整可运行代码仓库 + README（启动方式、依赖安装、演示步骤）
2. **种子数据脚本**：预置演示项目“个人网银系统”——含12个功能（覆盖支付/文件上传/导出/第三方登录等）、6个数据资产（含金融账户/生物识别）、5个角色+8个资源的权限矩阵、10个技术栈组件（其中故意含 log4j 2.14 用于演示漏洞命中）、4个API接口。跑通后应生成约60-80条安全需求、命中至少3个真实CVE、4份Word文档可直接打开查看
3. pytest 单元测试：规则引擎各维度规则命中测试、SBOM生成测试、OSV查询mock测试、文档生成测试
4. 全部界面与文档内容中文；代码注释中文

## 七、约束

- MVP 不接入 LLM（预留 `services/llm_rewriter.py` 空实现）
- 不引入 Redis/MQ 等中间件
- 所有枚举前后端共享一份常量定义（`shared/constants.ts` 与 `shared/constants.py` 由同一 YAML 生成或人工保持同步）
- 生成需求必须可追溯到输入（source_entity_id 必填），不允许出现无来源的“凭空”需求
- 文档模板与知识库均以数据文件形式存在，修改不涉及代码变更

---

## 附：给 Agent 的分批交付策略（发 prompt 时一并说明）

单次让 Agent 生成全部代码质量容易失控，建议按以下顺序发消息：

1. **第一批**：“先实现后端数据模型 + 知识库 YAML + 规则引擎 + pytest 测试，暂不做前端和文档生成”，先验证种子数据能生成合理的需求清单
2. **第二批**：“规则引擎已跑通，继续实现 SBOM 生成、OSV 查询和 4 份 Word 文档生成”
3. **第三批**：“实现前端 8 步向导 + 文档下载”，权限矩阵交叉表格单独强调
4. 每批结束让它**给出种子数据实际运行结果截图/输出片段**，确认规则命中合理再进入下一批
需要我接下来把 **knowledge_base.yaml 的具体内容**（30-40 条规则的完整模板，含标题、描述、验收标准原文）也写出来吗？这份内容质量决定了生成需求的专业度，比代码更值得先打磨。

## 引擎消费方式

rules/engine.py 的匹配逻辑为遍历全部模板、按 trigger 类型查项目输入数据、条件满足即实例化为 SecurityRequirement 记录（渲染 {{placeholder}} 占位符）。每种 trigger 的判定函数：

|trigger|数据来源|
|-|-|
|feature_category|features 表的 categories[] 数组交集|
|permission_rule|运行 SoD/审批缺失/super_admin 三种扫描算法，命中的写 detail|
|auth_method|auth_config.auth_methods 包含判断|
|policy_baseline|恒触发，占位符从 auth_config 取值|
|data_asset|遍历 assets + fields，mask_fields_any_of 与字段名/类型正则匹配|
|api_endpoint|遍历 api_endpoints 的布尔字段|
|compliance|compliance_targets 包含判断|
|vulnerability|OSV 查询结果 severity ∈ [high,critical]，每个组件生成一条需求|

注意：同类规则命中多个实例时（如3个上传功能）应生成3条独立需求分别关联各自 source_entity_id。
