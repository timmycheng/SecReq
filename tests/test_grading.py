# -*- coding: utf-8 -*-
"""定级问卷打分服务单元测试。"""
import pytest

from services.grading import GradingError, grade_survey, load_questions


def answers_of(*pairs):
    return [{"question_id": q, "option_id": o} for q, o in pairs]


def test_score_sum_maps_to_level_two():
    """分数路径: 总分11(未达三级12阈值, 未触发组合规则) → 建议二级。"""
    result = grade_survey(answers_of(
        ("Q1", "B"), ("Q2", "A"), ("Q3", "C"), ("Q4", "D"), ("Q5", "B")))
    assert result.suggested_level == "二级"
    assert result.total_score == 11
    assert result.max_score == 17
    assert len(result.details) == 5


def test_sensitive_pii_plus_funds_forces_level_three():
    """Q1=C(sensitive_pii) 且 Q2=C(funds) → 无论低分题如何, 建议三级。"""
    result = grade_survey(answers_of(
        ("Q1", "C"), ("Q2", "C"), ("Q3", "A"), ("Q4", "B"), ("Q5", "A")))
    assert result.suggested_level == "三级"
    assert set(result.matched_tags) == {"sensitive_pii", "funds"}
    assert "组合判定" in result.suggested_reason or "累计得分" in result.suggested_reason


def test_low_risk_answers_grade_one():
    result = grade_survey(answers_of(
        ("Q1", "A"), ("Q2", "A"), ("Q3", "A"), ("Q4", "A"), ("Q5", "A")))
    assert result.suggested_level == "一级"
    assert result.total_score == 1


def test_mid_answers_grade_two():
    result = grade_survey(answers_of(
        ("Q1", "B"), ("Q2", "B"), ("Q3", "B"), ("Q4", "B"), ("Q5", "A")))
    assert result.suggested_level == "二级"


def test_missing_answer_rejected():
    with pytest.raises(GradingError):
        grade_survey([{"question_id": "Q1", "option_id": "A"}])


def test_unknown_option_rejected():
    with pytest.raises(GradingError):
        grade_survey(answers_of(("Q1", "Z"), ("Q2", "A"), ("Q3", "A"), ("Q4", "A"), ("Q5", "A")))


def test_duplicate_answer_rejected():
    with pytest.raises(GradingError):
        grade_survey(answers_of(
            ("Q1", "A"), ("Q1", "B"), ("Q2", "A"), ("Q3", "A"), ("Q4", "A"), ("Q5", "A")))


def test_question_bank_shape():
    questions = load_questions()
    assert [q.id for q in questions] == ["Q1", "Q2", "Q3", "Q4", "Q5"]
    for question in questions:
        assert question.title
        for opt in question.options:
            assert isinstance(opt["score"], int)
