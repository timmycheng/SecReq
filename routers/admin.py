# -*- coding: utf-8 -*-
"""系统管理路由(仅安全角色): 知识库/题库/策略基线/LLM接入/用户/审计日志。

走查整改: 知识库策略可视化、可配置; 平台自身安全功能(用户管理、审计留痕)到位。
"""
import hashlib
import json
import logging
import os
import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import shared.constants as C
from models import AuditLog, PlatformUser
from routers.common import client_ip, get_db, require_login
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

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


def require_security(user: PlatformUser = Depends(require_login)) -> PlatformUser:
    """系统管理仅安全角色可用。"""
    if user.role != "security":
        raise HTTPException(status_code=403, detail="仅安全角色可访问系统管理")
    return user


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
    # 监管出处(每项 {file, clause, summary, note}), 编辑与新建能力对齐(#80);
    # 结构合法性由写回后的 loader 全量校验兜底, 不合法自动回滚
    regulatory_ref: list[dict] | None = None


@router.put("/knowledge-base/{template_id}")
def put_template(template_id: str, payload: TemplateUpdateIn, request: Request,
                 db: Session = Depends(get_db),
                 user: PlatformUser = Depends(require_security)):
    changes = payload.model_dump(exclude_none=True)
    try:
        row = update_template(template_id, changes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit(db, user.username, "kb_update", {"template_id": template_id}, client_ip(request))
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
    audit(db, user.username, "kb_create", {"template_id": payload.id}, client_ip(request))
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
    audit(db, user.username, "questions_update", {}, client_ip(request))
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
    audit(db, user.username, "policy_update", payload.baselines, client_ip(request))
    return {"status": "ok"}


def _apply_policy_settings(db: Session) -> None:
    """把库内策略覆盖注入运行时(lifespan 启动时与本保存接口共用)。"""
    from rules.policy import set_policy_baselines

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
          client_ip(request))
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
          client_ip(request))
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
    audit(db, user.username, "user_reset_password", {"target": username}, client_ip(request))
    return {"status": "ok", "password": None if payload.password else new_password}


class UserUpdateIn(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=50)
    employee_id: str | None = Field(default=None, max_length=30)
    role: str | None = None


@router.put("/users/{username}")
def update_user(username: str, payload: UserUpdateIn, request: Request,
                db: Session = Depends(get_db),
                user: PlatformUser = Depends(require_security)):
    """编辑用户资料(姓名/工号/角色; username 不可改, 审计留痕与权限引用均按 username)。"""
    target = db.query(PlatformUser).filter_by(username=username).first()
    if target is None:
        raise HTTPException(status_code=404, detail=f"用户不存在: {username}")
    changes = payload.model_dump(exclude_none=True)
    if "role" in changes:
        if changes["role"] not in C.PLATFORM_ROLES:
            raise HTTPException(status_code=400, detail=f"未知角色: {changes['role']}")
        if target.username == user.username and changes["role"] != user.role:
            raise HTTPException(status_code=400, detail="不能修改自己的角色")
    for key, value in changes.items():
        setattr(target, key, value)
    db.commit()
    audit(db, user.username, "user_update",
          {"target": username, "role": target.role, "display_name": target.display_name},
          client_ip(request))
    return {"username": username, "display_name": target.display_name,
            "employee_id": target.employee_id, "role": target.role}


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
          client_ip(request))
    return {"username": username, "active": bool(target.active)}


# ── 离线漏洞库(v2.2.0) ─────────────────────────────────
def _normalize_per_eco(raw: dict) -> dict:
    """per_ecosystem 的 key 归一化为平台 code(#61)。

    构建端 v2.2.2 起已写平台 code; 存量库 meta 里是 OSV 原始名(PyPI/Maven/crates.io…),
    按别名表 + 小写兜底归一化, 旧库无需重建即可正确显示各生态记录数。
    逻辑与 scripts/build_vuln_db.py 的 ecosystem_code() 保持一致。
    """
    out: dict = {}
    for key, value in (raw or {}).items():
        base = str(key).split(":")[0].strip()
        base = C.OSV_ECOSYSTEM_ALIASES.get(base, base)
        out[base.lower()] = value
    return out


