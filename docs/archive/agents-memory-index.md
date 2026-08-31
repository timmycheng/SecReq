# SecReq 项目长期记忆

## 项目是什么

安全需求管理平台（银行场景）。FastAPI + SQLAlchemy 2.0 + SQLite/PostgreSQL 后端，
React 19 + TS + AntD 前端，8 步向导采集项目信息，规则引擎按知识库
（61 条模板）自动生成安全需求清单，联动组件 SBOM 漏洞查询与 JR/T 0197 五级数据分级。

## 硬约束（任何改动都不得违反）

- **内网部署，无互联网出口。** 任何新增功能不得硬编码互联网地址；
  确需外部调用的必须可配置 + 有降级路径。
- **角色只有两个**：`developer`（仅可见自己创建的项目）/ `security`（全量 + 系统管理）。
  越权一律 404，不泄露资源存在性。
- 知识库模板必须带 `regulatory_ref`（`rules/loader.py` 强校验），**不允许编造条款号**。
- 共享枚举单一源放 `shared/constants.py`，经 `/api/meta/constants` 供前端；
  路由层与前端不得重复定义。
- 种子初始密码走 `SECREQ_SEED_PASSWORD`，源码内不得出现固定口令。
- 迁移脚本一律支持 `--dry-run` 且幂等，实现放 `services/` 由脚本与 lifespan 共用
  （沿用 `classification_migration.py` 的既有约定）。

## 不要动的地方（写得好的，别改坏）

- `rules/engine.py:36` 占位符白名单渲染 —— 只匹配 `{{word}}` + 查字典字面插入，
  不走 str.format/Jinja，天然免疫 SSTI。
- `services/osv.py:201` 多坐标过滤（精确 purl → 全限定名 → 裸名 → 兜底），
  挡 guicedee/pax-logging 这类派生包污染。
- `routers/common.py` 数据权限统一收口，没散落在各路由。
- `services/kb_admin.py` YAML 写回的备份 + 全量校验 + 失败回滚。

## 已知缺陷（未修，方案已就绪）

- `rules/engine.py:171` 全删全插 → 重新生成清空所有确认记录（P0-1）
- `services/step_store.py` 整表替换 → 主键变化导致需求溯源断链（P0-2）
- `services/sbom.py:34` 生成 `pkg:generic/...`，OSV 不支持 generic 生态，
  不填 purl 则漏洞查询必然空转
- `rules/engine.py:476` docstring 声明 `saas_finance` 但未实现，命中即抛异常（定时炸弹）
- 无 alembic；SQLite 无 WAL/busy_timeout；依赖无锁版本
- 容器无 TZ 设置，10 处 `datetime.now()` 导致显示时间差 8 小时

## 文档索引

| 文档 | 定位 |
| ---- | ---- |
| `MASTER_PLAN.md` | **总纲**：版本路线图、SCA 预留设计、跨版本约束、待确认项 |
| `OPTIMIZATION_REVIEW.md` | 问题清单与评级，各条目事实依据 |
| `IMPLEMENTATION_PLAN.md` | 阶段 0-4 文件级改动清单（细节仍可参照） |
| `OFFLINE_VULN_DB_PLAN.md` | 离线漏洞库设计 v2，含 OSV 数据源实测数据 |

## 版本路线图

| 版本 | 主题 | 风险 |
| ---- | ---- | ---- |
| v2.2.0 | 内网基建与快赢补丁 | 低 |
| v2.3.0 | 离线漏洞库 + SCA 预留（**上线阻塞项**） | 中 |
| v2.4.0 | 数据一致性 uid 迁移 | 高 |
| v2.5.0 | 工程质量与 CI | 低 |
| v2.6.0+ | SCA 对接 | 中 |

## 离线漏洞库关键数据（2026-08-30 实测，可直接复用）

生态包体积（MB，压缩）：npm 211.4 / Ubuntu 623.0 / GIT 176.7 / Debian 72.2 /
MinimOS 64.4 / Linux 52.9 / SUSE 44.5 / PyPI 32.4 / Chainguard 28.7 / Red Hat 25.3 /
openSUSE 20.6 / Wolfi 18.4 / openEuler 17.4 / Bitnami 8.8 / Go 10.9 / Maven 9.8 /
Root 13.5 / Azure Linux 13.6 / AlmaLinux 5.9 / Rocky 4.5 / Alpine 3.9 / NuGet 2.4 / crates.io 3.3

