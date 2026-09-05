# -*- coding: utf-8 -*-
"""平台认证与数据权限(#216 四类角色):

1. 登录: 账密错误 401 / 正确签发 token / 登出后 token 失效;
2. 全局认证: 无 token 访问业务接口 401(读写都拦), 开放路径放行;
3. 数据权限: pm 只见/只改自己创建的项目, 安全侧/审计全量可见, 越权一律 404;
4. 角色权限矩阵: auditor 任何写 403, pm 进系统管理 403, 存量角色迁移;
5. 项目创建: code 缺省自动生成且唯一, owner 自动写入创建人。
"""
import uuid

import pytest
from fastapi.testclient import TestClient

from conftest import api_as, login_as
from services.auth_service import SEED_DEFAULT_PASSWORD


@pytest.fixture()
def dev_b(api):
    """种子只有 dev_admin/sec_admin, 测试自建第二个 pm 账号。

    初始密码未指定时取种子默认密码, login_as 可直接登录。
    """
    sec = api_as(api, "sec_admin")
    resp = sec.post("/api/admin/users", json={
        "username": "dev_b", "display_name": "项目B", "role": "pm"})
    assert resp.status_code == 201, resp.text
    return "dev_b"


def _create_user(sec: TestClient, username: str, role: str) -> str:
    resp = sec.post("/api/admin/users", json={
        "username": username, "display_name": username, "role": role})
    assert resp.status_code == 201, resp.text
    return username


def test_login_wrong_password_401(api):
    client = TestClient(api.app)
    resp = client.post(
        "/api/auth/login", json={"username": "dev_admin", "password": "wrong"})
    assert resp.status_code == 401


def test_login_unknown_user_401(api):
    client = TestClient(api.app)
    resp = client.post(
        "/api/auth/login", json={"username": "nobody", "password": "x"})
    assert resp.status_code == 401


def test_login_success_returns_token_and_role(api):
    resp = TestClient(api.app).post(
        "/api/auth/login",
        json={"username": "dev_admin", "password": SEED_DEFAULT_PASSWORD})
    assert resp.status_code == 200
    body = resp.json()
    assert body["role"] == "pm"
    assert body["role_label"] == "项目管理"
    assert isinstance(body["id"], int)  # #219 前端按 id 判定提交人
    assert body["token"]


def test_me_and_logout_flow(api):
    client = login_as(TestClient(api.app), "sec_admin")
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["role"] == "security_lead"

    # 换一个新 token 登出后, 原 token 不可再用
    fresh = login_as(TestClient(api.app), "sec_admin")
    assert fresh.post("/api/auth/logout").status_code == 204
    assert fresh.get("/api/auth/me").status_code == 401


def test_open_paths_anonymous_ok_business_401(api):
    anon = TestClient(api.app)
    assert anon.get("/api/health").status_code == 200
    assert anon.get("/api/meta/constants").status_code == 200
    assert anon.get("/api/projects").status_code == 401
    assert anon.post("/api/projects", json={}).status_code == 401


def test_change_password_requires_old_password(api, dev_b):
    # 改密旋转口令运行时随机生成, 测试源码不落固定口令
    rotated = "Rotated-" + uuid.uuid4().hex[:10]
    client = login_as(TestClient(api.app), "dev_b")
    bad = client.post("/api/auth/change-password", json={
        "old_password": "not-it", "new_password": rotated})
    assert bad.status_code == 400

    ok = client.post("/api/auth/change-password", json={
        "old_password": SEED_DEFAULT_PASSWORD, "new_password": rotated})
    assert ok.status_code == 200
    # 旧会话全部吊销
    assert client.get("/api/auth/me").status_code == 401
    # 新密码可登录, 旧密码不可(api 夹具每用例全新内存库, 无需恢复密码)
    assert TestClient(api.app).post("/api/auth/login", json={
        "username": "dev_b", "password": SEED_DEFAULT_PASSWORD}).status_code == 401
    assert TestClient(api.app).post("/api/auth/login", json={
        "username": "dev_b", "password": rotated}).status_code == 200


