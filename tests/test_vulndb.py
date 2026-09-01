# -*- coding: utf-8 -*-
"""离线漏洞库测试(v2.2.0 内网上线的功能阻塞项)。

端到端覆盖: 合成 OSV 形态的 zip → scripts.build_vuln_db 建库 → OsvLocalSource 查询。
刻意保留旧版本组件作为种子, 能命中真实 CVE 才是"功能真的可用"的判据(MASTER_PLAN 5.3)。
"""
import json
import zipfile

import pytest

from conftest import add_base_project
from models import SbomComponent

# ── 样本记录(形态取自 OSV 官方离线包实测样本) ───────────────

# Bitnami: 标准 semver, 现有比较键零适配
BITNAMI_REDIS = {
    "id": "BIT-redis-2021-31294",
    "aliases": ["CVE-2021-31294"],
    "summary": "Redis 整数溢出可导致远程代码执行",
    "database_specific": {"severity": "CRITICAL"},
    "affected": [{
        "package": {"name": "redis", "ecosystem": "Bitnami", "purl": "pkg:bitnami/redis"},
        "ranges": [{"type": "SEMVER", "events": [
            {"introduced": "0"}, {"fixed": "6.2.0"},
        ]}],
    }],
}

# Alpine: 版本带 -rN 修订号, 且记录带完整 versions 枚举
ALPINE_OPENSSL = {
    "id": "ALPINE-CVE-2016-2105",
    "aliases": ["CVE-2016-2105"],
    "summary": "OpenSSL ASN.1 编码器内存损坏",
    "database_specific": {"severity": "HIGH"},
    "affected": [{
        "package": {
            "name": "openssl", "ecosystem": "Alpine:v3.4",
            "purl": "pkg:apk/alpine/openssl?arch=source",
        },
        "ranges": [{"type": "ECOSYSTEM", "events": [
            {"introduced": "0"}, {"fixed": "1.0.2h-r0"},
        ]}],
        "versions": ["1.0.2g-r0", "1.0.2h-r0"],
    }],
}

# Alpine Redis: 无 versions 枚举、修复版本 6.2.6(#96 目标版本=修复版本误报样本)
ALPINE_REDIS = {
    "id": "ALPINE-CVE-2021-32675",
    "aliases": ["CVE-2021-32675"],
    "summary": "Redis 整数溢出导致堆越界写",
    "database_specific": {"severity": "HIGH"},
    "affected": [{
        "package": {
            "name": "redis", "ecosystem": "Alpine:v3.15",
            "purl": "pkg:apk/alpine/redis?arch=source",
        },
        "ranges": [{"type": "ECOSYSTEM", "events": [
            {"introduced": "0"}, {"fixed": "6.2.6"},
        ]}],
    }],
}

NPM_LODASH = {
    "id": "GHSA-p6mc-m468-83gg",
    "aliases": ["CVE-2020-8203"],
    "summary": "lodash 原型污染",
    "database_specific": {"severity": "HIGH"},
    "affected": [{
        "package": {"name": "lodash", "ecosystem": "npm", "purl": "pkg:npm/lodash"},
        "ranges": [{"type": "SEMVER", "events": [
            {"introduced": "0"}, {"fixed": "4.17.19"},
        ]}],
    }],
}

# npm 预发布版本: 2.15.0-rc1 落在 [2.13.0, 2.15.0) 内(#21 漏报回归护栏)
NPM_PRERELEASE = {
    "id": "GHSA-test-prerelease",
    "aliases": ["CVE-2099-0001"],
    "summary": "预发布版本窗口归属回归样本",
    "database_specific": {"severity": "HIGH"},
    "affected": [{
        "package": {"name": "string-width", "ecosystem": "npm", "purl": "pkg:npm/string-width"},
        "ranges": [{"type": "SEMVER", "events": [
            {"introduced": "2.13.0"}, {"fixed": "2.15.0"},
        ]}],
    }],
}

# versions-only 记录: 只有受影响版本枚举、无 ranges(#28 结构性漏报样本)
VERSIONS_ONLY_NPM = {
    "id": "GHSA-test-versions-only",
    "aliases": ["CVE-2099-0002"],
    "summary": "无 ranges 只有 versions 枚举的公告形态",
    "database_specific": {"severity": "MEDIUM"},
    "affected": [{
        "package": {"name": "qs-utils", "ecosystem": "npm", "purl": "pkg:npm/qs-utils"},
        "versions": ["1.0.0", "1.2.0"],
    }],
}

