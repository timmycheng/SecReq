# -*- coding: utf-8 -*-
"""构建本地离线漏洞库(内网上线的功能阻塞项)。

数据源: OSV 官方离线包 https://osv-vulnerabilities.storage.googleapis.com/<ECO>/all.zip
离线包里每条 JSON 就是 OsvClient.normalize() 的输入形态, 因此上层规范化逻辑零改动复用,
本脚本只负责"下载 → 建索引 → 压缩存储", 换取数通道。

设计要点(基于 2026-08-30 实测):
- **zlib 存 raw JSON 收益远大于字段裁剪**(Bitnami 31%、Alpine 12%), 故默认保留完整记录;
- 按 (生态, 包名) 建索引, 查询时只解压候选记录(一个包通常几十到几百条, 开销可忽略);
- 生态名带版本后缀(如 `Alpine:v3.2`、`Debian:12`), 需归一化到内部 code;
- 一条漏洞可影响多个包坐标 → 按 (生态, 包名) 展开多行, 保证按名可查。

用法(联网区执行, 产物摆渡进内网):

    python scripts/build_vuln_db.py                       # 默认推荐配置(见 DEFAULT_ECOSYSTEMS)
    python scripts/build_vuln_db.py --ecosystems npm,Maven
    python scripts/build_vuln_db.py --source-dir ./osv-zips   # 用已下载的 zip, 不联网
    python scripts/build_vuln_db.py --dry-run             # 只报告将构建什么
    python scripts/build_vuln_db.py --list-ecosystems     # 列出 OSV 全部可用生态

默认配置(目标环境: 银河麒麟宿主 + Bitnami 中间件 + Alpine 基础库):
    语言层 npm/Maven/PyPI/Go/NuGet/crates.io + OS 层 Bitnami/Alpine + 宿主层 openEuler
不导入: Ubuntu(623MB, 性价比极低)、GIT(176.7MB, commit 级对版本匹配无用)。
"""
import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
import zlib
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import shared.constants as C  # noqa: E402

OSV_BUCKET = "https://osv-vulnerabilities.storage.googleapis.com"
ECOSYSTEMS_TXT = f"{OSV_BUCKET}/ecosystems.txt"

#: 推荐配置(见模块 docstring 的目标环境与体积实测)
DEFAULT_ECOSYSTEMS = [
    "npm", "Maven", "PyPI", "Go", "NuGet", "crates.io",
    "Bitnami", "Alpine", "openEuler",
]

#: 已知体积陷阱, 显式请求时给出警告但不阻止
VOLUME_WARNINGS = {
    "Ubuntu": "623.0MB(是 Debian 的 8.6 倍), 除非目标环境确为 Ubuntu, 否则不建议导入",
    "GIT": "176.7MB 且为 commit 级匹配, 对版本号匹配无用",
}

CHUNK = 1 << 20  # 1MB
REPORT_EVERY = 20000


# ── 生态名归一化 ────────────────────────────────────────────────
def ecosystem_code(raw: str) -> str:
    """OSV 生态名 → 内部 code。

    'Alpine:v3.2' → 'alpine';  'Debian:12' → 'debian';  'crates.io' → 'crates';
    'Red Hat' → 'redhat';  'openEuler' → 'openeuler'。
    """
    base = str(raw or "").split(":")[0].strip()
    base = C.OSV_ECOSYSTEM_ALIASES.get(base, base)
    return base.lower()


def internal_code(osv_name: str) -> str:
    """构建参数(OSV 名字) → 内部 code, 用于校验该生态是否被支持。"""
    return ecosystem_code(osv_name)


# ── 下载 ────────────────────────────────────────────────────────
def fetch_ecosystems(timeout: float) -> list[str]:
    with urllib.request.urlopen(ECOSYSTEMS_TXT, timeout=timeout) as resp:
        text = resp.read().decode("utf-8")
    return [line.strip() for line in text.splitlines() if line.strip()]


