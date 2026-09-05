# -*- coding: utf-8 -*-
"""存量库升级服务: 列补齐(ALTER) + 老 4 级 → JR/T 0197 五级迁移。

改造点1 的落地口径:
- 公开→1级_公开数据 / 内部→2级_C1次要信息 / 敏感→3级_C2主要信息 / 机密→4级_C3鉴别信息;
- 机密 且 生物识别类 且 敏感PII 的资产 → 4级并附加 C3 标签;
- 原值保留在 legacy_classification 留痕;
- 幂等: 已迁移(legacy_classification 非空)的行跳过。

main.py 的 lifespan 与 scripts/migrate_classification.py 共用本模块, 保证口径唯一。
"""
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

import shared.constants as C
from models import DataAsset

# SQLite 需要补齐的存量列: 表名 → [(列名, DDL类型), ...]
_NEW_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "platform_users": [
        ("password_hash", "VARCHAR(256)"),
    ],
    "data_assets": [
        ("legacy_classification", "VARCHAR(16)"),
        ("c3_tag", "BOOLEAN DEFAULT 0"),
        ("uid", "VARCHAR(36)"),
    ],
    # NetBox 系统互通(#154): 推送成功后回填的对象 id
    "systems": [
        ("netbox_object_id", "VARCHAR(32)"),
    ],
    "projects": [
        ("owner_user_id", "INTEGER"),
        ("types", "JSON"),
        ("system_id", "INTEGER"),
    ],
    "infra_assets": [
        # NetBox 互通(#153): 推送成功后回填的来源侧标识
        ("netbox_ref_type", "VARCHAR(40)"),
        ("netbox_ref_id", "VARCHAR(32)"),
        ("cpu_cores", "INTEGER"),
        ("memory_gb", "INTEGER"),
        ("disk_gb", "INTEGER"),
        ("os", "VARCHAR(100)"),
        ("quantity", "INTEGER"),
        ("purpose", "VARCHAR(300)"),
        ("uid", "VARCHAR(36)"),
    ],
    "features": [
        ("description", "VARCHAR(500)"),
        ("uid", "VARCHAR(36)"),
    ],
    "security_requirements": [
        ("source_entity_uid", "VARCHAR(64)"),
        ("source_label", "VARCHAR(200)"),
        ("regulatory_ref", "JSON"),
        ("owner", "VARCHAR(50)"),
        ("reg_confirmed", "BOOLEAN DEFAULT 0"),
        ("confirmed_by", "VARCHAR(50)"),
        ("confirmed_at", "DATETIME"),
        # 需求评审生命周期(#217): 补列后已有行为 NULL, 由 backfill_review_statuses 回填
        ("review_status", "VARCHAR(20)"),
    ],
    # v2.2.0 SBOM 漏洞联动新增列: 漏登记会导致存量库升级后第一个触及
    # SBOM 组件的请求即抛 no such column。DDL 与模型列定义逐一对应,
    # source 为 NOT NULL, ALTER 必须带 DEFAULT 才能通过并存老行
    "sbom_components": [
        ("uid", "VARCHAR(36)"),
        ("ecosystem", "VARCHAR(20)"),
        ("distro", "VARCHAR(20)"),
        ("osv_query_fingerprint", "VARCHAR(100)"),
        ("vuln_status", "VARCHAR(20)"),
        ("vuln_status_note", "VARCHAR(300)"),
        # SBOM 双轨(#224): 入库时间, 晚于评估轮创建时间即本轮增量
        ("created_at", "DATETIME"),
    ],
    # v2.3.0 实体稳定 uid(#66): 其余整表替换实体与接口资产关联。
    # 列补齐后由 services/entity_uid_migration.migrate_entity_uids 回填与重映射
    "roles": [
        ("uid", "VARCHAR(36)"),
    ],
    "resources": [
        ("uid", "VARCHAR(36)"),
    ],
    "external_systems": [
        ("uid", "VARCHAR(36)"),
    ],
    "api_endpoints": [
        ("uid", "VARCHAR(36)"),
        ("sensitive_asset_uids", "JSON"),
    ],
    "vulnerabilities": [
        ("source", "VARCHAR(20) NOT NULL DEFAULT 'osv_local'"),
        ("external_ref", "VARCHAR(200)"),
        ("cnnvd_id", "VARCHAR(32)"),
        ("cn_severity", "VARCHAR(20)"),
    ],
}