# 同公告多包坐标: log4j-core 与 log4j-api 各有修复版本(#29 污染回归样本)
MAVEN_MULTI_PACKAGE = {
    "id": "GHSA-test-multi-package",
    "aliases": ["CVE-2099-0003"],
    "summary": "同一公告列出多个派生包坐标",
    "database_specific": {"severity": "HIGH"},
    "affected": [
        {
            "package": {
                "name": "org.apache.logging.log4j:log4j-core", "ecosystem": "Maven",
                "purl": "pkg:maven/org.apache.logging.log4j/log4j-core",
            },
            "ranges": [{"type": "ECOSYSTEM", "events": [
                {"introduced": "2.0"}, {"fixed": "2.15.0"},
            ]}],
        },
        {
            "package": {
                "name": "org.apache.logging.log4j:log4j-api", "ecosystem": "Maven",
                "purl": "pkg:maven/org.apache.logging.log4j/log4j-api",
            },
            "ranges": [{"type": "ECOSYSTEM", "events": [
                {"introduced": "2.0"}, {"fixed": "2.17.1"},
            ]}],
        },
    ],
}

MAVEN_LOG4J = {
    "id": "GHSA-jfh8-c2jp-5v3q",
    "aliases": ["CVE-2021-44228"],
    "summary": "Log4Shell",
    "database_specific": {"severity": "CRITICAL"},
    "affected": [{
        "package": {
            "name": "org.apache.logging.log4j:log4j-core", "ecosystem": "Maven",
            "purl": "pkg:maven/org.apache.logging.log4j/log4j-core",
        },
        "ranges": [{"type": "ECOSYSTEM", "events": [
            {"introduced": "2.0"}, {"fixed": "2.15.0"},
        ]}],
    }],
}


def _write_zip(path, records: dict[str, list[dict]]) -> None:
    """按 OSV all.zip 的形态打包: 一个漏洞一个 JSON 文件。"""
    with zipfile.ZipFile(path, "w") as zf:
        for ecosystem, vulns in records.items():
            for vuln in vulns:
                zf.writestr(f"{vuln['id']}.json", json.dumps(vuln, ensure_ascii=False))


@pytest.fixture(scope="module")
def vulndb_path(tmp_path_factory):
    """用真实构建脚本产出一个小库(端到端, 而非手搓 SQLite)。"""
    from scripts.build_vuln_db import build

    cache = tmp_path_factory.mktemp("osv-zips")
    zips = []
    groups = {
        "Bitnami": [BITNAMI_REDIS],
        "Alpine": [ALPINE_OPENSSL, ALPINE_REDIS],
        "npm": [NPM_LODASH, NPM_PRERELEASE, VERSIONS_ONLY_NPM],
        "Maven": [MAVEN_LOG4J, MAVEN_MULTI_PACKAGE],
    }
    for ecosystem, vulns in groups.items():
        path = cache / f"{ecosystem}.zip"
        _write_zip(path, {ecosystem: vulns})
        zips.append((ecosystem, path))

    out = tmp_path_factory.mktemp("vulndb") / "vulndb.sqlite"
    stats = build(zips, out, slim=False, compress=True)
    # total 按"坐标行"计数(一条公告的多个 affected 包各算一行): 8 条公告 9 个坐标
    assert stats["total"] == 9
    return str(out)


@pytest.fixture
def local(vulndb_path):
    from services.vulndb import OsvLocalSource, VulnDb
    return OsvLocalSource(VulnDb(vulndb_path))


def _query(name, version, ecosystem=None, distro=None):
    from services.vuln_source import VulnQuery
    return VulnQuery(name=name, version=version, ecosystem=ecosystem, distro=distro)


# ── 版本归一化 ────────────────────────────────────────

@pytest.mark.parametrize("ecosystem,raw,want", [
    ("alpine", "1.0.2h-r0", "1.0.2h"),
    ("alpine", "1.0.2h", "1.0.2h"),
    ("debian", "8.0.32-1~deb12u1", "8.0.32"),
    ("debian", "1.18.0-6+deb11u2", "1.18.0"),
    ("redhat", "1.18.0-1.el9", "1.18.0"),
    ("redhat", "1.2.3-1.module_el9+2", "1.2.3"),
    ("openeuler", "1.18.0-1.oe2203", "1.18.0"),
    ("bitnami", "8.0.32-debian-11-r0", "8.0.32"),
    ("npm", "4.17.19", "4.17.19"),
])
def test_canonical_strips_distro_suffix(ecosystem, raw, want):
    from services.vuln_match import canonical
    assert canonical(ecosystem, raw) == want


def test_canonical_never_strips_to_empty():
    """保守策略: 剥离后不含数字则保留原串, 避免把短版本号剥成空。"""
    from services.vuln_match import canonical
    assert canonical("alpine", "-r0") == "-r0"
    assert canonical("debian", "") == ""


