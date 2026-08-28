# -*- coding: utf-8 -*-
"""生成与导出路由。

- POST /generate      全流程编排(漏洞同步→规则引擎→SBOM+5份Word 落盘)
- POST /requirements/preview  规则引擎干跑, 不落库(确认页显示触发数)
- GET  /requirements /vulnerabilities /sbom   产物查询
- POST /requirements/{req_id}/owner|confirm   责任人指派与监管报送确认
- GET  /export/docx/{doc_type} / export/xlsx 文档下载(按库内最新数据即时重渲染)
"""
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

import shared.constants as C
from models import (
    PlatformUser, Project, ReviewGate, SbomComponent, SecurityRequirement,
    VulnerabilityRecord,
)
from routers.common import (
    get_db, get_project_or_404, require_write_roles,
)
from schemas.requirement import (
    CategoryCount, GenerateSummary, PreviewResult, RequirementOut, VulnerabilityOut,
)
from services.pipeline import _load_vulnerabilities, run_full_pipeline

router = APIRouter(prefix="/api/projects/{project_id}", tags=["generate-export"])

ROOT_DIR = Path(__file__).resolve().parent.parent

DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

_pm_or_dev = Depends(require_write_roles("pm", "developer"))


class GenerateRequest(BaseModel):
    """skip_osv=True 时跳过 OSV.dev 网络查询(离线演示)。"""

    skip_osv: bool = False


class OwnerIn(BaseModel):
    owner: str


class GateBundleOut(BaseModel):
    """文档评审记录页取数: 全部门禁概要。"""

    gate_type: str
    status: str
    submitter: str | None = None
    reviewer: str | None = None
    reviewer_opinion: str | None = None
    reviewer_conclusion: str | None = None
    final_reviewer: str | None = None
    final_opinion: str | None = None
    submitted_at: datetime | None = None
    reviewed_at: datetime | None = None
    final_reviewed_at: datetime | None = None
    version_hash: str | None = None


def _category_counts(requirements: list[SecurityRequirement]) -> list[CategoryCount]:
    counter: dict[str, int] = {}
    for req in requirements:
        counter[req.category] = counter.get(req.category, 0) + 1
    label_to_code = {v: k for k, v in C.TRIGGER_CATEGORY_LABELS.items()}
    out = [
        CategoryCount(code=label_to_code.get(label, label), label=label, count=count)
        for label, count in counter.items()
    ]
    out.sort(key=lambda item: item.code)
    return out


def _priority_counts(requirements: list) -> dict[str, int]:
    counts: dict[str, int] = {}
    for req in requirements:
        counts[req.priority] = counts.get(req.priority, 0) + 1
    return {p: counts.get(p, 0) for p in ["critical", "high", "medium", "low"]}


@router.post("/requirements/preview", dependencies=[_pm_or_dev])
def preview_requirements(project: Project = Depends(get_project_or_404),
                         db: Session = Depends(get_db)):
    """规则引擎干跑: 返回将触发的需求规模, 不写任何数据。"""
    from rules import RuleEngine
    from rules.context import RequirementContext

    ctx = RequirementContext.from_db(db, project.id)
    pending = RuleEngine.load().generate(ctx)

    by_priority = _priority_counts(pending)
    top = sorted(
        pending,
        key=lambda r: (["critical", "high", "medium", "low"].index(r.priority)
                       if r.priority in ("critical", "high", "medium", "low") else 9,
                       r.req_id),
    )[:8]
    return PreviewResult(
        total=len(pending),
        by_category=_category_counts(pending),
        by_priority=by_priority,
        top_items=[f"【{C.label(C.REQUIREMENT_PRIORITY_LABELS, r.priority)}】{r.title}" for r in top],
    )


@router.post("/generate", response_model=GenerateSummary, dependencies=[_pm_or_dev])
def generate(payload: GenerateRequest | None = None,
             project: Project = Depends(get_project_or_404), db: Session = Depends(get_db)):
    """全量生成。成功后项目状态置为 generated, 文档写入 output/<项目编码>/。"""
    skip_osv = bool(payload.skip_osv) if payload else False
    try:
        result = run_full_pipeline(
            db, project.id, out_dir=ROOT_DIR / "output" / project.code,
            skip_osv=skip_osv,
        )
    except ValueError as exc:            # 项目不存在等
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:             # 知识库占位符缺陷等引擎期错误
        raise HTTPException(status_code=500, detail=f"生成失败: {exc}") from exc

    project.status = "generated"
    db.commit()

    documents = {
        doc_type: path.name for doc_type, path in (result.documents or {}).items()
    }
    critical_vulns = sum(1 for v in result.vulnerabilities if v.severity == "critical")
    return GenerateSummary(
        requirements_total=len(result.requirements),
        by_category=_category_counts(result.requirements),
        vulnerabilities_total=len(result.vulnerabilities),
        critical_vulnerabilities=critical_vulns,
        osv_summary=result.sync.summary_text() if result.sync else "离线模式未执行漏洞查询",
        degraded=bool(result.sync and result.sync.degraded),
        documents=documents,
        bom_file=result.bom_path.name if result.bom_path else None,
    )


