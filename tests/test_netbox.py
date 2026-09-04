# -*- coding: utf-8 -*-
"""NetBox 互通测试(#152): 客户端 + 配置 + 管理端点。

仿 test_osv.py: 用 httpx.MockTransport 模拟 NetBox REST, 覆盖:
env 回退 / token 掩码 / 连接测试成败与超时 / 错误归因 / 列表字段裁剪 / 审计留痕。
"""
import httpx
import pytest

from conftest import api_as, create_system_api

from services.netbox import NetboxApiError, NetboxClient, NetboxUnavailable
from services.settings_service import get_netbox_config, get_setting, set_setting

NB_BASE = "https://netbox.example.com"
NB_TOKEN = "tok-0123456789abcdef"


def _handler(routes: dict[str, object]):
    """按 (method, path) 前缀路由的 MockTransport 处理器。"""

    def handler(request: httpx.Request) -> httpx.Response:
        key = f"{request.method} {request.url.path}"
        if key in routes:
            outcome = routes[key]
            if isinstance(outcome, Exception):
                raise outcome
            if isinstance(outcome, httpx.Response):
                return outcome
            return httpx.Response(200, json=outcome)
        return httpx.Response(404, json={"detail": "Not found"})

    return handler


def _client(routes: dict[str, object], token: str = NB_TOKEN) -> NetboxClient:
    return NetboxClient(NB_BASE, token, transport=httpx.MockTransport(_handler(routes)))


def _routes_for_config(session, **cfg):
    set_setting(session, "netbox", cfg)


# ────────────────────────── 客户端 ──────────────────────────

def test_client_get_status_ok():
    client = _client({"GET /api/status": {"netbox-version": "4.2.1"}})
    try:
        assert client.get_status()["netbox-version"] == "4.2.1"
    finally:
        client.close()


def test_client_list_devices_trims_fields():
    """列表代理只留展示所需字段: 嵌套对象取 name/address/value。"""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["q"] == "edge"
        assert request.url.params["limit"] == "10"
        assert request.url.params["offset"] == "5"
        assert request.headers["Authorization"] == f"Token {NB_TOKEN}"
        return httpx.Response(200, json={
            "count": 1, "results": [{
                "id": 7, "name": "edge-sw01", "display": "edge-sw01",
                "primary_ip": {"address": "10.0.0.2/24"},
                "site": {"name": "总部机房"}, "role": {"name": "交换机"},
                "device_type": {"model": "S5735"}, "status": {"value": "active"},
                "url": f"{NB_BASE}/dcim/devices/7/",
            }],
        })

    client = NetboxClient(NB_BASE, NB_TOKEN, transport=httpx.MockTransport(handler))
    try:
        data = client.list_devices(keyword="edge", limit=10, offset=5)
    finally:
        client.close()
    row = data["results"][0]
    assert row == {
        "id": 7, "name": "edge-sw01", "primary_ip": "10.0.0.2/24",
        "site": "总部机房", "role": "交换机", "device_type": "S5735",
        "status": "active", "url": f"{NB_BASE}/dcim/devices/7/",
    }


def test_client_error_mapping():
    """连接失败/超时/5xx → NetboxUnavailable; 4xx → NetboxApiError 透传 detail。"""
    client = _client({
        "GET /api/status": httpx.Response(500, json={"detail": "boom"}),
        "GET /api/dcim/devices/": httpx.Response(403, json={"detail": "Permission denied"}),
    })
    try:
        with pytest.raises(NetboxUnavailable, match="服务异常"):
            client.get_status()
        with pytest.raises(NetboxApiError, match="Permission denied"):
            client.list_devices()
    finally:
        client.close()

    def connect_fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timeout")

    c2 = NetboxClient(NB_BASE, NB_TOKEN,
                      transport=httpx.MockTransport(connect_fail))
    c3 = NetboxClient(NB_BASE, NB_TOKEN, transport=httpx.MockTransport(timeout))
    try:
        with pytest.raises(NetboxUnavailable, match="不可达"):
            c2.get_status()
        with pytest.raises(NetboxUnavailable, match="超时"):
            c3.get_status()
    finally:
        c2.close()
        c3.close()


