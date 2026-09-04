# -*- coding: utf-8 -*-
"""安全需求规则引擎。

消费方式(DESIGN.md 附注): 遍历知识库全部模板, 按 trigger.type 分派判定函数,
条件满足即实例化为 SecurityRequirement(渲染 {{placeholder}} 占位符),
同类规则命中多个实例时生成多条独立需求并分别关联各自的 source_entity_id。

容错口径: 单条模板配置有误(未知 rule_key / 未知 trigger_type / 占位符缺值)时跳过
该模板并记入 `skipped`, 不中断整轮生成 —— 一条坏配置不该让其余模板全部失效。
"""
import logging
import re
from dataclasses import dataclass

from models import SecurityRequirement
from rules.context import RequirementContext
from rules.loader import KnowledgeBase, RequirementTemplate

import shared.constants as C

logger = logging.getLogger(__name__)

_PLACEHOLDER_PATTERN = re.compile(r"\{\{\s*(\w+)\s*\}\}")

# 高危漏洞整改默认整改时限(工作日), 后续批次可项目级配置
DEFAULT_FIX_DEADLINE_DAYS = 30


class RuleEngineError(Exception):
    """占位符渲染失败等引擎错误。"""


@dataclass
class Match:
    """一次命中: 渲染所需占位符 + 可追溯来源实体。

    source_entity_uid 是溯源权威锚点(跨整卷保存稳定, #66);
    source_entity_id 兼容保留(展示排序兜底), permission_entry 复合键时为 None。
    """

    placeholders: dict[str, str]
    source_entity_type: str
    source_entity_id: int | None
    source_entity_uid: str | None = None


_REQ_SEQ_RE = re.compile(r"^(?P<base>.*?)(?:-(?P<seq>\d{2,}))?$")


def _next_free_req_id(want: str, taken: set[str]) -> str:
    """want 可用则原样返回; 否则 base 序号递增到首个空闲值(确定性, 不依赖遍历顺序)。"""
    if want not in taken:
        return want
    m = _REQ_SEQ_RE.match(want)
    base, seq = m.group("base"), int(m.group("seq") or 1)
    while True:
        seq += 1
        candidate = f"{base}-{seq:02d}"
        if candidate not in taken:
            return candidate


def render(text: str, placeholders: dict[str, str], template_id: str) -> str:
    """替换 {{name}} 占位符; 有缺失值则报错(比静默留白更利于发现知识库缺陷)。

    安全口径: 仅做白名单占位符替换——正则只匹配 {{单词}} 形态, 取值查 placeholders
    字典并以函数替换字面插入; 不做表达式求值、不走 str.format/Jinja, 不构成模板注入(SSTI)。
    """

    def _sub(m: re.Match) -> str:
        key = m.group(1)
        if key not in placeholders:
            raise RuleEngineError(f"模板『{template_id}』占位符 {{{{{key}}}}} 没有可用的取值")
        return placeholders[key]

    return _PLACEHOLDER_PATTERN.sub(_sub, text)


