# -*- coding: utf-8 -*-
"""漏洞数据源抽象(v2.2.0): 协议 + 工厂 + SCA 预留位。

设计原则 —— 现在把"接缝"留好, 后面对接 SCA 时:
    新建 sca_source.py + 工厂注册 + 切配置
协议、表结构、pipeline、规则引擎、前端、导出全部不动。

为什么现在就抽:
    SCA 可对接性未知, 在结论出来前实现是浪费; 但接缝成本几乎为零, 不做才是浪费。

数据源选择走环境变量, 支持链式降级:

    SECREQ_VULN_SOURCE=local            仅本地库(内网默认)
    SECREQ_VULN_SOURCE=sca,local        优先 SCA, 不可用时降级本地库
    SECREQ_VULN_SOURCE=online           开发/演示环境直连 OSV(需互联网)

`sca` 目前只占位: available() 返回 (False, 未接入原因), 绝不静默失败。
"""
import logging
import os
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import shared.constants as C

logger = logging.getLogger(__name__)

#: 数据源标识(落 VulnerabilityRecord.source)
SOURCE_LOCAL = "osv_local"
SOURCE_ONLINE = "osv_online"
SOURCE_SCA = "sca"

ENV_VULN_SOURCE = "SECREQ_VULN_SOURCE"
ENV_VULNDB_PATH = "SECREQ_VULNDB_PATH"
ENV_CNNVD_PATH = "SECREQ_CNNVD_PATH"
ENV_DATA_DIR = "SECREQ_DATA_DIR"


def data_dir() -> str:
    """漏洞库所在目录(环境变量可覆盖, 内网挂载更新只需换文件)。"""
    return os.environ.get(ENV_DATA_DIR) or C.DEFAULT_DATA_DIR


def vulndb_path() -> str:
    return os.environ.get(ENV_VULNDB_PATH) or os.path.join(data_dir(), C.VULNDB_FILENAME)


def cnnvd_path() -> str:
    return os.environ.get(ENV_CNNVD_PATH) or os.path.join(data_dir(), C.CNNVD_FILENAME)


class VulnSourceUnavailable(Exception):
    """数据源不可用。必须由调用方显式处理(标注语义 + 记日志), 不得静默吞掉。"""


@dataclass
class VulnQuery:
    """一次查询的输入: 组件坐标 + 生态维度。"""

    name: str
    version: str
    purl: str | None = None
    ecosystem: str | None = None
    distro: str | None = None


@dataclass
class VulnQueryResult:
    """查询结果: 原始 OSV 形态字典 + 结果语义。

    status 四种取值不可合并(合并会制造虚假安全感):
        hit           命中已知漏洞
        not_found     已覆盖该生态, 但未匹配到漏洞
        undetermined  信息不足无法判定(未指定生态/分发渠道)
        not_covered   本地库未包含该生态数据
    """

    vulns: list[dict] = field(default_factory=list)
    status: str = "not_found"
    note: str | None = None

    @property
    def hit(self) -> bool:
        return self.status == "hit" and bool(self.vulns)


@runtime_checkable
class VulnSource(Protocol):
    """漏洞数据源协议。实现必须可在无网络环境下工作(online 除外)。"""

    #: 数据源标识, 落 VulnerabilityRecord.source
    name: str

    def available(self) -> tuple[bool, str]:
        """(是否可用, 不可用原因)。不可用时工厂会尝试链中的下一个。"""
        ...

    def query(self, q: VulnQuery) -> VulnQueryResult:
        """查询单个组件; 数据源故障抛 VulnSourceUnavailable。"""
        ...


class ScaPlatformSource:
    """行内 SCA 平台数据源 —— **预留位, v2.2.0 未实现**。

    对接时机取决于 SCA 核查结论(是否提供 REST API、是否支持按组件坐标查询;
    前两条任一为否即无法对接)。实现时只需:
        1. 本类实现 query(), 把 SCA 返回结构映射为 OSV 形态字典;
        2. 在 get_vuln_source() 的 _REGISTRY 中它已注册;
        3. 配置切到 sca。
    """

    name = SOURCE_SCA

    def available(self) -> tuple[bool, str]:
        return False, (
            "SCA 数据源尚未接入(v2.2.0 仅预留接口)。"
            "确认 SCA 提供 REST API 且支持按组件坐标查询后, 实现 ScaPlatformSource.query() 即可启用"
        )

    def query(self, q: VulnQuery) -> VulnQueryResult:  # pragma: no cover - 预留
        raise VulnSourceUnavailable(self.available()[1])


_REGISTRY: dict[str, type] = {
    SOURCE_LOCAL: None,   # 延迟填充, 避免 vulndb 导入 sqlalchemy 时的循环依赖
    SOURCE_ONLINE: None,
    "sca": ScaPlatformSource,
}


def _local_cls():
    from services.vulndb import OsvLocalSource  # 局部导入: vulndb 依赖本模块的常量
    return OsvLocalSource


def _online_cls():
    from services.vulndb import OsvOnlineSource
    return OsvOnlineSource


def _build(code: str):
    if code == "local":
        return _local_cls()()
    if code == "online":
        return _online_cls()()
    if code == "sca":
        return ScaPlatformSource()
    raise VulnSourceUnavailable(f"未知的漏洞数据源配置: {code}")


def configured_chain() -> list[str]:
    """配置的数据源链(逗号分隔), 默认 local。"""
    raw = os.environ.get(ENV_VULN_SOURCE, "local")
    return [part.strip() for part in raw.split(",") if part.strip()] or ["local"]


def get_vuln_source() -> tuple[VulnSource, list[str]]:
    """按配置链取第一个可用的数据源。

    返回 (数据源, 被跳过的不可用源及其原因)。链上全部不可用时抛
    VulnSourceUnavailable —— 由调用方显式处理, 不静默降级。
    """
    skipped: list[str] = []
    for code in configured_chain():
        try:
            source = _build(code)
        except VulnSourceUnavailable as exc:
            skipped.append(f"{code}: {exc}")
            continue
        ok, reason = source.available()
        if ok:
            if skipped:
                logger.warning("漏洞数据源降级: 跳过 %s, 使用 %s", "; ".join(skipped), source.name)
            return source, skipped
        skipped.append(f"{code}: {reason}")
    raise VulnSourceUnavailable("无可用漏洞数据源: " + "; ".join(skipped))


def describe_sources() -> list[dict]:
    """全部数据源的可用性快照(管理端「漏洞库」页展示)。"""
    rows = []
    for code in ("local", "online", "sca"):
        try:
            source = _build(code)
            ok, reason = source.available()
            rows.append({
                "code": code,
                "name": source.name,
                "available": ok,
                "reason": reason or None,
                "active": False,
            })
        except VulnSourceUnavailable as exc:
            rows.append({
                "code": code, "name": code, "available": False,
                "reason": str(exc), "active": False,
            })
    try:
        active, _ = get_vuln_source()
        for row in rows:
            row["active"] = row["name"] == active.name
    except VulnSourceUnavailable as exc:
        logger.error("无可用漏洞数据源: %s", exc)
    return rows