# 拓扑画布回退(#164)移除的表: 存量数据仅为坐标/区域归属/连线说明, 回退后无保留价值。
# 幂等: 已不存在的表跳过。
_DROPPED_TABLES: list[str] = ["network_zones", "infra_links", "infra_layouts"]

# infra_assets.zone_id 列带 FK 约束, SQLite 的 DROP COLUMN 拒绝带 FK 定义的列,
# 按官方 12 步法整表重建(INSERT..SELECT 保数据, 重建后列清单与 v2.6.0 模型一致)。
# 前置条件: _NEW_COLUMNS 补列先执行, 下列引用的列在存量库必然存在。
_INFRA_ASSETS_REBUILD_SQL: list[str] = [
    """
    CREATE TABLE infra_assets_rebuilt (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL REFERENCES projects (id),
        uid VARCHAR(36),
        asset_type VARCHAR(20) NOT NULL,
        name VARCHAR(200) NOT NULL,
        env VARCHAR(10) NOT NULL,
        ip VARCHAR(64),
        owner VARCHAR(50),
        holds_sensitive BOOLEAN,
        cpu_cores INTEGER,
        memory_gb INTEGER,
        disk_gb INTEGER,
        os VARCHAR(100),
        quantity INTEGER,
        purpose VARCHAR(300),
        netbox_ref_type VARCHAR(40),
        netbox_ref_id VARCHAR(32)
    )
    """,
    """
    INSERT INTO infra_assets_rebuilt
        (id, project_id, uid, asset_type, name, env, ip, owner, holds_sensitive,
         cpu_cores, memory_gb, disk_gb, os, quantity, purpose,
         netbox_ref_type, netbox_ref_id)
    SELECT id, project_id, uid, asset_type, name, env, ip, owner, holds_sensitive,
           cpu_cores, memory_gb, disk_gb, os, quantity, purpose,
           netbox_ref_type, netbox_ref_id
    FROM infra_assets
    """,
    "DROP TABLE infra_assets",
    "ALTER TABLE infra_assets_rebuilt RENAME TO infra_assets",
    "CREATE INDEX ix_infra_assets_project_id ON infra_assets (project_id)",
    "CREATE INDEX ix_infra_assets_uid ON infra_assets (uid)",
]


def _drop_legacy_topology(conn, inspector) -> dict[str, list[str]]:
    """回退拓扑画布(#164): DROP 三张画布表, 重建 infra_assets 去掉 zone_id 列(幂等)。

    存量清单数据经 INSERT..SELECT 原样保留; 返回实际执行的清理动作供调用方留痕。
    """
    dropped: dict[str, list[str]] = {}
    for table in _DROPPED_TABLES:
        if inspector.has_table(table):
            conn.execute(text(f"DROP TABLE {table}"))
            dropped.setdefault("tables", []).append(table)
    if inspector.has_table("infra_assets"):
        cols = [col["name"] for col in inspector.get_columns("infra_assets")]
        if "zone_id" in cols:
            for ddl in _INFRA_ASSETS_REBUILD_SQL:
                conn.execute(text(ddl))
            dropped.setdefault("columns", []).append("infra_assets.zone_id")
    return dropped


