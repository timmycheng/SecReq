# -*- coding: utf-8 -*-
"""Step8 API 接口清单与基础设施资产清单。"""
from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
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
    # NetBox 互通(#153): 推送成功后回填, 仅作来源侧标识, 不参与规则引擎
    netbox_ref_type: Mapped[str | None] = mapped_column(
        String(40), comment="NetBox 对象类型(如 dcim.device/virtualization.virtual-machine/ipam.ip-address)")
    netbox_ref_id: Mapped[str | None] = mapped_column(
        String(32), comment="NetBox 对象 id, 用于回查与外链")

    project: Mapped[Project] = relationship(back_populates="infra_assets")


class InfraArchImage(Base):
    """架构图(#164): 按环境各一张, data URL(base64)存库。

    随项目整卷复制/评估继承自动走通, 不依赖文件卷; 拓扑画布回退后
    架构关系以图片 + 清单表达。
    """

    __tablename__ = "infra_arch_images"
    __table_args__ = (UniqueConstraint("project_id", "env", name="uq_arch_image_project_env"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("projects.id"), index=True)
    env: Mapped[str] = mapped_column(String(10), comment="环境 test/prod/dev, 每环境一张")
    image_data_url: Mapped[str] = mapped_column(Text, comment="图片 data URL(png/jpeg/webp, base64)")
