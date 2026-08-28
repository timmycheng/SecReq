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

# ── 数据分级(JR/T 0197-2020 五级体系, 改造点1) ─────────
# 数据库 classification 直接存下列 code; 知识库 data_asset 条件按 code 匹配。
# 顺序: 高 → 低。
DATA_LEVELS = [
    "5级_重要数据",
    "4级_C3鉴别信息",
    "3级_C2主要信息",
    "2级_C1次要信息",
    "1级_公开数据",
]

# code → 数值等级(5 最高), 供 min_level 条件与门禁校验使用
DATA_LEVEL_ORDER = {code: 5 - i for i, code in enumerate(DATA_LEVELS)}

# code → 展示名 + 典型数据举例(节选自 JR/T 0197-2020 附录A, 辅助项目经理选择)
DATA_LEVEL_META = {
    "5级_重要数据": {
        "label": "5级(重要数据)",
        "examples": "影响国家安全或公众权益严重损害的数据, 如: 全行业集中的重要统计数据、"
                    "达标认定的重要业务系统运行数据、涉及国家安全的金融基础设施数据。",
    },
    "4级_C3鉴别信息": {
        "label": "4级(C3鉴别信息)",
        "examples": "账户鉴别信息, 如: 登录口令/支付密码、银行卡磁道与CVN2、指纹/人脸等"
                    "生物特征模板、数字证书私钥。",
    },
    "3级_C2主要信息": {
        "label": "3级(C2主要信息)",
        "examples": "账户信息与个人身份信息, 如: 银行账号、开户户名、身份证号、手机号、"
                    "KYC 资料、住址、交易流水。",
    },
    "2级_C1次要信息": {
        "label": "2级(C1次要信息)",
        "examples": "开放时间、开户时间、内部办公数据、网点信息、产品参数等次敏感信息。",
    },
    "1级_公开数据": {
        "label": "1级(公开数据)",
        "examples": "对外公开发布的信息, 如: 官网产品介绍、公告、已公示的利率表。",
    },
}

# 老 4 级 → 新 5 级迁移映射(改造点1; 配套 scripts/migrate_classification.py)
LEGACY_CLASSIFICATION_MAP = {
    "公开": "1级_公开数据",
    "内部": "2级_C1次要信息",
    "敏感": "3级_C2主要信息",
    "机密": "4级_C3鉴别信息",
}

# C3 标签: 4级及以上且属于鉴别信息(生物识别类等), 驱动传输/缓存/日志三条专属规则
C3_TAG_RULE_NOTE = "传输/展示环节禁止明文、禁止缓存(含前端CDN)、日志禁记"


def level_rank(classification: str | None) -> int:
    """分级 code → 数值等级; 老 4 级值按迁移映射折算; 未登记返回 0。"""
    if not classification:
        return 0
    if classification in DATA_LEVEL_ORDER:
        return DATA_LEVEL_ORDER[classification]
    legacy = LEGACY_CLASSIFICATION_MAP.get(classification)
    return DATA_LEVEL_ORDER.get(legacy, 0)


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
    "network": "网络设备",
    "database": "数据库实例",
    "middleware": "中间件",
}
ENV_NAMES = {"dev": "开发", "test": "测试", "prod": "生产"}

# ── 外部系统连接(Step1 采集) ───────────────────────────
EXTERNAL_SYSTEM_DIRECTIONS = {
    "inbound": "外部调用本系统",
    "outbound": "本系统调用外部",
    "bidirectional": "双向交互",
}

# ── 常用组件目录(按层级分组, 含默认许可证) ──────────────
COMMON_COMPONENTS: dict[str, list[dict]] = {
    "frontend": [
        {"name": "Vue", "license": "MIT"}, {"name": "React", "license": "MIT"},
        {"name": "Angular", "license": "MIT"}, {"name": "Element", "license": "MIT"},
        {"name": "AntDesign", "license": "MIT"}, {"name": "lodash", "license": "MIT"},
        {"name": "axios", "license": "MIT"}, {"name": "Ionic", "license": "MIT"},
        {"name": "jwt", "license": "MIT"},
    ],
    "backend": [
        {"name": "Spring Boot", "license": "Apache-2.0"}, {"name": "Spring Security", "license": "Apache-2.0"},
        {"name": "Django", "license": "BSD-3-Clause"}, {"name": "Flask", "license": "BSD-3-Clause"},
        {"name": "okhttp", "license": "Apache-2.0"}, {"name": "Retrofit", "license": "Apache-2.0"},
        {"name": "Struts2", "license": "Apache-2.0"}, {"name": "netty", "license": "Apache-2.0"},
        {"name": "dubbo", "license": "Apache-2.0"},
    ],
    "database": [
        {"name": "MySQL", "license": "GPL-2.0"}, {"name": "PostgreSQL", "license": "PostgreSQL"},
        {"name": "MongoDB", "license": "SSPL-1.0"}, {"name": "Oracle", "license": "商业授权"},
        {"name": "Redis", "license": "RSAL-2.0"},
    ],
    "middleware": [
        {"name": "Nginx", "license": "BSD-2-Clause"}, {"name": "kafka", "license": "Apache-2.0"},
        {"name": "RabbitMQ", "license": "MPL-2.0"}, {"name": "Elasticsearch", "license": "SSPL-1.0"},
        {"name": "tomcat", "license": "Apache-2.0"}, {"name": "kubernetes", "license": "Apache-2.0"},
        {"name": "Docker", "license": "Apache-2.0"}, {"name": "OpenSSL", "license": "Apache-2.0"},
    ],
    "library": [
        {"name": "log4j", "license": "Apache-2.0"}, {"name": "log4j-core", "license": "Apache-2.0"},
        {"name": "fastjson", "license": "Apache-2.0"}, {"name": "jackson", "license": "Apache-2.0"},
        {"name": "gson", "license": "Apache-2.0"}, {"name": "mybatis", "license": "Apache-2.0"},
        {"name": "Druid", "license": "Apache-2.0"}, {"name": "Shiro", "license": "Apache-2.0"},
        {"name": "XStream", "license": "BSD-3-Clause"}, {"name": "dom4j", "license": "BSD-3-Clause"},
        {"name": "poi", "license": "Apache-2.0"}, {"name": "itextpdf", "license": "AGPL-3.0"},
        {"name": "requests", "license": "Apache-2.0"},
    ],
    "infra": [
        {"name": "ImageMagick", "license": "ImageMagick"}, {"name": "FFmpeg", "license": "LGPL-2.1"},
        {"name": "zlib", "license": "Zlib"}, {"name": "libcurl", "license": "curl"},
        {"name": "Helm", "license": "Apache-2.0"},
    ],
}

