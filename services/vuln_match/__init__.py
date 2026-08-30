# -*- coding: utf-8 -*-
"""版本归一化与版本命中判定(v2.2.0 离线漏洞库)。

对外只暴露三个函数, 上层(services/vulndb.py)不需要知道生态细节:

    canonical(ecosystem, version)          剥离发行版后缀得到上游版本串
    version_key(ecosystem, version)        宽松比较键
    in_versions(ecosystem, target, enum)   在 OSV 记录的 versions 枚举里做归一化后精确匹配

匹配策略(按可靠性排序):
  1. versions 枚举精确匹配 —— 记录自带完整版本列表时最可靠, 用户填 `1.0.2h`
     能命中枚举里的 `1.0.2h-r0`;
  2. 范围比较 —— 枚举缺失时退化, 用归一化后的数字键判断落在哪个 [introduced, fixed) 窗口。
"""
from .normalizers import NORMALIZERS, Normalizer, get, numeric_key

__all__ = [
    "NORMALIZERS", "Normalizer", "canonical", "get", "in_versions",
    "numeric_key", "version_key",
]


def canonical(ecosystem: str | None, version: str | None) -> str:
    """剥离发行版后缀; 空值返回空串。"""
    return get(ecosystem).canonical(str(version or ""))


def version_key(ecosystem: str | None, version: str | None) -> tuple:
    """生态感知的宽松比较键(可直接用于 <、<= 比较)。"""
    return get(ecosystem).key(str(version or ""))


def in_versions(ecosystem: str | None, target: str | None, enumerated: list) -> bool:
    """目标版本是否出现在记录的 versions 枚举中(归一化后比较)。

    优先走枚举: 发行版生态的版本串带各种后缀, 范围比较容易跨渠道误判,
    而枚举是"该生态真实存在过的版本号", 精确得多。
    """
    if not target or not enumerated:
        return False
    want = canonical(ecosystem, target).lower()
    if not want:
        return False
    norm = get(ecosystem)
    for item in enumerated:
        if str(item or "").strip().lower() == want:
            return True
        if norm.canonical(str(item or "")).lower() == want:
            return True
    return False
