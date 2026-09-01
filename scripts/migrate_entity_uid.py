# -*- coding: utf-8 -*-
"""实体稳定 uid 迁移 CLI(v2.3.0, #66): 回填 uid + 存量需求溯源重映射。

用法:
    .venv/Scripts/python scripts/migrate_entity_uid.py --dry-run   # 先看断链比例报告
    .venv/Scripts/python scripts/migrate_entity_uid.py             # 执行(幂等)

与 scripts/migrate_classification.py 同一口径: 支持 --dry-run、幂等,
实现与 main.py lifespan 共用(services/entity_uid_migration.py)。

⚠ 本迁移属 v2.3.0 单向不可逆变更: 执行前必须备份数据库文件;
代码回退需连库一起回退到迁移前备份。
"""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models import make_engine  # noqa: E402
from services.classification_migration import ensure_schema_upgrade  # noqa: E402
from services.entity_uid_migration import migrate_entity_uids  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="实体 uid 迁移(回填/重映射/断链标记)")
    parser.add_argument("--dry-run", action="store_true",
                        help="只统计待处理量与断链风险, 不写库")
    parser.add_argument("--database", default=None,
                        help="数据库 URL(缺省用 SECREQ_DATABASE_URL 或 ./secreq.db)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    engine = make_engine(args.database)
    ensure_schema_upgrade(engine)  # 先补 uid 列(幂等)

    from models import make_session_factory
    session = make_session_factory(engine)()
    try:
        stats = migrate_entity_uids(session, dry_run=args.dry_run)
    finally:
        session.close()

    print("=" * 70)
    if args.dry_run:
        print(f"[dry-run] 待回填 uid 的实体行: {stats['rows_without_uid']}")
        print(f"[dry-run] 待重映射/断链的需求行: {stats['requirements_pending_remap']}")
        print("说明: 断链行(来源实体已消失)执行时将保留 source_label 并标 obsolete, 不伪造映射")
    else:
        print(f"uid 回填: {stats.get('uid_backfilled', {})}")
        print(f"需求溯源重映射: mapped={stats.get('mapped', 0)}, "
              f"obsolete(断链)={stats.get('obsolete', 0)}, skipped(已映射)={stats.get('skipped', 0)}")
        print(f"接口-资产关联: {stats.get('asset_links', {})}")
    print("完成(幂等, 可重复执行)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
