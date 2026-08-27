# -*- coding: utf-8 -*-
"""Step5 用户权限矩阵: 角色 × 资源 × 操作。"""
from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.database import Base
from models.project import Project


class Role(Base):
    """系统角色。role_type 见 ROLE_TYPES(normal/privileged/super_admin)。"""

    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(100), comment="角色名称")
    role_type: Mapped[str] = mapped_column(String(20), default="normal", comment="角色类型")
    user_count_estimate: Mapped[int] = mapped_column(Integer, default=0, comment="预估人数")

    project: Mapped[Project] = relationship(back_populates="roles")
    permission_entries: Mapped[list["PermissionEntry"]] = relationship(
        back_populates="role", cascade="all, delete-orphan"
    )


class Resource(Base):
    """被权限管理的资源。criticality 关键性参与高危审批规则判定。"""

    __tablename__ = "resources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(200), comment="资源名称")
    resource_type: Mapped[str] = mapped_column(String(30), comment="资源类型")
    criticality: Mapped[str] = mapped_column(String(20), default="medium", comment="关键性 low/medium/high/critical")

    project: Mapped[Project] = relationship(back_populates="resources")
    permission_entries: Mapped[list["PermissionEntry"]] = relationship(
        back_populates="resource", cascade="all, delete-orphan"
    )


class PermissionEntry(Base):
    """矩阵单元格中的一次授权: 角色对资源执行某操作。

    UNIQUE(role_id, resource_id, action) 保证同一格子同一操作只登记一次。
    """

    __tablename__ = "permission_entries"
    __table_args__ = (
        UniqueConstraint("role_id", "resource_id", "action", name="uq_perm_role_res_action"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    role_id: Mapped[int] = mapped_column(Integer, ForeignKey("roles.id"), index=True)
    resource_id: Mapped[int] = mapped_column(Integer, ForeignKey("resources.id"), index=True)
    action: Mapped[str] = mapped_column(String(30), comment="操作, 见 PERMISSION_ACTIONS")
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False, comment="该操作是否需审批")

    role: Mapped[Role] = relationship(back_populates="permission_entries")
    resource: Mapped[Resource] = relationship(back_populates="permission_entries")
