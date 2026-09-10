# -*- coding: utf-8 -*-
"""NetBox 互通测试(#152): 客户端 + 配置 + 管理端点。

仿 test_osv.py: 用 httpx.MockTransport 模拟 NetBox REST, 覆盖:
env 回退 / token 掩码 / 连接测试成败与超时 / 错误归因 / 列表字段裁剪 / 审计留痕。
"""
import httpx
import pytest

from conftest import api_as


from models import InfraAsset, System
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


def test_netbox_put_empty_or_masked_token_keeps_stored(api, sec, monkeypatch):
    """#324: 保存时空串/掩码 token 沿用库内原值, 不覆盖真实凭据。"""
    _isolate_env(monkeypatch)
    assert sec.put("/api/admin/netbox-config", json={
        "base_url": NB_BASE, "token": NB_TOKEN, "system_slug": "system",
        "field_map": {"name": "name", "code": "code", "owner": "owner"},
    }).status_code == 200
    masked = sec.get("/api/admin/netbox-config").json()["token"]

    from services.settings_service import get_setting

    def stored_token():
        db = api.session_factory()
        try:
            return get_setting(db, "netbox")["token"]
        finally:
            db.close()

    # 前端固定发送 token: v.token || '' → 空串不得清掉已存 token
    assert sec.put("/api/admin/netbox-config", json={
        "base_url": NB_BASE + "/", "token": "", "system_slug": "system",
        "field_map": {"name": "name", "code": "code", "owner": "owner"},
    }).status_code == 200
    assert stored_token() == NB_TOKEN

    assert sec.put("/api/admin/netbox-config", json={
        "base_url": NB_BASE, "token": masked, "system_slug": "system",
        "field_map": {"name": "name", "code": "code", "owner": "owner"},
    }).status_code == 200
    assert stored_token() == NB_TOKEN


def test_netbox_test_rejects_new_url_with_stored_token(api, sec, monkeypatch):
    """#324 外带防护: 沿用已存 token 只能测当前保存的 NetBox 地址。"""
    _isolate_env(monkeypatch)
    sec.put("/api/admin/netbox-config", json={
        "base_url": NB_BASE, "token": NB_TOKEN, "system_slug": "system",
        "field_map": {"name": "name", "code": "code", "owner": "owner"},
    })
    resp = sec.post("/api/admin/netbox-config/test",
                    json={"base_url": "https://evil.example.com"})
    assert resp.status_code == 400
    assert "重新输入" in resp.json()["detail"]


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


# ────────────────────────── 同步 ETL(#271) ──────────────────────────

