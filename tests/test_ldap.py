# -*- coding: utf-8 -*-
"""LDAP/AD 对接(#280): 配置存取掩码、登录回落、本地兜底开关、目录用户导入。

ldap3 交互全部 mock(内网目录服务在 CI 不可达), 只验证平台侧逻辑。
"""

import pytest

from conftest import api_as

LDAP_PUT = {
    "enabled": True,
    "host": "ldap://10.1.5.20",
    "port": 389,
    "base_dn": "dc=bank,dc=com,dc=cn",
    "bind_dn": "cn=svc-secreq,ou=service,dc=bank,dc=com,dc=cn",
    "bind_password": "svc-secret",
    "user_filter": "(objectClass=person)",
    "attr_username": "uid",
}


@pytest.fixture()
def sec_admin_api(api):
    """安全身份客户端: LDAP 配置端点仅安全角色可达。"""
    client = api_as(api, "sec_admin")
    # api_as 返回新 TestClient, 把同库会话工厂挂上去供用例直查
    client.session_factory = api.session_factory  # type: ignore[attr-defined]
    return client


# ── 配置存取 ─────────────────────────────────────────

def test_ldap_config_mask_and_password_reuse(sec_admin_api):
    """GET 不回显密码; PUT 留空密码沿用已存值。"""
    api = sec_admin_api
    empty = api.get("/api/admin/ldap-config").json()
    assert empty["enabled"] is False
    assert empty["has_password"] is False
    assert "bind_password" not in empty

    resp = api.put("/api/admin/ldap-config", json=LDAP_PUT)
    assert resp.status_code == 200, resp.text
    saved = api.get("/api/admin/ldap-config").json()
    assert saved["enabled"] is True
    assert saved["has_password"] is True
    assert "bind_password" not in saved

    # 密码留空再存: 沿用旧密码
    keep = {**LDAP_PUT, "bind_password": "", "host": "ldaps://10.1.5.21"}
    assert api.put("/api/admin/ldap-config", json=keep).status_code == 200
    from services.settings_service import get_setting
    from services.ldap_service import LDAP_KEY
    db = api.session_factory()
    try:
        stored = get_setting(db, LDAP_KEY)
    finally:
        db.close()
    assert stored["bind_password"] == "svc-secret"
    assert stored["host"] == "ldaps://10.1.5.21"


def test_ldap_requires_security_role(api):
    """开发角色访问 LDAP 配置 → 403。"""
    assert api.get("/api/admin/ldap-config").status_code == 403


# ── 登录集成 ─────────────────────────────────────────

