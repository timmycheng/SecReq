# -*- coding: utf-8 -*-
"""扫描整改回归: 项目编码不可用于路径穿越(创建时校验 + 输出目录清洗兜底)。"""
from pathlib import Path

import pytest
from pydantic import ValidationError

from schemas.project import ProjectCreate
from services.pipeline import project_output_dir


def test_project_code_rejects_path_chars():
    """创建项目时拒绝路径分隔符/盘符/相对路径片段。"""
    for bad in ("../evil", "a/b", "a\\b", "C:win", ".."):
        with pytest.raises(ValidationError):
            ProjectCreate(name="x", code=bad)


def test_project_code_allows_normal_values():
    """常规编码(含中文)不受影响。"""
    assert ProjectCreate(name="x", code="PRJ-IBANK-2026").code == "PRJ-IBANK-2026"
    assert ProjectCreate(name="x", code="网关项目A").code == "网关项目A"


def test_project_output_dir_sanitizes_traversal():
    """存量库可能存在未校验编码, 输出目录侧必须兜底清洗。"""
    base = Path("output")
    for hostile in ("../../evil", "..\\..\\win", "C:evil", ".."):
        safe = project_output_dir(base, hostile)
        assert safe.parent == base
        assert ".." not in safe.name
        assert ":" not in safe.name
    assert project_output_dir(base, "PRJ-IBANK-2026") == base / "PRJ-IBANK-2026"
    assert project_output_dir(base, "网关项目A") == base / "网关项目A"
    assert project_output_dir(base, "").name == "project"
