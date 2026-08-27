# -*- coding: utf-8 -*-
"""OSV.dev 漏洞查询服务。

DESIGN.md 模块3:
- 构造 purl 后调用 https://api.osv.dev/v1/query (POST {package:{purl}});
- 结果规范化为 VulnerabilityRecord 落库(CVE编号/CVSS分数与等级/影响范围/修复版本/简述);
- 查询结果按组件缓存 24h(SbomComponent.last_osv_query_at), 避免重复请求;
- 网络失败时降级: 保留既有记录、标记 failed, 不阻塞其他流程。

测试通过注入 httpx.MockTransport 替换网络层(见 tests/test_osv.py)。
"""
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy.orm import Session

import shared.constants as C
from models import SbomComponent, VulnerabilityRecord

logger = logging.getLogger(__name__)

OSV_BASE_URL = "https://api.osv.dev"
CACHE_TTL = timedelta(hours=24)

# CVSS 分数 → severity 档位(database_specific.severity 缺失时兜底判定)
CVSS_CRITICAL_MIN = 9.0
CVSS_HIGH_MIN = 7.0
CVSS_MEDIUM_MIN = 4.0

# GHSA/NVD 档位词别名(如 MODERATE)
SEVERITY_ALIASES = {"moderate": "medium"}

SUMMARY_MAX_LEN = 500


class OsvSyncResult:
    """一次漏洞同步的汇总, 供脚本/接口展示。

    updated  本次实际重新查询并写入记录的组件名
    cached   缓存未过期、跳过网络的组件名
    failed   OSV 查询失败(网络/HTTP错误)的组件名 → 展示"漏洞查询暂不可用"
    """

    def __init__(self) -> None:
        self.updated: list[str] = []
        self.cached: list[str] = []
        self.failed: list[str] = []

    @property
    def degraded(self) -> bool:
        return bool(self.failed)

    def summary_text(self) -> str:
        parts = [f"已更新{len(self.updated)}", f"缓存命中{len(self.cached)}"]
        if self.failed:
            parts.append(f"查询失败{len(self.failed)}({', '.join(self.failed)})")
        return "OSV查询: " + ", ".join(parts)


@dataclass
class NormalizedVuln:
    """单条 OSV 漏洞的规范化结果。"""

    cve_id: str
    severity: str  # critical/high/medium/low/unknown
    cvss_score: float | None
    affected_range: str | None
    fix_version: str | None
    summary: str | None


class OsvClient:
    """OSV.dev HTTP 客户端; transport 参数供测试注入 MockTransport。"""

    def __init__(self, timeout: float = 10.0, base_url: str = OSV_BASE_URL, transport=None):
        self._client = httpx.Client(
            base_url=base_url, timeout=timeout, transport=transport,
            headers={"User-Agent": "SecReq/1.0 (security baseline generator)"},
        )

    def close(self) -> None:
        self._client.close()

    def query_purl(self, purl: str) -> list[dict] | None:
        """查询单个 purl, 返回原始 vuln 字典列表; 网络异常/HTTP错误返回 None(降级)。"""
        try:
            resp = self._client.post("/v1/query", json={"package": {"purl": purl}})
            resp.raise_for_status()
            data = resp.json()
            vulns = data.get("vulns") or [] if isinstance(data, dict) else []
            return vulns if isinstance(vulns, list) else []
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("OSV 查询失败(%s): %s", purl, exc)
            return None

    # ────────────────────────── 规范化 ──────────────────────────

    @staticmethod
    def normalize(
        vuln: dict, target_purl: str | None = None, target_version: str | None = None
    ) -> NormalizedVuln:
        """把 OSV 原始字典转成 VulnerabilityRecord 所需字段。

        target_purl/target_version 用于在同一漏洞的多个包坐标中锁定本组件,
        并给出"包含当前版本"窗口对应的修复版本。
        """
        cve_id = next(
            (a for a in vuln.get("aliases") or [] if str(a).upper().startswith("CVE-")),
            None,
        ) or vuln.get("id", "")

        score = _extract_cvss_score(vuln)
        severity = _resolve_severity(vuln, score)
        windows = _extract_ranges(vuln, target_purl)
        fix_version = _pick_fix_version(windows, target_version)
        summary = (vuln.get("summary") or vuln.get("details") or "").strip()
        if len(summary) > SUMMARY_MAX_LEN:
            summary = summary[: SUMMARY_MAX_LEN - 1] + "…"

        return NormalizedVuln(
            cve_id=cve_id,
            severity=severity,
            cvss_score=score,
            affected_range=_render_range(windows),
            fix_version=fix_version,
            summary=summary or None,
        )


