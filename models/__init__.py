# -*- coding: utf-8 -*-
"""模型包统一出口: 导入即注册全部 ORM 映射。"""
from models.database import Base, init_db, make_engine, make_session_factory
from models.project import ExternalSystem, GradingSurvey, Project
from models.feature import Feature
from models.data_dictionary import DataAsset, DataField, DataTable
from models.permission import PermissionEntry, Resource, Role
from models.auth import AuthConfig
from models.sbom import SbomComponent, VulnerabilityRecord
from models.inventory import ApiEndpoint, InfraAsset, InfraLayout, InfraLink, NetworkZone
from models.requirement import SecurityRequirement
from models.review import GENESIS_HASH, PlatformUser, ReviewEvidence, ReviewGate
from models.session import UserSession
from models.setting import SystemSetting
from models.audit import AuditLog

__all__ = [
    "Base",
    "init_db",
    "make_engine",
    "make_session_factory",
    "Project",
    "GradingSurvey",
    "ExternalSystem",
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
    "InfraLayout",
    "InfraLink",
    "NetworkZone",
    "SecurityRequirement",
    "PlatformUser",
    "ReviewGate",
    "ReviewEvidence",
    "UserSession",
    "SystemSetting",
    "AuditLog",
    "GENESIS_HASH",
]
