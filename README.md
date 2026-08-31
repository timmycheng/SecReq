# SecReq — 安全需求管理平台

面向银行软件项目的**开发**与**安全**两类角色:通过 8 步向导采集项目信息
(支持粘贴需求段落自动生成功能点、数据字典自动分级),按知识库规则引擎自动生成
安全需求清单(产物以 Web 展示 + 一键复制到 Word),并联动组件 SBOM 漏洞查询、
JR/T 0197-2020 五级数据分级与监管合规基线映射。

[![CI](https://github.com/timmycheng/SecReq/actions/workflows/ci.yml/badge.svg)](https://github.com/timmycheng/SecReq/actions/workflows/ci.yml) [![Release CI](https://github.com/timmycheng/SecReq/actions/workflows/release.yml/badge.svg)](https://github.com/timmycheng/SecReq/actions/workflows/release.yml)

当前版本以 [CHANGELOG.md](CHANGELOG.md) 顶部章节为准

## 功能特性

- **8 步建项向导**:基本信息(含外部系统连接清单、定级问卷内联、定级后即时预览
  密码策略与合规基线)→ 功能清单 → 权限矩阵 → 技术组件 → API 接口 → 基础设施
  (服务器规格/网络设备)→ 认证与密码策略 → 确认生成;项目编码自动生成(`XM2026-001`)。
- **智能录入**:功能清单**粘贴需求段落自动生成**候选功能点(OpenAI 兼容大模型优先,
  未配置/失败降级关键词规则);数据字典**粘贴/上传自动解析分级**(字段名模式库推断
  JR/T 五级 + PII 识别 + 脱敏建议,确认后入库)。
- **知识库规则引擎**:`rules/knowledge_base.yml` 61 条安全需求模板(全部含合规出处
  `regulatory_ref`,不编造条款号),8 类触发器;权限矩阵内置免审批违规 / SoD 职责
  分离冲突 / 特权账号三种扫描;监管报送类需求(等保备案、出境评估、PIA 等 8 条)
  命中即置顶。
- **组件漏洞联动**:SBOM(CycloneDX 1.5)构建 + OSV.dev 在线漏洞查询
  (24h 缓存、失败降级、修复版建议),组件风险自动生成整改需求。
- **产物 Web 化**:需求清单平铺全文、来源中文化、统一确认动作 + 批量确认;
  「复制到 Word」(HTML 剪贴板,粘贴即保留标题/表格/标红);保留 SBOM JSON 与
  Jira Excel 跟踪表下载。
- **系统管理(安全角色)**:知识库/定级题库可视化编辑(写回 YAML 自动备份+全量校验)、
  密码策略基线按定级可配置、OpenAI 兼容大模型接入配置、用户管理、审计日志。
- **认证与数据权限**:账密登录(pbkdf2 + Bearer 会话 12h + 登录失败锁定),全接口
  鉴权;**开发只能看到/操作自己创建的项目,安全全量可见**(越权一律 404)。

## 快速开始

### Docker 部署(推荐)

```bash
docker run -d --name secreq -p 8000:8000 \
  -v secreq-data:/app/data -v secreq-output:/app/output \
  -e TZ=Asia/Shanghai \
  ghcr.io/timmycheng/secreq:v2.1.3
```

或使用仓库自带的 `docker-compose.yml`:

```bash
docker compose up -d
```

启动后访问 <http://localhost:8000>。SQLite 数据库持久化于容器 `/app/data`,
生成产物(SBOM JSON)于 `/app/output`,生产环境建议挂载卷保存。

离线环境可从 GitHub Release 下载对应版本的镜像包后导入:

```bash
docker load -i secreq-image-v2.2.0.tar.gz
```

### 内网部署(无互联网出口)

内网部署请使用 `docker-compose.intranet.yml`:固定镜像版本(内网拉不到 `latest`)、
显式注入时区、初始密码通过 `.env` 必填(参考 `.env.example`),
并预留了漏洞库挂载位(v2.2.0 起可用于不重建镜像更新漏洞数据)。

```bash
docker load -i secreq-image-v2.2.0.tar.gz
cp docker-compose.intranet.yml docker-compose.yml
cp .env.example .env   # 编辑 .env 设置 SECREQ_SEED_PASSWORD
docker compose up -d
```

HTTPS 由前置反向代理终结(容器本身只提供 HTTP), 配置模板见
`deploy/nginx/secreq.conf`。

### 离线漏洞库(v2.2.0)

平台在内网运行, **组件漏洞匹配完全依赖本地离线漏洞库**, 不访问任何外部服务。

**镜像内置的是基线库, 不是完整库。** 完整库通过挂载覆盖 —— 更新漏洞数据时只替换
一个文件并重启容器, 不必重建镜像走内网镜像入库流程(遇到 log4j2 级别的紧急漏洞
分钟级即可生效):

```yaml
volumes:
  - ./vulndb/vulndb-20260915.sqlite:/app/data/vulndb.sqlite:ro
```

在联网区构建漏洞库(产物摆渡进内网, 连同 `.sha256` 一起带):

```bash
# 默认推荐配置: 语言层(npm/Maven/PyPI/Go/NuGet/crates.io) + Bitnami + Alpine + openEuler
python scripts/build_vuln_db.py --out vulndb.sqlite

# 自定义生态 / 用已下载的 zip 离线构建 / 只看不写 / 列出全部可用生态
python scripts/build_vuln_db.py --ecosystems npm,Maven,Bitnami
python scripts/build_vuln_db.py --source-dir ./osv-zips
python scripts/build_vuln_db.py --dry-run
python scripts/build_vuln_db.py --list-ecosystems

# CNNVD 编号映射(可选; 月度 XML 需从 CNNVD 站点登录后下载, 无法自动化)
python scripts/build_cnnvd_map.py --source-dir ./cnnvd-xml
```

摆渡完成后可在**系统管理 → 漏洞库**查看库版本、生态覆盖与记录数, 并点
「校验文件完整性」比对 SHA256(该操作留审计)。

**⚠️ 已知覆盖缺口(务必知悉)**

| 缺口 | 说明 |
| ---- | ---- |
| **银河麒麟** | 麒麟不在 OSV 的 39 个生态中。本平台按 **openEuler 同源数据代理匹配**, 结果一律标注「推断, 以麒麟官方安全公告为准」。麒麟的独立补丁回合、自有组件(KVE 编号)与架构维度(aarch64 / loongarch64 / sw_64)**无法覆盖**。补齐的唯一途径是向麒麟索取正式数据源 |
| Kubernetes | Bitnami 与 Alpine 生态均无覆盖, 需由行内 SCA 或单独数据源补充 |
| 源码编译 / 自研组件 | 不在任何公开漏洞库覆盖范围, 需人工评估 |

**三种「查不到」在界面上是分开的**, 绝不会合并成「无漏洞」:
`未纳入本地漏洞库覆盖范围` / `无法判定(需补生态或分发渠道)` / `未发现已知漏洞`。

### 演示账号

| 账号 | 角色 | 权限 |
| ---- | ---- | ---- |
| dev_li / dev_zhang | 开发 | 新建项目(仅可见自己创建的)、填报向导、生成基线、确认需求 |
| sec_chen / sec_zhao | 安全 | 查看全部项目、系统管理(知识库/题库/策略/用户/审计/LLM) |

初始密码通过环境变量 `SECREQ_SEED_PASSWORD` 指定, 未设置时每次启动随机生成并打印到服务日志
(源码不含固定口令; 登录后可在右上角修改)。存量库旧角色自动迁移:
pm/developer → 开发; security_reviewer/security_lead → 安全; 风管/审计账号停用;
存量项目自动归入第一个开发账号。

### 本地开发

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # Linux/macOS 用 .venv/bin/pip

# 运行全部测试(OSV 查询使用 MockTransport, 不出网)
.venv/Scripts/python -m pytest tests -q

# 后端 API(默认 sqlite:///项目根/secreq.db, 可用 SECREQ_DATABASE_URL 覆盖)
.venv/Scripts/python -m uvicorn main:app --reload --port 8000

# 前端开发服务器(Vite, 已代理 /api → 127.0.0.1:8000)
cd frontend && npm install && npm run dev   # http://localhost:5173

# 生产模式: 构建后由 FastAPI 单进程托管(npm run build 后重启 uvicorn 即可)
cd frontend && npm run build
```

种子数据演示(种子项目故意保留旧版组件,在线模式下会命中真实 CVE):

```bash
.venv/Scripts/python scripts/run_seed_demo.py            # 在线: 调用真实 OSV.dev
.venv/Scripts/python scripts/run_seed_demo.py --offline  # 离线: 走"漏洞查询暂不可用"降级路径
```

### 存量数据迁移

```bash
.venv/Scripts/python scripts/migrate_classification.py --dry-run  # 预览
.venv/Scripts/python scripts/migrate_classification.py            # 执行(幂等)
```

应用启动时也会自动执行同一迁移(`main.py` lifespan 与脚本共用
`services/classification_migration.py`, 口径唯一)。

## 环境变量

| 变量 | 默认值 | 说明 |
| ---- | ------ | ---- |
| `SECREQ_DATABASE_URL` | `sqlite:///<应用目录>/secreq.db` | SQLAlchemy 连接串;容器镜像内默认 `sqlite:////app/data/secreq.db`,也可指向 PostgreSQL 等外部库 |
| `SECREQ_SEED_PASSWORD` | 未设置时每次启动随机生成 | 种子账号/未指定密码新建账号的初始密码;随机值会打印到服务启动日志(仅对当次新建或补设密码的账号生效)。生产部署建议显式设置并在首登后修改 |
| `SECREQ_VULN_SOURCE` | `local` | 漏洞数据源链(逗号分隔, 前一个不可用时自动降级到后一个并记日志): `local` 本地离线库(内网默认) / `online` OSV.dev 在线(需互联网) / `sca` 行内 SCA(尚未接入, 选中会明确报「未启用」) |
| `SECREQ_VULNDB_PATH` | `<SECREQ_DATA_DIR>/vulndb.sqlite` | 本地漏洞库路径;镜像内置基线库, 挂载外部库可覆盖 |
| `SECREQ_CNNVD_PATH` | `<SECREQ_DATA_DIR>/cnnvd_map.sqlite` | CNNVD 编号映射库路径(可选, 缺失不影响漏洞匹配) |
| `SECREQ_DATA_DIR` | `./data`(容器内 `/app/data`) | 主库 / 漏洞库 / CNNVD 映射库所在目录 |

## 目录结构

```
SecReq/
├─ main.py                # FastAPI 入口(启动时自动补列+迁移+种子用户+策略注入; 兼管前端构建托管)
├─ CHANGELOG.md           # 版本更新日志(各版本变更与历史实现说明存档)
├─ Dockerfile             # 容器镜像(多阶段: 前端构建 → FastAPI 单进程托管)
├─ docker-compose.yml     # 一键部署(挂载数据卷/产物卷)
├─ .github/workflows/release.yml  # 版本 tag 触发的 CI: 测试 → GHCR 镜像 → Release 附镜像包
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
│  ├─ sbom.py / sbom_import.py / osv.py   # SBOM 构建/导入/漏洞查询与规范化
│  ├─ vuln_source.py      # 数据源协议与工厂(local/online/sca 链式降级)
│  ├─ vulndb.py           # 本地离线漏洞库查询(内网默认数据源)
│  ├─ vuln_match/         # 按生态的版本归一化(Bitnami/Alpine/Debian/RHEL/openEuler)
│  └─ cnnvd.py            # CNNVD 编号映射(展示与导出补合规字段)
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
│  ├─ migrate_classification.py # 老四级分级迁移脚本(交付物)
│  ├─ build_vuln_db.py         # 构建本地离线漏洞库(联网区执行, 产物摆渡进内网)
│  └─ build_cnnvd_map.py       # 构建 CNNVD 编号映射库
├─ output/<项目编码>/       # 每次生成的 SBOM JSON 落盘位置
└─ tests/                 # pytest(189个用例: 认证与数据权限/智能录入/管理端/五级联动/报送触发等)
```

## 版本与发布

- 开发流程:所有改动经 issue → 分支 → PR → CI → squash 合并进入 main, main 受分支保护, 详见 [CONTRIBUTING.md](CONTRIBUTING.md);
- 发布流程:确认 main CI 全绿后, 修改 `main.py` 的 `version` 并在 [CHANGELOG.md](CHANGELOG.md) 新增对应版本章节, 本地运行 `python scripts/check_version.py vX.Y.Z` 校验 tag、代码版本、CHANGELOG 三者一致, 再推送 `vX.Y.Z` tag(CI 会再校验一次);
- tag 触发 release.yml:自动运行 pytest → 构建并推送 Docker 镜像到 `ghcr.io/timmycheng/secreq`(同时打 `X.Y.Z` / `X.Y` / `latest` 标签)→ 自动创建 GitHub Release(正文取 CHANGELOG 对应章节)并附离线镜像包(`secreq-image-vX.Y.Z.tar.gz`)。

## 路线图

- POC/上线门禁流程启用(数据结构已就绪: `gate_type` 枚举与 `ReviewGate` 表)、
  厂商门户与外部系统对接(OA/4A/SIEM)、电子签章接入(现为"姓名+工号+时间戳+哈希")、
  需求状态流转界面、LLM 润色接入(大模型接入配置已就绪, 润色应用按本期范围外暂缓)。
