# -*- coding: utf-8 -*-
"""Step7 SBOM 组件与漏洞记录。"""
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.database import Base
from models.project import Project


class SbomComponent(Base):
    """软件/框架清单条目, 同时是 CycloneDX SBOM 的数据源。"""

    __tablename__ = "sbom_components"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("projects.id"), index=True)
    layer: Mapped[str] = mapped_column(String(20), comment="层级, 见 SBOM_LAYERS")
    name: Mapped[str] = mapped_column(String(200), comment="组件名")
    version: Mapped[str] = mapped_column(String(50), comment="版本号(必填)")
    purl: Mapped[str | None] = mapped_column(String(300), comment="package URL, 漏洞查询用")
    license: Mapped[str | None] = mapped_column(String(100), comment="许可证")
    source_type: Mapped[str] = mapped_column(
        String(20), default="manual_input", comment="来源 manual_input/sbom_file"
    )
    last_osv_query_at: Mapped[datetime | None] = mapped_column(
        DateTime, comment="最近一次 OSV 查询成功时间(24h缓存判定依据)"
    )

    project: Mapped[Project] = relationship(back_populates="components")
    vulnerabilities: Mapped[list["VulnerabilityRecord"]] = relationship(
        back_populates="component", cascade="all, delete-orphan"
    )


class VulnerabilityRecord(Base):
    """OSV.dev 命中的漏洞结果(含24h缓存的落库形态)。"""

    __tablename__ = "vulnerabilities"
    __table_args__ = (
        UniqueConstraint("component_id", "cve_id", name="uq_vuln_component_cve"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    component_id: Mapped[int] = mapped_column(Integer, ForeignKey("sbom_components.id"), index=True)
    cve_id: Mapped[str] = mapped_column(String(30), comment="漏洞编号(CVE/GHSA等)")
    severity: Mapped[str] = mapped_column(String(10), comment="critical/high/medium/low")
    cvss_score: Mapped[float | None] = mapped_column(Float, comment="CVSS分数")
    affected_range: Mapped[str | None] = mapped_column(String(200), comment="受影响版本范围")
    fix_version: Mapped[str | None] = mapped_column(String(50), comment="修复版本")
    summary: Mapped[str | None] = mapped_column(String(500), comment="简述")

    component: Mapped[SbomComponent] = relationship(back_populates="vulnerabilities")
