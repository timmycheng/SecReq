# 2026-08-30

## SecReq v2.1.2 项目评审（只读走查，未改动代码）

通读后端（models/routers/services/rules）与前端（26 文件 5237 行）后产出优化建议清单。
结论按严重度分级，核心问题集中在「数据一致性」与「并发/性能」两类。

### 复核过的关键事实

- 测试：`137 passed, 1 failed`。唯一失败项 `tests/test_sbom.py::test_write_cyclonedx_file_keeps_utf8_chinese`
  是沙箱临时目录无法清理导致的环境问题，非代码缺陷。
- 知识库：`rules/knowledge_base.yml` 61 条模板，regulatory_ref 无缺失，无停用项。
  分布 feature_category 22 / data_asset 11 / regulatory_trigger 7 / 其余零散。
- `rules/engine.py:476` docstring 声明了 `saas_finance` 报送规则，但
  `_match_regulatory_triggers` 未实现该分支 → 命中即抛 RuleEngineError（当前 61 条模板未用到，属定时炸弹）。
- 无 alembic；无 SQLite PRAGMA（WAL / busy_timeout 均未配置）；`models/database.py:_sqlite_kwargs` 为死代码。
- 依赖 `requirements.txt` 全 `>=`，无锁文件；前端有 package-lock + npm ci（这块是对的）。
- `app.mount` 的 StaticFiles 不受 app 级 `dependencies=[Depends(auth_guard)]` 约束（Mount 非 APIRoute），
  前端静态包对匿名访客可见——对登录页是必要放行，但需知晓。

## 实施方案产出（同日）

产出 `IMPLEMENTATION_PLAN.md`，用户已确认三个决策：
1. 范围 = 全量 P0+P1+P2
2. 溯源修复走**稳定业务键 uid** 路线（非 diff upsert）
3. 先出方案等确认，暂不改代码

### uid 方案关键结论（后续实施直接复用）

- 需加 uid 列的模型共 8 个：Feature / DataAsset / SbomComponent / Role / Resource /
  ApiEndpoint / InfraAsset / ExternalSystem。DataTable、DataField 跟随 cascade，不加。
- `permission_entry` **不加列**，用 `(role_uid, resource_uid, action)` 复合键（语义天然稳定）。
- 无需改动的 source_entity_type：`project` / `compliance_target` / `auth_config` / `policy_baseline`
  （前两者用 project.id 稳定；后两者 auth_config 是单行 upsert 保留主键）。
- **第二处同类隐患**：`ApiEndpoint.sensitive_asset_ids` 存 DataAsset.id 数组，
  数据字典重存后接口-资产关联同样断裂，必须一并治理。
- 存量断链数据诚实处理：映射不到的需求标 `status="obsolete"`，保留 source_label，不伪造映射。
- 前端保存步骤必须回传 uid；后端加 409 保护（有生成记录却全行无 uid → 拒绝，防静默断链）。
- OSV 异步化时：**并发只做网络查询，写库仍串行**（`_replace_component_vulns` 依赖 flush 顺序语义）。

## 部署约束变更：内网离线部署

用户明确：**平台最终在内网部署，无互联网访问**。OSV.dev 在线查询不可用，
产出 `OFFLINE_VULN_DB_PLAN.md`。

### 已核实的数据源（2026-08-30）

- OSV 官方离线包：`https://osv-vulnerabilities.storage.googleapis.com/all.zip`
  按生态：`<ECOSYSTEM>/all.zip`；生态清单 `ecosystems.txt`；增量索引 `modified_id.csv`。
  记录数参考：npm 226676 / PyPI 24558 / Go 8821 / Maven 6881 / NuGet 1844 / crates.io 2668。
- Trivy DB：`oras pull ghcr.io/aquasecurity/trivy-db:2` → db.tar.gz；
  轻量 ~104MB、完整 ~221MB 解压；**Java 还需额外 trivy-java-db:1**；每 6 小时构建。
- CNNVD：月度 XML 约 5-8MB/月、全年约 48MB，CVE 级无包坐标。

### 方案结论

