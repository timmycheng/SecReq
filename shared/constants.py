# -*- coding: utf-8 -*-
"""前后端共享枚举常量。

约束(DESIGN.md 第七节): 所有枚举前后端共享一份常量定义。
前端 shared/constants.ts 与本文件人工保持同步, 后续可由 YAML 统一生成。
数据库存 code, 展示层取 label。
"""

# ── 项目 ─────────────────────────────────────────────
PROJECT_TYPES = {
    "web": "Web系统",
    "mobile_app": "手机APP",
    "api_service": "API服务",
    "desktop": "桌面客户端",
    "mini_program": "小程序",
}

USER_SCALES = {
    "under_1k": "<1千",
    "1k_to_100k": "1千-10万",
    "100k_to_1m": "10万-100万",
    "over_1m": ">100万",
}

DEPLOY_ENVS = {
    "private_cloud": "行内私有云",
    "hosted_cloud": "托管云",
    "saas": "外采SaaS",
}

PROJECT_STATUS = {
    "draft": "草稿",
    "generated": "已生成基线",
    "archived": "已归档",
}

# 等保定级(存中文标签, 知识库条件直接匹配)
GRADING_LEVELS = ["一级", "二级", "三级"]

# ── Step3 功能清单 ────────────────────────────────────
FEATURE_CATEGORIES = {
    "auth_login": "登录认证",
    "password_mgmt": "密码管理",
    "file_upload": "文件上传",
    "file_download": "文件下载",
    "payment": "支付交易",
    "refund": "退款",
    "order": "订单管理",
    "export_data": "数据导出",
    "message_push": "消息推送",
    "comment_ugc": "评论/UGC",
    "api_open": "开放API",
    "admin_console": "管理后台",
    "third_auth": "第三方登录",
    "ai_feature": "AI功能",
    "audit_log": "审计日志",
    "search": "搜索",
    "sms_email": "短信/邮件",
}

SENSITIVITY_LEVELS = {
    "public": "公开",
    "internal": "内部",
    "sensitive": "敏感",
    "confidential": "机密",
}

# ── Step4 数据字典 ────────────────────────────────────
DATA_ASSET_TYPES = {
    "basic_personal_info": "个人基本信息",
    "identity_info": "身份信息",
    "financial_account": "金融账户",
    "biometric": "生物识别",
    "health_medical": "健康医疗",
    "location_trace": "位置轨迹",
    "behavior_log": "行为日志",
    "business_data": "业务数据",
}

# 数据资产分类分级(知识库 data_asset 条件按此中文值匹配)
DATA_CLASSIFICATIONS = ["公开", "内部", "敏感", "机密"]

# 资产存储位置(用于 has_log_leakage_risk 判定)
STORAGE_ENVS = {
    "db": "数据库",
    "cache": "缓存",
    "log": "日志",
    "file": "文件存储",
    "object_storage": "对象存储",
    "mq": "消息队列",
}

# 需脱敏字段类型 → 字段名匹配正则(规则引擎 data_asset.mask_fields_any_of 使用)
MASK_FIELD_PATTERNS = {
    "phone_number": r"(手机|电话|mobile|phone)",
    "id_card": r"(身份证|证件|identity|id_?card)",
    "bank_card": r"(卡号|bank_?card|card_?num|账号)",
    "email": r"(邮箱|email)",
    "name": r"(姓名|^name$|customer_?name|user_?name$)",
}

MASK_RULES = {
    "phone_number": "保留前3后4, 中间****",
    "id_card": "保留前6后4, 其余*",
    "bank_card": "仅展示后4位",
    "email": "@前保留首字符",
    "name": "姓氏保留, 名用*替代",
}

# ── Step5 权限矩阵 ────────────────────────────────────
ROLE_TYPES = {
    "normal": "普通角色",
    "privileged": "特权角色",
    "super_admin": "超级管理员",
}

RESOURCE_TYPES = {
    "data_record": "业务数据记录",
    "api_endpoint": "API接口",
    "page_menu": "页面菜单",
    "system_config": "系统配置",
}

