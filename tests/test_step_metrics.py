# -*- coding: utf-8 -*-
"""步骤级耗时埋点与报表(#229): 保存端点上报落库, 报表输出平均/中位/P90。"""

from conftest import api_as, create_system_api


def _mk_project(api) -> int:
    sid = create_system_api(api, "埋点系统")["id"]
    return api.post("/api/projects", json={"name": "埋点项目", "system_id": sid}).json()["id"]


def test_save_endpoint_records_duration(api):
    """保存端点带 duration_seconds → 落库; 不带 → 不落库; 异常值忽略。"""
    pid = _mk_project(api)
    resp = api.post(f"/api/projects/{pid}/features?duration_seconds=125",
                    json=[{"name": "登录", "module": "用户中心", "categories": ["auth_login"]}])
    assert resp.status_code == 200, resp.text
    # 异常值(负数/超大)被忽略
    resp = api.post(f"/api/projects/{pid}/features?duration_seconds=-5",
                    json=[{"name": "转账", "module": "支付", "categories": ["payment"],
                           "sensitivity": "confidential", "involves_payment": True}])
    assert resp.status_code == 200, resp.text

    sec = api_as(api, "sec_admin")
    report = sec.get("/api/admin/step-metrics", params={"project_id": pid}).json()
    by_step = {s["step"]: s for s in report["steps"]}
    assert by_step["features"]["samples"] == 1
    assert by_step["features"]["avg_seconds"] == 125.0


def test_report_aggregates_median_p90(api):
    """报表: 多样本输出 平均/中位/P90; 无数据时空步骤列表。"""
    sec = api_as(api, "sec_admin")
    empty = sec.get("/api/admin/step-metrics").json()
    assert empty["steps"] == []

    pid = _mk_project(api)
    for i, seconds in enumerate((60, 120, 180, 240, 300)):
        resp = api.post(f"/api/projects/{pid}/api-endpoints?duration_seconds={seconds}",
                        json=[])
        assert resp.status_code == 200, resp.text

    report = sec.get("/api/admin/step-metrics", params={"project_id": pid}).json()
    assert len(report["steps"]) == 1
    step = report["steps"][0]
    assert step["step"] == "api_endpoints" and step["samples"] == 5
    assert step["avg_seconds"] == 180.0
    assert step["median_seconds"] == 180.0
    assert step["p90_seconds"] == 300.0
    assert report["rounds_covered"] == 1


def test_report_requires_security_role(api):
    pid = _mk_project(api)
    assert api.get("/api/admin/step-metrics").status_code == 403
