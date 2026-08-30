# -*- coding: utf-8 -*-
"""规则引擎容错: 单条模板配置有误时跳过该模板, 不中断整轮生成。

背景: `_match_regulatory_triggers` / `_match_permissions` / `_match_policy_baseline`
遇到未知 rule_key 会抛 RuleEngineError。若不做收敛, 一条坏配置会让整个项目
的生成 500, 其余 60 条模板全部失效 —— 典型例子是早前 docstring 声明过、
但从未实现的 `saas_finance` 报送规则。
"""
from conftest import add_base_project
from rules import RuleEngine, load_knowledge_base
from rules.context import RequirementContext
from rules.loader import RequirementTemplate

BAD_ID = "SEC-TST-999"
BAD_RULE_KEY = "saas_finance"


def _template(trigger_type: str, trigger: dict, tid: str = BAD_ID) -> RequirementTemplate:
    """构造一条结构合法、但规则配置有误的模板(绕过 loader 校验直接注入)。"""
    return RequirementTemplate(
        id=tid,
        trigger_type=trigger_type,
        trigger=trigger,
        title="测试: 配置有误的模板",
        description="用于验证坏配置被跳过而非中断整轮生成",
        priority="medium",
        asvs_ref=None,
        acceptance_criteria="无",
        suggested_phase="design",
        trigger_reason="测试",
        regulatory_ref=[{"file": "测试文件", "clause": "无", "summary": "测试"}],
        enabled=True,
    )


def _engine_with(*templates) -> RuleEngine:
    kb = load_knowledge_base()
    kb.templates.extend(templates)
    return RuleEngine(kb)


def test_baseline_knowledge_base_has_no_config_error(session):
    """前置断言: 知识库本身干净, 否则后面的跳过断言无意义。"""
    project = add_base_project(session)
    session.flush()
    engine = RuleEngine(load_knowledge_base())
    engine.generate(RequirementContext.from_db(session, project.id))
    assert engine.skipped == []


def test_unknown_rule_key_is_skipped_not_fatal(session):
    """未知 rule_key 跳过该模板, 其余模板照常产出。"""
    project = add_base_project(session)
    session.flush()

    clean = RuleEngine(load_knowledge_base())
    baseline = clean.generate(RequirementContext.from_db(session, project.id))

    engine = _engine_with(
        _template("regulatory_trigger",
                  {"type": "regulatory_trigger", "rule_key": BAD_RULE_KEY})
    )
    result = engine.generate(RequirementContext.from_db(session, project.id))

    assert len(engine.skipped) == 1
    assert engine.skipped[0]["template_id"] == BAD_ID
    assert BAD_RULE_KEY in engine.skipped[0]["reason"]
    # 其余模板照常产出, 规模与干净知识库一致
    assert len(result) == len(baseline)


def test_unknown_trigger_type_is_skipped(session):
    """未知 trigger_type 跳过, 不抛 KeyError。"""
    project = add_base_project(session)
    session.flush()

    engine = _engine_with(_template("bogus_type", {"type": "bogus_type"}))
    engine.generate(RequirementContext.from_db(session, project.id))

    assert len(engine.skipped) == 1
    assert engine.skipped[0]["template_id"] == BAD_ID
    assert "未知触发器类型" in engine.skipped[0]["reason"]


def test_skipped_resets_between_runs(session):
    """skipped 每次 generate 重置, 复用引擎实例时不累积。"""
    project = add_base_project(session)
    session.flush()

    engine = _engine_with(
        _template("regulatory_trigger",
                  {"type": "regulatory_trigger", "rule_key": BAD_RULE_KEY})
    )
    for _ in range(3):
        engine.generate(RequirementContext.from_db(session, project.id))
        assert len(engine.skipped) == 1, "skipped 应在每次 generate 时重置"


def test_disabled_template_not_in_skipped(session):
    """停用的模板是正常跳过, 不计入 skipped(那是配置错误专用通道)。"""
    project = add_base_project(session)
    session.flush()

    tpl = _template("regulatory_trigger",
                    {"type": "regulatory_trigger", "rule_key": BAD_RULE_KEY})
    tpl.enabled = False
    engine = _engine_with(tpl)
    engine.generate(RequirementContext.from_db(session, project.id))

    assert engine.skipped == []
