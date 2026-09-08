# v2.2.1 修复方案

> **管理方式**: 本方案 25 项已拆解为 issue 跟踪 —— P0-1~P2-10 共 24 项挂 milestone [v2.2.1](https://github.com/timmycheng/SecReq/milestone/1)(#14~#37), P2-11 已随本方案落地不再开 issue, 「既有问题备忘」5 项为无 milestone 的 backlog issue(#38~#42)。修复按 issue 建分支 `fix|chore/<issue号>-<slug>`, **完成状态以 issue/milestone 为准**, 本文保留为审查存档与改法细则。
>
> 来源: 两轮代码审查合并 —— v2.1.3 审查(原 `fix-plan-v2.2.1.md`)与 v2.2.0 (commit `984dcab` "离线漏洞库与 SCA 预留")审查(原 `fix-plan-v2.2.0-review.md`)。 合并前两份方案的内容已全部吸收进本文, 原文件删除; 旧方案各条目已逐一在 v2.2.0 当前 main 上复核, 行号为当前代码位置。
>
> 审查结论: 两版方向与工程习惯都在线(v2.2.0 的防虚假安全感设计与数据源接缝 尤其出色), 测试 186 passed + 5 xfailed 真实通过; 但 v2.1.3 遗留三处 "功能意图未闭环", v2.2.0 引入一处存量部署升级即挂的阻断缺陷, 均需本版闭合。

## 问题总览

| 编号 | 优先级 | 问题 | 位置 | 来源 |
|------|--------|------|------|------|
| P0-1 | 高(阻断) | 存量库升级缺列迁移, SBOM 查询直接 `no such column` | `services/classification_migration.py` | v2.2.0 |
| P0-2 | 高 | Excel 漏洞清单「组件」列恒为"—"(取自不存在的属性) | `services/tracking_export.py` | v2.2.0 |
| P0-3 | 高 | 引擎实例化阶段容错缺失, 占位符缺值仍中断整轮生成 | `rules/engine.py` | v2.1.3 |
| P0-4 | 高 | `RuleEngine.skipped` 写了无人读, 前端对"模板被跳过"无感知 | pipeline/schemas/generate/前端 | v2.1.3 |
| P0-5 | 高 | 内网 Nginx 拓扑下审计 IP 记录的是代理容器 IP | compose 配置 | v2.1.3 |
| P1-1 | 中 | retention.yml 清理窗口取反: 删最新、留最旧 | `.github/workflows/retention.yml:96` | v2.2.0 |
| P1-2 | 中 | retention.yml 定时触发恒 dry-run, 周清理永不执行 | `retention.yml:39,90` | v2.2.0 |
| P1-3 | 中 | 预发布版本排在同号稳定版之后, 与注释相反, 造成漏报 | `services/vuln_match/normalizers.py:26-38` + `services/osv.py:203-210` | v2.2.0 |
| P1-4 | 中 | sidecar 缺失时校验接口仍报"校验和一致" | `routers/admin.py:374` + `VulnDbTab.tsx` | v2.2.0 |
| P1-5 | 中 | Nginx `http2 on;` 需要 ≥ 1.25.1, 内网常见 1.18~1.24 起不来 | `deploy/nginx/secreq.conf:26` | v2.1.3 |
| P1-6 | 中 | 审计 IP 字段不一致(project_create / project_delete 缺失) | `routers/projects.py:47,92` | v2.1.3 |
| P1-7 | 低 | 内网 compose 暴露 8000, 可绕过 TLS | `docker-compose.intranet.yml:18-19` | v2.1.3 |
| P1-8 | 低 | WAL 在 NAS/NFS 上不适用, 未提示 | 部署文档 | v2.1.3 |
| P1-9 | 低 | steps.py 10 处 `require_write_roles` 声明冗余, 误导读者 | `routers/steps.py` | v2.1.3 |
| P2-1 | 低 | versions-only 的 OSV 记录(无 ranges)永不命中, 结构性漏报 | `services/vulndb.py:174-218` | v2.2.0 |
| P2-2 | 低 | 跨生态模糊匹配 purl 用错生态, 修复版本可能被同公告其他包污染 | `services/vulndb.py:257` + `services/osv.py:243-252` | v2.2.0 |
| P2-3 | 低 | `_REGISTRY` 死代码, ScaPlatformSource 注释与事实不符 | `services/vuln_source.py:125-129` | v2.2.0 |
| P2-4 | 低 | 管理端「未导入生态」清单混入 `other`, 并配错误指引 | `routers/admin.py:301-304` | v2.2.0 |
| P2-5 | 低 | `undetermined` 语义文案与实现不符(实现里只表示"未填版本号") | `shared/constants.py:330-341` 等 | v2.2.0 |
| P2-6 | 低 | VulnDb 查询连接不显式关闭(`with conn` 只管事务) | `services/vulndb.py:59-136` | v2.2.0 |
| P2-7 | 低 | vulndb.yml tag 注入面 / 无并发保护 / secreq-vulndb 包无保留策略 | `.github/workflows/vulndb.yml` | v2.2.0 |
| P2-8 | 低 | release.yml oras pull 网络故障时静默打 0 字节占位继续发版 | `.github/workflows/release.yml:59-67` | v2.2.0 |
| P2-9 | 低 | PRAGMA listener 挂全局 `Engine` 类, 作用域过宽 | `models/database.py:17-35` | v2.1.3 |
| P2-10 | 低 | AdminPage 的 Alert 嵌在 Paragraph 内 | `frontend/src/ui/AdminPage.tsx` | v2.1.3 |
| P2-11 | 低 | CHANGELOG 段内硬换行在 GitHub Release 页被渲染成断行, 中文句子被切碎 | `CHANGELOG.md`(正文风格) | 用户反馈 |

---

## P0-1 存量库升级补列登记(services/classification_migration.py)

### 现状(已实证)

v2.2.0 给 `sbom_components` 新增 5 列、`vulnerability_records` 新增 4 列(`models/sbom.py:29-45,73-84`), 但:

- `models/database.py:52` 的 `init_db` 只做 `create_all`, **不改已有表**;
- 项目自带的启动补列机制 `ensure_schema_upgrade` (`services/classification_migration.py:54`, `main.py:51` 启动时调用)的`_NEW_COLUMNS` 注册表(:19)**没有登记这两张表**。

后果: 任何带 v2.1.x 数据的部署升级后, ORM SELECT 含新列, 第一个触及 SBOM组件的请求即抛 `OperationalError: no such column`。全新部署不受影响, 但内网既有部署(恰是本版目标场景)升级即挂。已用模拟 v2.1.3 老库复现。

### 改法

`_NEW_COLUMNS` 追加两表, DDL 必须与模型列定义逐一对应(`source` 为 `Mapped[str]` 非 Optional, 是 NOT NULL, ALTER 需带 DEFAULT):

```python
"sbom_components": [
    ("ecosystem", "VARCHAR(20)"),
    ("distro", "VARCHAR(20)"),
    ("osv_query_fingerprint", "VARCHAR(100)"),
    ("vuln_status", "VARCHAR(20)"),
    ("vuln_status_note", "VARCHAR(300)"),
],
"vulnerabilities": [  # 原文误写 vulnerability_records; 模型实际表名见 models/sbom.py __tablename__
    ("source", "VARCHAR(20) NOT NULL DEFAULT 'osv_local'"),
    ("external_ref", "VARCHAR(200)"),
    ("cnnvd_id", "VARCHAR(32)"),
    ("cn_severity", "VARCHAR(20)"),
],
```

`ensure_schema_upgrade` 本身幂等(先查已有列再 ALTER), 无需其他改动; `scripts/migrate_classification.py` 共用该函数, 自动受益。

### 测试

新增 `tests/test_schema_upgrade.py`: 按 v2.1.3 旧列清单手工 `CREATE TABLE`两张表并插一行老数据 → 跑 `init_db` + `ensure_schema_upgrade` → `session.query(SbomComponent).first()` 与 `VulnerabilityRecord` 写入均正常,且 `source` 默认值为 `osv_local`; 重复执行 `ensure_schema_upgrade` 不再 ALTER (幂等)。先写失败用例(复现 `no such column`)再修, 作回归护栏。

---

## P0-2 Excel 漏洞清单「组件」列(services/tracking_export.py)

### 现状(已实证)

`_append_vuln_sheet`(:160-163) 读 `component_name` / `component_version`,但唯一生产调用链 `routers/generate.py:283` → `services/pipeline.py:90` `_load_vulnerabilities` 传回的是 ORM `VulnerabilityRecord` —— 该模型**没有**这两个属性(`models/sbom.py:63-84`), `getattr` 落到默认空串, 「组件」列输出恒为 `—`。合规通报表缺组件栏, 击中该功能自身目的。既有测试 `tests/test_tracking_export.py:60` 只导跟踪表不带漏洞清单, 没拦住。

### 改法

`_append_vuln_sheet` 内取组件名/版本改为"投影属性优先, ORM 关系兜底":

```python
def _comp_of(v):
    comp = getattr(v, "component", None)          # ORM relationship
    name = getattr(v, "component_name", None) or (getattr(comp, "name", "") or "")
    version = getattr(v, "component_version", None) or (getattr(comp, "version", "") or "")
    return name, version
```

- 行内拼接与排序 key 都改走 `_comp_of`;
- `services/pipeline.py` `_load_vulnerabilities` 的查询加`.options(joinedload(VulnerabilityRecord.component))`, 导出场景避免逐条 lazy load;
- 测试用的 SimpleNamespace 形态(带 `component_name`)继续兼容, 不用改。

### 测试

`tests/test_tracking_export.py` 追加: 用 ORM 形态记录(`VulnerabilityRecord(...)` + 挂 `component`)导出后读「漏洞清单」工作表E 列, 断言组件值为 `name@version` 而非 `—`。

---

## P0-3 引擎实例化阶段补容错(rules/engine.py)

### 现状

`generate()` 里 try/except 只包住了 handler 匹配循环(engine.py:107-116),占位符渲染发生在其后的实例化循环(engine.py:133-155), 不在保护范围内。`render()` 在占位符缺值时抛 `RuleEngineError`(engine.py:52), 该异常直接冲出`generate()`, 被生成路由的兜底分支接住变成整轮 500。

即: 模板 trigger 匹配成功、但 `{{placeholder}}` 无可用取值时, 全项目生成仍然失败——恰是容错要防的场景。except 分支注释写着"未知 rule_key / 占位符缺失等:跳过该模板"(engine.py:114-115), 在修复前属于 overclaim。

### 改法

把实例化循环里每个模板的构造包进 try/except, 失败走既有的 `_skip` 通道:

```python
for tpl, match in collected:
    merged = {**base_placeholders, **match.placeholders}
    try:
        req = SecurityRequirement(
            ...,
            title=render(tpl.title, merged, tpl.id),
            ...
        )
    except RuleEngineError as exc:
        self._skip(tpl, str(exc))
        continue
    seq = counters.get(tpl.id, 0) + 1
    counters[tpl.id] = seq
    req.req_id = tpl.id if seq == 1 else f"{tpl.id}-{seq:02d}"
    requirements.append(req)
```

两个细节:

- **序号 `counters` 在构造成功后才递增**, 失败的实例不消耗 `-NN` 序号,保证 req_id 分配仍是确定性的(现网代码 seq 先加后构造, 需一并调整);
- 同步修正 except 分支注释——修复后注释描述才成为事实。

### 测试

`tests/test_engine_fault_tolerance.py`(现有 5 条)追加: 构造一条 trigger 能匹配、但 title 含 `{{no_such_key}}` 的模板注入引擎, 断言:

- `skipped` 记 1 条且 reason 含"没有可用的取值";
- 其余模板产出数量与干净基线一致。

加上这条, 容错才覆盖 docstring 承诺的全部三种坏配置(未知 trigger_type /未知 rule_key / 占位符缺值)。

---

## P0-4 把 `skipped` 接到前端(4 个文件, 各 1-3 行)

### 现状

`RuleEngine.skipped` 只有引擎自身写入和测试读取: `services/pipeline.py` 调用`generate_and_save` 后不回传, `GenerateSummary`(schemas/requirement.py:70)没有对应字段。模板配置有误被跳过时, 前端只看到"生成成功", 需求条数悄悄变少——对合规工具来说, 覆盖缺口不可见比报错更危险。唯一痕迹是服务端 ERROR 日志。

### 改法

1. `services/pipeline.py:33` — `PipelineResult` 加字段`skipped_templates: list = field(default_factory=list)`; 在 `run_full_pipeline`第③步之后补 `result.skipped_templates = engine.skipped`(engine 是局部变量,正好取得到)。
2. `schemas/requirement.py:70` — `GenerateSummary` 加`skipped_templates: list[dict] = []`(带默认值, 对老客户端向后兼容)。
3. `routers/generate.py` — 组装 summary 时透传 `skipped_templates=...`。
4. 前端:
   - `frontend/src/types.ts` 的 `GenerateSummary` 加同名字段;
   - `frontend/src/ui/steps/ConfirmStep.tsx:49` 成功提示后追加: `summary.skipped_templates.length > 0` 时`message.warning("有 N 条知识库模板配置有误被跳过, 请联系安全管理员检查知识库(详见服务端日志)")`。前端不需展示具体原因, 知道"少了东西"即可; 具体原因引擎已记 ERROR 日志。

### 测试

API 层加一条用例: 通过 `run_full_pipeline(engine=注入坏模板的引擎)` 或等效方式,断言响应里出现 `skipped_templates`。

---

## P0-5 审计 IP 修复(配置为主, 零代码)

### 现状

Dockerfile 的 CMD 是裸 `uvicorn ... --host 0.0.0.0`, 没有 `--forwarded-allow-ips`。uvicorn 默认只信任 `127.0.0.1` 的 forwarded 头, 而 Nginx 容器从 docker 网桥IP(172.x)连入, `X-Forwarded-For` / `X-Real-IP` 被忽略——审计记录里的 export / project_delete 来源 IP 恒为 Nginx 容器 IP, 在文档推荐的内网 HTTPS 拓扑下失真。

### 改法

uvicorn 自动读环境变量 `FORWARDED_ALLOW_IPS`, 不用改 CMD:

1. `docker-compose.intranet.yml` 的 environment 加:

   ```yaml
         # 审计 IP 取真实客户端: 信任来自 compose 网段的 X-Forwarded-For(由 Nginx 注入)
         FORWARDED_ALLOW_IPS: 172.16.0.0/12
   ```

2. `deploy/nginx/secreq.conf` 头部注释补一句: "后端需设置 FORWARDED_ALLOW_IPS信任本代理, 否则审计日志的 IP 记录的是本容器地址"。

### 验证

起 compose + nginx 后执行一次导出, `/api/admin/audit-logs` 里 ip 应为客户端地址而非 172.x。

---

## P1-1 retention.yml 清理窗口取反

### 现状

`retention.yml:96`: `gh api ... --jq '.[].id' | head -n -"${KEEP}"`。GitHub release 列表按新→旧返回, `head -n -3` 表示"去掉**最后** 3 行"即去掉最旧 3 个 —— 实际删除的是**最新** Release 的附件、保留最旧 3 个,与步骤注释"跳过最近 KEEP 个"相反。`release.yml:150` 的 `tail -n +4` 才正确。当前仅靠 dry_run 默认 true 兜底, 一旦手动传 `dry_run=false` 即误删新附件。

### 改法

```yaml
ids=$(gh api --paginate "repos/${{ github.repository }}/releases?per_page=100" \
        --jq '.[].id' | tail -n +$((KEEP + 1)))
```

(列表新→旧, 跳过前 KEEP 个 = 从第 KEEP+1 行起。)中期应把 release.yml:141-159与 retention.yml 的重复清理逻辑收敛到 retention.yml 一处, 避免再分叉。

### 验证

fork 下手动 dispatch `dry_run=true` 跑一次, 检查"待删除"列表是最旧的而非最新的。

---

## P1-2 retention.yml 定时触发恒 dry-run

### 现状

两处 `DRY_RUN: ${{ inputs.dry_run || 'true' }}`(:39, :90): schedule 触发时`inputs` 恒为空, 表达式恒得 `'true'` —— 每周日 cron 必然 dry-run,自动清理从未生效。保守默认只对手动 dispatch 有意义。

### 改法

定时即真实执行, 手动默认 dry-run:

```yaml
DRY_RUN: ${{ github.event_name == 'schedule' && 'false' || (inputs.dry_run || 'true') }}
```

两个 job 同步修改。若担心首次自动删除风险, 可先合入 P1-1 并观察一周 dry-run输出再切换, 但两个改动应同批上线。

---

## P1-3 预发布版本排序与注释相反(漏报方向)

### 现状(已实证)

两处实现把预发布标记位设为 1(排在后), 注释却说"排在同号稳定版之前":

- `services/vuln_match/normalizers.py:26-38` `numeric_key` → `(nums, prerelease, letters)`, prerelease=1;
- `services/osv.py:203-210` `_version_key` → `nums + (prerelease,)`, 同样 =1。

实测 `version_key("npm", "2.15.0-rc1") >= version_key("npm", "2.15.0")` 为 True。后果: 窗口 `[2.13.0, 2.15.0)` 内的 `2.15.0-rc1` 被判"≥ fixed, 已修复"→ **漏报**; `_pick_fix_version` 的窗口归属判断同受影响。`osv._version_key` 为历史遗留, v2.2.0 的 `vuln_match` 照抄了实现与错误注释; 测试(`test_vulndb.py:154` 仅测 `1.0.2g-r0 < 1.0.2h-r0`)恰好未覆盖。

### 改法

两处一致改为"预发布排前":

```python
# normalizers.numeric_key
prerelease = 0 if _PRERELEASE_RE.search(text) else 1
# osv._version_key
prerelease = 0 if re.search(r"(?i)(beta|alpha|rc|-)", text) else 1
```

- introduced 缺省 `"0"` 无预发布标记 → flag=1, 仍小于一切真实版本, 不受影响;
- 两条调用链(normalizers 走 `vulndb._windows_including`, osv 走`_pick_fix_version`)各自内部自洽, 无交叉比较, 不存在跨键比较问题;
- 同步修正两处 docstring/注释(`normalizers.py:23`, `osv.py:204`)。

### 测试

`tests/test_vulndb.py` 追加:

1. `version_key("npm", "2.15.0-rc1") < version_key("npm", "2.15.0")`;
2. 端到端: 构造窗口 `[{"introduced": "2.13.0"}, {"fixed": "2.15.0"}]` 的 npm 记录,组件版本 `2.15.0-rc1` → 断言 `hit` 且 fix_version=2.15.0(修复前该用例失败,正是漏报形态的回归护栏)。

---

## P1-4 sidecar 缺失时校验接口改三态

### 现状

`routers/admin.py:374`: `ok = expected is None or digest == expected` ——校验文件(`.sha256` sidecar)缺失时 `match=true`, 前端`VulnDbTab.tsx:119-121` 显示"校验和一致, 文件完整", 与同页概况区"构建时未记录"自相矛盾。摆渡完整性核验可能空转却报成功。

### 改法

`match` 改三态: 一致 true / 不一致 false / 无可比对 null。

- `routers/admin.py`: `ok = (digest == expected) if expected is not None else None`,响应与审计 detail 原样携带;
- `frontend/src/types.ts` `VulnDbVerifyResult.match: boolean | null`;
- `VulnDbTab.tsx:40` 改 `if (res.match === true) ...` 并补 null 分支(`message.info("构建时未记录校验和, 无法核验完整性, 请核对文件来源")`); :119-121 Alert 同步三态(null → info 色"无校验和可比对")。

### 测试

`tests/test_admin.py` 追加: 无 sidecar 时 `/api/admin/vuln-db/verify` 返回`match=None` 且 `expected=None`; 有 sidecar 且匹配时 `match=true`。

---

## P1 其余小项

| # | 问题 | 改法 |
|---|------|------|
| P1-5 | Nginx `http2 on;` 需 ≥ 1.25.1(`deploy/nginx/secreq.conf:26`) | 改回兼容写法 `listen 443 ssl http2;`(1.18~1.24 可用, 1.25+ 仅告警), 内网交付兼容性优先 |
| P1-6 | 审计 IP 字段不一致: `project_create`/`project_delete` 无 IP(`routers/projects.py:47,92`) | 把 admin.py 已有的 `_client_ip(request)` 提为 `routers/common.py` 公共函数, projects.py 两处埋点补上 IP 参数 |
| P1-7 | 内网 compose 暴露 8000 绕过 TLS(`docker-compose.intranet.yml:18-19`) | `ports` 段加注释: "前置 Nginx 时删除本段, 仅保留代理入口" |
| P1-8 | WAL 不适用网络文件系统 | README 部署节 + compose 卷注释各加一句: "/app/data 若挂载 NAS/NFS, 请移除 WAL PRAGMA 或改用本地卷" |
| P1-9 | steps.py 10 处冗余 `require_write_roles` 声明(仅为取 user 做审计, 角色校验已由 `get_writable_project` 独立承担) | 改为 `Depends(require_login)`, 消除"读者以为是新增授权"的误导 |

---

## P2 次要项(小改动, 同批带上)

| # | 问题 | 改法 |
|---|------|------|
| P2-1 | versions-only OSV 记录(只有 `versions` 枚举、无 `ranges`)在 `_windows_including` 中返回空窗口, 永不命中(`vulndb.py:174-218`, 已实证 `_extract_ranges` 返回 `[]`)。OSV schema 允许该形态, 属结构性漏报 | **先量化再修**: 对真实构建库跑 `SELECT COUNT(*) FROM vulns WHERE raw NOT LIKE '%"ranges"%' AND raw LIKE '%"versions"%'` 确认占比; 修复取保守路线 —— `inside` 为空且 `in_versions(ecosystem, version, enumerated)` 为真时, 返回伪窗口 `[{"introduced": version}]` + 说明文案("该版本出现在公告受影响版本列表中, 记录未提供范围, 请人工核对修复版本"), 沿用现有 hit+note 通道, `_pick_fix_version` 无 fixed 自然返回 None |
| P2-2 | 跨生态模糊匹配时 purl 只按 `ecosystems[0]` 构造一次(`vulndb.py:257`), 其余生态的候选三级匹配全不中 → `_matched_affected_entries`(osv.py:243-252) fallback 到全部 affected 条目, 同公告其他包的窗口混入 `fix_version`(取 max) | ① `OsvLocalSource.query` 循环内逐生态 `_match_purl(q, ecosystem)`; ② `osv.component_query`(:352) 的 `build_purl(comp) or comp.purl` 纯冗余(build_purl 在 purl 非空时原样返回), 删掉 `or comp.purl`, 避免无生态组件把 `name@version` 残次 purl 带进匹配; ③ `_matched_affected_entries` 在 qualified 与 bare 之间加一档 Maven 坐标尾段匹配(`ename.split(":")[-1] == name`), 覆盖用户只填 artifact 名的场景 |
| P2-3 | `vuln_source.py:125-129` `_REGISTRY` 定义后从未被 `_build()` 读取; `ScaPlatformSource` docstring(:109)"已在 _REGISTRY 中注册"与事实不符 | 删除 `_REGISTRY`, docstring 改为"在 `_build()` 中注册一个分支" —— 与"SCA 接入时再实现"的 YAGNI 口径一致 |
| P2-4 | 管理端 `_vulndb_snapshot` 的 `missing_ecosystems`(admin.py:301-304)按全部 `VULN_ECOSYSTEMS` 计算, `other` 永远出现在"未导入"清单并配"重跑构建脚本"指引, 但该生态本就不可导入 | 列表推导追加 `and code != "other"` |
| P2-5 | `undetermined` 文案说"未指定生态/分发渠道"(`constants.py:333,340`, `vuln_source.py:73`, `vulndb.py:12-14`), 实现里缺生态/渠道走跨生态模糊匹配, 只有缺版本号才是 undetermined(`vulndb.py:244-245`) | 四处文案统一改为"无法判定(组件缺少版本号等信息)"口径; 前端标签走后端下发, 改常量即全链生效 |
| P2-6 | `VulnDb` 的 `meta()/candidates()/imported_ecosystems` 用 `with self.connect()`, 该上下文只管事务**不关连接**, 靠 GC 回收(`vulndb.py:59-136`); 同仓 `services/cnnvd.py:62-63` 的 `finally: conn.close()` 是正确范式 | 统一 `with closing(self.connect()) as conn:`(`contextlib.closing`), 或显式 try/finally |
| P2-7 | vulndb.yml: `inputs.tag` 直接内插进 `run` shell(:74-79, 注入面, dispatch 权限可触发); 无 `concurrency`, 定时与手动并发互覆 `latest`; `secreq-vulndb` 包按日期每周净增且无任何保留策略 | ① `tag` 步骤改 env 传递(照同文件 `inputs.ecosystems` 的写法); ② 加 `concurrency: { group: vulndb-build, cancel-in-progress: true }`; ③ retention.yml GHCR job 增加 secreq-vulndb 包清理(保留最近 4 个日期版本 + latest), 与 secreq 包同款逻辑 |
| P2-8 | release.yml:59-67 oras pull 失败(含瞬时网络故障)统一放 0 字节占位继续发版, 仅 warning —— 离线交付镜像可能缺基线库而无人察觉 | pull 失败先重试一次; 仍失败则 `exit 1` 终止发版。若需保留"artifact 缺失可跳过"的口子, 用独立输入显式声明并打醒目告警, 不做静默回退 |
| P2-9 | PRAGMA listener 挂全局 `Engine` 类(`models/database.py:17-35`), 对所有引擎实例生效, 作用域过宽 | 移入 `make_engine()` 内按实例注册(`event.listens_for(engine, "connect")`) |
| P2-10 | AdminPage 的 Alert 嵌在 `<Typography.Paragraph>` 内 | 挪到 Paragraph 外部 |
| P2-11 | CHANGELOG 为终端宽度硬换行书写, release.yml:99-116 的 awk 把对应章节原样抽为 Release 正文, 而 GitHub Release 页把段内换行渲染成真实断行 —— 中文句子在任意词组处被切断(仓库文件视图会合并软换行, 故只有 Release 页明显) | **已随本方案落地**: 全文重排为"一条/一段独占一行"(373→244 行, 去空白内容零变化 + 标题/列表/表格/围栏结构行数不变双重校验), 头部补「排版约定」要求后续条目遵守同一风格; `release.yml` 的 awk 按 `## [x.y.z]` 边界逐行抽取, 长行天然兼容, 无需改动 |

---

## 既有问题备忘(非 v2.2.x 引入, 顺手记录, 不阻塞本版)

| 位置 | 问题 |
|------|------|
| `frontend/src/ui/steps/Step7Components.tsx:238` | ComponentModal key 为 `${editIndex}-${name}`, 连续两次"新增组件"key 相同, Form 不重挂载、残留上次录入值 —— 高频路径 |
| `frontend/src/ui/admin/UsersTab.tsx:47` | `res.password ?? '-'` 在接口返回 null 时把"-"当新密码展示 |
| `frontend/src/ui/AdminPage.tsx:3-4` | 注释"六个 Tab"实际 7 个; "首屏加载两个 Tab"与 antd Tabs 惰性挂载不符 |
| `frontend/src/ui/admin/VulnDbTab.tsx:16-18` | SOURCE_LABELS 前端硬编码, 后端已下发 `name` 字段却弃用, 与"标签统一下发"约定相悖 |
| `frontend/src/ui/steps/Step7Components.tsx:27` | EMPTY.layer 硬编码 `'backend'`, 后端 code 变更时失配 |

---

## 版本与验收

- **定版 v2.2.1**: 两轮审查共 25 项(P0×5 / P1×9 / P2×11)合并为一次补丁发布。全部为缺陷修复 + 加固, 无破坏性 API 变更(`skipped_templates` 与 `match` 三态均为带默认值的放宽式响应变更, 前端同步改), 不等大版本。
- **实施顺序**: 后端缺陷先行 —— P0-1(升级阻断, 最先, 测试先写失败用例) → P0-2 → P0-3 → P0-4 → P1-3 → P1-4 → P0-5 与 P1 小项(多为配置/文案) → P1-1/P1-2(CI, **合并前必须修**, 否则 retention 一旦手动触发即误删) → P2 按表顺序; P2-1 需先跑量化查询再决定是否随本版修。
- **测试目标**: 现有 186 passed + 5 xfailed 基础上新增约 14 条(schema 升级 2-3、漏洞清单导出 1-2、引擎实例化容错 1-2、summary 透传 1、预发布排序 2、sidecar 三态 2、versions-only 与模糊匹配各 1-2、missing_ecosystems 1); 既有 xfail 护栏(strict=True)不动。
- **改动量预估**: 后端约 130 行 + 前端约 40 行 + 配置/workflows 约 50 行 +测试约 250 行; 涉及后端 9 文件、前端 5 文件、配置/workflows 6 文件、新增测试文件 1 个(`tests/test_schema_upgrade.py`)。另有 CHANGELOG.md 全文重排(P2-11, 纯 Markdown 排版, 已随方案落地, 不计入代码行数)。
- **发版前人工验证**: ① 用 v2.1.3 备份库走一遍启动升级, Step7 漏洞查询与管理端「漏洞库」页均正常; ② 导出 xlsx 检查「漏洞清单」组件列有值; ③ 起 compose + nginx 执行一次导出, 审计日志 IP 为客户端地址; ④ fork 手动 dispatch retention(dry_run=true)确认删除列表方向正确。