# ── #194 清单上收: infra_assets / sbom_components / infra_arch_images 挂系统 ──
#
# 三表的 project_id 列带 NOT NULL, 无法仅 ALTER 补 system_id(新行不再有轮次归属),
# 按官方 12 步法整表重建。数据上收口径: 每个已归属系统, 取其**最新一轮**(projects.id
# 最大)的清单行置 system_id; 未归属系统的轮次与历史轮次的清单行不迁移(系统清单以
# 最新一轮为准, 旧轮副本本就是复制产物)。组件漏洞记录仅保留被上收组件的行。
# 前置条件: projects.system_id 列已由 _NEW_COLUMNS 补齐、systems 表已建(create_all 先行)。
_INVENTORY_REBUILDS: dict[str, list[str]] = {
    "infra_assets": [
        """CREATE TABLE infra_assets_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            system_id INTEGER REFERENCES systems (id),
            uid VARCHAR(36),
            asset_type VARCHAR(20) NOT NULL,
            name VARCHAR(200) NOT NULL,
            env VARCHAR(10) NOT NULL,
            ip VARCHAR(64),
            owner VARCHAR(50),
            holds_sensitive BOOLEAN,
            cpu_cores INTEGER,
            memory_gb INTEGER,
            disk_gb INTEGER,
            os VARCHAR(100),
            quantity INTEGER,
            purpose VARCHAR(300),
            netbox_ref_type VARCHAR(40),
            netbox_ref_id VARCHAR(32)
        )""",
        """INSERT INTO infra_assets_new
            (id, system_id, uid, asset_type, name, env, ip, owner, holds_sensitive,
             cpu_cores, memory_gb, disk_gb, os, quantity, purpose,
             netbox_ref_type, netbox_ref_id)
        SELECT a.id, p.system_id, a.uid, a.asset_type, a.name, a.env, a.ip, a.owner,
               a.holds_sensitive, a.cpu_cores, a.memory_gb, a.disk_gb, a.os,
               a.quantity, a.purpose, a.netbox_ref_type, a.netbox_ref_id
        FROM infra_assets a
        JOIN projects p ON a.project_id = p.id
        WHERE p.system_id IS NOT NULL
          AND a.project_id = (SELECT MAX(p2.id) FROM projects p2 WHERE p2.system_id = p.system_id)""",
        "DROP TABLE infra_assets",
        "ALTER TABLE infra_assets_new RENAME TO infra_assets",
        "CREATE INDEX ix_infra_assets_system_id ON infra_assets (system_id)",
        "CREATE INDEX ix_infra_assets_uid ON infra_assets (uid)",
    ],
    "sbom_components": [
        """CREATE TABLE sbom_components_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            system_id INTEGER REFERENCES systems (id),
            uid VARCHAR(36),
            layer VARCHAR(20) NOT NULL,
            name VARCHAR(200) NOT NULL,
            version VARCHAR(50) NOT NULL,
            purl VARCHAR(300),
            license VARCHAR(100),
            source_type VARCHAR(20) DEFAULT 'manual_input' NOT NULL,
            ecosystem VARCHAR(20),
            distro VARCHAR(20),
            last_osv_query_at DATETIME,
            osv_query_fingerprint VARCHAR(100),
            vuln_status VARCHAR(20),
            vuln_status_note VARCHAR(300)
        )""",
        """INSERT INTO sbom_components_new
            (id, system_id, uid, layer, name, version, purl, license, source_type,
             ecosystem, distro, last_osv_query_at, osv_query_fingerprint,
             vuln_status, vuln_status_note)
        SELECT c.id, p.system_id, c.uid, c.layer, c.name, c.version, c.purl, c.license,
               c.source_type, c.ecosystem, c.distro, c.last_osv_query_at,
               c.osv_query_fingerprint, c.vuln_status, c.vuln_status_note
        FROM sbom_components c
        JOIN projects p ON c.project_id = p.id
        WHERE p.system_id IS NOT NULL
          AND c.project_id = (SELECT MAX(p2.id) FROM projects p2 WHERE p2.system_id = p.system_id)""",
        "DROP TABLE sbom_components",
        "ALTER TABLE sbom_components_new RENAME TO sbom_components",
        "CREATE INDEX ix_sbom_components_system_id ON sbom_components (system_id)",
        "CREATE INDEX ix_sbom_components_uid ON sbom_components (uid)",
        # 被上收清单之外的组件(旧轮副本/未归属轮次)的漏洞记录一并清理, 防孤儿行
        """DELETE FROM vulnerabilities
        WHERE component_id NOT IN (SELECT id FROM sbom_components)""",
    ],
    "infra_arch_images": [
        """CREATE TABLE infra_arch_images_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            system_id INTEGER REFERENCES systems (id),
            env VARCHAR(10) NOT NULL,
            image_data_url TEXT NOT NULL,
            CONSTRAINT uq_arch_image_system_env UNIQUE (system_id, env)
        )""",
        """INSERT INTO infra_arch_images_new (id, system_id, env, image_data_url)
        SELECT i.id, p.system_id, i.env, i.image_data_url
        FROM infra_arch_images i
        JOIN projects p ON i.project_id = p.id
        WHERE p.system_id IS NOT NULL
          AND i.project_id = (SELECT MAX(p2.id) FROM projects p2 WHERE p2.system_id = p.system_id)""",
        "DROP TABLE infra_arch_images",
        "ALTER TABLE infra_arch_images_new RENAME TO infra_arch_images",
        "CREATE INDEX ix_infra_arch_images_system_id ON infra_arch_images (system_id)",
    ],
}


