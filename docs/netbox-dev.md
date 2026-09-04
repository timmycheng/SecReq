# NetBox 联动测试环境

SecReq 的 NetBox 互通(#152 配置管理 / #153 资产导入推送 / #154 系统台账互通)针对真实 NetBox 4.x +
官方 [netbox-custom-objects](https://github.com/netboxlabs/netbox-custom-objects) 插件;单元层用
httpx MockTransport 隔离(tests/test_netbox.py),本环境提供**真实联动**的本地靶场。

- 实体目录 `netbox/`(已 gitignore):netbox-docker 克隆、数据卷、令牌文件,全部本地自持。
- 可版本化文件:`scripts/netbox_dev.sh`(拉起)、`scripts/netbox_smoke.sh`(联动冒烟),换环境只要这两件 + Docker。

## 快速开始

```bash
scripts/netbox_dev.sh up        # 拉起(首次自动克隆 netbox-docker 并拉镜像)
scripts/netbox_dev.sh info      # 查看地址/令牌/接入配置
scripts/netbox_dev.sh down      # 停止(数据卷保留; 卷也不要了: docker compose down -v)
```

`up` 会自动完成:克隆 netbox-docker → 打开 superuser 引导并写入 admin 密码 → 声明
`netbox_custom_objects` 插件 → 发布 8080 端口 → 等待就绪 → 容器内安装插件并重启 →
创建固定 key 的 v1 API 令牌(存 `netbox/api-token`)→ 建类型 `system` 与字段
`name(必填)/code/owner`(对应 SecReq 的 field_map 默认值)→ 铺样例数据
(演示站点/角色/设备类型/设备 `edge-app-01`/IP `10.20.0.5/24`/示例系统对象 `NB-SYS-001`)。

全部步骤幂等,重复执行 `up` 安全。

## SecReq 侧接入

二选一:

1. 管理界面:系统管理 → NetBox 互通,填 `http://localhost:8080` 与令牌(`netbox/api-token`)。
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

覆盖:配置回填 → `/api/netbox/status` → 系统清单导入(应见样例系统 `NB-SYS-001`)→
设备代理 → 新建 SecReq 台账系统并推送 NetBox,校验 `netbox_object_id` 回填。

## 契约速查(SecReq 消费面)

| 用途 | 端点 |
| --- | --- |
| 连接测试 | `GET /api/status` |
| 设备/虚拟机/IP 代理 | `GET /api/dcim/devices/` 等,`q=`+`limit/offset` |
| 站点/角色/设备类型下拉 | `GET /api/dcim/sites/`、`/dcim/roles/`、`/dcim/device-types/` |
| 系统对象清单/创建 | `GET|POST /api/plugins/custom-objects/<slug>/` |
| 类型定义(字段对照) | `GET /api/plugins/custom-objects/object-types/<slug>/` |

认证:`Authorization: Token <key>`;错误口径:未配置 409、NetBox 故障 502、4xx 透传 detail。

## 常见问题

- **端口/密码/slug 换掉**:`NETBOX_PORT` / `NETBOX_SUPERUSER_PASSWORD` / `NETBOX_SYSTEM_SLUG` 环境变量在 `up` 前设置。
- **down 后再 up**:容器重建后插件需要重装,`up` 会自动检测并补装;数据卷未删则 NetBox 数据保留。
- **彻底重置**:`cd netbox/netbox-docker && docker compose down -v`,再 `up` 即全新环境。
- **令牌轮换**:删除 `netbox/api-token` 后重跑 `up`(以新 key 重建 v1 令牌)。