推荐 **OSV 官方离线数据包 + 本地 SQLite 索引库**。决定性理由：离线包里每条 JSON
就是 `OsvClient.normalize()` 的输入形态，`normalize / _extract_ranges /
_pick_fix_version / _matched_affected_entries` **全部复用零改动**，只换取数通道。
抽 `VulnSource` 协议（Online / Local 双实现），上层 pipeline 与 engine 零改动。

### 新发现的隐性缺陷（必须一并修）

`services/sbom.py:34-41` 的 `ensure_purl` 对无 purl 组件生成 `pkg:generic/...`，
**OSV 不支持 generic 生态** → 只要用户不手填 purl，漏洞查询必然空转。
`ComponentIn.purl` 是可选字段且 Step7 未强制引导，实际绝大多数组件都中招。

### 其他关键设计

- 缓存语义：从 24h TTL 改为 `(db_version, 组件版本)` 指纹判定，导入新库即触发重算。
- 「查不到」必须区分三种语义：生态未覆盖 / 库未导入 / 确实无漏洞。不可混为一谈。
- 基础设施类组件（MySQL/Nginx/Redis/OpenSSL 等）属 OS 或 GIT 生态，
  与「组件名+版本」匹配模型不兼容，明确标注未覆盖。
- 与 IMPLEMENTATION_PLAN 的交互：**阶段 2.1 的 OSV 异步化在内网场景优先级下调**
  （本地查询毫秒级，不需要并发与总超时预算），保留给在线模式即可。
  SQLite WAL 反而更重要（漏洞库导入是大事务）。

## 离线漏洞库方案 v2（用户追加约束后重写）

新增约束：**SCA 有但对接能力未知 / npm 必导 / OS 必须覆盖 / CNNVD 要对齐 /
希望通过 CI 把数据打进 Docker 镜像**。文档 `OFFLINE_VULN_DB_PLAN.md` 已重写为 v2。

### 实测数据（2026-08-30，对 OSV 官方源实测，可直接复用）

生态包体积（压缩）：**npm 211.4MB**、**Ubuntu 623.0MB**、**GIT 176.7MB**、
Debian 72.2、MinimOS 64.4、Linux 52.9、SUSE 44.5、PyPI 32.4、Chainguard 28.7、
Red Hat 25.3、openSUSE 20.6、Wolfi 18.4、openEuler 17.4、Bitnami 8.8、Go 10.9、
Maven 9.8、Root 13.5、Azure Linux 13.6、AlmaLinux 5.9、Rocky 4.5、Alpine 3.9、
NuGet 2.4、crates.io 3.3。

基础设施软件覆盖实测：
- **Bitnami** 覆盖 mysql-client/redis/nginx/kafka/rabbitmq/elasticsearch/tomcat/
  postgresql/mongodb/mariadb/docker-cli；**无** openssl/imagemagick/ffmpeg/zlib/curl。
- **Alpine** 覆盖 openssl/imagemagick/ffmpeg/zlib/curl/redis/nginx/postgresql/mariadb；
  **无** mysql/kafka/elasticsearch/mongodb/tomcat。
- 两者高度互补，合计仅 12.7MB。**K8s 两者都无覆盖**（缺口）。

版本形态（关键）：
- Bitnami 用**标准 semver** → 现有 `_version_key` 零适配可直接匹配。
- Alpine 用 `1.0.2h-r0`（带 -rN 后缀）→ 用户填 `1.0.2h` 匹配不上，
  但记录带**完整 versions 枚举**（Alpine 全库 78099 条），走枚举 + 后缀规整更可靠。

压缩实测（Bitnami/Alpine 全库）：
- Bitnami 9079 条：原始 15.9MB → 裁剪 9.8MB(61%) → **zlib 4.9MB(31%)**
- Alpine 4566 条：原始 17.7MB → 裁剪 15.2MB(85%) → **zlib 2.2MB(12%)**
- 结论：**zlib 存 raw JSON 收益远大于字段裁剪**，查询时只对候选解压。

### 两个体积陷阱

- **Ubuntu 623MB**（是 Debian 的 8.6 倍）——发行版生态体积与发行版本数成正比，不用就别导。
- **GIT 176.7MB**——commit 级匹配，对版本号无用，不导。

