# 内网离线漏洞库方案 v2

基线 v2.1.2 · 2026-08-30 · 替代 [OPTIMIZATION_REVIEW.md](OPTIMIZATION_REVIEW.md) 中的 OSV 在线查询

> 本版相对 v1 的变化, 全部来自新确认的约束:
> **SCA 可对接性未知 / npm 必须纳入 / OS 必须覆盖 / CNNVD 需对齐 / 希望通过 CI 把数据打进 Docker 镜像。**
> 所有体积与覆盖结论均基于对 OSV 官方数据源的**实测**, 非估算。

---

## 〇、实测数据(决定后面所有取舍)

### 0.1 各生态离线包真实体积

2026-08-30 对 `https://osv-vulnerabilities.storage.googleapis.com/<ECO>/all.zip` 实测:

| 生态 | 压缩包 | 定位 | 建议 |
| ---- | ------ | ---- | ---- |
| **npm** | **211.4 MB** | 前端组件 | **必导**(你已确认) |
| Maven | 9.8 MB | Java 后端 | 必导 |
| PyPI | 32.4 MB | Python | 必导 |
| Go | 10.9 MB | Go | 导 |
| NuGet | 2.4 MB | .NET | 导 |
| crates.io | 3.3 MB | Rust | 导(极小) |
| **Bitnami** | **8.8 MB** | **容器化中间件(见 0.2)** | **必导, OS 覆盖主力** |
| **Alpine** | **3.9 MB** | **C 库与基础工具(见 0.2)** | **必导** |
| Red Hat | 25.3 MB | RHEL 系 | 按需 |
| openEuler | 17.4 MB | 信创/国产化 | 按需 |
| AlmaLinux | 5.9 MB | RHEL 兼容 | 按需 |
| Rocky Linux | 4.5 MB | RHEL 兼容 | 按需 |
| Debian | 72.2 MB | Debian 系 | 按需 |
| Linux | 52.9 MB | Linux 内核 | 按需 |
| openSUSE | 20.6 MB | SUSE 系 | 按需 |
| SUSE | 44.5 MB | SUSE 商业版 | 按需 |
| Chainguard / Wolfi / MinimOS / Root / Azure Linux / TuxCare / Echo / Mageia | 4-64 MB | 容器镜像发行版 | 视基础镜像选型 |
| **Ubuntu** | **623.0 MB** | Ubuntu | **不建议导, 见 0.4** |
| **GIT** | **176.7 MB** | commit 级 | **不建议导, 见 0.4** |

### 0.2 你的基础设施清单, 实测覆盖情况

`shared/constants.py:271` `COMMON_COMPONENTS` 里的中间件与基础库, 逐个实测:

| 组件 | Bitnami | Alpine | 说明 |
| ---- | ------- | ------ | ---- |
| MySQL / MariaDB | `mysql-client` `mysql-shell` `mariadb` `mariadb-galera` | `mariadb` `mariadb-connector-c` | 覆盖, 注意 Bitnami 无 `mysql` 主包 |
| Redis | `redis` | `redis` | 双覆盖 |
| Nginx | `nginx` `nginx-agent` `nginx-gateway` | `nginx` | 双覆盖 |
| Kafka | `kafka` | — | 仅 Bitnami |
| RabbitMQ | `rabbitmq` `rabbitmq-c` | `rabbitmq-c` | 覆盖 |
| Elasticsearch | `elasticsearch` | — | 仅 Bitnami |
| Tomcat | `tomcat` | — | 仅 Bitnami |
| PostgreSQL | `postgresql` `postgresql-jdbc-driver` | `postgresql` `postgresql13/14` | 双覆盖 |
| MongoDB | `mongodb` | — | 仅 Bitnami |
| OpenSSL | — | `openssl` `openssl3` | 仅 Alpine(及发行版生态) |
| ImageMagick | — | `imagemagick` | 仅 Alpine |
| FFmpeg | — | `ffmpeg` | 仅 Alpine |
| zlib | — | `zlib` `zlib-ng` | 仅 Alpine |
| curl / libcurl | — | `curl` | 仅 Alpine(另有独立 Curl 生态) |
| Docker | `docker-cli` | — | 仅 Bitnami |
| **Kubernetes** | — | — | **两个生态都无覆盖, 需另找源** |

**结论**: Bitnami 与 Alpine 高度互补, 合计仅 **12.7 MB** 就覆盖了上表除 K8s 外的绝大多数条目。性价比极高。

### 0.3 版本形态(决定匹配能不能落地)

