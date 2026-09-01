# -*- coding: utf-8 -*-
"""种子数据(个人网银系统)→ 规则引擎 集成测试。

对应 DESIGN.md 第一批验收目标: 种子数据能生成合理的需求清单。
"""
import pytest

from rules import RuleEngine
from rules.context import RequirementContext
from services.seed_data import seed_demo_project


@pytest.fixture(scope="module")
def seeded():
    """整个模块共用一份种子库(只读校验)。"""
    from models import make_engine
    from sqlalchemy.orm import sessionmaker

    engine = make_engine("sqlite:///:memory:")
    from models import init_db
    init_db(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    project = seed_demo_project(session)
    yield session, project, RuleEngine.load().generate(
        RequirementContext.from_db(session, project.id)
    )
    session.close()


def test_seed_inputs_complete(seeded):
    """设计要求的输入规模: 12功能/6资产/5角色8资源/10组件/4接口。"""
    from models import (
        ApiEndpoint, DataAsset, Feature, Resource, Role, SbomComponent,
        PermissionEntry,
    )
    session, project, _ = seeded
    assert session.query(Feature).filter_by(project_id=project.id).count() == 12
    assert session.query(DataAsset).filter_by(project_id=project.id).count() == 6
    assert session.query(Role).filter_by(project_id=project.id).count() == 5
    assert session.query(Resource).filter_by(project_id=project.id).count() == 8
    assert session.query(SbomComponent).filter_by(project_id=project.id).count() == 10
    assert session.query(ApiEndpoint).filter_by(project_id=project.id).count() == 4
    assert session.query(PermissionEntry).join(
        Role, PermissionEntry.role_id == Role.id
    ).filter(Role.project_id == project.id).count() >= 15  # 矩阵有效覆盖


def test_log4j_component_seeded_for_vulnerability_demo(seeded):
    from models import SbomComponent
    session, project, _ = seeded
    log4j = (
        session.query(SbomComponent)
        .filter_by(project_id=project.id, name="log4j-core")
        .one()
    )
    assert log4j.version == "2.14.1"  # 故意保留的旧版本, 第二批OSV演示用
    assert log4j.purl.endswith("log4j-core@2.14.1")


def test_grading_baseline_propagates_into_requirements(seeded):
    """定级结果作为策略基线: 等保三级文案应出现在口令强度需求中。"""
    _, _, reqs = seeded
    strength = next(r for r in reqs if r.template_id == "SEC-V2-005")
    assert "等保三级" in strength.description
    # Step6 显式配置(10位/4类/60天)渲染进描述
    assert "10" in strength.description and "60" in strength.description


def test_seed_survey_answers_usable_by_grading_api(seeded):
    """种子问卷答案必须是 {question_id, option_id} 当前形态(#98 回归护栏)。

    旧 {question_id, answer} 形态缺 option_id: 前端 Step1 整卷提交会被
    SurveyAnswerIn 必填校验 422 拦下, 演示流程第一步就卡死。
    """
    from models import GradingSurvey
    from services.grading import grade_survey, load_questions
    session, project, _ = seeded
    survey = session.query(GradingSurvey).filter_by(project_id=project.id).one()
    valid_options = {q.id: {o["id"] for o in q.options} for q in load_questions()}
    answers = survey.answers_json
    assert answers, "种子项目应有问卷答案"
    for a in answers:
        assert set(a) >= {"question_id", "option_id"}, f"答案缺字段: {a}"
        assert a["option_id"] in valid_options.get(a["question_id"], set()), \
            f"option_id 不在题库选项中: {a}"
    result = grade_survey([
        {"question_id": a["question_id"], "option_id": a["option_id"]} for a in answers
    ])
    assert result.suggested_level == "三级"


def test_generates_reasonable_requirement_volume(seeded):
    """首批(未接OSV漏洞查询)应产出约50-70条需求。"""
    _, _, reqs = seeded
    assert 40 <= len(reqs) <= 80, f"实际生成 {len(reqs)} 条"


def test_all_requirements_traceable_and_rendered(seeded):
    """可追溯性约束 + 占位符全部渲染干净。"""
    _, _, reqs = seeded
    for r in reqs:
        assert r.source_entity_type and r.source_entity_id is not None, \
            f"{r.req_id} 缺少来源追溯"
        assert "{{" not in r.title + r.description + r.acceptance_criteria + r.trigger_reason, \
            f"{r.req_id} 存在未渲染占位符"
        assert r.asvs_ref, f"{r.req_id} 缺少 ASVS 引用"
        assert r.priority in ("critical", "high", "medium", "low")


def test_all_dimensions_represented(seeded):
    _, _, reqs = seeded
    categories = {r.category for r in reqs}
    expected = {"功能安全", "权限与访问控制", "认证与会话", "口令与会话策略",
                "数据安全", "接口安全", "合规要求"}
    assert expected <= categories, f"缺少维度: {expected - categories}"


def test_priority_distribution_skews_high(seeded):
    """银行核心系统的高危属性应反映在优先级分布上。"""
    _, _, reqs = seeded
    critical_or_high = sum(1 for r in reqs if r.priority in ("critical", "high"))
    assert critical_or_high / len(reqs) > 0.5


def test_key_rules_hit_expected_instances(seeded):
    _, _, reqs = seeded
    tpl_count = {}
    for r in reqs:
        tpl_count[r.template_id] = tpl_count.get(r.template_id, 0) + 1

    # 上传4条规则齐发; 支付幂等命中2个支付功能; 机密资产3份
    assert tpl_count.get("SEC-V12-001") == 1          # 只有头像上传一个上传功能
    assert tpl_count.get("SEC-V12-002") == 1
    assert tpl_count.get("SEC-V11-201") == 2          # 转账汇款 + 交易撤销退款
    assert tpl_count.get("SEC-V6-001") == 3           # 三份机密级资产
    assert tpl_count.get("SEC-V13-503") == 3          # 三个公网暴露接口
    assert tpl_count.get("SEC-V13-504") == 2          # 两个免认证接口
    assert tpl_count.get("SEC-V4-004") == 1           # super_admin 角色存在
    assert "SEC-V1-001" in tpl_count                  # 集中式访问控制恒触发
