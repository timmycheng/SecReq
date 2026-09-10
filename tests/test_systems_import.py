# -*- coding: utf-8 -*-
"""系统批量导入(#346): 角色白名单(sys/dev/security 三管理员) + CSV 逐行校验。

仅 sys_admin/dev_admin/security_admin 可导入, pm/auditor 一律 403;
名称必填, 名称/编号冲突与枚举非法整行跳过并给可读原因, 有效行不阻塞。
"""
import io

from conftest import api_as

IMPORT_CSV = (
    "系统名称,系统编号,挂靠备案,用户规模,是否公网,业务类型,合规目标,归属部门,重要程度,标签,开发侧责任人\n"
    "手机银行系统,SYS-A,口径备案,1千-10万,是,手机APP、Web系统,等级保护、个人信息保护法,零售金融部,高,重要信息系统、人行上报,张三\n"
    "网上银行系统,SYS-B,口径备案,1千-10万,否,Web系统,等级保护,渠道部,中,,\n"
    ",SYS-C,,,,,,, ,\n"                        # 名称缺失
    "手机银行系统,SYS-D,,,,,,, ,\n"             # 与文件内重名
    "规模异常系统,SYS-E,口径备案,百万级,是,,,, ,\n"  # 用户规模非法
    "类型异常系统,SYS-F,,1千-10万,是,区块链,,, ,\n"  # 业务类型非法
    "程度异常系统,SYS-G,,1千-10万,是,,, ,超高,\n"   # 重要程度非法
    "无备案系统,SYS-H,不存在的备案,1千-10万,是,,,, ,\n"  # 备案不存在
)


def _csv(files_value: str) -> dict:
    return {"file": ("systems.csv", io.BytesIO(files_value.encode("utf-8")), "text/csv")}


def _seed_filing(client) -> int:
    resp = client.post("/api/filings", json={"name": "口径备案", "level": "三级"})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_import_forbidden_for_pm_and_auditor(api):
    """#346: pm 与审计员不可批量导入(403); pm 单建系统的权限不受影响。"""
    assert api.post("/api/systems/import", files=_csv(IMPORT_CSV)).status_code == 403
    auditor = api_as(api, "auditor")
    assert auditor.post("/api/systems/import", files=_csv(IMPORT_CSV)).status_code == 403


def test_import_allowed_roles_and_row_validation(api):
    """#346: 三管理员可导入; 有效行入库, 非法行整行跳过并给可读原因。"""
    sysa = api_as(api, "sysadmin")
    _seed_filing(sysa)

    resp = sysa.post("/api/systems/import", files=_csv(IMPORT_CSV))
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["created"] == 2
    reasons = {s["name"]: s["reason"] for s in body["skipped"]}
    assert len(body["skipped"]) == 6
    assert "名称为空" in reasons.get("", "")
    assert "重名或编号重复" in reasons.get("手机银行系统", "")
    assert "用户规模" in reasons.get("规模异常系统", "")
    assert "业务类型无法识别" in reasons.get("类型异常系统", "")
    assert "重要程度" in reasons.get("程度异常系统", "")
    assert "备案不存在" in reasons.get("无备案系统", "")

    # 入库字段核对(以开发管理员身份复核, dev_admin 全量可见)
    lead = api_as(api, "dev_lead")
    rows = {r["name"]: r for r in lead.get("/api/systems").json()}
    assert set(rows) == {"手机银行系统", "网上银行系统"}
    mobile = rows["手机银行系统"]
    assert mobile["code"] == "SYS-A"
    assert mobile["filing_name"] == "口径备案" and mobile["filing_level"] == "三级"
    assert mobile["user_scale"] == "1k_to_100k"
    assert mobile["is_public"] is True
    assert mobile["types"] == ["mobile_app", "web"]       # 中文标签归一为 code
    assert mobile["compliance_targets"] == ["djcp_l3", "pipl"]
    assert mobile["department"] == "零售金融部"
    assert mobile["importance"] == "高"
    assert mobile["tags"] == ["重要信息系统", "人行上报"]
    assert mobile["owner_dev_name"] == "张三"


def test_import_conflicts_with_existing_rows(api):
    """#346: 与库内已有名称/编号冲突的行跳过, 不阻塞其他行。"""
    sec = api_as(api, "sec_admin")
    assert sec.post("/api/systems", json={
        "name": "已有系统", "code": "SYS-EXIST"}).status_code == 201
    csv_text = (
        "系统名称,系统编号\n"
        "已有系统,SYS-NEW\n"       # 名称撞库内
        "新系统,SYS-EXIST\n"       # 编号撞库内
        "全新系统,SYS-OK\n"
    )
    resp = sec.post("/api/systems/import", files=_csv(csv_text))
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["created"] == 1
    assert len(body["skipped"]) == 2
    assert all("已存在" in s["reason"] for s in body["skipped"])


def test_import_owner_is_importer_and_audited(api):
    """#346: 导入人成为归属人(数据权限一致); 动作写审计 system_import。"""
    sec = api_as(api, "sec_admin")
    csv_text = "系统名称,系统编号\n安全侧导入系统,SYS-SEC\n"
    assert sec.post("/api/systems/import", files=_csv(csv_text)).status_code == 201

    # pm(默认 dev_admin 账号)看不到安全侧导入的系统
    assert [r["name"] for r in api.get("/api/systems").json()] == []
    # 审计留痕
    logs = sec.get("/api/admin/audit-logs").json()
    entry = next((log for log in logs if log["action"] == "system_import"), None)
    assert entry is not None and entry.get("detail", {}).get("created") == 1


def test_import_requires_csv_and_header(api):
    """#346: 非 CSV 拒绝; 缺名称列表头给可读报错。"""
    sysa = api_as(api, "sysadmin")
    resp = sysa.post("/api/systems/import",
                     files={"file": ("systems.xlsx", io.BytesIO(b"xx"),
                                     "application/vnd.ms-excel")})
    assert resp.status_code == 400
    resp = sysa.post("/api/systems/import",
                     files=_csv("编号,归属部门\nSYS-1,某部门\n"))
    assert resp.status_code == 400
    assert "系统名称" in resp.json()["detail"]
