# -*- coding: utf-8 -*-
"""备案 CSV 批量导入(DESIGN: 备案管理增加批量导入功能)。

覆盖: 中英文表头、GBK/UTF-8 解码、必填校验、定级枚举校验、名称冲突整行跳过,
以及非 CSV 后缀/缺表头的 400 拒绝。
"""
import io

from conftest import api_as


def _csv_file(content: str, filename: str = "filings.csv") -> dict:
    return {"file": (filename, io.BytesIO(content.encode("utf-8")), "text/csv")}


def test_import_csv_creates_filings(api):
    resp = api_as(api, "sec_admin").post(
        "/api/filings/import", files=_csv_file(
            "名称,定级,编号,备注\n核心业务系统,二级,BA-2026-001,2026年测评\n门户系统,三级,,\n"))
    assert resp.status_code == 201, resp.text
    assert resp.json()["created"] == 2
    assert resp.json()["skipped"] == []
    rows = api_as(api, "sec_admin").get("/api/filings").json()
    names = {r["name"]: r for r in rows}
    assert names["核心业务系统"]["level"] == "二级"
    assert names["核心业务系统"]["code"] == "BA-2026-001"
    assert names["门户系统"]["level"] == "三级"


def test_import_csv_gbk_encoded(api):
    """国内 Excel 另存的 GBK 文件可导入。"""
    payload = "名称,定级\n内网管理系统,一级\n".encode("gbk")
    resp = api_as(api, "sec_admin").post(
        "/api/filings/import",
        files={"file": ("filings.csv", io.BytesIO(payload), "text/csv")})
    assert resp.status_code == 201, resp.text
    assert resp.json()["created"] == 1


def test_import_csv_skips_invalid_rows(api):
    sec = api_as(api, "sec_admin")
    assert sec.post("/api/filings", json={
        "name": "已有系统", "level": "二级"}).status_code == 201
    resp = sec.post("/api/filings/import", files=_csv_file(
        "name,level\n,二级\n新系统,四级\n已有系统,三级\n新系统,一级\n"))
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["created"] == 1
    reasons = {s["row"]: s["reason"] for s in body["skipped"]}
    assert "名称为空" in reasons[2]
    assert "定级" in reasons[3]
    assert "已存在" in reasons[4] or "冲突" in reasons[4]
    rows = sec.get("/api/filings").json()
    kept = {r["name"]: r["level"] for r in rows}
    assert kept["已有系统"] == "二级"  # 冲突行不覆盖存量
    assert kept["新系统"] == "一级"


def test_import_csv_rejects_bad_input(api):
    sec = api_as(api, "sec_admin")
    resp = sec.post("/api/filings/import", files=_csv_file(
        "名称,定级\nx,二级\n", filename="filings.xlsx"))
    assert resp.status_code == 400
    resp = sec.post("/api/filings/import", files=_csv_file("foo,bar\n1,2\n"))
    assert resp.status_code == 400
    assert "缺少必需列" in resp.json()["detail"]


def test_import_pm_forbidden_and_audited(api):
    resp = api.post("/api/filings/import", files=_csv_file("name,level\nx,二级\n"))
    assert resp.status_code == 403
    api_as(api, "sec_admin").post(
        "/api/filings/import", files=_csv_file("name,level\n审计导入系统,三级\n"))
    rows = api_as(api, "sec_admin").get("/api/admin/audit-logs").json()
    entry = next(r for r in rows if r["action"] == "filing_import")
    assert entry["action_label"] == "批量导入备案"
    assert entry["detail"]["created"] == 1
