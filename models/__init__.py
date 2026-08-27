# -*- coding: utf-8 -*-
"""模型包统一出口: 导入即注册全部 ORM 映射。"""
from models.database import Base, init_db, make_engine, make_session_factory
from models.project import GradingSurvey, Project
from models.feature import Feature
from models.data_dictionary import DataAsset, DataField, DataTable
from models.permission import PermissionEntry, Resource, Role
from models.auth import AuthConfig
from models.sbom import SbomComponent, VulnerabilityRecord
from models.inventory import ApiEndpoint, InfraAsset
from models.requirement import SecurityRequirement

__all__ = [
    "Base",
    "init_db",
    "make_engine",
    "make_session_factory",
    "Project",
    "GradingSurvey",
    "Feature",
    "DataAsset",
    "DataTable",
    "DataField",
    "Role",
    "Resource",
    "PermissionEntry",
    "AuthConfig",
    "SbomComponent",
    "VulnerabilityRecord",
    "ApiEndpoint",
    "InfraAsset",
    "SecurityRequirement",
]
