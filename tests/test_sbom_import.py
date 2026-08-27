# -*- coding: utf-8 -*-
"""SBOM 文件解析单元测试(CycloneDX JSON / SPDX JSON / SPDX tag-value)。"""
import json

import pytest

from services.sbom_import import SbomParseError, detect_format


def _cyclonedx_doc():
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "components": [
            {"type": "library", "name": "lodash", "version": "4.17.15",
             "purl": "pkg:npm/lodash@4.17.15",
             "licenses": [{"license": {"id": "MIT"}}]},
            {"type": "framework", "name": "Spring Boot", "version": "2.7.18",
             "purl": "pkg:maven/org.springframework.boot/spring-boot@2.7.18",
             "licenses": [{"expression": "Apache-2.0"}]},
            {"type": "application", "name": "无版本组件"},   # 无版本 → 跳过
        ],
    }


def test_parse_cyclonedx_json():
    doc = _cyclonedx_doc()
    fmt, rows = detect_format("bom.json", json.dumps(doc).encode())
    assert fmt == "cyclonedx"
    by_name = {r["name"]: r for r in rows}
    assert set(by_name) == {"lodash", "Spring Boot"}
    assert by_name["lodash"]["layer"] == "library"
    assert by_name["lodash"]["license"] == "MIT"
    assert by_name["Spring Boot"]["layer"] == "backend"
    assert by_name["Spring Boot"]["license"] == "Apache-2.0"


def test_roundtrip_of_own_export_keeps_layer():
    """回读本工具导出的 SBOM: secreq:layer 属性优先于 type 推断。"""
    doc = _cyclonedx_doc()
    doc["components"][0]["properties"] = [
        {"name": "secreq:layer", "value": "frontend"},
    ]
    _, rows = detect_format("own.json", json.dumps(doc).encode())
    lodash = next(r for r in rows if r["name"] == "lodash")
    assert lodash["layer"] == "frontend"


def test_parse_spdx_json():
    doc = {
        "spdxVersion": "SPDX-2.3",
        "packages": [
            {"name": "log4j-core", "versionInfo": "2.14.1",
             "licenseConcluded": "Apache-2.0",
             "externalRefs": [
                 {"referenceCategory": "PACKAGE-MANAGER", "referenceType": "purl",
                  "referenceLocator": "pkg:maven/org.apache.logging.log4j/log4j-core@2.14.1"}
             ]},
            {"name": "no-version-pkg", "versionInfo": "NOASSERTION"},
        ],
    }
    fmt, rows = detect_format("sbom.spdx.json", json.dumps(doc).encode())
    assert fmt == "spdx_json"
    assert len(rows) == 1
    row = rows[0]
    assert row["name"] == "log4j-core"
    assert row["version"] == "2.14.1"
    assert row["purl"].endswith("log4j-core@2.14.1")


def test_parse_spdx_tagvalue():
    text = "\n".join([
        "SPDXVersion: SPDX-2.3",
        "PackageName: fastjson",
        "PackageVersion: 1.2.70",
        "PackageLicenseConcluded: NOASSERTION",  # 非目标键, 忽略
        "LicenseConcluded: Apache-2.0",
        "ExternalRef: PACKAGE purl pkg:maven/com.alibaba/fastjson@1.2.70",
        "",
    ])
    fmt, rows = detect_format("sbom.spdx", text.encode())
    assert fmt == "spdx_tagvalue"
    assert rows == [{
        "layer": "library", "name": "fastjson", "version": "1.2.70",
        "purl": "pkg:maven/com.alibaba/fastjson@1.2.70", "license": "Apache-2.0",
    }]


def test_unknown_format_rejected():
    with pytest.raises(SbomParseError):
        detect_format("x.txt", b"not a bom")


def test_broken_json_rejected():
    with pytest.raises(SbomParseError):
        detect_format("x.json", b'{"foo": ')
