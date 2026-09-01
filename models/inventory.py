# -*- coding: utf-8 -*-
"""Step8 API 接口清单与基础设施资产清单。"""
from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.database import Base, UidMixin
from models.project import Project


class ApiEndpoint(Base, UidMixin):
    """接口安全属性清单。sensitive_asset_ids 关联 DataAsset.id(请求/响应含敏感数据)。"""

    __tablename__ = "api_endpoints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(200), comment="接口名")
    path: Mapped[str] = mapped_column(String(300), comment="路径")
    method: Mapped[str] = mapped_column(String(10), comment="HTTP方法")
    auth_required: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否需要认证")
    public_exposed: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否公网暴露")
    sensitive_asset_ids: Mapped[list] = mapped_column(
        JSON, default=list, comment="关联敏感数据资产主键(v2.3.0 起为兼容保留, 以 *_uids 为准)"
    )
    sensitive_asset_uids: Mapped[list] = mapped_column(
        JSON, default=list, comment="关联敏感数据资产 uid 列表(跨整卷保存稳定, #66)"
    )
    rate_limit: Mapped[str | None] = mapped_column(String(50), comment="限流配置描述")

    project: Mapped[Project] = relationship(back_populates="api_endpoints")


class InfraAsset(Base, UidMixin):
    """服务器/网络设备/数据库/中间件资产。服务器需填规格; 网络设备设计期地址可预留。"""

    __tablename__ = "infra_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("projects.id"), index=True)
    asset_type: Mapped[str] = mapped_column(String(20), comment="server/network/database/middleware")
    name: Mapped[str] = mapped_column(String(200), comment="名称")
    env: Mapped[str] = mapped_column(String(10), comment="dev/test/prod")
    ip: Mapped[str | None] = mapped_column(String(64), comment="IP地址(网络设备设计期可预留)")
    owner: Mapped[str | None] = mapped_column(String(50), comment="负责人")
    holds_sensitive: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否承载敏感数据")
    # 服务器规格(设计期规划值)
    cpu_cores: Mapped[int | None] = mapped_column(Integer, comment="CPU核数")
    memory_gb: Mapped[int | None] = mapped_column(Integer, comment="内存(GB)")
    disk_gb: Mapped[int | None] = mapped_column(Integer, comment="磁盘(GB)")
    os: Mapped[str | None] = mapped_column(String(100), comment="操作系统")
    quantity: Mapped[int | None] = mapped_column(Integer, comment="数量")
    purpose: Mapped[str | None] = mapped_column(String(300), comment="用途说明/网络区域")
    zone_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("network_zones.id"), nullable=True,
        comment="所属网络区域(拓扑画布一期, #93)",
    )

    project: Mapped[Project] = relationship(back_populates="infra_assets")


class NetworkZone(Base, UidMixin):
    """网络区域(拓扑画布一期, #93): DMZ/核心区等分组框, 按项目+环境隔离。"""

    __tablename__ = "network_zones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("projects.id"), index=True)
    env: Mapped[str] = mapped_column(String(10), default="prod", comment="环境 test/prod(画布按环境独立)")
    name: Mapped[str] = mapped_column(String(100), comment="区域名(如 DMZ/核心区)")


class InfraLink(Base):
    """设备间连线(拓扑画布一期, #93): 按资产 uid 引用, 可带说明文字。"""

    __tablename__ = "infra_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("projects.id"), index=True)
    env: Mapped[str] = mapped_column(String(10), default="prod", index=True)
    source_uid: Mapped[str] = mapped_column(String(36), comment="起点资产 uid")
    target_uid: Mapped[str] = mapped_column(String(36), comment="终点资产 uid")
    label: Mapped[str | None] = mapped_column(String(200), comment="连线说明(如 HTTPS 8443)")


class InfraLayout(Base):
    """画布布局(#93): 节点坐标/区域框位置按 项目+环境 存 JSON, 不进规则引擎。"""

    __tablename__ = "infra_layouts"
    __table_args__ = (UniqueConstraint("project_id", "env", name="uq_layout_project_env"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("projects.id"), index=True)
    env: Mapped[str] = mapped_column(String(10), default="prod")
    layout: Mapped[dict] = mapped_column(JSON, default=dict, comment="{nodes: {uid: {x,y}}, zones: {zoneId: {x,y,w,h}}}")
