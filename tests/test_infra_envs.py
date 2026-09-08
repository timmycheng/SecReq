# -*- coding: utf-8 -*-
"""基础资源环境可配置 + 详情页外部连接系统清单分节(#289)。

环境列表存 system_settings(infra_envs), 经 /api/meta/constants 下发,
架构图环境校验随之动态; 外部连接清单与 features 分节同口径读基线来源轮次。
"""
import pytest

from conftest import api_as, create_system_api, demo_features, satisfy_design_gate


def test_infra_envs_default_and_update(api):
    """未配置时回退默认三环境; 安全侧更新后立即生效并留审计。"""
    sec = api_as(api, "sec_admin")
    resp = sec.get("/api/admin/infra-envs")
    assert resp.status_code == 200, resp.text
    assert [e["code"] for e in resp.json()["envs"]] == ["dev", "test", "prod"]

    resp = sec.put("/api/admin/infra-envs", json={"envs": [
        {"code": "dev", "name": "开发环境"},
        {"code": "sit", "name": "SIT 环境"},
        {"code": "uat", "name": "UAT 环境"},
        {"code": "prod", "name": "生产环境"},
    ]})
    assert resp.status_code == 200, resp.text
    assert [e["code"] for e in resp.json()["envs"]] == ["dev", "sit", "uat", "prod"]

    # 枚举下发接口同步(前端卡片与基础设施卡的环境来源)
    constants = api.get("/api/meta/constants").json()
    assert constants["infra_envs"]["sit"] == "SIT 环境"

    rows = sec.get("/api/admin/audit-logs").json()
    entry = next(r for r in rows if r["action"] == "infra_envs_update")
    assert entry["action_label"] == "更新基础资源环境配置"
    assert "sit" in entry["summary"]


def test_infra_envs_validation(api):
    """非法 code/重复 code/空列表一律拒绝。"""
    sec = api_as(api, "sec_admin")
    assert sec.put("/api/admin/infra-envs", json={"envs": [
        {"code": "Bad Code", "name": "x"}]}).status_code == 422  # code 含空格/大写
    assert sec.put("/api/admin/infra-envs", json={"envs": [
        {"code": "sit", "name": "a"}, {"code": "sit", "name": "b"}]}).status_code == 400
    assert sec.put("/api/admin/infra-envs", json={"envs": []}).status_code == 422
    # 未发生任何写入, 仍为默认值
    assert [e["code"] for e in sec.get("/api/admin/infra-envs").json()["envs"]] == \
        ["dev", "test", "prod"]


def test_arch_image_env_follows_config(api):
    """架构图环境校验随配置动态: 配置了 sit 才允许上传 sit 环境架构图。"""
    sec = api_as(api, "sec_admin")
    sid = sec.post("/api/systems", json={"name": "环境系统"}).json()["id"]
    data_url = "data:image/png;base64," + "A" * 64

    assert sec.put(f"/api/systems/{sid}/arch-images/sit",
                   json={"image_data_url": data_url}).status_code == 404

    sec.put("/api/admin/infra-envs", json={"envs": [
        {"code": "sit", "name": "SIT 环境"}, {"code": "prod", "name": "生产环境"}]})
    assert sec.put(f"/api/systems/{sid}/arch-images/sit",
                   json={"image_data_url": data_url}).status_code == 200, sec.text
    rows = sec.get(f"/api/systems/{sid}/arch-images").json()
    assert [r["env"] for r in rows] == ["sit"]


@pytest.fixture()
def reviewed_baseline(api):
    """走完整评审链写回基线的系统, 返回 (system_id, project_id)。"""
    sec = api_as(api, "sec_admin")
    sec.post("/api/admin/users", json={
        "username": "ie_reviewer", "display_name": "ie_reviewer",
        "role": "security_admin"})
    sid = create_system_api(api, "外部连接系统")["id"]
    pid = api.post("/api/projects", json={"name": "外部连接项目", "system_id": sid}).json()["id"]
    resp = api.post(f"/api/projects/{pid}/features",
                    json=[f.model_dump() for f in demo_features()])
    assert resp.status_code == 200, resp.text
    assert api.post(f"/api/projects/{pid}/generate", json={"skip_osv": True}).status_code == 200
    satisfy_design_gate(api, sid, pid)
    resp = api.post(f"/api/projects/{pid}/external-systems", json=[{
        "uid": "ext-287-1", "name": "支付网关", "purpose": "支付指令转发",
        "direction": "outbound", "involves_sensitive": True,
    }])
    assert resp.status_code == 200, resp.text
    reqs = api.get(f"/api/projects/{pid}/requirements").json()
    ids = [r["req_id"] for r in reqs]
    api.post(f"/api/projects/{pid}/requirements/batch-confirm", json={"req_ids": ids})
    assert api.post(f"/api/projects/{pid}/review/submit").json()["status"] == "submitted"
    from fastapi.testclient import TestClient
    from conftest import login_as
    reviewer = login_as(TestClient(api.app), "ie_reviewer")
    for r in reqs:
        reviewer.post(f"/api/projects/{pid}/review/requirements/{r['req_id']}/annotate",
                      json={"disposition": "approve"})
    # #309 单步评审: 安全管理员裁定通过即 passed(基线写回随裁定触发)
    resp = reviewer.post(f"/api/projects/{pid}/review/decide", json={"conclusion": "approve"})
    assert resp.status_code == 200, resp.text
    return sid, pid


def test_detail_section_external_systems(api, reviewed_baseline):
    """基本信息节的外部连接清单: 读基线来源轮次; 无基线时 rows 空并带引导。"""
    sid, pid = reviewed_baseline

    rows = api.get(f"/api/systems/{sid}/detail-section?section=external_systems").json()
    assert rows["has_baseline"] is True
    assert rows["source_project_id"] == pid
    assert rows["rows"] == [{
        "uid": rows["rows"][0]["uid"], "name": "支付网关", "purpose": "支付指令转发",
        "direction": "outbound", "involves_sensitive": True,
    }]

    # 尚未评审写回的系统: 引导口径
    sid2 = create_system_api(api, "无基线系统")["id"]
    empty = api.get(f"/api/systems/{sid2}/detail-section?section=external_systems").json()
    assert empty["has_baseline"] is False and empty["rows"] == []
