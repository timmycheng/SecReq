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


def _create_system(client, name="手机银行系统", filing_id=None, code=None) -> dict:
    resp = client.post("/api/systems", json={
        "name": name, "filing_id": filing_id, "code": code, "owner_name": "张三",
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


def test_developer_sees_only_own_systems(api, sec):
    """开发仅见本人创建的系统; 安全全量可见。"""
    _create_system(api, name="甲的系统")

    # 经管理端点开第二个开发账号(缺省种子口令), 以其身份再建一个系统
    resp = sec.post("/api/admin/users", json={
        "username": "dev_ledger", "display_name": "台账开发", "role": "developer"})
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
