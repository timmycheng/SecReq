# -*- coding: utf-8 -*-
"""改造验收用例(批次1): JR/T 0197 五级、regulatory_ref、监管报送触发器。

对应《改造 Prompt》第四部分验收标准:
2. 迁移脚本: 机密→4级、生物识别附加C3标签、legacy_classification 留痕;
3. 任取一条生成需求 regulatory_ref 非空且引用文件名真实存在;
4. 种子项目监管报送类需求 ≥ 4 条, 且 L4 不触发L5报送、无外采SaaS不触发外包评定;
   另覆盖: L5/C3 联动规则、报送类置顶。
"""
import pytest

from conftest import add_base_project, gen_for
from models import DataAsset, init_db, make_engine
from rules import RuleEngine, load_knowledge_base
from rules.context import RequirementContext
from services.classification_migration import migrate_legacy_classification
from services.seed_data import DEMO_PROJECT_CODE, seed_demo_project

# 行业真实存在的监管文件白名单(禁止编造)
REAL_REGULATORY_FILES = {
    "银行保险机构数据安全管理办法",
    "中华人民共和国数据安全法",
    "中华人民共和国网络安全法",
    "中华人民共和国个人信息保护法",
    "数据出境安全评估办法",
    "个人金融信息保护技术规范",
    "金融数据安全 数据安全分级指南",
    "网上银行系统信息安全通用规范",
    "金融行业网络安全等级保护实施指引",
    "金融科技创新安全通用规范",
    "商业银行信息科技风险管理指引",
    "银行保险机构信息科技外包风险监管办法",
    "关于加强银行业保险业移动互联网应用程序管理的通知",
    "关于加强商业银行互联网助贷业务管理的通知",
    "信息安全等级保护管理办法",
    "信息安全技术 网络安全等级保护基本要求(GB/T 22239-2019)",
    "金融监管总局信息科技监管要求",
    "支付卡行业数据安全标准(PCI DSS v4.0)",
}


# ── 验收2: 老 4 级迁移 ────────────────────────────────────

def test_migration_maps_confidential_to_l4_and_tags_c3():
    """机密→4级; 生物识别+敏感PII 附加C3标签; legacy 留痕; 幂等。"""
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    from sqlalchemy.orm import sessionmaker
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()

    project = seed_demo_project(session)
    # 种子按新五级直接写入; 构造一条"未迁移"的老数据
    legacy_asset = DataAsset(
        project_id=project.id, name="老机密指纹库", data_type="biometric",
        classification="机密", is_pii=True, is_sensitive_pii=True,
    )
    session.add(legacy_asset)
    session.commit()

    stats = migrate_legacy_classification(session)
    assert stats["migrated"] >= 1

    session.refresh(legacy_asset)
    assert legacy_asset.classification == "4级_C3鉴别信息"
    assert legacy_asset.legacy_classification == "机密"
    assert legacy_asset.c3_tag is True  # 生物识别类鉴别信息

    # 再次执行幂等
    stats2 = migrate_legacy_classification(session)
    assert stats2["migrated"] == 0 and stats2["already_migrated"] >= 1
    session.close()


def test_migration_maps_all_legacy_levels():
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    from sqlalchemy.orm import sessionmaker
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    project = seed_demo_project(session)
    for old, new in [
        ("公开", "1级_公开数据"), ("内部", "2级_C1次要信息"),
        ("敏感", "3级_C2主要信息"), ("机密", "4级_C3鉴别信息"),
    ]:
        session.add(DataAsset(
            project_id=project.id, name=f"资产{old}", data_type="business_data",
            classification=old, is_pii=True, is_sensitive_pii=False,
        ))
    session.commit()
    migrate_legacy_classification(session)
    rows = {
        a.legacy_classification: a.classification
        for a in session.query(DataAsset).filter(DataAsset.legacy_classification.isnot(None))
        if a.name.startswith("资产")
    }
    assert rows == {
        "公开": "1级_公开数据", "内部": "2级_C1次要信息",
        "敏感": "3级_C2主要信息", "机密": "4级_C3鉴别信息",
    }
    session.close()


# ── 验收3: regulatory_ref 完整性 ─────────────────────────

def test_all_templates_have_regulatory_ref_with_real_files():
    kb = load_knowledge_base()
    assert len(kb.templates) >= 38
    for tpl in kb.templates:
        assert tpl.regulatory_ref, f"{tpl.id} 缺少 regulatory_ref"
        for ref in tpl.regulatory_ref:
            assert ref["file"] in REAL_REGULATORY_FILES, \
                f"{tpl.id} 引用了白名单外的文件: {ref['file']}"