def test_client_create_device_uses_role_field():
    """NetBox 4.x 建设备的角色字段为 role; 成功回传对象。"""
    payload = {"name": "core-sw", "site": 1, "role": 2, "device_type": 3}

    def handler(request: httpx.Request) -> httpx.Response:
        import json
        assert json.loads(request.content) == payload
        return httpx.Response(201, json={"id": 9, **payload})

    client = NetboxClient(NB_BASE, NB_TOKEN, transport=httpx.MockTransport(handler))
    try:
        assert client.create_device(payload)["id"] == 9
    finally:
        client.close()


# ────────────────────────── 配置解析 ──────────────────────────

def test_netbox_config_env_fallback(session, monkeypatch):
    """库内未配置时回退 env; slug/field_map 有默认值。"""
    monkeypatch.setenv("SECREQ_NETBOX_URL", f"{NB_BASE}/")
    monkeypatch.setenv("SECREQ_NETBOX_TOKEN", NB_TOKEN)
    cfg = get_netbox_config(session)
    assert cfg["base_url"] == NB_BASE  # 尾斜杠去除
    assert cfg["token"] == NB_TOKEN
    assert cfg["system_slug"] == "system"
    assert cfg["field_map"] == {"name": "name", "code": "code", "owner": "owner"}


def test_netbox_config_db_overrides_env(session, monkeypatch):
    """库内配置优先于 env; 未配置齐(缺 token)返回空 dict。"""
    monkeypatch.setenv("SECREQ_NETBOX_URL", "https://from-env.example.com")
    monkeypatch.setenv("SECREQ_NETBOX_TOKEN", "env-token")
    env_cfg = get_netbox_config(session)
    assert env_cfg["base_url"] == "https://from-env.example.com"  # 库内未配置 → env 生效

    set_setting(session, "netbox", {
        "base_url": NB_BASE, "token": NB_TOKEN, "system_slug": "sysobj",
        "field_map": {"name": "title"},
    })
    cfg = get_netbox_config(session)
    assert cfg["base_url"] == NB_BASE and cfg["token"] == NB_TOKEN
    assert cfg["system_slug"] == "sysobj"
    assert cfg["field_map"] == {"name": "title"}
    assert get_setting(session, "netbox")["base_url"] == NB_BASE


def test_netbox_config_missing_token_is_unconfigured(session, monkeypatch):
    monkeypatch.setenv("SECREQ_NETBOX_URL", NB_BASE)
    monkeypatch.delenv("SECREQ_NETBOX_TOKEN", raising=False)
    assert get_netbox_config(session) == {}


# ────────────────────────── 管理端点 ──────────────────────────

@pytest.fixture()
def sec(api):
    from conftest import api_as
    return api_as(api, "sec_admin")


def _isolate_env(monkeypatch):
    for var in ("SECREQ_NETBOX_URL", "SECREQ_NETBOX_TOKEN", "SECREQ_NETBOX_SYSTEM_SLUG"):
        monkeypatch.delenv(var, raising=False)


def test_netbox_config_endpoint_mask_and_auth(api, sec, monkeypatch):
    """GET 掩码回显(前 4 位 + ****); 非安全角色 403; 未配置时 configured=False。"""
    assert api.get("/api/admin/netbox-config").status_code == 403

    _isolate_env(monkeypatch)
    body = sec.get("/api/admin/netbox-config").json()
    assert body["configured"] is False

    saved = sec.put("/api/admin/netbox-config", json={
        "base_url": NB_BASE, "token": NB_TOKEN, "system_slug": "system",
        "field_map": {"name": "name", "code": "code", "owner": "owner"},
    })
    assert saved.status_code == 200
    body = sec.get("/api/admin/netbox-config").json()
    assert body["configured"] is True
    assert body["base_url"] == NB_BASE
    assert body["token"] == "tok-" + "****"


