# -*- coding: utf-8 -*-
"""SBOM 组件与漏洞记录。#194 起组件挂系统(system_id): 系统的软件事实多轮共享。"""
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.database import Base, UidMixin
from models.system import System


class SbomComponent(Base, UidMixin):
    """软件/框架清单条目, 同时是 CycloneDX SBOM 的数据源。"""

    __tablename__ = "sbom_components"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    system_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("systems.id"), index=True,
        comment="所属系统(#194); 存量迁移外的历史行可为空",
    )
    layer: Mapped[str] = mapped_column(String(20), comment="层级, 见 SBOM_LAYERS")
    name: Mapped[str] = mapped_column(String(200), comment="组件名")
    version: Mapped[str] = mapped_column(String(50), comment="版本号(必填)")
    purl: Mapped[str | None] = mapped_column(String(300), comment="package URL, 漏洞查询用")
    license: Mapped[str | None] = mapped_column(String(100), comment="许可证")
    source_type: Mapped[str] = mapped_column(
        String(20), default="manual_input", comment="来源 manual_input/sbom_file"
    )
    # v2.2.0: 生态与分发渠道 —— OS 覆盖的前提。同一 MySQL 8.0.32 在 Debian/RHEL/Bitnami
    # 下版本串完全不同, 不知道分发渠道就无法匹配。
    ecosystem: Mapped[str | None] = mapped_column(
        String(20), comment="生态 code, 见 VULN_ECOSYSTEMS; 空则走跨生态模糊匹配"
    )
    distro: Mapped[str | None] = mapped_column(
        String(20), comment="分发渠道 code, 见 SBOM_DISTROS"
    )
    last_osv_query_at: Mapped[datetime | None] = mapped_column(
        DateTime, comment="最近一次漏洞查询成功时间(缓存判定依据)"
    )
    osv_query_fingerprint: Mapped[str | None] = mapped_column(
        String(100), comment="查询指纹(漏洞库版本+组件版本), 指纹不变则复用缓存"
    )
    # 查询语义: hit/not_found/undetermined/not_covered —— 四种不可合并, 合并会制造虚假安全感
    vuln_status: Mapped[str | None] = mapped_column(
        String(20), comment="查询结果语义, 见 VULN_QUERY_STATUS"
    )
    vuln_status_note: Mapped[str | None] = mapped_column(
        String(300), comment="语义补充说明(如麒麟代理匹配的免责声明)"
    )

    system: Mapped[System | None] = relationship(back_populates="components")
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

    # v2.2.0 预留列: SCA 对接与 CNNVD 对齐。现在就加, 避免 v2.4.0 对接时再做迁移。
    source: Mapped[str] = mapped_column(
        String(20), default="osv_local", comment="数据来源 osv_local/osv_online/sca"
    )
    external_ref: Mapped[str | None] = mapped_column(
        String(200), comment="来源侧记录标识, 用于回查与去重(SCA 对接后启用)"
    )
    cnnvd_id: Mapped[str | None] = mapped_column(String(32), comment="CNNVD 编号")
    cn_severity: Mapped[str | None] = mapped_column(
        String(20), comment="CNNVD 中文危害等级(超危/高危/中危/低危)"
    )

    component: Mapped[SbomComponent] = relationship(back_populates="vulnerabilities")
