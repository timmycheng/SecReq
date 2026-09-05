# -*- coding: utf-8 -*-
"""系统台账(定级备案/被评估系统)端点与项目归属。

覆盖: CRUD 与唯一性冲突、删除保护、数据权限(开发仅见本人系统)、
项目归属校验、当前基线动态计算、台账聚合、存量项目不受影响。
"""
import pytest

from conftest import api_as, cleanup_output, login_as


@pytest.fixture()
def dev(api):
    """开发角色客户端(conftest 默认身份即 dev_admin, 显式声明便于阅读)。"""
    return api


@pytest.fixture()
def sec(api):
    return api_as(api, "sec_admin")


def _create_filing(client, name="网银核心备案", level="三级", code="BA-001") -> dict:
    resp = client.post("/api/filings", json={"name": name, "code": code, "level": level})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_system(client, name="手机银行系统", filing_id=None, code=None, **extra) -> dict:
    resp = client.post("/api/systems", json={
        "name": name, "filing_id": filing_id, "code": code, "owner_name": "张三", **extra,
    })
    assert resp.status_code == 201, resp.text
    return resp.json()


# ── 备案 ─────────────────────────────────────────────


def test_filing_crud_and_ledger(dev, sec):
    """备案写仅安全角色(#192): 开发可读可选, 增删改 403。"""
    assert dev.post("/api/filings", json={"name": "X", "level": "二级"}).status_code == 403

    filing = _create_filing(sec)
    assert filing["level"] == "三级"

    # 开发把系统挂到安全侧维护的备案上: 读与选择不受限
    _create_system(dev, filing_id=filing["id"])
    rows = dev.get("/api/filings").json()
    assert len(rows) == 1
    assert rows[0]["system_count"] == 1

    assert dev.patch(f"/api/filings/{filing['id']}", json={"level": "二级"}).status_code == 403
    patched = sec.patch(f"/api/filings/{filing['id']}", json={"level": "二级"}).json()
    assert patched["level"] == "二级"
    assert dev.delete(f"/api/filings/{filing['id']}").status_code == 403


def test_filing_level_validated(sec):
    resp = sec.post("/api/filings", json={"name": "X", "level": "四级"})
    assert resp.status_code == 422


def test_filing_name_conflict_409(sec):
    _create_filing(sec, name="备案A")
    resp = sec.post("/api/filings", json={"name": "备案A", "level": "二级"})
    assert resp.status_code == 409


def test_filing_delete_guarded(dev, sec):
    filing = _create_filing(sec)
    _create_system(dev, filing_id=filing["id"])
    assert sec.delete(f"/api/filings/{filing['id']}").status_code == 409
    assert sec.delete("/api/filings/9999").status_code == 404
    assert dev.delete(f"/api/filings/{filing['id']}").status_code == 403


# ── 系统 ─────────────────────────────────────────────


def test_system_crud_and_detail_timeline(dev, sec):
    code = "SYS-TL"
    filing = _create_filing(sec)
    system = _create_system(dev, filing_id=filing["id"], code=code)
    assert system["filing_name"] == "网银核心备案"
    assert system["filing_level"] == "三级"

    # 项目挂到系统 → 详情时间线出现该轮, 未生成时无当前基线
    project = dev.post("/api/projects", json={
        "name": "手机银行一期", "system_id": system["id"], "code": "PRJ-SYSTL",
    }).json()
    assert project["system_id"] == system["id"]
    assert project["system_name"] == "手机银行系统"
    assert project["filing_level"] == "三级"
    assert project["is_current_baseline"] is False

    detail = dev.get(f"/api/systems/{system['id']}").json()
    assert [r["project_id"] for r in detail["rounds"]] == [project["id"]]
    assert detail["current_baseline_project_id"] is None

    try:
        resp = dev.post(f"/api/projects/{project['id']}/generate", json={"skip_osv": True})
        assert resp.status_code == 200, resp.text
        detail = dev.get(f"/api/systems/{system['id']}").json()
        assert detail["current_baseline_project_id"] == project["id"]
        ledger = sec.get("/api/systems/ledger").json()
        assert ledger[0]["latest_round"]["project_id"] == project["id"]
        assert ledger[0]["filing_level"] == "三级"
        # 项目列表标记当前基线
        projects = dev.get("/api/projects").json()
        target = next(p for p in projects if p["id"] == project["id"])
        assert target["is_current_baseline"] is True
    finally:
        cleanup_output(code)


