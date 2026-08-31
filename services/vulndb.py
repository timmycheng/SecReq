# -*- coding: utf-8 -*-
"""本地离线漏洞库数据源(v2.2.0 内网上线的功能阻塞项)。

为什么必须本地化: 平台最终部署在银行内网, 无互联网出口, OSV.dev 在线查询不可用。

关键设计 —— **复用在线通道的全部规范化逻辑, 只换取数通道**:
离线包里每条 JSON 就是 OsvClient.normalize() 的输入形态, 因此
`normalize / _extract_ranges / _matched_affected_entries` 之类的纯函数全部零改动复用,
本模块只负责"按包名取候选 → 解压 → 判断哪些记录真的命中当前版本"。

三种"查不到"必须分开(合并会制造虚假的安全感):
    not_covered   本地库未导入该生态 / 该生态本就不在 OSV 覆盖范围(如源码编译、K8s)
    undetermined  信息不足无法判定(未指定生态与分发渠道)
    not_found     已覆盖且已匹配, 确实没有命中
"""
import json
import logging
import sqlite3
import zlib
from pathlib import Path

import shared.constants as C
from services.vuln_match import canonical, in_versions, version_key
from services.vuln_source import (
    SOURCE_LOCAL, SOURCE_ONLINE, VulnQuery, VulnQueryResult, VulnSourceUnavailable,
    vulndb_path,
)

logger = logging.getLogger(__name__)

#: 版本串不含发行版修订号时的保守判定说明(宁可报疑似, 不可静默显示"无漏洞")
AMBIGUOUS_REVISION_NOTE = (
    "版本未包含发行版修订号(如 Alpine 的 -rN), 无法区分是否已含修复, "
    "按疑似命中处理; 请核对实际包版本"
)
#: versions-only 记录(只有 versions 枚举、无 ranges)命中的保守说明(#28)
VERSIONS_ONLY_NOTE = "该版本出现在公告受影响版本列表中, 记录未提供影响范围, 请人工核对修复版本"
FUZZY_NOTE = "未指定生态, 已在全部已导入生态中做跨渠道模糊匹配, 结果需人工确认"
KYLIN_NOTE = C.KYLIN_PROXY_NOTE


class VulnDb:
    """本地漏洞库只读访问封装。

    库结构(由 scripts/build_vuln_db.py 产出):
        meta(key, value)                    库版本/构建时间/生态清单/记录数/SHA256
        vulns(id, ecosystem, name, tail, raw)  raw = zlib 压缩的原始 OSV JSON
                                            tail = 包名去掉命名空间后的尾段(Maven 坐标)
    """

    def __init__(self, path: str | None = None):
        self.path = str(path or vulndb_path())
        self._meta: dict[str, str] | None = None

    # ── 可用性 ──────────────────────────────────────────
    def exists(self) -> bool:
        """库文件存在且非空(CI 未拉到基线库时会放 0 字节占位文件)。"""
        path = Path(self.path)
        return path.is_file() and path.stat().st_size > 0

    def connect(self) -> sqlite3.Connection:
        if not self.exists():
            raise VulnSourceUnavailable(f"本地漏洞库文件不存在: {self.path}")
        try:
            conn = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        except sqlite3.Error as exc:
            raise VulnSourceUnavailable(f"本地漏洞库无法打开({self.path}): {exc}") from exc
        conn.row_factory = sqlite3.Row
        return conn

    # ── 元信息 ──────────────────────────────────────────
    def meta(self) -> dict[str, str]:
        if self._meta is not None:
            return self._meta
        with self.connect() as conn:
            rows = conn.execute("SELECT key, value FROM meta").fetchall()
        self._meta = {r["key"]: r["value"] for r in rows}
        return self._meta

    def reload_meta(self) -> dict[str, str]:
        """导入新库后调用, 清掉元信息缓存。"""
        self._meta = None
        return self.meta()

    @property
    def version(self) -> str:
        """库指纹: 库版本 + 记录数。用于缓存判定 —— 库一换就触发全量重算。"""
        meta = self.meta()
        return f"{meta.get('db_version', 'unknown')}:{meta.get('total', '0')}"

    @property
    def ecosystems(self) -> list[str]:
        raw = self.meta().get("ecosystems", "")
        return [e for e in raw.split(",") if e]

    @property
    def imported_ecosystems(self) -> set[str]:
        """实际入库的生态(可能为库声明生态的子集, 以库内数据为准)。"""
        try:
            with self.connect() as conn:
                rows = conn.execute("SELECT DISTINCT ecosystem FROM vulns").fetchall()
        except (VulnSourceUnavailable, sqlite3.Error):
            return set()
        return {r["ecosystem"] for r in rows}

    @property
    def covered_ecosystems(self) -> set[str]:
        """**真正覆盖**的生态 = 构建时声明导入 ∩ 实际入库。

        不能只看"库里有没有该生态的记录": OSV 的多生态公告会在一个生态的 zip 里
        夹带其他生态的包坐标(实测 Maven/all.zip 里带了 92 条 npm、189 条 NuGet 记录)。
        若按"有记录即覆盖", 只导了 Maven 的库也会把 npm 组件报成"未发现已知漏洞" ——
        等于用 92 条记录冒充 22 万条, 是最危险的那种虚假安全感。
        """
        imported = self.imported_ecosystems
        declared = {e.strip().lower() for e in self.ecosystems if e.strip()}
        if not declared:  # 无声明信息(如手工构造的库)时退化为"入库即覆盖"
            return imported
        return declared & imported

    # ── 查询 ────────────────────────────────────────────
    def candidates(self, ecosystem: str, name: str) -> list[dict]:
        """按 (生态, 包名) 取候选记录; 只解压候选, 开销可忽略。"""
        key = (name or "").strip().lower()
        if not key or not ecosystem:
            return []
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT raw FROM vulns WHERE ecosystem = ? AND (name = ? OR tail = ?)",
                (ecosystem, key, key),
            ).fetchall()
        out = []
        for row in rows:
            try:
                out.append(json.loads(zlib.decompress(row["raw"]).decode("utf-8")))
            except (zlib.error, ValueError, UnicodeDecodeError) as exc:
                logger.warning("漏洞库记录解压失败(ecosystem=%s, name=%s): %s", ecosystem, key, exc)
        return out


