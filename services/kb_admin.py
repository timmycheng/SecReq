# -*- coding: utf-8 -*-
"""知识库/题库管理(走查整改: 策略可视化、可配置)。

安全中心在系统管理页编辑, 写回 YAML 文件:
- 写入前自动备份(<文件名>.bak-<时间戳>);
- 写入后用 loader 全量校验, 不合法则回滚并报错;
- 定级题库同理, 校验走 services.grading.load_question_bank。
"""
import copy
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

# 各触发类目的合法 condition 键与 rule_key 取值, 与 rules/engine.py 的判定分支一一对应。
# 意图: 条件键/rule_key 写错在保存时就被拦截, 而不是生成时静默不命中(引擎对未知
# condition 键是 elif 链不匹配 → 空结果, 对未知 rule_key 才会报错跳过)。
_TRIGGER_CONDITION_SPEC: dict[str, dict] = {
    "feature_category": {"keys": {"category"}},
    "permission_rule": {"keys": {"rule_key"},
                        "rule_keys": {"critical_action_without_approval", "sod_conflict",
                                      "super_admin_exists", "always"}},
    "auth_method": {"keys": {"method"}},
    "policy_baseline": {"keys": {"rule_key"},
                        "rule_keys": {"password_strength", "lockout_threshold",
                                      "session_timeout", "force_2fa", "always"}},
    "data_asset": {"keys": {"classification", "level", "min_level", "c3_tag",
                            "is_sensitive_pii", "mask_fields_any_of",
                            "has_log_leakage_risk", "cross_border"}},
    "api_endpoint": {"keys": {"public_exposed", "auth_required", "touches_sensitive_asset"}},
    "compliance": {"keys": {"target"}},
    "vulnerability": {"keys": {"severity_range"}},
    "regulatory_trigger": {"keys": {"rule_key"},
                           "rule_keys": {"l5_data_exists", "cross_border_exists",
                                         "mobile_app_type", "ai_feature", "final_level_l3",
                                         "sensitive_pii_exists", "djcp_l3_filing"}},
    "external_system": {"keys": {"sensitive_only"}},
    "license_risk": {"keys": {"risk"}},
}


def validate_trigger_condition(trigger: dict | None) -> None:
    """按触发类目校验 condition 键与 rule_key 取值, 不合法即抛 ValueError。"""
    ttype = (trigger or {}).get("type")
    spec = _TRIGGER_CONDITION_SPEC.get(ttype)
    if spec is None:
        return  # trigger.type 枚举校验由写回后的 loader 全量校验兜底
    condition = trigger.get("condition") or {}
    unknown = set(condition) - spec["keys"]
    if unknown:
        raise ValueError(
            f"触发类目「{ttype}」不支持条件键: {sorted(unknown)}, 合法键: {sorted(spec['keys'])}"
            "(写错的键会导致模板静默不命中)")
    rule_keys = spec.get("rule_keys")
    if rule_keys and "rule_key" in condition and condition["rule_key"] not in rule_keys:
        raise ValueError(
            f"触发类目「{ttype}」的 rule_key 非法: {condition['rule_key']}, "
            f"合法取值: {sorted(rule_keys)}")


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

    语义无变化时不写盘(#81): 编辑弹窗原样保存(仅回显未编辑)是最常见操作,
    safe_dump 全量重写会重排整个文件并丢失头注释 —— 比较解析前后的结构,
    值全部相等则跳过写盘与备份。
    """
    path = DEFAULT_KB_PATH
    data = _load_raw(path)
    row = next((t for t in data.get("templates", []) if t.get("id") == template_id), None)
    if row is None:
        raise ValueError(f"模板不存在: {template_id}")
    updates = {k: v for k, v in changes.items() if k in EDITABLE_TEMPLATE_FIELDS}
    if not updates:
        return row
    if "trigger" in updates:
        validate_trigger_condition(updates["trigger"])
    new_data = copy.deepcopy(data)
    target = next(t for t in new_data.get("templates", []) if t.get("id") == template_id)
    for key, value in updates.items():
        target[key] = value
    # 语义无变化(值全部相等) → 不写盘: safe_dump 全量重写会重排文件并丢注释,
    # 文本比对因注释存在永远不等, 所以比较解析后的结构
    if new_data == data:
        return row
    serialized = yaml.safe_dump(new_data, allow_unicode=True, sort_keys=False)
    backup = _backup(path)
    _guard_write_path(path, DEFAULT_KB_PATH)
    path.write_text(serialized, encoding="utf-8", newline="\n")
    _validate_or_restore(path, backup, load_knowledge_base)
    return target


def add_template(template: dict) -> dict:
    """新增知识库模板(完整字段), 返回新模板。写入目标固定为 DEFAULT_KB_PATH。"""
    path = DEFAULT_KB_PATH
    template.pop("_path", None)  # 兼容历史调用残留: 该字段不写入 YAML
    validate_trigger_condition(template.get("trigger"))
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
