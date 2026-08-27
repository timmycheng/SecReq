# -*- coding: utf-8 -*-
"""Step8 API 接口清单与基础设施资产清单。"""
from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.database import Base
from models.project import Project


class ApiEndpoint(Base):
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
        JSON, default=list, comment="关联敏感数据资产id列表"
    )
    rate_limit: Mapped[str | None] = mapped_column(String(50), comment="限流配置描述")

    project: Mapped[Project] = relationship(back_populates="api_endpoints")


class InfraAsset(Base):
    """服务器/数据库/中间件资产。"""

    __tablename__ = "infra_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("projects.id"), index=True)
    asset_type: Mapped[str] = mapped_column(String(20), comment="server/database/middleware")
    name: Mapped[str] = mapped_column(String(200), comment="名称")
    env: Mapped[str] = mapped_column(String(10), comment="dev/test/prod")
    ip: Mapped[str | None] = mapped_column(String(64), comment="IP地址")
    owner: Mapped[str | None] = mapped_column(String(50), comment="负责人")
    holds_sensitive: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否承载敏感数据")

    project: Mapped[Project] = relationship(back_populates="infra_assets")
