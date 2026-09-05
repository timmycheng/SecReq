# -*- coding: utf-8 -*-
"""SBOM 构建文件解析(#226): pom.xml / package.json / requirements.txt。

三类样例解析行数/版本/层级正确; 异常/损坏文件可读报错不崩溃;
离线解析不触网(pom 变量占位与范围约束置空不入库)。
"""
import pytest

from services.sbom_import import SbomParseError, detect_format

POM = b"""<?xml version="1.0"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <dependencies>
    <dependency>
      <groupId>org.apache.logging.log4j</groupId>
      <artifactId>log4j-core</artifactId>
      <version>2.14.1</version>
    </dependency>
    <dependency>
      <groupId>com.example</groupId>
      <artifactId>parent-managed</artifactId>
    </dependency>
    <dependency>
      <groupId>org.example</groupId>
      <artifactId>var-version</artifactId>
      <version>${project.version}</version>
    </dependency>
  </dependencies>
</project>
"""

PACKAGE_JSON = b"""{
  "dependencies": {"react": "^19.0.0", "antd": "6.0.0"},
  "devDependencies": {"vite": "~6.1.0", "typescript": "*"}
}
"""

REQUIREMENTS = b"""fastapi==0.115.0
uvicorn[standard]==0.30.1  # ASGI server
-r base.txt
SQLAlchemy>=2.0
"""


def test_pom_xml_parse():
    fmt, rows = detect_format("pom.xml", POM)
    assert fmt == "maven_pom"
    assert len(rows) == 1  # 无版本与变量占位条目不入库
    row = rows[0]
    assert row["name"] == "org.apache.logging.log4j:log4j-core"
    assert row["version"] == "2.14.1"
    assert row["layer"] == "backend"
    assert row["purl"] == "pkg:maven/org.apache.logging.log4j/log4j-core@2.14.1"


def test_package_json_parse():
    fmt, rows = detect_format("package.json", PACKAGE_JSON)
    assert fmt == "npm_package"
    by_name = {r["name"]: r for r in rows}
    assert set(by_name) == {"react", "antd", "vite"}  # * 版本条目不入库
    assert by_name["react"]["version"] == "19.0.0"      # ^ 前缀归一
    assert by_name["vite"]["version"] == "6.1.0"        # ~ 前缀归一
    assert by_name["antd"]["version"] == "6.0.0"
    assert all(r["layer"] == "frontend" for r in rows)


def test_requirements_txt_parse():
    fmt, rows = detect_format("requirements.txt", REQUIREMENTS)
    assert fmt == "requirements"
    by_name = {r["name"]: r for r in rows}
    assert set(by_name) == {"fastapi", "uvicorn"}
    assert by_name["fastapi"]["version"] == "0.115.0"
    assert by_name["uvicorn"]["version"] == "0.30.1"
    assert all(r["layer"] == "backend" for r in rows)


def test_broken_files_raise_readable_error():
    """损坏/空文件 → SbomParseError 带中文归因, 不崩溃。"""
    with pytest.raises(SbomParseError):
        detect_format("pom.xml", b"<project><dependencies>")
    with pytest.raises(SbomParseError):
        detect_format("package.json", b"{not json")
    with pytest.raises(SbomParseError):
        detect_format("package.json", b"[1,2,3]")
    # 空文件/全注释: 无可入库行不算异常, 返回空列表
    assert detect_format("requirements.txt", b"# only comment\n") == ("requirements", [])


@pytest.fixture()
def sec(api):
    from conftest import api_as
    return api_as(api, "sec_admin")


def test_import_endpoint_roundtrip(api, sec):
    """经 SBOM 导入端点两段式: 上传解析 → 确认入库(system 级组件)。"""
    system = sec.post("/api/systems", json={"name": "构建文件系统"}).json()
    resp = sec.post(f"/api/systems/{system['id']}/components/import-sbom",
                    files={"file": ("requirements.txt", REQUIREMENTS, "text/plain")})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["format"] == "requirements"
    assert body["added"] == 2
    rows = sec.get(f"/api/systems/{system['id']}/components").json()
    assert {c["name"] for c in rows} == {"fastapi", "uvicorn"}
