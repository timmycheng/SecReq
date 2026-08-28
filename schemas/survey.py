# -*- coding: utf-8 -*-
"""Step2 定级问卷请求/响应模型。"""
from pydantic import BaseModel, Field


class SurveyAnswerIn(BaseModel):
    question_id: str
    option_id: str


class SurveySubmitIn(BaseModel):
    """整卷提交。final_level 为人工修正值, 不传则引擎使用系统建议定级。"""

    answers: list[SurveyAnswerIn] = Field(default_factory=list)
    final_level: str | None = None
    manual_adjust_note: str | None = None


class SurveyOut(BaseModel):
    project_id: int
    answers_json: list[dict] = []
    suggested_level: str | None
    suggested_reason: str | None
    final_level: str | None
    manual_adjust_note: str | None
    effective_level: str = ""
