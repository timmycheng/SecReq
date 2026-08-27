# -*- coding: utf-8 -*-
"""SBOM 文件批量导入解析(CycloneDX JSON / SPDX JSON / SPDX tag-value)。

解析结果为统一行形态 [{layer, name, version, purl, license}], 由
step_store.append_components 以 source_type=sbom_file 追加入库。
支持回读本工具导出的 CycloneDX 文件(secreq:layer/secreq:source_type 属性优先)。
"""
import json
import re

from schemas.component import SbomImportResult


class SbomParseError(Exception):
    """文件格式无法识别或结构损坏。"""


def _license_from_cyclonedx(component: dict) -> str | None:
    licenses = component.get("licenses") or []
    for item in licenses:
        if isinstance(item, dict):
            if item.get("expression"):
                return str(item["expression"])
            lic = item.get("license") or {}
            text = lic.get("id") or lic.get("name")
            if text:
                return str(text)
    return None


def _layer_from_cyclonedx(component: dict) -> str:
    # 回读本工具导出的文件时, 自定义属性中的录入层级优先
    for prop in component.get("properties") or []:
        if prop.get("name") == "secreq:layer":
            return str(prop.get("value"))
    return {
        "application": "backend",
        "framework": "backend",
        "library": "library",
        "container": "infra",
        "operating-system": "infra",
        "platform": "middleware",
        "device": "infra",
        "firmware": "infra",
        "file": "library",
        "machine-learning-model": "library",
        "data": "library",
        "cryptographic-asset": "library",
    }.get(str(component.get("type")), "library")


def _component_row(name: str, version: str | None, purl=None,
                   license=None, layer="library") -> dict | None:
    name = (name or "").strip()
    if not name:
        return None
    version = (version or "").strip()
    if version.upper() in {"NOASSERTION", "NO ASSERTION", "N/A"}:
        version = ""
    if not version:
        return None
    row = {
        "layer": layer or "library",
        "name": name[:200],
        "version": version[:50],
        "purl": (purl or "").strip() or None,
        "license": (license or "").strip() or None,
    }
    return row


def parse_cyclonedx(data: dict) -> list[dict]:
    rows = []
    for comp in data.get("components") or []:
        row = _component_row(
            name=comp.get("name"),
            version=comp.get("version"),
            purl=comp.get("purl"),
            license=_license_from_cyclonedx(comp),
            layer=_layer_from_cyclonedx(comp),
        )
        if row:
            rows.append(row)
    return rows


def _purl_from_spdx(package: dict) -> str | None:
    for ref in package.get("externalRefs") or []:
        if str(ref.get("referenceType", "")).lower() == "purl":
            return ref.get("referenceLocator")
    return None


def parse_spdx_json(data: dict) -> list[dict]:
    rows = []
    for pkg in data.get("packages") or []:
        row = _component_row(
            name=pkg.get("name"),
            version=pkg.get("versionInfo"),
            purl=_purl_from_spdx(pkg),
            license=(pkg.get("licenseConcluded") or "").strip() or None,
        )
        # SPDX 主包占位与免责说明条目不入库
        if row and row["name"].upper() not in {"NOASSERTION", "NO SOURCE"}:
            rows.append(row)
    return rows


_TAG_LINE = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*):\s*(.*)$")


def parse_spdx_tagvalue(text: str) -> list[dict]:
    """极简 SPDX tag-value 解析: 只提取当前包级字段(遇到新 PackageName 归档上一包)。"""
    packages: list[dict] = []
    current: dict | None = None
    for line in text.splitlines():
        line = line.rstrip()
        if not line or line.startswith("#"):
            continue
        match = _TAG_LINE.match(line)
        if not match:
            continue
        key, value = match.group(1), match.group(2).strip()
        if key == "PackageName":
            current = {"name": value}
            packages.append(current)
        elif current is None:
            continue
        elif key == "PackageVersion":
            current["version"] = value
        elif key == "LicenseConcluded":
            current.setdefault("license", value)
        elif key == "ExternalRef":
            parts = value.split()
            if len(parts) >= 3 and parts[1].lower() == "purl":
                current.setdefault("purl", parts[2])
    rows = []
    for pkg in packages:
        row = _component_row(
            name=pkg.get("name"), version=pkg.get("version"),
            purl=pkg.get("purl"), license=pkg.get("license"),
        )
        if row:
            rows.append(row)
    return rows


def detect_format(filename: str, payload: bytes) -> tuple[str, list[dict]]:
    """识别格式并解析。返回 (格式名, 统一行列表)。"""
    text = payload.decode("utf-8-sig", errors="replace")
    stripped = text.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise SbomParseError(f"JSON 解析失败: {exc}") from exc
        if isinstance(data, dict) and str(data.get("bomFormat", "")).lower() == "cyclonedx":
            return "cyclonedx", parse_cyclonedx(data)
        if isinstance(data, dict) and "spdxVersion" in data:
            return "spdx_json", parse_spdx_json(data)
        raise SbomParseError("JSON 既非 CycloneDX(bomFormat) 也非 SPDX(spdxVersion) 结构")
    if re.search(r"^SPDXVersion:", text, flags=re.M):
        return "spdx_tagvalue", parse_spdx_tagvalue(text)
    raise SbomParseError(f"无法识别的 SBOM 文件格式: {filename}")


def import_sbom_file(session, project_id: int, filename: str, payload: bytes) -> SbomImportResult:
    """解析并以 sbom_file 来源追加入库(同名同版本跳过)。"""
    from services.step_store import append_components

    fmt, rows = detect_format(filename, payload)
    added, skipped_dup = append_components(session, project_id, rows)
    return SbomImportResult(
        filename=filename, format=fmt, total_parsed=len(rows),
        added=added, skipped_duplicate=skipped_dup,
    )
