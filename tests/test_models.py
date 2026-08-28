# -*- coding: utf-8 -*-
"""数据模型约束测试。"""
import pytest
from sqlalchemy.exc import IntegrityError

from conftest import add_base_project
from models import PermissionEntry, Resource, Role


def test_permission_entry_unique_constraint(session):
    """UNIQUE(role_id, resource_id, action) 防止矩阵格子重复登记。"""
    project = add_base_project(session)
    role = Role(project_id=project.id, name="管理员", role_type="privileged")
    res = Resource(project_id=project.id, name="参数配置", resource_type="system_config")
    session.add_all([role, res])
    session.flush()
    session.add(PermissionEntry(role_id=role.id, resource_id=res.id,
                                action="update", requires_approval=False))
    session.flush()
    session.add(PermissionEntry(role_id=role.id, resource_id=res.id,
                                action="update", requires_approval=True))
    with pytest.raises(IntegrityError):
        session.flush()


def test_grading_survey_effective_level_prefers_manual(session):
    from models import GradingSurvey
    project = add_base_project(session)
    survey = GradingSurvey(project_id=project.id, suggested_level="二级",
                           final_level=None, answers_json=[])
    assert survey.effective_level() == "二级"
    survey.final_level = "三级"
    assert survey.effective_level() == "三级"


def test_feature_category_match(session):
    from models import Feature
    project = add_base_project(session)
    f = Feature(project_id=project.id, name="转账", categories=["payment", "sms_email"])
    assert f.matches_any_category("payment")
    assert not f.matches_any_category("file_upload")


def test_classification_enum_is_jrt0197_five_levels():
    """防呆: 分级枚举使用 JR/T 0197-2020 五级 code, 与知识库条件一致。"""
    import shared.constants as C
    assert C.DATA_LEVELS == [
        "5级_重要数据", "4级_C3鉴别信息", "3级_C2主要信息", "2级_C1次要信息", "1级_公开数据",
    ]
    # 老四级映射完整
    assert C.LEGACY_CLASSIFICATION_MAP == {
        "公开": "1级_公开数据", "内部": "2级_C1次要信息",
        "敏感": "3级_C2主要信息", "机密": "4级_C3鉴别信息",
    }
    # 数值等级: 5 最高
    assert C.level_rank("5级_重要数据") == 5 and C.level_rank("1级_公开数据") == 1
    assert C.level_rank("机密") == 4  # 老值按迁移映射折算
