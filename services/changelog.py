# -*- coding: utf-8 -*-
"""CHANGELOG.md 解析服务(#55): 供系统管理「更新日志」页展示。

与 scripts/check_version.py 同一章节约定(`## [X.Y.Z] - 日期`, 无 v 前缀)。
解析为结构化块(小标题/列表/引用/段落), 前端零依赖渲染; 行内 **加粗** 与
`代码` 由前端处理。仓库受控格式, 不做完整 Markdown 解析。
"""
import re
from pathlib import Path

SECTION_RE = re.compile(r"^## \[(\d+\.\d+\.\d+)\] - (\d{4}-\d{2}-\d{2})\s*$")
SUB_RE = re.compile(r"^### (.+)$")
LIST_RE = re.compile(r"^[-*] (.+)$")
QUOTE_RE = re.compile(r"^> ?(.*)$")


def _parse_section(lines: list[str]) -> list[dict]:
    """把一个版本章节的正文行解析为块列表。"""
    blocks: list[dict] = []
    para: list[str] = []

    def flush_para():
        if para:
            blocks.append({"kind": "para", "text": " ".join(x.strip() for x in para)})
            para.clear()

    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            flush_para()
            continue
        m = SUB_RE.match(line)
        if m:
            flush_para()
            blocks.append({"kind": "h3", "text": m.group(1).strip()})
            continue
        m = LIST_RE.match(line.strip())
        if m:
            flush_para()
            blocks.append({"kind": "list_item", "text": m.group(1).strip()})
            continue
        m = QUOTE_RE.match(line.strip())
        if m:
            flush_para()
            blocks.append({"kind": "quote", "text": m.group(1).strip()})
            continue
        if line.strip().startswith("|"):
            flush_para()
            # 表格行原样保留, 交前端按 | 切分(跳过分隔行)
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                continue
            blocks.append({"kind": "table_row", "cells": cells})
            continue
        para.append(line.strip())
    flush_para()
    return blocks


def parse_changelog(text: str) -> list[dict]:
    """把 CHANGELOG 全文解析为版本列表(新版本在前), 无章节时返回空列表。"""
    versions: list[dict] = []
    current: dict | None = None
    body: list[str] = []
    for line in text.splitlines():
        m = SECTION_RE.match(line.strip())
        if m:
            if current is not None:
                current["blocks"] = _parse_section(body)
                versions.append(current)
            current = {"version": m.group(1), "date": m.group(2)}
            body = []
        elif current is not None:
            body.append(line)
    if current is not None:
        current["blocks"] = _parse_section(body)
        versions.append(current)
    return versions


def load_changelog(path: Path | None = None) -> list[dict]:
    """读取并解析仓库根 CHANGELOG.md; 文件缺失返回空列表(前端空态兜底)。"""
    target = path or (Path(__file__).resolve().parent.parent / "CHANGELOG.md")
    if not target.is_file():
        return []
    try:
        return parse_changelog(target.read_text(encoding="utf-8"))
    except OSError:
        return []