- **Bitnami**（容器中间件）与 **Alpine**（C 库与基础工具）高度互补，合计 12.7MB，
  覆盖 mysql/redis/nginx/kafka/rabbitmq/elasticsearch/tomcat/postgresql/mongodb/
  openssl/imagemagick/ffmpeg/zlib/curl。**K8s 两者都无覆盖。**
- Bitnami 用标准 semver（现有 `_version_key` 零适配）；Alpine 用 `1.0.2h-r0`
  需剥离 `-rN`，但记录带完整 versions 枚举，走枚举匹配更可靠。
- **不导 Ubuntu**（623MB，性价比极低）与 **GIT**（176.7MB，commit 级对版本匹配无用）。
- zlib 存 raw JSON 可压到 12-31%，收益远大于字段裁剪。

## 环境相关（本机/沙箱）

- `pytest tests` 全量跑时 `test_sbom.py::test_write_cyclonedx_file_keeps_utf8_chinese`
  会失败，原因是沙箱 `SAFE_DELETE_BULK_CONFIRM_REQUIRED` 阻止 pytest 清理临时目录。
  **单跑该用例通过，不是代码缺陷**，不要去"修"它。
- 前端 `npm run build` 会因 vite 清空 `dist/` 被 safe-delete 拦截。
  绕法：`npx tsc -b && npx vite build --emptyOutDir false`。
- SQLite 删空表后 `max(rowid)` 归零，新插入会**复用原 ID**；
  测主键漂移必须用"删除"而非"追加"来构造场景。

## 工程实践约定

- **红灯护栏用 `xfail(strict=True)`** 而非留失败测试：修复前 XFAIL 不阻塞 CI，
  修复后 XPASS 失败强制提醒清理标记。
- 兜底 `except Exception` 一律走 `services/errors.py` 的 `server_error()`：
  服务端记栈 + 客户端只收「通用文案 + trace_id」。业务校验错误（模板不存在、
  参数越界）不在此列，仍回显具体原因。
- 改了行为就要补测试证明它生效，不能只看既有测试没挂。

## 私有仓库产物限额（实测，2026-08-30）

| 项 | 用量 | 限额 |
|---|---|---|
| Release 附件 | 205.1 MB（3 个版本） | 单文件 ≤2GB，建议仓库 <1GB |
| Actions 缓存 | 773.2 MB / 85 个 | 10 GB/仓库，7 天未访问淘汰 |
| Actions 构件 | 0.4 MB | 与 Packages 共享 |
| GHCR 镜像 | **目前免费**（容器注册表免费期） | — |

- **GHCR 容器镜像存储当前不计费**，镜像体积短期不是压力。
- **长期风险是 Release 附件累积**（每版 +70MB）。**漏洞库绝不能随 Release 分发**，
  必须走独立 GHCR OCI artifact —— 这正是 v2.2.0 解耦设计的价值所在。
- Actions 缓存偏大是 `release.yml` 的 `cache-to: type=gha,mode=max` 存的中间层太多。

## 目标部署环境（已确认）

- 宿主 OS：**银河麒麟**（信创）｜中间件：**Bitnami 容器镜像**｜基础库：**Alpine 容器镜像**
- **麒麟 V10 血统是 openEuler，不是 CentOS/RHEL**（麒麟官方发布说明：基于 openEuler 22.03 LTS；
  包管理 RPM/dnf；glibc 2.34+）。代理匹配用 **openEuler**（17.4MB），RHEL 系仅在其他环境需要时才导。

### 麒麟覆盖缺口（v2.2.0 无法闭合，必须如实告知）

**麒麟不在 OSV 的 39 个生态中**。openEuler 代理的四类失真：
麒麟独立 backport → 误报；麒麟自有组件（kysec-daemon / ukui-session-manager 等 KVE 编号）→ 完全漏报；
架构维度（aarch64/loongarch64/mips64el/sw_64）→ OSV 无此信息；KVE 编号 → 需单独映射。

麒麟官方 CVE 门户 `support.kylinos.cn/#/security/cve` 数据完备但**无公开 API**（SPA，已实测探测 404）。
路径：① 向麒麟索取正式数据源（首选，采购/服务渠道）② 门户抓取（联网区，备选）
③ openEuler 代理（过渡，**结果必须标注"推断，以麒麟官方公告为准"**）。

## 工作习惯

- 出方案前先实测，不拍脑袋给数字。
- 方案与实施分离：先出文档等用户确认，再动代码。
- 发现问题时区分「查不到」的三种语义（未覆盖 / 无法判定 / 确实没有），
  绝不能统一显示成"无"，那会给人虚假安全感。
