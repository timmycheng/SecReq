# -*- coding: utf-8 -*-
"""Step7 软件/框架清单(SBOM 来源)与 SBOM 文件导入结果模型。"""
from pydantic import BaseModel, Field


class ComponentIn(BaseModel):
    layer: str
    name: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=50)
    purl: str | None = None
    license: str | None = Field(default=None, max_length=100)


class ComponentsSaveIn(BaseModel):
    components: list[ComponentIn]


class ComponentVulnInline(BaseModel):
    """组件条目内嵌的漏洞摘要(Step7 表格展示用)。"""

    cve_id: str
    severity: str
    cvss_score: float | None
    affected_range: str | None
    fix_version: str | None
    summary: str | None


class ComponentOut(BaseModel):
    id: int
    layer: str
    name: str
    version: str
    purl: str | None
    license: str | None
    source_type: str
    vulnerabilities: list[ComponentVulnInline] = []


class SbomImportResult(BaseModel):
    """SBOM 文件导入结果。"""

    filename: str
    format: str                 # cyclonedx / spdx_json
    total_parsed: int
    added: int
    skipped_duplicate: int