def test_system_detail_basic_info_fields(dev):
    """#214 详情接口返回基本信息三件套(user_scale/types/is_public), 不再回落默认值。"""
    system = _create_system(
        dev, name="网银系统", code="SYS-DET",
        user_scale="1万-10万", types=["个人网银", "企业网银"], is_public=True,
    )
    detail = dev.get(f"/api/systems/{system['id']}").json()
    assert detail["user_scale"] == "1万-10万"
    assert detail["types"] == ["个人网银", "企业网银"]
    assert detail["is_public"] is True
    # 台账接口保持原口径, 不受详情补字段影响
    ledger = dev.get("/api/systems/ledger").json()
    target = next(s for s in ledger if s["id"] == system["id"])
    assert target["name"] == "网银系统"


def test_system_baseline_zone_and_histories(dev, session=None):
    """#223 安全基线 D 区: 初始空不报错; 写入基线+履历后详情可见, 履历倒序。"""
    from models import SystemBaseline, SystemBaselineHistory

    system = _create_system(dev, name="基线系统", code="SYS-BL")
    detail = dev.get(f"/api/systems/{system['id']}").json()
    assert detail["baseline"] is None            # 履历初始为空不报错
    assert detail["baseline_histories"] == []

    db = dev.session_factory()
    try:
        bl = SystemBaseline(
            system_id=system["id"],
            baseline_json={
                "data_assets": [{"uid": "asset-1", "name": "客户信息", "data_type": "database",
                                 "classification": "3级_C2主要信息", "is_pii": True,
                                 "is_sensitive_pii": False, "storage_envs": ["db"],
                                 "cross_border_transfer": False,
                                 "tables": [{"table_name": "customers", "fields": [
                                     {"field_name": "id_card", "field_type": "string",
                                      "need_encrypt": True, "need_mask": True, "mask_rule": None}]}]}],
                "roles": [{"uid": "role-1", "name": "柜员", "role_type": "internal"}],
                "resources": [{"uid": "res-1", "name": "账户接口", "resource_type": "api"}],
                "permission_entries": [{"role_uid": "role-1", "resource_uid": "res-1",
                                        "action": "read", "requires_approval": False}],
                "api_endpoints": [],  # 计数为 0 的分区同样展示
            },
            source_project_id=7, updated_by="评审员甲", summary="首轮基线写回")
        db.add(bl)
        db.flush()
        db.add(SystemBaselineHistory(
            system_id=system["id"], baseline_id=bl.id, project_id=7,
            summary="首轮基线写回: 资产 1/字典 2 表", operator_name="评审员甲"))
        db.commit()
    finally:
        db.close()

    detail = dev.get(f"/api/systems/{system['id']}").json()
    assert detail["baseline"]["summary"] == {
        "data_assets": 1, "data_tables": 1, "roles": 1, "resources": 1,
        "permission_entries": 1, "api_endpoints": 0}
    assert detail["baseline"]["source_project_id"] == 7
    assert detail["baseline"]["updated_by"] == "评审员甲"
    assert [h["summary"] for h in detail["baseline_histories"]] == ["首轮基线写回: 资产 1/字典 2 表"]


def test_system_unique_conflict_409(dev):
    _create_system(dev, name="系统A", code="SYS-A")
    assert dev.post("/api/systems", json={"name": "系统A"}).status_code == 409
    assert dev.post("/api/systems", json={"name": "系统B", "code": "SYS-A"}).status_code == 409


