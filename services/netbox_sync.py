# -*- coding: utf-8 -*-
"""NetBox 同步引擎(#271): SecReq → NetBox 单向 ETL。

语义约定(见 issue #271 细化): NetBox 只是后备资产库, 只推不拉;
系统基础设施的「选择/填报」永远由用户在 SecReq 内维护(不从 NetBox 导入),
同步只把已录入的事实推到 NetBox 侧存档。

- 幂等 upsert: 系统按 netbox_object_id(断链回退名称精确匹配)定位,
  字段无变化跳过、有变化 PATCH; 基础设施资产同理按 netbox_ref_id / 名称;
  IP 按地址全局唯一, 不重复建。
- 引导对象: dcim 设备的 site/role/device_type/manufacturer 为必填外键,
  同步使用约定的 secreq-* 引导对象(slug 定位, 缺失自动创建一次),
  不虚构用户未填报的业务属性。
- 容错: 单对象失败记入本轮 errors 明细, 不中断整轮; 结果回填
  netbox_object_id / netbox_ref_id, 供下轮增量更新与外链。
- 调度: start_scheduler 起守护线程周期触发(读 netbox 配置的 enabled/interval_hours);
  手动触发经 /api/netbox/sync/run, 二者共用 run_sync 与互斥状态。

测试: 网络层可注入 NetboxClient(transport)或直接 monkeypatch run_sync 内部步骤;
调度线程用 SECREQ_DISABLE_NETBOX_SCHEDULER=1 关停(单测不依赖真实周期)。
"""
import logging
import os
import threading
import time
from datetime import datetime

from sqlalchemy.orm import Session

from models import InfraAsset, NetboxSyncLog, System
from services.netbox import NetboxApiError, NetboxClient, NetboxUnavailable
from services.settings_service import get_netbox_config, get_netbox_schedule

logger = logging.getLogger(__name__)

#: 调度循环的检查间隔(秒): 到期判断粒度, 与同步周期解耦
SCHEDULER_TICK_SECONDS = 60.0

#: 引导对象的固定 slug(带 secreq- 前缀避免与真实资产混淆)
BOOTSTRAP_SITE_SLUG = "secreq"
BOOTSTRAP_ROLE_SLUG = "secreq-infra"
BOOTSTRAP_DEVICE_TYPE_SLUG = "secreq-generic"
BOOTSTRAP_MANUFACTURER_SLUG = "secreq"


