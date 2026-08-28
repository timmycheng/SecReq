# -*- coding: utf-8 -*-
"""平台认证与数据权限(走查整改):

1. 登录: 账密错误 401 / 正确签发 token / 登出后 token 失效;
2. 全局认证: 无 token 访问业务接口 401(读写都拦), 开放路径放行;
3. 数据权限: 开发只见/只改自己创建的项目, 安全全量可见, 越权一律 404;
4. 项目创建: code 缺省自动生成且唯一, owner 自动写入创建人。
"""
from fastapi.testclient import TestClient

from conftest import api_as, login_as
from services.auth_service import SEED_DEFAULT_PASSWORD


def test_login_wrong_password_401(api):
    client = TestClient(api.app)
    resp = client.post(
        "/api/auth/login", json={"username": "dev_li", "password": "wrong"})
    assert resp.status_code == 401


def test_login_unknown_user_401(api):
    client = TestClient(api.app)
    resp = client.post(
        "/api/auth/login", json={"username": "nobody", "password": "x"})
    assert resp.status_code == 401


def test_login_success_returns_token_and_role(api):
    resp = TestClient(api.app).post(
        "/api/auth/login",
        json={"username": "dev_li", "password": SEED_DEFAULT_PASSWORD})
    assert resp.status_code == 200
    body = resp.json()
    assert body["role"] == "developer"
    assert body["role_label"] == "开发"
    assert body["token"]


def test_me_and_logout_flow(api):
    client = login_as(TestClient(api.app), "sec_chen")
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["role"] == "security"

    # 换一个新 token 登出后, 原 token 不可再用
    fresh = login_as(TestClient(api.app), "sec_chen")
    assert fresh.post("/api/auth/logout").status_code == 204
    assert fresh.get("/api/auth/me").status_code == 401


def test_open_paths_anonymous_ok_business_401(api):
    anon = TestClient(api.app)
    assert anon.get("/api/health").status_code == 200
    assert anon.get("/api/meta/constants").status_code == 200
    assert anon.get("/api/projects").status_code == 401
    assert anon.post("/api/projects", json={}).status_code == 401


def test_change_password_requires_old_password(api):
    client = login_as(TestClient(api.app), "dev_zhang")
    bad = client.post("/api/auth/change-password", json={
        "old_password": "not-it", "new_password": "NewPass12345"})
    assert bad.status_code == 400

    ok = client.post("/api/auth/change-password", json={
        "old_password": SEED_DEFAULT_PASSWORD, "new_password": "NewPass12345"})
    assert ok.status_code == 200
    # 旧会话全部吊销
    assert client.get("/api/auth/me").status_code == 401
    # 新密码可登录, 旧密码不可
    assert TestClient(api.app).post("/api/auth/login", json={
        "username": "dev_zhang", "password": SEED_DEFAULT_PASSWORD}).status_code == 401
    restore_client = TestClient(api.app)
    login_resp = restore_client.post("/api/auth/login", json={
        "username": "dev_zhang", "password": "NewPass12345"})
    assert login_resp.status_code == 200
    restore = TestClient(restore_client.app, headers={
        "Authorization": f"Bearer {login_resp.json()['token']}"})
    # 恢复默认密码, 避免影响其他用例
    assert restore.post("/api/auth/change-password", json={
        "old_password": "NewPass12345", "new_password": SEED_DEFAULT_PASSWORD}).status_code == 200


def _create_project(client: TestClient, name: str, code: str | None = None):
    payload = {"name": name, "type": "web", "user_scale": "1k_to_100k"}
    if code:
        payload["code"] = code
    return client.post("/api/projects", json=payload)


def test_create_project_auto_code_and_owner(api):
    dev = api_as(api, "dev_li")
    resp = _create_project(dev, "自动编码项目")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["code"].startswith("XM")
    assert body["owner_name"] == "李开发"
    # 编码唯一: 第二次自动生成不冲突
    resp2 = _create_project(dev, "自动编码项目2")
    assert resp2.status_code == 201
    assert resp2.json()["code"] != body["code"]


def test_developer_sees_only_own_projects(api):
    dev_li = api_as(api, "dev_li")
    dev_zhang = api_as(api, "dev_zhang")
    mine = _create_project(dev_li, "李的项目").json()["id"]
    theirs = _create_project(dev_zhang, "张的项目").json()["id"]

    li_ids = {p["id"] for p in dev_li.get("/api/projects").json()}
    zhang_ids = {p["id"] for p in dev_zhang.get("/api/projects").json()}
    assert mine in li_ids and theirs not in li_ids
    assert theirs in zhang_ids and mine not in zhang_ids


def test_security_sees_all_projects(api):
    dev_li = api_as(api, "dev_li")
    dev_zhang = api_as(api, "dev_zhang")
    id1 = _create_project(dev_li, "李的项目").json()["id"]
    id2 = _create_project(dev_zhang, "张的项目").json()["id"]

    sec = api_as(api, "sec_chen")
    sec_ids = {p["id"] for p in sec.get("/api/projects").json()}
    assert {id1, id2} <= sec_ids
    assert sec.get(f"/api/projects/{id1}").status_code == 200


def test_developer_cannot_touch_others_project(api):
    dev_li = api_as(api, "dev_li")
    dev_zhang = api_as(api, "dev_zhang")
    theirs = _create_project(dev_zhang, "张的项目").json()["id"]

    # 读/写/删 越权一律 404(不泄露存在性), 向导状态同理
    assert dev_li.get(f"/api/projects/{theirs}").status_code == 404
    assert dev_li.patch(f"/api/projects/{theirs}", json={"name": "篡改"}).status_code == 404
    assert dev_li.delete(f"/api/projects/{theirs}").status_code == 404
    assert dev_li.get(f"/api/projects/{theirs}/wizard-state").status_code == 404
    assert dev_li.post(f"/api/projects/{theirs}/features", json=[]).status_code == 404
    # 安全可以改
    sec = api_as(api, "sec_chen")
    assert sec.patch(f"/api/projects/{theirs}", json={"name": "安全代改"}).status_code == 200


def test_code_conflict_still_409(api):
    dev = api_as(api, "dev_li")
    created = _create_project(dev, "冲突项目", code="XM-CUSTOM-01")
    assert created.status_code == 201
    dup = _create_project(dev, "冲突项目2", code="XM-CUSTOM-01")
    assert dup.status_code == 409


def test_code_immutable_on_patch(api):
    dev = api_as(api, "dev_li")
    pid = _create_project(dev, "编码保护").json()["id"]
    resp = dev.patch(f"/api/projects/{pid}", json={"code": "XM-HACK"})
    assert resp.status_code == 400
