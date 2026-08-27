# -*- coding: utf-8 -*-
"""知识库 YAML 完整性与加载器测试。"""
import pytest

from rules import KnowledgeBaseError, load_knowledge_base


@pytest.fixture(scope="module")
def kb():
    return load_knowledge_base()


def test_load_succeeds(kb):
    assert kb.templates, "知识库不应为空"
    assert kb.version


def test_template_ids_unique_and_wellformed(kb):
    ids = [t.id for t in kb.templates]
    assert len(ids) == len(set(ids)), "模板 id 存在重复"
    for tid in ids:
        assert tid.startswith("SEC-") and tid.split("-")[-1].isdigit(), f"id 格式异常: {tid}"


def test_all_eight_trigger_dimensions_covered(kb):
    types = {t.trigger_type for t in kb.templates}
    expected = {
        "feature_category", "permission_rule", "auth_method", "policy_baseline",
        "data_asset", "api_endpoint", "compliance", "vulnerability",
    }
    assert expected <= types, f"知识库缺少维度: {expected - types}"


def test_every_step3_category_has_rule(kb):
    """DESIGN.md 要求功能触发规则覆盖全部 Step3 受控枚举分类。"""
    import shared.constants as C
    covered = {
        t.trigger["condition"]["category"]
        for t in kb.by_trigger("feature_category")
        if isinstance(t.trigger.get("condition"), dict)
    }
    missing = set(C.FEATURE_CATEGORIES) - covered
    assert not missing, f"以下功能分类没有规则模板: {missing}"


def test_templates_have_chinese_content(kb):
    for t in kb.templates:
        for text in (t.title, t.description, t.acceptance_criteria):
            assert text and any("\u4e00" <= ch <= "\u9fff" for ch in text), \
                f"{t.id} 中文内容缺失"


def test_asvs_ref_present_for_all(kb):
    no_ref = [t.id for t in kb.templates if not t.asvs_ref]
    assert not no_ref, f"以下模板缺少 ASVS 引用: {no_ref}"


def test_broken_kb_reports_errors(tmp_path):
    bad = tmp_path / "kb.yml"
    bad.write_text(
        """
meta: {version: "0.0"}
templates:
  - id: BAD-001
    trigger: {type: nonsense_trigger}
  - id: SEC-V1-001
    trigger: {type: compliance, target: djcp_l3}
""",
        encoding="utf-8",
    )
    with pytest.raises(KnowledgeBaseError) as exc:
        load_knowledge_base(bad)
    # 汇总报错而不是遇到第一个就停
    assert "nonsense_trigger" in str(exc.value)


def test_placeholder_braces_balanced(kb):
    """占位符必须成对闭合, 防止维护者手误。"""
    for t in kb.templates:
        for text in (t.title, t.description, t.acceptance_criteria, t.trigger_reason):
            assert text.count("{{") == text.count("}}"), f"{t.id} 存在未闭合的占位符"