def _extract_cvss_score(vuln: dict) -> float | None:
    """从 severity 数组/CVSS 向量中尽力取数值分数。"""
    for item in vuln.get("severity") or []:
        text = str(item.get("score", ""))
        # CVSS_SCORE 型直接给数字; CVSS_V3 型给向量串, 取其中的基础分不可行则跳过
        try:
            return float(text)
        except ValueError:
            continue
    legacy = vuln.get("score")
    if isinstance(legacy, (int, float)):
        return float(legacy)
    if isinstance(legacy, str):
        try:
            return float(legacy)
        except ValueError:
            pass
    return None


def _score_to_severity(score: float | None) -> str:
    if score is None:
        return "unknown"
    if score >= CVSS_CRITICAL_MIN:
        return "critical"
    if score >= CVSS_HIGH_MIN:
        return "high"
    if score >= CVSS_MEDIUM_MIN:
        return "medium"
    return "low"


def _resolve_severity(vuln: dict, score: float | None) -> str:
    """优先 database_specific.severity(GHSA 维护), 兜底按 CVSS 分数划档。"""
    tag = str((vuln.get("database_specific") or {}).get("severity", "")).lower()
    tag = SEVERITY_ALIASES.get(tag, tag)
    if tag in C.SEVERITY_ORDER and tag != "unknown":
        return tag
    return _score_to_severity(score)


_VERSION_NUM_RE = re.compile(r"\d+")


def _version_key(text: str | None) -> tuple:
    """宽松版本比较键: 提取数字段补齐到4位, 预发布标记(beta/rc/-)排在同号稳定版之前。"""
    text = str(text or "")
    nums = [int(n) for n in _VERSION_NUM_RE.findall(text)]
    while len(nums) < 4:
        nums.append(0)
    prerelease = 1 if re.search(r"(?i)(beta|alpha|rc|-)", text) else 0
    return tuple(nums[:4]) + (prerelease,)


def _parse_purl(purl: str | None) -> tuple[str | None, str | None]:
    """解析 pkg:<type>/<namespace>/<name>@<version> 的 (namespace, name)。"""
    if not purl:
        return None, None
    body = purl.split("://", 1)[-1]
    body = body.split("#", 1)[0].split("?", 1)[0].split("@", 1)[0]  # 去 version/qualifier
    parts = body.split("/")
    if len(parts) >= 3:  # 带命名空间: type/ns/name
        return parts[1], "/".join(parts[2:])
    if len(parts) == 2:
        return None, parts[1]
    return None, None


def _matched_affected_entries(vuln: dict, target_purl: str | None) -> list[dict]:
    """筛选与目标组件同坐标的 affected 条目。

    OSV 同一漏洞常列出多个派生包坐标(guicedee/pax-logging 等分支),
    若不加过滤会污染影响范围与修复版本。匹配优先级:
    精确 purl(忽略版本) > 'namespace:name' 全限定名 > 裸名 > 兜底全部。
    """
    entries = vuln.get("affected") or []
    ns, name = _parse_purl(target_purl)
    if not name:
        return entries

    def pkg_text(entry: dict) -> tuple[str, str]:
        pkg = entry.get("package") or {}
        return str(pkg.get("purl") or ""), str(pkg.get("name") or "")

    exact, qualified, bare = [], [], []
    for entry in entries:
        epurl, ename = pkg_text(entry)
        if epurl and target_purl and epurl.split("@", 1)[0] == target_purl.split("@", 1)[0]:
            exact.append(entry)
        elif ns and ename == f"{ns}:{name}":
            qualified.append(entry)
        elif not ns and ename == name:
            bare.append(entry)
    return exact or qualified or bare or entries


def _extract_ranges(vuln: dict, target_purl: str | None = None) -> list[dict]:
    """抽取受影响窗口(introduced 起点 / fixed 终点), 仅统计与目标组件同坐标的条目。

    OSV 事件为单键映射形态, 如 [{"introduced":"2.0"},{"fixed":"2.15.0"},
    {"introduced":"2.15.1"},{"fixed":"2.17.0"}] → 切成两个窗口。
    若出现"未闭合又开新窗口"(意味着该起点之后全域受影响),
    记录开放式窗口并终止本 range 解析; 无终点的 [introduced 0] 也是开放式窗口。
    """
    windows: list[dict] = []
    for affected in _matched_affected_entries(vuln, target_purl):
        for rg in affected.get("ranges") or []:
            open_since: str | None = None
            closed = True

            for event in rg.get("events") or []:
                for kind, raw_value in event.items():
                    value = str(raw_value)
                    if kind == "introduced":
                        if open_since is not None:
                            # 前一窗口未闭合即出现新起点 → 该组件全域受影响
                            windows.append({"introduced": open_since})
                            open_since = None
                            closed = False
                            break
                        open_since = value
                        closed = True
                    elif kind in ("fixed", "last_affected"):
                        if open_since is None:
                            continue
                        windows.append({"introduced": open_since, kind: value})
                        open_since = None
                if not closed:
                    break

            if open_since is not None:  # 循环自然结束仍有未闭合起点 → 开放式窗口
                windows.append({"introduced": open_since})
    return windows


