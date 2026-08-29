# -*- coding: utf-8 -*-
"""系统管理路由(仅安全角色): 知识库/题库/策略基线/LLM接入/用户/审计日志。

走查整改: 知识库策略可视化、可配置; 平台自身安全功能(用户管理、审计留痕)到位。
"""
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import shared.constants as C
from models import AuditLog, PlatformUser
from routers.common import get_db, require_login
from services.audit_service import audit
from services.auth_service import (
    SEED_DEFAULT_PASSWORD, get_user, hash_password,
)
from services.kb_admin import (
    add_template, list_templates, load_question_bank_raw,
    save_question_bank, update_template,
)
from services.session_service import revoke_user_sessions
from services.settings_service import get_llm_config, get_setting, set_setting

router = APIRouter(prefix="/api/admin", tags=["admin"])


def require_security(user: PlatformUser = Depends(require_login)) -> PlatformUser:
    """系统管理仅安全角色可用。"""
    if user.role != "security":
        raise HTTPException(status_code=403, detail="仅安全角色可访问系统管理")
    return user


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


# ── 知识库 ────────────────────────────────────────────
@router.get("/knowledge-base")
def get_knowledge_base(keyword: str | None = None,
                       _: PlatformUser = Depends(require_security)):
    rows = list_templates()
    if keyword:
        rows = [r for r in rows if keyword.lower() in r["id"].lower() or keyword in r["title"]]
    return {"total": len(rows), "templates": rows}


