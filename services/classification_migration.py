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
    "projects": [
        ("offshore_vendor", "BOOLEAN DEFAULT 0"),
        ("owner_user_id", "INTEGER"),
        ("types", "JSON"),
        ("system_id", "INTEGER"),
    ],
    "infra_assets": [
        ("zone_id", "INTEGER"),
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