# 许可证风险库: 使用类 GPL 强传染许可证为高风险(需安全/法务评估)
LICENSE_RISK: dict[str, dict] = {
    "GPL-2.0": {"risk": "high", "label": "强传染 Copyleft", "note": "GPL 系列具有传染性, 组件以链接方式集成可能要求整体开源, 须安全与法务联合评估"},
    "GPL-3.0": {"risk": "high", "label": "强传染 Copyleft", "note": "GPL 系列具有传染性, 商用闭源系统集成需法务评估"},
    "AGPL-3.0": {"risk": "high", "label": "网络传染 Copyleft", "note": "AGPL 连网络调用也触发开源义务, 风险最高, 建议替换或隔离部署"},
    "SSPL-1.0": {"risk": "high", "label": "非开源许可", "note": "SSPL 非 OSI 认可开源许可证, 提供服务场景需商业授权"},
    "RSAL-2.0": {"risk": "high", "label": "非开源许可", "note": "限制性源码可用许可, 商用分发需商业授权"},
    "LGPL-2.1": {"risk": "medium", "label": "弱传染 Copyleft", "note": "动态链接可隔离, 修改库本身需开源, 建议以独立进程/动态链接方式集成"},
    "MPL-2.0": {"risk": "medium", "label": "文件级 Copyleft", "note": "修改 MPL 文件需开源该文件, 需评审修改范围"},
    "EPL-2.0": {"risk": "medium", "label": "弱传染 Copyleft", "note": "修改需声明, 商用基本可控, 保留版权声明"},
    "ImageMagick": {"risk": "medium", "label": "类 BSD 附加条款", "note": "含附加条款, 商用前评审声明要求"},
    "商业授权": {"risk": "medium", "label": "商业许可", "note": "须确认采购授权范围与部署数量限制"},
    "curl": {"risk": "low", "label": "宽松", "note": "MIT 类衍生许可, 保留版权声明即可"},
    "Zlib": {"risk": "low", "label": "宽松", "note": "保留版权声明即可"},
    "PostgreSQL": {"risk": "low", "label": "宽松", "note": "类 BSD 宽松许可"},
    "BSD-2-Clause": {"risk": "low", "label": "宽松", "note": "保留版权声明即可"},
    "BSD-3-Clause": {"risk": "low", "label": "宽松", "note": "保留版权声明即可"},
    "MIT": {"risk": "low", "label": "宽松", "note": "保留版权声明即可"},
    "Apache-2.0": {"risk": "low", "label": "宽松", "note": "保留版权与 NOTICE 声明即可"},
}
LICENSE_RISK_ORDER = {"high": 3, "medium": 2, "low": 1}

# ── 合规目标(compliance 触发器 target 取值) ───────────
COMPLIANCE_TARGETS = {
    "djcp_l3": "等级保护",
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

# 来源实体类型 → 中文(需求溯源展示, 替代 data_asset#3 这类英文串)
SOURCE_TYPE_LABELS = {
    "feature": "功能",
    "permission_entry": "权限授权",
    "role": "角色",
    "permission_matrix": "权限矩阵",
    "auth_config": "认证与密码策略",
    "policy_baseline": "定级策略基线",
    "data_asset": "数据资产",
    "api_endpoint": "API接口",
    "compliance_target": "合规目标",
    "sbom_component": "第三方组件",
    "project": "项目整体",
    "external_system": "外部系统",
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
    "regulatory_trigger": "监管报送",
    "external_system": "外部系统交互",
    "license_risk": "开源许可证风险",
}

# ── 平台角色与数据权限 ─────────────────────────────────
# 走查整改: 角色精简为 开发/安全 两类(不再区分审计/风管/评审员/负责人)。
PLATFORM_ROLES = {
    "developer": "开发",
    "security": "安全",
}

# 数据权限口径: 开发只能看到/操作自己创建的项目, 安全可以看到/操作全部。
ALL_PLATFORM_ROLES = list(PLATFORM_ROLES.keys())
WRITE_WIZARD_ROLES = ["developer", "security"]


def label(mapping: dict, code, default="") -> str:
    """按映射字典取中文标签, 未注册的 code 原样返回。"""
    return mapping.get(code, code if isinstance(code, str) and code else default)
