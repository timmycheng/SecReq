# -*- coding: utf-8 -*-
"""就地复制(copy-from)与一键清空(reset-wizard)测试(#172)。

copy-from = 先清后拷(整卷替换语义): 重复复制不叠加脏数据;
reset-wizard = 清空全部向导输入回到空白模板, 生成产出不动。
"""
from conftest import add_base_project, api_as, create_system_api  # noqa: F401 — 服务层用例/夹具复用
import pytest


@pytest.fixture()
def sec(api):
    """安全角色客户端(与 test_admin 同口径)。"""
    return api_as(api, "sec_admin")


def _create_project(api, name: str, system_id: int | None = None) -> int:
    body = {"name": name}
    if system_id is not None:
        body["system_id"] = system_id
    return api.post("/api/projects", json=body).json()["id"]


@pytest.fixture()
def bound_projects(api):
    """同一系统下的两个评估(清单挂系统共享, #194)。"""
    system = create_system_api(api, "重置流程系统")
    sid = system["id"]

    def make(name: str) -> int:
        return _create_project(api, name, system_id=sid)
    return make


def _seed_inputs(api, pid: int) -> None:
    assert api.post(f"/api/projects/{pid}/features", json=[
        {"name": "转账汇款", "module": "支付模块"},
        {"name": "账单查询", "module": "查询模块"},
    ]).status_code == 200
    assert api.post(f"/api/projects/{pid}/infra-assets", json={
        "assets": [{"asset_type": "server", "name": "app-01", "env": "prod", "quantity": 2}],
    }).status_code == 200
    assert api.post(f"/api/projects/{pid}/external-systems", json=[
        {"name": "核心系统", "purpose": "账务", "direction": "bidirectional",
         "involves_sensitive": True},
    ]).status_code == 200


def test_copy_from_replaces_not_appends(api, bound_projects):
    """复制到已落库项目: 先清后拷 —— 重复复制不因 uid 相同叠加成双份。"""
    src = bound_projects("来源评估")
    _seed_inputs(api, src)
    dst = bound_projects("目标评估")

    first = api.post(f"/api/projects/{dst}/copy-from", json={"from_project_id": src})
    assert first.status_code == 200, first.text
    features = api.get(f"/api/projects/{dst}/features").json()
    assert [f["name"] for f in features] == ["转账汇款", "账单查询"]
    assert all(f["uid"] for f in features)

    # 再次复制: uid 相同但先清后拷, 不叠加
    api.post(f"/api/projects/{dst}/copy-from", json={"from_project_id": src})
    features_again = api.get(f"/api/projects/{dst}/features").json()
    assert len(features_again) == 2
    assert {f["uid"] for f in features_again} == {f["uid"] for f in features}

    # 其它步骤同样整卷到达
    assets = api.get(f"/api/projects/{dst}/infra-assets").json()
    assert [a["name"] for a in assets] == ["app-01"]
    exts = api.get(f"/api/projects/{dst}/external-systems").json()
    assert [e["name"] for e in exts] == ["核心系统"]


def test_copy_from_overwrites_existing_inputs(api, bound_projects):
    """目标项目已有输入 → 复制后完全被来源覆盖, 不残留。"""
    src = bound_projects("来源")
    _seed_inputs(api, src)
    dst = bound_projects("目标")
    assert api.post(f"/api/projects/{dst}/features", json=[
        {"name": "旧功能"}, {"name": "旧功能2"}, {"name": "旧功能3"},
    ]).status_code == 200

    resp = api.post(f"/api/projects/{dst}/copy-from", json={"from_project_id": src})
    assert resp.status_code == 200
    features = api.get(f"/api/projects/{dst}/features").json()
    assert [f["name"] for f in features] == ["转账汇款", "账单查询"]


def test_copy_from_guards(api):
    """自身复制 400; 来源/目标不存在 404。"""
    pid = _create_project(api, "某评估")
    self_copy = api.post(f"/api/projects/{pid}/copy-from", json={"from_project_id": pid})
    assert self_copy.status_code == 400

    missing = api.post(f"/api/projects/{pid}/copy-from", json={"from_project_id": 99999})
    assert missing.status_code == 404
    missing_target = api.post("/api/projects/99999/copy-from",
                              json={"from_project_id": pid})
    assert missing_target.status_code == 404


def test_reset_wizard_clears_all_inputs(api, bound_projects):
    """一键清空: 轮次步骤输入清空; 系统清单(#194)不受影响; 保存链路正常。"""
    pid = bound_projects("待清空评估")
    _seed_inputs(api, pid)

    resp = api.post(f"/api/projects/{pid}/reset-wizard")
    assert resp.status_code == 200

    assert api.get(f"/api/projects/{pid}/features").json() == []
    assert api.get(f"/api/projects/{pid}/external-systems").json() == []
    # 基础设施挂系统共享: 一键清空不清系统清单
    assert [a["name"] for a in api.get(f"/api/projects/{pid}/infra-assets").json()] == ["app-01"]

    # 清空后保存链路正常: 重新写入功能清单
    saved = api.post(f"/api/projects/{pid}/features", json=[{"name": "新功能"}])
    assert saved.status_code == 200
    assert [f["name"] for f in api.get(f"/api/projects/{pid}/features").json()] == ["新功能"]


def test_copy_and_reset_audited(api, sec, bound_projects):
    """copy-from 与 reset-wizard 都有审计留痕(以安全角色操作)。"""
    src = bound_projects("审计来源")
    _seed_inputs(api, src)
    dst = bound_projects("审计目标")
    assert sec.post(f"/api/projects/{dst}/copy-from", json={"from_project_id": src}).status_code == 200
    assert sec.post(f"/api/projects/{dst}/reset-wizard").status_code == 200

    logs = sec.get("/api/admin/audit-logs").json()
    actions = {log["action"] for log in logs}
    assert {"project_copy_from", "project_reset_wizard"} <= actions
