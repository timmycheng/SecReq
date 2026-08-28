# -*- coding: utf-8 -*-
"""知识库 YAML 加载与完整性校验。"""
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# 知识库默认路径(项目根/rules/knowledge_base.yml)
DEFAULT_KB_PATH = Path(__file__).resolve().parent / "knowledge_base.yml"

ALLOWED_TRIGGER_TYPES = {
    "feature_category",
    "permission_rule",
    "auth_method",
    "policy_baseline",
    "data_asset",
    "api_endpoint",
    "compliance",
    "vulnerability",
    "regulatory_trigger",
}

REQUIRED_TEMPLATE_FIELDS = [
    "id", "trigger", "title", "description", "priority",
    "suggested_phase", "acceptance_criteria", "trigger_reason", "regulatory_ref",
]

_REQ_ID_PATTERN = re.compile(r"^SEC-[A-Z0-9]+-\d{3}$")
_PLACEHOLDER_PATTERN = re.compile(r"\{\{\s*(\w+)\s*\}\}")


class KnowledgeBaseError(Exception):
    """知识库结构不合法时抛出, 汇总全部错误便于安全中心维护者一次修复。"""


@dataclass
class Template:
    """单条需求模板的运行时形态(已做字段规范化)。"""

    id: str
    trigger_type: str
    trigger: dict
    title: str
    description: str
    priority: str
    asvs_ref: str | None
    acceptance_criteria: str
    suggested_phase: str
    trigger_reason: str
    regulatory_ref: list[dict] = field(default_factory=list)

    @property
    def placeholders(self) -> set[str]:
        """模板文本中引用的全部占位符名。"""
        names: set[str] = set()
        for text in (self.title, self.description, self.acceptance_criteria, self.trigger_reason):
            names |= set(_PLACEHOLDER_PATTERN.findall(text or ""))
        return names

    @property
    def regulatory_files(self) -> list[str]:
        """引用的监管文件名列表(文档合规依据列与完整性校验用)。"""
        return [str(ref.get("file", "")) for ref in self.regulatory_ref if ref.get("file")]


@dataclass
class KnowledgeBase:
    version: str
    templates: list[Template] = field(default_factory=list)

    def by_trigger(self, trigger_type: str) -> list[Template]:
        return [t for t in self.templates if t.trigger_type == trigger_type]


def _clean(text) -> str:
    """YAML 块标量(|/>)转为单行段落文本, 便于渲染与后续写入 Word。"""
    if text is None:
        return ""
    return str(text).strip()


def _normalize_regulatory_ref(raw) -> list[dict]:
    """合规出处规范化: 列表内每项保留 file/clause/summary/note 四个字符串键。

    任何缺 file 或结构不合法的条目使整组视为空(触发必填校验报错)。
    """
    if not isinstance(raw, list) or not raw:
        return []
    normalized: list[dict] = []
    for entry in raw:
        if not isinstance(entry, dict):
            return []
        file_name = _clean(entry.get("file"))
        if not file_name:
            return []
        normalized.append({
            "file": file_name,
            "clause": _clean(entry.get("clause")),
            "summary": _clean(entry.get("summary")),
            "note": _clean(entry.get("note")),
        })
    return normalized


def load_knowledge_base(path: str | Path | None = None) -> KnowledgeBase:
    """加载并校验知识库; 校验失败抛 KnowledgeBaseError 并列出全部问题。"""
    path = Path(path or DEFAULT_KB_PATH)
    if not path.exists():
        raise KnowledgeBaseError(f"知识库文件不存在: {path}")

    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict) or not isinstance(raw.get("templates"), list):
        raise KnowledgeBaseError("知识库结构错误: 缺少顶层 templates 列表")

    errors: list[str] = []
    seen_ids: set[str] = set()
    meta = raw.get("meta") or {}
    kb = KnowledgeBase(version=str(meta.get("version", "unknown")))

    for idx, item in enumerate(raw["templates"], start=1):
        label = f"templates[{idx}]"
        if not isinstance(item, dict):
            errors.append(f"{label}: 必须是映射结构")
            continue

        tid = _clean(item.get("id"))
        if not _REQ_ID_PATTERN.match(tid):
            errors.append(f"{label}: id『{tid}』不符合 SEC-XXX-000 格式")
        if tid in seen_ids:
            errors.append(f"{label}: id『{tid}』重复")
        seen_ids.add(tid)

        trigger = item.get("trigger") if isinstance(item.get("trigger"), dict) else None
        if trigger is None:
            errors.append(f"{label}({tid}): 缺少 trigger 映射")
            continue
        if trigger.get("type") not in ALLOWED_TRIGGER_TYPES:
            errors.append(
                f"{label}({tid}): 未知的 trigger.type『{trigger.get('type')}』, "
                f"允许值: {sorted(ALLOWED_TRIGGER_TYPES)}"
            )
            continue

        missing = [k for k in REQUIRED_TEMPLATE_FIELDS if not _clean(item.get(k))]
        if missing:
            errors.append(f"{label}({tid or '?'}): 缺少必填字段 {missing}")
            continue

        reg_refs = _normalize_regulatory_ref(item.get("regulatory_ref"))
        if not reg_refs:
            errors.append(
                f"{label}({tid}): regulatory_ref 必须是非空列表, 每项含 file(监管文件名)"
            )
            continue

        kb.templates.append(
            Template(
                id=tid,
                trigger_type=trigger["type"],
                trigger=trigger,
                title=_clean(item["title"]),
                description=_clean(item.get("description")),
                priority=_clean(item.get("priority")) or "medium",
                asvs_ref=_clean(item.get("asvs_ref")) or None,
                acceptance_criteria=_clean(item.get("acceptance_criteria")),
                suggested_phase=_clean(item.get("suggested_phase")),
                trigger_reason=_clean(item.get("trigger_reason")),
                regulatory_ref=reg_refs,
            )
        )

    if errors:
        raise KnowledgeBaseError("知识库校验失败:\n" + "\n".join(errors))
    if not kb.templates:
        raise KnowledgeBaseError("知识库为空: templates 列表没有任何条目")
    return kb