def _create_project(client: TestClient, name: str, code: str | None = None):
    from conftest import create_system_api
    sid = create_system_api(client, f"RBAC系统-{uuid.uuid4().hex[:8]}")["id"]
    payload = {"name": name, "system_id": sid}
    if code:
        payload["code"] = code
    return client.post("/api/projects", json=payload)


def test_create_project_auto_code_and_owner(api):
    dev = api_as(api, "dev_admin")
    resp = _create_project(dev, "自动编码项目")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["code"].startswith("XM")
    assert body["owner_name"] == "开发管理员"
    # 编码唯一: 第二次自动生成不冲突
    resp2 = _create_project(dev, "自动编码项目2")
    assert resp2.status_code == 201
    assert resp2.json()["code"] != body["code"]


def test_pm_sees_only_own_projects(api, dev_b):
    dev_admin = api_as(api, "dev_admin")
    other = api_as(api, dev_b)
    mine = _create_project(dev_admin, "甲的项目").json()["id"]
    theirs = _create_project(other, "乙的项目").json()["id"]

    mine_ids = {p["id"] for p in dev_admin.get("/api/projects").json()}
    other_ids = {p["id"] for p in other.get("/api/projects").json()}
    assert mine in mine_ids and theirs not in mine_ids
    assert theirs in other_ids and mine not in other_ids


def test_security_lead_sees_all_projects(api, dev_b):
    dev_admin = api_as(api, "dev_admin")
    other = api_as(api, dev_b)
    id1 = _create_project(dev_admin, "甲的项目").json()["id"]
    id2 = _create_project(other, "乙的项目").json()["id"]

    sec = api_as(api, "sec_admin")
    sec_ids = {p["id"] for p in sec.get("/api/projects").json()}
    assert {id1, id2} <= sec_ids
    assert sec.get(f"/api/projects/{id1}").status_code == 200


def test_pm_cannot_touch_others_project(api, dev_b):
    dev_admin = api_as(api, "dev_admin")
    other = api_as(api, dev_b)
    theirs = _create_project(other, "乙的项目").json()["id"]

    # 读/写/删 越权一律 404(不泄露存在性), 向导状态同理
    assert dev_admin.get(f"/api/projects/{theirs}").status_code == 404
    assert dev_admin.patch(f"/api/projects/{theirs}", json={"name": "篡改"}).status_code == 404
    assert dev_admin.delete(f"/api/projects/{theirs}").status_code == 404
    assert dev_admin.get(f"/api/projects/{theirs}/wizard-state").status_code == 404
    assert dev_admin.post(f"/api/projects/{theirs}/features", json=[]).status_code == 404
    # 安全负责人可以改
    sec = api_as(api, "sec_admin")
    assert sec.patch(f"/api/projects/{theirs}", json={"name": "安全代改"}).status_code == 200


# ── 角色权限矩阵(#216) ────────────────────────────────


def test_auditor_readonly_full_visibility(api):
    """审计员只读全量: 项目/系统全部可见, 任何写端点一律 403。"""
    sec = api_as(api, "sec_admin")
    dev_admin = api_as(api, "dev_admin")
    _create_project(dev_admin, "被审计的项目")
    client = login_as(TestClient(api.app), _create_user(sec, "auditor_a", "auditor"))

    assert client.get("/api/projects").status_code == 200
    assert client.get("/api/systems").status_code == 200
    # 写端点(业务/系统/备案/管理)一律 403
    assert client.post("/api/projects", json={"name": "x"}).status_code == 403
    assert client.post("/api/systems", json={"name": "x"}).status_code == 403
    assert client.post("/api/filings", json={"name": "x", "code": "BA-X", "level": "二级"}).status_code == 403
    assert client.post("/api/admin/users", json={
        "username": "nope", "display_name": "nope", "role": "pm"}).status_code == 403


