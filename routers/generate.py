# -*- coding: utf-8 -*-
"""生成与导出路由。

- POST /generate      全流程编排(漏洞同步→规则引擎→SBOM JSON 落盘)
- POST /requirements/preview  规则引擎干跑, 不落库(确认页显示触发数)
- GET  /requirements /vulnerabilities /sbom   产物查询
- POST /requirements/{req_id}/confirm       单条确认
- POST /requirements/batch-confirm          批量确认(走查整改: 确认动作+批量操作)
- GET  /export/docx   《安全需求说明书》Word 全文下载(走查整改: 全文下载用 .docx)
- GET  /export/xlsx   需求跟踪表下载(Jira 可导入)
"""
import logging
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import shared.constants as C
from models import PlatformUser, Project, SbomComponent, SecurityRequirement, VulnerabilityRecord
from routers.common import (
    get_accessible_project, get_db, get_writable_project, require_login,
)
from services.audit_service import audit
from services.errors import server_error
from schemas.requirement import (
    CategoryCount, GenerateSummary, PreviewResult, RequirementOut, VulnerabilityOut,
)
from services.pipeline import _load_vulnerabilities, project_output_dir, run_full_pipeline

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects/{project_id}", tags=["generate-export"])

ROOT_DIR = Path(__file__).resolve().parent.parent

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"




class GenerateRequest(BaseModel):
    """skip_osv=True 时跳过 OSV.dev 网络查询(离线演示)。"""

    skip_osv: bool = False


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


