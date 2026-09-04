# -*- coding: utf-8 -*-
"""NetBox 代理与写回端点(#153): 基础设施资产 导入/推送。

- /api/netbox 前缀不在 OPEN_API_PREFIXES, 全局 auth_guard 自动要求登录;
- #196: NetBox 收敛为安全侧数据通道, 全部端点(含只读代理)仅 security 可用,
  开发侧界面不渲染任何入口, 直调 API 一律 403;
- 错误映射: 未配置 → 409 可读提示, 断连/超时 → 502(中文归因), 4xx → 502 透传 detail;
- 兜底原则: NetBox 是旁路增强 —— 推送是保存后的旁路动作, 失败不回滚、可重试。
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from models import InfraAsset, PlatformUser, Project, System
from routers.admin import require_security
from routers.common import ensure_project_access, get_db
from services.audit_service import audit
from services.netbox import NetboxApiError, NetboxClient, NetboxUnavailable
from services.settings_service import get_netbox_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/netbox", tags=["netbox"])


def _client_or_409(db: Session) -> tuple[dict, NetboxClient]:
    """取配置并建客户端; 未配置一律 409 可读提示。"""
    cfg = get_netbox_config(db)
    if not cfg:
        raise HTTPException(
            status_code=409, detail="NetBox 尚未配置, 请在 系统管理 → NetBox 互通 填写地址与 Token")
    return cfg, NetboxClient(cfg["base_url"], cfg["token"])


def _proxy_502(exc: Exception) -> HTTPException:
    """NetBox 侧故障统一 502: 断连/超时带中文归因, 4xx 透传 detail。"""
    return HTTPException(status_code=502, detail=str(exc))


def _require_security_role(user: PlatformUser) -> None:
    """#196: NetBox 读写均收敛为安全角色; 其余角色 403。"""
    if user.role != "security":
        raise HTTPException(status_code=403, detail="仅安全角色可访问 NetBox 互通功能")


@router.get("/status")
def netbox_status(user: PlatformUser = Depends(require_security),
                  db: Session = Depends(get_db)):
    """前端构建 NetBox 外链用: 是否已配置 + base_url。"""
    cfg = get_netbox_config(db)
    return {"configured": bool(cfg), "base_url": (cfg or {}).get("base_url")}


# ────────────────────────── 只读代理 ──────────────────────────

@router.get("/devices")
def proxy_devices(keyword: str | None = None, limit: int = 25, offset: int = 0,
                  user: PlatformUser = Depends(require_security),
                  db: Session = Depends(get_db)):
    cfg, client = _client_or_409(db)
    try:
        return client.list_devices(keyword=keyword, limit=limit, offset=offset)
    except (NetboxUnavailable, NetboxApiError) as exc:
        raise _proxy_502(exc) from exc
    finally:
        client.close()


@router.get("/virtual-machines")
def proxy_virtual_machines(keyword: str | None = None, limit: int = 25, offset: int = 0,
                           user: PlatformUser = Depends(require_security),
                           db: Session = Depends(get_db)):
    cfg, client = _client_or_409(db)
    try:
        return client.list_virtual_machines(keyword=keyword, limit=limit, offset=offset)
    except (NetboxUnavailable, NetboxApiError) as exc:
        raise _proxy_502(exc) from exc
    finally:
        client.close()


@router.get("/ip-addresses")
def proxy_ip_addresses(keyword: str | None = None, limit: int = 25, offset: int = 0,
                       user: PlatformUser = Depends(require_security),
                       db: Session = Depends(get_db)):
    cfg, client = _client_or_409(db)
    try:
        return client.list_ip_addresses(keyword=keyword, limit=limit, offset=offset)
    except (NetboxUnavailable, NetboxApiError) as exc:
        raise _proxy_502(exc) from exc
    finally:
        client.close()


@router.get("/options")
def proxy_options(user: PlatformUser = Depends(require_security),
                  db: Session = Depends(get_db)):
    """推送弹窗下拉数据: sites/roles/device_types, 附 base_url 供外链。"""
    cfg, client = _client_or_409(db)
    try:
        return {
            "sites": client.list_sites(),
            "roles": client.list_device_roles(),
            "device_types": client.list_device_types(),
            "base_url": cfg["base_url"],
        }
    except (NetboxUnavailable, NetboxApiError) as exc:
        raise _proxy_502(exc) from exc
    finally:
        client.close()


