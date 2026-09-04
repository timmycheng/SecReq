# -*- coding: utf-8 -*-
"""规则引擎的输入上下文: 汇聚一个项目的全部输入数据。

引擎只依赖本上下文而非直接查库, 便于测试时用内存对象构造场景。
"""
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

import shared.constants as C
from models import (
    ApiEndpoint, AuthConfig, DataAsset, DataTable, ExternalSystem,
    Feature, GradingSurvey, InfraAsset, PermissionEntry, Project, Resource, Role,
    SbomComponent,
)


@dataclass
class RequirementContext:
    """一个项目参与规则匹配的全部输入快照。"""

    project: Project
    survey: GradingSurvey | None = None
    features: list[Feature] = field(default_factory=list)
    data_assets: list[DataAsset] = field(default_factory=list)
    roles: list[Role] = field(default_factory=list)
    resources: list[Resource] = field(default_factory=list)
    permission_entries: list[PermissionEntry] = field(default_factory=list)
    auth_config: AuthConfig | None = None
    components: list[SbomComponent] = field(default_factory=list)
    api_endpoints: list[ApiEndpoint] = field(default_factory=list)
    infra_assets: list[InfraAsset] = field(default_factory=list)
    external_systems: list[ExternalSystem] = field(default_factory=list)

    # ── 派生便捷属性 ──────────────────────────────────

    @property
    def grading_level(self) -> str:
        """有效定级(人工修正优先)。"""
        return self.survey.effective_level() if self.survey else ""

    @property
    def grading_text(self) -> str:
        return f"等保{self.grading_level}" if self.grading_level else "未定级"

    @property
    def user_scale_text(self) -> str:
        return C.label(C.USER_SCALES, self.project.effective_user_scale(), "未知规模")

    # ── 工厂方法 ──────────────────────────────────────

    @classmethod
    def from_db(cls, session: Session, project_id: int) -> "RequirementContext":
        """从数据库加载项目全部输入(规则引擎主入口)。"""
        import sqlalchemy.orm as orm

        project = session.get(Project, project_id)
        if project is None:
            raise ValueError(f"项目不存在: id={project_id}")

        ctx = cls(project=project)
        ctx.survey = session.query(GradingSurvey).filter_by(project_id=project_id).first()
        ctx.features = (
            session.query(Feature).filter_by(project_id=project_id).order_by(Feature.id).all()
        )
        ctx.data_assets = (
            session.query(DataAsset)
            .filter_by(project_id=project_id)
            .options(orm.selectinload(DataAsset.tables).selectinload(DataTable.fields))
            .order_by(DataAsset.id)
            .all()
        )
        ctx.roles = session.query(Role).filter_by(project_id=project_id).all()
        ctx.resources = session.query(Resource).filter_by(project_id=project_id).all()
        ctx.permission_entries = (
            session.query(PermissionEntry)
            .join(Role, PermissionEntry.role_id == Role.id)
            .filter(Role.project_id == project_id)
            .all()
        )
        ctx.auth_config = session.query(AuthConfig).filter_by(project_id=project_id).first()
        # 组件与基础设施自 #194 起挂系统: 取绑定系统的当前清单(未绑定系统则为空,
        # 触发口径不变 —— 同数据同触发, 仅取数来源随实体归属调整)
        ctx.components = (
            session.query(SbomComponent)
            .filter_by(system_id=project.system_id)
            .options(orm.selectinload(SbomComponent.vulnerabilities))
            .all()
            if project.system_id is not None else []
        )
        ctx.api_endpoints = (
            session.query(ApiEndpoint).filter_by(project_id=project_id).all()
        )
        ctx.infra_assets = (
            session.query(InfraAsset).filter_by(system_id=project.system_id).all()
            if project.system_id is not None else []
        )
        ctx.external_systems = (
            session.query(ExternalSystem).filter_by(project_id=project_id).all()
        )
        return ctx

    # ── uid 索引(#66) ─────────────────────────────────

    def entity_by_uid(self, entity_type: str, uid: str | None):
        """按稳定 uid 定位实体; 找不到返回 None(断链场景由引擎如实降级)。"""
        routes = {
            "feature": ("features",),
            "role": ("roles",),
            "resource": ("resources",),
            "data_asset": ("data_assets",),
            "api_endpoint": ("api_endpoints",),
            "sbom_component": ("components",),
            "external_system": ("external_systems",),
        }
        if not uid or entity_type not in routes:
            return None
        rows = getattr(self, routes[entity_type][0])
        return next((r for r in rows if getattr(r, "uid", None) == uid), None)

    # ── 权限矩阵扫描辅助 ──────────────────────────────

    def entries_of_role(self, role_id: int) -> list[PermissionEntry]:
        return [e for e in self.permission_entries if e.role_id == role_id]

    def resource_by_id(self, resource_id: int) -> Resource | None:
        return next((r for r in self.resources if r.id == resource_id), None)

    def role_actions_on(self, role_id: int, resource_id: int) -> set[str]:
        """某角色在某资源上被授予的全部操作。"""
        return {
            e.action for e in self.permission_entries
            if e.role_id == role_id and e.resource_id == resource_id
        }

    def sensitive_asset_names(self, asset_uids: list) -> list[str]:
        """按 uid 解析敏感资产名(#66); 旧主键数组调用方已随契约一并迁移。"""
        names = []
        uid_set = {u for u in (asset_uids or [])}
        for asset in self.data_assets:
            if asset.uid in uid_set:
                names.append(asset.name)
        return names