def download(ecosystem: str, dest_dir: Path, timeout: float) -> Path:
    """下载单个生态的 all.zip; 已存在则复用(幂等)。"""
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / f"{ecosystem.replace('/', '_')}.zip"
    if target.is_file() and target.stat().st_size > 0:
        print(f"  · 复用已下载: {target.name} ({target.stat().st_size / 1e6:.1f} MB)")
        return target
    url = f"{OSV_BUCKET}/{urllib.parse.quote(ecosystem)}/all.zip"  # noqa: E501
    print(f"  · 下载 {url}")
    tmp = target.with_suffix(".zip.part")
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp, open(tmp, "wb") as fh:
            while True:
                block = resp.read(CHUNK)
                if not block:
                    break
                fh.write(block)
    except (urllib.error.URLError, TimeoutError) as exc:
        tmp.unlink(missing_ok=True)
        raise SystemExit(f"下载失败 {ecosystem}: {exc}") from exc
    tmp.replace(target)
    print(f"  · 完成 {target.name} ({target.stat().st_size / 1e6:.1f} MB)")
    return target


# ── 建库 ────────────────────────────────────────────────────────
SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE vulns (
    id        INTEGER PRIMARY KEY,
    vuln_id   TEXT NOT NULL,
    ecosystem TEXT NOT NULL,
    name      TEXT NOT NULL,
    tail      TEXT NOT NULL,
    raw       BLOB NOT NULL
);
CREATE INDEX idx_vulns_eco_name ON vulns(ecosystem, name);
CREATE INDEX idx_vulns_eco_tail ON vulns(ecosystem, tail);
"""


def _tail(name: str) -> str:
    """Maven 坐标 `org.apache:log4j-core` 的尾段, 便于用户只填 artifact 时也能命中。"""
    return name.rsplit(":", 1)[-1].lower()


def _packages(vuln: dict) -> list[tuple[str, str]]:
    """(生态 code, 包名小写) 去重列表; 无 affected 时回退到顶层 package。"""
    found: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    entries = vuln.get("affected") or []
    if not entries and vuln.get("package"):
        entries = [{"package": vuln["package"]}]
    for entry in entries:
        pkg = entry.get("package") or {}
        eco = ecosystem_code(pkg.get("ecosystem"))
        name = str(pkg.get("name") or "").strip().lower()
        if not eco or not name:
            continue
        if (eco, name) in seen:
            continue
        seen.add((eco, name))
        found.append((eco, name))
    return found


def build(zips: list[tuple[str, Path]], out_path: Path, slim: bool, compress: bool) -> dict:
    """建库; 返回统计信息。写入临时文件后原子替换, 保证幂等。"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_name = tempfile.mkstemp(suffix=".sqlite", dir=str(out_path.parent))
    os.close(tmp_fd)
    tmp_path = Path(tmp_name)

    conn = sqlite3.connect(tmp_path)
    conn.executescript(SCHEMA)

    stats: dict[str, int] = {}
    total = 0
    unsupported: set[str] = set()
    started = time.time()

    try:
        for ecosystem, zip_path in zips:
            eco_count = 0
            with zipfile.ZipFile(zip_path) as zf:
                members = [n for n in zf.namelist() if n.lower().endswith(".json")]
                for idx, member in enumerate(members, 1):
                    try:
                        vuln = json.loads(zf.read(member))
                    except (ValueError, KeyError, zlib.error):
                        continue
                    if not isinstance(vuln, dict):
                        continue
                    packages = _packages(vuln)
                    if not packages:
                        continue
                    if slim:
                        vuln.pop("details", None)
                        refs = vuln.get("references")
                        if isinstance(refs, list):
                            vuln["references"] = refs[:3]
                    raw = json.dumps(vuln, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                    blob = zlib.compress(raw, 9) if compress else raw
                    vid = str(vuln.get("id") or member)
                    for eco, name in packages:
                        if eco not in C.VULN_ECOSYSTEMS:
                            unsupported.add(eco)
                            continue
                        conn.execute(
                            "INSERT INTO vulns (vuln_id, ecosystem, name, tail, raw) VALUES (?,?,?,?,?)",
                            (vid, eco, name, _tail(name), blob),
                        )
                        eco_count += 1
                    if idx % REPORT_EVERY == 0:
                        print(f"    … {ecosystem}: 已处理 {idx}/{len(members)}")
            stats[ecosystem] = eco_count
            total += eco_count
            print(f"  · {ecosystem}: {eco_count} 条(去重后坐标行)")

        built_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        meta = {
            "db_version": datetime.now(timezone.utc).strftime("%Y%m%d"),
            "built_at": built_at,
            "ecosystems": ",".join(sorted({ecosystem_code(e) for e, _ in zips})),
            "source_ecosystems": ",".join(e for e, _ in zips),
            "total": str(total),
            "format": "secreq-vulndb/1",
            "compressed": "1" if compress else "0",
            "slim": "1" if slim else "0",
            "per_ecosystem": json.dumps(stats, ensure_ascii=False),
            "builder": "scripts/build_vuln_db.py",
            "upstream": OSV_BUCKET,
        }
        conn.executemany(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?,?)", list(meta.items())
        )
        conn.commit()
        conn.execute("VACUUM")
        conn.close()
    except BaseException:
        conn.close()
        tmp_path.unlink(missing_ok=True)
        raise

    if out_path.exists():
        out_path.unlink()
    shutil.move(str(tmp_path), str(out_path))

    size_mb = out_path.stat().st_size / 1e6
    print(f"\n构建完成: {out_path}")
    print(f"  记录(坐标行)合计 {total}, 耗时 {time.time() - started:.0f}s, 体积 {size_mb:.1f} MB")
    if unsupported:
        print(f"  ⚠ 已跳过未注册生态: {', '.join(sorted(unsupported))}"
              f"(如需支持请在 shared/constants.py 的 VULN_ECOSYSTEMS 注册)")
    return {"total": total, "size_mb": size_mb, "per_ecosystem": stats}


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