def _pick_fix_version(windows: list[dict], target_version: str | None = None) -> str | None:
    """从窗口中选出对本组件最有指导意义的修复版本。

    优先取"包含目标版本"的窗口端点(如 2.14.1 ∈ [2.13.0, 2.15.0) → 升级到 2.15.0);
    多线并存时兜底取数值最高的修复版(排除低版本分支的干扰)。
    """
    with_fix = [w["fixed"] for w in windows if w.get("fixed")]
    if not with_fix:
        return None
    if target_version:
        try:
            vk = _version_key(target_version)
            for w in windows:
                if (
                    w.get("fixed")
                    and _version_key(w["introduced"]) <= vk < _version_key(w["fixed"])
                ):
                    return w["fixed"]
        except TypeError:  # 宽松键异常时走兜底
            pass
    return max(with_fix, key=_version_key)


def _render_range(windows: list[dict]) -> str | None:
    """影响范围渲染为人读形态: '≥2.0 且 <2.15.0'; 多段用 '；' 分隔。"""
    if not windows:
        return None
    segments = []
    for w in windows[:3]:
        seg = f"≥{w['introduced']}"
        if w.get("fixed"):
            seg += f" 且 <{w['fixed']}"
        elif w.get("last_affected"):
            seg += f" 且 ≤{w['last_affected']}"
        segments.append(seg)
    return "；".join(segments)


def sync_vulnerabilities(
    session: Session,
    components: list[SbomComponent],
    client: OsvClient | None = None,
    force: bool = False,
    now: datetime | None = None,
) -> tuple[list[VulnerabilityRecord], OsvSyncResult]:
    """对组件清单执行漏洞同步(24h 缓存 + 失败降级), 返回(全部记录, 同步汇总)。

    - 缓存有效(last_osv_query_at 在 TTL 内)且未 force → 直接沿用已落库记录;
    - 无 purl 组件跳过(ensure_purl 已在 SBOM 阶段补齐, 此处仅防御);
    - 单个组件查询失败只记入 failed 并保留旧记录, 不抛出、不阻塞其余组件。
    """
    from services.sbom import ensure_purl  # 局部导入避免循环依赖

    own_client = client is None
    client = client or OsvClient()
    now = now or datetime.now(timezone.utc)
    result = OsvSyncResult()

    for comp in components:
        fresh_until = (
            comp.last_osv_query_at.replace(tzinfo=timezone.utc)
            if comp.last_osv_query_at else None
        )
        if not force and fresh_until is not None and now - fresh_until < CACHE_TTL:
            result.cached.append(comp.name)
            continue

        purl = ensure_purl(comp)

        raw_vulns = client.query_purl(purl)
        if raw_vulns is None:
            # 降级: 不清空旧记录, 下次运行重试
            result.failed.append(comp.name)
            continue

        records = _replace_component_vulns(session, comp, raw_vulns)
        comp.last_osv_query_at = now
        result.updated.append(comp.name)
        session.add_all(records)

    session.commit()
    # 重新读取本次涉及组件的全部漏洞记录(含缓存沿用与刚写入的), 按严重度→CVE 排序
    component_ids = [c.id for c in components]
    all_records = (
        session.query(VulnerabilityRecord)
        .filter(VulnerabilityRecord.component_id.in_(component_ids))
        .all()
        if component_ids else []
    )
    all_records.sort(
        key=lambda v: (C.SEVERITY_ORDER.get(v.severity, 9), v.component_id, v.cve_id)
    )
    if own_client:
        client.close()
    return all_records, result


def _replace_component_vulns(
    session: Session, comp: SbomComponent, raw_vulns: list[dict]
) -> list[VulnerabilityRecord]:
    """重建该组件的漏洞记录: 清空旧集合(cascade 删除孤儿), 按 cve_id 去重写入。

    注意: 必须在清空后立即 flush, 否则 commit 时单元OfWork按"先插入后删除"
    执行, 新记录会撞上 (component_id, cve_id) 唯一约束。
    """
    comp.vulnerabilities = []
    session.flush()

    deduped: dict[str, NormalizedVuln] = {}
    for raw in raw_vulns:
        nv = OsvClient.normalize(raw, target_purl=comp.purl, target_version=comp.version)
        key = nv.cve_id or id(nv)
        existing = deduped.get(key)
        if existing is None or C.SEVERITY_ORDER.get(nv.severity, 9) < C.SEVERITY_ORDER.get(existing.severity, 9):
            deduped[key] = nv

    records = [
        VulnerabilityRecord(
            component=comp,  # 走关系构造, 反向引用同步维护 comp.vulnerabilities 集合
            cve_id=nv.cve_id,
            severity=nv.severity,
            cvss_score=nv.cvss_score,
            affected_range=nv.affected_range,
            fix_version=nv.fix_version,
            summary=nv.summary,
        )
        for nv in deduped.values()
    ]
    records.sort(key=lambda v: (C.SEVERITY_ORDER.get(v.severity, 9), v.cve_id))
    return records