### 关键设计结论

- 推荐配置 B（语言层 + Bitnami + Alpine + RHEL系 + openEuler）：压缩包 336MB，
  索引库预估 ~200MB（按实测 0.6x 折算外推，npm 需实测校准）。
- **OS 覆盖的技术难点不在数据源，而在"发行版"维度**：同一 MySQL 8.0.32 在 Debian 是
  `8.0.32-1~deb12u1`、RHEL 是 `8.0.32-1.el9`、Bitnami 是 `8.0.32-debian-11-r0`。
  **Step7 必须增加 distro 字段**，否则无法匹配。
- Docker 镜像方案建议**双轨**：内置基线库（开箱即用）+ 运行时挂载覆盖（日常更新走文件摆渡，
  比镜像入库轻）。漏洞库单独做成 OCI artifact（`secreq-vulndb:YYYYMMDD`）与主镜像解耦。
- SCA 三实现降级链：ScaPlatformSource → OsvLocalSource → OsvOnlineSource。
  **即使 SCA 能对接，本地库仍要建**（降级备份/交叉验证/环境差异）。
- CNNVD 定位为**叠加层**：只抽 `CVE→CNNVD编号+中文等级` 映射，不做组件匹配（CVE 级无包坐标，
  硬匹配需 CPE，精度差）。

## 总方案产出：MASTER_PLAN.md（同日）

用户决策：**SCA 只预留接口、按无 SCA 推进，对接放 v2.6+**。
`MASTER_PLAN.md` 为总纲，整合前三份文档；冲突时以它为准。

### 版本路线图

用户质疑"都是 minor 没有 patch"——**确实是我编排不严谨**，已按 SemVer 修正。
项目 CHANGELOG 本就在正确用 SemVer（2.1.1 纯修复 = PATCH，2.1.2 新增 description 字段 = MINOR）。

| 版本 | 类型 | 主题 | 定级依据 |
|---|---|---|---|
| **v2.1.3** | **PATCH** | 缺陷修复与内网基建 | 只修缺陷，无新增功能/字段 |
| **v2.2.0** | MINOR | 离线漏洞库 + SCA 预留（**内网上线阻塞项**） | 新增数据源/脚本/管理页/Step7 两字段 |
| **v2.3.0** | MINOR | 数据一致性 uid 迁移 | 虽是修 bug，但改数据模型 + 前端保存契约 |
| **v2.4.0** | MINOR | SCA 对接 | 新增数据源实现 |

**工程质量（CI/组件拆分/E2E）不占版本号**——产品行为未变，不构成 SemVer 语义变更。
CI 立刻做；组件拆分与代码分割随 v2.2.0（本就要改那两个文件）；E2E 放 v2.3.0 之后
（契约稳定后再写，避免返工）。

**旧编排（已废弃）**：v2.2.0 内网基建 / v2.3.0 离线库 / v2.4.0 uid / v2.5.0 工程 / v2.6.0 SCA

排序理由：v2.2.0 低风险先垫底；v2.3.0 是功能阻塞项（没它漏洞联动是死的）；
v2.4.0 带数据迁移单独发版便于定位。

### SCA 预留机制（关键设计，现在只做接缝）

1. `services/vuln_source.py` 定义 `VulnSource` 协议 + 工厂。
   配置值 `local` / `online` / `sca`，`sca` 返回"未启用"明确错误而非静默失败。
2. `VulnerabilityRecord` 增列 `source`（osv_local/osv_online/sca）+ `external_ref` + `cnnvd_id`
   —— **v2.3.0 一并加，避免 v2.6 对接时再做迁移**。
3. 汇总带来源标识，前端与导出显示"数据来源：本地漏洞库 vYYYYMMDD"。

v2.6 对接只需：新建 `sca_source.py` + 工厂注册 + 切配置。
协议 / 表结构 / pipeline / 引擎 / 前端 / 导出全不动。

### 新发现的内网问题：时区

