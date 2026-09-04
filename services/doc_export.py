# -*- coding: utf-8 -*-
"""「下载 Word 文档」产物导出(走查整改: 全文下载用 .docx, 分区粘贴用前端 HTML 剪贴板)。

生成《安全需求说明书》: 封面标题 + 项目概况与定级 + 安全需求清单(全文平铺)
+ 漏洞清单。中文字体: 标题黑体、正文宋体; 表格带边框, 表头灰底。
"""
import io
from datetime import datetime

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

import shared.constants as C

_HEADER_FILL = "EDEDED"
_CRITICAL_RED = RGBColor(0xC0, 0x00, 0x00)


def _set_cn_font(run, name: str = "宋体", size: float = 10.5, bold: bool = False,
                 color: RGBColor | None = None) -> None:
    run.font.name = "Times New Roman"
    run.font.size = Pt(size)
    run.font.bold = bold
    if color is not None:
        run.font.color.rgb = color
    r_pr = run._element.get_or_add_rPr()
    r_fonts = r_pr.get_or_add_rFonts()
    r_fonts.set(qn("w:eastAsia"), name)


def _shade(cell, fill: str) -> None:
    shd = cell._tc.get_or_add_tcPr().makeelement(qn("w:shd"), {})
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:fill"), fill)
    cell._tc.get_or_add_tcPr().append(shd)


def _cell_text(cell, text: str, bold: bool = False, size: float = 9, red: bool = False) -> None:
    cell.text = ""
    para = cell.paragraphs[0]
    run = para.add_run(text or "—")
    _set_cn_font(run, size=size, bold=bold, color=_CRITICAL_RED if red else None)


def _add_table(doc: Document, headers: list[str], widths_cm: list[float]) -> list:
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, (header, width) in enumerate(zip(headers, widths_cm)):
        cell = table.rows[0].cells[i]
        _cell_text(cell, header, bold=True)
        _shade(cell, _HEADER_FILL)
        cell.width = Cm(width)
    return table


def _heading(doc: Document, text: str) -> None:
    para = doc.add_paragraph()
    run = para.add_run(text)
    _set_cn_font(run, name="黑体", size=14, bold=True)
    para.paragraph_format.space_before = Pt(14)
    para.paragraph_format.space_after = Pt(6)


def _note(doc: Document, text: str) -> None:
    """小号灰色说明段(数据来源声明、覆盖缺口提示)。"""
    para = doc.add_paragraph()
    run = para.add_run(text)
    _set_cn_font(run, size=8.5, color=RGBColor(0x59, 0x59, 0x59))
    para.paragraph_format.space_before = Pt(2)
    para.paragraph_format.space_after = Pt(6)


#: 数据来源 → 人读文案(导出文档里必须交代来源, 便于合规说明)
_SOURCE_LABELS = {
    "osv_local": "本地离线漏洞库",
    "osv_online": "OSV.dev 在线库",
    "sca": "行内 SCA 平台",
}


def _vuln_source_note(doc: Document, vulnerabilities: list) -> None:
    """标注数据来源与库版本 —— 内网交付时这是合规说明的一部分。"""
    sources = sorted({getattr(v, "source", "osv_local") or "osv_local" for v in vulnerabilities})
    text = "数据来源: " + "、".join(_SOURCE_LABELS.get(s, s) for s in sources)
    try:
        from services.vulndb import VulnDb
        meta = VulnDb().meta()
        text += f" v{meta.get('db_version', '未知版本')}(构建于 {meta.get('built_at', '未知')})"
    except Exception:  # 库不可读时只显示来源, 不阻断导出
        pass
    _note(doc, text)
    if any(getattr(v, "source", "") == "osv_local" for v in vulnerabilities):
        _note(doc, "本结果由本地离线漏洞库匹配得出, 未访问任何外部服务。")


def _uncovered_note(doc: Document, components: list) -> None:
    """把"未覆盖 / 无法判定 / 命中但待确认"的组件单独列出。

    三者都不能混进"未发现漏洞"里 —— 那会给人虚假的安全感。
    """
    pending = [
        c for c in components
        if getattr(c, "vuln_status", None) in ("not_covered", "undetermined")
        # 命中但带说明: 跨渠道模糊匹配、麒麟推断、版本缺修订号等
        or (getattr(c, "vuln_status", None) == "hit" and getattr(c, "vuln_status_note", None))
    ]
    if not pending:
        return
    lines = []
    for comp in pending:
        label = C.VULN_QUERY_STATUS.get(comp.vuln_status, comp.vuln_status)
        if comp.vuln_status == "hit":
            label = "命中待确认"
        lines.append(f"{comp.name}@{comp.version}: {label}。{comp.vuln_status_note or ''}")
    _note(doc, "以下组件需人工确认: " + " ".join(lines))


