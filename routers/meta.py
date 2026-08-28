# -*- coding: utf-8 -*-
"""元数据路由: 前后端共享枚举的唯一来源(DESIGN.md 约束第七节)。

前端不硬编码任何枚举选项与中文标签, 启动时从 /api/meta/constants 拉取;
密码策略默认基线、定级问卷题库同样由本路由供数。
"""
from fastapi import APIRouter

import shared.constants as C
from services.grading import load_questions

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
def get_constants() -> dict:
    """全部枚举(code→label 映射 + 数组型常量)。"""
    payload: dict = {key: dict(value) for key, value in _ENUMS.items()}
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
            "default_pwd_policy_by_level": C.DEFAULT_PWD_POLICY_BY_LEVEL,
            "default_lockout_threshold": C.DEFAULT_LOCKOUT_THRESHOLD,
            "default_session_timeout_min": C.DEFAULT_SESSION_TIMEOUT_MIN,
            "severity_labels": C.SEVERITY_LABELS,
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