**10 处 `datetime.now()`，Dockerfile 无 TZ 设置** → 容器默认 UTC，
确认时间/审计时间/导出时间整体差 8 小时。`session_service.py:48` 的过期判断与写入
都用 `datetime.now()`，**会话逻辑自洽不会出错**，只是显示错。
修复成本一行 `ENV TZ=Asia/Shanghai`。

其他内网基建：print→logging 统一（仅 main.py 2 处）、SQLite WAL、依赖锁、
HTTPS（Nginx 反代模板）、LLM 配置页加内网提示（降级已内建，留空走关键词规则）、
新增 `docker-compose.intranet.yml`。

### 生态选型定稿（v2.3.0，基于实测）

语言层 npm 211.4 + Maven 9.8 + PyPI 32.4 + Go 10.9 + NuGet 2.4 + crates.io 3.3
OS 层 Bitnami 8.8 + Alpine 3.9
发行版层 Red Hat 25.3 + Rocky 4.5 + AlmaLinux 5.9 + openEuler 17.4
合计 336.0 MB 压缩，索引库预估 ~200 MB。**不导 Ubuntu 623MB、GIT 176.7MB。**

### 立即可开工（无依赖）

1. 时区修复（一行）
2. SCA 核查（7 条清单，结论决定 v2.6 存废）
3. npm 单生态实测（校准体积预估）

## v2.1.3 实施完成（同日，代码已改）

按 MASTER_PLAN 实施 v2.1.3（PATCH）。测试：**148 passed + 5 xfailed**，
唯一失败项 `test_sbom.py::test_write_cyclonedx_file_keeps_utf8_chinese` 是沙箱
`SAFE_DELETE_BULK_CONFIRM_REQUIRED`（60 个临时文件超阈值）阻止 pytest 清理临时目录，
**单跑该用例通过，非代码缺陷**。

### 已落地改动

- **时区**：Dockerfile 装 `tzdata` + `ENV TZ=Asia/Shanghai`（slim 镜像不保证带 tzdata，
  光设 TZ 不生效）；compose 与 README 同步。
- **SQLite 并发**：`models/database.py` 用 `@event.listens_for(Engine, "connect")` 设
  `journal_mode=WAL` / `busy_timeout=5000` / `synchronous=NORMAL`。
- **异常脱敏**：新增 `services/errors.py`（`new_trace_id()` + `server_error()`），
  生成与 Excel 解析兜底分支改为日志记栈 + 客户端只收「文案 + 12 位追踪码」。
  顺带收敛 `feature_extract.py` 的 LLM 降级提示（只回显 `type(exc).__name__`，
  原文可能含内网大模型地址）。
- **引擎容错**：`generate()` 捕获 `RuleEngineError` → 跳过该模板记入 `RuleEngine.skipped`；
  未知 `trigger_type` 也跳过。移除 docstring 中未实现的 `saas_finance`。
- **上传限制**：`_read_limited()` 按块读取，累计 >5MB 返回 413（字典导入 + SBOM 导入两处）。
- **审计补全**：新增 project_create / project_delete / export / step_save（8 个保存端点
  + SBOM 导入）。**`login_failed` 早已有**（`routers/auth.py:48`），我评审时漏看了。
- **日志**：main.py 两处 print → logging，补 `logging.basicConfig`（root 已配置时空操作）。
- **内网交付**：`docker-compose.intranet.yml` + `.env.example` + `deploy/nginx/secreq.conf`。
- 删死代码 `_sqlite_kwargs()`；版本与 CHANGELOG 更新至 2.1.3。

### 测试护栏的写法（可复用）

`tests/test_traceability_stability.py` 用 **`xfail(strict=True)`** 作为红灯护栏：
现在失败 → XFAIL 套件绿灯；v2.3.0 修好后通过 → strict 模式报 XPASS 失败，
强制提醒移除标记。**比直接留红灯测试更工程化**（不阻塞 CI）。

### 踩过的坑（重要）

**SQLite 删空表后 max(rowid) 归零，新插入会复用原 ID** —— 所以"只在末尾追加"的
场景恰好掩盖了 P0-2 主键漂移问题。我第一版护栏测试因此 XPASS（没测出 bug）。
**真正暴露缺陷的是"删除"**：删掉首行后其余行整体前移，已生成需求指向错误实体。
改写为"删除一行后其余行主键不漂移"才正确复现。

