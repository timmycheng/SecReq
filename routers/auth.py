# -*- coding: utf-8 -*-
"""平台身份路由(MVP): 用户清单 + 登录校验 + 当前身份。

无口令设计: 请求经 X-Auth-User 头携带用户名; 本路由属开放路径
(routers.common.OPEN_API_PREFIXES), RBAC 拦截见 routers/common.py。
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import shared.constants as C
from models import PlatformUser
from routers.common import get_current_user, get_db
from schemas.review import LoginIn, LoginOut, UserOut
from services.auth_service import ensure_seed_users, get_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db)):
    """演示用户清单(前端身份切换下拉数据源)。"""
    ensure_seed_users(db)
    return db.query(PlatformUser).filter_by(active=True).order_by(PlatformUser.id).all()


@router.post("/login", response_model=LoginOut)
def login(payload: LoginIn, db: Session = Depends(get_db)):
    """校验用户名存在并回显角色(MVP 无口令)。"""
    ensure_seed_users(db)
    user = get_user(db, payload.username)
    if user is None:
        raise HTTPException(status_code=401, detail="用户不存在或已停用")
    return LoginOut(
        username=user.username,
        display_name=user.display_name,
        employee_id=user.employee_id,
        role=user.role,
        role_label=C.label(C.PLATFORM_ROLES, user.role),
    )


@router.get("/me", response_model=LoginOut | None)
def me(user: PlatformUser | None = Depends(get_current_user)):
    if user is None:
        return None
    return LoginOut(
        username=user.username,
        display_name=user.display_name,
        employee_id=user.employee_id,
        role=user.role,
        role_label=C.label(C.PLATFORM_ROLES, user.role),
    )
