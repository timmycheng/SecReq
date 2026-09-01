# -*- coding: utf-8 -*-
"""审计日志服务: 敏感动作统一留痕(登录/生成/确认/知识库与用户管理变更)。

展示侧(动作中文化与明细摘要)也统一定义在本模块、由后端下发,
前端不自映射 —— 避免重蹈 #41(VulnDbTab SOURCE_LABELS 前端硬编码)的约定偏离。
"""
import shared.constants as C
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


# ── 展示侧: 动作标签与明细摘要(#65) ───────────────────

#: action code → 中文标签; 未识别的 code 由 action_label() 回退原文, 兼容存量日志
ACTION_LABELS: dict[str, str] = {
    "login": "登录",
    "login_failed": "登录失败",
    "project_create": "创建项目",
    "project_delete": "删除项目",
    "step_save": "保存向导步骤",
    "generate": "生成审查材料",
    "confirm": "确认需求",
    "confirm_batch": "批量确认需求",
    "export": "导出材料",
    "kb_create": "新建知识库模板",
    "kb_update": "更新知识库模板",
    "questions_update": "更新定级题库",
    "policy_update": "更新策略基线",
    "llm_update": "更新大模型配置",
    "code_rule_update": "更新编号规则",
    "user_create": "创建用户",
    "user_reset_password": "重置用户密码",
    "user_toggle": "启停用户",
    "vulndb_verify": "漏洞库校验",
}

#: step_save 的 step 值 → 中文名(与 routers/steps.py 的调用点对应)
_STEP_NAMES: dict[str, str] = {
    "external_systems": "外部系统",
    "features": "功能清单",
    "data_assets": "数据资产",
    "permission_matrix": "权限矩阵",
    "auth_config": "认证配置",
    "components": "组件清单",
    "sbom_import": "SBOM 导入",
    "api_endpoints": "API 接口",
    "infra_assets": "基础设施",
}


def action_label(action: str) -> str:
    """动作中文标签; 未识别的 action 回退原始 code。"""
    return ACTION_LABELS.get(action, action)


def summarize_detail(action: str, detail: dict) -> str | None:
    """按动作类型把明细渲染成人类可读的一句话; 无法识别返回 None(前端回退原文)。"""
    def get(key: str):
        return detail.get(key)

    if action == "project_create":
        return f"创建项目 {get('name')}({get('code')})"
    if action == "project_delete":
        return f"删除项目 {get('name')}({get('code')})"
    if action == "step_save":
        step = _STEP_NAMES.get(str(get("step")), str(get("step") or "未知步骤"))
        return f"项目 #{get('project_id')} 保存{step}, 共 {get('count')} 条"
    if action == "generate":
        return f"项目 #{get('project_id')} 生成需求 {get('requirements')} 条"
    if action == "confirm":
        return f"项目 #{get('project_id')} 确认需求 {get('req_id')}"
    if action == "confirm_batch":
        return f"项目 #{get('project_id')} 批量确认 {get('count')} 条需求"
    if action == "export":
        return f"项目 {get('code')}(#{get('project_id')})导出 {get('format')} 格式 {get('count')} 条"
    if action == "kb_create":
        return f"新建知识库模板 {get('template_id')}"
    if action == "kb_update":
        return f"更新知识库模板 {get('template_id')}"
    if action == "policy_update":
        return f"更新策略基线, 共 {len(detail)} 项配置"
    if action == "llm_update":
        return f"大模型配置: {get('model')} @ {get('base_url')}"
    if action == "code_rule_update":
        return f"项目编号前缀更新为 {get('prefix')}"
    if action == "user_create":
        return f"创建用户 {get('target')}({C.label(C.PLATFORM_ROLES, str(get('role')))})"
    if action == "user_reset_password":
        return f"重置用户 {get('target')} 的密码"
    if action == "user_toggle":
        return f"{'启用' if get('active') else '停用'}用户 {get('target')}"
    if action == "vulndb_verify":
        match = get("match")
        verdict = "校验通过" if match else ("校验失败" if match is not None else "无基准可比对")
        return f"漏洞库完整性{verdict}, {get('size_mb')} MB"
    return None
