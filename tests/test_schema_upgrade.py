# -*- coding: utf-8 -*-
"""存量库升级回归护栏(#18): v2.1.x 老库必须能无损补齐 v2.2.0 的 SBOM 新列。

v2.2.0 给 sbom_components 新增 5 列、vulnerabilities 新增 4 列, 但启动补列机制
ensure_schema_upgrade 的 _NEW_COLUMNS 未登记这两张表 —— 修复前, 带 v2.1.x 数据的
部署升级后第一个触及 SBOM 组件的请求即抛 OperationalError: no such column
(即本文件用例修复前的失败形态)。
"""
import pytest
from sqlalchemy import create_engine, inspect as sa_inspect, text
from sqlalchemy.orm import sessionmaker

from models import SbomComponent, VulnerabilityRecord
from models.database import init_db
from services.classification_migration import ensure_schema_upgrade

# v2.1.3 的真实建表形态(v2.2.0 新增列加入前的列清单); systems/projects 为
# v2.6.0 时代形态(projects 已带 system_id), 供 #194 清单上收重建走通
_LEGACY_DDL = [
    """
    CREATE TABLE systems (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name VARCHAR(200)
    )
    """,
    """
    CREATE TABLE projects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name VARCHAR(200),
        system_id INTEGER
    )
    """,
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
    """
    CREATE TABLE infra_arch_images (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        env VARCHAR(10) NOT NULL,
        image_data_url TEXT NOT NULL
    )
    """,
    # v2.5.x 拓扑画布(#93)时期的表形态: zone_id 带 FK, 三张画布表
    """
    CREATE TABLE infra_assets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        asset_type VARCHAR(20) NOT NULL,
        name VARCHAR(200) NOT NULL,
        env VARCHAR(10) NOT NULL,
        ip VARCHAR(64),
        owner VARCHAR(50),
        holds_sensitive BOOLEAN,
        zone_id INTEGER,
        FOREIGN KEY (zone_id) REFERENCES network_zones (id)
    )
    """,
    """
    CREATE TABLE network_zones (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        uid VARCHAR(36),
        env VARCHAR(10),
        name VARCHAR(100)
    )
    """,
    """
    CREATE TABLE infra_links (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        env VARCHAR(10),
        source_uid VARCHAR(36) NOT NULL,
        target_uid VARCHAR(36) NOT NULL,
        label VARCHAR(200)
    )
    """,
    """
    CREATE TABLE infra_layouts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        env VARCHAR(10),
        layout JSON
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
        conn.execute(text("INSERT INTO systems (name) VALUES ('遗留系统')"))
        conn.execute(text("INSERT INTO projects (name, system_id) VALUES ('遗留评估', 1)"))
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
        conn.execute(
            text(
                "INSERT INTO network_zones (project_id, uid, env, name)"
                " VALUES (1, 'zone-legacy-0001', 'prod', 'DMZ')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO infra_assets (project_id, asset_type, name, env, zone_id)"
                " VALUES (1, 'server', 'E2E 应用服务器', 'prod', 1)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO infra_arch_images (project_id, env, image_data_url)"
                " VALUES (1, 'prod', 'data:image/png;base64,QUJD')"
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
    assert comp.system_id == 1  # #194: 清单按最新一轮上收到挂靠系统
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
        "uid", "ecosystem", "distro", "osv_query_fingerprint", "vuln_status",
        "vuln_status_note",
    }
    # #194: 三张清单表已整表重建挂 system_id, 记录在 tables 动作里
    assert {"infra_assets", "sbom_components", "infra_arch_images"}         <= set(added.get("tables", []))
    assert set(added["vulnerabilities"]) == {
        "source", "external_ref", "cnnvd_id", "cn_severity",
    }


def test_schema_upgrade_idempotent(legacy_engine):
    """重复执行不再 ALTER(幂等), 与既有补列机制口径一致。"""
    init_db(legacy_engine)
    assert ensure_schema_upgrade(legacy_engine)
    assert ensure_schema_upgrade(legacy_engine) == {}


def test_topology_tables_dropped_and_data_kept(legacy_engine):
    """拓扑回退(#164): 三张画布表 DROP, zone_id 列移除, infra_assets 存量数据无损。"""
    init_db(legacy_engine)
    added = ensure_schema_upgrade(legacy_engine)

    insp = sa_inspect(legacy_engine)
    assert not insp.has_table("network_zones")
    assert not insp.has_table("infra_links")
    assert not insp.has_table("infra_layouts")
    assert "zone_id" not in {c["name"] for c in insp.get_columns("infra_assets")}
    assert {"network_zones", "infra_links", "infra_layouts"} <= set(added["tables"])
    assert "system_id" in {c["name"] for c in insp.get_columns("infra_assets")}

    factory = sessionmaker(bind=legacy_engine, autoflush=False, expire_on_commit=False)
    db = factory()
    row = db.execute(text("SELECT asset_type, name, system_id FROM infra_assets")).one()
    assert row == ("server", "E2E 应用服务器", 1)
    db.close()
