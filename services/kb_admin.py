# -*- coding: utf-8 -*-
"""知识库/题库管理(走查整改: 策略可视化、可配置)。

安全中心在系统管理页编辑, 写回 YAML 文件:
- 写入前自动备份(<文件名>.bak-<时间戳>);
- 写入后用 loader 全量校验, 不合法则回滚并报错;
- 定级题库同理, 校验走 services.grading.load_question_bank。
"""
import shutil
from datetime import datetime
from pathlib import Path

import yaml

from rules.loader import DEFAULT_KB_PATH, load_knowledge_base

QUESTION_BANK_PATH = Path(__file__).resolve().parent.parent / "rules" / "grading_questions.yml"

# 管理页可编辑的模板字段(其余字段原样保留)
EDITABLE_TEMPLATE_FIELDS = [
    "id", "trigger", "title", "description", "priority", "asvs_ref",
    "suggested_phase", "acceptance_criteria", "trigger_reason",
    "regulatory_ref", "enabled",
]


def _backup(path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = path.with_suffix(f".bak-{stamp}{path.suffix}")
    shutil.copy2(path, backup)
    return backup


def _load_raw(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _validate_or_restore(path: Path, backup: Path, validator) -> None:
    try:
        validator(path)
    except Exception as exc:
        shutil.copy2(backup, path)  # 回滚
        raise ValueError(f"保存后校验失败, 已回滚: {exc}") from exc


def update_template(template_id: str, changes: dict) -> dict:
    """更新单条知识库模板(按 id 定位), 返回更新后的模板。"""
    path = Path(changes.pop("_path", None) or DEFAULT_KB_PATH)
    backup = _backup(path)
    data = _load_raw(path)
    row = next((t for t in data.get("templates", []) if t.get("id") == template_id), None)
    if row is None:
        raise ValueError(f"模板不存在: {template_id}")
    for key, value in changes.items():
        if key in EDITABLE_TEMPLATE_FIELDS:
            row[key] = value
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
    _validate_or_restore(path, backup, load_knowledge_base)
    return row


def add_template(template: dict) -> dict:
    """新增知识库模板(完整字段), 返回新模板。"""
    path = Path(template.pop("_path", None) or DEFAULT_KB_PATH)
    data = _load_raw(path)
    ids = {t.get("id") for t in data.get("templates", [])}
    if template.get("id") in ids:
        raise ValueError(f"模板 id 已存在: {template.get('id')}")
    data["templates"].append(template)
    backup = _backup(path)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
    _validate_or_restore(path, backup, load_knowledge_base)
    return template


def list_templates() -> list[dict]:
    """知识库清单(带 enabled 与触发类型, 供管理页展示)。"""
    kb = load_knowledge_base()
    return [
        {
            "id": t.id,
            "trigger_type": t.trigger_type,
            "trigger": t.trigger,
            "title": t.title,
            "description": t.description,
            "priority": t.priority,
            "asvs_ref": t.asvs_ref,
            "acceptance_criteria": t.acceptance_criteria,
            "suggested_phase": t.suggested_phase,
            "trigger_reason": t.trigger_reason,
            "regulatory_ref": t.regulatory_ref,
            "enabled": t.enabled,
        }
        for t in kb.templates
    ]


def load_question_bank_raw() -> dict:
    with open(QUESTION_BANK_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def save_question_bank(bank: dict) -> None:
    """整体保存定级题库, 保存后走打分加载器校验。"""
    from services.grading import load_question_bank

    backup = _backup(QUESTION_BANK_PATH)
    with open(QUESTION_BANK_PATH, "w", encoding="utf-8", newline="\n") as f:
        yaml.safe_dump(bank, f, allow_unicode=True, sort_keys=False)
    try:
        load_question_bank(QUESTION_BANK_PATH)  # 结构校验(缓存键含 mtime, 立即重新加载)
    except Exception as exc:
        shutil.copy2(backup, QUESTION_BANK_PATH)
        raise ValueError(f"题库保存后校验失败, 已回滚: {exc}") from exc
