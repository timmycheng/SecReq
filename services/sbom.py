# -*- coding: utf-8 -*-
"""SBOM 生成服务: 项目软件/框架清单 → CycloneDX 1.5 JSON。

DESIGN.md 模块3: 从 Step7 组件清单生成 CycloneDX 1.5 格式 SBOM,
含组件名、版本、purl、许可证、来源; 层级与录入来源用自定义 properties 保留。

v2.2.0 修复 —— 未填 purl 时不再补 `pkg:generic/...`:
OSV **不支持 generic 生态**, 这类 purl 永远查不到任何漏洞。
而 ComponentIn.purl 是可选字段、Step7 原先也未引导填生态, 实际绝大多数组件
都落进 generic, 漏洞联动形同虚设。现改为:
  1. 有生态 → 按生态构造规范 purl(pkg:npm/lodash@4.17.20);
  2. 无生态 → 返回 None, 由漏洞查询走跨生态模糊匹配并标注「待确认」;
  3. SBOM 落盘的 purl 字段缺失时降级为 name@version, 但漏洞匹配不依赖它。
"""
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

import shared.constants as C
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


def sanitize_name(name: str) -> str:
    """组件名 → purl 安全形态(小写、空格与空白转 -)。"""
    return re.sub(r"\s+", "-", (name or "").strip()).lower()


def build_purl(component: SbomComponent) -> str | None:
    """按生态构造规范 purl; 无生态时返回 None(不生成 OSV 不支持的 generic)。

    用户手填的 purl 优先保留(可能是带命名空间/group 的完整坐标)。
    """
    if component.purl:
        return component.purl
    ecosystem = (component.ecosystem or "").strip().lower()
    if ecosystem not in C.ECOSYSTEM_PURL_TYPE:
        return None
    name = sanitize_name(component.name)
    if not name:
        return None
    ptype = C.ECOSYSTEM_PURL_TYPE[ecosystem]
    version = (component.version or "").strip()
    return f"pkg:{ptype}/{name}@{version}" if version else f"pkg:{ptype}/{name}"


#: purl type → 内部生态 code(带命名空间的类型如 apk/alpine 两种形态都注册)
_PURL_TYPE_TO_ECOSYSTEM = {}
for _eco, _ptype in C.ECOSYSTEM_PURL_TYPE.items():
    _PURL_TYPE_TO_ECOSYSTEM[_ptype] = _eco
    _PURL_TYPE_TO_ECOSYSTEM[_ptype.split("/")[0]] = _eco

#: 这些 purl 类型的 distro 在命名空间位(pkg:apk/alpine/openssl), 需两段合起来才是类型
_NAMESPACED_TYPES = {"apk", "rpm", "deb"}


def ecosystem_from_purl(purl: str | None) -> str | None:
    """从 purl 反推生态 code(SBOM 文件导入时补全 Step7 未填的生态维度)。

    `pkg:apk/alpine/openssl@1.0.2h` → alpine; `pkg:maven/log4j-core@2.14.1` → maven。
    无法识别返回 None(交给跨生态模糊匹配)。
    """
    if not purl:
        return None
    body = str(purl).split("://", 1)[-1]
    body = body.split("#", 1)[0].split("?", 1)[0].split("@", 1)[0]
    parts = [p for p in body.split("/") if p]
    if not parts:
        return None
    parts[0] = parts[0].split(":")[-1]  # 去掉 'pkg:' 前缀, 与 ECOSYSTEM_PURL_TYPE 对齐
    head = parts[0]
    # apk/rpm/deb 的 distro 在命名空间位(pkg:apk/alpine/openssl), 需带上才是完整类型
    candidate = f"{head}/{parts[1]}" if len(parts) >= 2 and head in _NAMESPACED_TYPES else head
    return (
        _PURL_TYPE_TO_ECOSYSTEM.get(candidate)
        or _PURL_TYPE_TO_ECOSYSTEM.get(candidate.split("/")[0])
    )


def ensure_purl(component: SbomComponent) -> str:
    """保证组件有可用于展示/导出的坐标串并回写 ORM 对象。

    注意: 无生态时回写的是 `name@version` 而非 `pkg:generic/...` ——
    generic 类型 OSV 不认, 写了等于给自己一个"查过了"的假象。
    """
    purl = build_purl(component)
    if purl:
        component.purl = purl
        return purl
    fallback = f"{sanitize_name(component.name)}@{component.version}"
    component.purl = fallback
    return fallback


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
        raise ValueError(f"评估不存在: id={project_id}")
    components = (
        session.query(SbomComponent).filter_by(project_id=project_id).order_by(SbomComponent.id).all()
    )
    return build_cyclonedx(project, components), components
