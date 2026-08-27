# -*- coding: utf-8 -*-
"""生成产物: 安全需求 / 漏洞 / 预览与全量生成汇总。"""
from pydantic import BaseModel, ConfigDict


class RequirementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    req_id: str
    template_id: str
    title: str
    description: str
    category: str
    priority: str
    asvs_ref: str | None
    acceptance_criteria: str
    suggested_phase: str
    source_entity_type: str
    source_entity_id: int
    trigger_reason: str
    status: str


class VulnerabilityOut(BaseModel):
    component_name: str = ""
    component_version: str = ""
    cve_id: str
    severity: str
    cvss_score: float | None
    affected_range: str | None
    fix_version: str | None
    summary: str | None


class CategoryCount(BaseModel):
    code: str
    label: str
    count: int


class PreviewResult(BaseModel):
    """确认页『已触发 XX 条安全需求』的预览(不落库)。"""

    total: int
    by_category: list[CategoryCount]
    by_priority: dict[str, int] = {}
    top_items: list[str] = []


class GenerateSummary(BaseModel):
    requirements_total: int
    by_category: list[CategoryCount]
    vulnerabilities_total: int
    critical_vulnerabilities: int
    osv_summary: str
    degraded: bool = False
    documents: dict[str, str] = {}   # doc_type → 文件名
    bom_file: str | None = None
