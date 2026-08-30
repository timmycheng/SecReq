# -*- coding: utf-8 -*-
"""Step7 软件/框架清单(SBOM 来源)与 SBOM 文件导入结果模型。"""
from pydantic import BaseModel, Field


class ComponentIn(BaseModel):
    layer: str
    name: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=50)
    purl: str | None = None
    license: str | None = Field(default=None, max_length=100)
    #: v2.2.0: 生态与分发渠道 —— OS 覆盖的前提(同一 MySQL 8.0.32 在 Debian/RHEL/Bitnami
    #: 下版本串完全不同, 不知道分发渠道就无法匹配)
    ecosystem: str | None = Field(default=None, max_length=20)
    distro: str | None = Field(default=None, max_length=20)


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
    cnnvd_id: str | None = None
    cn_severity: str | None = None


class ComponentOut(BaseModel):
    id: int
    layer: str
    name: str
    version: str
    purl: str | None
    license: str | None
    source_type: str
    ecosystem: str | None = None
    distro: str | None = None
    #: 查询语义: hit/not_found/undetermined/not_covered, 前端据此区分"未覆盖/无法判定/未发现"
    vuln_status: str | None = None
    vuln_status_note: str | None = None
    vulnerabilities: list[ComponentVulnInline] = []


class SbomImportResult(BaseModel):
    """SBOM 文件导入结果。"""

    filename: str
    format: str                 # cyclonedx / spdx_json
    total_parsed: int
    added: int
    skipped_duplicate: int
