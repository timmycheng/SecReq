# -*- coding: utf-8 -*-
"""SBOM CycloneDX 1.5 生成测试。"""
import json

import pytest

from conftest import add_base_project
from models import SbomComponent
from services.sbom import (
    LAYER_TO_COMPONENT_TYPE, build_cyclonedx, build_purl, ecosystem_from_purl,
    generate_project_sbom, write_cyclonedx_file,
)


def _add_component(session, project, **kwargs) -> SbomComponent:
    defaults = dict(
        project_id=project.id, layer="library", name="demo-lib",
        version="1.0.0", source_type="manual_input",
    )
    defaults.update(kwargs)
    comp = SbomComponent(**defaults)
    session.add(comp)
    session.flush()
    return comp


def test_bom_header_conforms_to_cyclonedx_15(session):
    project = add_base_project(session)
    _add_component(session, project)

    bom = build_cyclonedx(project, session.query(SbomComponent).all())

    assert bom["bomFormat"] == "CycloneDX"
    assert bom["specVersion"] == "1.5"
    assert bom["serialNumber"].startswith("urn:uuid:")
    assert bom["version"] == 1
    # 主组件(被分析的项目)信息
    main = bom["metadata"]["component"]
    assert main["name"] == "测试项目"
    assert any(
        p["name"] == "secreq:project-code" and p["value"] == "PRJ-T001"
        for p in main["properties"]
    )


def test_layer_maps_to_component_type_and_properties_kept(session):
    project = add_base_project(session)
    backend = _add_component(session, project, layer="backend", name="srv")
    lib = _add_component(session, project, layer="library", name="log4j-core", version="2.14.1")
    infra = _add_component(session, project, layer="infra", name="k8s")

    bom = build_cyclonedx(project, [backend, lib, infra])
    by_name = {c["name"]: c for c in bom["components"]}
    types = LAYER_TO_COMPONENT_TYPE
    assert by_name["srv"]["type"] == types["backend"] == "application"
    assert by_name["log4j-core"]["type"] == "library"
    assert by_name["k8s"]["type"] == "container"

    log4j_props = {p["name"]: p["value"] for p in by_name["log4j-core"]["properties"]}
    assert log4j_props["secreq:layer"] == "library"
    assert log4j_props["secreq:source-type"] == "manual_input"


def test_purl_passthrough_and_ecosystem_based_autofill(session):
    """已有 purl 原样保留; 缺失时按生态构造规范 purl 并回写 ORM 对象。"""
    project = add_base_project(session)
    explicit = _add_component(session, project, name="vue", version="3.3.4",
                              purl="pkg:npm/vue@3.3.4")
    with_eco = _add_component(session, project, name="Some Lib X", version="2.1.0",
                              ecosystem="pypi")
    without_eco = _add_component(session, project, name="Mystery Dep", version="9.9")

    bom = build_cyclonedx(project, [explicit, with_eco, without_eco])
    by_name = {c["name"]: c for c in bom["components"]}
    assert by_name["vue"]["purl"] == "pkg:npm/vue@3.3.4"
    assert by_name["vue"]["bom-ref"] == "pkg:npm/vue@3.3.4"

    # 有生态 → 规范 purl(OSV 支持该类型)
    assert by_name["Some Lib X"]["purl"] == "pkg:pypi/some-lib-x@2.1.0"
    assert with_eco.purl == "pkg:pypi/some-lib-x@2.1.0"


def test_missing_ecosystem_never_falls_back_to_generic(session):
    """无生态时不得生成 pkg:generic —— OSV 不支持该类型, 查了也是空转。"""
    project = add_base_project(session)
    comp = _add_component(session, project, name="Mystery Dep", version="9.9")

    assert build_purl(comp) is None
    bom = build_cyclonedx(project, [comp])
    purl = bom["components"][0]["purl"]
    assert not purl.startswith("pkg:generic")
    assert purl == "mystery-dep@9.9"      # 降级坐标, 仅供展示, 不参与漏洞匹配


def test_ecosystem_from_purl_roundtrip():
    """purl → 生态反推(SBOM 文件导入时补全生态维度)。"""
    assert ecosystem_from_purl("pkg:apk/alpine/openssl@1.0.2h") == "alpine"
    assert ecosystem_from_purl("pkg:bitnami/redis@6.2.0") == "bitnami"
    assert ecosystem_from_purl("pkg:maven/log4j-core@2.14.1") == "maven"
    assert ecosystem_from_purl("pkg:rpm/openeuler/openssl@1.1.1") == "openeuler"
    assert ecosystem_from_purl(None) is None
    assert ecosystem_from_purl("not-a-purl") is None


def test_license_spdx_id_vs_free_text(session):
    """SPDX id 形态(含'-'与数字)走 license.id; 含空格的描述文本走 license.name。"""
    project = add_base_project(session)
    _add_component(session, project, name="a-mit", version="1", license="MIT")
    _add_component(session, project, name="b-apache", version="1", license="Apache-2.0")
    _add_component(session, project, name="c-free", version="1", license="Apache License 2.0 商业发行协议")

    bom = build_cyclonedx(project, session.query(SbomComponent).all())
    licenses = {
        c["name"]: c.get("licenses")[0]["license"] for c in bom["components"]
    }
    assert licenses["a-mit"] == {"id": "MIT"}
    assert licenses["b-apache"] == {"id": "Apache-2.0"}
    assert licenses["c-free"] == {"name": "Apache License 2.0 商业发行协议"}


def test_write_cyclonedx_file_keeps_utf8_chinese(session):
    project = add_base_project(session)
    bom = build_cyclonedx(project, [_add_component(session, project)])

    path = write_cyclonedx_file(bom, "output_test/prj-t001_sbom.cdx.json")
    raw = path.read_text(encoding="utf-8")
    parsed = json.loads(raw)
    assert parsed == bom

    import os
    os.unlink(path)
    os.rmdir(path.parent)


def test_generate_project_sbom_reads_db_and_validates_project(session):
    project = add_base_project(session)
    _add_component(session, project, layer="database", name="MySQL", version="8.0.33")

    bom, comps = generate_project_sbom(session, project.id)
    assert [c.name for c in comps] == ["MySQL"]
    assert len(bom["components"]) == 1

    with pytest.raises(ValueError, match="项目不存在"):
        generate_project_sbom(session, 99999)
