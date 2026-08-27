# -*- coding: utf-8 -*-
"""种子数据: 演示项目「个人网银系统」。

对应 DESIGN.md 交付物第2条:
12功能 / 6数据资产 / 5角色×8资源权限矩阵(含故意构造的审批缺失与SoD冲突) /
10技术栈组件(故意包含 log4j 2.14.1 用于第二批漏洞演示) / 4 API接口。
"""
from sqlalchemy.orm import Session

import shared.constants as C
from models import (
    ApiEndpoint, AuthConfig, DataAsset, DataField, DataTable, Feature,
    GradingSurvey, InfraAsset, PermissionEntry, Project, Resource, Role,
    SbomComponent,
)

DEMO_PROJECT_CODE = "PRJ-IBANK-2026"


def seed_demo_project(session: Session, overwrite: bool = True) -> Project:
    """写入演示项目全部输入数据, 返回 Project。重复执行默认先清旧数据。"""
    existing = session.query(Project).filter_by(code=DEMO_PROJECT_CODE).first()
    if existing is not None:
        if not overwrite:
            return existing
        _delete_project(session, existing)

    project = Project(
        name="个人网银系统",
        code=DEMO_PROJECT_CODE,
        type="web",
        industry="零售金融-个人业务条线",
        user_scale="over_1m",
        deploy_env=["private_cloud"],
        is_public=True,
        pm_name="张明",
        dev_lead_name="李强",
        sec_contact_name="王安全",
        compliance_targets=["djcp_l3", "pipl", "pci_dss"],
        status="draft",
    )
    session.add(project)
    session.flush()  # 取得 project.id 供下游外键使用

    # ── Step2 定级问卷 ────────────────────────────────────
    session.add(
        GradingSurvey(
            project_id=project.id,
            answers_json=[
                {"question_id": "Q1", "answer": "处理公民个人信息且含敏感个人信息(金融账户/身份信息)"},
                {"question_id": "Q2", "answer": "涉及资金交易"},
                {"question_id": "Q3", "answer": "服务对象为社会公众"},
                {"question_id": "Q4", "answer": "破坏后全行业务受影响"},
                {"question_id": "Q5", "answer": "是渠道类系统的依赖底座之一"},
            ],
            suggested_level="三级",
            suggested_reason=(
                "处理敏感个人信息并涉及资金交易, 服务社会公众, 受破坏后影响全行重点业务, "
                "依据行内定级指引判定为等保三级。"
            ),
            final_level=None,  # 未人工修正, 引擎取建议定级
        )
    )

    # ── Step3 功能清单(12条) ──────────────────────────────
    features = [
        ("账户登录认证", "统一认证模块", ["auth_login"], False, True),
        ("密码修改与找回", "统一认证模块", ["password_mgmt", "sms_email"], False, True),
        ("转账汇款", "支付模块", ["payment"], True, True),
        ("交易撤销与退款", "支付模块", ["refund", "payment"], True, False),
        ("交易明细导出", "账务查询模块", ["export_data"], False, False),
        ("客户头像上传", "客户中心", ["file_upload"], False, True),
        ("对账文件下载", "账务查询模块", ["file_download"], False, False),
        ("微信授权登录", "统一认证模块", ["third_auth"], False, True),
        ("短信验证码服务", "公共支撑", ["sms_email"], False, True),
        ("站内消息推送", "公共支撑", ["message_push"], False, False),
        ("理财产品搜索与讨论", "财富模块", ["search", "comment_ugc"], False, True),
        ("运营管理后台", "运营支撑", ["admin_console", "audit_log"], False, False),
    ]
    for name, module, cats, involves_pay, exposed in features:
        session.add(
            Feature(
                project_id=project.id,
                name=name,
                module=module,
                categories=cats,
                sensitivity="confidential" if involves_pay else "internal",
                involves_payment=involves_pay,
                exposed_to_internet=exposed,
            )
        )

    # ── Step4 数据字典: 资产 → 表 → 字段(6资产) ───────────
    def add_asset(name, dtype, classification, pii, s_pii, envs, cross_border, tables):
        asset = DataAsset(
            project_id=project.id, name=name, data_type=dtype,
            classification=classification, is_pii=pii, is_sensitive_pii=s_pii,
            storage_envs=envs, cross_border_transfer=cross_border,
        )
        session.add(asset)
        session.flush()
        for table_name, fields in tables:
            table = DataTable(asset_id=asset.id, table_name=table_name)
            session.add(table)
            session.flush()
            for f_name, f_type, enc, mask in fields:
                mask_rule = C.label(C.MASK_RULES, mask) if mask else None
                session.add(
                    DataField(
                        table_id=table.id, field_name=f_name, field_type=f_type,
                        need_encrypt=enc, need_mask=bool(mask), mask_rule=mask_rule,
                    )
                )
        return asset

    add_asset(
        "银行账户信息", "financial_account", "机密", True, True, ["db"],
        False,
        [("t_bank_account", [
            ("card_number", "varchar(32)", True, "bank_card"),
            ("account_balance", "decimal(18,2)", False, None),
            ("withdraw_password_hash", "varchar(128)", True, None),
        ])],
    )
    add_asset(
        "公民身份信息", "identity_info", "机密", True, True, ["db", "object_storage"],
        False,
        [("t_customer_identity", [
            ("id_card_number", "varchar(18)", True, "id_card"),
            ("real_name", "varchar(64)", False, "name"),
            ("nationality", "varchar(20)", False, None),
        ])],
    )
    add_asset(
        "指纹生物特征", "biometric", "机密", True, True, ["db"],
        False,
        [("t_biometric_template", [
            ("fingerprint_feature", "blob", True, None),
            ("liveness_seed", "varchar(64)", True, None),
        ])],
    )
    add_asset(
        "客户联系方式", "basic_personal_info", "内部", True, False, ["db", "cache"],
        False,
        [("t_customer_contact", [
            ("mobile_number", "varchar(16)", False, "phone_number"),
            ("email_address", "varchar(128)", False, "email"),
        ])],
    )
    add_asset(
        "客户行为日志", "behavior_log", "内部", False, False, ["db", "log"],
        False,
        [("t_behavior_log", [
            ("device_id", "varchar(64)", False, None),
            ("page_path", "varchar(200)", False, None),
        ])],
    )
    add_asset(
        "跨境营销统计报表", "business_data", "敏感", False, False, ["object_storage"],
        True,
        [("t_marketing_oversea_report", [
            ("country_code", "varchar(8)", False, None),
            ("conversion_rate", "decimal(8,4)", False, None),
        ])],
    )

    # ── Step5 权限矩阵(5角色 × 8资源) ─────────────────────
    roles = {
        "超级管理员": Role(project_id=project.id, name="超级管理员", role_type="super_admin", user_count_estimate=2),
        "运营管理员": Role(project_id=project.id, name="运营管理员", role_type="privileged", user_count_estimate=5),
        "风控复核员": Role(project_id=project.id, name="风控复核员", role_type="privileged", user_count_estimate=8),
        "客服专员": Role(project_id=project.id, name="客服专员", role_type="normal", user_count_estimate=30),
        "审计员": Role(project_id=project.id, name="审计员", role_type="normal", user_count_estimate=3),
    }
    session.add_all(roles.values())

    resources = {
        "银行账户信息记录": Resource(project_id=project.id, name="银行账户信息记录", resource_type="data_record", criticality="critical"),
        "交易流水记录": Resource(project_id=project.id, name="交易流水记录", resource_type="data_record", criticality="critical"),
        "系统参数配置": Resource(project_id=project.id, name="系统参数配置", resource_type="system_config", criticality="critical"),
        "系统用户管理菜单": Resource(project_id=project.id, name="系统用户管理菜单", resource_type="page_menu", criticality="critical"),
        "营销活动配置": Resource(project_id=project.id, name="营销活动配置", resource_type="system_config", criticality="medium"),
        "审计日志归档": Resource(project_id=project.id, name="审计日志归档", resource_type="data_record", criticality="high"),
        "开放接口配置": Resource(project_id=project.id, name="开放接口配置", resource_type="api_endpoint", criticality="high"),
        "客服工作台页面": Resource(project_id=project.id, name="客服工作台页面", resource_type="page_menu", criticality="low"),
    }
    session.add_all(resources.values())
    session.flush()
    role_of = {r.name: r.id for r in roles.values()}
    res_of = {r.name: r.id for r in resources.values()}

    # (角色, 资源, [操作...]) 操作格式为 code 或 (code, requires_approval)
    matrix = [
        # 故意违规①②③: 超级管理员关键资源高危操作免审批
        ("超级管理员", "银行账户信息记录", [("delete", False), "read"]),
        ("超级管理员", "系统参数配置", [("config_change", False)]),
        ("超级管理员", "审计日志归档", [("export", False), "read"]),
        ("超级管理员", "系统用户管理菜单", ["update"]),
        # 故意违规④: 运营管理员创建+审批同一关键资源(SoD), 且导出客户账户免审批
        ("运营管理员", "交易流水记录", ["create", "approve", "update"]),
        ("运营管理员", "系统参数配置", [("config_change", True), ("approve", True)]),  # 已挂审批, 合规
        ("运营管理员", "银行账户信息记录", [("export", False), "read"]),
        ("运营管理员", "营销活动配置", ["create", "update", ("delete", True)]),  # 已挂审批, 合规
        ("风控复核员", "交易流水记录", [("approve", True), "read"]),  # 审批已挂, 合规
        ("客服专员", "银行账户信息记录", ["read"]),
        ("客服专员", "客服工作台页面", ["read"]),
        ("审计员", "审计日志归档", ["read", ("export", True)]),  # 已挂审批, 合规
    ]
    for role_name, res_name, actions in matrix:
        for action in actions:
            code, needs_appr = action if isinstance(action, tuple) else (action, False)
            session.add(
                PermissionEntry(
                    role_id=role_of[role_name], resource_id=res_of[res_name],
                    action=code, requires_approval=needs_appr,
                )
            )

    # ── Step6 认证与密码策略 ──────────────────────────────
    session.add(
        AuthConfig(
            project_id=project.id,
            auth_methods=["password", "sms_otp", "dynamic_otp", "third_oauth", "sso"],
            pwd_min_length=10, pwd_complexity=4, pwd_valid_days=60,
            lockout_threshold=5, pwd_history_limit=3, force_2fa=True,
            session_timeout_min=10, concurrent_limit=1,
        )
    )

    # ── Step7 SBOM 组件清单(10项, 含 log4j 2.14.1) ────────
    components = [
        ("backend", "Spring Boot", "2.7.18", "pkg:maven/org.springframework.boot/spring-boot-starter-web@2.7.18", "Apache-2.0"),
        ("frontend", "Vue", "3.3.4", "pkg:npm/vue@3.3.4", "MIT"),
        ("frontend", "Element Plus", "2.4.2", "pkg:npm/element-plus@2.4.2", "MIT"),
        ("library", "log4j-core", "2.14.1", "pkg:maven/org.apache.logging.log4j/log4j-core@2.14.1", "Apache-2.0"),  # 故意保留旧版供漏洞演示
        ("library", "fastjson", "1.2.70", "pkg:maven/com.alibaba/fastjson@1.2.70", "Apache-2.0"),
        ("database", "MySQL", "8.0.33", "pkg:generic/mysql@8.0.33", "GPL-2.0"),
        ("middleware", "Redis", "6.2.6", "pkg:generic/redis@6.2.6", "BSD-3-Clause"),
        ("middleware", "Nginx", "1.20.0", "pkg:generic/nginx@1.20.0", "BSD-2-Clause"),
        ("library", "lodash", "4.17.15", "pkg:npm/lodash@4.17.15", "MIT"),
        ("infra", "Kubernetes", "1.24.3", "pkg:generic/kubernetes@1.24.3", "Apache-2.0"),
    ]
    for i, (layer, name, version, purl, lic) in enumerate(components):
        source = "manual_input"
        if i == 0:
            source = "sbom_file"  # 首个组件标记为SBOM文件导入来源, 演示两种source_type
        session.add(
            SbomComponent(
                project_id=project.id, layer=layer, name=name, version=version,
                purl=purl, license=lic, source_type=source,
            )
        )

    # ── Step8 API 接口清单(4条)与基础设施资产 ─────────────
    asset_ids = {a.name: a.id for a in session.query(DataAsset).filter_by(project_id=project.id)}
    endpoints = [
        ("转账汇款接口", "/api/v1/transfers", "POST", True, True, ["银行账户信息", "公民身份信息"], "100 QPS/IP"),
        ("外汇牌价查询", "/api/v1/rates", "GET", False, True, [], None),
        ("微信回调通知", "/open/wechat/callback", "POST", False, True, [], None),
        ("客户信息查询", "/api/v1/customers/{id}", "GET", True, False, ["客户联系方式", "银行账户信息"], "50 QPS/IP"),
    ]
    for name, path, method, need_auth, pub, asset_names, rate in endpoints:
        session.add(
            ApiEndpoint(
                project_id=project.id, name=name, path=path, method=method,
                auth_required=need_auth, public_exposed=pub,
                sensitive_asset_ids=[asset_ids[n] for n in asset_names],
                rate_limit=rate,
            )
        )

    infra = [
        ("server", "网银应用集群A", "prod", "10.20.1.11", "李强", True),
        ("database", "核心Oracle RAC", "prod", "10.20.2.21", "陈数据库", True),
        ("middleware", "Nginx接入层", "prod", "10.20.0.5", "运维组", False),
    ]
    for a_type, name, env, ip, owner, sensitive in infra:
        session.add(
            InfraAsset(
                project_id=project.id, asset_type=a_type, name=name,
                env=env, ip=ip, owner=owner, holds_sensitive=sensitive,
            )
        )

    session.commit()
    return project