# ── 入口 ────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="构建 SecReq 本地离线漏洞库")
    parser.add_argument("--ecosystems", default=",".join(DEFAULT_ECOSYSTEMS),
                        help="逗号分隔的 OSV 生态名, 默认推荐配置")
    parser.add_argument("--out", default=os.path.join(C.DEFAULT_DATA_DIR, "vulndb.sqlite"),
                        help="输出库路径, 默认 ./data/vulndb.sqlite")
    parser.add_argument("--cache-dir", default="./.vulndb-cache",
                        help="下载缓存目录, 默认 ./.vulndb-cache")
    parser.add_argument("--source-dir", default=None,
                        help="从该目录读取已有的 <生态>.zip, 不联网(内网/离线构建用)")
    parser.add_argument("--slim", action="store_true",
                        help="裁剪 details 与 references(默认关闭: zlib 存 raw 收益更大)")
    parser.add_argument("--no-compress", action="store_true", help="不压缩 raw JSON")
    parser.add_argument("--timeout", type=float, default=120.0, help="下载超时秒数")
    parser.add_argument("--dry-run", action="store_true", help="只报告将构建的内容, 不写库")
    parser.add_argument("--list-ecosystems", action="store_true", help="列出 OSV 全部生态并退出")
    args = parser.parse_args(argv)

    if args.list_ecosystems:
        for name in fetch_ecosystems(args.timeout):
            code = ecosystem_code(name)
            known = "✓" if code in C.VULN_ECOSYSTEMS else " "
            print(f"  [{known}] {name}  -> {code}")
        return 0

    ecosystems = [e.strip() for e in args.ecosystems.split(",") if e.strip()]
    if not ecosystems:
        raise SystemExit("--ecosystems 为空")

    print("将构建以下生态:")
    for name in ecosystems:
        warning = VOLUME_WARNINGS.get(name)
        suffix = f"  ⚠ {warning}" if warning else ""
        unknown = "" if ecosystem_code(name) in C.VULN_ECOSYSTEMS else "  ⚠ 未注册生态, 入库时会被跳过"
        print(f"  · {name} -> {ecosystem_code(name)}{suffix}{unknown}")

    if args.dry_run:
        print("\n--dry-run: 未执行下载与建库")
        return 0

    zips: list[tuple[str, Path]] = []
    if args.source_dir:
        src = Path(args.source_dir)
        for name in ecosystems:
            candidate = src / f"{name.replace('/', '_')}.zip"
            if not candidate.is_file():
                raise SystemExit(f"--source-dir 模式下缺少文件: {candidate}")
            zips.append((name, candidate))
    else:
        cache = Path(args.cache_dir)
        for name in ecosystems:
            zips.append((name, download(name, cache, args.timeout)))

    out_path = Path(args.out)
    build(zips, out_path, args.slim, not args.no_compress)

    # 校验和写 sidecar 文件, 不写回库内 —— 往库里 INSERT 会改变文件本身,
    # 库里记录的校验和一旦写入就已过期。格式与 sha256sum 兼容, 便于用系统命令复核。
    digest = sha256_of(out_path)
    checksum_path = out_path.with_name(out_path.name + ".sha256")
    checksum_path.write_text(f"{digest}  {out_path.name}\n", encoding="utf-8")
    print(f"  SHA256: {digest}  -> {checksum_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
