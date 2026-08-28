# -*- coding: utf-8 -*-
"""API 全流程测试: 向导各步骤保存 → 干跑预览 → 全量生成 → 文档/Excel/SBOM 下载。"""
import json
import shutil
from pathlib import Path

CYCLONE_MIN = {
    "bomFormat": "CycloneDX", "specVersion": "1.5",
    "components": [
        {"type": "library", "name": "minio-py", "version": "7.1.0",
         "purl": "pkg:pypi/minio@7.1.0", "licenses": [{"license": {"id": "Apache-2.0"}}]},
        {"type": "library", "name": "minio-py", "version": "7.1.2"},
    ],
}

SURVEY_ANSWERS = [
    {"question_id": qid, "option_id": oid}
    for qid, oid in [("Q1", "C"), ("Q2", "C"), ("Q3", "C"), ("Q4", "D"), ("Q5", "B")]
]


def _cleanup_output(code):
    out_dir = Path(__file__).resolve().parent.parent / "output" / code
    shutil.rmtree(out_dir, ignore_errors=True)


def test_meta_constants_and_questions(api):
    resp = api.get("/api/meta/constants")
    assert resp.status_code == 200
    consts = resp.json()
    assert consts["project_types"]["web"] == "Web系统"
    assert consts["default_pwd_policy_by_level"]["三级"]["pwd_min_length"] == 10

    resp = api.get("/api/meta/grading-questions")
    questions = resp.json()["questions"]
    assert len(questions) == 5
    assert all(q["options"] for q in questions)


def test_duplicate_project_code_conflict(api):
    body = {"name": "A", "code": "PRJ-DUP", "type": "web", "user_scale": "under_1k"}
    assert api.post("/api/projects", json=body).status_code == 201
    assert api.post("/api/projects", json=body).status_code == 409