def build_full_docx(
    project,
    requirements: list,
    vulnerabilities: list,
    components: list | None = None,
    diff_data: dict | None = None,
) -> bytes:
    """生成整册《安全需求说明书》.docx 字节流。

    diff_data: services.requirement_diff.diff_requirements 的结果(评估继承场景,
    有上一轮时附「与上一轮差异」章节); None 则不出现该章节。
    """
    doc = Document()
    section = doc.sections[0]
    section.page_width, section.page_height = Cm(21.0), Cm(29.7)  # A4 纵向

    # 标题
    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _set_cn_font(title.add_run(f"{project.name} 安全需求说明书"), name="黑体", size=20, bold=True)
    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _set_cn_font(
        sub.add_run(f"项目编码: {project.code}    导出时间: {datetime.now():%Y-%m-%d %H:%M}"),
        size=9,
    )

    # 一、项目概况与定级
    _heading(doc, "一、项目概况与定级")
    survey = project_survey(project)
    survey_obj = getattr(project, "survey", None)
    level = survey_obj.effective_level() if survey_obj else ""
    meta_rows = [
        ("项目名称", project.name),
        ("项目编码", project.code),
        ("有效定级", f"等保{level}" if level else "未定级"),
        ("项目类型", "、".join(
            C.label(C.PROJECT_TYPES, t) for t in (getattr(project, "types", None) or [])) or "—"),
        ("合规目标", "、".join(
            C.label(C.COMPLIANCE_TARGETS, t) for t in (project.compliance_targets or [])) or "—"),
        ("定级结论", survey or "—"),
        ("安全需求数", f"{len(requirements)} 条"),
    ]
    meta_table = doc.add_table(rows=0, cols=2)
    meta_table.style = "Table Grid"
    for key, value in meta_rows:
        row = meta_table.add_row()
        _cell_text(row.cells[0], key, bold=True)
        _shade(row.cells[0], _HEADER_FILL)
        _cell_text(row.cells[1], value, size=10)
        row.cells[0].width, row.cells[1].width = Cm(3.5), Cm(13.0)

    # 二、安全需求清单(全文平铺)
    _heading(doc, f"二、安全需求清单(共 {len(requirements)} 条)")
    if requirements:
        priority_order = {p: i for i, p in enumerate(["critical", "high", "medium", "low"])}
        sorted_reqs = sorted(
            requirements,
            key=lambda r: (priority_order.get(r.priority, 9), r.req_id),
        )
        table = _add_table(
            doc,
            ["序号", "需求内容", "优先级", "类目/来源", "验收标准", "合规依据/确认"],
            [1.0, 7.2, 1.4, 2.6, 3.4, 2.9],
        )
        for idx, req in enumerate(sorted_reqs, start=1):
            row = table.add_row().cells
            _cell_text(row[0], str(idx), red=req.priority == "critical")

            content = row[1]
            content.text = ""
            p1 = content.paragraphs[0]
            _set_cn_font(p1.add_run(f"[{req.req_id}] {req.title}"), bold=True)
            p2 = content.add_paragraph()
            _set_cn_font(p2.add_run(req.description or ""))
            p3 = content.add_paragraph()
            _set_cn_font(p3.add_run(f"验收标准: {req.acceptance_criteria or '—'}"))

            _cell_text(row[2], C.label(C.REQUIREMENT_PRIORITY_LABELS, req.priority),
                       red=req.priority == "critical")

            source = getattr(req, "source_label", None) or f"{req.source_entity_type}#{req.source_entity_id}"
            _cell_text(row[3], f"{req.category}\n{source}")

            refs = ";\n".join(
                f"《{ref.get('file', '')}》{ref.get('clause', '')}"
                for ref in (getattr(req, "regulatory_ref", None) or [])
                if ref.get("file")
            )
            confirmed = "✓ 已确认" if getattr(req, "reg_confirmed", False) else "□ 未确认"
            _cell_text(row[4], refs or "—", size=8.5)
            _cell_text(row[5], confirmed, size=8.5)
    else:
        doc.add_paragraph("尚未生成安全需求, 请先在向导确认页执行「生成安全基线」。")

    # 三、漏洞清单
    _heading(doc, f"三、漏洞清单(共 {len(vulnerabilities)} 条)")
    if vulnerabilities:
        comp_by_id = {c.id: c for c in (components or [])}
        table = _add_table(
            doc,
            # v2.2.0: 补 CNNVD 编号 —— 银行合规通报常要求国产编号, 事后手工补录成本很高
            ["等级", "CVE", "CNNVD", "组件", "受影响范围", "修复版本", "简述"],
            [1.3, 2.8, 2.6, 3.3, 3.1, 2.4, 3.6],
        )
        for v in vulnerabilities:
            comp = comp_by_id.get(v.component_id)
            comp_label = f"{comp.name}@{comp.version}" if comp else f"组件#{v.component_id}"
            row = table.add_row().cells
            high = v.severity in ("critical", "high")
            _cell_text(row[0], C.label(C.SEVERITY_LABELS, v.severity), red=high)
            _cell_text(row[1], v.cve_id, red=high)
            _cell_text(row[2], getattr(v, "cnnvd_id", None) or "—")
            _cell_text(row[3], comp_label)
            _cell_text(row[4], v.affected_range or "—")
            _cell_text(row[5], v.fix_version or "官方暂未发布修复版")
            _cell_text(row[6], v.summary or "")
        _vuln_source_note(doc, vulnerabilities)
        _uncovered_note(doc, components or [])
    else:
        doc.add_paragraph("未发现漏洞记录。")

    if diff_data is not None:
        _diff_chapter(doc, diff_data)

    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def _diff_chapter(doc: Document, diff: dict) -> None:
    """「与上一轮差异」章节(评估继承 #151): 分期建设场景下审阅者最关心增量。"""
    prev_code = (diff.get("previous_project") or {}).get("project_code") or "上一轮"
    added_rows = diff.get("added") or []
    removed_rows = diff.get("removed") or []
    changed_rows = diff.get("changed") or []
    _heading(doc, f"四、与上一轮({prev_code})差异")
    if not (added_rows or removed_rows or changed_rows):
        doc.add_paragraph(f"与上一轮({prev_code})对比, 安全需求无变化。")
        return
    para = doc.add_paragraph()
    _set_cn_font(para.add_run(
        f"新增 {len(added_rows)} 条;移除 {len(removed_rows)} 条;变更 {len(changed_rows)} 条。"),
        bold=True,
    )
    table = _add_table(doc, ["变更", "编号", "优先级", "需求标题", "来源", "说明"],
                       [1.4, 3.0, 1.4, 5.4, 3.0, 3.3])
    for kind, rows, color in (("新增", added_rows, None), ("移除", removed_rows, _CRITICAL_RED)):
        for r in rows:
            row = table.add_row().cells
            _cell_text(row[0], kind, bold=True, red=color is not None)
            _cell_text(row[1], r["req_id"])
            _cell_text(row[2], C.label(C.REQUIREMENT_PRIORITY_LABELS, r["priority"]))
            _cell_text(row[3], r["title"])
            _cell_text(row[4], r.get("source_label") or "—")
            _cell_text(row[5], "本轮基线不再包含" if kind == "移除" else "本轮基线新增要求")
    for c in changed_rows:
        row = table.add_row().cells
        cur = c.get("current") or {}
        _cell_text(row[0], "变更", bold=True)
        _cell_text(row[1], cur.get("req_id", ""))
        _cell_text(row[2], C.label(C.REQUIREMENT_PRIORITY_LABELS, cur.get("priority", "")))
        _cell_text(row[3], cur.get("title", ""))
        _cell_text(row[4], cur.get("source_label") or "—")
        _cell_text(row[5], "变化字段: " + "、".join(c.get("fields") or []))
    _note(doc, "差异按知识库模板与来源实体对齐(template_id + source_entity_uid); "
               "同一输入实体的要求调整记为「变更」。")


def project_survey(project) -> str | None:
    """定级结论一句话(人工修正标注); 无问卷返回 None。"""
    survey = getattr(project, "survey", None)
    if survey is None or not survey.effective_level():
        return None
    if survey.final_level and survey.suggested_level:
        tag = "人工修正"
    elif survey.final_level:
        tag = "直接指定"
    else:
        tag = "系统建议"
    return f"等保{survey.effective_level()}({tag})"