实测样本:

```
Bitnami / BIT-redis-2021-31294
  package: {"name":"redis","ecosystem":"Bitnami","purl":"pkg:bitnami/redis"}
  ranges:  [{"type":"SEMVER","events":[{"introduced":"0"},{"fixed":"6.2.0"}]}]

Alpine / ALPINE-CVE-2016-2105
  package: {"name":"openssl","ecosystem":"Alpine:v3.2","purl":"pkg:apk/alpine/openssl?arch=source"}
  ranges:  [{"type":"ECOSYSTEM","events":[{"introduced":"0"},{"fixed":"1.0.2h-r0"}]}]
  versions: ["0.9.8i-r0","0.9.8j-r0",...]
```

两个关键结论:

1. **Bitnami 用标准 semver(`6.2.0`), 现有 `_version_key` 可直接匹配, 零适配。**
2. **Alpine 用发行版包版本(`1.0.2h-r0`), 带 `-rN` 后缀。** 用户填 `OpenSSL 1.0.2h` 匹配不上 `1.0.2h-r0`。
   但记录里带了**完整 `versions` 枚举**(Alpine 全库 78,099 个), 可以走"用户输入版本 → 在枚举里做
   `-rN` 后缀规整后精确匹配", 比范围比较更可靠。

**这印证了一个判断: OS 覆盖的技术难点不在数据源, 而在"发行版"这个维度。**
同一个 MySQL 8.0.32, 在 Debian 是 `8.0.32-1~deb12u1`, 在 RHEL 是 `8.0.32-1.el9`,
在 Bitnami 是 `8.0.32-debian-11-r0`。**版本号串完全不同, 不知道分发渠道就无法匹配。**

### 0.4 两个体积陷阱

- **Ubuntu 623 MB** —— 是 Debian(72 MB) 的 8.6 倍。发行版生态的数据量与"发行版本数"成正比,
  Ubuntu 的 LTS + interim 版本极多。若目标环境不是 Ubuntu, **不要导**。
- **GIT 176.7 MB** —— commit 级匹配(`introduced: <commit-hash>`), 对"版本号"几乎无用。
  占了大体积却不解决你的问题, **不导**。

### 0.5 裁剪与压缩实测

对 Bitnami / Alpine 全库实测(裁剪 = 去 `details` 全文 + `references` 限 3 条 + 去 `versions` 枚举):

| 生态 | 记录数 | 原始 JSON | 裁剪后 | zlib(9) 后 | 丢弃的 details |
| ---- | ------ | --------- | ------ | ---------- | -------------- |
| Bitnami | 9,079 | 15.9 MB | 9.8 MB (61%) | **4.9 MB (31%)** | 3.8 MB |
| Alpine | 4,566 | 17.7 MB | 15.2 MB (85%) | **2.2 MB (12%)** | 1.6 MB |

**zlib 压缩 raw JSON 的收益极大(降到 12-31%)**, 远超字段裁剪。建议: 索引库直接 zlib 存 raw,
查询时只对候选记录解压(按包名索引取候选, 一个包通常几十到几百条, 解压开销可忽略)。

---

## 一、目标环境(已确认)

| 维度 | 选型 | 覆盖来源 |
| ---- | ---- | -------- |
| 宿主 OS | **银河麒麟**(V10 系列) | ⚠️ **缺口**, 见 3.6 |
| 中间件 | **Bitnami 容器镜像** | Bitnami 生态, 已覆盖 |
| 基础库/工具 | **Alpine 容器镜像** | Alpine 生态, 已覆盖 |
| 应用开发栈 | Java 为主 + 前端 | Maven / npm / PyPI / Go / NuGet / crates.io |

> 麒麟 V10 的技术血统是 **openEuler**(非 CentOS/RHEL)。
> 依据: 麒麟官方《云底座操作系统 V10 版本发布说明》写明"继续基于 openEuler 22.03 LTS";
> 包管理为 RPM/dnf; glibc 2.34+。
> **这条决定了代理匹配的上游应选 openEuler, 而不是 Red Hat/Rocky/AlmaLinux。**

### 1.1 推荐配置与体积预估

| 配置 | 内容 | 压缩包合计 | 索引库预估 |
| ---- | ---- | ---------- | ---------- |
| **A 精简** | 语言层 + Bitnami + Alpine | 282.9 MB | ~170 MB |
| **B 推荐(本环境)** | A + **openEuler**(麒麟血统, 必导) | 300.3 MB | ~180 MB |
| C 加 RHEL 系 | B + Red Hat + Rocky + AlmaLinux | 336.0 MB | ~200 MB |
| D 全量 | C + Debian + Linux 内核 | 461.1 MB | ~280 MB |