def test_netbox_put_config_audited(api, sec):
    """PUT 保存并审计(netbox_update), 审计明细不含 token 明文。"""
    resp = sec.put("/api/admin/netbox-config", json={
        "base_url": NB_BASE, "token": NB_TOKEN, "system_slug": "system",
        "field_map": {"name": "name", "code": "code", "owner": "owner"},
    })
    assert resp.status_code == 200
    logs = sec.get("/api/admin/audit-logs").json()
    entry = next((log for log in logs if log["action"] == "netbox_update"), None)
    assert entry is not None
    assert NB_TOKEN not in str(entry)


def test_netbox_test_endpoint_attribution(api, sec, monkeypatch):
    """测试连接: 未存 token 且未提交 → 400; 成功/认证失败/超时/不可达 可读归因。

    端点内部自建 client, 桩掉 routers.admin.NetboxClient 免真实网络;
    归因文案本身来自客户端异常(客户端层归因已有单测), 这里验证透传与归类。
    """
    _isolate_env(monkeypatch)
    assert sec.post("/api/admin/netbox-config/test",
                    json={"base_url": NB_BASE}).status_code == 400

    sec.put("/api/admin/netbox-config", json={
        "base_url": NB_BASE, "token": NB_TOKEN, "system_slug": "system",
        "field_map": {"name": "name", "code": "code", "owner": "owner"},
    })

    class FakeClient:
        """按用例注入的 get_status 行为构造。"""

        behavior: Exception | dict = {}

        def __init__(self, base_url: str, token: str, timeout: float = 10.0, transport=None):
            assert token == NB_TOKEN, "未提交 token 时应沿用已保存配置"

        def get_status(self):
            if isinstance(self.behavior, Exception):
                raise self.behavior
            return self.behavior

        def close(self):
            pass

    monkeypatch.setattr("routers.admin.NetboxClient", FakeClient)

    def call() -> dict:
        return sec.post("/api/admin/netbox-config/test",
                        json={"base_url": NB_BASE}).json()

    FakeClient.behavior = {"netbox-version": "4.2.1"}
    ok = call()
    assert ok["ok"] is True and ok["version"] == "4.2.1" and "latency_ms" in ok

    FakeClient.behavior = NetboxApiError("NetBox 返回 401: invalid token")
    assert "凭据无效" in call()["reason"]

    FakeClient.behavior = NetboxUnavailable("请求超时(8s), NetBox 无响应或网络不通")
    assert "超时" in call()["reason"]

    FakeClient.behavior = NetboxUnavailable("地址不可达(连接失败), 请检查 NetBox 地址与网络")
    assert "不可达" in call()["reason"]


def test_netbox_system_fields_unconfigured(api, sec, monkeypatch):
    """未配置时 system-fields 返回 409 可读提示。"""
    _isolate_env(monkeypatch)
    resp = sec.get("/api/admin/netbox-config/system-fields")
    assert resp.status_code == 409
    assert "尚未配置" in resp.json()["detail"]


# ────────────────────────── /api/netbox 代理与写回(#153) ──────────────────────────