@router.post("/requirements/preview")
def preview_requirements(project: Project = Depends(get_writable_project),
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


@router.post("/generate", response_model=GenerateSummary)
def generate(payload: GenerateRequest | None = None,
             project: Project = Depends(get_writable_project), db: Session = Depends(get_db),
             user: PlatformUser = Depends(require_login)):
    """全量生成。成功后项目状态置为 generated, 文档写入 output/<项目编码>/。"""
    skip_osv = bool(payload.skip_osv) if payload else False
    try:
        result = run_full_pipeline(
            db, project.id, out_dir=project_output_dir(ROOT_DIR / "output", project.code),
            skip_osv=skip_osv,
        )
    except ValueError as exc:            # 项目不存在等(业务性, 原因可回显)
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:             # 知识库占位符缺陷等引擎期错误
        raise server_error(logger, exc, "生成失败",
                           project_id=project.id, skip_osv=skip_osv) from exc

    project.status = "generated"
    db.commit()
    audit(db, user.username, "generate", {"project_id": project.id,
          "requirements": len(result.requirements)})

    critical_vulns = sum(1 for v in result.vulnerabilities if v.severity == "critical")
    return GenerateSummary(
        requirements_total=len(result.requirements),
        by_category=_category_counts(result.requirements),
        vulnerabilities_total=len(result.vulnerabilities),
        critical_vulnerabilities=critical_vulns,
        osv_summary=result.sync.summary_text() if result.sync else "离线模式未执行漏洞查询",
        degraded=bool(result.sync and result.sync.degraded),
        bom_file=result.bom_path.name if result.bom_path else None,
    )


class BatchConfirmIn(BaseModel):
    req_ids: list[str] = Field(min_length=1, max_length=500)


@router.post("/requirements/batch-confirm", response_model=dict)
def batch_confirm(payload: BatchConfirmIn,
                  project: Project = Depends(get_writable_project),
                  db: Session = Depends(get_db),
                  user: PlatformUser = Depends(require_login)):
    """批量确认安全需求(走查整改: 去责任人, 统一为确认动作+批量操作)。"""
    rows = db.query(SecurityRequirement).filter(
        SecurityRequirement.project_id == project.id,
        SecurityRequirement.req_id.in_(payload.req_ids),
    ).all()
    now = datetime.now()
    for req in rows:
        req.reg_confirmed = True
        req.confirmed_by = user.display_name
        req.confirmed_at = now
    db.commit()
    audit(db, user.username, "confirm_batch", {"project_id": project.id, "count": len(rows)})
    return {"confirmed": len(rows), "missing": sorted(set(payload.req_ids) - {r.req_id for r in rows})}


@router.post("/requirements/{req_id}/confirm", response_model=RequirementOut)
def confirm_regulatory(req_id: str, project: Project = Depends(get_writable_project),
                       db: Session = Depends(get_db),
                       user: PlatformUser = Depends(require_login)):
    """确认一条安全需求(含监管报送类; 走查整改: 所有需求统一确认动作)。"""
    req = db.query(SecurityRequirement).filter_by(
        project_id=project.id, req_id=req_id,
    ).first()
    if req is None:
        raise HTTPException(status_code=404, detail=f"需求不存在: {req_id}")
    req.reg_confirmed = True
    req.confirmed_by = user.display_name
    req.confirmed_at = datetime.now()
    db.commit()
    audit(db, user.username, "confirm", {"project_id": project.id, "req_id": req_id})
    return RequirementOut.model_validate(req)


def _sorted_requirements(db: Session, pid: int) -> list:
    rows = db.query(SecurityRequirement).filter_by(project_id=pid).all()
    order = ["critical", "high", "medium", "low"]
    rows.sort(key=lambda r: (order.index(r.priority) if r.priority in order else 9, r.req_id))
    return rows


@router.get("/requirements", response_model=list[RequirementOut])
def list_requirements(project: Project = Depends(get_accessible_project),
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
def list_vulnerabilities(project: Project = Depends(get_accessible_project),
                         db: Session = Depends(get_db)):
    comp_ids = {c.id: c for c in db.query(SbomComponent).filter_by(project_id=project.id)}
    rows = (
        db.query(VulnerabilityRecord)
        .filter(VulnerabilityRecord.component_id.in_(list(comp_ids)))
        .all() if comp_ids else []
    )
    def severity_key(v):
        return C.SEVERITY_ORDER.get(v.severity, 9)
    rows.sort(key=lambda v: (severity_key(v), comp_ids[v.component_id].name, v.cve_id))
    return [
        VulnerabilityOut(
            component_name=comp_ids[v.component_id].name,
            component_version=comp_ids[v.component_id].version,
            cve_id=v.cve_id, severity=v.severity, cvss_score=v.cvss_score,
            affected_range=v.affected_range, fix_version=v.fix_version, summary=v.summary,
            cnnvd_id=v.cnnvd_id, cn_severity=v.cn_severity, source=v.source,
        )
        for v in rows
    ]


@router.get("/sbom")
def get_sbom(project: Project = Depends(get_accessible_project), db: Session = Depends(get_db)):
    """实时构建 CycloneDX JSON(含 purl 自动补齐回写)。"""
    from services.sbom import build_cyclonedx, ensure_purl
    from rules.context import RequirementContext

    ctx = RequirementContext.from_db(db, project.id)
    for comp in ctx.components:
        ensure_purl(comp)
    db.commit()
    return build_cyclonedx(ctx.project, ctx.components)


# ── 下载 ──────────────────────────────────────────────
DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _audit_export(db: Session, user: PlatformUser, project: Project,
                  fmt: str, count: int, request: Request) -> None:
    """导出留痕: 需求清单外带属敏感动作, 需记录导出格式、条目数、来源 IP。"""
    audit(db, user.username, "export",
          {"project_id": project.id, "code": project.code, "format": fmt, "count": count},
          request.client.host if request.client else None)


@router.get("/export/docx")
def export_docx(request: Request, project: Project = Depends(get_accessible_project),
                db: Session = Depends(get_db),
                user: PlatformUser = Depends(require_login)):
    """《安全需求说明书》全文 Word 下载(概况定级 + 需求清单全文 + 漏洞清单)。"""
    from rules.context import RequirementContext
    from services.doc_export import build_full_docx

    reqs = _sorted_requirements(db, project.id)
    if not reqs:
        raise HTTPException(
            status_code=409, detail="尚未生成安全基线, 请先在向导确认页执行『生成安全基线』")
    ctx = RequirementContext.from_db(db, project.id)
    vulns = _load_vulnerabilities(db, ctx.components)
    content = build_full_docx(ctx.project, reqs, vulns, components=ctx.components)
    _audit_export(db, user, project, "docx", len(reqs), request)
    filename = f"{project.code}_安全需求说明书.docx"
    return Response(
        content=content,
        media_type=DOCX_MEDIA_TYPE,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@router.get("/export/xlsx")
def export_xlsx(request: Request, project: Project = Depends(get_accessible_project),
                db: Session = Depends(get_db),
                user: PlatformUser = Depends(require_login)):
    from rules.context import RequirementContext
    from services.tracking_export import tracking_xlsx_bytes

    reqs = _sorted_requirements(db, project.id)
    if not reqs:
        raise HTTPException(
            status_code=409, detail="尚无安全需求可导出, 请先执行『生成安全基线』")
    # v2.2.0: 一并导出漏洞清单(带 CNNVD 编号与数据来源), 免得合规通报时手工补录
    ctx = RequirementContext.from_db(db, project.id)
    content = tracking_xlsx_bytes(reqs, _load_vulnerabilities(db, ctx.components))
    _audit_export(db, user, project, "xlsx", len(reqs), request)
    filename = f"{project.code}_安全需求跟踪表.xlsx"
    return Response(
        content=content,
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )
