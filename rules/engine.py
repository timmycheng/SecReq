# -*- coding: utf-8 -*-
"""安全需求规则引擎。

消费方式(DESIGN.md 附注): 遍历知识库全部模板, 按 trigger.type 分派判定函数,
条件满足即实例化为 SecurityRequirement(渲染 {{placeholder}} 占位符),
同类规则命中多个实例时生成多条独立需求并分别关联各自的 source_entity_id。
"""
import re
from dataclasses import dataclass

from models import SecurityRequirement
from rules.context import RequirementContext
from rules.loader import KnowledgeBase, Template

import shared.constants as C

_PLACEHOLDER_PATTERN = re.compile(r"\{\{\s*(\w+)\s*\}\}")

# 高危漏洞整改默认整改时限(工作日), 后续批次可项目级配置
DEFAULT_FIX_DEADLINE_DAYS = 30


class RuleEngineError(Exception):
    """占位符渲染失败等引擎错误。"""


@dataclass
class Match:
    """一次命中: 渲染所需占位符 + 可追溯来源实体。"""

    placeholders: dict[str, str]
    source_entity_type: str
    source_entity_id: int


def render(text: str, placeholders: dict[str, str], template_id: str) -> str:
    """替换 {{name}} 占位符; 有缺失值则报错(比静默留白更利于发现知识库缺陷)。"""

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
        }

    @classmethod
    def load(cls, path=None) -> "RuleEngine":
        """从默认知识库文件构建引擎。"""
        from rules.loader import load_knowledge_base
        return cls(load_knowledge_base(path))

    # ────────────────────────── 主流程 ──────────────────────────

    def generate(self, ctx: RequirementContext) -> list[SecurityRequirement]:
        """对项目上下文执行全量规则匹配, 返回未入库的 SecurityRequirement 列表。

        排序稳定(知识库声明顺序 → 来源实体id), 同模板多实例用 -NN 序号保证 req_id 唯一。
        """
        collected: list[tuple[Template, Match]] = []
        seen: set[tuple[str, int]] = set()

        for tpl in self.kb.templates:
            handler = self._handlers[tpl.trigger_type]
            for match in handler(tpl, ctx):
                key = (tpl.id, match.source_entity_id)
                if key in seen:  # 同一模板对同一来源只生成一条
                    continue
                seen.add(key)
                collected.append((tpl, match))

        # 稳定排序后分配 req_id 与实例序号
        collected.sort(key=lambda pair: pair[1].source_entity_id)
        counters: dict[str, int] = {}
        requirements: list[SecurityRequirement] = []
        base_placeholders = self._universal_placeholders(ctx)

        for tpl, match in collected:
            seq = counters.get(tpl.id, 0) + 1
            counters[tpl.id] = seq
            req_id = tpl.id if seq == 1 else f"{tpl.id}-{seq:02d}"
            merged = {**base_placeholders, **match.placeholders}
            requirements.append(
                SecurityRequirement(
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
                    source_entity_id=match.source_entity_id,
                    trigger_reason=render(tpl.trigger_reason, merged, tpl.id),
                    status="open",
                )
            )
        return requirements

    def generate_and_save(self, ctx: RequirementContext, session) -> list[SecurityRequirement]:
        """生成并持久化(供后续 POST /generate 路由复用); 重复执行先清空旧需求。"""
        session.query(SecurityRequirement).filter_by(project_id=ctx.project.id).delete()
        requirements = self.generate(ctx)
        session.add_all(requirements)
        session.commit()
        return requirements

    # ────────────────────────── 通用占位符 ──────────────────────────

    def _universal_placeholders(self, ctx: RequirementContext) -> dict[str, str]:
        return {
            "project_name": ctx.project.name,
            "project_code": ctx.project.code,
            "grading_text": ctx.grading_text,
            "user_scale": ctx.user_scale_text,
            "user_scale_text": ctx.user_scale_text,
            "fix_deadline_days": str(self.fix_deadline_days),
        }

    # ────────────────────────── 各维度判定 ──────────────────────────

    def _match_features(self, tpl: Template, ctx: RequirementContext) -> list[Match]:
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
                    )
                )
        return matches

    def _match_permissions(self, tpl: Template, ctx: RequirementContext) -> list[Match]:
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
    def _entry_role(ctx: RequirementContext, entry) -> "Role | None":
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
                        source_entity_id=entry.id,
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
            )
            for role in ctx.roles
            if role.role_type == "super_admin"
        ]

    def _match_auth_method(self, tpl: Template, ctx: RequirementContext) -> list[Match]:
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

    def _match_policy_baseline(self, tpl: Template, ctx: RequirementContext) -> list[Match]:
        """定级推导的策略基线: 默认恒触发(逐条从 auth_config 取值);

        例外: force_2fa 仅在勾选强制双因素、或用户规模>10万、或等保三级时建议。
        """
        rule_key = tpl.trigger.get("rule_key")
        source_id = ctx.auth_config.id if ctx.auth_config else ctx.project.id
        placeholders: dict[str, str] = {}

        if rule_key == "force_2fa":
            cfg = ctx.auth_config
            flagged = bool(cfg.force_2fa) if cfg else False
            large_scale = ctx.project.user_scale in ("100k_to_1m", "over_1m")
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

    def _match_data_assets(self, tpl: Template, ctx: RequirementContext) -> list[Match]:
        """数据资产规则: 按 condition 键分派, 每条命中的资产独立成需求。"""
        condition = tpl.trigger.get("condition") or {}
        matches: list[Match] = []

        if "classification" in condition:
            for asset in ctx.data_assets:
                if asset.classification == condition["classification"]:
                    matches.append(Match({"asset_name": asset.name}, "data_asset", asset.id))

        elif condition.get("is_sensitive_pii"):
            for asset in ctx.data_assets:
                if asset.is_sensitive_pii:
                    matches.append(Match({"asset_name": asset.name}, "data_asset", asset.id))

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
                        )
                    )

        elif condition.get("has_log_leakage_risk"):
            for asset in ctx.data_assets:
                if "log" in (asset.storage_envs or []):
                    matches.append(Match({"asset_name": asset.name}, "data_asset", asset.id))

        elif condition.get("cross_border"):
            for asset in ctx.data_assets:
                if asset.cross_border_transfer:
                    matches.append(Match({"asset_name": asset.name}, "data_asset", asset.id))

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

    def _match_api_endpoints(self, tpl: Template, ctx: RequirementContext) -> list[Match]:
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
                asset_names = ctx.sensitive_asset_names(ep.sensitive_asset_ids)
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
                    )
                )
        return matches

    def _match_compliance(self, tpl: Template, ctx: RequirementContext) -> list[Match]:
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

    def _match_vulnerabilities(self, tpl: Template, ctx: RequirementContext) -> list[Match]:
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
                )
            )
        return matches