class TemplateUpdateIn(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    description: str | None = None
    priority: str | None = None
    suggested_phase: str | None = None
    acceptance_criteria: str | None = None
    trigger_reason: str | None = None
    trigger: dict | None = None
    enabled: bool | None = None


@router.put("/knowledge-base/{template_id}")
def put_template(template_id: str, payload: TemplateUpdateIn, request: Request,
                 db: Session = Depends(get_db),
                 user: PlatformUser = Depends(require_security)):
    changes = payload.model_dump(exclude_none=True)
    try:
        row = update_template(template_id, changes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit(db, user.username, "kb_update", {"template_id": template_id}, _client_ip(request))
    return row


class TemplateCreateIn(TemplateUpdateIn):
    id: str = Field(min_length=3, max_length=40)
    regulatory_ref: list[dict] = Field(default_factory=list)


@router.post("/knowledge-base", status_code=201)
def post_template(payload: TemplateCreateIn, request: Request,
                  db: Session = Depends(get_db),
                  user: PlatformUser = Depends(require_security)):
    data = payload.model_dump(exclude_none=True)
    required = ["id", "trigger", "title", "priority", "suggested_phase",
                "acceptance_criteria", "trigger_reason", "regulatory_ref"]
    missing = [k for k in required if not data.get(k)]
    if missing:
        raise HTTPException(status_code=400, detail=f"缺少必填字段: {missing}")
    try:
        row = add_template(data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit(db, user.username, "kb_create", {"template_id": payload.id}, _client_ip(request))
    return row


# ── 定级题库 ──────────────────────────────────────────
@router.get("/grading-questions")
def get_question_bank(_: PlatformUser = Depends(require_security)):
    return load_question_bank_raw()


@router.put("/grading-questions")
def put_question_bank(bank: dict, request: Request,
                      db: Session = Depends(get_db),
                      user: PlatformUser = Depends(require_security)):
    try:
        save_question_bank(bank)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit(db, user.username, "questions_update", {}, _client_ip(request))
    return {"status": "ok"}


# ── 密码策略基线 ──────────────────────────────────────
@router.get("/policy-baselines")
def get_policy_baselines(_: PlatformUser = Depends(require_security)):
    from rules.policy import get_policy_baselines
    return {
        "baselines": get_policy_baselines(),
        "lockout_threshold": C.DEFAULT_LOCKOUT_THRESHOLD,
        "session_timeout_min": C.DEFAULT_SESSION_TIMEOUT_MIN,
    }


class PolicyBaselinesIn(BaseModel):
    baselines: dict = Field(description='{"三级": {pwd_min_length..}, ...}')
    lockout_threshold: int = Field(ge=1, le=100)
    session_timeout_min: int = Field(ge=1, le=1440)


@router.put("/policy-baselines")
def put_policy_baselines(payload: PolicyBaselinesIn, request: Request,
                         db: Session = Depends(get_db),
                         user: PlatformUser = Depends(require_security)):
    for level in C.GRADING_LEVELS:
        base = payload.baselines.get(level)
        if not isinstance(base, dict):
            raise HTTPException(status_code=400, detail=f"缺少 {level} 的基线配置")
    set_setting(db, "policy_baselines", {
        "baselines": payload.baselines,
        "lockout_threshold": payload.lockout_threshold,
        "session_timeout_min": payload.session_timeout_min,
    })
    _apply_policy_settings(db)
    audit(db, user.username, "policy_update", payload.baselines, _client_ip(request))
    return {"status": "ok"}


def _apply_policy_settings(db: Session) -> None:
    """把库内策略覆盖注入运行时(lifespan 启动时与本保存接口共用)。"""
    from rules.policy import set_policy_baselines
    from services.settings_service import get_setting

    stored = get_setting(db, "policy_baselines")
    if stored.get("baselines"):
        set_policy_baselines(stored["baselines"])


# ── LLM 接入配置 ──────────────────────────────────────
@router.get("/llm-config")
def get_llm(_: PlatformUser = Depends(require_security), db: Session = Depends(get_db)):
    cfg = get_llm_config(db)
    if cfg.get("api_key"):
        cfg["api_key"] = cfg["api_key"][:4] + "****"
    cfg["configured"] = bool(cfg)
    return cfg


class LlmConfigIn(BaseModel):
    base_url: str = Field(max_length=300)
    api_key: str = Field(max_length=300)
    model: str = Field(max_length=100)


@router.put("/llm-config")
def put_llm(payload: LlmConfigIn, request: Request,
            db: Session = Depends(get_db),
            user: PlatformUser = Depends(require_security)):
    set_setting(db, "llm", payload.model_dump())
    audit(db, user.username, "llm_update", {"base_url": payload.base_url, "model": payload.model},
          _client_ip(request))
    return {"status": "ok"}


# ── 用户管理 ──────────────────────────────────────────
@router.get("/users")
def list_users(_: PlatformUser = Depends(require_security), db: Session = Depends(get_db)):
    return [
        {
            "id": u.id, "username": u.username, "display_name": u.display_name,
            "employee_id": u.employee_id, "role": u.role, "active": bool(u.active),
        }
        for u in db.query(PlatformUser).order_by(PlatformUser.id).all()
    ]


class UserCreateIn(BaseModel):
    username: str = Field(min_length=2, max_length=50)
    display_name: str = Field(min_length=1, max_length=50)
    employee_id: str | None = Field(default=None, max_length=30)
    role: str
    password: str | None = Field(default=None, min_length=8, max_length=128)


@router.post("/users", status_code=201)
def create_user(payload: UserCreateIn, request: Request,
                db: Session = Depends(get_db),
                user: PlatformUser = Depends(require_security)):
    if payload.role not in C.PLATFORM_ROLES:
        raise HTTPException(status_code=400, detail=f"未知角色: {payload.role}")
    if get_user(db, payload.username) or db.query(PlatformUser).filter_by(username=payload.username).first():
        raise HTTPException(status_code=409, detail=f"用户已存在: {payload.username}")
    db.add(PlatformUser(
        username=payload.username, display_name=payload.display_name,
        employee_id=payload.employee_id, role=payload.role,
        password_hash=hash_password(payload.password or SEED_DEFAULT_PASSWORD),
    ))
    db.commit()
    audit(db, user.username, "user_create", {"target": payload.username, "role": payload.role},
          _client_ip(request))
    return {"status": "ok",
            "initial_password": payload.password or SEED_DEFAULT_PASSWORD}


class PasswordResetIn(BaseModel):
    password: str | None = Field(default=None, min_length=8, max_length=128,
                                 description="缺省时由后端生成随机密码并在响应中返回")


@router.post("/users/{username}/reset-password")
def reset_password(username: str, payload: PasswordResetIn, request: Request,
                   db: Session = Depends(get_db),
                   user: PlatformUser = Depends(require_security)):
    target = db.query(PlatformUser).filter_by(username=username).first()
    if target is None:
        raise HTTPException(status_code=404, detail=f"用户不存在: {username}")
    new_password = payload.password or secrets.token_urlsafe(12)
    target.password_hash = hash_password(new_password)
    revoke_user_sessions(db, username)
    audit(db, user.username, "user_reset_password", {"target": username}, _client_ip(request))
    return {"status": "ok", "password": None if payload.password else new_password}


@router.post("/users/{username}/toggle-active")
def toggle_active(username: str, request: Request,
                  db: Session = Depends(get_db),
                  user: PlatformUser = Depends(require_security)):
    target = db.query(PlatformUser).filter_by(username=username).first()
    if target is None:
        raise HTTPException(status_code=404, detail=f"用户不存在: {username}")
    if target.username == user.username:
        raise HTTPException(status_code=400, detail="不能停用自己")
    target.active = not target.active
    if not target.active:
        revoke_user_sessions(db, username)
    db.commit()
    audit(db, user.username, "user_toggle", {"target": username, "active": bool(target.active)},
          _client_ip(request))
    return {"username": username, "active": bool(target.active)}


# ── 审计日志 ──────────────────────────────────────────
@router.get("/audit-logs")
def list_audit_logs(limit: int = 200,
                    _: PlatformUser = Depends(require_security), db: Session = Depends(get_db)):
    rows = db.query(AuditLog).order_by(AuditLog.id.desc()).limit(min(limit, 500)).all()
    return [
        {
            "id": r.id, "username": r.username, "action": r.action,
            "detail": r.detail, "ip": r.ip, "created_at": r.created_at.isoformat(sep=" ", timespec="seconds"),
        }
        for r in rows
    ]
