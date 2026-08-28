# -*- coding: utf-8 -*-
"""生成主流程编排(供未来 POST /api/projects/{id}/generate 与脚本复用):

加载上下文 → 补齐 purl 并构建 CycloneDX → OSV 漏洞同步(可降级)
→ 规则引擎生成安全需求落库 → 输出 SBOM JSON + 4 份 Word 文档。

漏洞同步放在规则引擎之前执行, 保证 vulnerability 触发器能看到命中的 CVE。
"""
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from models import init_db  # noqa: F401 (保证模型注册)
from rules import RuleEngine
from rules.context import RequirementContext
from services.osv import OsvClient, OsvSyncResult, sync_vulnerabilities
from services.sbom import build_cyclonedx, write_cyclonedx_file


@dataclass
class PipelineResult:
    """一次完整生成的产物汇总。"""

    project_id: int
    requirements: list = field(default_factory=list)
    sync: OsvSyncResult | None = None
    vulnerabilities: list = field(default_factory=list)
    bom_path: Path | None = None
    documents: dict[str, Path] = field(default_factory=dict)


def run_full_pipeline(
    session: Session,
    project_id: int,
    out_dir: str | Path | None = None,
    engine: RuleEngine | None = None,
    osv_client: OsvClient | None = None,
    skip_osv: bool = False,
) -> PipelineResult:
    """对单个项目执行"需求+SBOM+漏洞+文档"全量生成。

    skip_osv 为 True 时完全跳过网络查询(离线模式), 漏洞保持库内现状。
    """
    from models import Project
    from services.docgen import generate_all_documents

    if session.get(Project, project_id) is None:
        raise ValueError(f"项目不存在: id={project_id}")

    result = PipelineResult(project_id=project_id)
    ctx = RequirementContext.from_db(session, project_id)

    # ① 先构建 SBOM(同时把缺失 purl 回写), 供后续查询与文件输出
    bom = build_cyclonedx(ctx.project, ctx.components)
    session.commit()

    # ② OSV 漏洞同步(24h 缓存/失败降级); 同步后整体重载上下文以携带最新记录
    if skip_osv:
        summary_text = "离线模式未执行漏洞查询"
    else:
        _, result.sync = sync_vulnerabilities(session, ctx.components, client=osv_client)
        summary_text = result.sync.summary_text()
        ctx = RequirementContext.from_db(session, project_id)

    all_vulns = _load_vulnerabilities(session, ctx.components)
    result.vulnerabilities = all_vulns

    # ③ 规则引擎生成安全需求并落库
    engine = engine or RuleEngine.load()
    result.requirements = engine.generate_and_save(ctx, session)

    # ④ 文件产出: CycloneDX JSON + 5 份 Word
    base = Path(out_dir) if out_dir else Path("output") / ctx.project.code
    result.bom_path = write_cyclonedx_file(bom, base / "sbom.cdx.json")
    from models import ReviewGate

    gates = session.query(ReviewGate).filter_by(project_id=project_id).all()
    gate_bundles = [
        {
            "gate_type": g.gate_type, "status": g.status,
            "submitter": _user_name(session, g.submitter_id),
            "reviewer": _user_name(session, g.reviewer_id),
            "reviewer_opinion": g.reviewer_opinion,
            "reviewer_conclusion": g.reviewer_conclusion,
            "final_reviewer": _user_name(session, g.final_reviewer_id),
            "final_opinion": g.final_opinion,
            "submitted_at": g.submitted_at, "reviewed_at": g.reviewed_at,
            "final_reviewed_at": g.final_reviewed_at,
            "version_hash": g.version_hash,
        }
        for g in gates
    ]
    result.documents = generate_all_documents(
        ctx, base, requirements=result.requirements,
        vulnerabilities=all_vulns, osv_summary=summary_text,
        generated_at=datetime.now(), gates=gate_bundles,
    )
    return result


def _user_name(session: Session, user_id: int | None) -> str | None:
    if user_id is None:
        return None
    from models import PlatformUser

    user = session.get(PlatformUser, user_id)
    return user.display_name if user else None


def _load_vulnerabilities(session: Session, components) -> list:
    """收集组件集合的全部漏洞记录, 按 严重度→组件→CVE 排序。"""
    import shared.constants as C

    from models import VulnerabilityRecord

    ids = [c.id for c in components]
    if not ids:
        return []
    rows = (
        session.query(VulnerabilityRecord)
        .filter(VulnerabilityRecord.component_id.in_(ids))
        .all()
    )
    rows.sort(key=lambda v: (C.SEVERITY_ORDER.get(v.severity, 9), v.component_id, v.cve_id))
    return rows
