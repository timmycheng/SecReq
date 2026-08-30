# -*- coding: utf-8 -*-
"""CNNVD 编号映射(叠加层, 不是主数据源)。

定位说明: CNNVD 是 CVE 级的、不带包坐标, 硬拿来做组件匹配需要 CPE 映射, 精度很差。
正确用法: 从 CNNVD 月度 XML 抽 `CVE-ID → CNNVD-ID + 中文危害等级`, 建成小映射表,
只在**展示与导出**时补合规字段(银行合规通报常要求国产编号)。

库文件由 scripts/build_cnnvd_map.py 产出, 缺库时全部查询返回空 —— 不影响主流程。
"""
import logging
import sqlite3
from pathlib import Path

from services.vuln_source import cnnvd_path

logger = logging.getLogger(__name__)

_CNNVD_RE = None


def db_exists(path: str | None = None) -> bool:
    return Path(path or cnnvd_path()).is_file()


def _connect(path: str) -> sqlite3.Connection | None:
    if not Path(path).is_file():
        return None
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        logger.warning("CNNVD 映射库打开失败(%s): %s", path, exc)
        return None
    conn.row_factory = sqlite3.Row
    return conn


def lookup(cve_ids: list[str], path: str | None = None) -> dict[str, dict]:
    """批量查 CVE → CNNVD 映射; 库缺失返回空字典(调用方静默跳过)。"""
    ids = [str(c).strip().upper() for c in cve_ids if c and str(c).strip()]
    if not ids:
        return {}
    conn = _connect(path or cnnvd_path())
    if conn is None:
        return {}
    try:
        placeholders = ",".join("?" for _ in ids)
        rows = conn.execute(
            f"SELECT cve_id, cnnvd_id, cn_severity, title_zh FROM cnnvd_map WHERE cve_id IN ({placeholders})",
            ids,
        ).fetchall()
        return {
            r["cve_id"]: {
                "cnnvd_id": r["cnnvd_id"],
                "cn_severity": r["cn_severity"],
                "title_zh": r["title_zh"],
            }
            for r in rows
        }
    except sqlite3.Error as exc:
        logger.warning("CNNVD 映射查询失败: %s", exc)
        return {}
    finally:
        conn.close()


def stats(path: str | None = None) -> dict:
    """映射库概况(管理端展示)。"""
    path = path or cnnvd_path()
    conn = _connect(path)
    if conn is None:
        return {"available": False, "path": path, "total": 0}
    try:
        row = conn.execute(
            "SELECT value FROM meta WHERE key = 'db_version'"
        ).fetchone()
        total = conn.execute("SELECT COUNT(*) AS n FROM cnnvd_map").fetchone()["n"]
        return {
            "available": True,
            "path": path,
            "db_version": row["value"] if row else None,
            "total": total,
        }
    except sqlite3.Error as exc:
        return {"available": False, "path": path, "total": 0, "reason": str(exc)}
    finally:
        conn.close()
