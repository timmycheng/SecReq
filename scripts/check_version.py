# -*- coding: utf-8 -*-
"""发版前置一致性校验: tag ↔ main.py 版本 ↔ pyproject.toml 版本 ↔ CHANGELOG 章节。

用法: python scripts/check_version.py v2.2.1
release.yml 在测试阶段调用, 失败即中止 —— 把版本漂移拦在构建镜像之前;
本地打 tag 前也可手动跑一次。纯标准库实现。
"""
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    if len(sys.argv) != 2:
        print("用法: python scripts/check_version.py vX.Y.Z")
        return 2
    tag = sys.argv[1].strip()
    matched = re.fullmatch(r"v(\d+\.\d+\.\d+)", tag)
    if matched is None:
        print(f"::error::tag 格式非法: {tag!r}(应为 vX.Y.Z, SemVer 三段)")
        return 1
    version = matched.group(1)
    errors = []

    # main.py 的 FastAPI version 是 API 文档与 /api 元数据对外展示的版本号
    main_py = (ROOT / "main.py").read_text(encoding="utf-8")
    app_version = re.search(r'version\s*=\s*"(\d+\.\d+\.\d+)"', main_py)
    if app_version is None:
        errors.append('main.py 中未找到 FastAPI version="..." 字段')
    elif app_version.group(1) != version:
        errors.append(
            f"main.py 的 version={app_version.group(1)!r} 与 tag {tag} 不一致, 发版前请同步"
        )

    pyproject = ROOT / "pyproject.toml"
    if pyproject.is_file():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            pyproject_version = data.get("project", {}).get("version")
        except (tomllib.TOMLDecodeError, OSError) as exc:
            errors.append(f"pyproject.toml 解析失败: {exc}")
        else:
            if pyproject_version != version:
                errors.append(
                    f"pyproject.toml 的 version={pyproject_version!r} 与 tag {tag} 不一致, 发版前请同步"
                )

    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    if not re.search(rf"^## \[{re.escape(version)}\]", changelog, re.MULTILINE):
        errors.append(f"CHANGELOG.md 中未找到 [{version}] 章节, 请先补充该版本变更再打 tag")

    for err in errors:
        print(f"::error::{err}")
    if errors:
        return 1
    print(f"版本一致性校验通过: {tag} = main.py version = pyproject.toml version = CHANGELOG 章节")
    return 0


if __name__ == "__main__":
    sys.exit(main())