class FakeSyncClient:
    """同步引擎的可编程桩: 进程内字典模拟 NetBox 对象存储, 覆盖 upsert 语义。

    - 系统对象: list/get/create/patch, 按内存字典维护(含 404 断链场景);
    - 引导对象: 首查空 → create 计数; 再查命中 → 不重建;
    - 设备/IP: 名称/地址查重 + 创建 + PATCH(名称/主 IP)。
    """

    def __init__(self, base_url=None, token=None, timeout=None, transport=None):
        self.system_objects = {}
        self.next_id = 100
        self.created_counts = {"site": 0, "role": 0, "manufacturer": 0, "device_type": 0}
        self.sites = {}
        self.roles = {}
        self.manufacturers = {}
        self.device_types = {}
        self.devices = {}
        self.ips = {}
        self.patches = []

    def _new_id(self):
        self.next_id += 1
        return self.next_id

    # 系统 custom-objects
    def list_system_objects(self, slug, keyword=None, limit=25, offset=0):
        rows = [o for o in self.system_objects.values()
                if not keyword or keyword.lower() in str(o.get("name") or "").lower()]
        return {"count": len(rows), "results": rows}

    def get_system_object(self, slug, object_id):
        if int(object_id) not in self.system_objects:
            raise NetboxApiError("NetBox 返回 404: Not found")
        return self.system_objects[int(object_id)]

    def create_system_object(self, slug, payload):
        obj = {"id": self._new_id(), **payload}
        self.system_objects[obj["id"]] = obj
        return obj

    def patch_system_object(self, slug, object_id, payload):
        self.system_objects[int(object_id)].update(payload)
        self.patches.append(("system", int(object_id), payload))
        return self.system_objects[int(object_id)]

    # 引导对象: 首查为空 → 创建并建档; 二轮 list 命中 → 不重建
    def list_sites(self):
        return list(self.sites.values())

    def create_site(self, payload):
        self.created_counts["site"] += 1
        row = {"id": self._new_id(), **payload}
        self.sites[row["slug"]] = row
        return row

    def list_device_roles(self):
        return list(self.roles.values())

    def create_device_role(self, payload):
        self.created_counts["role"] += 1
        row = {"id": self._new_id(), **payload}
        self.roles[row["slug"]] = row
        return row

    def list_manufacturers(self):
        return list(self.manufacturers.values())

    def create_manufacturer(self, payload):
        self.created_counts["manufacturer"] += 1
        row = {"id": self._new_id(), **payload}
        self.manufacturers[row["slug"]] = row
        return row

    def list_device_types(self):
        return list(self.device_types.values())

    def create_device_type(self, payload):
        self.created_counts["device_type"] += 1
        row = {"id": self._new_id(), **payload}
        self.device_types[row["slug"]] = row
        return row

    # 设备与 IP
    def list_devices(self, keyword=None, limit=25, offset=0):
        rows = [d for d in self.devices.values()
                if not keyword or keyword.lower() in str(d.get("name") or "").lower()]
        return {"count": len(rows), "results": rows}

    def get_device(self, device_id):
        if int(device_id) not in self.devices:
            raise NetboxApiError("NetBox 返回 404: Not found")
        return self.devices[int(device_id)]

    def create_device(self, payload):
        obj = {"id": self._new_id(), **payload, "primary_ip4": None}
        self.devices[obj["id"]] = obj
        return obj

    def patch_device(self, device_id, payload):
        self.devices[int(device_id)].update(payload)
        self.patches.append(("device", int(device_id), payload))
        return self.devices[int(device_id)]

    def list_ip_addresses(self, keyword=None, limit=25, offset=0):
        rows = [i for i in self.ips.values()
                if not keyword or keyword in str(i.get("address") or "")]
        return {"count": len(rows), "results": rows}

    def create_ip_address(self, payload):
        row = {"id": self._new_id(), **payload}
        self.ips[row["id"]] = row
        return row

    def close(self):
        pass


def _configured_session(session):
    """给纯 db 会话配好 netbox 设置(直连 run_sync 的用例)。"""
    set_setting(session, "netbox", {
        "base_url": NB_BASE, "token": NB_TOKEN, "system_slug": "system",
        "field_map": {"name": "name", "code": "code", "owner": "owner"},
    })


def _add_system(session, name="核心系统", code="SYS-1", owner="张三"):
    system = System(name=name, code=code, owner_name=owner,
                    user_scale="1k_to_100k", is_public=False)
    session.add(system)
    session.commit()
    return system


def _add_asset(session, system_id, name="应用服务器", ip="10.0.0.9/24"):
    asset = InfraAsset(system_id=system_id, asset_type="server", name=name,
                       env="prod", quantity=1, ip=ip)
    session.add(asset)
    session.commit()
    return asset


def test_sync_unconfigured_creates_failed_log(session):
    """未配置时同步直接 failed, 日志留可读原因(不抛异常)。"""
    from services.netbox_sync import run_sync
    log = run_sync(session, "manual")
    assert log.status == "failed"
    assert "尚未配置" in log.errors[0]
    assert log.finished_at is not None


def test_sync_system_upsert_idempotent(session):
    """系统首轮创建并回填 id; 二轮无变化跳过; 改名后 PATCH 更新(#271)。"""
    from services.netbox_sync import run_sync
    _configured_session(session)
    system = _add_system(session)
    fake = FakeSyncClient()

    log1 = run_sync(session, "manual", client=fake)
    assert log1.status == "success"
    assert log1.stats["systems"] == {"created": 1, "updated": 0, "skipped": 0, "failed": 0}
    assert system.netbox_object_id is not None

    log2 = run_sync(session, "scheduled", client=fake)
    assert log2.stats["systems"]["skipped"] == 1
    assert log2.trigger == "scheduled"

    system.name = "核心系统(更名)"
    session.commit()
    log3 = run_sync(session, "manual", client=fake)
    assert log3.stats["systems"]["updated"] == 1
    assert fake.system_objects[int(system.netbox_object_id)]["name"] == "核心系统(更名)"