class SyncState:
    """进程内互斥: 同一时刻只允许一轮同步(手动与定时共用)。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._running = False

    def begin(self) -> bool:
        with self._lock:
            if self._running:
                return False
            self._running = True
            return True

    def end(self) -> None:
        with self._lock:
            self._running = False

    @property
    def running(self) -> bool:
        with self._lock:
            return self._running


sync_state = SyncState()


def _blank_stats() -> dict:
    return {
        "systems": {"created": 0, "updated": 0, "skipped": 0, "failed": 0},
        "devices": {"created": 0, "updated": 0, "skipped": 0, "failed": 0},
        "ips": {"created": 0, "skipped": 0, "failed": 0},
    }


def _finalize_status(stats: dict) -> str:
    failed = sum(v.get("failed", 0) for v in stats.values())
    touched = sum(v.get("created", 0) + v.get("updated", 0) for v in stats.values())
    if failed and touched:
        return "partial"
    if failed:
        return "failed"
    return "success"


def _find_exact(rows: list[dict], key: str, value: str) -> dict | None:
    lowered = value.strip().lower()
    for row in rows:
        if str(row.get(key) or "").strip().lower() == lowered:
            return row
    return None


def _sync_system(db: Session, cfg: dict, client: NetboxClient,
                 system: System, stats: dict, errors: list[str]) -> None:
    """单个系统的 upsert: id 断链 → 名称匹配 → 新建; 字段无变化跳过。"""
    slug = cfg["system_slug"]
    fm = cfg.get("field_map") or {}
    name_key = fm.get("name") or "name"
    payload: dict = {name_key: system.name}
    if system.code and fm.get("code"):
        payload[fm["code"]] = system.code
    if system.owner_name and fm.get("owner"):
        payload[fm["owner"]] = system.owner_name
    try:
        obj = None
        if system.netbox_object_id:
            try:
                obj = client.get_system_object(slug, system.netbox_object_id)
            except NetboxApiError:
                # 关联已失效(对端被删): 断链后按名称重建关联
                system.netbox_object_id = None
        if obj is None:
            found = client.list_system_objects(slug, system.name, 100, 0).get("results") or []
            obj = _find_exact(found, name_key, system.name)
            if obj is not None:
                system.netbox_object_id = str(obj.get("id"))
        if obj is None:
            created = client.create_system_object(slug, payload)
            system.netbox_object_id = str(created.get("id"))
            stats["systems"]["created"] += 1
            return
        changed = {k: v for k, v in payload.items() if obj.get(k) != v}
        if changed:
            client.patch_system_object(slug, obj["id"], changed)
            stats["systems"]["updated"] += 1
        else:
            stats["systems"]["skipped"] += 1
    except (NetboxUnavailable, NetboxApiError) as exc:
        stats["systems"]["failed"] += 1
        errors.append(f"系统「{system.name}」: {exc}")


def _ensure_bootstrap_objects(client: NetboxClient) -> dict:
    """定位/创建 secreq-* 引导对象, 返回 site/role/device_type 的 NetBox id。

    device_type 必挂 manufacturer, 因此引导对象共四类; 全部 slug 定位、幂等。
    """
    site = _find_exact(client.list_sites(), "slug", BOOTSTRAP_SITE_SLUG)
    if site is None:
        site = client.create_site(
            {"name": "SecReq 同步", "slug": BOOTSTRAP_SITE_SLUG})
    role = _find_exact(client.list_device_roles(), "slug", BOOTSTRAP_ROLE_SLUG)
    if role is None:
        role = client.create_device_role(
            {"name": "SecReq 基础设施", "slug": BOOTSTRAP_ROLE_SLUG})
    device_type = _find_exact(client.list_device_types(), "slug", BOOTSTRAP_DEVICE_TYPE_SLUG)
    if device_type is None:
        manufacturers = client.list_manufacturers()
        manufacturer = _find_exact(manufacturers, "slug", BOOTSTRAP_MANUFACTURER_SLUG)
        if manufacturer is None:
            manufacturer = client.create_manufacturer(
                {"name": "SecReq 同步", "slug": BOOTSTRAP_MANUFACTURER_SLUG})
        device_type = client.create_device_type({
            "model": "SecReq 通用机型", "slug": BOOTSTRAP_DEVICE_TYPE_SLUG,
            "manufacturer": manufacturer["id"],
        })
    return {"site": site["id"], "role": role["id"], "device_type": device_type["id"]}


def _sync_device_and_ip(db: Session, client: NetboxClient, asset: InfraAsset,
                        bootstrap: dict, stats: dict, errors: list[str]) -> None:
    """单条基础设施资产 → dcim 设备 upsert; 带 IP 时顺带建/挂主 IP(可分离失败)。"""
    try:
        payload = {
            "name": asset.name, "site": bootstrap["site"],
            "role": bootstrap["role"], "device_type": bootstrap["device_type"],
            "status": "active",
        }
        obj = None
        if asset.netbox_ref_id:
            try:
                obj = client.get_device(asset.netbox_ref_id)
            except NetboxApiError:
                asset.netbox_ref_id = None
        if obj is None:
            found = client.list_devices(keyword=asset.name, limit=100).get("results") or []
            obj = _find_exact(found, "name", asset.name)
            if obj is not None:
                asset.netbox_ref_id = str(obj.get("id"))
        if obj is None:
            created = client.create_device(payload)
            asset.netbox_ref_id = str(created.get("id"))
            stats["devices"]["created"] += 1
        elif obj.get("name") != asset.name:
            client.patch_device(obj["id"], {"name": asset.name})
            stats["devices"]["updated"] += 1
        else:
            stats["devices"]["skipped"] += 1
    except (NetboxUnavailable, NetboxApiError) as exc:
        stats["devices"]["failed"] += 1
        errors.append(f"资产「{asset.name}」: {exc}")
        return

    if not asset.ip:
        return
    try:
        # 已有主 IP 则跳过; 否则按地址去重后建 IP 并挂为设备主 IP
        device = client.get_device(asset.netbox_ref_id) if asset.netbox_ref_id else None
        if device and device.get("primary_ip4"):
            stats["ips"]["skipped"] += 1
            return
        found = client.list_ip_addresses(keyword=asset.ip, limit=100).get("results") or []
        ip_row = _find_exact(found, "address", asset.ip)
        if ip_row is None:
            ip_row = client.create_ip_address({"address": asset.ip, "status": "active"})
            stats["ips"]["created"] += 1
        else:
            stats["ips"]["skipped"] += 1
        if asset.netbox_ref_id:
            client.patch_device(asset.netbox_ref_id, {"primary_ip4": ip_row["address"]})
    except (NetboxUnavailable, NetboxApiError) as exc:
        stats["ips"]["failed"] += 1
        errors.append(f"资产「{asset.name}」的 IP {asset.ip}: {exc}")


def run_sync(db: Session, trigger: str,
             client: NetboxClient | None = None) -> NetboxSyncLog:
    """执行一轮同步并落日志; 调用方负责互斥(手动端点/调度循环均先 sync_state.begin)。

    client 参数供测试注入桩客户端; 生产路径不传, 内部按配置自建。
    """
    log = NetboxSyncLog(trigger=trigger, status="running")
    db.add(log)
    db.commit()
    started = time.monotonic()

    cfg = get_netbox_config(db)
    if not cfg:
        log.status = "failed"
        log.errors = ["NetBox 尚未配置, 请在 平台设置 → Netbox 管理 先填写地址与 Token"]
        log.finished_at = datetime.now()
        db.commit()
        return log

    stats = _blank_stats()
    errors: list[str] = []
    own_client = client is None
    if client is None:
        client = NetboxClient(cfg["base_url"], cfg["token"])
    try:
        # 第一级: 系统(custom-objects), 无外键门槛, 永远同步
        for system in db.query(System).order_by(System.id).all():
            _sync_system(db, cfg, client, system, stats, errors)
        # 第二级: 基础设施资产(仅服务器/网络设备) + IP; 引导对象缺失时自动创建
        bootstrap = _ensure_bootstrap_objects(client)
        assets = (
            db.query(InfraAsset)
            .filter(InfraAsset.asset_type.in_(("server", "network")))
            .order_by(InfraAsset.id).all()
        )
        for asset in assets:
            _sync_device_and_ip(db, client, asset, bootstrap, stats, errors)
    except (NetboxUnavailable, NetboxApiError) as exc:
        # 引导对象阶段即失败(如断连): 整轮 failed
        errors.append(f"同步中止: {exc}")
        log.status = "failed"
    else:
        log.status = _finalize_status(stats)
    finally:
        if own_client:
            client.close()

    db.commit()  # 先落 netbox_object_id / netbox_ref_id 回填
    log.stats = stats
    log.errors = errors
    log.finished_at = datetime.now()
    db.commit()
    logger.info("NetBox 同步完成(%s): %.1fs, status=%s, stats=%s",
                trigger, time.monotonic() - started, log.status, stats)
    return log


def start_scheduler(session_factory) -> threading.Thread | None:
    """启动定时同步守护线程; 单测/迁移场景用环境变量关停。"""
    if os.environ.get("SECREQ_DISABLE_NETBOX_SCHEDULER") == "1":
        logger.info("NetBox 定时同步已被环境变量关停")
        return None

    def loop() -> None:
        while True:
            time.sleep(SCHEDULER_TICK_SECONDS)
            db = session_factory()
            try:
                schedule = get_netbox_schedule(db)
                if not schedule["enabled"] or sync_state.running:
                    continue
                last = (
                    db.query(NetboxSyncLog)
                    .order_by(NetboxSyncLog.id.desc()).first()
                )
                if last is not None and last.started_at is not None:
                    elapsed = (datetime.now() - last.started_at).total_seconds()
                    if elapsed < schedule["interval_hours"] * 3600:
                        continue
                run_sync(db, "scheduled")
            except Exception:
                logger.warning("NetBox 定时同步异常", exc_info=True)
            finally:
                db.close()

    thread = threading.Thread(target=loop, name="netbox-sync-scheduler", daemon=True)
    thread.start()
    logger.info("NetBox 定时同步线程已启动(每 %gs 检查一次到期)", SCHEDULER_TICK_SECONDS)
    return thread