# ────────────────────────── 写回 ──────────────────────────

class NetboxDevicePushIn(BaseModel):
    """推送一条基础设施资产为 NetBox 设备; 成功后回填 asset 的 netbox_ref_*。"""

    project_id: int
    asset_id: int
    name: str = Field(min_length=1, max_length=200)
    site_id: int
    role_id: int
    device_type_id: int
    ip_address: str | None = Field(default=None, max_length=64)


def _find_exact(rows: list[dict], key: str, value: str) -> dict | None:
    lowered = value.strip().lower()
    for row in rows:
        if str(row.get(key) or "").strip().lower() == lowered:
            return row
    return None


@router.post("/devices")
def push_device(payload: NetboxDevicePushIn,
                user: PlatformUser = Depends(require_security),
                db: Session = Depends(get_db)):
    _require_security_role(user)
    asset = db.get(InfraAsset, payload.asset_id)
    project = db.get(Project, payload.project_id)
    # #194 资产挂系统: 资产须属于该评估所挂的系统, 访问口径随项目走
    if asset is None or project is None or asset.system_id != project.system_id:
        raise HTTPException(status_code=404, detail=f"资产不存在: id={payload.asset_id}")
    ensure_project_access(user, project)
    if asset.netbox_ref_id:
        raise HTTPException(status_code=409,
                            detail=f"该资产已关联 NetBox 对象({asset.netbox_ref_id}), 无需重复推送")

    cfg, client = _client_or_409(db)
    try:
        # 名称查重: NetBox 侧已存在同名设备则拒绝(附外链), 失败可重试不回滚
        dup = _find_exact(client.list_devices(keyword=payload.name, limit=100)["results"],
                          "name", payload.name)
        if dup:
            raise HTTPException(
                status_code=409,
                detail=f"NetBox 已存在同名设备「{payload.name}」: {dup.get('url') or '(无外链)'}")

        device = client.create_device({
            "name": payload.name,
            "site": payload.site_id,
            "role": payload.role_id,
            "device_type": payload.device_type_id,
            "status": "active",
        })
        device_id = device.get("id")
        note = None
        if payload.ip_address:
            # 可选建 IP 并挂设备主 IP; IP 环节失败不影响设备结果(旁路不回滚)
            try:
                ip = client.create_ip_address({"address": payload.ip_address, "status": "active"})
                client.patch_device(device_id, {"primary_ip4": {"address": ip["address"]}})
            except (NetboxUnavailable, NetboxApiError) as exc:
                logger.warning("推送设备 %s 的可选 IP 失败(设备已建): %s", payload.name, exc)
                note = f"设备已创建, 但 IP {payload.ip_address} 创建/挂载失败: {exc}"

        asset.netbox_ref_type = "dcim.device"
        asset.netbox_ref_id = str(device_id)
        db.commit()
        audit(db, user.username, "netbox_push",
              {"asset_id": asset.id, "netbox_device_id": device_id})
        return {
            "netbox_ref_type": asset.netbox_ref_type,
            "netbox_ref_id": asset.netbox_ref_id,
            "url": device.get("display_url") or device.get("url")
                or f"{cfg['base_url']}/dcim/devices/{device_id}/",
            **({"note": note} if note else {}),
        }
    except (NetboxUnavailable, NetboxApiError) as exc:
        raise _proxy_502(exc) from exc
    finally:
        client.close()


# ────────────────────────── 系统清单互通(#154) ──────────────────────────

