# -*- coding: utf-8 -*-
"""元数据路由: 前后端共享枚举的唯一来源(DESIGN.md 约束第七节)。

前端不硬编码任何枚举选项与中文标签, 启动时从 /api/meta/constants 拉取;
密码策略默认基线、定级问卷题库同样由本路由供数; 工作台聚合数据(#280)也挂这里。
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

import shared.constants as C
from routers.common import get_db, require_login, visible_projects_query
from services.grading import load_questions
from services.step_metrics import step_metrics_report
from services.vuln_source import configured_chain

router = APIRouter(prefix="/api/meta", tags=["meta"])

_ENUMS = {
    "project_types": C.PROJECT_TYPES,
    "user_scales": C.USER_SCALES,
    "project_status": C.PROJECT_STATUS,
    "feature_categories": C.FEATURE_CATEGORIES,
    "sensitivity_levels": C.SENSITIVITY_LEVELS,
    "data_asset_types": C.DATA_ASSET_TYPES,
    "storage_envs": C.STORAGE_ENVS,
    "role_types": C.ROLE_TYPES,
    "resource_types": C.RESOURCE_TYPES,
    "criticality_levels": c if (c := C.CRITICALITY_LEVELS) else {},
    "permission_actions": C.PERMISSION_ACTIONS,
    "auth_methods": C.AUTH_METHODS,
    "sbom_layers": C.SBOM_LAYERS,
    "sbom_source_types": C.SBOM_SOURCE_TYPES,
    # v2.2.0 离线漏洞库: 生态 / 分发渠道 / 查询语义(Step7 下拉与结果展示的唯一来源)
    "vuln_ecosystems": C.VULN_ECOSYSTEMS,
    "sbom_distros": C.SBOM_DISTROS,
    "vuln_query_status": C.VULN_QUERY_STATUS,
    "vuln_query_status_hints": C.VULN_QUERY_STATUS_HINTS,
    "infra_asset_types": C.INFRA_ASSET_TYPES,
    "external_system_directions": C.EXTERNAL_SYSTEM_DIRECTIONS,
    "license_risk": C.LICENSE_RISK,
    "common_components": C.COMMON_COMPONENTS,
    "env_names": C.ENV_NAMES,
    "compliance_targets": C.COMPLIANCE_TARGETS,
    "priority_labels": C.REQUIREMENT_PRIORITY_LABELS,
    "requirement_phases": C.REQUIREMENT_PHASES,
    "requirement_status": C.REQUIREMENT_STATUS,
    "category_labels": C.TRIGGER_CATEGORY_LABELS,
}


@router.get("/constants")
def get_constants(db: Session = Depends(get_db)) -> dict:
    """全部枚举(code→label 映射 + 数组型常量)。"""
    payload: dict = {key: dict(value) for key, value in _ENUMS.items()}
    from services.settings_service import get_infra_envs, get_system_dicts
    payload["infra_envs"] = {e["code"]: e["name"] for e in get_infra_envs(db)}
    # 系统字典(#283): 标签 + 系统类型枚举(系统管理可自定义, types 未配置回退常量)
    dicts = get_system_dicts(db)
    payload["system_tags"] = dicts["tags"]
    payload["project_types"] = dicts["types"]
    payload.update(
        {
            "grading_levels": list(C.GRADING_LEVELS),
            "data_levels": list(C.DATA_LEVELS),
            "data_level_meta": C.DATA_LEVEL_META,
            "data_level_labels": {code: meta["label"] for code, meta in C.DATA_LEVEL_META.items()},
            "platform_roles": C.PLATFORM_ROLES,
            "http_methods": list(C.HTTP_METHODS),
            "high_risk_actions": list(C.HIGH_RISK_ACTIONS),
            "mask_rules": dict(C.MASK_RULES),
            "mask_field_patterns": C.MASK_FIELD_PATTERNS,
            "default_pwd_policy_by_level": C.DEFAULT_PWD_POLICY_BY_LEVEL,
            "default_lockout_threshold": C.DEFAULT_LOCKOUT_THRESHOLD,
            "default_session_timeout_min": C.DEFAULT_SESSION_TIMEOUT_MIN,
            "severity_labels": C.SEVERITY_LABELS,
            "kylin_proxy_note": C.KYLIN_PROXY_NOTE,
            # 部署期数据源链(#94): 界面「漏洞库查询方式」据此定默认与可选项
            "vuln_source_chain": configured_chain(),
        }
    )
    return payload


@router.get("/grading-questions")
def get_grading_questions() -> dict:
    """Step2 题库(basis 判定依据文案由安全中心在 YAML 中维护)。"""
    return {
        "questions": [
            {
                "id": q.id,
                "title": q.title,
                "options": [
                    {"id": o["id"], "label": o.get("label", ""),
                     "score": int(o.get("score", 0)), "basis": o.get("basis", "")}
                    for o in q.options
                ],
            }
            for q in load_questions()
        ]
    }


#: 工作台趋势图的优先级分桶: critical=高 / high=中 / medium+low=低
_DASHBOARD_TREND_BUCKETS = {"critical": "high", "high": "mid", "medium": "low", "low": "low"}
_TREND_MONTHS = 6


@router.get("/dashboard")
def get_dashboard(user=Depends(require_login), db: Session = Depends(get_db)) -> dict:
    """工作台聚合数据(#280): 指标卡 + 步骤耗时 + 需求优先级月度趋势 + 最近评估。

    全部按当前用户数据权限过滤(pm 仅本人项目); 统计口径:
    评估中=草稿, 已完成=已生成基线; 趋势按评估创建月份聚合计数。
    """
    from models import SecurityRequirement, System

    projects = visible_projects_query(db, user).all()
    eval_active = sum(1 for p in projects if p.status == "draft")
    eval_done = len(projects) - eval_active
    system_names = {
        s.id: s.name
        for s in db.query(System).filter(
            System.id.in_({p.system_id for p in projects if p.system_id} or {0})).all()
    }

    # 近 N 个月需求优先级趋势: (评估创建月, 优先级) 计数, 数据量级小, Python 聚合即可
    months: list[str] = []
    cursor = _current_month()
    for _ in range(_TREND_MONTHS):
        months.append(cursor[:7])
        cursor = _prev_month(cursor)
    months.reverse()  # 图表横轴从旧到新
    month_index = {m: i for i, m in enumerate(months)}
    trend = [{"month": m, "high": 0, "mid": 0, "low": 0} for m in months]
    project_ids = [p.id for p in projects]
    if project_ids:
        rows = db.query(SecurityRequirement.project_id, SecurityRequirement.priority).filter(
            SecurityRequirement.project_id.in_(project_ids)).all()
        created_at_by_id = {p.id: p.created_at for p in projects}
        for project_id, priority in rows:
            created = created_at_by_id.get(project_id)
            if created is None:
                continue
            idx = month_index.get(created.strftime("%Y-%m"))
            if idx is not None:
                trend[idx][_DASHBOARD_TREND_BUCKETS.get(priority, "low")] += 1

    # 步骤耗时按可见项目过滤(#330), pm 不再看到全平台/他人轮次的耗时
    report = step_metrics_report(db, project_ids=project_ids)
    recent = [
        {
            "id": p.id,
            "code": p.code,
            "name": p.name,
            "system_name": system_names.get(p.system_id),
            "status": p.status,
            "grading_level": (p.survey.effective_level() if p.survey else None),
            "created_at": p.created_at.strftime("%Y-%m-%d %H:%M") if p.created_at else None,
        }
        for p in projects[:8]
    ]
    from services.system_service import visible_systems_query

    return {
        "system_count": visible_systems_query(db, user).count(),
        "eval_total": len(projects),
        "eval_active": eval_active,
        "eval_done": eval_done,
        "avg_minutes": round(report["total_avg_seconds"] / 60, 1),
        "step_minutes": [
            {"step": s["label"], "min": round(s["avg_seconds"] / 60, 1)}
            for s in report["steps"]
        ],
        "req_trend": trend,
        "recent": recent,
    }


def _current_month() -> str:
    from datetime import date
    return date.today().strftime("%Y-%m")


def _prev_month(month: str) -> str:
    """'2026-09' → '2026-08'; 跨年回退到上一年 12 月。"""
    year, mon = int(month[:4]), int(month[5:7])
    return f"{year - 1}-12" if mon == 1 else f"{year}-{mon - 1:02d}"
