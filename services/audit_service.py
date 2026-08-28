# -*- coding: utf-8 -*-
"""审计日志服务: 敏感动作统一留痕(登录/生成/确认/知识库与用户管理变更)。"""
from sqlalchemy.orm import Session

from models import AuditLog


def audit(db: Session, username: str | None, action: str,
          detail: dict | None = None, ip: str | None = None) -> None:
    """追加一条审计记录; 失败不影响主流程(留痕尽力而为)。"""
    try:
        db.add(AuditLog(
            username=username or "-",
            action=action,
            detail=detail or {},
            ip=ip,
        ))
        db.commit()
    except Exception:
        db.rollback()