def test_system_delete_guarded_by_projects(dev):
    system = _create_system(dev)
    dev.post("/api/projects", json={"name": "P1", "system_id": system["id"]})
    assert dev.delete(f"/api/systems/{system['id']}").status_code == 409


def test_system_filing_must_exist(dev):
    assert dev.post("/api/systems", json={"name": "系统X", "filing_id": 999}).status_code == 409


# ── 数据权限与项目归属 ────────────────────────────────


def test_pm_sees_only_own_systems(api, sec):
    """pm 仅见本人创建的系统; 安全侧全量可见。"""
    _create_system(api, name="甲的系统")

    # 经管理端点开第二个开发账号(缺省种子口令), 以其身份再建一个系统
    resp = sec.post("/api/admin/users", json={
        "username": "dev_ledger", "display_name": "台账开发", "role": "pm"})
    assert resp.status_code == 201, resp.text
    other = login_as(api, "dev_ledger")
    _create_system(other, name="乙的系统")

    mine = api.get("/api/systems").json()
    assert [s["name"] for s in mine] == ["甲的系统"]
    everything = sec.get("/api/systems").json()
    assert {s["name"] for s in everything} == {"甲的系统", "乙的系统"}
    # 台账聚合同样按数据权限过滤
    assert [s["name"] for s in api.get("/api/systems/ledger").json()] == ["甲的系统"]


def test_project_cannot_attach_foreign_system(api, sec):
    """开发不能把项目挂到他人系统上(与台账数据权限口径一致)。"""
    filing = _create_filing(sec, name="安全侧备案")
    system = sec.post("/api/systems", json={
        "name": "安全的系统", "filing_id": filing["id"]}).json()
    resp = api.post("/api/projects", json={"name": "P", "system_id": system["id"]})
    assert resp.status_code == 400


def test_project_patch_system_required(dev):
    """#195: 评估必须归属系统, PATCH 置空被拒绝; 未显式传则不改动归属。"""
    system = _create_system(dev)
    project = dev.post("/api/projects", json={
        "name": "P", "system_id": system["id"], "code": "PRJ-DETACH"}).json()
    resp = dev.patch(f"/api/projects/{project['id']}", json={"system_id": None})
    assert resp.status_code == 400
    assert dev.get(f"/api/projects/{project['id']}").json()["system_id"] == system["id"]


def test_project_requires_system(dev):
    """#195: 创建评估必须绑定已有系统, 缺失 422。"""
    resp = dev.post("/api/projects", json={"name": "无系统项目"})
    assert resp.status_code == 422


def test_existing_projects_unaffected(session):
    """存量项目 system_id 为空即可正常工作(不强制回填)。"""
    from models import Project
    project = Project(name="遗留项目", code="PRJ-LEGACY")
    session.add(project)
    session.flush()
    assert project.system_id is None


def test_schema_upgrade_adds_system_id(tmp_path, monkeypatch):
    """存量库补列幂等: 已有 projects 表缺 system_id 时自动补齐。"""
    from sqlalchemy import create_engine, inspect
    from services.classification_migration import ensure_schema_upgrade

    engine = create_engine(f"sqlite:///{tmp_path}/legacy.db")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE projects (id INTEGER PRIMARY KEY, name VARCHAR(200))")
    added = ensure_schema_upgrade(engine)
    assert "system_id" in added.get("projects", [])
    columns = {col["name"] for col in inspect(engine).get_columns("projects")}
    assert "system_id" in columns
    assert ensure_schema_upgrade(engine) == {}  # 二次执行幂等