def test_pm_blocked_from_admin_and_review_side(api):
    """pm 进系统管理 403; 评审动作端点(#218 落地)同口径拒绝。"""
    sec = api_as(api, "sec_admin")
    client = login_as(TestClient(api.app), _create_user(sec, "pm_a", "pm"))

    assert client.get("/api/admin/users").status_code == 403
    assert client.post("/api/admin/users", json={
        "username": "nope", "display_name": "nope", "role": "pm"}).status_code == 403
    assert client.get("/api/admin/audit-logs").status_code == 403


def test_review_side_roles_split(api):
    """评审员/负责人同属安全侧: 系统管理与业务写可用, 都能看全量评审队列。"""
    sec = api_as(api, "sec_admin")
    dev_admin = api_as(api, "dev_admin")
    _create_project(dev_admin, "待评审项目")

    for username, role in (("reviewer_a", "security_reviewer"), ("lead_a", "security_lead")):
        client = login_as(TestClient(api.app), _create_user(sec, username, role))
        assert client.get("/api/projects").status_code == 200
        assert client.get("/api/admin/users").status_code == 200
        # 业务写(向导/项目)可用 —— 评审动作端点的细粒度白名单在 #218 落地
        assert client.post("/api/systems", json={"name": f"系统-{username}"}).status_code == 201


def test_auditor_blocked_from_admin(api):
    """审计员连系统管理也不进(用户管理敏感)。"""
    sec = api_as(api, "sec_admin")
    client = login_as(TestClient(api.app), _create_user(sec, "auditor_b", "auditor"))
    assert client.get("/api/admin/users").status_code == 403


def test_meta_constants_expose_four_roles(api):
    roles = api.get("/api/meta/constants").json()["platform_roles"]
    assert roles == {
        "pm": "项目管理", "security_reviewer": "安全评审员",
        "security_lead": "安全负责人", "auditor": "审计员",
    }


def test_legacy_role_migration_to_four_roles(session):
    """存量库迁移(#216): developer→pm, security→security_lead, 权限不回退。"""
    from models import PlatformUser
    from services.auth_service import ensure_seed_users

    session.add_all([
        PlatformUser(username="old_dev", display_name="老开发", role="developer",
                     password_hash="legacy-hash"),
        PlatformUser(username="old_sec", display_name="老安全", role="security",
                     password_hash="legacy-hash"),
    ])
    session.flush()

    ensure_seed_users(session)

    users = {u.username: u for u in session.query(PlatformUser).all()}
    assert users["old_dev"].role == "pm" and users["old_dev"].active is True
    assert users["old_sec"].role == "security_lead" and users["old_sec"].active is True
    # 种子账号本身按新角色落库/迁移
    assert users["dev_admin"].role == "pm"
    assert users["sec_admin"].role == "security_lead"


def test_migrated_accounts_can_login(api, session=None):
    """存量 developer/security 账号升级后可正常登录(dev_admin 即存量迁移路径)。"""
    for username, role in (("dev_admin", "pm"), ("sec_admin", "security_lead")):
        resp = TestClient(api.app).post(
            "/api/auth/login", json={"username": username, "password": SEED_DEFAULT_PASSWORD})
        assert resp.status_code == 200, resp.text
        assert resp.json()["role"] == role


def test_code_conflict_still_409(api):
    dev = api_as(api, "dev_admin")
    created = _create_project(dev, "冲突项目", code="XM-CUSTOM-01")
    assert created.status_code == 201
    dup = _create_project(dev, "冲突项目2", code="XM-CUSTOM-01")
    assert dup.status_code == 409


def test_code_immutable_on_patch(api):
    dev = api_as(api, "dev_admin")
    pid = _create_project(dev, "编码保护").json()["id"]
    resp = dev.patch(f"/api/projects/{pid}", json={"code": "XM-HACK"})
    assert resp.status_code == 400