def test_generated_requirement_carries_regulatory_ref():
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    from sqlalchemy.orm import sessionmaker
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    project = add_base_project(session)
    session.add(DataAsset(
        project_id=project.id, name="银行卡账户", data_type="financial_account",
        classification="4级_C3鉴别信息", is_pii=True, is_sensitive_pii=True,
    ))
    reqs = gen_for(session, project, RuleEngine.load())
    sampled = [r for r in reqs if r.template_id == "SEC-V6-001"]
    assert sampled, "4级资产应触发 SEC-V6-001"
    req = sampled[0]
    assert req.regulatory_ref, "生成需求必须带合规出处"
    for ref in req.regulatory_ref:
        assert ref["file"] in REAL_REGULATORY_FILES
    session.close()


# ── 验收4: 种子项目监管报送 ≥4 且不误触 ─────────────────

@pytest.fixture(scope="module")
def seed_requirements():
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    from sqlalchemy.orm import sessionmaker
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    project = seed_demo_project(session)
    reqs = RuleEngine.load().generate(RequirementContext.from_db(session, project.id))
    yield session, project, reqs
    session.close()


def test_seed_fires_at_least_four_regulatory_filings(seed_requirements):
    _, _, reqs = seed_requirements
    regulatory = [r for r in reqs if r.category == "监管报送"]
    assert len(regulatory) >= 4, f"监管报送类应≥4条, 实得{len(regulatory)}"
    templates = {r.template_id for r in regulatory}
    # 触发: 出境评估(有跨境资产)/投产变更报告(三级)/PIA(敏感PII)/等保测评备案(三级)
    assert "SEC-REG-002" in templates
    assert "SEC-REG-006" in templates
    assert "SEC-REG-007" in templates
    assert "SEC-REG-008" in templates


def test_seed_does_not_misfire_l5_or_saas_filings(seed_requirements):
    """L4 资产不触发 L5 报送; 无外采SaaS/境外供应商不触发外包评定。"""
    _, project, reqs = seed_requirements
    templates = {r.template_id for r in reqs}
    assert "SEC-REG-001" not in templates, "种子无5级资产, 不应触发重要数据备案"
    assert "SEC-REG-003" not in templates, "种子无外采SaaS, 不应触发外包评定"
    assert "SEC-REG-004" not in templates, "种子是Web系统, 不应触发App台账"
    assert "SEC-REG-005" not in templates, "种子无AI功能, 不应触发创新申报"
    assert project.code == DEMO_PROJECT_CODE


def test_regulatory_requirements_sorted_top(seed_requirements):
    _, _, reqs = seed_requirements
    regulatory = [i for i, r in enumerate(reqs) if r.category == "监管报送"]
    first_non_reg = next(
        i for i, r in enumerate(reqs) if r.category != "监管报送"
    )
    assert max(regulatory) < first_non_reg, "监管报送类需求必须置顶"


# ── 五级联动规则 ─────────────────────────────────────────

def _make_session_with_asset(**asset_kwargs):
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    from sqlalchemy.orm import sessionmaker
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    project = add_base_project(session)
    params = dict(
        project_id=project.id, name="测试资产", data_type="business_data",
        classification="1级_公开数据",
    )
    params.update(asset_kwargs)
    session.add(DataAsset(**params))
    session.commit()
    return session, project


def test_l5_asset_triggers_reporting_and_annual_assessment():
    session, project = _make_session_with_asset(
        name="全行客户统计", classification="5级_重要数据")
    reqs = gen_for(session, project, RuleEngine.load())
    templates = {r.template_id for r in reqs}
    assert {"SEC-REG-001", "SEC-DS5-001", "SEC-DS5-002", "SEC-DS5-003"} <= templates
    session.close()


def test_l4_asset_does_not_trigger_l5_rules_but_triggers_l4_protection():
    session, project = _make_session_with_asset(
        name="账户鉴别信息", classification="4级_C3鉴别信息")
    reqs = gen_for(session, project, RuleEngine.load())
    templates = {r.template_id for r in reqs}
    assert "SEC-V6-001" in templates        # 4级触发三重防护
    assert "SEC-DS5-001" not in templates   # 不触发 L5 专属
    assert "SEC-REG-001" not in templates
    session.close()


def test_c3_tag_trips_transport_cache_log_rules():
    session, project = _make_session_with_asset(
        name="指纹模板", data_type="biometric", classification="4级_C3鉴别信息",
        is_pii=True, is_sensitive_pii=True, c3_tag=True)
    reqs = gen_for(session, project, RuleEngine.load())
    templates = {r.template_id for r in reqs}
    assert {"SEC-C3-001", "SEC-C3-002", "SEC-C3-003"} <= templates
    session.close()


def test_regulatory_trigger_extra_cases():
    # App 台账
    session, project = _make_session_with_asset()
    project.type = "mobile_app"
    reqs = gen_for(session, project, RuleEngine.load())
    assert any(r.template_id == "SEC-REG-004" for r in reqs)
    session.close()

    # 境外供应商触发出境申报
    session, project = _make_session_with_asset()
    project.offshore_vendor = True
    reqs = gen_for(session, project, RuleEngine.load())
    assert any(r.template_id == "SEC-REG-002" for r in reqs)
    session.close()