def _delete_project(session: Session, project: Project) -> None:
    """清理旧项目全部子表数据, 与 API 删除共用同一套级联口径。"""
    from services.project_service import delete_project_cascade
    delete_project_cascade(session, project.id)


def summarize_requirements(requirements) -> str:
    """控制台输出: 按需求类目分组统计 + 明细列表, 用于人工核验规则命中合理性。"""
    grouped: dict[str, list] = {}
    for req in requirements:
        grouped.setdefault(req.category, []).append(req)

    lines = [f"共生成 {len(requirements)} 条安全需求:", ""]
    priority_order = {p: i for i, p in enumerate(["critical", "high", "medium", "low"])}
    priority_label = lambda p: C.label(C.REQUIREMENT_PRIORITY_LABELS, p)
    phase_label = lambda ph: C.label(C.REQUIREMENT_PHASES, ph, ph)

    for category, items in grouped.items():
        counts = {}
        for it in items:
            counts[it.priority] = counts.get(it.priority, 0) + 1
        stat = ", ".join(
            f"{priority_label(p)}{counts[p]}条" for p in sorted(counts, key=priority_order.get)
        )
        lines.append(f"【{category}】{len(items)}条 ({stat})")
        for it in sorted(items, key=lambda x: priority_order.get(x.priority, 9)):
            lines.append(f"  [{priority_label(it.priority)}|{phase_label(it.suggested_phase)}] "
                         f"{it.req_id} {it.title}")
            lines.append(f"      来源: {it.source_entity_type}#{it.source_entity_id} ← {it.trigger_reason}")
        lines.append("")
    return "\n".join(lines)