def test_in_versions_matches_after_normalization():
    """用户填 1.0.2g 能命中枚举里的 1.0.2g-r0(发行版修订号不参与比较)。"""
    from services.vuln_match import in_versions
    assert in_versions("alpine", "1.0.2g", ["1.0.2g-r0", "1.0.2h-r0"])
    assert not in_versions("alpine", "1.0.2z", ["1.0.2g-r0", "1.0.2h-r0"])


def test_version_key_orders_across_revisions():
    from services.vuln_match import version_key
    assert version_key("alpine", "1.0.2g-r0") < version_key("alpine", "1.0.2h-r0")


# ── 本地库查询: 四种语义 ───────────────────────────────

def test_bitnami_semver_hit_and_fix_version(local):
    """Bitnami 用标准 semver, 6.0.9 落在 [0, 6.2.0) → 命中并建议升到 6.2.0。"""
    result = local.query(_query("redis", "6.0.9", ecosystem="bitnami"))
    assert result.status == "hit"
    assert [v["id"] for v in result.vulns] == ["BIT-redis-2021-31294"]
    assert result.vulns[0].get("_secreq_windows") is not None  # 预筛窗口已挂载


def test_bitnami_patched_version_not_reported(local):
    result = local.query(_query("redis", "7.0.0", ecosystem="bitnami"))
    assert result.status == "not_found"
    assert result.vulns == []


def test_alpine_revision_suffix_matching(local):
    """Alpine 的 -rN 修订号: 1.0.2g 命中, 1.0.2t 已修复。"""
    assert local.query(_query("openssl", "1.0.2g", distro="alpine")).status == "hit"
    assert local.query(_query("openssl", "1.0.2t", distro="alpine")).status == "not_found"


def test_alpine_version_without_revision_is_conservatively_flagged(local):
    """用户只填 1.0.2h 而修复版是 1.0.2h-r0: 无法判断是否已含修复, 按疑似命中并说明。

    绝不能静默判成"未发现漏洞" —— 那会给人虚假的安全感。
    """
    result = local.query(_query("openssl", "1.0.2h", distro="alpine"))
    assert result.status == "hit"
    assert "修订号" in (result.note or "")


def test_target_equal_to_fixed_version_is_not_reported(local):
    """目标版本与修复版本完全相等: 不命中(#96 误报回归护栏)。

    Redis@6.2.6 与 fixed=6.2.6 原始串相同, 用户已在修复版本上;
    疑似命中兜底只覆盖「原始串不同、归一化后相同」的场景, 不得把相等也吞进去。
    """
    result = local.query(_query("redis", "6.2.6", distro="alpine"))
    assert result.status == "not_found"
    assert result.vulns == []


def test_target_inside_window_still_hits_normally(local):
    """目标版本落在 [introduced, fixed) 区间内: 正常命中(#96 修复不伤及正常路径)。"""
    result = local.query(_query("redis", "6.2.5", distro="alpine"))
    assert result.status == "hit"
    assert result.vulns[0]["id"] == "ALPINE-CVE-2021-32675"


def test_maven_tail_matches_bare_artifact_name(local):
    """Maven 坐标带 group 前缀, 用户只填 log4j-core 也要命中。"""
    result = local.query(_query("log4j-core", "2.14.1", ecosystem="maven"))
    assert result.status == "hit"
    assert result.vulns[0]["id"] == "GHSA-jfh8-c2jp-5v3q"


def test_version_key_orders_prerelease_before_release():
    """预发布排在同号稳定版之前: 2.15.0-rc1 < 2.15.0(修复前为 False, 排序与注释相反)。"""
    from services.vuln_match import version_key
    assert version_key("npm", "2.15.0-rc1") < version_key("npm", "2.15.0")


def test_prerelease_inside_window_is_not_missed(local):
    """2.15.0-rc1 落在窗口 [2.13.0, 2.15.0) 内 → hit 且修复版 2.15.0。

    修复前 2.15.0-rc1 被判 "≥ fixed, 已修复" 而漏报 —— 本用例即漏报形态回归护栏。
    """
    result = local.query(_query("string-width", "2.15.0-rc1", ecosystem="npm"))
    assert result.status == "hit"
    assert result.vulns[0]["_secreq_windows"] == [{"introduced": "2.13.0", "fixed": "2.15.0"}]


def test_versions_only_record_is_reported_with_note(local):
    """只有 versions 枚举、无 ranges 的记录: 枚举命中即报 hit 并说明"未提供范围"(#28)。"""
    result = local.query(_query("qs-utils", "1.2.0", ecosystem="npm"))
    assert result.status == "hit"
    assert result.vulns[0]["_secreq_windows"] == [{"introduced": "1.2.0"}]
    assert "未提供" in (result.note or "")


