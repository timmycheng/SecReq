# -*- coding: utf-8 -*-
"""平台认证与数据权限(走查整改):

1. 登录: 账密错误 401 / 正确签发 token / 登出后 token 失效;
2. 全局认证: 无 token 访问业务接口 401(读写都拦), 开放路径放行;
3. 数据权限: 开发只见/只改自己创建的项目, 安全全量可见, 越权一律 404;
4. 项目创建: code 缺省自动生成且唯一, owner 自动写入创建人。
"""
import uuid

import pytest
from fastapi.testclient import TestClient

from conftest import api_as, login_as
from services.auth_service import SEED_DEFAULT_PASSWORD


@pytest.fixture()
def dev_b(api):
    """种子精简为 dev_admin/sec_admin 后(#63), 测试自建第二个开发账号。

    初始密码未指定时取种子默认密码, login_as 可直接登录。
    """
    sec = api_as(api, "sec_admin")
    resp = sec.post("/api/admin/users", json={
        "username": "dev_b", "display_name": "开发B", "role": "developer"})
    assert resp.status_code == 201, resp.text
    return "dev_b"


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
    assert body["role"] == "developer"
    assert body["role_label"] == "开发"
    assert body["token"]


def test_me_and_logout_flow(api):
    client = login_as(TestClient(api.app), "sec_admin")
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["role"] == "security"

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
    payload = {"name": name, "type": "web", "user_scale": "1k_to_100k"}
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


def test_developer_sees_only_own_projects(api, dev_b):
    dev_admin = api_as(api, "dev_admin")
    other = api_as(api, dev_b)
    mine = _create_project(dev_admin, "甲的项目").json()["id"]
    theirs = _create_project(other, "乙的项目").json()["id"]

    mine_ids = {p["id"] for p in dev_admin.get("/api/projects").json()}
    other_ids = {p["id"] for p in other.get("/api/projects").json()}
    assert mine in mine_ids and theirs not in mine_ids
    assert theirs in other_ids and mine not in other_ids


def test_security_sees_all_projects(api, dev_b):
    dev_admin = api_as(api, "dev_admin")
    other = api_as(api, dev_b)
    id1 = _create_project(dev_admin, "甲的项目").json()["id"]
    id2 = _create_project(other, "乙的项目").json()["id"]

    sec = api_as(api, "sec_admin")
    sec_ids = {p["id"] for p in sec.get("/api/projects").json()}
    assert {id1, id2} <= sec_ids
    assert sec.get(f"/api/projects/{id1}").status_code == 200


def test_developer_cannot_touch_others_project(api, dev_b):
    dev_admin = api_as(api, "dev_admin")
    other = api_as(api, dev_b)
    theirs = _create_project(other, "乙的项目").json()["id"]

    # 读/写/删 越权一律 404(不泄露存在性), 向导状态同理
    assert dev_admin.get(f"/api/projects/{theirs}").status_code == 404
    assert dev_admin.patch(f"/api/projects/{theirs}", json={"name": "篡改"}).status_code == 404
    assert dev_admin.delete(f"/api/projects/{theirs}").status_code == 404
    assert dev_admin.get(f"/api/projects/{theirs}/wizard-state").status_code == 404
    assert dev_admin.post(f"/api/projects/{theirs}/features", json=[]).status_code == 404
    # 安全可以改
    sec = api_as(api, "sec_admin")
    assert sec.patch(f"/api/projects/{theirs}", json={"name": "安全代改"}).status_code == 200


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
