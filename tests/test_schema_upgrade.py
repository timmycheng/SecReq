# -*- coding: utf-8 -*-
"""存量库升级回归护栏(#18): v2.1.x 老库必须能无损补齐 v2.2.0 的 SBOM 新列。

v2.2.0 给 sbom_components 新增 5 列、vulnerabilities 新增 4 列, 但启动补列机制
ensure_schema_upgrade 的 _NEW_COLUMNS 未登记这两张表 —— 修复前, 带 v2.1.x 数据的
部署升级后第一个触及 SBOM 组件的请求即抛 OperationalError: no such column
(即本文件用例修复前的失败形态)。
"""
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from models import SbomComponent, VulnerabilityRecord
from models.database import init_db
from services.classification_migration import ensure_schema_upgrade

# v2.1.3 的真实建表形态(v2.2.0 新增列加入前的列清单)
_LEGACY_DDL = [
    """
    CREATE TABLE sbom_components (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        layer VARCHAR(20) NOT NULL,
        name VARCHAR(200) NOT NULL,
        version VARCHAR(50) NOT NULL,
        purl VARCHAR(300),
        license VARCHAR(100),
        source_type VARCHAR(20),
        last_osv_query_at DATETIME
    )
    """,
    """
    CREATE TABLE vulnerabilities (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        component_id INTEGER NOT NULL,
        cve_id VARCHAR(30) NOT NULL,
        severity VARCHAR(10) NOT NULL,
        cvss_score FLOAT,
        affected_range VARCHAR(200),
        fix_version VARCHAR(50),
        summary VARCHAR(500)
    )
    """,
]


@pytest.fixture()
def legacy_engine(tmp_path):
    """模拟带 v2.1.x 数据的存量库: 两张 SBOM 表只有旧列, 各插一行老数据。"""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'legacy.db'}", connect_args={"check_same_thread": False}
    )
    with engine.begin() as conn:
        for ddl in _LEGACY_DDL:
            conn.execute(text(ddl))
        conn.execute(
            text(
                "INSERT INTO sbom_components (project_id, layer, name, version, source_type)"
                " VALUES (1, 'runtime', 'openssl', '1.1.1k', 'manual_input')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO vulnerabilities (component_id, cve_id, severity)"
                " VALUES (1, 'CVE-2021-3450', 'high')"
            )
        )
    return engine


def test_legacy_db_upgrade_columns_added(legacy_engine):
    """老库跑 init_db + ensure_schema_upgrade 后, ORM 读写与新部署一致。"""
    init_db(legacy_engine)  # 只补缺失的表, 已存在的两张表不会被 create_all 改动
    added = ensure_schema_upgrade(legacy_engine)

    factory = sessionmaker(bind=legacy_engine, autoflush=False, expire_on_commit=False)
    db = factory()
    comp = db.query(SbomComponent).first()  # 修复前此处即抛 no such column
    assert comp.name == "openssl"
    assert comp.vuln_status is None  # 老数据的新列值为空

    vuln = VulnerabilityRecord(component_id=comp.id, cve_id="CVE-2022-0778", severity="high")
    db.add(vuln)
    db.commit()
    assert vuln.source == "osv_local"
    db.close()

    # ALTER 带DEFAULT: 升级前已存在的老行同样回填默认值
    with legacy_engine.connect() as conn:
        legacy_source = conn.execute(
            text("SELECT source FROM vulnerabilities WHERE cve_id = 'CVE-2021-3450'")
        ).scalar()
    assert legacy_source == "osv_local"

    assert set(added["sbom_components"]) == {
        "ecosystem", "distro", "osv_query_fingerprint", "vuln_status", "vuln_status_note",
    }
    assert set(added["vulnerabilities"]) == {
        "source", "external_ref", "cnnvd_id", "cn_severity",
    }


def test_schema_upgrade_idempotent(legacy_engine):
    """重复执行不再 ALTER(幂等), 与既有补列机制口径一致。"""
    init_db(legacy_engine)
    assert ensure_schema_upgrade(legacy_engine)
    assert ensure_schema_upgrade(legacy_engine) == {}