def _match_purl(q: VulnQuery, ecosystem: str) -> str:
    """按生态构造用于同坐标筛选的 purl(不带版本, 交给范围比较)。"""
    ptype = C.ECOSYSTEM_PURL_TYPE.get(ecosystem, "generic")
    return f"pkg:{ptype}/{q.name}@{q.version}"


def _candidate_ecosystems(q: VulnQuery, covered: set[str]) -> tuple[list[str], str | None]:
    """按生态 → 分发渠道 → 跨生态模糊的顺序, 决定查询哪些生态。

    参数 covered 是"真正覆盖"的生态集合(声明 ∩ 入库), 见 VulnDb.covered_ecosystems。

    返回 (生态序列, 说明文案)。序列为空表示"本地库未覆盖该生态"。
    """
    if q.ecosystem and q.ecosystem in C.VULN_ECOSYSTEMS:
        if q.ecosystem == "other":
            return [], "该生态未纳入本地漏洞库覆盖范围(如源码编译、K8s), 需人工评估或由 SCA 补充"
        if q.ecosystem not in covered:
            return [], f"本地漏洞库未导入{C.VULN_ECOSYSTEMS[q.ecosystem]}生态数据"
        return [q.ecosystem], None

    if q.distro and q.distro != "other":
        if q.distro == "source":
            return [], "源码编译/自研组件不在 OSV 覆盖范围, 需人工评估或由 SCA 补充"
        mapped = [e for e in C.DISTRO_ECOSYSTEMS.get(q.distro, []) if e in covered]
        if not mapped:
            label = C.SBOM_DISTROS.get(q.distro, q.distro)
            return [], f"本地漏洞库未导入 {label} 对应的生态数据"
        note = KYLIN_NOTE if q.distro == "kylin" else None
        return mapped, note

    # 未指定生态/分发渠道 → 跨生态模糊匹配(宁可给带标注的疑似结果)
    fuzzy = [e for e in C.FUZZY_ECOSYSTEM_ORDER if e in covered]
    return fuzzy, FUZZY_NOTE if fuzzy else None


def _windows_including(vuln: dict, purl: str, ecosystem: str, version: str) -> tuple[list[dict], str | None]:
    """筛出"包含目标版本"的窗口; 返回 (窗口列表, 待确认说明)。

    两条判定路径:
      1. 记录带 versions 枚举时先确认该版本在生态中真实存在(比范围比较可靠);
      2. 再用生态感知的比较键判断落在哪个 [introduced, fixed) 窗口;
      3. 记录只有 versions 枚举、无 ranges 时, 枚举命中即按伪窗口返回(带说明)。

    边界: 用户填 `1.0.2h` 而修复版是 `1.0.2h-r0` 时, 两者归一化后相等,
    严格比大小会判成"未受影响" —— 但用户很可能只是没写发行版修订号。
    这里保守判为**疑似命中**并给出说明, 不静默放过。
    """
    from services.osv import _extract_ranges, _matched_affected_entries

    entries = _matched_affected_entries(vuln, purl)
    windows = _extract_ranges(vuln, purl)

    enumerated: list[str] = []
    for entry in entries:
        enumerated.extend(str(v) for v in (entry.get("versions") or []))
    # npm 等生态把 versions 放在顶层
    if not enumerated:
        enumerated = [str(v) for v in (vuln.get("versions") or [])]

    key_of = lambda v: version_key(ecosystem, v)  # noqa: E731
    target = key_of(version)

    inside: list[dict] = []
    for w in windows:
        if target < key_of(w.get("introduced", "0")):
            continue
        if w.get("fixed") and target >= key_of(w["fixed"]):
            continue
        if w.get("last_affected") and target > key_of(w["last_affected"]):
            continue
        inside.append(w)
    if inside:
        return inside, None

    # 疑似命中: 版本号与某个 fixed 端点在剥离修订号后相同
    for w in windows:
        if w.get("fixed") and canonical(ecosystem, w["fixed"]) == canonical(ecosystem, version):
            if enumerated and not in_versions(ecosystem, version, enumerated):
                continue
            return [w], AMBIGUOUS_REVISION_NOTE

    # versions-only 记录(#28): 只有受影响版本枚举、无 ranges, 范围比较永远不中。
    # 保守判为命中并说明"未提供范围", 不让该形态结构性漏报(修复版本自然缺省)
    if not windows and enumerated and in_versions(ecosystem, version, enumerated):
        return [{"introduced": version}], VERSIONS_ONLY_NOTE
    return [], None