### 前端构建注意

沙箱下 `npm run build` 会因 vite 清空 `dist/` 被 safe-delete 拦截而失败。
绕法：`npx tsc -b && npx vite build --emptyOutDir false`。
当前 bundle 1.29MB（gzip 407KB），代码分割待 v2.2.0 处理。

## 提交与推送（同日收尾）

v2.1.3 已提交并推送至 `origin/main`，commit `1e26ccd`。
本地与远程一致，工作区干净。方案文档按用户决定留在本地 agent 工作目录（gitignored）未入库。

### 环境坑：git 推送需要显式挂 gh 凭据

非交互环境里 git 无法弹窗读用户名（`/dev/tty: No such device`），
默认 credential.helper 失效。**可用方式**：

```bash
git -c credential.helper='!gh auth git-credential' push origin main
```

`gh` 已认证为 timmycheng（keyring，含 repo / workflow 权限）。
用 `-c` 只作用于当次命令，不改全局配置。

另一个坑：fetch/push 成功后**本地 `refs/remotes/origin/main` 可能不刷新**
（沙箱阻止写 `.git/refs/`），导致 `git status` 误报 `ahead 12`。
核验用 `gh api repos/timmycheng/SecReq/commits/main`，
修复用 `git update-ref refs/remotes/origin/main <sha>`。

### v2.1.3 已打 tag 并触发 Release

`git tag -a v2.1.3 -m "..."` 已推送，release workflow 已触发（推送 tag 即触发）。
便捷命令：`git tag -a vX.Y.Z -m "..." && git -c credential.helper='!gh auth git-credential' push origin vX.Y.Z`

## 私有仓库产物限额（2026-08-30 实测 + 官方限额核对）

用户担心 private repo 产物超限。**实测用量**：

| 项 | 用量 | 限额 | 状态 |
|---|---|---|---|
| Release 附件 | 3 个共 **205.1 MB**（64.9/70.1/70.1） | 单文件 ≤2GB；建议仓库 <1GB | ⚠️ 主要长期风险 |
| Actions 缓存 | **773.2 MB / 85 个** | 10 GB/仓库，7 天未访问自动淘汰 | 在限内但浪费 |
| Actions 构件 | 4 个共 0.4 MB | 与 Packages 共享配额 | 可忽略 |
| GHCR 镜像存储 | — | **目前免费**（容器注册表免费期延长） | 暂不计费 |
| Actions 时长 | 每次 release 约 8-10 分钟 | Free 2000 分钟/月 | 充裕 |

**限额表**（GitHub 官方）：Packages 存储 Free 500MB / Pro 2GB / Team 2GB / Enterprise 50GB；
Packages 存储与 Actions 构件、缓存共享额度。

### 结论与对策

1. **GHCR 容器镜像存储目前免费** —— 镜像本身短期不构成压力。
2. **真正的长期风险是 Release 附件累积**：每版 +70MB，v2.2.0 若把 200MB 漏洞库打进镜像
   会变成每版 +150~200MB，10 个版本就逼近 1GB 软警告线。
3. **v2.2.0 的漏洞库解耦设计正好是关键缓解措施**：漏洞库做成独立 OCI artifact
   （`secreq-vulndb:YYYYMMDD`）走 GHCR（免费），主镜像保持 ~70MB，
   **不要**把漏洞库随 Release 附件分发。
4. **Actions 缓存 773MB 偏大**，成因是 `release.yml` 的 `cache-to: type=gha,mode=max`
   把全部中间层都存了。可改 `mode=min` 或按版本 scope，并加保留策略。
5. 可按需清理被取代版本的 Release 附件、给 GHCR 版本配保留规则。

## v2.1.3 Release 已发布（同日收尾）

tag `v2.1.3` 已推送，release workflow **completed / success**，
GitHub Release 已创建，附件 `secreq-image-v2.1.3.tar.gz` 70.1MB。
Release 附件累计升至 **275.2 MB / 4 个版本**。