def test_full_wizard_flow_and_generate_offline(api):
    code = "PRJ-E2E-T1"
    _cleanup_output(code)
    try:
        # ── Step1 创建 ──
        resp = api.post("/api/projects", json={
            "name": "API端到端测试项目", "code": code, "type": "web",
            "user_scale": "over_1m", "deploy_env": ["private_cloud"],
            "is_public": True,
            "compliance_targets": ["djcp_l3", "pipl"],
            "pm_name": "测试经理",
        })
        assert resp.status_code == 201, resp.text
        pid = resp.json()["id"]
        detail = api.get(f"/api/projects/{pid}").json()
        assert detail["counts"] == {
            "features": 0, "data_assets": 0, "roles": 0, "resources": 0,
            "permission_entries": 0, "components": 0, "api_endpoints": 0,
            "infra_assets": 0, "requirements": 0, "vulnerabilities": 0,
        }

        # 未生成前导出应被拦截(409)
        assert api.get(f"/api/projects/{pid}/export/xlsx").status_code == 409

        # ── Step2 问卷 ──
        resp = api.post(f"/api/projects/{pid}/survey",
                        json={"answers": SURVEY_ANSWERS})
        assert resp.status_code == 200, resp.text
        survey = resp.json()
        assert survey["suggested_level"] == "三级"
        assert survey["effective_level"] == "三级"
        assert survey["total_score"] == 17

        # 人工修正覆写最终定级
        resp = api.post(f"/api/projects/{pid}/survey", json={
            "answers": SURVEY_ANSWERS, "final_level": "二级", "manual_adjust_note": "试点范围有限"})
        assert resp.json()["effective_level"] == "二级"

        # ── Step3 功能清单 ──
        features = [
            {"name": "文件上传", "module": "公共", "categories": ["file_upload"],
             "sensitivity": "internal", "involves_payment": False,
             "exposed_to_internet": True},
            {"name": "转账支付", "categories": ["payment"], "involves_payment": True},
            {"name": "报表导出", "categories": ["export_data"]},
        ]
        resp = api.post(f"/api/projects/{pid}/features", json=features)
        assert resp.status_code == 200, resp.text
        saved_features = resp.json()
        assert [f["id"] for f in saved_features] == [1, 2, 3]
        # 整体替换幂等: 再存一次仍是 3 行且 id 重排后仍连续
        resp = api.post(f"/api/projects/{pid}/features", json=features[:1])
        assert [f["id"] for f in resp.json()] == [1]

        # ── Step4 数据字典 ──
        assets = [{
            "name": "客户账户信息", "data_type": "financial_account",
            "classification": "机密", "is_pii": True, "is_sensitive_pii": True,
            "storage_envs": ["db"],
            "tables": [{"table_name": "t_account", "fields": [
                {"field_name": "card_no", "field_type": "varchar(32)",
                 "need_encrypt": True, "need_mask": True, "mask_rule": None},
                {"field_name": "balance", "field_type": "decimal(18,2)"},
            ]}],
        }]
        resp = api.post(f"/api/projects/{pid}/data-assets", json=assets)
        assert resp.status_code == 200, resp.text
        asset_out = resp.json()[0]
        assert asset_out["tables"][0]["fields"][0]["need_encrypt"] is True
        asset_id = asset_out["id"]

        # ── Step5 权限矩阵(entry 用下标定位) ──
        matrix = {
            "roles": [
                {"name": "超级管理员", "role_type": "super_admin", "user_count_estimate": 1},
                {"name": "柜员", "role_type": "normal", "user_count_estimate": 20},
            ],
            "resources": [
                {"name": "账户记录", "resource_type": "data_record", "criticality": "critical"},
                {"name": "参数配置", "resource_type": "system_config", "criticality": "high"},
            ],
            "entries": [
                {"role_index": 0, "resource_index": 0, "action": "delete",
                 "requires_approval": False},   # 触发免审批违规
                {"role_index": 1, "resource_index": 0, "action": "read",
                 "requires_approval": False},
            ],
        }
        resp = api.post(f"/api/projects/{pid}/matrix", json=matrix)
        assert resp.status_code == 200, resp.text
        saved_matrix = resp.json()
        assert saved_matrix["saved"] == {"roles": 2, "resources": 2, "entries": 2}
        role_ids = [r["id"] for r in saved_matrix["roles"]]
        assert saved_matrix["entries"][0]["role_id"] == role_ids[0]

        # 越界下标被拒
        bad = {**matrix, "entries": [
            {"role_index": 5, "resource_index": 0, "action": "read"}]}
        assert api.post(f"/api/projects/{pid}/matrix", json=bad).status_code == 400

        # ── Step6 认证与密码策略 ──
        # 默认值按有效定级推导(当前二级 → 长度8)
        resp = api.get(f"/api/projects/{pid}/auth-defaults")
        defaults = resp.json()
        assert defaults["grading_level"] == "二级"
        assert defaults["defaults"]["pwd_min_length"] == 8

        resp = api.post(f"/api/projects/{pid}/auth-config", json={
            "auth_methods": ["password", "sms_otp"],
            "pwd_min_length": 10, "lockout_threshold": 5,
        })
        assert resp.status_code == 200
        # 显式配置覆盖默认值; 其余仍按基线补齐(有效期取二级90天)
        final_defaults = api.get(f"/api/projects/{pid}/auth-defaults").json()["defaults"]
        assert final_defaults["pwd_min_length"] == 10
        assert final_defaults["pwd_valid_days"] == 90

        # ── Step7 组件清单: 手工录入 + SBOM 文件导入 ──
        resp = api.post(f"/api/projects/{pid}/components", json={"components": [
            {"layer": "backend", "name": "log4j-core", "version": "2.14.1",
             "purl": "pkg:maven/org.apache.logging.log4j/log4j-core@2.14.1",
             "license": "Apache-2.0"},
        ]})
        assert resp.status_code == 200
        assert [c["source_type"] for c in resp.json()] == ["manual_input"]

        resp = api.post(
            f"/api/projects/{pid}/components/import-sbom",
            files={"file": ("bom.json", json.dumps(CYCLONE_MIN).encode("utf-8"),
                            "application/json")})
        assert resp.status_code == 200, resp.text
        imported = resp.json()
        assert imported["format"] == "cyclonedx"
        assert imported["total_parsed"] == 2
        assert imported["added"] == 2          # minio-py 两个版本均无同名同版本冲突
        # 同名同版本再导入 → 跳过重复
        resp = api.post(
            f"/api/projects/{pid}/components/import-sbom",
            files={"file": ("bom.json", json.dumps(CYCLONE_MIN).encode("utf-8"),
                            "application/json")})
        assert resp.json()["skipped_duplicate"] == 2

        components = api.get(f"/api/projects/{pid}/components").json()
        assert len(components) == 3
        by_name_ver = {(c["name"], c["version"]) for c in components}
        assert ("minio-py", "7.1.2") in by_name_ver

        # 坏格式文件被拒
        resp = api.post(
            f"/api/projects/{pid}/components/import-sbom",
            files={"file": ("bom.txt", b"garbage", "text/plain")})
        assert resp.status_code == 400 or resp.status_code == 422

        # ── Step8 接口清单与资产清单 ──
        inv = {
            "api_endpoints": [
                {"name": "匿名行情", "path": "/open/rates", "method": "GET",
                 "auth_required": False, "public_exposed": True,
                 "sensitive_asset_ids": []},
                {"name": "账户查询", "path": "/api/accounts/{id}", "method": "GET",
                 "auth_required": True, "public_exposed": False,
                 "sensitive_asset_ids": [asset_id], "rate_limit": "50 QPS/IP"},
            ],
            "infra_assets": [
                {"asset_type": "database", "name": "核心库", "env": "prod",
                 "ip": "10.0.0.9", "owner": "DBA组", "holds_sensitive": True},
            ],
        }
        resp = api.post(f"/api/projects/{pid}/inventory", json=inv)
        assert resp.status_code == 200
        got = api.get(f"/api/projects/{pid}/inventory").json()
        assert got["api_endpoints"][1]["sensitive_asset_ids"] == [asset_id]

        # ── 确认页预览(干跑, 不落库) ──
        before = api.get(f"/api/projects/{pid}").json()["counts"]["requirements"]
        resp = api.post(f"/api/projects/{pid}/requirements/preview")
        assert resp.status_code == 200, resp.text
        preview = resp.json()
        assert preview["total"] > 10
        after_preview = api.get(f"/api/projects/{pid}").json()["counts"]["requirements"]
        assert after_preview == before              # 干跑不写库
        codes = {c["code"] for c in preview["by_category"]}
        assert {"feature_category", "permission_rule", "data_asset"} <= codes
        assert preview["top_items"]

        # ── 生成安全基线(离线, OSV 不出网) ──
        resp = api.post(f"/api/projects/{pid}/generate", json={"skip_osv": True})
        assert resp.status_code == 200, resp.text
        summary = resp.json()
        assert summary["requirements_total"] >= preview["total"]
        assert set(summary["documents"]) == {"grading", "requirement", "design", "sbom_vuln", "review"}
        assert summary["osv_summary"]               # 离线文案

        detail = api.get(f"/api/projects/{pid}").json()
        assert detail["status"] == "generated"

        # ── 需求查询与筛选 ──
        rows = api.get(f"/api/projects/{pid}/requirements").json()
        assert rows
        filtered = api.get(
            f"/api/projects/{pid}/requirements",
            params={"category": "feature_category", "priority": "high"}).json()
        assert all(r["priority"] == "high" for r in filtered)
        assert all(r["category"] == "功能安全" for r in filtered)
        assert filtered[0]["source_entity_id"] > 0     # 追溯约束
        assert api.get(f"/api/projects/{pid}/requirements",
                       params={"priority": "bad"}).status_code == 400

        # 漏洞清单(离线为空但接口可用)
        assert api.get(f"/api/projects/{pid}/vulnerabilities").json() == []

        # SBOM JSON 实时构建
        bom = api.get(f"/api/projects/{pid}/sbom").json()
        assert bom["bomFormat"] == "CycloneDX"
        names = {c["name"] for c in bom["components"]}
        assert "log4j-core" in names and "minio-py" in names

        # ── 文档下载(Word×4 + Excel 跟踪表) ──
        docx_mime = ("application/vnd.openxmlformats-officedocument."
                     "wordprocessingml.document")
        for doc_type in ("grading", "requirement", "design", "sbom_vuln"):
            resp = api.get(f"/api/projects/{pid}/export/docx/{doc_type}")
            assert resp.status_code == 200, (doc_type, resp.text)
            assert resp.headers["content-type"].startswith(docx_mime)
            assert resp.content[:2] == b"PK"
        assert api.get(f"/api/projects/{pid}/export/docx/nope").status_code == 404

        resp = api.get(f"/api/projects/{pid}/export/xlsx")
        assert resp.status_code == 200
        assert resp.content[:2] == b"PK"

        # 向导状态一次拉全
        state = api.get(f"/api/projects/{pid}/wizard-state").json()
        for key in ("project", "survey", "features", "data_assets", "roles",
                    "resources", "permission_entries", "auth_config",
                    "components", "api_endpoints", "infra_assets"):
            assert key in state, key
        assert state["survey"]["final_level"] == "二级"
        assert state["data_assets"][0]["classification"] == "4级_C3鉴别信息"  # 老"机密"入参自动折算 JR/T 五级
        assert state["data_assets"][0]["legacy_classification"] is None  # 新录入无迁移留痕

        # 项目编辑(PATCH)与删除
        resp = api.patch(f"/api/projects/{pid}", json={"pm_name": "新经理"})
        assert resp.json()["pm_name"] == "新经理"
        assert api.delete(f"/api/projects/{pid}").status_code == 204
        assert api.get(f"/api/projects/{pid}").status_code == 404
    finally:
        _cleanup_output(code)


def test_missing_project_returns_404(api):
    assert api.get("/api/projects/9999").status_code == 404
    assert api.get("/api/projects/9999/features").status_code == 404


def test_survey_incomplete_rejected(api):
    resp = api.post("/api/projects", json={
        "name": "问卷校验项目", "code": "PRJ-SURV-T1", "type": "mobile_app",
        "user_scale": "under_1k"})
    pid = resp.json()["id"]
    resp = api.post(f"/api/projects/{pid}/survey", json={
        "answers": [{"question_id": "Q1", "option_id": "A"}]})
    assert resp.status_code == 400
    assert "缺少题目" in resp.json()["detail"]
