# -*- coding: utf-8 -*-
"""NetBox 同步端点(#271 重设计): 系统管理内的单向 ETL。

- /api/netbox 前缀不在 OPEN_API_PREFIXES, 全局 auth_guard 自动要求登录;
- #196: NetBox 仅安全角色可见可用, 其他角色界面零感知, 直调 API 一律 403;
- #271: 逐条手工推送/导入端点全部下线, 收敛为「定时 + 手动」的一键同步 ETL
  (SecReq → NetBox 单向推送, 幂等 upsert, 见 services/netbox_sync);
- 同步执行期间再次触发(手动或定时)一律 409, 结果与逐条错误见同步日志。
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from models import NetboxSyncLog, PlatformUser
from routers.admin import require_security
from routers.common import get_db
from services.audit_service import audit
from services.netbox_sync import run_sync, sync_state
from services.settings_service import get_netbox_config, get_netbox_schedule

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/netbox", tags=["netbox"])


def _log_out(log: NetboxSyncLog) -> dict:
    return {
        "id": log.id,
        "trigger": log.trigger,
        "status": log.status,
        "started_at": log.started_at.isoformat() if log.started_at else None,
        "finished_at": log.finished_at.isoformat() if log.finished_at else None,
        "stats": log.stats or {},
        "errors": log.errors or [],
    }


@router.get("/status")
def netbox_status(user: PlatformUser = Depends(require_security),
                  db: Session = Depends(get_db)):
    """连接配置探测: 管理页判断是否已配置(不再对外提供 base_url 外链)。"""
    cfg = get_netbox_config(db)
    return {"configured": bool(cfg)}


@router.get("/sync/state")
def sync_state_endpoint(user: PlatformUser = Depends(require_security),
                        db: Session = Depends(get_db)):
    """当前同步状态: 是否执行中 + 调度配置 + 最近一轮日志。"""
    last = db.query(NetboxSyncLog).order_by(NetboxSyncLog.id.desc()).first()
    return {
        "running": sync_state.running,
        "schedule": get_netbox_schedule(db),
        "last": _log_out(last) if last else None,
    }


@router.post("/sync/run")
def sync_run(user: PlatformUser = Depends(require_security),
             db: Session = Depends(get_db)):
    """手动触发一轮同步(内联执行); 未配置 409, 执行中 409。"""
    if not get_netbox_config(db):
        raise HTTPException(
            status_code=409, detail="NetBox 尚未配置, 请在 平台设置 → Netbox 管理 填写地址与 Token")
    if not sync_state.begin():
        raise HTTPException(status_code=409, detail="已有一轮同步在执行, 请稍后再试")
    try:
        log = run_sync(db, "manual")
    finally:
        sync_state.end()
    audit(db, user.username, "netbox_sync",
          {"log_id": log.id, "status": log.status,
           "trigger": "manual"})
    return _log_out(log)


@router.get("/sync/logs")
def sync_logs(limit: int = 20,
              user: PlatformUser = Depends(require_security),
              db: Session = Depends(get_db)):
    """同步执行历史(倒序), 管理端历史表用。"""
    rows = (
        db.query(NetboxSyncLog)
        .order_by(NetboxSyncLog.id.desc())
        .limit(min(max(limit, 1), 100))
        .all()
    )
    return [_log_out(r) for r in rows]