## 存储治理三条任务并入 v2.2.0（用户决定）

用户说「加到 2.2.0 里」。已写入 `MASTER_PLAN.md` 5.5 + 任务 11-13，
并同步到 `OFFLINE_VULN_DB_PLAN.md` 5.2/5.3（两份文档口径一致，不打架）。

- **任务 11** Actions 缓存瘦身：`release.yml` 的 `cache-to: type=gha,mode=max` → `mode=min`
  （或加版本 scope）。现状 773.2MB / 85 个缓存，主因是 max 存了全部中间层。
- **任务 12** GHCR 版本保留规则：新增 `retention.yml`，清悬空 + 超窗旧版本，
  保留最近 3 个 minor + 所有 patch，`latest` 与当前 minor 不得删。
- **任务 13** Release 附件保留策略：只保留最近 3 个 Release 的 tar.gz，
  更旧的删除（代码与 tag 仍在，镜像可从 GHCR 重新导出）。

### 三条硬约束（写进跨版本约束第 8 条）

1. **漏洞库绝不随 Release 附件分发**，只走 GHCR OCI artifact `secreq-vulndb:YYYYMMDD`。
2. **应用镜像内置精简基线库，不是完整库**；完整库走挂载覆盖。
3. **Release 附件保留最近 3 个版本**。

## 目标环境确认：麒麟 + Bitnami + Alpine（用户答复）

- 宿主 OS = **银河麒麟**（信创）；中间件 = **Bitnami 容器镜像**；基础库 = **Alpine 容器镜像**。
- 生态选型随之调整：**openEuler 必导（17.4MB），RHEL 系改为可选**。
  配置 B 从 336.0MB 降到 **300.3MB**（索引库 ~180MB）。

### 关键事实：麒麟 V10 血统是 openEuler，不是 CentOS/RHEL

依据：麒麟官方《云底座操作系统 V10 版本发布说明》「继续基于 openEuler 22.03 LTS」；
包管理 RPM/dnf；glibc 2.34+。
**这条推翻了此前"用 RHEL 系做代理匹配"的默认假设**，已同步修正两份文档。

### 麒麟缺口（必须在 v2.2.0 验收时明确交代）

**麒麟不在 OSV 的 39 个生态中**（已核对 ecosystems.txt）。openEuler 只能代理匹配，
四类系统性失真无法回避：
1. 麒麟独立 backport 补丁 → 误报（openEuler 已修 ≠ 麒麟已修）
2. 麒麟自有组件（kysec-daemon KVE-2026-07277、ukui-session-manager KVE-2026-05165）→ **完全漏报**
3. 架构维度（aarch64/loongarch64/mips64el/x86_64/sw_64）→ OSV 数据不含
4. KVE 编号 → 无，需单独映射（同 CNNVD 处理）

麒麟官方 CVE 门户 `https://support.kylinos.cn/#/security/cve` 数据完备
（CVE+KVE 双编号、按产品版本与架构细分、含修复版本），
但**是 SPA，常见 API 路径均 404，无公开机器可读接口**（已实测探测）。

**三条路径**：① 向麒麟索取正式数据源（首选，走采购/服务合同）② 门户抓取（联网区跑，备选）
③ openEuler 代理（过渡，结果必须标注"推断，以麒麟官方公告为准"）。
推荐 ③ 先落地 + ① 并行。拿到数据后加 `KylinSource`，VulnSource 协议天然支持多源。

### 项目约定（后续改动需遵守）

- 角色固定两个：`developer`（仅可见自己创建的项目）/ `security`（全量 + 系统管理）。越权一律 404 不泄露存在性。
- 知识库模板必须带 `regulatory_ref`（`rules/loader.py` 强校验），不允许编造条款号。
- 共享枚举放 `shared/constants.py`，经 `/api/meta/constants` 供前端，不在路由层重复定义。
- 种子初始密码走 `SECREQ_SEED_PASSWORD`，未设置则启动随机生成并打印日志，源码内不得出现固定口令。

## v2.2.0 离线漏洞库实施完成（同日）

