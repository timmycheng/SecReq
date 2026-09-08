# -*- coding: utf-8 -*-
"""清单服务端过滤分页(#283 item9): 带 page 返回 {items,total} 信封,
不带 page 保持全量列表旧口径(存量调用方零破坏)。"""
from conftest import api_as, create_system_api


def _mk_project(api, name, system_id):
    resp = api.post("/api/projects", json={"name": name, "system_id": system_id})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_projects_paginated_envelope_and_filters(api):
    sid_a = create_system_api(api, "分页系统A")["id"]
    sid_b = create_system_api(api, "分页系统B")["id"]
    _mk_project(api, "信封项目一", sid_a)
    _mk_project(api, "信封项目二", sid_a)
    _mk_project(api, "其他系统项目", sid_b)

    legacy = api.get("/api/projects").json()
    assert isinstance(legacy, list) and len(legacy) == 3  # 旧口径不变

    page1 = api.get("/api/projects", params={"page": 1, "page_size": 2}).json()
    assert page1["total"] == 3 and len(page1["items"]) == 2
    page2 = api.get("/api/projects", params={"page": 2, "page_size": 2}).json()
    assert len(page2["items"]) == 1

    by_system = api.get("/api/projects", params={"page": 1, "system_id": sid_b}).json()
    assert by_system["total"] == 1 and by_system["items"][0]["system_id"] == sid_b

    by_kw = api.get("/api/projects", params={"page": 1, "keyword": "信封"}).json()
    assert by_kw["total"] == 2

    by_status = api.get("/api/projects", params={"page": 1, "status": "draft"}).json()
    assert by_status["total"] == 3
    assert api.get("/api/projects", params={"page": 1, "status": "generated"}).json()["total"] == 0


def test_ledger_paginated_envelope_and_filters(api):
    from services.classification_migration import ensure_schema_upgrade  # noqa: F401 (启动口径已覆盖)
    sec = api_as(api, "sec_admin")
    sid_a = sec.post("/api/systems", json={
        "name": "台账A", "importance": "高", "tags": ["重要信息系统"]}).json()["id"]
    sec.post("/api/systems", json={"name": "台账B", "importance": "低"})

    legacy = sec.get("/api/systems/ledger").json()
    assert isinstance(legacy, list) and len(legacy) == 2

    page1 = sec.get("/api/systems/ledger", params={"page": 1, "page_size": 1}).json()
    assert page1["total"] == 2 and len(page1["items"]) == 1

    imp = sec.get("/api/systems/ledger", params={"page": 1, "importance": "高"}).json()
    assert imp["total"] == 1 and imp["items"][0]["id"] == sid_a

    tag = sec.get("/api/systems/ledger", params={"page": 1, "tag": "重要信息系统"}).json()
    assert tag["total"] == 1 and tag["items"][0]["id"] == sid_a

    kw = sec.get("/api/systems/ledger", params={"page": 1, "keyword": "台账B"}).json()
    assert kw["total"] == 1

