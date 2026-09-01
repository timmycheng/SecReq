# -*- coding: utf-8 -*-
"""API接口 / 合规 / SBOM漏洞联动 维度规则测试。"""
import pytest

from conftest import add_base_project, gen_for
from models import ApiEndpoint, DataAsset, SbomComponent, VulnerabilityRecord
from rules import RuleEngine


@pytest.fixture()
def engine():
    return RuleEngine.load()


# ── API 接口规则 ────────────────────────────────────────

def test_public_endpoint_triggers_defense_in_depth(session, engine):
    project = add_base_project(session)
    ep = ApiEndpoint(project_id=project.id, name="转账接口", path="/api/v1/transfers",
                     method="POST", public_exposed=True, rate_limit="100 QPS/IP")
    session.add(ep)

    reqs = [r for r in gen_for(session, project, engine) if r.template_id == "SEC-V13-503"]
    assert len(reqs) == 1
    assert "POST /api/v1/transfers" in reqs[0].description
    assert "100" in reqs[0].description  # 限流阈值渲染


def test_anonymous_endpoint_flagged_for_assessment(session, engine):
    project = add_base_project(session)
    session.add_all([
        ApiEndpoint(project_id=project.id, name="牌价查询", path="/api/v1/rates",
                    method="GET", auth_required=False, public_exposed=True),
        ApiEndpoint(project_id=project.id, name="内部客户查询", path="/api/v1/cust",
                    method="GET", auth_required=True, public_exposed=False),
    ])

    anon = [r for r in gen_for(session, project, engine) if r.template_id == "SEC-V13-504"]
    assert len(anon) == 1
    assert "牌价查询" in anon[0].trigger_reason


def test_sensitive_asset_association_renders_names(session, engine):
    project = add_base_project(session)
    asset = DataAsset(project_id=project.id, name="银行账户信息", data_type="financial_account",
                      classification="机密")
    session.add(asset)
    session.flush()
    session.add(ApiEndpoint(project_id=project.id, name="客户信息查询",
                            path="/api/v1/customers", method="GET",
                            sensitive_asset_uids=[asset.uid]))

    (req,) = [r for r in gen_for(session, project, engine) if r.template_id == "SEC-V8-405"]
    assert "银行账户信息" in req.description


# ── 合规映射规则 ────────────────────────────────────────

def test_compliance_targets_fire_corresponding_rules(session, engine):
    project = add_base_project(session)
    project.compliance_targets = ["djcp_l3", "pipl"]

    tpl_ids = {r.template_id for r in gen_for(session, project, engine)}
    assert "SEC-CMP-701" in tpl_ids  # 等保三级
    assert "SEC-CMP-702" in tpl_ids  # 个保法
    assert "SEC-CMP-703" not in tpl_ids  # 未勾选 PCI-DSS


def test_no_compliance_targets_no_rules(session, engine):
    project = add_base_project(session)  # compliance_targets 默认空
    tpl_ids = {r.template_id for r in gen_for(session, project, engine)}
    assert not any(tid.startswith("SEC-CMP") for tid in tpl_ids)


# ── SBOM 漏洞联动(第二批接入OSV前的引擎侧测试) ─────────

def _add_component_with_vuln(session, project, name, version,
                             cve, severity, score, fix=None):
    comp = SbomComponent(project_id=project.id, layer="library",
                         name=name, version=version, purl=f"pkg:generic/{name}@{version}")
    session.add(comp)
    session.flush()
    vuln = VulnerabilityRecord(
        component_id=comp.id, cve_id=cve, severity=severity,
        cvss_score=score, affected_range=f"<{fix or '99.9'}", fix_version=fix,
        summary="模拟漏洞记录",
    )
    session.add(vuln)
    return comp


def test_high_severity_creates_requirement_per_component(session, engine):
    """每个含高危及以上漏洞的组件各出一条需求, 聚合CVE清单。"""
    project = add_base_project(session)
    c1 = _add_component_with_vuln(session, project, "log4j-core", "2.14.1",
                                  "CVE-2021-44228", "critical", 10.0, fix="2.17.1")
    c2 = _add_component_with_vuln(session, project, "lodash", "4.17.15",
                                  "CVE-2021-23337", "high", 7.2, fix="4.17.21")
    _add_component_with_vuln(session, project, "clean-lib", "1.0.0",
                             "CVE-2020-0001", "low", 3.0)  # 低危不触发

    reqs = [r for r in gen_for(session, project, engine) if r.template_id == "SEC-V14-801"]
    assert len(reqs) == 2
    by_src = {r.source_entity_id: r for r in reqs}
    assert "CVE-2021-44228" in by_src[c1.id].description
    assert "CVE-2021-23337" in by_src[c2.id].description
    assert all(r.priority == "critical" for r in reqs)


def test_placeholder_rendering_is_strict(tmp_path):
    """缺占位符取值时报错并指明模板与变量名。"""
    from rules.engine import RuleEngineError, render
    with pytest.raises(RuleEngineError) as exc:
        render("需要 {{missing_value}} 占位", {}, "SEC-T-001")
    assert "missing_value" in str(exc.value)
