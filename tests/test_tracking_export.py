# -*- coding: utf-8 -*-
"""Excel 需求跟踪表导出测试。"""

import services.tracking_export as te
from models import SecurityRequirement


def _make_req(i, priority="high", category="功能安全", req_id=None):
    return SecurityRequirement(
        project_id=1,
        req_id=req_id or f"SEC-V15-{i:03d}",
        template_id=f"SEC-V15-{i:03d}",
        title=f"需求{i}",
        description="描述文本",
        category=category,
        priority=priority,
        acceptance_criteria="验收标准文本",
        suggested_phase="design",
        source_entity_type="feature",
        source_entity_id=i,
        trigger_reason="触发了输入项: 文件上传功能",
    )


def test_headers_match_design_fields():
    wb = te.build_tracking_workbook([_make_req(1)])
    ws = wb["跟踪表"]
    headers = [c.value for c in ws[1]]
    assert headers == ["req_id", "需求描述", "优先级", "责任方", "建议阶段", "验收标准", "合规依据", "状态", "备注"]


def test_rows_ordered_by_priority_and_trace_in_note():
    rows = [
        _make_req(2, priority="medium"),
        _make_req(1, priority="critical"),
        _make_req(3, priority="high"),
    ]
    wb = te.build_tracking_workbook(rows)
    ws = wb["跟踪表"]
    assert ws.cell(row=2, column=1).value == "SEC-V15-001"
    assert ws.cell(row=3, column=1).value == "SEC-V15-003"
    # 优先级列为中文标签
    assert ws.cell(row=2, column=3).value == "紧急"
    # 状态默认 open → 待处理
    assert ws.cell(row=2, column=8).value == "待处理"
    # 备注列含追溯信息
    note = ws.cell(row=2, column=9).value
    assert note.startswith("feature ←") and "触发" in note  # source_label 未设置时回退类型名


def test_jira_hint_sheet_exists():
    wb = te.build_tracking_workbook([])
    assert "Jira导入说明" in wb.sheetnames
    hint_text = wb["Jira导入说明"].cell(row=4, column=1).value
    assert "映射" in hint_text


def test_bytes_roundtrip():
    data = te.tracking_xlsx_bytes([_make_req(9)])
    assert data[:2] == b"PK"  # xlsx 本质为 zip 包
