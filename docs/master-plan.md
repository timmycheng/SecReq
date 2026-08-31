# SecReq 整体开发方案(内网部署版)

基线 v2.1.2 · 2026-08-30 · 整合评审、实施计划与离线漏洞库三份文档

> **状态说明(2026-08-31 由 `.workbuddy/` 同步至 docs/)**: 本文档是 v2.1.2 时期的开发总纲, v2.1.3 与 v2.2.0 已按其编排发布, v2.2.1 缺陷修复已按 issue 跟踪并发布。**当前完成状态一律以 issue / milestone 与 CHANGELOG 为准**, 流程规范以 [dev-workflow.md](dev-workflow.md) 为唯一权威来源; 本文保留用于跨版本约束、uid 迁移(#66)与 SCA 对接(#70)的方案依据、外部待确认项。原 `.workbuddy/` 配套文档已归档至 [archive/](archive/README.md)。

---

## 零、约束与目标

| 约束 | 来源 | 对方案的影响 |
| ---- | ---- | ------------ |
| 内网部署, 无互联网 | 你确认 | OSV 在线查询、OpenAI 在线调用均不可用 |
| 有 SCA 但对接能力未知 | 你确认 | **预留接口, v2.4.0 实现**; 本方案按"无 SCA"推进 |
| npm 生态必须纳入 | 你确认 | 离线库体积的主要来源(211.4 MB) |
| OS/中间件必须覆盖 | 你确认 | 需 Bitnami + Alpine + 发行版维度, Step7 增字段 |
| CNNVD 编号需对齐 | 你确认 | 叠加映射层, 不做组件匹配 |
| 数据经 CI 打进 Docker 镜像 | 你确认 | 漏洞库做独立 OCI artifact, 内置 + 挂载双轨 |

**总目标**: 交付一个可在银行内网独立运行、漏洞联动真实可用、需求溯源可靠的安全需求管理平台。

---

## 一、文档关系

| 文档 | 定位 | 状态 |
| ---- | ---- | ---- |
| **本文档** | **总纲**: 版本路线图、跨版本约束、待确认项 | 方案参考(状态以 issue/milestone 与 CHANGELOG 为准) |
| [archive/workbuddy-optimization-review.md](archive/workbuddy-optimization-review.md) | 问题清单与评级(P0/P1/P2), 各条目的事实依据 | 已完成 |
| [archive/workbuddy-implementation-plan.md](archive/workbuddy-implementation-plan.md) | 阶段 0-4 的文件级改动清单 | 已被本文版本编排取代, 细节仍可参照 |
| [archive/workbuddy-offline-vuln-db-plan.md](archive/workbuddy-offline-vuln-db-plan.md) | 离线漏洞库设计(v2, 含实测数据) | v2.2.0 已落地 |

> 本文与归档文档均为历史方案存档; 有冲突时以 issue / milestone 与 CHANGELOG 为准。

---

## 二、SCA 预留设计

**原则: 现在把"接缝"留好, 后面对接 SCA 时不改表结构、不改上层调用、不做数据迁移。**

### 2.1 现在就做(v2.2.0 随离线库落地)

**① 抽协议** `services/vuln_source.py`

```python
class VulnSource(Protocol):
    def query(self, purl: str, version: str) -> list[dict] | None: ...
    # 返回 OSV 形态的 vuln 字典列表; 不可用返回 None 触发降级
```

工厂按配置返回实现:

| 配置值 | 实现 | v2.2.0 状态 |
| ------ | ---- | ----------- |
| `local` | `OsvLocalSource` | **实现**(默认) |
| `online` | `OsvOnlineSource`(包装现有 `OsvClient`) | 实现(开发/演示) |
| `sca` | `ScaPlatformSource` | **预留**: 返回明确错误"未启用", 不静默失败 |

**② 数据模型预留列**(v2.2.0 一并加, 避免后面对接时再迁移)

```python
# models/sbom.py → VulnerabilityRecord
source: Mapped[str] = mapped_column(String(20), default="osv_local")
    # osv_local / osv_online / sca
external_ref: Mapped[str | None] = mapped_column(String(200))
    # SCA 侧的记录标识, 对接后用于回查与去重
cnnvd_id: Mapped[str | None] = mapped_column(String(32))
    # CNNVD 编号(本版即可填充)
```

**③ 结果汇总带来源标识**

`OsvSyncResult.summary_text()` 输出"数据来源: 本地漏洞库 v20260830",前端与导出文档显示来源与库版本 —— 对内网友好, 也便于合规说明。

### 2.2 v2.4.0 对接 SCA 时的工作量

1. 新增 `services/sca_source.py`, 实现 `ScaPlatformSource`;
2. 在工厂注册, 配置项切到 `sca`;
3. 补对接测试。

**协议、表结构、pipeline、规则引擎、前端、导出全部不动。**

### 2.3 为什么现在只留接缝而不实现

SCA 可对接性未知(7 条核查清单见 `archive/workbuddy-offline-vuln-db-plan.md` 2.3)。
**前两条任一为否就无法对接** —— 是否提供 REST API、是否支持按组件坐标查询。
在结论出来前投入实现是浪费; 但接缝成本几乎为零, 不做才是浪费。

---

## 三、版本路线图

版本类型严格按 SemVer(与 CHANGELOG 既有风格一致: 2.1.1 纯修复为 PATCH,
2.1.2 因新增 `description` 字段为 MINOR)。

| 版本 | 类型 | 主题 | 定级依据 | 阻塞上线 | 风险 |
| ---- | ---- | ---- | -------- | -------- | ---- |
| **v2.1.3** | **PATCH** | 缺陷修复与内网基建 | 只修缺陷, 无任何新增功能或字段 | 否(建议先做) | 低 |
| **v2.2.0** | MINOR | 离线漏洞库 + SCA 预留 | 新增数据源/脚本/管理页/Step7 字段 | **是** | 中 |
| **v2.3.0** | MINOR | 数据一致性(uid 迁移) | 虽修缺陷, 但改数据模型与前端保存契约 | 否 | **高** |
| **v2.4.0** | MINOR | SCA 对接 | 新增数据源实现 | 否 | 中 |

**工程质量(CI 补全 / 组件拆分 / E2E)不单独占版本号**, 见第八节 —— 产品行为未变,
不构成 SemVer 语义上的变更。

**排序理由**: v2.1.3 全是低风险修复, 先出一批稳定成果垫底;
v2.2.0 是内网上线的功能阻塞项(没它漏洞联动就是死的);v2.3.0 带数据迁移, 单独发版以便出问题时精确定位。

---

## 四、v2.1.3 缺陷修复与内网基建(PATCH)

**定级说明**: 本节全部为缺陷修复与不影响产品契约的工程改进, 无新增功能、无新增字段,
因此为 PATCH 而非 MINOR。

### 4.1 测试护栏(先写红灯测试)

新增 `tests/test_traceability_stability.py`、`tests/test_osv_concurrency.py`。4 个测试锁定 v2.3.0 的目标行为, 1 个锁定并发度。
**验收**: 新测试全红, 既有 137 个用例全绿。

### 4.2 快赢补丁

| 项 | 文件 | 改动 |
| -- | ---- | ---- |
| 异常脱敏 | `routers/generate.py:105`、`routers/steps.py:233` | `logger.exception` 记栈 + trace_id, 客户端只收通用文案 |
| `saas_finance` 炸弹 | `rules/engine.py:476` | 跳过坏模板并记录, 而非中断整轮生成 |
| 上传限制 | `routers/steps.py:221/334` | `max_upload_size` 5 MB, 超限 413 |
| 审计补全 | `routers/auth.py`、`projects.py`、`generate.py` | 补 login_failed / project_delete / export / step_save |
| 死代码 | `models/database.py:16` | 删 `_sqlite_kwargs()` |

### 4.3 内网部署基建

| 项 | 问题 | 改动 |
| -- | ---- | ---- |
| **时区** | **10 处 `datetime.now()`, 容器无 TZ 设置 → 时间整体差 8 小时** | Dockerfile 加 `ENV TZ=Asia/Shanghai`; compose 同步注入 |
| 日志 | `main.py:46/51` 用 print, 其余 188 处用 logging | 统一为 logging, 配置 handler 输出到 stdout |
| SQLite 并发 | 无 WAL / busy_timeout | `make_engine` 加 event listener 设 PRAGMA |
| 依赖锁定 | `requirements.txt` 全 `>=` | 出 `requirements.lock`, Dockerfile 装锁文件 |
| HTTPS | 仅 EXPOSE 8000 走 HTTP | 提供 Nginx 反代模板 + 证书挂载说明(容器本身不改) |
| LLM 内网化 | `feature_extract` 调 OpenAI 兼容接口, 内网不通 | 配置页加提示: 填行内大模型 base_url, 留空则用关键词规则(降级已内建) |
| 交付模板 | 缺内网 compose | 新增 `docker-compose.intranet.yml`(含漏洞库挂载与 TZ) |

**时区这条单独说**: `services/session_service.py:48` 的过期判断与写入都用 `datetime.now()`,
所以**会话逻辑自洽不会出错**, 但页面上"确认时间""导出时间""审计时间"会显示成 UTC。这是内网交付后用户第一批发现的问题, 成本一行, 收益明显。

**验收**: 137+ 用例通过; 容器内 `date` 与页面显示时间一致;
断网环境下 `docker compose up` 可完整启动并走通向导。

---

## 五、v2.2.0 离线漏洞库(MINOR, 内网功能阻塞项)

**定级说明**: 新增独立数据源、构建脚本、管理端页面, 且 Step7 新增「生态」「分发渠道」
两个字段 —— 与 2.1.2 因新增 `description` 字段而定为 MINOR 同理。

详细设计见 `archive/workbuddy-offline-vuln-db-plan.md`, 此处只列任务与验收。

### 5.1 任务清单

| # | 任务 | 文件 | 依赖 |
| - | ---- | ---- | ---- |
| 1 | `VulnSource` 协议 + 工厂 + SCA 预留位 | `services/vuln_source.py`(新) | — |
| 2 | 数据模型预留列 | `models/sbom.py` | — |
| 3 | 漏洞库构建脚本 | `scripts/build_vuln_db.py`(新) | 1 |
| 4 | 版本归一化器 | `services/vuln_match/`(新) | 1 |
| 5 | Local 实现 + 生态/distro 映射 | `services/vulndb.py`(新) | 3, 4 |
| 6 | **修 `pkg:generic` + Step7 增生态/distro 下拉** | `services/sbom.py:34`、`Step7Components.tsx`、`types.ts` | — |
| 7 | 缓存语义改为库版本(库变更即全量重算) | `services/osv.py` | 5 |
| 8 | CNNVD 映射层 + 导出补字段 | `scripts/build_cnnvd_map.py`(新)、`doc_export.py`、`tracking_export.py` | 5 |
| 9 | 管理端漏洞库页 + SHA256 校验 + 审计 | `routers/admin.py`、`AdminPage.tsx` | 5 |
| 10 | CI 构建漏洞库 artifact + 打进镜像 | `.github/workflows/vulndb.yml`(新)、`release.yml`、`Dockerfile` | 5 |
| 11 | Actions 构建缓存瘦身 | `.github/workflows/release.yml` | 10 |
| 12 | GHCR 版本保留规则 | `.github/workflows/retention.yml`(新) | 10 |
| 13 | Release 附件保留策略 | `.github/workflows/release.yml` | 10 |

### 5.2 生态选型(基于实测, 目标环境已确认)

**目标环境**: 宿主 OS 为银河麒麟(V10)、中间件用 Bitnami 容器镜像、基础库用 Alpine 容器镜像。

```
语言层   npm 211.4 + Maven 9.8 + PyPI 32.4 + Go 10.9 + NuGet 2.4 + crates.io 3.3
OS 层    Bitnami 8.8 + Alpine 3.9
宿主层   openEuler 17.4(麒麟 V10 血统, 必导)
────────────────────────────────────────────
合计 300.3 MB(压缩), 索引库预估 ~180 MB
```

- **麒麟 V10 的技术血统是 openEuler 而非 CentOS/RHEL**(麒麟官方《云底座操作系统 V10
  版本发布说明》:"继续基于 openEuler 22.03 LTS"; 包管理 RPM/dnf; glibc 2.34+)。  因此宿主层选 openEuler, **不再默认导入 RHEL 系**。
- RHEL 系(Red Hat 25.3 + Rocky 4.5 + AlmaLinux 5.9 = 35.7 MB)仅在其他环境仍跑
  RHEL/CentOS 时才追加。
- **不导入**: Ubuntu 623 MB(性价比极低)、GIT 176.7 MB(commit 级, 对版本匹配无用)。
- **⚠️ 麒麟本身不在 OSV 生态列表内**, openEuler 只是代理匹配, 存在系统性缺口, 见 5.4。

### 5.3 验收标准

- [ ] `scripts/build_vuln_db.py` 可离线产出 `vulndb.sqlite`, 记录数与体积有明确报告
- [ ] **用种子数据(故意保留旧版组件)验证能命中真实 CVE** —— 这是功能是否真的可用的判据
- [ ] Bitnami 层的 redis / nginx / mysql 能用标准版本号直接命中
- [ ] Alpine 层的 openssl `1.0.2h` 能通过 `-rN` 规整命中 `1.0.2h-r0`
- [ ] 断网环境下全链路可用, 无一处尝试访问外网
- [ ] 三种"查不到"语义在界面上可区分: 未覆盖 / 无法判定 / 未发现
- [ ] 镜像内置基线库, 挂载外部 sqlite 可覆盖生效

### 5.4 风险

| 风险 | 应对 |
| ---- | ---- |
| npm 实测体积远超预估 | 先单导 npm 实测; 超限则启用 zlib 存 raw(实测可降到 12-31%) |
| 发行版生态选错(目标环境不在列表) | 发行版层做成可配置, 更换生态只需改构建参数重跑 |
| 跨渠道模糊匹配误报 | 命中一律标注"待确认", 不静默报为确认漏洞 |
| K8s 无覆盖 | 明确标注未覆盖, 不阻塞主线; 后续由 SCA 或单独数据源补 |
| **漏洞库体积失控拖大镜像与附件** | 见 5.5: 只走 GHCR OCI, 不进 Release 附件 |
| **麒麟覆盖缺口(v2.2.0 无法完全闭合)** | 见 5.6: openEuler 代理 + 向麒麟索取正式数据源 |

### 5.6 麒麟(Kylin)覆盖缺口 —— 必须在验收时明确交代

**麒麟不在 OSV 的 39 个生态中**(已核对 `ecosystems.txt`)。openEuler 代理匹配能覆盖
同源组件的上游 CVE, 但以下四类**系统性失真无法回避**:

| 失真类型 | 后果 |
| -------- | ---- |
| 麒麟独立 backport 补丁 | 误报: openEuler 已修 ≠ 麒麟已修, 反之亦然 |
| 麒麟自有组件(kysec-daemon、ukui-session-manager 等) | **完全漏报**, 只有麒麟源有 |
| 架构维度(aarch64/loongarch64/mips64el/sw_64) | OSV 数据不含架构, 无法区分 |
| KVE 编号 | 无, 需单独映射(同 CNNVD 处理) |

麒麟官方 CVE 门户 `https://support.kylinos.cn/#/security/cve` 数据完备(CVE + KVE 双编号、按产品版本与架构细分、含修复版本), 但**无公开机器可读接口**(SPA, 常见 API 路径均 404)。

**推进路径(组合)**:

1. **向麒麟索取正式数据源(首选, 并行推进)** —— 银行采购麒麟通常含服务合同,
   直接向麒麟或集成商索取离线数据包 / OVAL / 安全公告订阅。最合规, 且能补齐 KVE 与架构维度。
2. **openEuler 代理(过渡, v2.2.0 内落地)** —— 结果**必须标注推断来源**,
   展示文案: 「基于 openEuler 同源数据推断; 麒麟的补丁回合与组件范围与上游存在差异,   最终以麒麟官方安全公告为准」。
3. 拿到麒麟数据后新增 `KylinSource` —— `VulnSource` 协议天然支持多源, 上层零改动。

**v2.2.0 验收时必须明确交代这一缺口**, 不得让麒麟相关结果以"确认"面貌呈现。

### 5.5 产物体积与存储治理

仓库为 **private**, 产物体积会持续累积。2026-08-30 实测与官方限额核对:

| 项 | 实测用量 | 限额 | 判断 |
| -- | -------- | ---- | ---- |
| Release 附件 | 3 个共 205.1 MB(64.9 / 70.1 / 70.1) | 单文件 ≤2 GB; 建议仓库 <1 GB | **唯一长期风险** |
| Actions 缓存 | 773.2 MB / 85 个 | 10 GB/仓库, 7 天未访问自动淘汰 | 在限内但浪费 |
| Actions 构件 | 4 个共 0.4 MB | 与 Packages 共享额度 | 可忽略 |
| GHCR 镜像存储 | — | **目前免费**(容器注册表免费期延长) | 暂不计费 |
| Actions 时长 | 每次 release 约 8-10 分钟 | Free 2,000 分钟/月 | 充裕 |

**核心结论**: GHCR 容器镜像当前不计费, 镜像体积短期不是压力;
**真正的风险是 Release 附件按版本累积**。当前每版 +70 MB,
若把 ~200 MB 漏洞库打进应用镜像, 每版将变成 +150~200 MB,十个版本即逼近 1 GB 软警告线 —— **这正是本节三条治理任务的由来**。

**三条硬约束(任一不得违反)**:

1. **漏洞库绝不随 Release 附件分发。** 只走独立的 GHCR OCI artifact
   `secreq-vulndb:YYYYMMDD`(容器镜像存储当前免费), 主镜像保持 ~70 MB。   任务 10 与任务 11-13 必须一起验收, 否则等于把风险又搬回附件。
2. **应用镜像内置的是精简基线库, 不是完整库。** 完整库通过挂载覆盖
   (见 `archive/workbuddy-offline-vuln-db-plan.md` 5.1 的双轨设计)。
3. **Release 附件保留最近 N 个版本**(建议 N=3), 更旧的自动清理。

**任务 11 细节 —— Actions 缓存瘦身**

现状 `release.yml` 用 `cache-to: type=gha,mode=max`, 把构建的全部中间层都存入缓存,累积到 773 MB / 85 个。改为:

- `cache-to: type=gha,mode=min`(只存最终层, 够用且小一个数量级);
- 或保留 `mode=max` 但给 `scope` 加版本维度, 避免跨版本无限堆积;
- 缓存本身 7 天未访问会自动淘汰, 主要收益是缩短构建时间而非省配额。

**任务 12 细节 —— GHCR 版本保留规则**

新增 `retention.yml`(定时或手动触发), 清理:

- 无 tag 的悬空版本;
- 超出保留窗口的旧版本(建议保留最近 3 个 minor 版本 + 所有 patch);
- **注意**: `latest` 与当前 minor 标签不得删除。

**任务 13 细节 —— Release 附件保留策略**

在 `release.yml` 的 release job 末尾追加清理步骤, 或在 `retention.yml` 中统一处理:按创建时间倒序保留最近 N 个 Release 的附件, 删除更旧 Release 上的`secreq-image-v*.tar.gz`(代码与 tag 仍在, 镜像可从 GHCR 重新导出)。

---

## 六、v2.3.0 数据一致性(uid 迁移, MINOR)

**定级说明**: 修的是 P0-1/P0-2 两个缺陷, 性质上像 PATCH;
但它改动数据模型(增 uid 列、改 `sensitive_asset_ids`)并要求前端保存时回传 uid,
**契约发生了变化, 不再是向后兼容的修复**, 因此定 MINOR。

详细设计见 `archive/workbuddy-implementation-plan.md` 阶段 3, 此处只列要点。

### 6.1 要解决的两个 P0

- **P0-1** `rules/engine.py:171` 全删全插 → 重新生成会清空所有确认记录
- **P0-2** `services/step_store.py` 整表替换 → 主键变化, 已生成需求的 `source_entity_id` 断链

### 6.2 关键设计(已核准模型后确定)

- 加 uid 列的模型 **8 个**: Feature / DataAsset / SbomComponent / Role / Resource /
  ApiEndpoint / InfraAsset / ExternalSystem
- `permission_entry` **不加列**, 用 `(role_uid, resource_uid, action)` 复合键
- 无需改动: `project` / `compliance_target` / `auth_config` / `policy_baseline`
- `ApiEndpoint.sensitive_asset_ids` → `sensitive_asset_uids`(**第二处同类隐患**)
- 存量断链数据标 `status="obsolete"`, 保留 `source_label`, **不伪造映射**
- 前端保存步骤须回传 uid; 后端 409 保护(有生成记录却全行无 uid → 拒绝)

### 6.3 验收与风险

**验收**: 阶段 0 的 4 个红灯测试转绿; 手工回归"生成 → 确认 → 改一步 → 重新生成"
后确认状态保留且溯源正确; 存量库 `--dry-run` 先出断链比例报告。

**风险**: 唯一带数据迁移的版本, 单向不可逆, 必须连数据库一起备份。
**回滚**: 保留迁移前 db 备份 + 代码回退到上一 tag。

---

## 七、v2.4.0 SCA 对接(MINOR)

前置: 拿到 SCA 核查结论(7 条清单)。工作量: 新增 `services/sca_source.py` + 工厂注册 + 对接测试。
**表结构与上层调用零改动**(v2.2.0 已预留接缝与新列)。

即使 SCA 可对接, 本地库仍建议保留: 降级备份、交叉验证漏报、开发/测试环境权限差异。

---

## 八、工程质量与 CI(不单独占版本号)

产品行为未变, 不构成 SemVer 语义变更, 因此**不占用版本号**, 按下面节奏分散进行:

| 项 | 时机 | 理由 |
| -- | ---- | ---- |
| CI 补全(PR 触发: pytest + oxlint + `tsc -b` + build) | **立刻做** | 越早越好, 后续每个版本都受益 |
| 组件拆分 | **随 v2.2.0 一起** | v2.2.0 本就要改 `Step7Components.tsx` 与 `AdminPage.tsx`(加漏洞库页), 顺势拆分, 避免二次改动 |
| 代码分割(vite manualChunks / React.lazy) | 随 v2.2.0 | 同上, 前端构建链本就要动 |
| E2E(Playwright 覆盖建项目 → 8 步 → 生成 → 确认 → 导出) | **v2.3.0 之后** | v2.2.0 与 v2.3.0 都会改前端保存契约, 提前写会反复返工 |

`AdminPage.tsx` 527 行六个 Tab 相互独立, 拆分收益最高、风险最低, 建议第一个拆。

---

## 九、跨版本约束(每次改动都要遵守)

1. **单一枚举源**: 共享枚举放 `shared/constants.py`, 经 `/api/meta/constants` 供前端,
   路由层与前端不得重复定义。
2. **知识库模板必带 `regulatory_ref`**, 不得编造条款号。
3. **角色固定两个**: `developer`(仅本人项目)/ `security`(全量 + 系统管理), 越权一律 404。
4. **种子密码走 `SECREQ_SEED_PASSWORD`**, 源码内不得出现固定口令。
5. **迁移脚本一律支持 `--dry-run` 且幂等**, 与 `services/` 共用实现(沿用
   `migrate_classification.py` 的既有约定)。
6. **不得改动**: 占位符白名单渲染(`engine.py:36`)、OSV 多坐标过滤(`osv.py:201`)、
   数据权限收口(`routers/common.py`)、YAML 写回的备份校验回滚(`kb_admin.py`)。
7. **内网友好**: 任何新增功能不得引入对互联网地址的硬编码依赖;
   确需外部调用的必须可配置且具备降级路径。
8. **大体积数据不进 Release 附件**: 仓库为 private, 产物按版本累积
   (实测已 205 MB / 3 个版本)。漏洞库等大文件一律走 GHCR OCI artifact,   Release 附件只保留应用镜像包且仅留最近 3 个版本。见 5.5。

---

## 十、待确认(按影响排序)

~~1. 目标发行版 / 2. 是否用 Bitnami / Alpine 容器镜像~~ → **已确认**: 银河麒麟 +Bitnami + Alpine。选型见 5.2, 麒麟缺口见 5.6。

1. **麒麟的具体版本?**(V10 SP1/SP2/SP3 还是 V11)不同 SP 基于的 openEuler 版本不同,
   影响代理匹配的准确度。**同时请尽快启动"向麒麟索取正式数据源"(见 5.6 路径 ①)** ——   这是唯一能闭合缺口的途径, 走采购/服务渠道可能耗时较久, 越早启动越好。
2. **麒麟的部署形态**: 裸机 / 虚机 / 容器? 若中间件全跑在 Bitnami 容器里,
   麒麟层面需要覆盖的主要是 OS 基础包与内核 —— 缺口影响相对可控。
3. **Docker 基础镜像是什么?** 若是 Alpine 则与 ② 层重合; 若是麒麟基础镜像则另需处理。
4. **SCA 核查结论** —— 建议尽快拿到, 决定 v2.4.0 是否启动以及怎么实现。
5. **K8s 缺口**: 标注未覆盖即可, 还是必须补?
6. **CNNVD / KVE 只需编号, 还是要中文危害等级与中文标题?**
7. **漏洞库更新频率**: 决定 CI 定时周期与摆渡流程的常态化安排。
8. **v2.3.0 的 obsolete 需求如何展示**: 隐藏 / 置灰 / 保留并标注"风险已消除"?

---

## 附: 立即可开工的三件事(无依赖)

| # | 事项 | 说明 | 状态 |
| - | ---- | ---- | ---- |
| 1 | 时区修复 | 一行 `ENV TZ=Asia/Shanghai` | ✅ v2.1.3 已完成 |
| 2 | SCA 核查 | 7 条清单, 结论影响 v2.4.0 的存废 | 待办 |
| 3 | npm 单生态实测 | 下载 `npm/all.zip` 建库, 校准 v2.2.0 的体积预估 | 待办 |
| 4 | **启动向麒麟索取数据源** | 走采购/服务渠道, 周期可能较长, 越早越好 | 待办 |
| 5 | Actions 缓存瘦身 | `mode=max` → `min`, 现状 773 MB | 待办(并入 v2.2.0) |