@router.post("/requirements/{req_id}/owner", response_model=RequirementOut,
             dependencies=[_pm_or_dev])
def set_owner(req_id: str, payload: OwnerIn,
              project: Project = Depends(get_project_or_404),
              db: Session = Depends(get_db)):
    """指定需求责任人(门禁校验项: critical 需求必须有责任人)。"""
    req = db.query(SecurityRequirement).filter_by(
        project_id=project.id, req_id=req_id,
    ).first()
    if req is None:
        raise HTTPException(status_code=404, detail=f"需求不存在: {req_id}")
    req.owner = payload.owner.strip()
    db.commit()
    return RequirementOut.model_validate(req)


@router.post("/requirements/{req_id}/confirm", response_model=RequirementOut,
             dependencies=[_pm_or_dev])
def confirm_regulatory(req_id: str, project: Project = Depends(get_project_or_404),
                       db: Session = Depends(get_db),
                       user: PlatformUser = Depends(
                           require_write_roles("pm", "developer"))):
    """确认监管报送类需求(立项门禁要求全部确认)。"""
    req = db.query(SecurityRequirement).filter_by(
        project_id=project.id, req_id=req_id,
    ).first()
    if req is None:
        raise HTTPException(status_code=404, detail=f"需求不存在: {req_id}")
    if req.category != C.label(C.TRIGGER_CATEGORY_LABELS, "regulatory_trigger"):
        raise HTTPException(status_code=400, detail="仅监管报送类需求需要确认")
    req.reg_confirmed = True
    req.confirmed_by = user.display_name
    req.confirmed_at = datetime.now()
    db.commit()
    return RequirementOut.model_validate(req)


@router.get("/gates-bundle", response_model=list[GateBundleOut])
def gates_bundle(project: Project = Depends(get_project_or_404),
                 db: Session = Depends(get_db)):
    """文档评审记录页取数: 全部门禁概要(文档渲染内部也复用此查询)。"""
    return _gate_bundle(db, project.id)


def _gate_bundle(db: Session, project_id: int) -> list[dict]:
    rows = db.query(ReviewGate).filter_by(project_id=project_id).all()
    by_type = {g.gate_type: g for g in rows}
    out = []
    for gate_type in C.GATE_TYPES:
        gate = by_type.get(gate_type)
        if gate is None:
            continue
        out.append({
            "gate_type": gate_type,
            "status": gate.status,
            "submitter": _display_name(db, gate.submitter_id),
            "reviewer": _display_name(db, gate.reviewer_id),
            "reviewer_opinion": gate.reviewer_opinion,
            "reviewer_conclusion": gate.reviewer_conclusion,
            "final_reviewer": _display_name(db, gate.final_reviewer_id),
            "final_opinion": gate.final_opinion,
            "submitted_at": gate.submitted_at,
            "reviewed_at": gate.reviewed_at,
            "final_reviewed_at": gate.final_reviewed_at,
            "version_hash": gate.version_hash,
        })
    return out


def _display_name(db: Session, user_id: int | None) -> str | None:
    if user_id is None:
        return None
    user = db.get(PlatformUser, user_id)
    return user.display_name if user else None


def _sorted_requirements(db: Session, pid: int) -> list:
    rows = db.query(SecurityRequirement).filter_by(project_id=pid).all()
    order = ["critical", "high", "medium", "low"]
    rows.sort(key=lambda r: (order.index(r.priority) if r.priority in order else 9, r.req_id))
    return rows


