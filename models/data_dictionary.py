# -*- coding: utf-8 -*-
"""Step4 数据字典: 数据资产 → 数据表 → 字段 三级结构。"""
from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.database import Base
from models.project import Project


class DataAsset(Base):
    """数据资产(字典一级)。classification 存中文(公开/内部/敏感/机密), 与知识库条件直接匹配。"""

    __tablename__ = "data_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(200), comment="资产名称")
    data_type: Mapped[str] = mapped_column(String(50), comment="分类, 见 DATA_ASSET_TYPES")
    classification: Mapped[str] = mapped_column(String(10), comment="分级: 公开/内部/敏感/机密")
    is_pii: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否个人信息")
    is_sensitive_pii: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否敏感个人信息")
    storage_envs: Mapped[list] = mapped_column(
        JSON, default=list, comment="存储位置多选(db/cache/log/file/object_storage/mq)"
    )
    cross_border_transfer: Mapped[bool] = mapped_column(
        Boolean, default=False, comment="是否涉及跨境传输"
    )

    project: Mapped[Project] = relationship(back_populates="data_assets")
    tables: Mapped[list["DataTable"]] = relationship(
        back_populates="asset", cascade="all, delete-orphan"
    )

    def iter_fields(self):
        """遍历资产下全部字段(engine 的 mask_fields_any_of 扫描入口)。"""
        for table in self.tables or []:
            for field in table.fields or []:
                yield table, field


class DataTable(Base):
    """数据表(字典二级)。"""

    __tablename__ = "data_tables"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_id: Mapped[int] = mapped_column(Integer, ForeignKey("data_assets.id"), index=True)
    table_name: Mapped[str] = mapped_column(String(128), comment="物理表名")

    asset: Mapped[DataAsset] = relationship(back_populates="tables")
    fields: Mapped[list["DataField"]] = relationship(
        back_populates="table", cascade="all, delete-orphan"
    )


class DataField(Base):
    """字段(字典三级), 带脱敏/加密设计属性。"""

    __tablename__ = "data_fields"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    table_id: Mapped[int] = mapped_column(Integer, ForeignKey("data_tables.id"), index=True)
    field_name: Mapped[str] = mapped_column(String(128), comment="字段名")
    field_type: Mapped[str] = mapped_column(String(64), comment="数据类型(varchar/decimal等)")
    need_encrypt: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否加密存储")
    need_mask: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否脱敏展示")
    mask_rule: Mapped[str | None] = mapped_column(String(200), comment="脱敏规则建议")

    table: Mapped[DataTable] = relationship(back_populates="fields")