@pytest.fixture()
def netbox_ready(api, sec, monkeypatch):
    """配置好 NetBox 并桩掉 routers.netbox.NetboxClient; 返回可编程的 Fake 类。"""
    _isolate_env(monkeypatch)
    saved = sec.put("/api/admin/netbox-config", json={
        "base_url": NB_BASE, "token": NB_TOKEN, "system_slug": "system",
        "field_map": {"name": "name", "code": "code", "owner": "owner"},
    })
    assert saved.status_code == 200

    class FakeProxyClient:
        devices: list[dict] = []
        created: dict | None = None
        create_error: Exception | None = None
        unreachable: Exception | None = None

        def __init__(self, base_url: str, token: str, timeout: float = 10.0, transport=None):
            pass

        def close(self):
            pass

        def list_devices(self, keyword=None, limit=25, offset=0):
            if FakeProxyClient.unreachable:
                raise FakeProxyClient.unreachable
            rows = [d for d in FakeProxyClient.devices
                    if not keyword or keyword.lower() in str(d.get("name") or "").lower()]
            return {"count": len(rows), "results": rows[offset:offset + limit]}

        def list_sites(self):
            return [{"id": 1, "name": "总部机房", "slug": "hq"}]

        def list_device_roles(self):
            return [{"id": 2, "name": "交换机", "slug": "switch"}]

        def list_device_types(self):
            return [{"id": 3, "model": "S5735", "slug": "s5735"}]

        def create_device(self, payload: dict):
            if FakeProxyClient.create_error:
                raise FakeProxyClient.create_error
            FakeProxyClient.created = payload
            return {"id": 42, "url": f"{NB_BASE}/dcim/devices/42/"}

        def create_ip_address(self, payload: dict):
            return {"id": 7, "address": payload["address"]}

        def patch_device(self, device_id: int, payload: dict):
            return {"id": device_id}

        system_objects: list[dict] = []
        created_system: dict | None = None

        def list_system_objects(self, slug: str, keyword=None, limit=25, offset=0):
            rows = [o for o in FakeProxyClient.system_objects
                    if not keyword or keyword.lower() in str(o.get("name") or "").lower()]
            return {"count": len(rows), "results": rows[offset:offset + limit]}

        def create_system_object(self, slug: str, payload: dict):
            FakeProxyClient.created_system = payload
            return {"id": 77, **payload,
                    "url": f"{NB_BASE}/plugins/custom-objects/{slug}/objects/77"}

    monkeypatch.setattr("routers.netbox.NetboxClient", FakeProxyClient)
    FakeProxyClient.devices = []
    FakeProxyClient.created = None
    FakeProxyClient.create_error = None
    FakeProxyClient.unreachable = None
    FakeProxyClient.system_objects = []
    FakeProxyClient.created_system = None
    return FakeProxyClient


def _make_asset(api) -> tuple[int, int]:
    """建(挂系统的)项目并保存一条基础设施资产, 返回 (project_id, asset_id)。"""
    system = create_system_api(api, f"NetBox 资产系统{id(api) % 10000}")
    pid = api.post("/api/projects", json={
        "name": "NetBox 资产项目", "system_id": system["id"]}).json()["id"]
    rows = api.post(f"/api/projects/{pid}/infra-assets", json={
        "assets": [{"asset_type": "server", "name": "E2E 应用服务器", "env": "prod",
                    "quantity": 1}],
    }).json()
    return pid, rows[0]["id"]


def test_proxy_unconfigured_returns_409(api, sec, monkeypatch):
    """#196: NetBox 全端点仅安全角色; 开发直调一律 403。"""
    assert api.get("/api/netbox/devices").status_code == 403
    assert api.get("/api/netbox/status").status_code == 403
    _isolate_env(monkeypatch)
    resp = sec.get("/api/netbox/devices")
    assert resp.status_code == 409
    assert "尚未配置" in resp.json()["detail"]


def test_proxy_list_and_options(netbox_ready, sec):
    netbox_ready.devices = [
        {"id": 9, "name": "edge-sw01", "primary_ip": "10.0.0.2/24", "site": "总部机房",
         "role": "交换机", "device_type": "S5735", "status": "active",
         "url": f"{NB_BASE}/dcim/devices/9/"},
    ]
    rows = sec.get("/api/netbox/devices", params={"keyword": "edge"}).json()
    assert rows["count"] == 1 and rows["results"][0]["name"] == "edge-sw01"

    options = sec.get("/api/netbox/options").json()
    assert options["base_url"] == NB_BASE
    assert options["sites"][0]["name"] == "总部机房"
    assert options["roles"][0]["id"] == 2
    assert options["device_types"][0]["model"] == "S5735"