@router.get("/systems")
def proxy_systems(keyword: str | None = None, limit: int = 25, offset: int = 0,
                  user: PlatformUser = Depends(require_security),
                  db: Session = Depends(get_db)):
    """custom-objects 系统清单代理: 按 field_map 裁剪为 {id, name, code, owner, url}。"""
    cfg, client = _client_or_409(db)
    fm = cfg.get("field_map") or {}
    name_key, code_key, owner_key = fm.get("name") or "name", fm.get("code") or "code", fm.get("owner") or "owner"
    try:
        data = client.list_system_objects(cfg["system_slug"], keyword, limit, offset)
    except (NetboxUnavailable, NetboxApiError) as exc:
        raise _proxy_502(exc) from exc
    finally:
        client.close()
    results = [
        {
            "id": row.get("id"),
            "name": row.get(name_key),
            "code": row.get(code_key),
            "owner": row.get(owner_key),
            "url": row.get("display_url") or row.get("url"),
        }
        for row in (data.get("results") or []) if isinstance(row, dict)
    ]
    return {"count": data.get("count", len(results)), "results": results}


class NetboxSystemPushIn(BaseModel):
    """推送一条台账系统为 NetBox system 对象; 成功后回填 netbox_object_id。"""

    system_id: int
    name: str = Field(min_length=1, max_length=200)
    code: str | None = Field(default=None, max_length=64)
    owner: str | None = Field(default=None, max_length=50)


@router.post("/systems")
def push_system(payload: NetboxSystemPushIn,
                user: PlatformUser = Depends(require_security),
                db: Session = Depends(get_db)):
    _require_security_role(user)
    system = db.get(System, payload.system_id)
    if system is None or (
        user.role != "security" and system.owner_user_id not in (None, user.id)
    ):
        raise HTTPException(status_code=404, detail=f"系统不存在: id={payload.system_id}")
    if system.netbox_object_id:
        raise HTTPException(status_code=409,
                            detail=f"该系统已关联 NetBox 对象({system.netbox_object_id}), 无需重复推送")

    cfg, client = _client_or_409(db)
    fm = cfg.get("field_map") or {}
    name_key = fm.get("name") or "name"
    try:
        # 名称查重: NetBox 侧已存在同名系统对象则拒绝(附外链), 失败可重试
        data = client.list_system_objects(cfg["system_slug"], payload.name, 100, 0)
        lowered = payload.name.strip().lower()
        for row in data.get("results") or []:
            if isinstance(row, dict) and str(row.get(name_key) or "").strip().lower() == lowered:
                url = row.get("display_url") or row.get("url")
                raise HTTPException(
                    status_code=409,
                    detail=f"NetBox 已存在同名系统「{payload.name}」: {url or '(无外链)'}")
        obj_payload = {name_key: payload.name}
        if payload.code and fm.get("code"):
            obj_payload[fm["code"]] = payload.code
        if payload.owner and fm.get("owner"):
            obj_payload[fm["owner"]] = payload.owner
        created = client.create_system_object(cfg["system_slug"], obj_payload)
    except (NetboxUnavailable, NetboxApiError) as exc:
        raise _proxy_502(exc) from exc
    finally:
        client.close()

    system.netbox_object_id = str(created.get("id"))
    db.commit()
    audit(db, user.username, "netbox_push",
          {"system_id": system.id, "netbox_system_id": system.netbox_object_id})
    return {
        "netbox_object_id": system.netbox_object_id,
        "url": created.get("display_url") or created.get("url"),
    }


class NetboxIpPushIn(BaseModel):
    address: str = Field(min_length=1, max_length=64)
    status: str = Field(default="active", max_length=32)


@router.post("/ip-addresses")
def push_ip_address(payload: NetboxIpPushIn,
                    user: PlatformUser = Depends(require_security),
                    db: Session = Depends(get_db)):
    """独立建 IP(不挂设备), 推送前按地址查重。"""
    _require_security_role(user)
    cfg, client = _client_or_409(db)
    try:
        dup = _find_exact(client.list_ip_addresses(keyword=payload.address, limit=100)["results"],
                          "address", payload.address)
        if dup:
            raise HTTPException(
                status_code=409,
                detail=f"NetBox 已存在该地址 {payload.address}: {dup.get('url') or '(无外链)'}")
        created = client.create_ip_address({"address": payload.address, "status": payload.status})
        audit(db, user.username, "netbox_push", {"netbox_ip": payload.address})
        return {"id": created.get("id"), "address": created.get("address"),
                "url": created.get("display_url") or created.get("url")}
    except (NetboxUnavailable, NetboxApiError) as exc:
        raise _proxy_502(exc) from exc
    finally:
        client.close()