class RuleEngine:
    def __init__(self, kb: KnowledgeBase, fix_deadline_days: int = DEFAULT_FIX_DEADLINE_DAYS):
        self.kb = kb
        self.fix_deadline_days = fix_deadline_days
        # 本轮因配置有误被跳过的模板 [{template_id, reason}]; 每次 generate 重置
        self.skipped: list[dict] = []
        # trigger.type → 命中判定函数(返回 Match 列表)
        self._handlers = {
            "feature_category": self._match_features,
            "permission_rule": self._match_permissions,
            "auth_method": self._match_auth_method,
            "policy_baseline": self._match_policy_baseline,
            "data_asset": self._match_data_assets,
            "api_endpoint": self._match_api_endpoints,
            "compliance": self._match_compliance,
            "vulnerability": self._match_vulnerabilities,
            "regulatory_trigger": self._match_regulatory_triggers,
            "external_system": self._match_external_systems,
            "license_risk": self._match_license_risk,
        }

    @classmethod
    def load(cls, path=None) -> "RuleEngine":
        """从默认知识库文件构建引擎。"""
        from rules.loader import load_knowledge_base
        return cls(load_knowledge_base(path))

    def _skip(self, tpl: RequirementTemplate, reason: str) -> None:
        """记录一条被跳过的模板(供调用方提示与排障)。"""
        self.skipped.append({"template_id": tpl.id, "reason": reason})
        logger.error("跳过配置有误的知识库模板『%s』: %s", tpl.id, reason)

    # ────────────────────────── 主流程 ──────────────────────────

    def generate(self, ctx: RequirementContext) -> list[SecurityRequirement]:
        """对项目上下文执行全量规则匹配, 返回未入库的 SecurityRequirement 列表。

        排序稳定(知识库声明顺序 → 来源实体id), 同模板多实例用 -NN 序号保证 req_id 唯一。
        单条模板配置有误时跳过并记入 `self.skipped`, 不中断整轮匹配。
        """
        collected: list[tuple[RequirementTemplate, Match]] = []
        seen: set[tuple[str, int]] = set()
        self.skipped = []

        for tpl in self.kb.templates:
            if not tpl.enabled:
                continue
            handler = self._handlers.get(tpl.trigger_type)
            if handler is None:
                self._skip(tpl, f"未知触发器类型: {tpl.trigger_type}")
                continue
            try:
                for match in handler(tpl, ctx):
                    key = (tpl.id, match.source_entity_uid or match.source_entity_id)
                    if key in seen:  # 同一模板对同一来源只生成一条
                        continue
                    seen.add(key)
                    collected.append((tpl, match))
            except RuleEngineError as exc:
                # 未知 rule_key 等匹配期错误: 跳过该模板, 其余模板继续
                # (占位符缺值属渲染期错误, 由下方实例化循环兜底)
                self._skip(tpl, str(exc))

        # 稳定排序后分配 req_id 与实例序号; 监管报送类恒置顶
        # 按来源 uid 稳定排序(#66): 自增 id 会随整卷替换漂移, 会让 req_id 序号不稳定
        collected.sort(key=lambda pair: (
            0 if pair[0].trigger_type == "regulatory_trigger" else 1,
            pair[1].source_entity_uid or "",
            pair[1].source_entity_id or 0,
        ))
        counters: dict[str, int] = {}
        requirements: list[SecurityRequirement] = []
        base_placeholders = self._universal_placeholders(ctx)

        for tpl, match in collected:
            # 先取号、构造成功才登记: 失败的实例不消耗 -NN 序号, req_id 分配保持确定性
            seq = counters.get(tpl.id, 0) + 1
            req_id = tpl.id if seq == 1 else f"{tpl.id}-{seq:02d}"
            merged = {**base_placeholders, **match.placeholders}
            try:
                req = SecurityRequirement(
                    project_id=ctx.project.id,
                    req_id=req_id,
                    template_id=tpl.id,
                    title=render(tpl.title, merged, tpl.id),
                    description=render(tpl.description, merged, tpl.id),
                    category=C.label(C.TRIGGER_CATEGORY_LABELS, tpl.trigger_type),
                    priority=tpl.priority,
                    asvs_ref=tpl.asvs_ref,
                    acceptance_criteria=render(tpl.acceptance_criteria, merged, tpl.id),
                    suggested_phase=tpl.suggested_phase,
                    source_entity_type=match.source_entity_type,
                    source_entity_id=match.source_entity_id or 0,
                    source_entity_uid=match.source_entity_uid,
                    trigger_reason=render(tpl.trigger_reason, merged, tpl.id),
                    source_label=self._source_label(ctx, match.source_entity_type, match.source_entity_uid),
                    status="open",
                    regulatory_ref=[dict(ref) for ref in tpl.regulatory_ref],
                    reg_confirmed=False,
                )
            except RuleEngineError as exc:
                # 占位符缺值等渲染期错误: 跳过该模板, 其余模板继续
                self._skip(tpl, str(exc))
                continue
            counters[tpl.id] = seq
            requirements.append(req)
        return requirements

    def _source_label(self, ctx: RequirementContext, entity_type: str, entity_uid: str | None) -> str:
        """来源溯源中文名(展示用, 替代 data_asset#3 形态); 按 uid 查实体(#66)。"""
        label = C.label(C.SOURCE_TYPE_LABELS, entity_type, entity_type)
        if entity_type == "feature":
            found = ctx.entity_by_uid("feature", entity_uid)
            return f"{label}:{found.name}" if found else label
        if entity_type == "role":
            found = ctx.entity_by_uid("role", entity_uid)
            return f"{label}:{found.name}" if found else label
        if entity_type == "permission_entry":
            # 复合键: role_uid|resource_uid|action
            if entity_uid:
                role_uid, res_uid, action = entity_uid.split("|", 2)
                role = ctx.entity_by_uid("role", role_uid)
                res = ctx.entity_by_uid("resource", res_uid)
                if role and res:
                    return f"权限授权:{role.name}→{res.name}({C.label(C.PERMISSION_ACTIONS, action)})"
            return label
        if entity_type == "data_asset":
            found = ctx.entity_by_uid("data_asset", entity_uid)
            return f"{label}:{found.name}" if found else label
        if entity_type == "api_endpoint":
            found = ctx.entity_by_uid("api_endpoint", entity_uid)
            return f"{label}:{found.name}" if found else label
        if entity_type == "sbom_component":
            found = ctx.entity_by_uid("sbom_component", entity_uid)
            return f"{label}:{found.name}@{found.version}" if found else label
        if entity_type == "external_system":
            found = ctx.entity_by_uid("external_system", entity_uid)
            return f"{label}:{found.name}" if found else label
        if entity_type == "compliance_target":
            return label
        if entity_type == "policy_baseline":
            return f"{label}({ctx.grading_text})"
        return label

    def generate_and_save(self, ctx: RequirementContext, session) -> list[SecurityRequirement]:
        """生成并持久化: 按 (template_id, source_entity_uid) upsert(#66, P0-1)。

        - 命中已有行 → 更新标题/描述等派生字段, 保留 reg_confirmed/confirmed_by/
          confirmed_at 与 status(此前被标 obsolete 的行复活时回到 open);
        - 未命中 → 新增;
        - 本轮未命中的旧行 → 不硬删, 标 status="obsolete"(输入已变更/风险已消除),
          保留 source_label, 不伪造映射。

        req_id 唯一性: 保留行的 req_id 原样占位(确认记录与外部引用不漂移),
        新增行撞号时递增序号, obsolete 行撞号时加 -OBS 后缀。
        """
        existing = session.query(SecurityRequirement).filter_by(project_id=ctx.project.id).all()
        index = {(r.template_id, r.source_entity_uid): r for r in existing}
        requirements: list[SecurityRequirement] = []
        taken: set[str] = set()
        for req in self.generate(ctx):
            old = index.pop((req.template_id, req.source_entity_uid), None)
            if old is not None:
                for field in ("title", "description", "category", "priority", "asvs_ref",
                              "acceptance_criteria", "suggested_phase", "trigger_reason",
                              "source_entity_type", "source_entity_id", "source_label",
                              "regulatory_ref"):
                    setattr(old, field, getattr(req, field))
                if old.status == "obsolete":
                    old.status = "open"
                requirements.append(old)
                taken.add(old.req_id)
            else:
                req.req_id = _next_free_req_id(req.req_id, taken)
                taken.add(req.req_id)
                requirements.append(req)
                session.add(req)
        for old in index.values():
            old.status = "obsolete"
            if old.req_id in taken:
                old.req_id = _next_free_req_id(f"{old.req_id}-OBS", taken)
            taken.add(old.req_id)
        session.commit()
        return requirements

    # ────────────────────────── 通用占位符 ──────────────────────────

    def _universal_placeholders(self, ctx: RequirementContext) -> dict[str, str]:
        return {
            "project_name": ctx.project.name,
            "project_code": ctx.project.code,
            "grading_text": ctx.grading_text,
            "grading_level": ctx.grading_level or "未定级",
            "user_scale": ctx.user_scale_text,
            "user_scale_text": ctx.user_scale_text,
            "fix_deadline_days": str(self.fix_deadline_days),
        }

    # ────────────────────────── 各维度判定 ──────────────────────────

    def _match_features(self, tpl: RequirementTemplate, ctx: RequirementContext) -> list[Match]:
        """功能分类命中: 每个包含目标分类的功能独立一条(关联 feature.id)。"""
        category = (tpl.trigger.get("condition") or {}).get("category")
        matches = []
        for feature in ctx.features:
            if feature.matches_any_category(category):
                matches.append(
                    Match(
                        placeholders={
                            "feature_name": feature.name,
                            "feature_module": feature.module or "",
                        },
                        source_entity_type="feature",
                        source_entity_id=feature.id,
                        source_entity_uid=feature.uid,
                    )
                )
        return matches

    def _match_permissions(self, tpl: RequirementTemplate, ctx: RequirementContext) -> list[Match]:
        """权限矩阵分析: 扫描算法按 trigger.rule_key 选择。"""
        rule_key = tpl.trigger.get("rule_key")
        scan = {
            "critical_action_without_approval": self._scan_missing_approval,
            "sod_conflict": self._scan_sod_conflict,
            "super_admin_exists": self._scan_super_admin,
            "always": lambda ctx_: (
                [Match({}, "permission_matrix", ctx_.project.id)] if ctx_.roles else []
            ),
        }.get(rule_key)
        if scan is None:
            raise RuleEngineError(f"模板『{tpl.id}』未知权限规则 rule_key={rule_key}")
        return scan(ctx)

    @staticmethod
    def _entry_role(ctx: RequirementContext, entry) -> "Role | None":  # noqa: F821
        return next((r for r in ctx.roles if r.id == entry.role_id), None)

    def _scan_missing_approval(self, ctx: RequirementContext) -> list[Match]:
        """算法1: 关键资源的高危操作未勾选审批 → 每个违规授权一条需求。"""
        matches = []
        for entry in ctx.permission_entries:
            resource = ctx.resource_by_id(entry.resource_id)
            role = self._entry_role(ctx, entry)
            if resource is None or role is None:
                continue
            if (
                resource.criticality == "critical"
                and entry.action in C.HIGH_RISK_ACTIONS
                and not entry.requires_approval
            ):
                action_label = C.label(C.PERMISSION_ACTIONS, entry.action)
                matches.append(
                    Match(
                        placeholders={
                            "detail_list": f"角色「{role.name}」对资源「{resource.name}」"
                                           f"拥有免审批的「{action_label}」操作",
                            "role_name": role.name,
                        },
                        source_entity_type="permission_entry",
                        source_entity_id=None,
                        source_entity_uid=f"{role.uid}|{resource.uid}|{entry.action}",
                    )
                )
        return matches

    def _scan_sod_conflict(self, ctx: RequirementContext) -> list[Match]:
        """算法2: 同一角色在同一 high/critical 资源上持有互斥操作对(SoD)。

        按角色聚合全部冲突组合成一条整改需求, conflict_pairs 列出明细。
        """
        matches = []
        for role in ctx.roles:
            details: list[str] = []
            for resource in ctx.resources:
                if resource.criticality not in ("high", "critical"):
                    continue
                actions = ctx.role_actions_on(role.id, resource.id)
                for left, right in C.SOD_CONFLICT_PAIRS:
                    if left in actions and right in actions:
                        details.append(
                            f"{C.label(C.PERMISSION_ACTIONS, left)}"
                            f"+{C.label(C.PERMISSION_ACTIONS, right)}"
                            f"(资源「{resource.name}」)"
                        )
                        break  # 同一资源命中一个互斥对即足够说明问题
            if details:
                matches.append(
                    Match(
                        placeholders={
                            "role_name": role.name,
                            "conflict_pairs": "、".join(details),
                        },
                        source_entity_type="role",
                        source_entity_id=role.id,
                        source_entity_uid=role.uid,
                    )
                )
        return matches

    def _scan_super_admin(self, ctx: RequirementContext) -> list[Match]:
        """算法3: 存在超级管理员角色 → 特权账号治理需求。"""
        return [
            Match(
                placeholders={"user_count": str(role.user_count_estimate)},
                source_entity_type="role",
                source_entity_id=role.id,
                source_entity_uid=role.uid,
            )
            for role in ctx.roles
            if role.role_type == "super_admin"
        ]

    def _match_auth_method(self, tpl: RequirementTemplate, ctx: RequirementContext) -> list[Match]:
        """认证方式包含判断 → 单条系统级需求。"""
        method = tpl.trigger.get("method")
        methods = ctx.auth_config.auth_methods or [] if ctx.auth_config else []
        if method not in methods:
            return []
        return [
            Match(
                {"method_label": C.label(C.AUTH_METHODS, method)},
                "auth_config",
                ctx.auth_config.id,
            )
        ]

    def _effective_policy(self, ctx: RequirementContext) -> dict[str, str]:
        """密码策略实际生效值, 统一取自 rules.policy(文档生成共用同一实现)。"""
        from rules.policy import effective_password_policy
        return effective_password_policy(ctx)

    def _match_policy_baseline(self, tpl: RequirementTemplate, ctx: RequirementContext) -> list[Match]:
        """定级推导的策略基线: 默认恒触发(逐条从 auth_config 取值);

        例外: force_2fa 仅在勾选强制双因素、或用户规模>10万、或等保三级时建议。
        """
        rule_key = tpl.trigger.get("rule_key")
        source_id = ctx.auth_config.id if ctx.auth_config else ctx.project.id
        placeholders: dict[str, str] = {}

        if rule_key == "force_2fa":
            cfg = ctx.auth_config
            flagged = bool(cfg.force_2fa) if cfg else False
            large_scale = ctx.project.effective_user_scale() in ("100k_to_1m", "over_1m")
            top_level = ctx.grading_level == "三级"
            if not (flagged or large_scale or top_level):
                return []
            placeholders.update({"force_2fa_flagged": str(flagged)})
        elif rule_key in (
            "password_strength", "lockout_threshold", "session_timeout"
        ):
            placeholders.update(self._effective_policy(ctx))
        elif rule_key != "always":
            raise RuleEngineError(f"模板『{tpl.id}』未知策略基线 rule_key={rule_key}")

        return [Match(placeholders, "policy_baseline", source_id)]

    def _match_data_assets(self, tpl: RequirementTemplate, ctx: RequirementContext) -> list[Match]:
        """数据资产规则: 按 condition 键分派, 每条命中的资产独立成需求。

        分级条件(JR/T 0197 五级):
        - {level: code}  精确等于该级;
        - {min_level: code} 数值等级不低于该级(如 4级 条件覆盖 4级与5级);
        - {c3_tag: true} 命中 C3 鉴别信息标签。
        """
        condition = tpl.trigger.get("condition") or {}
        matches: list[Match] = []

        if "classification" in condition:
            for asset in ctx.data_assets:
                if asset.classification == condition["classification"]:
                    matches.append(Match({"asset_name": asset.name}, "data_asset", asset.id, asset.uid))

        elif "level" in condition or "min_level" in condition:
            threshold = C.level_rank(condition.get("level") or condition.get("min_level"))
            exact = "level" in condition
            for asset in ctx.data_assets:
                rank = C.level_rank(asset.classification)
                if rank <= 0:
                    continue
                if (rank == threshold) if exact else (rank >= threshold):
                    matches.append(Match({"asset_name": asset.name}, "data_asset", asset.id, asset.uid))

        elif condition.get("c3_tag"):
            for asset in ctx.data_assets:
                if asset.c3_tag:
                    matches.append(Match({"asset_name": asset.name}, "data_asset", asset.id, asset.uid))

        elif condition.get("is_sensitive_pii"):
            for asset in ctx.data_assets:
                if asset.is_sensitive_pii:
                    matches.append(Match({"asset_name": asset.name}, "data_asset", asset.id, asset.uid))

        elif "mask_fields_any_of" in condition:
            # 与字段名正则匹配, 命中任一需脱敏字段类型的资产出一条需求
            for asset in ctx.data_assets:
                hit_kinds = self._asset_mask_hits(asset, condition["mask_fields_any_of"])
                if hit_kinds:
                    labels = "、".join(C.label(C.MASK_FIELD_PATTERNS, k, k) for k in sorted(hit_kinds))
                    matches.append(
                        Match(
                            {"asset_name": asset.name, "matched_field_types": labels},
                            "data_asset",
                            asset.id,
                            asset.uid,
                        )
                    )

        elif condition.get("has_log_leakage_risk"):
            for asset in ctx.data_assets:
                if "log" in (asset.storage_envs or []):
                    matches.append(Match({"asset_name": asset.name}, "data_asset", asset.id, asset.uid))

        elif condition.get("cross_border"):
            for asset in ctx.data_assets:
                if asset.cross_border_transfer:
                    matches.append(Match({"asset_name": asset.name}, "data_asset", asset.id, asset.uid))

        return matches

    @staticmethod
    def _asset_mask_hits(asset, kinds: list[str]) -> set[str]:
        """返回该资产命中的脱敏字段类型集合。"""
        import re as _re

        hits: set[str] = set()
        compiled = {
            kind: _re.compile(C.MASK_FIELD_PATTERNS[kind], _re.IGNORECASE)
            for kind in kinds if kind in C.MASK_FIELD_PATTERNS
        }
        for _, field in asset.iter_fields():
            for kind, pattern in compiled.items():
                if pattern.search(field.field_name or ""):
                    hits.add(kind)
        return hits

    def _match_api_endpoints(self, tpl: RequirementTemplate, ctx: RequirementContext) -> list[Match]:
        """接口属性布尔判定, 每个满足条件的接口一条需求。"""
        condition = tpl.trigger.get("condition") or {}
        matches: list[Match] = []

        for ep in ctx.api_endpoints:
            hit = False
            asset_names: list[str] = []
            if "public_exposed" in condition and ep.public_exposed == bool(condition["public_exposed"]):
                hit = True
            if "auth_required" in condition and ep.auth_required == bool(condition["auth_required"]):
                hit = True
            if condition.get("touches_sensitive_asset"):
                asset_names = ctx.sensitive_asset_names(ep.sensitive_asset_uids)
                if asset_names:
                    hit = True

            if hit:
                matches.append(
                    Match(
                        placeholders={
                            "api_name": ep.name,
                            "api_path": f"{ep.method} {ep.path}",
                            "rate_limit": ep.rate_limit or "未配置",
                            "asset_name": "、".join(asset_names) if asset_names else "",
                        },
                        source_entity_type="api_endpoint",
                        source_entity_id=ep.id,
                        source_entity_uid=ep.uid,
                    )
                )
        return matches

    def _match_compliance(self, tpl: RequirementTemplate, ctx: RequirementContext) -> list[Match]:
        """合规目标包含判断: target 在项目合规目标列表中即命中。"""
        target = tpl.trigger.get("target")
        targets = ctx.project.compliance_targets or []
        if target not in targets:
            return []
        return [
            Match(
                {"compliance_target": C.label(C.COMPLIANCE_TARGETS, target)},
                "compliance_target",
                ctx.project.id,
            )
        ]

    def _match_regulatory_triggers(self, tpl: RequirementTemplate, ctx: RequirementContext) -> list[Match]:
        """监管报送触发器(改造点3): 项目输入满足条件即在需求清单置顶生成报送类需求。

        rule_key 枚举(7 项, 均已实现):
        - l5_data_exists        存在 5级(重要数据)资产
        - cross_border_exists   任一资产跨境传输 或 项目存在境外外包/供应商
        - mobile_app_type       项目类型为手机APP/小程序
        - ai_feature            功能清单含 AI 功能
        - final_level_l3        有效定级为三级
        - sensitive_pii_exists  存在敏感个人信息资产(PIA 事前评估)
        - djcp_l3_filing        三级系统等保测评与公安机关备案

        未知 rule_key 抛 RuleEngineError, 由 generate() 捕获后跳过该模板
        (早前 docstring 曾列有未实现的 saas_finance, 已移除以免误导配置)。
        """
        key = tpl.trigger.get("rule_key")
        pid = ctx.project.id

        if key == "l5_data_exists":
            assets = [a for a in ctx.data_assets if C.level_rank(a.classification) == 5]
            if not assets:
                return []
            names = "、".join(a.name for a in assets)
            return [Match({"asset_list": names}, "project", pid)]

        if key == "cross_border_exists":
            assets = [a for a in ctx.data_assets if a.cross_border_transfer]
            offshore = bool(ctx.project.effective_offshore_vendor())
            if not assets and not offshore:
                return []
            detail = []
            if assets:
                detail.append(f"跨境数据资产: {('、'.join(a.name for a in assets))}")
            if offshore:
                detail.append("项目存在境外外包/境外供应商")
            return [Match({"cross_border_detail": "; ".join(detail)}, "project", pid)]

        if key == "mobile_app_type":
            types = project_types(ctx.project)
            mobile = [t for t in types if t in ("mobile_app", "mini_program")]
            if not mobile:
                return []
            labels = "、".join(C.label(C.PROJECT_TYPES, t) for t in mobile)
            return [
                Match({"project_type_label": labels}, "project", pid)
            ]

        if key == "ai_feature":
            ai_features = [
                f for f in ctx.features if f.matches_any_category("ai_feature")
            ]
            if not ai_features:
                return []
            return [
                Match(
                    {"feature_list": "、".join(f.name for f in ai_features)},
                    "project", pid,
                )
            ]

        if key == "final_level_l3":
            if ctx.grading_level != "三级":
                return []
            return [Match({}, "project", pid)]

        if key == "sensitive_pii_exists":
            assets = [a for a in ctx.data_assets if a.is_sensitive_pii]
            if not assets:
                return []
            return [
                Match(
                    {"asset_list": "、".join(a.name for a in assets)},
                    "project", pid,
                )
            ]

        if key == "djcp_l3_filing":
            if ctx.grading_level != "三级" and "djcp_l3" not in (ctx.project.compliance_targets or []):
                return []
            return [Match({}, "project", pid)]

        raise RuleEngineError(f"模板『{tpl.id}』未知监管报送 rule_key={key}")

    def _match_external_systems(self, tpl: RequirementTemplate, ctx: RequirementContext) -> list[Match]:
        """外部系统交互: 每个对接的外部系统一条需求。

        condition:
        - {} 或 {"sensitive_only": false}  命中全部外部系统
        - {"sensitive_only": true}         仅命中传输敏感数据的外部系统
        """
        condition = tpl.trigger.get("condition") or {}
        sensitive_only = bool(condition.get("sensitive_only"))
        for system in ctx.external_systems:
            if sensitive_only and not system.involves_sensitive:
                continue
            yield Match(
                placeholders={
                    "system_name": system.name,
                    "direction_label": C.label(
                        C.EXTERNAL_SYSTEM_DIRECTIONS, system.direction, system.direction),
                },
                source_entity_type="external_system",
                source_entity_id=system.id,
                source_entity_uid=system.uid,
            )

    def _match_license_risk(self, tpl: RequirementTemplate, ctx: RequirementContext) -> list[Match]:
        """许可证风险: 组件申报许可证的风险等级达到模板阈值时每个组件一条需求。

        condition: {"risk": "high"} 或 {"risk": "medium"}(含 medium 及以上)。
        """
        threshold = (tpl.trigger.get("condition") or {}).get("risk", "high")
        threshold_rank = C.LICENSE_RISK_ORDER.get(threshold, 3)
        for component in ctx.components:
            info = C.LICENSE_RISK.get(component.license or "")
            if info is None:
                continue
            if C.LICENSE_RISK_ORDER.get(info["risk"], 0) < threshold_rank:
                continue
            yield Match(
                placeholders={
                    "component_name": component.name,
                    "license_name": component.license or "",
                    "risk_label": info["label"],
                    "risk_note": info["note"],
                },
                source_entity_type="sbom_component",
                source_entity_id=component.id,
                source_entity_uid=component.uid,
            )

    def _match_vulnerabilities(self, tpl: RequirementTemplate, ctx: RequirementContext) -> list[Match]:
        """SBOM 漏洞联动: 组件存在 high/critical 漏洞时每个组件一条需求。

        OSV 实际查询在 services 层(第二批实现); 本判定仅依赖已落库的 VulnerabilityRecord。
        """
        # severity_range 给出允许区间(如 [high, critical]), 取其中最不严重的档位作阈值
        severity_range = tpl.trigger.get("severity_range", ["high", "critical"])
        threshold = max(C.SEVERITY_ORDER.get(s, 9) for s in severity_range)
        matches: list[Match] = []

        for component in ctx.components:
            vulns = [
                v for v in (component.vulnerabilities or [])
                if C.SEVERITY_ORDER.get(v.severity, 9) <= threshold
            ]
            if not vulns:
                continue
            vulns.sort(key=lambda v: C.SEVERITY_ORDER.get(v.severity, 9))
            shown = [
                f"{v.cve_id}"
                + (f"(CVSS {v.cvss_score:g})" if v.cvss_score is not None else "")
                + (f" 修复版 {v.fix_version}" if v.fix_version else "")
                for v in vulns[:3]
            ]
            summary = "; ".join(shown) + (f" 等{len(vulns)}项" if len(vulns) > 3 else "")
            matches.append(
                Match(
                    placeholders={
                        "component_name": component.name,
                        "component_version": component.version,
                        "vuln_summary": summary,
                        "cve_list": ", ".join(v.cve_id for v in vulns),
                    },
                    source_entity_type="sbom_component",
                    source_entity_id=component.id,
                    source_entity_uid=component.uid,
                )
            )
        return matches


def project_types(project) -> list[str]:
    """项目类型多选(#194 起真相在挂靠系统, 兼容存量单值回退)。"""
    types = list(project.effective_types() if hasattr(project, "effective_types")
                 else (getattr(project, "types", None) or []))
    if not types:
        single = getattr(project, "type", "")
        types = [single] if single else []
    return types