def test_proxy_unreachable_502(netbox_ready, sec):
    netbox_ready.unreachable = NetboxUnavailable("地址不可达(连接失败), 请检查 NetBox 地址与网络")
    resp = sec.get("/api/netbox/devices")
    assert resp.status_code == 502
    assert "不可达" in resp.json()["detail"]


def test_push_device_roundtrip_and_dedupe(netbox_ready, api, sec):
    """推送成功回填 netbox_ref; 重复推送 409; NetBox 同名设备 409 带外链; 审计留痕。"""
    pid, asset_id = _make_asset(api)

    # NetBox 侧已有同名设备 → 409 带外链
    netbox_ready.devices = [{"id": 5, "name": "E2E 应用服务器", "url": f"{NB_BASE}/dcim/devices/5/"}]
    dup = sec.post("/api/netbox/devices", json={
        "project_id": pid, "asset_id": asset_id, "name": "E2E 应用服务器",
        "site_id": 1, "role_id": 2, "device_type_id": 3, "ip_address": "10.0.0.9/24",
    })
    assert dup.status_code == 409
    assert "/dcim/devices/5/" in dup.json()["detail"]

    # 无同名 → 建设备 + 可选 IP 挂主 IP + 回填 ref
    netbox_ready.devices = []
    ok = sec.post("/api/netbox/devices", json={
        "project_id": pid, "asset_id": asset_id, "name": "E2E 应用服务器",
        "site_id": 1, "role_id": 2, "device_type_id": 3, "ip_address": "10.0.0.9/24",
    })
    assert ok.status_code == 200, ok.text
    assert ok.json()["netbox_ref_id"] == "42"
    assert netbox_ready.created["role"] == 2  # NetBox 4.x 角色字段为 role

    assets = api.get(f"/api/projects/{pid}/infra-assets").json()
    assert assets[0]["netbox_ref_type"] == "dcim.device"
    assert assets[0]["netbox_ref_id"] == "42"

    # 已关联 → 再推 409
    again = sec.post("/api/netbox/devices", json={
        "project_id": pid, "asset_id": asset_id, "name": "E2E 应用服务器",
        "site_id": 1, "role_id": 2, "device_type_id": 3,
    })
    assert again.status_code == 409
    assert "已关联" in again.json()["detail"]

    logs = sec.get("/api/admin/audit-logs").json()
    assert any(log["action"] == "netbox_push" for log in logs)


def test_push_device_netbox_4xx_passthrough(netbox_ready, api, sec):
    """NetBox 4xx → 502 透传 detail; SecReq 资产行不回滚。"""
    pid, asset_id = _make_asset(api)
    netbox_ready.create_error = NetboxApiError("NetBox 返回 400: Invalid site")
    resp = sec.post("/api/netbox/devices", json={
        "project_id": pid, "asset_id": asset_id, "name": "E2E 应用服务器",
        "site_id": 999, "role_id": 2, "device_type_id": 3,
    })
    assert resp.status_code == 502
    assert "Invalid site" in resp.json()["detail"]
    assets = api.get(f"/api/projects/{pid}/infra-assets").json()
    assert assets[0]["netbox_ref_id"] is None  # 失败不回填, 行数据无损


def test_push_device_role_and_project_guard(netbox_ready, api, sec):
    """资产不属于该项目 → 404; 越权项目 → 404(不泄露存在性)。"""
    pid, asset_id = _make_asset(api)
    resp = sec.post("/api/netbox/devices", json={
        "project_id": pid + 1, "asset_id": asset_id, "name": "x",
        "site_id": 1, "role_id": 2, "device_type_id": 3,
    })
    assert resp.status_code == 404