@router.get("/requirements", response_model=list[RequirementOut])
def list_requirements(project: Project = Depends(get_project_or_404),
                      category: str | None = None, priority: str | None = None,
                      db: Session = Depends(get_db)):
    """需求列表; category 支持类目代码(feature_category 等), priority 支持 critical/high/medium/low。"""
    query = db.query(SecurityRequirement).filter_by(project_id=project.id)
    if category:
        label = C.label(C.TRIGGER_CATEGORY_LABELS, category)
        query = query.filter(SecurityRequirement.category == label)
    if priority:
        if priority not in C.REQUIREMENT_PRIORITY_LABELS:
            raise HTTPException(status_code=400, detail=f"未知优先级: {priority}")
        query = query.filter(SecurityRequirement.priority == priority)
    rows = query.all()
    order = ["critical", "high", "medium", "low"]
    rows.sort(key=lambda r: (order.index(r.priority) if r.priority in order else 9, r.req_id))
    return [RequirementOut.model_validate(r) for r in rows]


@router.get("/vulnerabilities", response_model=list[VulnerabilityOut])
def list_vulnerabilities(project: Project = Depends(get_project_or_404),
                         db: Session = Depends(get_db)):
    comp_ids = {c.id: c for c in db.query(SbomComponent).filter_by(project_id=project.id)}
    rows = (
        db.query(VulnerabilityRecord)
        .filter(VulnerabilityRecord.component_id.in_(list(comp_ids)))
        .all() if comp_ids else []
    )
    severity_key = lambda v: C.SEVERITY_ORDER.get(v.severity, 9)
    rows.sort(key=lambda v: (severity_key(v), comp_ids[v.component_id].name, v.cve_id))
    return [
        VulnerabilityOut(
            component_name=comp_ids[v.component_id].name,
            component_version=comp_ids[v.component_id].version,
            cve_id=v.cve_id, severity=v.severity, cvss_score=v.cvss_score,
            affected_range=v.affected_range, fix_version=v.fix_version, summary=v.summary,
        )
        for v in rows
    ]


@router.get("/sbom")
def get_sbom(project: Project = Depends(get_project_or_404), db: Session = Depends(get_db)):
    """实时构建 CycloneDX JSON(含 purl 自动补齐回写)。"""
    from services.sbom import build_cyclonedx, ensure_purl
    from rules.context import RequirementContext

    ctx = RequirementContext.from_db(db, project.id)
    for comp in ctx.components:
        ensure_purl(comp)
    db.commit()
    return build_cyclonedx(ctx.project, ctx.components)


# ── 文档下载 ──────────────────────────────────────────

def _regenerate_documents(db: Session, project: Project) -> dict[str, Path]:
    """按库内最新数据重渲染 5 份 Word 到 output 目录(OSV 查询不重复发起)。"""
    from rules.context import RequirementContext
    from services.docgen import generate_all_documents

    ctx = RequirementContext.from_db(db, project.id)
    reqs = _sorted_requirements(db, project.id)
    if not reqs:
        raise HTTPException(
            status_code=409, detail="尚未生成安全基线, 请先在向导确认页执行『生成安全基线』")
    vulns = _load_vulnerabilities(db, ctx.components)
    summary = f"本次下载基于最近一次漏洞同步的库内记录渲染(共{len(vulns)}条)"
    out_dir = ROOT_DIR / "output" / project.code
    return generate_all_documents(
        ctx, out_dir, requirements=reqs, vulnerabilities=vulns,
        osv_summary=summary, generated_at=datetime.now(),
        gates=_gate_bundle(db, project.id),
    )


@router.get("/export/docx/{doc_type}")
def export_docx(doc_type: str, project: Project = Depends(get_project_or_404),
                db: Session = Depends(get_db)):
    from services.docgen import DOC_BUILDERS

    if doc_type not in DOC_BUILDERS:
        raise HTTPException(
            status_code=404, detail=f"未知文档类型: {doc_type}, 可选 {'、'.join(DOC_BUILDERS)}")
    paths = _regenerate_documents(db, project)
    path = paths[doc_type]
    if not Path(path).exists():
        raise HTTPException(status_code=500, detail="文档生成失败, 请查看服务日志")
    return FileResponse(path, media_type=DOCX_MEDIA_TYPE, filename=Path(path).name)


@router.get("/export/xlsx")
def export_xlsx(project: Project = Depends(get_project_or_404), db: Session = Depends(get_db)):
    from services.tracking_export import tracking_xlsx_bytes

    reqs = _sorted_requirements(db, project.id)
    if not reqs:
        raise HTTPException(
            status_code=409, detail="尚无安全需求可导出, 请先执行『生成安全基线』")
    content = tracking_xlsx_bytes(reqs)
    filename = f"{project.code}_安全需求跟踪表.xlsx"
    return Response(
        content=content,
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )
