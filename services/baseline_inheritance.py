# -*- coding: utf-8 -*-
"""评估继承系统基线(#224): 首轮建档 / 后续轮按基线预填、PM 只填增量。

- 系统无基线 → 首轮评估, 行为不变(空白填报), 本轮终审通过后建立基线(#225);
- 系统有基线 → 新建轮次自动按基线预填 资产/字典/权限矩阵/API 清单;
- 继承标注: 预填行原样保留实体 uid(#66), 来源判定 = uid 是否在基线索引中,
  前端据此打「基线继承 / 本轮新增」标记, 评审时可区分审阅;
- SBOM 双轨: 组件挂系统持累计技术栈, 各轮以 created_at 晚于轮次创建时间记为本轮增量。
"""
from sqlalchemy.orm import Session

from models import (
    ApiEndpoint, DataAsset, DataField, DataTable, PermissionEntry,
    Resource, Role, SystemBaseline,
)


def baseline_uid_index(baseline: SystemBaseline | None) -> dict[str, list[str]]:
    """基线 uid 索引: 前端「基线继承/本轮新增」标记的数据源。"""
    if baseline is None:
        return {}
    data = baseline.baseline_json or {}
    def pick(key: str) -> list[str]:
        return [row["uid"] for row in (data.get(key) or [])
                if isinstance(row, dict) and row.get("uid")]
    return {
        "data_assets": pick("data_assets"),
        "roles": pick("roles"),
        "resources": pick("resources"),
        "api_endpoints": pick("api_endpoints"),
    }


def prefill_project_from_baseline(db: Session, project, baseline: SystemBaseline) -> dict:
    """按基线快照预填项目的向导数据(资产/字典/权限/API), 返回各分区条数。

    预填行保留基线实体 uid; 同一项目重复创建不会发生(每轮新行), 幂等性由
    调用方保证(仅在创建时调用一次)。
    """
    data = baseline.baseline_json or {}

    for a in data.get("data_assets") or []:
        if not isinstance(a, dict):
            continue
        asset = DataAsset(
            project_id=project.id,
            uid=a.get("uid"), name=a.get("name") or "", data_type=a.get("data_type") or "",
            classification=a.get("classification") or "1级_公开数据",
            legacy_classification=a.get("legacy_classification"),
            c3_tag=bool(a.get("c3_tag")), is_pii=bool(a.get("is_pii")),
            is_sensitive_pii=bool(a.get("is_sensitive_pii")),
            storage_envs=a.get("storage_envs") or [],
            cross_border_transfer=bool(a.get("cross_border_transfer")),
        )
        db.add(asset)
        db.flush()
        for t in a.get("tables") or []:
            table = DataTable(asset_id=asset.id, table_name=t.get("table_name") or "")
            db.add(table)
            db.flush()
            for f in t.get("fields") or []:
                db.add(DataField(
                    table_id=table.id,
                    field_name=f.get("field_name") or "",
                    field_type=f.get("field_type") or "string",
                    need_encrypt=bool(f.get("need_encrypt")),
                    need_mask=bool(f.get("need_mask")),
                    mask_rule=f.get("mask_rule"),
                ))

    role_map: dict[str, int] = {}
    for r in data.get("roles") or []:
        if not isinstance(r, dict):
            continue
        row = Role(
            project_id=project.id, uid=r.get("uid"), name=r.get("name") or "",
            role_type=r.get("role_type") or "",
            user_count_estimate=r.get("user_count_estimate"),
        )
        db.add(row)
        db.flush()
        if r.get("uid"):
            role_map[r["uid"]] = row.id

    resource_map: dict[str, int] = {}
    for r in data.get("resources") or []:
        if not isinstance(r, dict):
            continue
        row = Resource(
            project_id=project.id, uid=r.get("uid"), name=r.get("name") or "",
            resource_type=r.get("resource_type") or "",
            criticality=r.get("criticality") or "",
        )
        db.add(row)
        db.flush()
        if r.get("uid"):
            resource_map[r["uid"]] = row.id

    for e in data.get("permission_entries") or []:
        if not isinstance(e, dict):
            continue
        role_id = role_map.get(e.get("role_uid"))
        resource_id = resource_map.get(e.get("resource_uid"))
        if role_id is None or resource_id is None:
            continue  # 基线内引用断裂的条目不预填, 不阻断建档
        db.add(PermissionEntry(
            role_id=role_id, resource_id=resource_id,
            action=e.get("action") or "read",
            requires_approval=bool(e.get("requires_approval")),
        ))

    for ep in data.get("api_endpoints") or []:
        if not isinstance(ep, dict):
            continue
        db.add(ApiEndpoint(
            project_id=project.id, uid=ep.get("uid"), name=ep.get("name") or "",
            path=ep.get("path") or "", method=ep.get("method") or "GET",
            auth_required=bool(ep.get("auth_required", True)),
            public_exposed=bool(ep.get("public_exposed")),
            sensitive_asset_ids=[],  # 旧主键引用不继承, 以 uid 关联为准(#151 原则)
            sensitive_asset_uids=ep.get("sensitive_asset_uids") or [],
            rate_limit=ep.get("rate_limit"),
        ))

    db.commit()
    counts = {
        "data_assets": len(data.get("data_assets") or []),
        "roles": len(role_map),
        "resources": len(resource_map),
        "api_endpoints": len(data.get("api_endpoints") or []),
    }
    return counts
