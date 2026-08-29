# -*- coding: utf-8 -*-
"""SBOM 生成服务: 项目软件/框架清单 → CycloneDX 1.5 JSON。

DESIGN.md 模块3: 从 Step7 组件清单生成 CycloneDX 1.5 格式 SBOM,
含组件名、版本、purl、许可证、来源; 层级与录入来源用自定义 properties 保留。
未填 purl 的组件自动补 pkg:generic/<name>@<version> 并回写, 保证 OSV 可查询。
"""
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from models import Project, SbomComponent

CYCLONEDX_SPEC_VERSION = "1.5"

# 层级 → CycloneDX 组件 type 映射
LAYER_TO_COMPONENT_TYPE = {
    "frontend": "application",
    "backend": "application",
    "database": "application",
    "middleware": "application",
    "library": "library",
    "infra": "container",
}

# SPDX 许可证 id 形态(如 Apache-2.0 / MIT / BSD-3-Clause); 含空格等视为自由文本
_SPDX_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+-]*$")


def ensure_purl(component: SbomComponent) -> str:
    """组件无 purl 时按 generic 包坐标补齐并回写 ORM 对象。"""
    if component.purl:
        return component.purl
    safe_name = component.name.strip().replace(" ", "-").lower()
    purl = f"pkg:generic/{safe_name}@{component.version}"
    component.purl = purl
    return purl


def _license_node(license_text: str) -> dict:
    """有 SPDX id 形态的走 license.id, 其余(自述文本)走 license.name。"""
    text = (license_text or "").strip()
    if not text:
        return {}
    key = "id" if _SPDX_ID_PATTERN.match(text) else "name"
    return {"license": {key: text}}


def build_cyclonedx(project: Project, components: list[SbomComponent]) -> dict:
    """由项目与组件清单构建 CycloneDX 1.5 字典结构(不含文件写出)。"""
    items = []
    for comp in sorted(components, key=lambda c: c.id):
        purl = ensure_purl(comp)
        entry = {
            "type": LAYER_TO_COMPONENT_TYPE.get(comp.layer, "library"),
            "bom-ref": purl,
            "name": comp.name,
            "version": comp.version,
            "purl": purl,
            "properties": [
                {"name": "secreq:layer", "value": comp.layer},
                {"name": "secreq:source-type", "value": comp.source_type},
            ],
        }
        lic = _license_node(comp.license)
        if lic:
            entry["licenses"] = [lic]
        items.append(entry)

    return {
        "bomFormat": "CycloneDX",
        "specVersion": CYCLONEDX_SPEC_VERSION,
        "serialNumber": f"urn:uuid:{uuid.uuid4()}",
        "version": 1,
        "metadata": {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "component": {
                "type": "application",
                "name": project.name,
                "version": "1.0",
                "properties": [
                    {"name": "secreq:project-code", "value": project.code},
                    {"name": "secreq:tool", "value": "SecReq 安全需求与设计基线生成工具"},
                ],
            },
        },
        "components": items,
    }


def write_cyclonedx_file(bom: dict, path: str | Path) -> Path:
    """SBOM JSON 落盘(UTF-8、保留中文可读); 输出路径不允许包含相对路径段(防穿越)。"""
    path = Path(path)
    if ".." in path.parts:
        raise ValueError(f"输出路径不允许包含相对路径段: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(bom, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def generate_project_sbom(session: Session, project_id: int) -> tuple[dict, list[SbomComponent]]:
    """从数据库读取项目组件并生成 CycloneDX 字典。

    返回 (bom字典, 组件列表); 组件 purl 可能已被补齐回写, 由调用方决定是否 commit。
    """
    project = session.get(Project, project_id)
    if project is None:
        raise ValueError(f"项目不存在: id={project_id}")
    components = (
        session.query(SbomComponent).filter_by(project_id=project_id).order_by(SbomComponent.id).all()
    )
    return build_cyclonedx(project, components), components