def test_baseline_inheritance_prefill_on_second_round(dev):
    """#224: 无基线首轮保持空白建档; 写入基线后新建轮次自动预填并可标记来源。"""
    from models import SystemBaseline

    system = _create_system(dev, name="继承系统", code="SYS-INH")
    # 首轮: 系统无基线 → 空白(行为不变)
    first = dev.post("/api/projects", json={"name": "首轮评估", "system_id": system["id"]}).json()
    ws1 = dev.get(f"/api/projects/{first['id']}/wizard-state").json()
    assert ws1["data_assets"] == [] and ws1["roles"] == [] and ws1["api_endpoints"] == []

    # 模拟 #225 写回结果: 系统持有评审通过的基线快照
    baseline_json = {
        "data_assets": [{
            "uid": "asset-inh-1", "name": "客户信息", "data_type": "database",
            "classification": "3级_C2主要信息", "is_pii": True, "is_sensitive_pii": False,
            "storage_envs": ["db"], "cross_border_transfer": False,
            "tables": [{"table_name": "customers", "fields": [
                {"field_name": "phone", "field_type": "string",
                 "need_encrypt": False, "need_mask": True, "mask_rule": None}]}],
        }],
        "roles": [{"uid": "role-inh-1", "name": "柜员", "role_type": "internal"}],
        "resources": [{"uid": "res-inh-1", "name": "账户服务", "resource_type": "api"}],
        "permission_entries": [{"role_uid": "role-inh-1", "resource_uid": "res-inh-1",
                                "action": "read", "requires_approval": False}],
        "api_endpoints": [{"uid": "api-inh-1", "name": "查询账户", "path": "/api/accounts",
                           "method": "GET", "auth_required": True, "public_exposed": False,
                           "sensitive_asset_uids": ["asset-inh-1"], "rate_limit": None}],
    }
    db = dev.session_factory()
    try:
        db.add(SystemBaseline(system_id=system["id"], baseline_json=baseline_json,
                              source_project_id=first["id"], updated_by="测试"))
        db.commit()
    finally:
        db.close()

    # 第二轮: 自动按基线预填(uid 原样保留 → 可标「基线继承」)
    second = dev.post("/api/projects", json={"name": "第二轮评估", "system_id": system["id"]}).json()
    ws2 = dev.get(f"/api/projects/{second['id']}/wizard-state").json()
    assert [a["uid"] for a in ws2["data_assets"]] == ["asset-inh-1"]
    assert ws2["data_assets"][0]["tables"][0]["fields"][0]["field_name"] == "phone"
    assert [r["uid"] for r in ws2["roles"]] == ["role-inh-1"]
    assert [(e["action"]) for e in ws2["permission_entries"]] == ["read"]
    assert [(e["uid"], e["sensitive_asset_uids"]) for e in ws2["api_endpoints"]] == [
        ("api-inh-1", ["asset-inh-1"])]

    # 前端来源标记的数据源: 系统详情基线带 uid 索引
    detail = dev.get(f"/api/systems/{system['id']}").json()
    assert detail["baseline"]["uid_index"]["data_assets"] == ["asset-inh-1"]
    assert detail["baseline"]["uid_index"]["api_endpoints"] == ["api-inh-1"]


def test_sbom_round_increment_marker(dev, sec):
    """#224 SBOM 双轨: 轮次创建后入库的组件标记为本轮增量。"""
    system = _create_system(dev, name="双轨系统", code="SYS-DUAL")
    comp_in = {"components": [{"uid": "comp-old", "layer": "library", "name": "old-lib", "version": "1.0"}]}
    resp = dev.post(f"/api/systems/{system['id']}/components", json=comp_in)
    assert resp.status_code == 200, resp.text
    project = dev.post("/api/projects", json={
        "name": "双轨评估", "system_id": system["id"]}).json()
    # 轮次创建后再入库的组件 = 本轮增量(端点为整卷 upsert, 须带全量清单)
    resp = dev.post(f"/api/systems/{system['id']}/components", json={"components": [
        {"uid": "comp-old", "layer": "library", "name": "old-lib", "version": "1.0"},
        {"layer": "library", "name": "new-lib", "version": "2.0"}]})
    assert resp.status_code == 200, resp.text
    ws = dev.get(f"/api/projects/{project['id']}/wizard-state").json()
    flags = {c["name"]: c["is_round_increment"] for c in ws["components"]}
    assert flags == {"old-lib": False, "new-lib": True}
