# -*- coding: utf-8 -*-
"""命令行验证入口: 建库 → 种子数据 → OSV漏洞同步 → 规则引擎 → SBOM JSON + 4份Word。

用法:
    .venv/Scripts/python scripts/run_seed_demo.py             # 在线模式(调用真实 OSV.dev)
    .venv/Scripts/python scripts/run_seed_demo.py --offline   # 离线模式(跳过网络, 演示降级路径)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import shared.constants as C
from models import init_db, make_engine, make_session_factory
from services.pipeline import run_full_pipeline
from services.seed_data import summarize_requirements


def main() -> None:
    offline = "--offline" in sys.argv

    root = Path(__file__).resolve().parent.parent
    db_path = root / "secreq.db"
    if db_path.exists():
        db_path.unlink()

    engine = make_engine(f"sqlite:///{db_path}")
    init_db(engine)
    session = make_session_factory(engine)()

    from services.seed_data import seed_demo_project

    project = seed_demo_project(session)
    print(f"种子项目已写入: {project.name}({project.code}) id={project.id}")

    result = run_full_pipeline(
        session, project.id,
        out_dir=root / "output" / project.code,
        skip_osv=offline,
    )

    print(f"知识库模板规则已执行, 产物目录 output/{project.code}/")
    print("=" * 70)
    print(f"[SBOM] CycloneDX 1.5 已输出: {result.bom_path}")
    if result.sync:
        vulns = result.vulnerabilities
        top = [
            f"{v.cve_id}({C.label(C.SEVERITY_LABELS, v.severity)}"
            f"{f'/CVSS {v.cvss_score:g}' if v.cvss_score is not None else ''})"
            for v in vulns[:5]
        ]
        print(
            f"[OSV] {result.sync.summary_text()}; 共命中 {len(vulns)} 条记录"
            + (f", 严重度最高: {'、'.join(top)}" if top else "")
        )
        if result.sync.degraded:
            print("[OSV] ⚠ 存在查询失败组件, 已降级为『漏洞查询暂不可用』, 不阻塞其余流程")
    else:
        print("[OSV] 跳过网络查询(--offline)")
    print("-" * 70)

    print(summarize_requirements(result.requirements))

    print("[文档] 生成的 Word 文件:")

if __name__ == "__main__":
    main()
