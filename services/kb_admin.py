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


def _guard_write_path(path: Path, expected: Path) -> None:
    """写盘前守卫: 目标必须与预期的知识库/题库常量路径一致。

    防穿越兜底: 即便未来调用链再次引入可变路径, 写入也会被拦截并报错,
    而不是落写到预期之外的位置。
    """
    if Path(path).resolve() != Path(expected).resolve():
        raise ValueError(f"拒绝写入非预期路径: {path} (期望 {expected})")


def _validate_or_restore(path: Path, backup: Path, validator) -> None:
    try:
        validator(path)
    except Exception as exc:
        shutil.copy2(backup, path)  # 回滚
        raise ValueError(f"保存后校验失败, 已回滚: {exc}") from exc


def update_template(template_id: str, changes: dict) -> dict:
    """更新单条知识库模板(按 id 定位), 返回更新后的模板。

    写入目标固定为 DEFAULT_KB_PATH(安全中心管理页唯一可编辑知识库),
    不接受调用方指定路径, 避免路径被外部输入左右。
    """
    path = DEFAULT_KB_PATH
    backup = _backup(path)
    data = _load_raw(path)
    row = next((t for t in data.get("templates", []) if t.get("id") == template_id), None)
    if row is None:
        raise ValueError(f"模板不存在: {template_id}")
    for key, value in changes.items():
        if key in EDITABLE_TEMPLATE_FIELDS:
            row[key] = value
    _guard_write_path(path, DEFAULT_KB_PATH)
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8", newline="\n")
    _validate_or_restore(path, backup, load_knowledge_base)
    return row


def add_template(template: dict) -> dict:
    """新增知识库模板(完整字段), 返回新模板。写入目标固定为 DEFAULT_KB_PATH。"""
    path = DEFAULT_KB_PATH
    template.pop("_path", None)  # 兼容历史调用残留: 该字段不写入 YAML
    data = _load_raw(path)
    ids = {t.get("id") for t in data.get("templates", [])}
    if template.get("id") in ids:
        raise ValueError(f"模板 id 已存在: {template.get('id')}")
    data["templates"].append(template)
    backup = _backup(path)
    _guard_write_path(path, DEFAULT_KB_PATH)
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8", newline="\n")
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
    _guard_write_path(QUESTION_BANK_PATH, QUESTION_BANK_PATH)
    QUESTION_BANK_PATH.write_text(
        yaml.safe_dump(bank, allow_unicode=True, sort_keys=False),
        encoding="utf-8", newline="\n")
    try:
        load_question_bank(QUESTION_BANK_PATH)  # 结构校验(缓存键含 mtime, 立即重新加载)
    except Exception as exc:
        shutil.copy2(backup, QUESTION_BANK_PATH)
        raise ValueError(f"题库保存后校验失败, 已回滚: {exc}") from exc
