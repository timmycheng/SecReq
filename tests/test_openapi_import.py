# -*- coding: utf-8 -*-
"""API 清单 OpenAPI/Swagger 规范文件导入(#227)。

JSON/YAML 均支持; 认证按 security 定义推断(操作级覆盖全局, 显式空列表=匿名);
复用 #92 两段式(解析预览不落库); 损坏文件给出可读报错行不崩溃。
"""
import json


from services.api_import import parse_openapi, parse_upload

OPENAPI_YAML = """
openapi: 3.0.0
info:
  title: demo
security:
  - bearerAuth: []
paths:
  /api/accounts:
    get:
      summary: 查询账户
    post:
      summary: 新建账户
      security: []
  /health:
    get:
      operationId: healthCheck
      security: []
  /ignored:
    parameters: []
"""

OPENAPI_JSON = json.dumps({
    "openapi": "3.0.0",
    "paths": {
        "/pets": {
            "get": {"summary": "List pets"},
            "post": {"operationId": "createPet"},
        },
    },
})

SWAGGER2_JSON = json.dumps({
    "swagger": "2.0",
    "security": [],
    "paths": {"/pets": {"get": {"summary": "List pets"}}},
})


def test_openapi_yaml_parse():
    rows = parse_openapi(OPENAPI_YAML)
    assert [r["path"] for r in rows] == ["/api/accounts", "/api/accounts", "/health"]
    # 全局 security 非空 → 需要认证; 操作级 security: [] 覆盖为匿名
    assert rows[0]["auth_required"] is True
    assert rows[1]["auth_required"] is False
    # 名称取 summary 优先, 回落 operationId
    assert rows[0]["name"] == "查询账户"
    assert rows[2]["name"] == "healthCheck"
    assert all(r["method"] in ("GET", "POST") for r in rows)


def test_openapi_json_and_swagger2():
    rows = parse_openapi(OPENAPI_JSON)
    assert [(r["path"], r["method"]) for r in rows] == [
        ("/pets", "GET"), ("/pets", "POST")]

    # Swagger2 全局 security: [] → 默认匿名
    rows = parse_openapi(SWAGGER2_JSON)
    assert rows[0]["auth_required"] is False


def test_parse_upload_dispatches_by_extension():
    assert parse_upload("openapi.yaml", OPENAPI_YAML.encode())[0]["path"] == "/api/accounts"
    assert parse_upload("openapi.json", OPENAPI_JSON.encode())[0]["path"] == "/pets"


def test_broken_spec_returns_error_row():
    """损坏/非规范文件: 返回带 error 的单行, 不崩溃。"""
    rows = parse_upload("api.json", b"{not json")
    assert len(rows) == 1 and rows[0]["error"]

    rows = parse_upload("api.yaml", b"just: some\n")
    assert len(rows) == 1 and "OpenAPI/Swagger" in rows[0]["error"]


def test_parse_endpoint_roundtrip(api):
    """两段式第一段: 规范文件上传 → 预览行; 不落库。"""
    sid_resp = api.post("/api/systems", json={"name": "OpenAPI系统"})
    assert sid_resp.status_code == 201, sid_resp.text
    pid = api.post("/api/projects", json={
        "name": "OpenAPI项目", "system_id": sid_resp.json()["id"]}).json()["id"]
    resp = api.post(f"/api/projects/{pid}/api-endpoints/parse",
                    files={"file": ("openapi.yaml", OPENAPI_YAML.encode(), "application/yaml")})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 3 and body["invalid"] == 0
    assert {r["path"] for r in body["rows"]} == {"/api/accounts", "/health"}