def test_versions_only_record_missed_version_is_not_found(local):
    """versions-only 记录: 枚举外的版本仍应 not_found, 伪窗口不得放宽成全命中。"""
    result = local.query(_query("qs-utils", "1.3.0", ecosystem="npm"))
    assert result.status == "not_found"


def test_same_announcement_other_package_does_not_pollute_fix(local):
    """同公告其他包坐标不得混入窗口: log4j-core 2.14.1 → [2.0, 2.15.0), 而非混入 api 的 2.17.1(#29)。"""
    result = local.query(_query("log4j-core", "2.14.1", ecosystem="maven"))
    assert result.status == "hit"
    assert result.vulns[0]["_secreq_windows"] == [{"introduced": "2.0", "fixed": "2.15.0"}]


def test_fuzzy_query_builds_purl_per_ecosystem(local):
    """跨生态模糊匹配逐生态构造 purl: npm 类型不再抢先定义 maven 组件的同坐标筛选(#29)。"""
    result = local.query(_query("log4j-core", "2.14.1"))
    assert result.status == "hit"
    assert "模糊匹配" in (result.note or "")
    assert result.vulns[0]["_secreq_windows"] == [{"introduced": "2.0", "fixed": "2.15.0"}]


def test_ecosystem_not_imported_is_not_covered(local):
    """声明了生态但库里没导 → not_covered, 不能报成"未发现漏洞"。"""
    result = local.query(_query("nginx", "1.20.0", ecosystem="openeuler"))
    assert result.status == "not_covered"
    assert "openEuler" in result.note


def test_source_build_is_not_covered(local):
    result = local.query(_query("internal-sdk", "1.0.0", distro="source"))
    assert result.status == "not_covered"
    assert "源码编译" in result.note


def test_missing_version_is_undetermined(local):
    result = local.query(_query("redis", "", ecosystem="bitnami"))
    assert result.status == "undetermined"


def test_unknown_ecosystem_falls_back_to_fuzzy(local):
    """未指定生态 → 跨生态模糊匹配, 命中即返回但必须标注需人工确认。"""
    result = local.query(_query("lodash", "4.17.15"))
    assert result.status == "hit"
    assert "模糊匹配" in (result.note or "")


def test_kylin_proxy_marks_inferred_source(local):
    """麒麟走 openEuler 代理, 结果必须带推断声明, 不得以"确认"面貌呈现。"""
    result = local.query(_query("redis", "6.0.9", distro="kylin"))
    # 库里没有 openEuler 的 redis → 未覆盖; 但一旦命中必须带推断声明
    if result.status == "hit":
        assert "麒麟官方安全公告" in (result.note or "")
    else:
        assert result.status == "not_covered"


# ── 数据源工厂 ────────────────────────────────────────

def test_sca_source_is_reserved_but_explicit(monkeypatch):
    """sca 目前只占位: 返回明确的"未启用"原因, 绝不静默失败。"""
    from services.vuln_source import ScaPlatformSource
    ok, reason = ScaPlatformSource().available()
    assert ok is False
    assert "尚未接入" in reason


def test_source_chain_degrades_to_local(monkeypatch, vulndb_path):
    """SECREQ_VULN_SOURCE=sca,local → SCA 不可用, 降级到本地库并留下降级记录。"""
    from services import vuln_source

    monkeypatch.setenv("SECREQ_VULN_SOURCE", "sca,local")
    monkeypatch.setenv("SECREQ_VULNDB_PATH", vulndb_path)
    source, skipped = vuln_source.get_vuln_source()
    assert source.name == "osv_local"
    assert any("sca" in s for s in skipped)


def test_all_sources_unavailable_raises(monkeypatch):
    from services import vuln_source
    from services.vuln_source import VulnSourceUnavailable

    monkeypatch.setenv("SECREQ_VULN_SOURCE", "sca")
    with pytest.raises(VulnSourceUnavailable) as exc:
        vuln_source.get_vuln_source()
    assert "无可用漏洞数据源" in str(exc.value)


def test_describe_sources_marks_active(monkeypatch, vulndb_path):
    from services import vuln_source

    monkeypatch.setenv("SECREQ_VULN_SOURCE", "local")
    monkeypatch.setenv("SECREQ_VULNDB_PATH", vulndb_path)
    rows = vuln_source.describe_sources()
    active = [r for r in rows if r["active"]]
    assert len(active) == 1 and active[0]["code"] == "local"


