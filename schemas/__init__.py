# -*- coding: utf-8 -*-
"""Pydantic 请求/响应模型(API 契约层)。

约定: 数据库一律存 code/枚举值, 中文标签由前端按 /api/meta/constants 映射展示。
"""
from schemas.auth import AuthConfigIn, AuthConfigOut, AuthDefaultsOut
from schemas.component import (
    ComponentIn, ComponentOut, ComponentVulnInline,
    SbomImportResult, ComponentsSaveIn,
)
from schemas.data_dictionary import (
    DataAssetIn, DataAssetListIn, DataAssetOut,
    DataFieldIn, DataFieldOut, DataTableIn, DataTableOut,
)
from schemas.feature import FeatureIn, FeatureOut
from schemas.inventory import (
    ApiEndpointIn, ApiEndpointOut, InfraAssetIn, InfraAssetOut, InventorySaveIn,
)
from schemas.permission import (
    MatrixEntryIn, MatrixEntryOut, PermissionMatrixIn, PermissionMatrixOut,
    ResourceIn, ResourceOut, RoleIn, RoleOut,
)
from schemas.project import (
    ProjectCreate, ProjectDetail, ProjectOut, ProjectUpdate, WizardState,
)
from schemas.requirement import (
    CategoryCount, GenerateSummary, PreviewResult, RequirementOut, VulnerabilityOut,
)
from schemas.survey import SurveyAnswerIn, SurveyOut, SurveySubmitIn

__all__ = [
    # 项目与问卷
    "ProjectCreate", "ProjectUpdate", "ProjectOut", "ProjectDetail", "WizardState",
    "SurveyAnswerIn", "SurveySubmitIn", "SurveyOut",
    # 步骤数据
    "FeatureIn", "FeatureOut",
    "DataAssetIn", "DataAssetListIn", "DataAssetOut",
    "DataFieldIn", "DataFieldOut", "DataTableIn", "DataTableOut",
    "RoleIn", "RoleOut", "ResourceIn", "ResourceOut",
    "PermissionMatrixIn", "PermissionMatrixOut", "MatrixEntryIn", "MatrixEntryOut",
    "AuthConfigIn", "AuthConfigOut", "AuthDefaultsOut",
    "ComponentIn", "ComponentOut", "ComponentsSaveIn", "ComponentVulnInline",
    "SbomImportResult",
    "ApiEndpointIn", "ApiEndpointOut", "InfraAssetIn", "InfraAssetOut", "InventorySaveIn",
    # 结果产物
    "RequirementOut", "VulnerabilityOut", "CategoryCount",
    "PreviewResult", "GenerateSummary",
]
