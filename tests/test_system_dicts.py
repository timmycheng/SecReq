# -*- coding: utf-8 -*-
"""系统清单画像字段(#283 item1/2)与系统字典设置(标签/类型枚举)。

字段: 归属部门/重要程度/三方责任人/标签 上 System 模型, 存量库由
ensure_schema_upgrade 补列; 字典存 system_settings(system_dicts),
types 未配置回退内置 PROJECT_TYPES 并经 /api/meta/constants 下发。
"""
from sqlalchemy import create_engine, inspect as sa_inspect, text

from conftest import api_as


def test_system_profile_fields_roundtrip(api):
    """新建/编辑携带 画像字段, 详情与清单原样返回。"""
    resp = api.post("/api/systems", json={
        "name": "画像系统",
        "department": "个人金融部",
        "importance": "高",
        "owner_dev_name": "张三",
        "owner_ops_name": "李四",
        "owner_biz_name": "王五",
        "tags": ["重要信息系统", "人行上报"],
    })
    assert resp.status_code == 201, resp.text
    sid = resp.json()["id"]

    detail = api.get(f"/api/systems/{sid}").json()
    assert detail["department"] == "个人金融部"
    assert detail["importance"] == "高"
    assert (detail["tags"] == ["重要信息系统", "人行上报"])
    assert detail["owner_dev_name"] == "张三" and detail["owner_ops_name"] == "李四"
    assert detail["owner_biz_name"] == "王五"

    ledger = api.get("/api/systems/ledger").json()
    row = next(r for r in ledger if r["id"] == sid)
    assert row["importance"] == "高" and row["department"] == "个人金融部"

    resp = api.patch(f"/api/systems/{sid}", json={"importance": "低", "tags": []})
    assert resp.status_code == 200, resp.text
    assert api.get(f"/api/systems/{sid}").json()["importance"] == "低"


def test_system_importance_validation(api):
    """重要程度必须是 高/中/低。"""
    assert api.post("/api/systems", json={
        "name": "坏画像", "importance": "超级重要"}).status_code == 422
    assert api.post("/api/systems", json={
        "name": "好画像", "importance": "中"}).status_code == 201


def test_system_dicts_default_and_update(api):
    """默认标签回退 + 类型回退内置枚举; 更新后经 constants 下发并留审计。"""
    sec = api_as(api, "sec_admin")
    dicts = sec.get("/api/admin/system-dicts").json()
    assert dicts["tags"] == ["重要信息系统", "人行上报"]
    assert dicts["types"]["web"] == "Web系统"

    resp = sec.put("/api/admin/system-dicts", json={
        "tags": ["重要信息系统", "人行上报", "外联单位"],
        "types": [
            {"code": "web", "label": "Web系统"},
            {"code": "biz_platform", "label": "业务平台"},
        ]})
    assert resp.status_code == 200, resp.text

    constants = api.get("/api/meta/constants").json()
    assert constants["project_types"]["biz_platform"] == "业务平台"
    assert "外联单位" in constants["system_tags"]

    rows = sec.get("/api/admin/audit-logs").json()
    entry = next(r for r in rows if r["action"] == "system_dicts_update")
    assert entry["action_label"] == "更新系统字典"

    # 系统表单可选用新类型 code
    resp = api.post("/api/systems", json={"name": "新类型系统", "types": ["biz_platform"]})
    assert resp.status_code == 201


def test_system_dicts_validation(api):
    """清空类型枚举 400; 空 tag 项被剔除。"""
    sec = api_as(api, "sec_admin")
    assert sec.put("/api/admin/system-dicts", json={
        "tags": [], "types": []}).status_code == 400
    resp = sec.put("/api/admin/system-dicts", json={
        "tags": ["  ", "外联"], "types": [{"code": "web", "label": "Web系统"}]})
    assert resp.status_code == 200
    assert resp.json()["tags"] == ["外联"]


def test_system_dicts_pm_forbidden(api):
    assert api.get("/api/admin/system-dicts").status_code == 403


def test_schema_upgrade_adds_profile_columns():
    """存量老库 systems 表补齐画像列(幂等)。"""
    from models.database import init_db
    from services.classification_migration import ensure_schema_upgrade

    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE systems (id INTEGER PRIMARY KEY AUTOINCREMENT, name VARCHAR(200))"))
    report = ensure_schema_upgrade(engine)
    added = set(report.get("systems", []))
    assert {"department", "importance", "owner_dev_name",
            "owner_ops_name", "owner_biz_name", "tags"} <= added
    cols = {c["name"] for c in sa_inspect(engine).get_columns("systems")}
    assert "importance" in cols and "tags" in cols
    # 幂等: 再跑一遍不再新增
    assert not ensure_schema_upgrade(engine).get("systems")
    init_db(engine)