def _vulndb_snapshot() -> dict:
    """本地漏洞库概况: 版本/生态/记录数/体积/校验和 + 覆盖缺口。"""
    from services.cnnvd import stats as cnnvd_stats
    from services.vulndb import VulnDb
    from services.vuln_source import describe_sources

    db = VulnDb()
    base = {
        "available": False,
        "path": db.path,
        "sources": describe_sources(),
        "cnnvd": cnnvd_stats(),
    }
    if not db.exists():
        return {**base, "reason": f"漏洞库文件不存在: {db.path}"}
    try:
        meta = db.meta()
        imported = db.imported_ecosystems
        covered = db.covered_ecosystems
    except Exception as exc:  # 库损坏/不可读时明确报出, 不伪装成"正常"
        logger.error("读取漏洞库失败(%s): %s", db.path, exc, exc_info=True)
        return {**base, "reason": f"漏洞库无法读取: {exc}"}

    per_eco: dict[str, int] = {}
    try:
        per_eco = _normalize_per_eco(json.loads(meta.get("per_ecosystem") or "{}"))
    except ValueError:
        per_eco = {}

    declared = [e for e in (meta.get("ecosystems") or "").split(",") if e]
    missing = [
        {"code": code, "label": label}
        # other 本就不可导入, 不进"未导入"清单(#31)
        for code, label in C.VULN_ECOSYSTEMS.items()
        if code not in imported and code != "other"
    ]
    try:
        size_mb = round(os.path.getsize(db.path) / 1e6, 2)
    except OSError:
        size_mb = None

    return {
        **base,
        "available": True,
        "db_version": meta.get("db_version"),
        "built_at": meta.get("built_at"),
        "total": int(meta.get("total") or 0),
        "size_mb": size_mb,
        "sha256": _read_expected_sha256(db.path),
        "compressed": meta.get("compressed") == "1",
        "slim": meta.get("slim") == "1",
        "declared_ecosystems": [
            {"code": code, "label": C.VULN_ECOSYSTEMS.get(code, code), "records": per_eco.get(code)}
            for code in declared
        ],
        "imported_ecosystems": sorted(imported),
        # 真正覆盖 = 声明导入 ∩ 实际入库。OSV 的多生态公告会在一个生态的 zip 里
        # 夹带其他生态的包坐标(实测 Maven/all.zip 带 92 条 npm), 按"有记录即覆盖"
        # 会把只导了部分生态的库当成全覆盖 —— 最危险的那种虚假安全感。
        "covered_ecosystems": sorted(covered),
        "incidental_ecosystems": sorted(imported - covered),
        "missing_ecosystems": missing,
        "upstream": meta.get("upstream"),
        "gaps": [
            {
                "code": "kylin",
                "label": "银河麒麟",
                "note": C.KYLIN_PROXY_NOTE,
                "detail": (
                    "麒麟不在 OSV 的 39 个生态中, 本平台按 openEuler 同源数据代理匹配。"
                    "麒麟的独立补丁回合、自有组件(KVE 编号)与架构维度均无法覆盖, "
                    "结果仅供参考, 最终以麒麟官方安全公告为准"
                ),
            },
            {
                "code": "k8s",
                "label": "Kubernetes",
                "note": "Bitnami 与 Alpine 生态均无 Kubernetes 覆盖",
                "detail": "需由行内 SCA 或单独数据源补充; 当前一律标注为「未纳入本地漏洞库」",
            },
        ],
    }


@router.get("/vuln-db")
def get_vuln_db(_: PlatformUser = Depends(require_security)):
    """漏洞库状态(管理端「漏洞库」页)。"""
    return _vulndb_snapshot()


@router.post("/vuln-db/verify")
def verify_vuln_db(request: Request, db: Session = Depends(get_db),
                   user: PlatformUser = Depends(require_security)):
    """重算 SHA256 与构建时记录的校验和比对(摆渡完整性核验), 并留审计。

    大库(数百 MB)重算校验和是秒级操作, 故做成显式触发而非随状态查询执行。
    """
    from services.cnnvd import stats as cnnvd_stats
    from services.vuln_source import vulndb_path

    path = vulndb_path()
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail=f"漏洞库文件不存在: {path}")
    digest = _sha256_file(path)
    expected = _read_expected_sha256(path)
    # 三态(#22): true 一致 / false 不一致 / null 无 sidecar 可比对
    ok = (digest == expected) if expected is not None else None
    detail = {
        "path": path,
        "sha256": digest,
        "expected": expected,
        "match": ok,
        "size_mb": round(os.path.getsize(path) / 1e6, 2),
    }
    audit(db, user.username, "vulndb_verify", detail, client_ip(request))
    if ok is False:
        logger.error("漏洞库校验和不匹配: %s(期望 %s)", digest, expected)
    return {**detail, "cnnvd": cnnvd_stats()}


def _sha256_file(path: str, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_expected_sha256(path: str) -> str | None:
    """读构建时产出的 sidecar 校验文件(<库名>.sha256, sha256sum 兼容格式)。

    校验和不放在库内: 往库里写记录会改变文件本身, 库内记录的校验和写入即失效。
    """
    sidecar = Path(path).with_name(Path(path).name + ".sha256")
    if not sidecar.is_file():
        return None
    try:
        return sidecar.read_text(encoding="utf-8").split()[0].strip().lower() or None
    except (OSError, IndexError, UnicodeDecodeError):
        return None


# ── 审计日志 ──────────────────────────────────────────
@router.get("/audit-logs")
def list_audit_logs(limit: int = 200,
                    _: PlatformUser = Depends(require_security), db: Session = Depends(get_db)):
    from services.audit_service import action_label, summarize_detail

    rows = db.query(AuditLog).order_by(AuditLog.id.desc()).limit(min(limit, 500)).all()
    return [
        {
            "id": r.id, "username": r.username, "action": r.action,
            # 动作中文标签与明细可读摘要在后端统一下发(#65), 前端不自映射
            "action_label": action_label(r.action),
            "summary": summarize_detail(r.action, r.detail or {}),
            "detail": r.detail, "ip": r.ip, "created_at": r.created_at.isoformat(sep=" ", timespec="seconds"),
        }
        for r in rows
    ]
