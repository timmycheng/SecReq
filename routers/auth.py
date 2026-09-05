# -*- coding: utf-8 -*-
"""平台认证路由: 账号+密码登录 → Bearer token; 登出/改密/当前用户。

本路由下 /login 属开放路径(routers.common.OPEN_API_PREFIXES),
其余接口经 get_current_user 鉴权。
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

import shared.constants as C
from models import PlatformUser
from routers.common import get_current_user, get_db
from schemas.platform_user import (
    ChangePasswordIn, LoginIn, LoginOut, PasswordChangeResult,
)
from services.audit_service import audit
from services.auth_service import (
    get_user, hash_password, verify_password,
)
from services.session_service import (
    clear_login_failures, create_session, login_locked,
    record_login_failure, revoke_session, revoke_user_sessions,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _login_out(user: PlatformUser, token: str | None = None) -> LoginOut:
    return LoginOut(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        employee_id=user.employee_id,
        role=user.role,
        role_label=C.label(C.PLATFORM_ROLES, user.role),
        token=token,
    )


@router.post("/login", response_model=LoginOut)
def login(payload: LoginIn, request: Request, db: Session = Depends(get_db)):
    """校验账密签发会话 token。连续失败达到阈值后临时锁定。"""
    username = payload.username.strip()
    if login_locked(username):
        raise HTTPException(status_code=429, detail="失败次数过多, 账号已临时锁定, 请5分钟后再试")
    user = get_user(db, username)
    if user is None or not verify_password(payload.password, user.password_hash):
        record_login_failure(username)
        audit(db, username, "login_failed", {}, request.client.host if request.client else None)
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    clear_login_failures(username)
    token = create_session(db, user, ip=request.client.host if request.client else None)
    audit(db, user.username, "login", {}, request.client.host if request.client else None)
    return _login_out(user, token=token)


@router.post("/logout", status_code=204)
def logout(
    request: Request,
    db: Session = Depends(get_db),
    _: PlatformUser | None = Depends(get_current_user),
):
    """吊销当前会话(请求头里的 token)。"""
    auth = request.headers.get("Authorization") or ""
    token = auth[len("Bearer "):].strip() if auth.startswith("Bearer ") else None
    revoke_session(db, token)


@router.post("/change-password", response_model=PasswordChangeResult)
def change_password(
    payload: ChangePasswordIn,
    db: Session = Depends(get_db),
    user: PlatformUser = Depends(get_current_user),
):
    """修改本人密码; 成功后吊销该用户全部旧会话(需重新登录)。"""
    if user is None:
        raise HTTPException(status_code=401, detail="未登录或会话已过期, 请重新登录")
    if not verify_password(payload.old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="原密码不正确")
    if len(payload.new_password) < 8:
        raise HTTPException(status_code=400, detail="新密码至少8位")
    if payload.new_password == payload.old_password:
        raise HTTPException(status_code=400, detail="新密码不能与原密码相同")
    user.password_hash = hash_password(payload.new_password)
    revoke_user_sessions(db, user.username)
    return PasswordChangeResult(message="密码已修改, 请使用新密码重新登录")


@router.get("/me", response_model=LoginOut | None)
def me(user: PlatformUser | None = Depends(get_current_user)):
    if user is None:
        return None
    return _login_out(user)
