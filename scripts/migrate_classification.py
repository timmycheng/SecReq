# -*- coding: utf-8 -*-
"""老 4 级数据分级 → JR/T 0197-2020 五级 迁移脚本(改造点1交付物)。

用法:
    .venv/Scripts/python scripts/migrate_classification.py            # 迁移默认库 ./secreq.db
    .venv/Scripts/python scripts/migrate_classification.py --dry-run  # 只预览, 不写库
    .venv/Scripts/python scripts/migrate_classification.py --db 路径  # 指定库文件

行为(与 main.py lifespan 自动升级共用 services/classification_migration):
1. 为存量表补齐新增列(data_assets.legacy_classification/c3_tag、
   projects.offshore_vendor、security_requirements.regulatory_ref/owner/reg_confirmed
   /confirmed_by/confirmed_at), 新表(评审门禁/用户)由 create_all 创建;
2. 分级映射: 公开→1级_公开数据、内部→2级_C1次要信息、敏感→3级_C2主要信息、
   机密→4级_C3鉴别信息; 机密且生物识别类且敏感PII → 附加 C3 标签;
3. 原值保留在 legacy_classification 留痕; 幂等, 可重复执行。
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models import make_engine, make_session_factory, init_db  # noqa: E402
from services.auth_service import ensure_seed_users  # noqa: E402
from services.classification_migration import (  # noqa: E402
    ensure_schema_upgrade, migrate_legacy_classification,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="老四级分级迁移为 JR/T 0197 五级")
    parser.add_argument("--db", default="./secreq.db", help="SQLite 数据库文件路径")
    parser.add_argument("--dry-run", action="store_true", help="只预览统计, 不写库")
    args = parser.parse_args()

    db_path = Path(args.db).resolve()
    if not db_path.exists():
        print(f"[SecReq] 数据库不存在: {db_path}(首次启动由应用自动建库, 无需迁移)")
        return 1

    engine = make_engine(f"sqlite:///{db_path}")
    init_db(engine)
    added = ensure_schema_upgrade(engine)
    for table, columns in added.items():
        print(f"[SecReq] 表 {table} 补齐列: {', '.join(columns)}")

    session = make_session_factory(engine)()
    try:
        stats = migrate_legacy_classification(session, dry_run=args.dry_run)
        action = "预览(未写库)" if args.dry_run else "完成"
        print(f"[SecReq] 分级迁移{action}: "
              f"迁移 {stats['migrated']} 条, 附加C3标签 {stats['c3_tagged']} 条, "
              f"已是新五级 {stats['already_migrated']} 条, 未识别 {stats['invalid']} 条")
        if not args.dry_run:
            ensure_seed_users(session)
            print("[SecReq] 种子平台用户已就绪(pm/dev/评审员/负责人/风险/审计)")
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