# ── 同步流程接入 ──────────────────────────────────────

def _add(session, project, **kwargs) -> SbomComponent:
    comp = SbomComponent(project_id=project.id, layer="library", **kwargs)
    session.add(comp)
    session.flush()
    return comp


def test_sync_via_local_source_persists_status_and_source(session, monkeypatch, vulndb_path):
    """端到端: 本地库 → 落库记录带 source=osv_local, 组件带 vuln_status。"""
    from services.osv import sync_vulnerabilities
    from services.vulndb import OsvLocalSource, VulnDb

    monkeypatch.setenv("SECREQ_VULNDB_PATH", vulndb_path)
    project = add_base_project(session)
    comp = _add(session, project, name="redis", version="6.0.9",
                ecosystem="bitnami", distro="bitnami")
    covered = _add(session, project, name="internal-sdk", version="1.0.0", distro="source")

    records, result = sync_vulnerabilities(
        session, [comp, covered], source=OsvLocalSource(VulnDb(vulndb_path))
    )

    assert [r.cve_id for r in records] == ["CVE-2021-31294"]
    assert records[0].source == "osv_local"
    assert comp.vuln_status == "hit"
    assert covered.vuln_status == "not_covered"
    assert result.status["internal-sdk"] == "not_covered"
    assert "本地漏洞库" in result.summary_text()


def test_new_library_invalidates_cache_immediately(session, monkeypatch, vulndb_path):
    """换了漏洞库就必须重算 —— 沿用旧结果等于把新入库的 CVE 全漏掉。"""
    from services.osv import sync_vulnerabilities
    from services.vulndb import OsvLocalSource, VulnDb

    project = add_base_project(session)
    comp = _add(session, project, name="redis", version="6.0.9", ecosystem="bitnami")
    db = VulnDb(vulndb_path)
    sync_vulnerabilities(session, [comp], source=OsvLocalSource(db))

    from services.vulndb import VulnDb as _VulnDb
    monkeypatch.setattr(_VulnDb, "version", property(lambda self: "20990101:9999"))
    _, result = sync_vulnerabilities(session, [comp], source=OsvLocalSource(db))
    assert "redis" in result.updated, "库版本变化必须触发重算, 不能命中缓存"


def test_version_change_invalidates_cache(session, vulndb_path):
    """24h 内改了组件版本号, 旧结果即失效(旧实现只按时间判定会沿用错误结果)。"""
    from services.osv import sync_vulnerabilities
    from services.vulndb import OsvLocalSource, VulnDb

    project = add_base_project(session)
    comp = _add(session, project, name="redis", version="6.0.9", ecosystem="bitnami")
    source = OsvLocalSource(VulnDb(vulndb_path))
    sync_vulnerabilities(session, [comp], source=source)

    comp.version = "7.2.0"
    _, result = sync_vulnerabilities(session, [comp], source=source)
    assert "redis" in result.updated
    assert comp.vuln_status == "not_found"


# ── 覆盖判定的诚实性 ───────────────────────────────────

def test_incidental_records_do_not_imply_coverage(local, vulndb_path):
    """库里"有记录"不等于"覆盖了该生态"。

    OSV 的多生态公告会在一个生态的 zip 里夹带其他生态的包坐标 —— 实测
    Maven/all.zip 里带了 92 条 npm、189 条 NuGet 记录。若按"有记录即覆盖",
    只导了 Maven 的库会把 npm 组件报成"未发现已知漏洞", 等于用 92 条记录
    冒充 22 万条。覆盖率必须按"构建时声明导入 ∩ 实际入库"判定。
    """
    import sqlite3
    import zlib

    from services.vulndb import VulnDb

    db = VulnDb(vulndb_path)
    # 该库声明导入的是 Bitnami/Alpine/npm/Maven; 塞入一条 openEuler 记录模拟"夹带"
    assert "openeuler" not in db.imported_ecosystems
    conn = sqlite3.connect(vulndb_path)
    conn.execute(
        "INSERT INTO vulns (vuln_id, ecosystem, name, tail, raw) VALUES (?,?,?,?,?)",
        ("FAKE-oe", "openeuler", "openssl", "openssl", sqlite3.Binary(zlib.compress(b"{}"))),
    )
    conn.commit()
    conn.close()
    db.reload_meta()

    assert "openeuler" in db.imported_ecosystems, "前置条件: 库里确实存在该生态记录"
    assert "openeuler" not in db.covered_ecosystems

    result = local.query(_query("openssl", "1.1.1", ecosystem="openeuler"))
    assert result.status == "not_covered", "夹带的记录不得冒充覆盖"
    assert "未导入" in result.note