- **本环境按配置 B**。RHEL 系(35.7 MB)仅在其他环境仍跑 RHEL/CentOS 时才需要。
- Linux 内核生态(52.9 MB)按需: 麒麟内核是 openEuler 优化版, 版本号不直接对应上游,
  若要求内核级覆盖需单独评估, 见 3.6。

> 索引库体积按 0.5 实测的"zip → 原始 → zlib"折算链外推(约 0.6x)。
> **npm 占比最大且记录形态与 Bitnami/Alpine 不同, 该数字需首次构建后校准。**

**建议先按配置 B 构建**, 拿到真实索引库体积后再决定是否加减生态。

---

## 二、SCA 可对接性未知的处理

### 2.1 三实现 + 运行时降级链

```
VulnSource(协议)
├── ScaPlatformSource   行内 SCA(若可对接)—— 优先
├── OsvLocalSource      内置离线库 —— 兜底 / 交叉验证
└── OsvOnlineSource     开发演示环境(能联网)
```

运行时按配置选, 且**支持失败自动降级**: SCA 不可用 → 自动切本地库, 不阻塞生成流程。
上层 `sync_vulnerabilities` / `pipeline` / `rules/engine.py` **零改动**。

### 2.2 为什么即使 SCA 能对接, 本地库仍要建

1. **降级备份**: SCA 平台会停机、升级、变更网络策略;
2. **交叉验证**: 两个源可互相补漏报, 对安全产品是实打实的加分项;
3. **环境差异**: 开发/测试环境常常拿不到生产 SCA 的接入权限;
4. **成本已很低**: 主要工作量就一个 `scripts/build_vuln_db.py`。

### 2.3 给你的 SCA 核查清单

按这个顺序问供应商/查文档, **前两条任一为否, 就直接走本地库方案**:

1. 是否提供 **REST API**(而非只有 Web 界面)?
2. 是否支持按**组件坐标**查询?
   (purl / `groupId:artifactId:version` / 包名+版本 任一即可; 只支持按 CVE 号查则无用)
3. 认证方式? (Token / mTLS / IP 白名单 —— 影响能否在容器里调用)
4. 返回字段能否映射到现有 `VulnerabilityRecord`?
   (`cve_id` `severity` `cvss_score` `affected_range` `fix_version` `summary`)
5. 是否有 **QPS / 配额限制**? (生成时可能一次查几十个组件)
6. 是否有 OpenAPI / Swagger 文档?
7. 商用软件是否**需额外购买 API 模块**? (常见坑, 早早问清楚)

---

## 三、OS 覆盖的设计(本次新增重点)

### 3.1 三层结构

| 层 | 数据源 | 覆盖 | 版本形态 | 适配成本 |
| -- | ------ | ---- | -------- | -------- |
| ① 容器化中间件 | **Bitnami** | MySQL/Redis/Nginx/Kafka/RabbitMQ/ES/Tomcat/PostgreSQL/MongoDB | 标准 semver | **零**(复用 `_version_key`) |
| ② 基础 C 库与工具 | **Alpine** | OpenSSL/ImageMagick/FFmpeg/zlib/curl | `X.Y.Z-rN` | 中(走 versions 枚举) |
| ③ 发行版包 | Debian / Red Hat / openEuler … | 取决于选型 | `X.Y.Z-N.el9` 等 | 中(需 distro 维度) |

### 3.2 Step7 必须增加 `distro` 字段

这是 OS 覆盖的**前提**, 绕不过去。建议在组件录入增加「分发渠道」下拉:

```
Bitnami 镜像 / Alpine / Debian / Ubuntu / RHEL 系(Red Hat·Rocky·Alma) / openEuler / 其他发行版 / 源码编译
```

与 purl 规范的 `?distro=` qualifier 对齐:
`pkg:apk/alpine/openssl@1.0.2h-r0?distro=alpine-3.18`

**降级策略**: 未填 distro 时, 走"跨渠道模糊匹配 —— 按包名在全部已导入生态中查,
提取用户输入版本号做前缀规整后比对", 命中即返回但**标注「待确认: 请补充分发渠道以精化」**。
宁可给带标注的疑似结果, 也不要静默显示"无漏洞"。

### 3.3 每个发行版需要一个版本归一化器

建议 `services/vuln_match/` 下按生态各写一个, 保持与 `_version_key` 同风格的"宽松比较":