def test_infra_asset_netbox_ref_persists_via_save(api):
    """整卷保存带回 netbox_ref_*(导入场景): 落库并回读一致。"""
    system = create_system_api(api, "NetBox 导入系统")
    pid = api.post("/api/projects", json={
        "name": "NetBox 导入项目", "system_id": system["id"]}).json()["id"]
    saved = api.post(f"/api/projects/{pid}/infra-assets", json={
        "assets": [{"asset_type": "server", "name": "db-vm01", "env": "prod",
                    "netbox_ref_type": "virtualization.virtual-machine",
                    "netbox_ref_id": "31"}],
    }).json()
    assert saved[0]["netbox_ref_type"] == "virtualization.virtual-machine"
    rows = api.get(f"/api/projects/{pid}/infra-assets").json()
    assert rows[0]["netbox_ref_id"] == "31"


# ────────────────────────── 系统清单互通(#154) ──────────────────────────

def test_proxy_systems_field_map_trimming(netbox_ready, sec):
    """系统清单代理按 field_map 裁剪: 自定义字段名映射生效。"""
    saved = sec.put("/api/admin/netbox-config", json={
        "base_url": NB_BASE, "token": NB_TOKEN, "system_slug": "sysobj",
        "field_map": {"name": "title", "code": "sn", "owner": "keeper"},
    })
    assert saved.status_code == 200
    netbox_ready.system_objects = [
        {"id": 31, "title": "个人网银", "sn": "NB-001", "keeper": "张三",
         "url": f"{NB_BASE}/plugins/custom-objects/sysobj/objects/31"},
    ]
    data = sec.get("/api/netbox/systems").json()
    assert data["count"] == 1
    assert data["results"][0] == {
        "id": 31, "name": "个人网银", "code": "NB-001", "owner": "张三",
        "url": f"{NB_BASE}/plugins/custom-objects/sysobj/objects/31",
    }


def test_push_system_roundtrip_and_dedupe(netbox_ready, api, sec):
    """推送台账系统: 名称查重 409 / 成功回填 netbox_object_id / 已关联 409 / 审计。"""
    sid = api.post("/api/systems", json={"name": "个人网银", "owner_name": "张三"}).json()["id"]

    netbox_ready.system_objects = [
        {"id": 20, "name": "个人网银", "url": f"{NB_BASE}/plugins/custom-objects/system/objects/20"},
    ]
    dup = sec.post("/api/netbox/systems", json={
        "system_id": sid, "name": "个人网银", "owner": "张三"})
    assert dup.status_code == 409
    assert "已存在同名系统" in dup.json()["detail"]

    netbox_ready.system_objects = []
    ok = sec.post("/api/netbox/systems", json={
        "system_id": sid, "name": "个人网银", "code": "SRQ-001", "owner": "张三"})
    assert ok.status_code == 200, ok.text
    assert ok.json()["netbox_object_id"] == "77"
    assert netbox_ready.created_system == {"name": "个人网银", "code": "SRQ-001", "owner": "张三"}

    systems = api.get("/api/systems").json()
    mine = next(sy for sy in systems if sy["id"] == sid)
    assert mine["netbox_object_id"] == "77"

    again = sec.post("/api/netbox/systems", json={"system_id": sid, "name": "个人网银"})
    assert again.status_code == 409
    assert "已关联" in again.json()["detail"]

    logs = sec.get("/api/admin/audit-logs").json()
    assert any(log["action"] == "netbox_push" for log in logs)


def test_push_system_owner_guard(netbox_ready, api, sec):
    """开发只可推送本人系统; 越权 404 不泄露存在性; 开发直调一律 403(#196)。"""
    other = api_as(api, "sec_admin")  # 安全角色建的系统, owner_user_id 为 sec
    sid = other.post("/api/systems", json={"name": "他人系统"}).json()["id"]
    resp = api.post("/api/netbox/systems", json={"system_id": sid, "name": "他人系统"})
    assert resp.status_code == 403  # #196: 角色门控先于归属校验
    other_sid = sec.post("/api/systems", json={"name": "安全侧推送系统"}).json()["id"]
    ok = sec.post("/api/netbox/systems", json={"system_id": other_sid, "name": "安全侧推送系统"})
    assert ok.status_code in (200, 409)  # 安全角色可推送(重复名由 NetBox 侧查重兜底)
