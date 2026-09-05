# -*- coding: utf-8 -*-
"""漏填检测服务(#221): 设计门禁 missing 的兜底来源, 5 条规则集中声明。

只读检测、不落库、不阻断填写; 结果汇入设计门禁(#222)的 blocked 契约,
只在提交评审时运行。规则按同一思路派生: 命中敏感语义/高风险形态的输入,
却缺少应有的治理动作(关联/加密/分级/限流), 即视为漏填。
"""
import re

from sqlalchemy.orm import Session

from models import ApiEndpoint, DataAsset, Feature, Project

# 敏感字段名正则: 命中即按敏感字段对待(身份证/手机号/银行卡/护照/口令)
SENSITIVE_FIELD_RE = re.compile(
    r"id_?card|身份[证号码]|phone|手机|mobile|bank_?card|银行[卡账号]|passport|护照|password|密码|口令",
    re.I,
)
# 账户/支付类资产名正则: 支付类功能应至少有一条该类资产承载
ACCOUNT_ASSET_RE = re.compile(r"账户|账务|支付|订单|交易|银行[卡号]|余额|清算|结算")
# 低分级集合: 敏感字段挂在以下分级疑似偏低
LOW_LEVELS = {"1级_公开数据", "2级_C1次要信息"}
# C2/C3 及以上分级(数据字典必须建表): 3级/4级/5级
C3_PLUS_LEVELS = {"3级_C2主要信息", "4级_C3鉴别信息", "5级_重要数据"}


def _sensitive_fields(assets: list[DataAsset]):
    """展开 (资产, 表, 字段) 三级并筛出敏感字段。"""
    for asset in assets:
        for table in asset.tables or []:
            for field in table.fields or []:
                if SENSITIVE_FIELD_RE.search(field.field_name or ""):
                    yield asset, table, field


def run_omission_checks(db: Session, project: Project) -> list[str]:
    """漏填检测(#221): 返回缺项描述列表, 空列表 = 通过。"""
    missing: list[str] = []
    assets = db.query(DataAsset).filter_by(project_id=project.id).all()
    features = db.query(Feature).filter_by(project_id=project.id).all()
    endpoints = db.query(ApiEndpoint).filter_by(project_id=project.id).all()

    # 规则1: 接口命中敏感语义但未关联敏感资产(敏感数据未挂资产)
    for ep in endpoints:
        blob = f"{ep.name or ''}{ep.path or ''}"
        if SENSITIVE_FIELD_RE.search(blob) and not (ep.sensitive_asset_uids or []):
            missing.append(
                f"漏填检测: 接口「{ep.name}」({ep.path})命中敏感数据语义但未关联敏感数据资产")

    # 规则2: 敏感字段未配置加密或脱敏
    for asset, _table, field in _sensitive_fields(assets):
        if not field.need_encrypt and not field.need_mask:
            missing.append(
                f"漏填检测: 字段「{field.field_name}」(资产「{asset.name}」)疑似敏感字段"
                "但未配置加密或脱敏")

    # 规则3: 分级疑似偏低 —— 敏感字段挂在 1级/2级 资产上
    for asset, _table, field in _sensitive_fields(assets):
        if asset.classification in LOW_LEVELS:
            missing.append(
                f"漏填检测: 资产「{asset.name}」含敏感字段「{field.field_name}」"
                f"但分级为 {asset.classification}, 疑似分级偏低")

    # 规则4: payment 类功能无账户/支付类资产
    if any("payment" in (f.categories or []) or "refund" in (f.categories or [])
           for f in features):
        if not any(ACCOUNT_ASSET_RE.search(a.name or "") for a in assets):
            missing.append("漏填检测: 存在支付/退款类功能但资产目录缺少账户/支付/交易类资产")

    # 规则5: 公网暴露接口未配置限流
    for ep in endpoints:
        if ep.public_exposed and not (ep.rate_limit or "").strip():
            missing.append(f"漏填检测: 接口「{ep.name}」公网暴露但未配置限流")

    return missing