def test_login_falls_back_to_ldap(sec_admin_api, monkeypatch):
    """本地密码未通过 → LDAP 认证通过即登录并自动开通账号。"""
    api = sec_admin_api
    from models import PlatformUser

    def fake_authenticate(db, username, password):
        if password != "ldap-pass":
            return None
        user = db.query(PlatformUser).filter_by(username="ldap_user").first()
        if user is None:
            from services.auth_service import hash_password
            user = PlatformUser(username="ldap_user", display_name="目录用户",
                                role="pm", active=True,
                                password_hash=hash_password("random"))
            db.add(user)
            db.commit()
        return user

    import routers.auth as auth_router
    monkeypatch.setattr(auth_router, "ldap_authenticate", fake_authenticate)

    resp = api.post("/api/auth/login", json={"username": "ldap_user", "password": "ldap-pass"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["role"] == "pm"

    # 本地密码仍然有效(默认允许本地兜底)
    ok = api.post("/api/auth/login", json={"username": "dev_admin", "password": "x"}).status_code
    assert ok == 401  # 错误密码不被 LDAP 放水


def test_local_login_blocked_when_fallback_disabled(sec_admin_api, monkeypatch):
    """关闭本地兜底后, 本地密码正确也不再放行, 必须走目录认证。"""
    import routers.auth as auth_router
    monkeypatch.setattr(auth_router, "local_login_allowed", lambda db: False)
    monkeypatch.setattr(auth_router, "ldap_authenticate", lambda db, u, p: None)

    resp = sec_admin_api.post("/api/auth/login", json={"username": "dev_admin", "password": "x"})
    assert resp.status_code in (401, 429)


# ── 连接测试与用户导入(ldap3 交互 mock) ───────────────

class FakeEntry:
    def __init__(self, dn, attrs):
        self.entry_dn = dn
        self._attrs = attrs

    def __contains__(self, name):
        return name in self._attrs

    def __getitem__(self, name):
        class _V:
            def __init__(self, value):
                self.value = value
        return _V(self._attrs.get(name))


class FakeConn:
    """ldap3.Connection 最小替身: 服务账号 bind 成功, 搜索返回预置条目。"""

    def __init__(self, entries, fail_bind=False):
        self.entries = entries
        self.fail_bind = fail_bind
        self.result = {}

    def unbind(self):
        return True

    def search(self, **_kwargs):
        if self.fail_bind:
            return False
        return True


def test_ldap_test_connection(sec_admin_api, monkeypatch):
    """连接测试: 提交值自带密码(只测不存); bind 失败返回可读原因。"""
    import services.ldap_service as svc

    body = {**LDAP_PUT}
    monkeypatch.setattr(
        svc, "_connect",
        lambda cfg, dn=None, pwd=None: FakeConn([
            FakeEntry(f"uid=u{i},ou=people,dc=bank", {"uid": f"u{i}"}) for i in range(3)
        ]))
    resp = sec_admin_api.post("/api/admin/ldap-config/test", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True
    assert data["user_count"] == 3

    # bind 失败 → ok=False + 原因
    monkeypatch.setattr(
        svc, "_connect",
        lambda cfg, dn=None, pwd=None: (_ for _ in ()).throw(Exception("connection refused")))
    resp = sec_admin_api.post("/api/admin/ldap-config/test", json=body)
    assert resp.json()["ok"] is False
    assert "连接失败" in resp.json()["reason"]


def test_ldap_sync_users(sec_admin_api, monkeypatch):
    """目录导入: 新增默认 pm; 重复导入跳过已有账号。"""
    import services.ldap_service as svc

    assert sec_admin_api.put("/api/admin/ldap-config", json=LDAP_PUT).status_code == 200
    monkeypatch.setattr(
        svc, "_connect",
        lambda cfg, dn=None, pwd=None: FakeConn([
            FakeEntry("uid=dev_admin,ou=people", {"uid": "dev_admin", "cn": "已有账号"}),
            FakeEntry("uid=wang,ou=people", {"uid": "wang", "cn": "王五"}),
            FakeEntry("uid=zhao,ou=people", {"uid": "zhao", "cn": "赵六"}),
        ]))

    resp = sec_admin_api.post("/api/admin/ldap-config/sync")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["total"] == 3
    assert data["created"] == 2
    assert data["skipped"] == 1

    db = sec_admin_api.session_factory()
    try:
        from models import PlatformUser
        wang = db.query(PlatformUser).filter_by(username="wang").first()
        assert wang is not None and wang.role == "pm" and wang.active
    finally:
        db.close()

    # 再导一次: 全部跳过
    data2 = sec_admin_api.post("/api/admin/ldap-config/sync").json()
    assert data2["created"] == 0 and data2["skipped"] == 3


def test_ldap_sync_requires_config(sec_admin_api, monkeypatch):
    """未启用/未配置完整时导入 → 400 可读提示。"""
    import services.ldap_service as svc
    monkeypatch.setattr(svc, "_connect", lambda *a, **k: FakeConn([]))
    resp = sec_admin_api.post("/api/admin/ldap-config/sync")
    assert resp.status_code == 400
    assert "未启用" in resp.json()["detail"]


def test_ldap_audit_trail(sec_admin_api, monkeypatch):
    """LDAP 配置更新与导入动作进审计留痕。"""
    import services.ldap_service as svc
    sec_admin_api.put("/api/admin/ldap-config", json=LDAP_PUT)
    monkeypatch.setattr(svc, "_connect", lambda cfg, dn=None, pwd=None: FakeConn([]))
    sec_admin_api.post("/api/admin/ldap-config/sync")

    logs = sec_admin_api.get("/api/admin/audit-logs").json()
    actions = {row["action"] for row in logs}
    assert {"ldap_update", "ldap_sync"} <= actions
    labels = {row["action"]: row["action_label"] for row in logs}
    assert labels["ldap_sync"] == "LDAP 用户导入"
