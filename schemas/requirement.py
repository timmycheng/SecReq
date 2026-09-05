# -*- coding: utf-8 -*-
"""生成产物: 安全需求 / 漏洞 / 预览与全量生成汇总。"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class RegulatoryRefOut(BaseModel):
    file: str
    clause: str = ""
    summary: str = ""
    note: str = ""


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
    source_entity_uid: str | None = None
    source_label: str | None = None
    trigger_reason: str
    status: str
    review_status: str = "open"
    regulatory_ref: list[RegulatoryRefOut] = []
    owner: str | None = None
    reg_confirmed: bool = False
    confirmed_by: str | None = None
    confirmed_at: datetime | None = None


class VulnerabilityOut(BaseModel):
    component_name: str = ""
    component_version: str = ""
    cve_id: str
    severity: str
    cvss_score: float | None
    affected_range: str | None
    fix_version: str | None
    summary: str | None
    #: v2.2.0: 合规通报常要求国产编号, 导出与展示都带上
    cnnvd_id: str | None = None
    cn_severity: str | None = None
    source: str = "osv_local"


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
    bom_file: str | None = None
    # 配置有误被跳过的知识库模板([{template_id, reason}]; 带默认值, 老客户端向后兼容)
    skipped_templates: list[dict] = []


class RequirementTransitionOut(BaseModel):
    """需求流转记录(#217): 每步生命周期变更的操作人/时间/意见。"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    requirement_id: int
    action: str
    from_status: str
    to_status: str
    operator_id: int | None = None
    operator_name: str
    opinion: str | None = None
    created_at: datetime
