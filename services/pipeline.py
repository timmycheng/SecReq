# -*- coding: utf-8 -*-
"""生成主流程编排(POST /api/projects/{id}/generate 与脚本复用):

加载上下文 → 补齐 purl 并构建 CycloneDX → OSV 漏洞同步(可降级)
→ 规则引擎生成安全需求落库 → 输出 SBOM JSON。

Word 文档生成已按走查整改移除: 产物以 Web 形式展示, 前端提供「复制到 Word」。
漏洞同步放在规则引擎之前执行, 保证 vulnerability 触发器能看到命中的 CVE。
"""
import re
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.orm import Session, joinedload

from models import init_db  # noqa: F401 (保证模型注册)
from rules import RuleEngine
from rules.context import RequirementContext
from services.osv import OsvClient, OsvSyncResult, sync_vulnerabilities, sync_vulnerabilities_async
from services.sbom import build_cyclonedx, write_cyclonedx_file

# 项目编码 → 目录名: 去掉路径分隔符/盘符等危险字符(存量库编码可能未经 schema 校验)
_UNSAFE_DIR_CHARS = re.compile(r"[^0-9A-Za-z\u4e00-\u9fff._-]+")


def project_output_dir(base_dir: Path, code: str) -> Path:
    """项目产物输出目录: base_dir/<清洗后的项目编码>, 编码含危险字符时替换为下划线。"""
    safe = _UNSAFE_DIR_CHARS.sub("_", code or "").strip("._") or "project"
    return base_dir / safe


@dataclass
class PipelineResult:
    """一次完整生成的产物汇总。"""

    project_id: int
    requirements: list = field(default_factory=list)
    sync: OsvSyncResult | None = None
    vulnerabilities: list = field(default_factory=list)
    bom_path: Path | None = None
    # 配置有误被跳过的知识库模板([{template_id, reason}]), 供响应透传与前端提示覆盖缺口
    skipped_templates: list = field(default_factory=list)


def run_full_pipeline(
    session: Session,
    project_id: int,
    out_dir: str | Path | None = None,
    engine: RuleEngine | None = None,
    osv_client: OsvClient | None = None,
    skip_osv: bool = False,
    vuln_source_override: str | None = None,
) -> PipelineResult:
    """对单个项目执行"需求+SBOM+漏洞+文档"全量生成。

    skip_osv 为 True 时完全跳过漏洞查询(离线模式), 漏洞保持库内现状。
    osv_client 传入时走在线通道(测试与开发演示用); 不传则按 SECREQ_VULN_SOURCE
    配置链选取数据源, 内网默认为本地离线漏洞库。
    """
    from models import Project

    if session.get(Project, project_id) is None:
        raise ValueError(f"项目不存在: id={project_id}")

    result = PipelineResult(project_id=project_id)
    ctx = RequirementContext.from_db(session, project_id)

    # ① 先构建 SBOM(同时把缺失 purl 回写), 供后续查询与文件输出
    bom = build_cyclonedx(ctx.project, ctx.components)
    session.commit()

    # ② 漏洞同步(指纹缓存/失败降级); 同步后整体重载上下文以携带最新记录
    if not skip_osv:
        _, result.sync = sync_vulnerabilities(
            session, ctx.components, client=osv_client, source_override=vuln_source_override)
        ctx = RequirementContext.from_db(session, project_id)

    all_vulns = _load_vulnerabilities(session, ctx.components)
    result.vulnerabilities = all_vulns

    # ③ 规则引擎生成安全需求并落库
    engine = engine or RuleEngine.load()
    result.requirements = engine.generate_and_save(ctx, session)
    result.skipped_templates = list(engine.skipped)

    # ④ 文件产出: CycloneDX JSON(未指定 out_dir 时按 output/<编码> 落盘, 编码经清洗防穿越)
    base = Path(out_dir) if out_dir else project_output_dir(Path("output"), ctx.project.code)
    result.bom_path = write_cyclonedx_file(bom, base / "sbom.cdx.json")
    return result


async def run_full_pipeline_async(
    session: Session,
    project_id: int,
    out_dir: str | Path | None = None,
    engine: RuleEngine | None = None,
    osv_client: OsvClient | None = None,
    skip_osv: bool = False,
    vuln_source_override: str | None = None,
) -> PipelineResult:
    """run_full_pipeline 的异步版(#71): 在线漏洞源走并发查询, 其余流程不变。

    与同步版共用全部构建/落库逻辑; 仅漏洞同步换成并发实现。
    """
    from models import Project

    if session.get(Project, project_id) is None:
        raise ValueError(f"项目不存在: id={project_id}")

    result = PipelineResult(project_id=project_id)
    ctx = RequirementContext.from_db(session, project_id)

    bom = build_cyclonedx(ctx.project, ctx.components)
    session.commit()

    if not skip_osv:
        _, result.sync = await sync_vulnerabilities_async(
            session, ctx.components, client=osv_client, source_override=vuln_source_override)
        ctx = RequirementContext.from_db(session, project_id)

    result.vulnerabilities = _load_vulnerabilities(session, ctx.components)

    engine = engine or RuleEngine.load()
    result.requirements = engine.generate_and_save(ctx, session)
    result.skipped_templates = list(engine.skipped)

    base = Path(out_dir) if out_dir else project_output_dir(Path("output"), ctx.project.code)
    result.bom_path = write_cyclonedx_file(bom, base / "sbom.cdx.json")
    return result


def _load_vulnerabilities(session: Session, components) -> list:
    """收集组件集合的全部漏洞记录, 按 严重度→组件→CVE 排序。"""
    import shared.constants as C

    from models import VulnerabilityRecord

    ids = [c.id for c in components]
    if not ids:
        return []
    rows = (
        session.query(VulnerabilityRecord)
        # 预载组件关系: Excel 漏洞清单导出取组件名/版本, 避免 ORM 逐条 lazy load
        .options(joinedload(VulnerabilityRecord.component))
        .filter(VulnerabilityRecord.component_id.in_(ids))
        .all()
    )
    rows.sort(key=lambda v: (C.SEVERITY_ORDER.get(v.severity, 9), v.component_id, v.cve_id))
    return rows