| 生态 | 形态 | 归一化要点 |
| ---- | ---- | ---------- |
| Bitnami | `6.2.0` | 直接用现有 `_version_key` |
| Alpine | `1.0.2h-r0` | 剥离 `-rN` 后缀后比较 |
| Debian/Ubuntu | `1.18.0-6+deb11u2` | 剥离 `-N` 与 `+debNuN` 后缀 |
| RHEL 系 | `1.18.0-1.el9` | 剥离 `-N.elN` 后缀 |

**优先走记录里的 `versions` 枚举精确匹配, 枚举缺失时再退化为范围比较。**

### 3.4 K8s 的缺口

Bitnami 与 Alpine 都无 Kubernetes 覆盖。可选:
- 接 K8s 官方 CVE 源(`https://kubernetes.io/docs/reference/issues-security/` 的 CVE 列表);
- 或从 NVD/GHSA 单独拉 K8s 相关记录;
- 若行内 SCA 覆盖 K8s, 由 SCA 补。

**建议先标注为"未覆盖", 不阻塞主方案。**

### 3.6 ⚠️ 麒麟(Kylin)覆盖缺口 —— 本环境的真实差距

**结论先行: 麒麟不在 OSV 生态列表内, openEuler 只能做"代理匹配", 不是等价替代。**

已核实 `ecosystems.txt`(39 个生态)中**没有 Kylin**。麒麟官方有 CVE 门户
`https://support.kylinos.cn/#/security/cve`, 含 CVE + **KVE 双编号**、风险等级、
受影响产品(按 V10 SP1/SP2/SP3、V11 等细分)、**架构**(aarch64 / loongarch64 /
mips64el / x86_64 / sw_64)、修复版本与关联安全公告 —— 数据很完备, 但:
门户是 SPA, 常见 API 路径均返回 404, **目前没有公开的机器可读接口**。

#### 用 openEuler 代理能覆盖什么、不能覆盖什么

| 维度 | openEuler 代理 | 说明 |
| ---- | -------------- | ---- |
| 上游同源组件的 CVE | 大致可用 | 麒麟 V10 基于 openEuler 22.03 LTS, 包名与版本序列接近 |
| **麒麟独立 backport 的补丁** | ❌ 必然失真 | 麒麟会独立回合补丁: openEuler 已修 ≠ 麒麟已修, 反之亦然 |
| **麒麟自有组件的漏洞** | ❌ 完全漏报 | 如 `kysec-daemon`(KVE-2026-07277)、`ukui-session-manager`(KVE-2026-05165) 只存在于麒麟源 |
| **架构维度** | ❌ 无此信息 | OSV 数据不含架构; 麒麟门户按 aarch64/loongarch64/mips64el/sw_64 分别标注"影响/不影响" |
| **内核版本对应** | ⚠️ 需单独核 | 麒麟内核为 openEuler 优化版, 版本号不直接对应上游 |
| **KVE 编号** | ❌ 无 | 合规通报常要求国产编号, 需单独映射(同 CNNVD 处理) |

#### 三条路径(建议组合推进)

| 路径 | 可行性 | 说明 |
| ---- | ------ | ---- |
| **① 向麒麟索取正式数据源** | **推荐, 首选** | 银行采购麒麟通常含服务合同。直接向麒麟或集成商索取离线数据包 / OVAL / 安全公告订阅。最合规、最可靠, 且能拿到 KVE 编号与架构维度 |
| ② 官方门户抓取(联网区跑) | 备选 | 需逆向内部接口, 随时可能变; 需评估合规与反爬。产出离线包摆渡进内网, 与现有架构一致 |
| ③ openEuler 代理匹配 | 过渡 | 立即可用, 但结果**必须标注推断来源**, 不能当结论用 |

**推荐组合: ③ 先落地(不阻塞 v2.2.0) + ① 并行推进(走采购/服务渠道)**。
拿到麒麟正式数据后新增 `KylinSource` 实现 —— `VulnSource` 协议天然支持多源,
这是已内建的能力, 不需要改上层。

#### 过渡期的展示口径(必须执行)

麒麟相关结果一律标注:

> 「基于 openEuler 同源数据推断; 麒麟的补丁回合与组件范围与上游存在差异,
> **最终以麒麟官方安全公告为准**」

绝不能把推断结果直接呈现为"确认漏洞"或"确认无漏洞"。

#### KVE 编号

与 CNNVD 同法处理: 做成编号映射层(详见第四节), 在展示与导出时补上 KVE 编号,
满足国产化合规通报要求。若麒麟正式数据源含 KVE, 直接从该源取则更准确。

### 3.5 三种语义必须分开

- 生态未纳入覆盖范围(如 K8s) → 「未纳入本地漏洞库」
- 本地库未导入 / 组件未填 distro 无法判定 → 「无法判定, 待补充」
- 已覆盖且在范围内但无命中 → 「未发现已知漏洞」

**绝不能把前两种显示成第三种**, 那会给人虚假的安全感。

---

## 四、CNNVD 对齐(已确认要做)

定位: **叠加层, 不是主数据源。**

CNNVD 是 CVE 级的、不带包坐标, 硬拿来做组件匹配需要 CPE 映射, 精度很差。
正确用法: 从 CNNVD 月度 XML(约 5-8 MB/月, 全年约 48 MB)抽 `CVE-ID → CNNVD-ID + 中文危害等级`,
建成一张小映射表, 只在**展示与导出**时补合规字段。

实现:
1. `scripts/build_cnnvd_map.py`: 解析月度 XML → `cnnvd_map(cve_id, cnnvd_id, cn_severity, title_zh)`;
2. 与漏洞库**同一构建流程产出**, 一起进镜像;
3. `VulnerabilityRecord` 增列 `cnnvd_id` / `cn_severity`(可空);
4. Word/Excel 导出时补上 CNNVD 编号与中文等级。

> 若行内要求 CNVD 编号, 同法再加一列即可, 成本很低。

---

## 五、CI 打包进 Docker 镜像(你提的方案, 建议做成双轨)

### 5.1 结论: 可以做, 但不要做成唯一通道

**纯镜像方案的问题**: 更新漏洞库要重建镜像 + 重走内网镜像入库流程(扫描、审批、多环境同步)。
遇到 log4j2 那种紧急漏洞, 这个链路太慢。

**推荐: 内置基线 + 运行时可覆盖**

```dockerfile
# 阶段三: 漏洞库(独立可替换的一层)
FROM ghcr.io/timmycheng/secreq-vulndb:20260830 AS vulndb

FROM python:3.12-slim
...
COPY --from=vulndb /vulndb.sqlite /app/data/vulndb.sqlite
ENV SECREQ_VULNDB_PATH=/app/data/vulndb.sqlite
```

```yaml
# docker-compose.yml
volumes:
  - /mnt/vulndb/vulndb-20260915.sqlite:/app/data/vulndb.sqlite:ro
```

| 场景 | 做法 |
| ---- | ---- |
| 首次部署 | 直接 `docker run`, 用内置基线, 开箱即用 |
| 日常更新 | 只替换挂载的 sqlite 文件(走**文件摆渡**, 比镜像入库轻) |
| 紧急漏洞 | 换文件 + 重启容器, 分钟级 |

### 5.2 CI 设计

建议**漏洞库单独成一个 OCI artifact**, 与主镜像解耦:

```yaml
# .github/workflows/vulndb.yml  (每周定时 + 手动触发)
- run: |
    python scripts/build_vuln_db.py \
      --ecosystems npm,Maven,PyPI,Go,NuGet,crates.io,Bitnami,Alpine,Red\ Hat,openEuler \
      --slim --compress --out vulndb.sqlite
    python scripts/build_cnnvd_map.py --out cnnvd_map.sqlite
- run: oras push ghcr.io/timmycheng/secreq-vulndb:$(date +%Y%m%d) vulndb.sqlite cnnvd_map.sqlite
```

```yaml
# .github/workflows/release.yml  增加一步
- run: oras pull ghcr.io/timmycheng/secreq-vulndb:${VULNDB_TAG}
# Dockerfile: COPY vulndb.sqlite /app/data/
```

好处: 漏洞库可独立更新、独立版本化、被多个系统复用, 主镜像构建不必每次重下 336 MB。

> **⚠️ 硬约束: 漏洞库绝不随 Release 附件分发。**
> 仓库为 private, Release 附件按版本累积(2026-08-30 实测已 205 MB / 3 个版本,
> 每版 +70 MB; 官方建议仓库 <1 GB)。若把 ~200 MB 漏洞库塞进应用镜像,
> 每版附件将变成 +150~200 MB, 十个版本即逼近软警告线。
> **漏洞库只走 GHCR OCI artifact** —— 容器镜像存储目前免费, 且可独立更新与复用。
> 详见 `MASTER_PLAN.md` 5.5「产物体积与存储治理」。

### 5.3 镜像体积影响

按配置 B: 索引库约 200 MB → **镜像增加约 200 MB**。

- **镜像本身**: GHCR 容器镜像存储当前免费, 短期不构成压力。
- **但要害在 Release 附件**: 主镜像变大会让每版附带的 `secreq-image-v*.tar.gz`
  从 70 MB 涨到 150~200 MB, 长期累积才是问题。

因此**应用镜像内置的是精简基线库, 不是完整库** —— 完整库走上面的 OCI artifact
+ 运行时挂载覆盖。这样主镜像保持精简, Release 附件也维持在 70 MB 量级。

若确实需要完整库进镜像(如某些环境不便挂载), 走配置 C 或加 Ubuntu 会到 300 MB 以上,
建议届时改为**完整库独立 artifact + 挂载**, 而不是塞进主镜像。

### 5.4 构建耗时

下载 336 MB + 解析建索引, CI 里预计 10-20 分钟。
放在**独立的定时 workflow** 里, 不要拖慢每次 release。

---

## 六、仍然要修的隐性缺陷: `pkg:generic`

**位置**: `services/sbom.py:34-41`

```python
purl = f"pkg:generic/{safe_name}@{component.version}"
```

OSV **不支持 `generic` 生态**, 这类 purl 永远查不到任何漏洞。
`ComponentIn.purl` 是可选字段、Step7 未强制引导 → **实际使用中绝大多数组件都落进 generic,
漏洞联动形同虚设。**

必须一并修:
1. Step7 增加「生态」+「分发渠道」两个下拉, 选定后自动生成规范 purl;
2. `COMMON_COMPONENTS` 为每条补上生态标注, 点选常用组件时自动带上;
3. 未指定生态时走跨生态模糊匹配, 结果标注「待确认」。

---

## 七、实施顺序

| 步骤 | 内容 | 依赖 | 可并行 |
| ---- | ---- | ---- | ------ |
| 1 | 抽 `VulnSource` 协议, 包装现有 `OsvClient` 为 Online 实现 | — | 是 |
| 2 | **核查 SCA 可对接性**(2.3 清单) | — | 是, 建议最先做 |
| 3 | `scripts/build_vuln_db.py` + 配置 B 实测体积 | 1 | |
| 4 | `services/vuln_match/` 版本归一化器(Bitnami/Alpine/**openEuler**) | 1 | 与 3 并行 |
| 5 | `services/vulndb.py` Local 实现 + 生态与 distro 映射 | 3, 4 | |
| 6 | `sync_vulnerabilities` 接入配置切换 + 缓存语义改为库版本 | 5 | |
| 7 | 修 `pkg:generic` + Step7 生态/distro 下拉 | — | 是, 可立即做 |
| 8 | CI 构建漏洞库 artifact + 打进镜像 + 挂载覆盖 | 5 | |
| 9 | CNNVD 映射层 + 导出补字段 | 5 | |
| 10 | 管理端漏洞库导入页 + SHA256 校验 + 审计 | 5 | |

**步骤 1、2、7 无依赖, 可以立即开始。** 步骤 2 的结论会决定步骤 5 是否还要再写一个 `ScaPlatformSource`。

---

## 八、需要你确认

~~1. 目标发行版 / 2. 是否用 Bitnami / Alpine 容器镜像~~ → **已确认**: 银河麒麟(Kylin)+
Bitnami+Alpine。选型见 1.1, 麒麟缺口见 3.6。

1. **麒麟的具体版本?**(V10 SP1/SP2/SP3 / V11)不同 SP 基于的 openEuler 版本不同。
2. **能否拿到麒麟正式数据源?** 见 3.6 路径 ①(向麒麟/集成商索取)。**建议尽快启动**,
   走采购或服务渠道周期可能较长。这决定 3.6 的缺口能否闭合。
3. **麒麟的部署形态**: 裸机 / 虚机 / 容器? 若中间件全在 Bitnami 容器里,
   麒麟层面主要是 OS 基础包与内核, 缺口影响可控。
4. **Docker 基础镜像是什么?** 若 Alpine 则与 ② 层重合; 若麒麟基础镜像需另处理。
5. **K8s 缺口如何处理?** 标注未覆盖, 还是单独找源?
6. **CNNVD / KVE 只需编号, 还是也要中文危害等级与中文标题?**
7. **SCA 核查结果** —— 建议尽快拿到, 它会改变步骤 5 之后的工作内容。
8. **更新频率**: 漏洞库多久更新一次? 决定 CI 定时周期与摆渡流程的常态化安排。
