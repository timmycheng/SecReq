# -*- coding: utf-8 -*-
"""评估轮次增量对比: 按 (template_id, source_entity_uid) 对齐两轮安全需求。

- 新增: 本轮有、上轮无;
- 移除: 上轮有、本轮无(含本轮被置为 obsolete 的场景对侧呈现);
- 变更: 同键但 标题/描述/优先级/验收标准/类目/合规出处 任一变化。
"""
from datetime import datetime

from sqlalchemy.orm import Session

from models import Project, SecurityRequirement

_EPOCH = datetime.min

# 参与变更判定的字段: 内容变化即视为需求变更
_CHANGED_FIELDS = ("title", "description", "priority", "acceptance_criteria",
                   "category", "regulatory_ref")

# 变更字段中文名(#176): 前端对比弹窗与 Word 差异章节共用同一口径
FIELD_LABELS = {
    "title": "需求标题",
    "description": "需求内容",
    "priority": "优先级",
    "acceptance_criteria": "验收标准",
    "category": "类目",
    "regulatory_ref": "合规出处",
}


def _field_display(value) -> str:
    """字段值的前后值展示形态: 合规出处(结构化列表)拼成可读句, 其余转字符串。"""
    if value is None:
        return ""
    if isinstance(value, list):
        parts = []
        for ref in value:
            if isinstance(ref, dict):
                parts.append(f"《{ref.get('file', '')}》{ref.get('clause') or ''}")
            else:
                parts.append(str(ref))
        return "; ".join(p for p in parts if p.strip("《》"))
    return str(value)


def find_previous_round(db: Session, project: Project,
                        against: int | None = None) -> Project | None:
    """定位对比基准轮: 显式指定 against 时要求同系统且非本轮; 否则取同系统中
    早于本轮的最近一个已生成项目。"""
    if against is not None:
        candidate = db.get(Project, against)
        if (candidate is None or candidate.id == project.id
                or candidate.system_id is None
                or candidate.system_id != project.system_id):
            return None
        return candidate
    if project.system_id is None:
        return None
    candidates = (
        db.query(Project)
        .filter(
            Project.system_id == project.system_id,
            Project.id != project.id,
            Project.status == "generated",
        )
        .order_by(Project.created_at.desc(), Project.id.desc())
        .all()
    )
    current_key = (project.created_at or _EPOCH, project.id)
    for cand in candidates:
        if (cand.created_at or _EPOCH, cand.id) < current_key:
            return cand
    return None


def _row(req: SecurityRequirement) -> dict:
    return {
        "req_id": req.req_id,
        "title": req.title,
        "priority": req.priority,
        "category": req.category,
        "source_label": req.source_label,
        "status": req.status,
        "suggested_phase": req.suggested_phase,
    }


def _key(req: SecurityRequirement) -> tuple[str, str]:
    return (req.template_id, req.source_entity_uid or "")


def diff_requirements(db: Session, current: Project, previous: Project) -> dict:
    cur_rows = db.query(SecurityRequirement).filter_by(project_id=current.id).all()
    prev_rows = db.query(SecurityRequirement).filter_by(project_id=previous.id).all()
    cur_map = {_key(r): r for r in cur_rows}
    prev_map = {_key(r): r for r in prev_rows}

    added = [r for key, r in cur_map.items() if key not in prev_map]
    removed = [r for key, r in prev_map.items() if key not in cur_map]

    changed = []
    for key, cur in cur_map.items():
        prev = prev_map.get(key)
        if prev is None:
            continue
        diff_fields = [
            field for field in _CHANGED_FIELDS
            if getattr(cur, field) != getattr(prev, field)
        ]
        if diff_fields:
            changed.append({
                "fields": diff_fields,
                # 字段级前后值(#176): 变更常由 描述/验收标准 变化触发,
                # 只给字段名看不出「到底什么变了」
                "field_values": {
                    field: {
                        "label": FIELD_LABELS[field],
                        "previous": _field_display(getattr(prev, field)),
                        "current": _field_display(getattr(cur, field)),
                    }
                    for field in diff_fields
                },
                "previous": _row(prev),
                "current": _row(cur),
            })

    by_priority = lambda rows: sorted(  # noqa: E731
        rows, key=lambda r: {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(r.priority, 9))
    return {
        "previous_project": {
            "project_id": previous.id,
            "project_name": previous.name,
            "project_code": previous.code,
            "created_at": previous.created_at.isoformat() if previous.created_at else None,
        },
        "added": [_row(r) for r in by_priority(added)],
        "removed": [_row(r) for r in by_priority(removed)],
        "changed": changed,
        "summary": {
            "current_total": len(cur_rows),
            "previous_total": len(prev_rows),
            "added": len(added),
            "removed": len(removed),
            "changed": len(changed),
        },
    }
