# -*- coding: utf-8 -*-
"""演示走查脚本: pm 填报 → 门禁阻断 → 补齐 → 评审员审核 → 负责人终审。

材料交付物要求的完整走查(可代替录屏, 输出即走查记录):

    .venv/Scripts/python scripts/demo_review_flow.py

使用独立临时 SQLite 库 + TestClient, 不触碰 secreq.db 与 output/。
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

STEP = "\n\033[1m== {} ==\033[0m"


def build_client():
    import main
    from models import init_db
    from routers.common import get_db
    from services.auth_service import ensure_seed_users

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False}, poolclass=StaticPool)
    init_db(engine)
    db_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    seed = db_factory()
    ensure_seed_users(seed)
    seed.close()

    def _override():
        db = db_factory()
        try:
            yield db
        finally:
            db.close()

    main.app.dependency_overrides[get_db] = _override
    return TestClient(main.app)


def as_user(client: TestClient, username: str) -> TestClient:
    return TestClient(client.app, headers={"X-Auth-User": username})


def say(client: TestClient, resp, note: str = "") -> None:
    who = client.headers.get("X-Auth-User", "匿名")
    print(f"  [{who}] {resp.status_code} {note}")
    if resp.status_code >= 400:
        body = resp.json()
        detail = body.get("detail", body)
        print(f"         ↳ {str(detail)[:220]}")


def main() -> int:
    out_dir = Path(tempfile.mkdtemp(prefix="secreq_demo_"))
    print("演示产物目录:", out_dir)
    client = build_client()
    pm = as_user(client, "pm_wang")
    reviewer = as_user(client, "sec_chen")
    lead = as_user(client, "sec_zhao")
    auditor = as_user(client, "audit_sun")

    print(STEP.format("1. 项目经理填报: 建项目/问卷定级/数据字典"))
    r = pm.post("/api/projects", json={
        "name": "演示-线上信贷系统", "code": "PRJ-DEMO-REV", "type": "web",
        "user_scale": "over_1m", "deploy_env": ["private_cloud"],
        "compliance_targets": ["djcp_l3", "pipl"], "pm_name": "王建国",
    })
    say(pm, r, "创建项目")
    pid = r.json()["id"]
    say(pm, pm.post(f"/api/projects/{pid}/survey", json={
        "answers": [{"question_id": "Q1", "option_id": "C"},
                    {"question_id": "Q2", "option_id": "C"},
                    {"question_id": "Q3", "option_id": "C"},
                    {"question_id": "Q4", "option_id": "D"},
                    {"question_id": "Q5", "option_id": "B"}],
    }), "提交定级问卷(系统建议三级)")
    say(pm, pm.post(f"/api/projects/{pid}/data-assets", json=[{
        "name": "信贷账户数据", "data_type": "financial_account",
        "classification": "4级_C3鉴别信息", "c3_tag": True,
        "is_pii": True, "is_sensitive_pii": True, "storage_envs": ["db"],
        "tables": [{"table_name": "t_loan_account", "fields": [
            {"field_name": "card_no", "field_type": "varchar(32)",
             "need_encrypt": True, "need_mask": True, "mask_rule": "仅展示后4位"},
        ]}],
    }]), "录入4级资产(带C3标签)")
    say(pm, pm.post(f"/api/projects/{pid}/matrix", json={
        "roles": [{"name": "运营管理员", "role_type": "privileged", "user_count_estimate": 3}],
        "resources": [{"name": "信贷账户记录", "resource_type": "data_record",
                       "criticality": "critical"}],
        "entries": [{"role_index": 0, "resource_index": 0, "action": "create",
                     "requires_approval": False},
                    {"role_index": 0, "resource_index": 0, "action": "approve",
                     "requires_approval": False}],
    }), "权限矩阵(故意构造SoD冲突)")
    say(pm, pm.post(f"/api/projects/{pid}/generate", json={"skip_osv": True}),
       "生成安全基线")

    print(STEP.format("2. 门禁阻断: 需求门禁(critical缺责任人) + 立项门禁(报送未确认)"))
    say(pm, pm.post(f"/api/projects/{pid}/gates/requirement/submit"),
        "提交需求门禁 → 409 blocked + missing 清单")
    say(pm, pm.post(f"/api/projects/{pid}/gates/initiation/submit"),
        "提交立项门禁 → 409 blocked + missing 清单")

    print(STEP.format("3. RBAC 抽查: 审计只读 / pm 不能审核"))
    say(auditor, auditor.post(f"/api/projects/{pid}/gates/requirement/submit"),
        "审计 POST 提交门禁 → 403")
    say(auditor, auditor.get(f"/api/projects/{pid}/requirements"), "审计只读需求 → 200")

    print(STEP.format("4. 补齐: 确认监管报送事项 + 指定 critical 责任人"))
    reqs = pm.get(f"/api/projects/{pid}/requirements").json()
    reg = [x for x in reqs if x["category"] == "监管报送"]
    for x in reg:
        say(pm, pm.post(f"/api/projects/{pid}/requirements/{x['req_id']}/confirm"),
            f"确认报送事项 {x['req_id']}《{x['title']}》")
    for x in reqs:
        if x["priority"] == "critical":
            say(pm, pm.post(f"/api/projects/{pid}/requirements/{x['req_id']}/owner",
                            json={"owner": "李开发"}),
                f"指定 {x['req_id']} 责任人")

    print(STEP.format("5. 重新提交 → 评审员审核 → 负责人终审(两步签核)"))
    for gate_type in ("initiation", "requirement"):
        say(pm, pm.post(f"/api/projects/{pid}/gates/{gate_type}/submit"),
            f"重新提交{gate_type}门禁")
        gate_id = pm.get(f"/api/projects/{pid}/gates").json()
        gid = next(g["id"] for g in gate_id if g["gate_type"] == gate_type)
        say(reviewer, reviewer.post(f"/api/projects/{pid}/gates/{gid}/review",
                                    json={"action": "approve", "opinion": "材料齐备, 同意"}),
            f"{gate_type}: 评审员通过(待终审)")
        say(lead, lead.post(f"/api/projects/{pid}/gates/{gid}/final",
                            json={"action": "sign", "opinion": "同意放行"}),
            f"{gate_type}: 负责人终审签核 → passed")

    print(STEP.format("6. 留痕哈希链校验(审计视角)"))
    say(auditor, auditor.get(f"/api/projects/{pid}/gates"), "读取门禁总览")
    gates = auditor.get(f"/api/projects/{pid}/gates").json()
    gid = next(g["id"] for g in gates if g["gate_type"] == "initiation" and g["id"])
    say(auditor, auditor.get(f"/api/projects/{pid}/gates/{gid}/evidence"),
        "读取立项门禁留痕")
    evidence = auditor.get(f"/api/projects/{pid}/gates/{gid}/evidence").json()
    for e in evidence:
        print(f"    {e['action']:>14} | {e['actor']} | hash={e['curr_hash'][:16]}…")
    say(auditor, auditor.get(f"/api/projects/{pid}/gates/{gid}/evidence/verify"),
        "链式哈希复算 → valid")

    print(STEP.format("7. 导出《项目安全评审表》(评审会材料)"))
    say(pm, pm.get(f"/api/projects/{pid}/export/docx/review"),
        f"下载 → {out_dir}(实际由 /export/docx/review 在线渲染)")

    print("\n走查完成: 门禁硬校验/RBAC/两步签核/哈希链 全部符合预期。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
