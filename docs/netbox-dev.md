# NetBox 联动测试环境

SecReq 的 NetBox 互通(#152 配置管理 / #153 资产导入推送 / #154 系统台账互通)针对真实 NetBox 4.x +
官方 [netbox-custom-objects](https://github.com/netboxlabs/netbox-custom-objects) 插件;单元层用
httpx MockTransport 隔离(tests/test_netbox.py),本环境提供**真实联动**的本地靶场。

- **直跑,不依赖 Docker**:真实 NetBox(pip 包 `netbox==4.7.0`)+ 插件直接运行在 Linux/WSL 上
  (NetBox 官方要求 PostgreSQL + Redis;Windows 原生不受支持)。当前环境对接 NetBox 4.7.0 / 插件 0.6.1。
- Windows 宿主:脚本自动经 `wsl -d Ubuntu -u root` 重入,宿主用 `localhost:8080` 访问
  (WSL2 端口转发;未生效时按提示改用 WSL IP)。服务以 `setsid` 脱离会话,`up` 结束后持续运行。
- 实体目录 `netbox/`(已 gitignore):API 令牌、运行日志、pid,全部本地自持。
- 可版本化文件只有 `scripts/netbox_dev.sh`(拉起)与 `scripts/netbox_smoke.sh`(联动冒烟)——
  换环境(另一台 Windows+WSL 或任意 Linux)只要有这两件,`up` 一条命令复刻同一环境。

## 快速开始

```bash
scripts/netbox_dev.sh up        # 拉起: apt 依赖 → postgres/redis → venv 装包 → 迁移 → 令牌 → 样例数据 → runserver
scripts/netbox_dev.sh info      # 查看地址/令牌/接入配置
scripts/netbox_dev.sh down      # 停止 runserver 与 postgres/redis(数据保留)
```

`up` 幂等,自动完成:

- apt 安装 python3-venv/postgresql/redis-server 及构建依赖;启动服务并创建专属库
  `netbox_secreq`(不复用宿主机可能已有的 `netbox` 库);
- venv(默认 `~/.secreq-netbox`,Linux 文件系统)安装 `netbox==4.7.0` +
  `netboxlabs-netbox-custom-objects==0.6.1`(版本随脚本顶部 NB_VERSION/PLUGIN_VERSION 升级);
- 生成 `configuration.py`(插件声明、本地 media/static 路径、DEBUG=True 仅测试用途);
- `migrate` 后创建 admin(密码默认 `secreq-admin`)与 **v1 API 令牌** —— 由 NetBox 生成 40 位明文,
  存 `netbox/api-token`;v1 保住 `Authorization: Token <key>` 口径,避开 4.4+ 的 Token V2/pepper 机制。
  明文在 DB 可回读:文件丢了重跑 `up` 自动恢复。
- 后台启动 `netbox runserver 0.0.0.0:8080`(日志 `netbox/netbox.log`,pid `netbox/netbox.pid`);
- 建 custom object 类型 `system` 与文本字段 `name(必填)/code/owner_name`;
  **NetBox 4.5+ 自带 `owner` 对象引用字段**,文本负责人字段因此改名 `owner_name`,
  SecReq 侧 field_map 相应配 `{"owner": "owner_name"}`;
- 铺样例数据:演示站点/角色/设备类型/设备 `edge-app-01`/IP `10.20.0.5/24`/示例系统对象 `NB-SYS-001`。

## SecReq 侧接入

二选一:

1. 管理界面:系统管理 → NetBox 互通,填 `http://localhost:8080` 与令牌(`netbox/api-token`),
   field_map 配 `{"name":"name","code":"code","owner":"owner_name"}`。
2. 后端环境变量(库内未配置时回退):

   ```bash
   SECREQ_NETBOX_URL=http://localhost:8080
   SECREQ_NETBOX_TOKEN=<netbox/api-token 内容>
   SECREQ_NETBOX_SYSTEM_SLUG=system
   ```

## 联动冒烟

SecReq 后端运行后(注意:NetBox 全部端点自 #196 起仅安全角色可用):

```bash
SECREQ_URL=http://127.0.0.1:8000 \
SECREQ_USER=sec_admin SECREQ_PASSWORD=<密码> \
scripts/netbox_smoke.sh
```

覆盖:配置回填(含 field_map)→ `/api/netbox/status` → 系统清单导入(应见样例系统 `NB-SYS-001`)→
设备代理 → 新建 SecReq 台账系统并推送 NetBox,校验 `netbox_object_id` 回填。

冒烟也可以完全零依赖地跑:临时 SecReq 实例(独立 sqlite,不碰生产库),跑完删除:

```bash
SECREQ_DATABASE_URL=sqlite:///./netbox/smoke-secreq.db SECREQ_SEED_PASSWORD=netbox-smoke \
  uv run uvicorn main:app --port 8000 &
SECREQ_PASSWORD=netbox-smoke scripts/netbox_smoke.sh
```

## 契约速查(SecReq 消费面,对照 NetBox 4.7 实测)

| 用途 | 端点 |
| --- | --- |
| 连接测试 | `GET /api/status`(301 → `/api/status/`,客户端已开 follow_redirects) |
| 设备/虚拟机/IP 代理 | `GET /api/dcim/devices/` 等,`q=`+`limit/offset` |
| 站点/角色/设备类型下拉 | `GET /api/dcim/sites/`、`/api/dcim/device-roles/`(4.7 实名,非 roles/)、`/api/dcim/device-types/` |
| 系统对象清单/创建 | `GET|POST /api/plugins/custom-objects/<slug>/` |
| 类型定义(字段对照) | `GET /api/plugins/custom-objects/custom-object-types/` |

认证:`Authorization: Token <key>`(v1);错误口径:未配置 409、NetBox 故障 502、4xx 透传 detail。
`services/netbox.py` 的两处实测修正:客户端 `follow_redirects=True`、角色下拉用 `device-roles`。

## 常见问题

- **端口/密码/slug 换掉**:`NETBOX_PORT` / `NETBOX_SUPERUSER_PASSWORD` / `NETBOX_SYSTEM_SLUG` 在 `up` 前设置。
- **localhost:8080 从 Windows 打不开**:WSL2 转发未生效时,`up` 结束会打印 WSL IP
  (也可 `wsl hostname -I` 查看),接入配置里的 base_url 换成 `http://<WSL_IP>:8080`。
- **升级 NetBox/插件**:改脚本顶部 `NB_VERSION` / `PLUGIN_VERSION` 后重跑 `up`;
  全新数据:`down` → `dropdb`/`rm -rf ~/.secreq-netbox` → `up`。
- **令牌轮换**:`down` 后在 DB 删除 v1 令牌(`manage.py shell` 里 `Token.objects.filter(version=1).delete()`),
  重跑 `up` 即生成新令牌并覆盖 `netbox/api-token`。
