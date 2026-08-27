# -*- coding: utf-8 -*-
"""OSV 漏洞查询服务测试。

用 httpx.MockTransport 模拟 api.osv.dev, 覆盖: 结果规范化 / 24h 缓存 /
强制刷新 / 失败降级(不阻塞) / 与规则引擎的漏洞联动。
"""
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from conftest import add_base_project
from models import SbomComponent, VulnerabilityRecord
from rules import RuleEngine
from rules.context import RequirementContext
from services.osv import (
    OsvClient, _extract_ranges, _render_range, _score_to_severity,
    _resolve_severity, sync_vulnerabilities,
)

LOG4J_PURL = "pkg:maven/org.apache.logging.log4j/log4j-core@2.14.1"
FASTJSON_PURL = "pkg:maven/com.alibaba/fastjson@1.2.70"

# 仿真的 OSV 原始响应片段(log4shell 多窗口受影响区间)
GHSA_LOG4J = {
    "id": "GHSA-jfh8-c2jp-5v3q",
    "summary": "Apache Log4j2 JNDI注入远程代码执行漏洞(Log4Shell)",
    "aliases": ["CVE-2021-44228", "GHSA-pgx7-fr8w-m8wg"],
    "severity": [{"type": "CVSS_V3", "score": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H"}],
    "affected": [{
        "package": {"purl": LOG4J_PURL},
        "ranges": [{"type": "ECOSYSTEM", "events": [
            {"introduced": "2.0"}, {"fixed": "2.15.0"},
            {"introduced": "2.15.1"}, {"fixed": "2.17.0"},
        ]}],
    }],
    "database_specific": {"severity": "CRITICAL"},
}
# fastjson autoType 绕过(CVSS_SCORE 数值分 + MODERATE 别名覆盖单测)
CVE_FASTJSON = {
    "id": "GHSA-fastjson-test",
    "aliases": ["CVE-2022-25845"],
    "summary": "fastjson autoType未完全闭合导致远程代码执行",
    "severity": [{"type": "CVSS_SCORE", "score": "8.1"}],
    "affected": [{
        "ranges": [{"type": "ECOSYSTEM", "events": [
            {"introduced": "0"}, {"fixed": "2.0.0"},
        ]}],
    }],
}

NOW = datetime(2026, 8, 27, 10, 0, 0, tzinfo=timezone.utc)


class FakeOsv:
    """构造带请求记录的 MockTransport 客户端; payload 为 Exception 时模拟网络故障。"""

    def __init__(self, payload_by_purl: dict):
        self.calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            purl = json.loads(request.content)["package"]["purl"]
            self.calls.append(purl)
            payload = payload_by_purl.get(purl)
            if isinstance(payload, Exception):
                raise payload
            # 注意: json=None 在 httpx 里等价于"不传响应体", 必须显式给空 dict
            return httpx.Response(200, json=payload if payload is not None else {})

        self.client = OsvClient(transport=httpx.MockTransport(handler))


def _seed_components(session):
    project = add_base_project(session)
    comps = [
        SbomComponent(project_id=project.id, layer="library", name="log4j-core",
                      version="2.14.1", purl=LOG4J_PURL),
        SbomComponent(project_id=project.id, layer="library", name="fastjson",
                      version="1.2.70", purl=FASTJSON_PURL),
        SbomComponent(project_id=project.id, layer="frontend", name="vue",
                      version="3.3.4", purl="pkg:npm/vue@3.3.4"),
    ]
    session.add_all(comps)
    session.flush()
    return project, comps


# ────────────────────────── 规范化单测 ──────────────────────────


def test_normalize_prefers_cve_alias_and_critical_from_db_specific():
    nv = OsvClient.normalize(GHSA_LOG4J)
    assert nv.cve_id == "CVE-2021-44228"
    assert nv.severity == "critical"
    assert nv.cvss_score is None  # 向量串不强行估分
    assert nv.fix_version == "2.17.0"       # 取最后一个 fixed 端点


def test_normalize_multi_window_range_rendering():
    windows = _extract_ranges(GHSA_LOG4J)
    assert windows == [
        {"introduced": "2.0", "fixed": "2.15.0"},
        {"introduced": "2.15.1", "fixed": "2.17.0"},
    ]
    rendered = _render_range(windows)
    assert rendered == "≥2.0 且 <2.15.0；≥2.15.1 且 <2.17.0"


# 复刻 GHSA-jfh8-c2jp-5v3q 真实形态: 同一漏洞列出多个 Maven 坐标(主线+分支派生包)
REAL_WORLD_LOG4SHELL = {
    "id": "GHSA-jfh8-c2jp-5v3q",
    "aliases": ["CVE-2021-44228"],
    "summary": "Remote code injection in Log4j",
    "severity": [{"type": "CVSS_V3", "score": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H"}],
    "affected": [
        {  # 主线坐标(与组件同全限定名) — 共三条不同版本线
            "package": {"ecosystem": "Maven", "name": "org.apache.logging.log4j:log4j-core"},
            "ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "2.13.0"}, {"fixed": "2.15.0"}]}],
        },
        {
            "package": {"ecosystem": "Maven", "name": "org.apache.logging.log4j:log4j-core"},
            "ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "2.0-beta9"}, {"fixed": "2.3.1"}]}],
        },
        {
            "package": {"ecosystem": "Maven", "name": "org.apache.logging.log4j:log4j-core"},
            "ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "2.4"}, {"fixed": "2.12.2"}]}],
        },
        {  # 派生包坐标, 不应进入本组件的影响范围/修复版本判定
            "package": {"ecosystem": "Maven", "name": "com.guicedee.services:log4j-core"},
            "ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "0"}, {"last_affected": "1.2.1.2-jre17"}]}],
        },
        {  # 低版本线的 pax 分支, 其 fixed 不应盖过主线
            "package": {"ecosystem": "Maven", "name": "org.ops4j.pax.logging:pax-logging-log4j2"},
            "ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "2.0.0"}, {"fixed": "2.0.11"}]}],
        },
    ],
    "database_specific": {"severity": "CRITICAL"},
}


def test_normalize_filters_fork_coordinates_against_real_payload():
    """真实 log4shell 数据回归: 分支坐标被过滤, 修复版取包含目标版本的窗口端点。"""
    nv = OsvClient.normalize(
        REAL_WORLD_LOG4SHELL, target_purl=LOG4J_PURL, target_version="2.14.1"
    )
    assert nv.cve_id == "CVE-2021-44228"
    assert nv.severity == "critical"
    # 2.14.1 ∈ [2.13.0, 2.15.0) → 升级路径指向 2.15.0, 而非分支包的 2.0.11
    assert nv.fix_version == "2.15.0"
    assert nv.affected_range is not None
    assert "guicedee" not in nv.affected_range and "pax" not in nv.affected_range
    assert nv.affected_range.startswith("≥2.13.0 且 <2.15.0")

    # 无目标信息时兜底为全部条目, 但仍取数值最高的修复版
    nv_loose = OsvClient.normalize(REAL_WORLD_LOG4SHELL)
    assert nv_loose.fix_version is None or nv_loose.fix_version in ("2.15.0", "2.3.1", "2.12.2")


def test_normalize_score_number_and_open_ended_range():
    nv = OsvClient.normalize(CVE_FASTJSON)
    assert nv.cve_id == "CVE-2022-25845"
    assert nv.cvss_score == 8.1
    assert nv.severity == "high"
    assert nv.affected_range == "≥0 且 <2.0.0"

    # 真正的开放式窗口(只有 introduced, 无 fixed)
    open_vuln = {
        "id": "X", "aliases": ["CVE-2099-0001"],
        "affected": [{"ranges": [{"events": [{"introduced": "0"}]}]}],
    }
    nv_open = OsvClient.normalize(open_vuln)
    assert nv_open.affected_range == "≥0" and nv_open.fix_version is None


def test_cvss_score_severity_thresholds():
    assert _score_to_severity(9.8) == "critical"
    assert _score_to_severity(9.0) == "critical"
    assert _score_to_severity(7.5) == "high"
    assert _score_to_severity(7.0) == "high"
    assert _score_to_severity(6.9) == "medium"
    assert _score_to_severity(4.0) == "medium"
    assert _score_to_severity(3.9) == "low"
    assert _score_to_severity(None) == "unknown"


def test_moderate_alias_mapped_to_medium():
    assert _resolve_severity({"database_specific": {"severity": "MODERATE"}}, None) == "medium"
    # 未识别档位回落到分数划档
    vuln = {"database_specific": {"severity": "WEIRD"}, "severity": [{"type": "CVSS_SCORE", "score": "5.5"}]}
    assert _resolve_severity(vuln, 5.5) == "medium"


def test_summary_truncated():
    long_vuln = {"id": "X", "summary": "重" * 900}
    nv = OsvClient.normalize(long_vuln)
    assert len(nv.summary) <= 500 and nv.summary.endswith("…")


def test_severity_dedup_keeps_stricter_when_same_cve_listed_twice(session):
    """同一 CVE 出现在两条原始记录(如 GHSA+CVE 双编号互为别名)时只落一条, 取更严重档。"""
    import shared.constants as C
    from models import SbomComponent, VulnerabilityRecord
    from services.osv import _replace_component_vulns

    project = add_base_project(session)
    comp = SbomComponent(project_id=project.id, layer="library", name="fastjson",
                         version="1.2.70", purl=FASTJSON_PURL)
    session.add(comp)
    session.flush()

    low_dup = {
        "id": "GHSA-low-dup", "aliases": ["CVE-2022-25845"],
        "database_specific": {"severity": "LOW"},
    }
    records = _replace_component_vulns(session, comp, [dict(CVE_FASTJSON), low_dup])
    session.add_all(records)  # 该函数只负责构造, 入会话由调用方完成
    session.commit()

    rows = session.query(VulnerabilityRecord).filter_by(component_id=comp.id).all()
    assert [r.cve_id for r in rows] == ["CVE-2022-25845"]
    assert rows[0].severity == "high"


# ────────────────────────── 同步流程 ──────────────────────────


def _payloads_for_hit_all() -> dict:
    return {
        LOG4J_PURL: {"vulns": [GHSA_LOG4J]},
        FASTJSON_PURL: {"vulns": [dict(CVE_FASTJSON)]},
        "pkg:npm/vue@3.3.4": {},  # 无漏洞: 官方返回体不带 vulns 键
    }


def test_sync_inserts_normalized_records(session):
    project, comps = _seed_components(session)
    fake = FakeOsv(_payloads_for_hit_all())

    records, result = sync_vulnerabilities(
        session, comps, client=fake.client, now=NOW
    )

    assert sorted(result.updated) == ["fastjson", "log4j-core", "vue"]  # 首轮全部实查(含无结果的vue)
    assert result.cached == []
    assert not result.degraded

    log4j_records = [
        v for v in session.query(VulnerabilityRecord).all() if v.cve_id == "CVE-2021-44228"
    ]
    assert len(log4j_records) == 1
    rec = log4j_records[0]
    assert rec.severity == "critical"
    # 目标版本 2.14.1 落在 [2.13.0, 2.15.0) 窗口 → 指导升级到 2.15.0
    assert rec.fix_version == "2.15.0"
    assert "Log4Shell" in rec.summary

    fast = next(v for v in records if v.cve_id == "CVE-2022-25845")
    assert fast.cvss_score == 8.1
    assert fast.affected_range == "≥0 且 <2.0.0"

    comp = session.query(SbomComponent).filter_by(name="log4j-core").one()
    # SQLite 回读后 tzinfo 丢失, 比较 naive 形态
    assert comp.last_osv_query_at.replace(tzinfo=None) == NOW.replace(tzinfo=None)


def test_cache_within_ttl_skips_network(session):
    project, comps = _seed_components(session)
    fake = FakeOsv(_payloads_for_hit_all())
    sync_vulnerabilities(session, comps, client=fake.client, now=NOW)
    first_count = len(fake.calls)

    _, result = sync_vulnerabilities(
        session, comps, client=fake.client, now=NOW + timedelta(hours=23)
    )
    assert len(fake.calls) == first_count      # 零额外网络请求
    assert set(result.cached) == {"log4j-core", "fastjson", "vue"}
    assert result.updated == []


def test_expired_cache_or_force_refreshes(session):
    project, comps = _seed_components(session)
    fake = FakeOsv(_payloads_for_hit_all())
    sync_vulnerabilities(session, comps, client=fake.client, now=NOW)

    _, result = sync_vulnerabilities(
        session, comps, client=fake.client, now=NOW + timedelta(hours=25), force=True
    )
    assert set(result.updated) >= {"log4j-core", "fastjson"}
    all_rows = session.query(VulnerabilityRecord).all()
    cves = [v.cve_id for v in all_rows]
    assert len(cves) == len(set(cves)), "重复刷新后不得出现重复 CVE 记录"
    assert len([v for v in all_rows if v.cve_id == "CVE-2021-44228"]) == 1


def test_failure_degrades_gracefully_and_keeps_old_records(session):
    project, comps = _seed_components(session)
    fast = next(c for c in comps if c.name == "fastjson")
    session.add(VulnerabilityRecord(
        component_id=fast.id, cve_id="CVE-OLD-STALE", severity="medium",
    ))
    session.commit()

    fake = FakeOsv({
        LOG4J_PURL: {"vulns": [GHSA_LOG4J]},
        FASTJSON_PURL: httpx.ConnectError("network unreachable"),
    })
    records, result = sync_vulnerabilities(session, comps, client=fake.client, now=NOW)

    assert result.failed == ["fastjson"]
    assert result.degraded is True
    assert result.summary_text().startswith("OSV查询: ") and "查询失败" in result.summary_text()
    assert "log4j-core" in result.updated       # 其余组件照常完成 → 不阻塞
    assert any(v.cve_id == "CVE-OLD-STALE" for v in records)   # 失败组件旧记录保留待重试


def test_vulnerability_engine_rule_fires_after_sync(session):
    """规则引擎 vulnerability 触发器消费同步产物: 命中组件生成整改需求。"""
    from models import SecurityRequirement

    project, comps = _seed_components(session)
    fake = FakeOsv(_payloads_for_hit_all())
    sync_vulnerabilities(session, comps, client=fake.client, now=NOW)

    engine = RuleEngine.load()
    reqs = engine.generate(RequirementContext.from_db(session, project.id))

    vuln_reqs = [r for r in reqs if r.template_id.startswith("SEC-V14-801")]
    by_comp = {r.source_entity_id: r for r in vuln_reqs}
    names = {
        c.name: c.id for c in session.query(SbomComponent).filter_by(project_id=project.id)
    }
    assert set(by_comp) == {names["log4j-core"], names["fastjson"]}

    log4j_req = by_comp[names["log4j-core"]]
    assert log4j_req.priority == "critical"     # 知识库模板优先级
    assert "CVE-2021-44228" in log4j_req.trigger_reason
