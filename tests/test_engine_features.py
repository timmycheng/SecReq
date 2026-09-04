# -*- coding: utf-8 -*-
"""功能分类触发规则测试。"""
from conftest import add_base_project, gen_for
from models import Feature


def test_upload_feature_triggers_all_four_rules(session, engine):
    project = add_base_project(session)
    f1 = Feature(project_id=project.id, name="头像上传", categories=["file_upload"])
    session.add(f1)
    session.flush()

    reqs = gen_for(session, project, engine)
    upload = [r for r in reqs if r.template_id.startswith("SEC-V12")]
    assert len(upload) == 4
    # 每条独立需求可追溯到同一 feature 实体, 占位符全部渲染干净
    assert {r.source_entity_type for r in upload} == {"feature"}
    assert {r.source_entity_id for r in upload} == {f1.id}
    assert len({r.req_id for r in reqs}) == len(reqs), "req_id 必须唯一"
    assert all("{{" not in (r.title + r.description) for r in upload)


def test_same_rule_multiple_features_generate_independent_requirements(session, engine):
    """DESIGN.md 附注: 3个上传功能应生成3条独立需求, 各关联各自 source_entity_id。"""
    project = add_base_project(session)
    feats = [
        Feature(project_id=project.id, name=f"上传功能{i}", categories=["file_upload"])
        for i in range(3)
    ]
    session.add_all(feats)

    reqs = [
        r for r in gen_for(session, project, engine)
        if r.template_id == "SEC-V12-001"
    ]
    assert len(reqs) == 3
    assert {r.req_id for r in reqs} == {"SEC-V12-001", "SEC-V12-001-02", "SEC-V12-001-03"}
    assert {r.source_entity_id for r in reqs} == {f.id for f in feats}


def test_category_not_present_generates_nothing(session, engine):
    project = add_base_project(session)
    session.add(Feature(project_id=project.id, name="普通查询", categories=["search"]))
    reqs = gen_for(session, project, engine)
    assert all(r.template_id != "SEC-V11-201" for r in reqs)  # 支付幂等规则不触发


def test_multi_category_feature_hits_each_dimension_once(session, engine):
    project = add_base_project(session)
    session.add(
        Feature(project_id=project.id, name="理财搜索与讨论", categories=["search", "comment_ugc"])
    )
    tpl_ids = {r.template_id for r in gen_for(session, project, engine)}
    assert "SEC-V5-104" in tpl_ids   # search → 防SQL注入
    assert "SEC-V5-103" in tpl_ids   # comment_ugc → XSS净化


def test_trigger_reason_mentions_feature_name(session, engine):
    project = add_base_project(session)
    session.add(Feature(project_id=project.id, name="对账单下载", categories=["file_download"]))
    (req,) = [r for r in gen_for(session, project, engine) if r.template_id == "SEC-V5-101"]
    assert "对账单下载" in req.trigger_reason
    assert "对账单下载" in req.description