def test_sync_broken_link_relinks_by_name(session):
    """对端对象被删(id 404)时按名称重新关联, 不重复建对象(#271 幂等)。"""
    from services.netbox_sync import run_sync
    _configured_session(session)
    system = _add_system(session)
    fake = FakeSyncClient()
    run_sync(session, "manual", client=fake)
    old_id = int(system.netbox_object_id)

    # 对端对象仍在, 但本地关联 id 失效(指向不存在的对象): 按名称重新关联
    system.netbox_object_id = "999999"
    session.commit()
    log = run_sync(session, "manual", client=fake)
    assert log.status == "success"
    assert int(system.netbox_object_id) == old_id  # 名称命中 → 重新关联同一对象
    assert log.stats["systems"]["created"] == 0


def test_sync_devices_and_ips_with_bootstrap(session):
    """基础设施资产 → 引导对象自动创建一次 + 设备/IP 创建并回填 ref; 二轮跳过。"""
    from services.netbox_sync import run_sync
    _configured_session(session)
    system = _add_system(session)
    asset = _add_asset(session, system.id)
    fake = FakeSyncClient()

    log1 = run_sync(session, "manual", client=fake)
    assert log1.stats["systems"]["created"] == 1
    assert log1.stats["devices"]["created"] == 1
    assert log1.stats["ips"]["created"] == 1
    assert all(v == 1 for v in fake.created_counts.values())
    assert asset.netbox_ref_id is not None
    device = fake.devices[int(asset.netbox_ref_id)]
    assert device["primary_ip4"] == "10.0.0.9/24"

    log2 = run_sync(session, "manual", client=fake)
    assert log2.stats["devices"]["skipped"] == 1
    assert log2.stats["ips"]["skipped"] == 1
    assert fake.created_counts["site"] == 1  # 引导对象不重复创建


def test_sync_failure_recorded(session):
    """单对象失败(断连)记明细, 整轮状态 failed 且日志带对象名。"""
    from services.netbox_sync import run_sync
    _configured_session(session)
    _add_system(session, name="会失败的系统")
    fake = FakeSyncClient()

    def broken_create(slug, payload):
        raise NetboxUnavailable("地址不可达(连接失败)")

    fake.create_system_object = broken_create
    log = run_sync(session, "manual", client=fake)
    assert log.status == "failed"
    assert any("会失败的系统" in e for e in log.errors)
    assert log.finished_at is not None


def test_sync_endpoint_auth_and_flow(api, sec, monkeypatch):
    """端点口径: 开发 403; 未配置 409; 配置后手动跑通, state/logs 可查。"""
    from services import netbox_sync as ns

    assert api.post("/api/netbox/sync/run").status_code == 403
    assert api.get("/api/netbox/sync/state").status_code == 403
    assert sec.get("/api/netbox/sync/logs").json() == []

    resp = sec.post("/api/netbox/sync/run")
    assert resp.status_code == 409
    assert "尚未配置" in resp.json()["detail"]

    sec.put("/api/admin/netbox-config", json={
        "base_url": NB_BASE, "token": NB_TOKEN, "system_slug": "system",
        "field_map": {"name": "name", "code": "code", "owner": "owner"},
        "sync_enabled": True, "sync_interval_hours": 6,
    })
    monkeypatch.setattr(ns, "NetboxClient", FakeSyncClient)
    run = sec.post("/api/netbox/sync/run")
    assert run.status_code == 200, run.text
    assert run.json()["status"] == "success"

    state = sec.get("/api/netbox/sync/state").json()
    assert state["running"] is False
    assert state["schedule"] == {"enabled": True, "interval_hours": 6}
    assert state["last"]["status"] == "success"

    logs = sec.get("/api/netbox/sync/logs").json()
    assert len(logs) == 1 and logs[0]["trigger"] == "manual"


def test_sync_schedule_defaults(session):
    """调度配置默认关闭、周期回退 24h; 非法值不生效(#271)。"""
    from services.settings_service import get_netbox_schedule
    assert get_netbox_schedule(session) == {"enabled": False, "interval_hours": 24}
    set_setting(session, "netbox", {"sync_enabled": True, "sync_interval_hours": 0})
    assert get_netbox_schedule(session)["interval_hours"] == 24
    set_setting(session, "netbox", {"sync_enabled": True, "sync_interval_hours": 6})
    assert get_netbox_schedule(session) == {"enabled": True, "interval_hours": 6}
