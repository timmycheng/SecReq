# -*- coding: utf-8 -*-
"""构建 CNNVD 编号映射库(叠加层, 不做组件匹配)。

定位说明: CNNVD 是 CVE 级的、不带包坐标, 硬拿来做组件匹配需要 CPE 映射, 精度很差。
正确用法: 抽 `CVE-ID → CNNVD-ID + 中文危害等级`, 建成小映射表, 只在展示与导出时补字段。

数据来源: CNNVD 月度 XML(约 5-8 MB/月)。官方下载通常需登录, 因此本脚本以
**本地 XML 文件/目录**为主要输入, 联网直连仅作可选能力。

用法:

    python scripts/build_cnnvd_map.py --source-dir ./cnnvd-xml
    python scripts/build_cnnvd_map.py --source-file cnnvd-2026-08.xml
    python scripts/build_cnnvd_map.py --source-dir ./xml --dry-run

产物与 vulndb.sqlite 放同一目录, 由 services/cnnvd.py 在同步时查询填充。
"""
import argparse
import os
import re
import sqlite3
import sys
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import shared.constants as C  # noqa: E402

# CNNVD 各时期 XML 标签名不统一, 这里做 tolerant 匹配
CVE_TAGS = ("cve-id", "cve_id", "cveId", "cve", "cveid")
CNNVD_TAGS = ("cnnvd-id", "cnnvd_id", "cnnvdId", "cnnvdid", "number")
SEVERITY_TAGS = ("vuln-level", "vuln_level", "vulnLevel", "severity", "level", "risk-level")
TITLE_TAGS = ("name", "title", "vuln-name", "vulnName")

CVE_RE = re.compile(r"^CVE-\d{4}-\d{4,}$", re.IGNORECASE)
CNNVD_RE = re.compile(r"^CNNVD-\d{6}-\d{4,}$", re.IGNORECASE)

SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE cnnvd_map (
    cve_id      TEXT PRIMARY KEY,
    cnnvd_id    TEXT,
    cn_severity TEXT,
    title_zh    TEXT
);
"""


def _local(tag: str) -> str:
    return tag.split("}")[-1].lower()


def _first_text(entry: ET.Element, candidates: tuple[str, ...]) -> str:
    for child in entry.iter():
        if _local(child.tag) in candidates:
            text = (child.text or "").strip()
            if text:
                return text
    return ""


def _normalize_cve(text: str) -> str:
    return text.strip().upper()


def parse_xml(path: Path) -> list[tuple[str, str, str, str]]:
    """解析单个月度 XML → [(cve_id, cnnvd_id, cn_severity, title_zh)]。"""
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        print(f"  ⚠ 解析失败, 跳过 {path.name}: {exc}")
        return []

    rows: list[tuple[str, str, str, str]] = []
    seen: set[str] = set()
    for entry in root.iter():
        if _local(entry.tag) != "entry":
            continue
        cve = _normalize_cve(_first_text(entry, CVE_TAGS))
        if not CVE_RE.match(cve) or cve in seen:
            continue
        cnnvd = _first_text(entry, CNNVD_TAGS).strip().upper()
        if not CNNVD_RE.match(cnnvd):
            cnnvd = ""
        severity = _first_text(entry, SEVERITY_TAGS)
        title = _first_text(entry, TITLE_TAGS)[:500]
        seen.add(cve)
        rows.append((cve, cnnvd, severity, title))
    return rows


def collect_sources(source_dir: Path | None, source_file: Path | None) -> list[Path]:
    files: list[Path] = []
    if source_file:
        if not source_file.is_file():
            raise SystemExit(f"文件不存在: {source_file}")
        files.append(source_file)
    if source_dir:
        if not source_dir.is_dir():
            raise SystemExit(f"目录不存在: {source_dir}")
        files.extend(sorted(source_dir.glob("*.xml")))
    if not files:
        raise SystemExit("未指定输入: 需要 --source-dir 或 --source-file")
    return files


def build(files: list[Path], out_path: Path) -> dict:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(suffix=".sqlite", dir=str(out_path.parent))
    os.close(fd)
    tmp = Path(tmp_name)

    conn = sqlite3.connect(tmp)
    conn.executescript(SCHEMA)
    total = 0
    with_cnnvd = 0
    try:
        for path in files:
            rows = parse_xml(path)
            conn.executemany(
                "INSERT OR REPLACE INTO cnnvd_map (cve_id, cnnvd_id, cn_severity, title_zh)"
                " VALUES (?,?,?,?)",
                rows,
            )
            total += len(rows)
            with_cnnvd += sum(1 for r in rows if r[1])
            print(f"  · {path.name}: {len(rows)} 条 CVE")
        meta = {
            "db_version": datetime.now(timezone.utc).strftime("%Y%m%d"),
            "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "format": "secreq-cnnvd-map/1",
            "total": str(total),
            "source_files": ",".join(p.name for p in files),
            "upstream": "CNNVD 月度安全公告 XML",
        }
        conn.executemany(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?,?)", list(meta.items())
        )
        conn.commit()
        conn.close()
    except BaseException:
        conn.close()
        tmp.unlink(missing_ok=True)
        raise

    if out_path.exists():
        out_path.unlink()
    tmp.replace(out_path)
    size_mb = out_path.stat().st_size / 1e6
    print(f"\n构建完成: {out_path}")
    print(f"  CVE 合计 {total}(其中 {with_cnnvd} 条带 CNNVD 编号), 体积 {size_mb:.2f} MB")
    return {"total": total, "with_cnnvd": with_cnnvd, "size_mb": size_mb}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="构建 CNNVD 编号映射库")
    parser.add_argument("--source-dir", default=None, help="CNNVD 月度 XML 所在目录")
    parser.add_argument("--source-file", default=None, help="单个 CNNVD XML 文件")
    parser.add_argument("--out", default=os.path.join(C.DEFAULT_DATA_DIR, C.CNNVD_FILENAME),
                        help=f"输出库路径, 默认 {os.path.join(C.DEFAULT_DATA_DIR, C.CNNVD_FILENAME)}")
    parser.add_argument("--dry-run", action="store_true", help="只报告将解析的文件, 不写库")
    args = parser.parse_args(argv)

    files = collect_sources(
        Path(args.source_dir) if args.source_dir else None,
        Path(args.source_file) if args.source_file else None,
    )
    print(f"将解析 {len(files)} 个 XML 文件:")
    for path in files:
        print(f"  · {path} ({path.stat().st_size / 1e6:.2f} MB)")

    if args.dry_run:
        print("\n--dry-run: 未执行解析与建库")
        return 0

    build(files, Path(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