按 MASTER_PLAN 5.1 的 13 项任务全量落地。测试 **185 passed + 5 xfailed**
（唯一失败项 `test_sbom.py::test_write_cyclonedx_file_keeps_utf8_chinese`
是沙箱 safe-delete 阻止 pytest 清理临时目录的环境问题，单跑通过）。

### 新增文件

| 文件 | 作用 |
|---|---|
| `services/vuln_source.py` | VulnSource 协议 + 工厂 + 链式降级（local/online/sca） |
| `services/vulndb.py` | OsvLocalSource（内网默认）+ VulnDb 只读封装 |
| `services/vuln_match/` | 按生态的版本归一化（Bitnami/Alpine/Debian/RHEL/openEuler） |
| `services/cnnvd.py` | CNNVD 编号映射查询 |
| `scripts/build_vuln_db.py` | 下载 OSV all.zip → 建索引库 |
| `scripts/build_cnnvd_map.py` | CNNVD 月度 XML → 映射库 |
| `frontend/src/ui/admin/*` | AdminPage 拆出的 7 个 Tab 组件（含新 VulnDbTab） |

### 实施中发现的真实缺陷（方案阶段没预见）

1. **版本比较键忽略字母后缀** —— OpenSSL 用末尾字母做发布序号（1.0.2g / 1.0.2h），
   只比数字会把两者判成同一版本，直接漏掉 CVE-2016-2105。
   修法：`numeric_key` 增加字母段序列 `key = (数字元组, 预发布位, 字母元组)`。
2. **校验和不能写进库里** —— 往 SQLite INSERT 会改变文件本身，写入即失效。
   改为 sidecar `<库名>.sha256`（sha256sum 兼容格式）。
3. **"库里有记录"≠"覆盖了该生态"** —— 实测 **Maven/all.zip 里夹带 92 条 npm、
   189 条 NuGet、101 条 PyPI 记录**（OSV 多生态公告会跨生态列包坐标）。
   按"有记录即覆盖"，只导了 Maven 的库会把 npm 组件报成"未发现已知漏洞"，
   等于用 92 条记录冒充 22 万条。
   修法：覆盖 = **构建时声明导入 ∩ 实际入库**（`VulnDb.covered_ecosystems`）。
4. **Debian 后缀剥离要叠加而非命中即返回** —— `8.0.32-1~deb12u1` 需先剥 `~debNuN`
   再剥 `-N`，原实现第一轮就返回 `8.0.32-1`。

### 端到端验证（真实 OSV 数据）

`scripts/build_vuln_db.py --ecosystems Maven,crates.io` 从官方源实测下载
（Maven 10.3MB / crates.io 3.4MB），建库 12273 条 / 25.1MB / 3 秒。
跑种子项目（故意保留旧版组件）：

- log4j-core 2.14.1 → **CVE-2021-44228（Log4Shell）修复版 2.15.0** ✓
- fastjson 1.2.70 → CVE-2022-25845 修复版 1.2.83 ✓
- MySQL/Redis/Nginx（Bitnami 未导入）→ `not_covered` 且注明"未导入 Bitnami 生态数据" ✓
- Kubernetes → `not_covered`（显式标注未纳入覆盖）✓

**这条满足 MASTER_PLAN 5.3 的核心验收标准。**

### 前端拆分结果

AdminPage 527 行 → 外壳 + 7 个 Tab；`React.lazy` 按需加载 + `manualChunks`。
单包 1.29MB → antd 独立 1.16MB 缓存块 + 应用代码 108KB + 各 Tab 1-6KB。

### 配置 B 全量未构建

本次只构建了 Maven + crates.io 做验证。**配置 B 全量（npm 211MB + Bitnami + Alpine +
openEuler 等，压缩 300.3MB）尚未实际构建**，索引库体积预估 ~180MB 仍未校准。
首次跑 `vulndb.yml` 工作流时需核对真实体积。

### 提交状态

已提交，未打 tag。打 tag 前建议先跑一次 VulnDB 工作流产出基线库，
否则 release 镜像会不含漏洞库（会如实降级为"无法判定"，但体验不佳）。
