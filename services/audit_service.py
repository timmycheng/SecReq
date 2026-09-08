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
    "infra_envs_update": "更新基础资源环境配置",
    "system_dicts_update": "更新系统字典",
    "user_create": "创建用户",
    "user_update": "更新用户",
    "user_reset_password": "重置用户密码",
    "user_toggle": "启停用户",
    "vulndb_verify": "漏洞库校验",
    "ldap_update": "更新 LDAP 配置",
    "ldap_sync": "LDAP 用户导入",
    "netbox_update": "更新 NetBox 配置",
    "netbox_sync": "触发 NetBox 同步",
    "filing_create": "登记备案",
    "filing_update": "更新备案",
    "filing_delete": "删除备案",
    "filing_import": "批量导入备案",
    "system_create": "登记系统",
    "system_update": "更新系统",
    "system_delete": "删除系统",
    "system_infra_save": "保存系统基础设施",
    "system_components_save": "保存系统组件清单",
    "system_arch_image": "上传系统架构图",
    "system_arch_image_delete": "删除系统架构图",
    "baseline_level_confirm": "确认级别变更",
    "baseline_writeback_failed": "基线写回失败",
    "project_copy_from": "整卷复制评估",
    "project_reset_wizard": "清空向导输入",
    "project_withdraw": "撤回评审",
    "review_submit": "提交评审",
    "review_submit_blocked": "提交评审未过门禁",
    "review_annotate": "需求批注",
    "review_decide": "评审裁定",
    "review_finalize": "评审终审",
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
    if action == "ldap_sync":
        return f"导入目录用户: 总数 {get('total')}, 新增 {get('created')}, 跳过 {get('skipped')}"
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
    if action == "infra_envs_update":
        return f"基础资源环境更新为 {get('count')} 个: {get('codes')}"
    if action == "system_dicts_update":
        return f"系统字典更新: 标签 {get('tags')} 个, 系统类型 {get('types')} 个"
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
    if action in ("filing_create", "filing_update"):
        return f"{ACTION_LABELS[action]} {get('name')}({get('level')})"
    if action == "filing_delete":
        return f"删除备案 {get('name')}"
    if action == "filing_import":
        return f"批量导入备案: 新增 {get('created')} 条, 跳过 {get('skipped')} 条"
    if action in ("system_create", "system_update"):
        return f"{ACTION_LABELS[action]} {get('name')}"
    if action == "system_delete":
        return f"删除系统 {get('name')}"
    if action in ("system_infra_save", "system_components_save"):
        what = "基础设施" if action == "system_infra_save" else "组件清单"
        return f"系统 #{get('system_id')} 保存{what}, 共 {get('count')} 条"
    if action in ("system_arch_image", "system_arch_image_delete"):
        env = C.ENV_NAMES.get(get("env"), get("env"))
        verb = "上传" if action == "system_arch_image" else "删除"
        return f"系统 #{get('system_id')} {verb}{env}架构图"
    if action == "baseline_level_confirm":
        verdict = ("采纳评估建议级" if get("decision") == "adopt_suggested"
                   else "维持备案定级")
        return f"系统 #{get('system_id')} 级别变更确认: {verdict}"
    if action == "baseline_writeback_failed":
        return f"项目 #{get('project_id')} 基线写回失败: {get('error')}"
    if action == "netbox_update":
        return f"NetBox 配置: {get('base_url')}({get('system_slug')})"
    if action == "netbox_sync":
        return f"NetBox 同步({get('trigger')}): {get('status')}, 日志 #{get('log_id')}"
    if action == "user_update":
        return f"更新用户 {get('target')}({C.label(C.PLATFORM_ROLES, str(get('role')))})"
    if action == "project_copy_from":
        return f"项目 #{get('project_id')} 自项目 #{get('copied_from')} 整卷复制向导数据"
    if action == "project_reset_wizard":
        return f"项目 #{get('project_id')} 清空全部向导输入"
    if action == "project_withdraw":
        return f"项目 #{get('project_id')} 撤回评审, 回到填写阶段(数据保留)"
    if action == "review_submit":
        return f"项目 #{get('project_id')} 提交评审(门禁 #{get('gate_id')})"
    if action == "review_submit_blocked":
        missing = get("missing") or []
        return f"项目 #{get('project_id')} 提交评审被门禁拦截, 缺 {len(missing)} 项"
    if action == "review_annotate":
        disposition = {"approve": "通过", "return": "退回整改", "object": "异议留痕"}.get(
            str(get("disposition")), str(get("disposition")))
        return f"项目 #{get('project_id')} 需求 {get('req_id')} 批注: {disposition}"
    if action == "review_decide":
        conclusion = {"approve": "通过, 待终审", "request_change": "退回整改",
                      "reject": "否决"}.get(str(get("conclusion")), str(get("conclusion")))
        return f"项目 #{get('project_id')} 评审裁定: {conclusion}"
    if action == "review_finalize":
        verdict = "终审通过" if get("gate_status") == "passed" else "终审未通过"
        return f"项目 #{get('project_id')} {verdict}"
    return None