CRITICALITY_LEVELS = {
    "low": "低",
    "medium": "中",
    "high": "高",
    "critical": "关键",
}

PERMISSION_ACTIONS = {
    "create": "创建",
    "read": "读取",
    "update": "修改",
    "delete": "删除",
    "export": "导出",
    "approve": "审批",
    "config_change": "配置变更",
}

# 高危操作: 关键资源执行这些操作必须挂审批流(权限矩阵扫描算法1)
HIGH_RISK_ACTIONS = ["delete", "export", "approve", "config_change"]

# 职责分离(SoD)互斥操作对: 同一角色在同一 high/critical 资源上不可兼得(扫描算法2)
SOD_CONFLICT_PAIRS = [
    ("create", "approve"),
    ("update", "approve"),
    ("config_change", "approve"),
]

# ── Step6 认证与密码策略 ──────────────────────────────
AUTH_METHODS = {
    "password": "账密登录",
    "sms_otp": "短信验证码",
    "dynamic_otp": "OTP动态口令",
    "third_oauth": "第三方OAuth",
    "sso": "行内SSO",
    "biometric": "生物识别",
}

# 按等保定级推导的默认密码基线(Step6 密码策略设计器默认值)
DEFAULT_PWD_POLICY_BY_LEVEL = {
    "三级": {"pwd_min_length": 10, "pwd_complexity": 4, "pwd_valid_days": 60},
    "二级": {"pwd_min_length": 8, "pwd_complexity": 3, "pwd_valid_days": 90},
    "一级": {"pwd_min_length": 8, "pwd_complexity": 3, "pwd_valid_days": 180},
}
DEFAULT_LOCKOUT_THRESHOLD = 5
DEFAULT_SESSION_TIMEOUT_MIN = 15

# ── Step7 SBOM ────────────────────────────────────────
SBOM_LAYERS = {
    "frontend": "前端",
    "backend": "后端",
    "database": "数据库",
    "middleware": "中间件",
    "library": "三方库",
    "infra": "基础设施",
}

SBOM_SOURCE_TYPES = {
    "manual_input": "手工录入",
    "sbom_file": "SBOM文件导入",
}

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "unknown": 9}
SEVERITY_LABELS = {
    "critical": "严重",
    "high": "高危",
    "medium": "中危",
    "low": "低危",
}

# ── Step8 接口与资产 ──────────────────────────────────
HTTP_METHODS = ["GET", "POST", "PUT", "DELETE", "PATCH"]
INFRA_ASSET_TYPES = {
    "server": "服务器",
    "database": "数据库实例",
    "middleware": "中间件",
}
ENV_NAMES = {"dev": "开发", "test": "测试", "prod": "生产"}

# ── 合规目标(compliance 触发器 target 取值) ───────────
COMPLIANCE_TARGETS = {
    "djcp_l3": "网络安全等级保护三级",
    "pipl": "个人信息保护法",
    "pci_dss": "PCI-DSS银行卡安全",
}

# ── 安全需求 ──────────────────────────────────────────
REQUIREMENT_PRIORITY_LABELS = {
    "critical": "紧急",
    "high": "高",
    "medium": "中",
    "low": "低",
}
REQUIREMENT_PHASES = {
    "design": "设计阶段",
    "development": "开发阶段",
    "test": "测试阶段",
}
REQUIREMENT_STATUS = {
    "open": "待处理",
    "in_progress": "处理中",
    "done": "已完成",
    "risk_accepted": "风险接受",
}

# 需求业务归类(trigger.type → 中文类目), 用于文档分组与筛选
TRIGGER_CATEGORY_LABELS = {
    "feature_category": "功能安全",
    "permission_rule": "权限与访问控制",
    "auth_method": "认证与会话",
    "policy_baseline": "口令与会话策略",
    "data_asset": "数据安全",
    "api_endpoint": "接口安全",
    "compliance": "合规要求",
    "vulnerability": "第三方组件风险",
}


def label(mapping: dict, code, default="") -> str:
    """按映射字典取中文标签, 未注册的 code 原样返回。"""
    return mapping.get(code, code if isinstance(code, str) and code else default)