def _rebuild_inventory_tables(conn, inspector) -> dict[str, list[str]]:
    """#194 清单三表挂系统(幂等): 缺 system_id 列的表按最新一轮口径整表重建上收。"""
    rebuilt: dict[str, list[str]] = {}
    if not inspector.has_table("systems"):
        return rebuilt
    inspector.clear_cache()  # 前面的 ALTER 补列/重建可能改变了本事务内的表结构
    project_cols = {col["name"] for col in inspector.get_columns("projects")} \
        if inspector.has_table("projects") else set()
    if "system_id" not in project_cols:
        return rebuilt
    for table, ddl_list in _INVENTORY_REBUILDS.items():
        if not inspector.has_table(table):
            continue
        cols = {col["name"] for col in inspector.get_columns(table)}
        if "system_id" in cols:
            continue
        for ddl in ddl_list:
            conn.execute(text(ddl))
        rebuilt.setdefault("tables", []).append(table)
    return rebuilt


def ensure_schema_upgrade(engine) -> dict[str, list[str]]:
    """为已存在的表补齐新增列(幂等); 新表由 create_all 负责。"""
    inspector = inspect(engine)
    added: dict[str, list[str]] = {}
    with engine.begin() as conn:
        for table, columns in _NEW_COLUMNS.items():
            if not inspector.has_table(table):
                continue
            existing = {col["name"] for col in inspector.get_columns(table)}
            for name, ddl in columns:
                if name in existing:
                    continue
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
                added.setdefault(table, []).append(name)
        added.update(_drop_legacy_topology(conn, inspector))
        for key, values in _rebuild_inventory_tables(conn, inspector).items():
            added.setdefault(key, []).extend(values)
    return added


def migrate_legacy_classification(session: Session, dry_run: bool = False) -> dict[str, int]:
    """执行老 4 级 → 新 5 级迁移, 返回统计。可重复执行(幂等)。"""
    stats = {"migrated": 0, "c3_tagged": 0, "already_migrated": 0, "invalid": 0}
    assets = session.query(DataAsset).all()
    for asset in assets:
        current = asset.classification or ""
        if asset.legacy_classification:
            stats["already_migrated"] += 1
            continue
        if current in C.LEGACY_CLASSIFICATION_MAP:
            new_level = C.LEGACY_CLASSIFICATION_MAP[current]
            if not dry_run:
                asset.legacy_classification = current
                asset.classification = new_level
                if C.level_rank(new_level) >= 4 and asset.data_type == "biometric" \
                        and asset.is_sensitive_pii:
                    asset.c3_tag = True
                    stats["c3_tagged"] += 1
            elif C.level_rank(new_level) >= 4 and asset.data_type == "biometric" \
                    and asset.is_sensitive_pii:
                stats["c3_tagged"] += 1
            stats["migrated"] += 1
        elif current not in C.DATA_LEVELS:
            stats["invalid"] += 1
    if not dry_run:
        session.commit()
    return stats