class OsvLocalSource:
    """本地离线漏洞库数据源(内网默认)。"""

    name = SOURCE_LOCAL

    def __init__(self, db: VulnDb | None = None):
        self.db = db or VulnDb()

    def available(self) -> tuple[bool, str]:
        if not self.db.exists():
            return False, (
                f"本地漏洞库文件不存在: {self.db.path}。"
                "内网部署需先由 scripts/build_vuln_db.py 生成并挂载到该路径"
            )
        try:
            total = self.db.meta().get("total", "0")
        except (VulnSourceUnavailable, sqlite3.Error) as exc:
            return False, f"本地漏洞库不可用: {exc}"
        if not str(total).isdigit() or int(total) <= 0:
            return False, f"本地漏洞库为空或损坏: {self.db.path}"
        return True, f"本地漏洞库 {self.db.meta().get('db_version', '未知版本')}, {total} 条记录"

    def query(self, q: VulnQuery) -> VulnQueryResult:
        if not q.version:
            return VulnQueryResult(status="undetermined", note="组件未填版本号, 无法匹配漏洞")

        covered = self.db.covered_ecosystems
        ecosystems, note = _candidate_ecosystems(q, covered)
        if not ecosystems:
            return VulnQueryResult(
                status="not_covered",
                note=note or "本地漏洞库未包含该组件所属生态的数据",
            )

        from services.osv import MATCHED_WINDOWS_KEY

        matched: list[dict] = []
        notes: list[str] = []
        for ecosystem in ecosystems:
            # 逐生态构造 purl: 同一组件名在不同生态的类型不同,
            # 按 ecosystems[0] 构造一次会让其余生态的同坐标筛选全不中(#29)
            purl = q.purl or _match_purl(q, ecosystem)
            for vuln in self.db.candidates(ecosystem, q.name):
                windows, ambiguous = _windows_including(vuln, purl, ecosystem, q.version)
                if not windows:
                    continue
                # 把预筛窗口挂到原始记录上, 供 osv.normalize 直接沿用,
                # 避免把同一漏洞下不相关的窗口也渲染进"影响范围"
                vuln[MATCHED_WINDOWS_KEY] = windows
                matched.append(vuln)
                if ambiguous:
                    notes.append(ambiguous)
            if matched:
                break  # 精确生态优先命中即止, 避免跨渠道重复
        if notes:
            note = "; ".join(sorted(set(notes)))
            return VulnQueryResult(vulns=matched, status="hit", note=f"{note}；{KYLIN_NOTE}" if q.distro == "kylin" else note)

        if not matched:
            return VulnQueryResult(status="not_found", note=note)
        return VulnQueryResult(
            vulns=matched, status="hit",
            note=note or (KYLIN_NOTE if q.distro == "kylin" else None),
        )


class OsvOnlineSource:
    """在线 OSV.dev 数据源(开发/演示环境; 内网不可用, 仅作对照)。"""

    name = SOURCE_ONLINE

    def __init__(self, client=None):
        self._client = client

    def available(self) -> tuple[bool, str]:
        return True, "在线 OSV.dev(需互联网, 内网环境不可用)"

    def query(self, q: VulnQuery) -> VulnQueryResult:
        from services.osv import OsvClient

        client = self._client or OsvClient()
        own = self._client is None
        try:
            purl = q.purl or _match_purl(q, q.ecosystem or "npm")
            vulns = client.query_purl(purl)
        finally:
            if own:
                client.close()
        if vulns is None:
            raise VulnSourceUnavailable(f"OSV 在线查询失败: {q.name}")
        return VulnQueryResult(
            vulns=vulns, status="hit" if vulns else "not_found",
        )
