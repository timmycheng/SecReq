# -*- coding: utf-8 -*-
"""评审门禁与用户 API 模型。"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    username: str
    display_name: str
    employee_id: str | None
    role: str


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=50)


class LoginOut(BaseModel):
    username: str
    display_name: str
    employee_id: str | None
    role: str
    role_label: str


class GateCheck(BaseModel):
    status: str            # passed / blocked / not_available
    missing: list[str] = []


class GateOut(BaseModel):
    id: int
    gate_type: str
    gate_label: str
    status: str
    status_label: str
    latest_verb: str
    submitted_at: datetime | None = None
    reviewed_at: datetime | None = None
    submitter: str | None = None
    reviewer: str | None = None
    reviewer_conclusion: str | None = None
    reviewer_opinion: str | None = None
    final_reviewer: str | None = None
    final_opinion: str | None = None
    final_reviewed_at: datetime | None = None
    version_hash: str | None = None
    check: GateCheck
    evidence_count: int = 0


class ReviewActionIn(BaseModel):
    """评审动作: 评审员 approve/reject/request_change; 负责人终审 sign/reject。"""

    action: str
    opinion: str = Field(min_length=1, max_length=2000)


class EvidenceOut(BaseModel):
    id: int
    actor: str
    actor_role: str
    action: str
    action_label: str
    timestamp: datetime
    ip: str | None
    comment: str | None
    prev_hash: str
    curr_hash: str


class ChainVerifyOut(BaseModel):
    gate_id: int
    valid: bool
    count: int
    broken_at: int | None = None
