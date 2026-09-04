# -*- coding: utf-8 -*-
"""认证方式 + 密码/会话策略基线测试。"""
from conftest import add_base_project, gen_for
from models import AuthConfig, GradingSurvey


def test_sms_otp_method_triggers_code_lifecycle_rule(session, engine):
    project = add_base_project(session)
    session.add(AuthConfig(project_id=project.id, auth_methods=["password", "sms_otp"]))
    sms = [r for r in gen_for(session, project, engine) if r.template_id == "SEC-V2-002"]
    assert len(sms) == 1
    assert sms[0].source_entity_type == "auth_config"


def test_unselected_auth_method_no_trigger(session, engine):
    project = add_base_project(session)
    session.add(AuthConfig(project_id=project.id, auth_methods=["password"]))
    reqs = gen_for(session, project, engine)
    assert all(r.template_id != "SEC-V2-002" for r in reqs)   # 短信OTP规则不触发
    assert all(r.template_id != "SEC-V2-003" for r in reqs)   # 生物识别规则不触发


def test_biometric_triggers(session, engine):
    project = add_base_project(session)
    session.add(AuthConfig(project_id=project.id, auth_methods=["biometric"]))
    reqs = gen_for(session, project, engine)
    assert any(r.template_id == "SEC-V2-003" for r in reqs)


def test_password_strength_uses_explicit_config_over_defaults(session, engine):
    project = add_base_project(session)
    session.add(GradingSurvey(project_id=project.id, suggested_level="二级", answers_json=[]))
    session.add(
        AuthConfig(
            project_id=project.id, auth_methods=["password"],
            pwd_min_length=12, pwd_complexity=4, pwd_valid_days=45,
            pwd_history_limit=5,
        )
    )
    (req,) = [r for r in gen_for(session, project, engine) if r.template_id == "SEC-V2-005"]
    for token in ("12", "45"):
        assert token in req.description
    assert "等保二级" in req.description


def test_password_policy_falls_back_to_grading_default(session, engine):
    """未显式配置时按定级推导默认基线: 三级→10位/4类/60天。"""
    project = add_base_project(session)
    session.add(GradingSurvey(project_id=project.id, suggested_level="三级", answers_json=[]))
    session.add(AuthConfig(project_id=project.id, auth_methods=["password"]))
    (req,) = [r for r in gen_for(session, project, engine) if r.template_id == "SEC-V2-005"]
    assert "{{" not in req.description
    assert "等保三级" in req.description


def test_lockout_and_session_rules_render_threshold(session, engine):
    project = add_base_project(session)
    session.add(
        AuthConfig(project_id=project.id, auth_methods=["password"],
                   lockout_threshold=3, session_timeout_min=20)
    )
    reqs = gen_for(session, project, engine)
    lock = next(r for r in reqs if r.template_id == "SEC-V2-006")
    timeout = next(r for r in reqs if r.template_id == "SEC-V3-001")
    assert "3" in lock.description
    assert "20" in timeout.description


def test_force_2fa_small_scale_not_flagged_skips(session, engine):
    """小规模且未勾选强制双因素 → 不出强制2FA需求。"""
    project = add_base_project(session)
    project.user_scale = "under_1k"
    session.add(GradingSurvey(project_id=project.id, suggested_level="一级", answers_json=[]))
    session.add(AuthConfig(project_id=project.id, auth_methods=["password"], force_2fa=False))
    reqs = gen_for(session, project, engine)
    assert all(r.template_id != "SEC-V2-004" for r in reqs)


def test_force_2fa_large_scale_recommends(session, engine):
    """用户规模>10万 → 强制2FA建议(DESIGN.md 模块2 规则3)。"""
    project = add_base_project(session)
    project.user_scale = "over_1m"
    session.add(GradingSurvey(project_id=project.id, suggested_level="二级", answers_json=[]))
    session.add(AuthConfig(project_id=project.id, auth_methods=["password"], force_2fa=False))
    mfa = next(r for r in gen_for(session, project, engine) if r.template_id == "SEC-V2-004")
    assert "100万" in mfa.description
