# -*- coding: utf-8 -*-
"""obsolete 需求口径统一(#326): 评审通过/差异对比/导出统计一致排除失效需求。"""
import io
import zipfile
from types import SimpleNamespace

import pytest

from conftest import api_as, create_system_api, demo_features, login_as
from services.requirement_diff import find_previous_round
from services.review_sheet_export import build_review_sheet_docx


def _client(api, username):
    from fastapi.testclient import TestClient
    return login_as(TestClient(api.app), username)


def _save_features(api, pid, feats):
    resp = api.post(f"/api/projects/{pid}/features",
                    json=[f.model_dump() for f in feats])
    assert resp.status_code == 200, resp.text


def _saved_features(api, pid, drop_name=None):
    """读回已保存功能行(带 uid), 可按名称剔除一行后原样回传。"""
    rows = api.get(f"/api/projects/{pid}/features").json()
    return [r for r in rows if r["name"] != drop_name]


def _save_features_raw(api, pid, rows):
    resp = api.post(f"/api/projects/{pid}/features", json=rows)
    assert resp.status_code == 200, resp.text


def _generate(api, pid):
    resp = api.post(f"/api/projects/{pid}/generate", json={"skip_osv": True})
    assert resp.status_code == 200, resp.text


def _confirm_all(api, pid, reqs):
    resp = api.post(f"/api/projects/{pid}/requirements/batch-confirm",
                    json={"req_ids": [r["req_id"] for r in reqs]})
    assert resp.status_code == 200, resp.text


@pytest.fixture()
def confirmed_then_obsolete(api):
    """先生成并全部确认, 再删除「登录」重生成 → 一条已确认的 obsolete 行。"""
    sid = create_system_api(api, "口径系统")["id"]
    pid = api.post("/api/projects", json={
        "name": "口径项目", "system_id": sid}).json()["id"]
    _save_features(api, pid, demo_features())
    _generate(api, pid)
    reqs_v1 = api.get(f"/api/projects/{pid}/requirements").json()
    _confirm_all(api, pid, reqs_v1)

    # 生成过后保存必须带 uid(防漂移守卫): 读回原样回传, 仅剔除「登录」
    _save_features_raw(api, pid, _saved_features(api, pid, drop_name="登录"))
    _generate(api, pid)

    reqs = api.get(f"/api/projects/{pid}/requirements").json()
    obsolete = [r for r in reqs if r["status"] == "obsolete"]
    assert obsolete and all(r["review_status"] == "confirmed" for r in obsolete), \
        "前置条件: 被移除输入的需求应保持已确认的 obsolete 行"
    return pid, reqs, obsolete


@pytest.fixture()
def reviewers(api):
    sec = api_as(api, "sec_admin")
    resp = sec.post("/api/admin/users", json={
        "username": "sema_u", "display_name": "评审安全", "role": "security_admin"})
    assert resp.status_code == 201, resp.text
    return True


def test_obsolete_not_pushed_to_reviewed_on_approve(api, confirmed_then_obsolete, reviewers):
    """裁定通过只落盘有效需求(#326): obsolete 行不得被推成 reviewed。"""
    pid, reqs, obsolete = confirmed_then_obsolete
    active = [r for r in reqs if r["status"] != "obsolete"]
    assert active

    from conftest import satisfy_design_gate
    sid = api.get(f"/api/projects/{pid}").json()["system_id"]
    satisfy_design_gate(api, sid, pid)

    assert api.post(f"/api/projects/{pid}/review/submit").json()["status"] == "submitted"
    seca = _client(api, "sema_u")
    resp = seca.post(f"/api/projects/{pid}/review/decide",
                     json={"conclusion": "approve"})
    assert resp.status_code == 200, resp.text

    after = {r["req_id"]: r
             for r in api.get(f"/api/projects/{pid}/requirements").json()}
    for r in active:
        assert after[r["req_id"]]["review_status"] == "reviewed"
    for r in obsolete:
        assert after[r["req_id"]]["review_status"] == "confirmed", \
            f"obsolete 行 {r['req_id']} 被推成 {after[r['req_id']]['review_status']}"


def test_sorted_requirements_exclude_obsolete(api, confirmed_then_obsolete):
    """导出链路口径(#326): _sorted_requirements 不再产出 obsolete 行。"""
    pid, _, _ = confirmed_then_obsolete
    from routers.generate import _sorted_requirements
    db = api.session_factory()
    try:
        rows = _sorted_requirements(db, pid)
    finally:
        db.close()
    assert rows
    assert all(r.status != "obsolete" for r in rows)


def test_diff_counts_obsolete_as_removed(api):
    """差异对比口径(#326): 本轮 obsolete 归入 removed, total 不再计入。"""
    sid = create_system_api(api, "差异系统")["id"]
    p1 = api.post("/api/projects", json={
        "name": "第一轮", "system_id": sid}).json()["id"]
    feats = demo_features()
    _save_features(api, p1, feats)
    _generate(api, p1)

    p2 = api.post("/api/projects", json={
        "name": "第二轮", "system_id": sid, "from_project_id": p1}).json()["id"]
    # 第二轮先原样生成一次, 再剔除「登录」重新生成 → 产生 obsolete 行
    _generate(api, p2)
    _save_features_raw(api, p2, _saved_features(api, p2, drop_name="登录"))
    _generate(api, p2)

    data = api.get(f"/api/projects/{p2}/requirements/diff").json()
    removed_ids = {r["req_id"] for r in data["removed"]}
    reqs = api.get(f"/api/projects/{p2}/requirements").json()
    obsolete_ids = {r["req_id"] for r in reqs if r["status"] == "obsolete"}
    assert obsolete_ids
    assert obsolete_ids <= removed_ids, \
        f"本轮移除未体现: obsolete={obsolete_ids} removed={removed_ids}"
    assert data["summary"]["current_total"] == len(reqs) - len(obsolete_ids)
    assert data["summary"]["added"] == 0


def test_diff_against_rejects_draft_or_later_round(api):
    """显式 against 只认已生成且早于本轮(#326), 防止 diff 方向反转。"""
    sid = create_system_api(api, "基准系统")["id"]
    p1 = api.post("/api/projects", json={
        "name": "第一轮", "system_id": sid}).json()["id"]
    _save_features(api, p1, demo_features())
    _generate(api, p1)

    p2 = api.post("/api/projects", json={
        "name": "第二轮", "system_id": sid, "from_project_id": p1}).json()["id"]
    _save_features(api, p2, demo_features())
    _generate(api, p2)

    p3_draft = api.post("/api/projects", json={
        "name": "草稿轮", "system_id": sid, "from_project_id": p1}).json()["id"]

    db = api.session_factory()
    try:
        from models import Project
        current = db.get(Project, p2)
        assert find_previous_round(db, current, against=p3_draft) is None, \
            "草稿轮不能作为对比基准"
        assert find_previous_round(db, current, against=p1) is not None
        # 更晚轮次不能作为基准
        later = db.get(Project, p2)
        earlier = db.get(Project, p1)
        assert find_previous_round(db, earlier, against=later.id) is None
    finally:
        db.close()


def test_review_sheet_summary_includes_invalid_row():
    """评审表统计补「不属实」行(#326): 总数与正文明细口径一致。"""
    project = SimpleNamespace(name="口径项目", code="PRJ-TEST")
    content = build_review_sheet_docx(
        project, None,
        {"open": 1, "confirmed": 2, "reviewed": 3, "rectifying": 0, "invalid": 4},
        [], True, None)
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
    assert "不属实: 4 条" in xml
    assert "需求总数: 10 条" in xml
