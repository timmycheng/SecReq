# -*- coding: utf-8 -*-
"""按生态的版本归一化器。

OS 覆盖的技术难点不在数据源, 而在"发行版"这个维度 —— 同一个 MySQL 8.0.32:

    Debian   8.0.32-1~deb12u1
    RHEL     8.0.32-1.el9
    Bitnami  8.0.32-debian-11-r0
    openEuler 8.0.32-1.oe2203

版本号串完全不同。用户只会填 `8.0.32`, 不归一化就一条也匹配不上。

每个归一化器提供两件事:
  canonical()  剥离发行版后缀, 得到可与用户填写值比较的上游版本串
  key()        宽松比较键(与 services.osv._version_key 同风格, 但感知生态后缀)
"""
import re

_NUM_RE = re.compile(r"\d+")
_LETTERS_RE = re.compile(r"[A-Za-z]+")

# 预发布标记: 命中则排在同号稳定版之前(与 osv._version_key 保持一致)
_PRERELEASE_RE = re.compile(r"(?i)(alpha|beta|rc|dev|pre|snapshot|-)")


def numeric_key(text: str) -> tuple:
    """宽松比较键: (数字段补齐 4 位, 预发布标记, 字母段序列, 预发布段尾序)。

    字母段是必需的 —— OpenSSL 这类版本用末尾字母做发布序号(1.0.2g / 1.0.2h),
    只比数字会把 1.0.2g 和 1.0.2h 判成同一个版本, 直接漏掉 CVE-2016-2105。
    预发布(#21): 命中 alpha/beta/rc/- 等标记时, 标记之后的文本不参与数字段/字母段
    提取 —— 否则 2.15.0-rc1 的 "1" 会被当成第 4 位版本号, 永远排在同号稳定版之后,
    窗口 [2.13.0, 2.15.0) 内的 2.15.0-rc1 被误判"已修复"而漏报; 标记位使预发布排前,
    预发布段内的数字/字母单独作尾序(2.15.0-rc1 < 2.15.0-rc2 < 2.15.0)。
    """
    text = str(text or "")
    m = _PRERELEASE_RE.search(text)
    release, pre = (text[:m.start()], text[m.start():]) if m else (text, "")
    nums = [int(n) for n in _NUM_RE.findall(release)]
    while len(nums) < 4:
        nums.append(0)
    letters = tuple(s.lower() for s in _LETTERS_RE.findall(release))
    prerelease = 0 if m else 1
    pre_tail = (tuple(s.lower() for s in _LETTERS_RE.findall(pre)),
                tuple(int(n) for n in _NUM_RE.findall(pre)))
    return (tuple(nums[:4]), prerelease, letters, pre_tail)


class Normalizer:
    """通用归一化器: 按正则表剥离发行版后缀, 再走数字键比较。

    剥离采取"保守策略" —— 只有当剥离后仍含数字时才认可结果,
    否则保留原串(避免把 `1.0` 这类短版本剥成空串)。
    """

    #: 按顺序尝试的后缀剥离模式(匹配尾部)
    strip_patterns: tuple[str, ...] = ()

    def canonical(self, version: str) -> str:
        text = str(version or "").strip()
        for pattern in self.strip_patterns:
            stripped = re.sub(pattern + r"$", "", text, flags=re.IGNORECASE)
            # 顺序叠加而非命中即返回: Debian 的 8.0.32-1~deb12u1 要先剥 ~debNuN 再剥 -N
            if stripped != text and _NUM_RE.search(stripped):
                text = stripped
        return text

    def key(self, version: str) -> tuple:
        return numeric_key(self.canonical(version))


class SemverNormalizer(Normalizer):
    """npm / PyPI / Go / NuGet / crates / Bitnami: 标准 semver, 零适配。

    只剥 Bitnami 的镜像渠道后缀(8.0.32-debian-11-r0), **不碰 semver 预发布段**:
    把 2.15.0-RC1 规整成 2.15.0 会让"已修复"的版本被误判为已修复, 属于漏报。
    """

    strip_patterns = (
        r"-(?:debian|rhel|ol|ubi|alpine|centos)[a-z0-9.\-_]*$",
        r"-r\d+$",
    )


class AlpineNormalizer(Normalizer):
    """Alpine: `1.0.2h-r0` 的 `-rN` 是包修订号, 剥离后才是上游版本。"""

    strip_patterns = (r"-r\d+$", r"[-+][0-9A-Za-z.\-_]+$")


class DebianNormalizer(Normalizer):
    """Debian/Ubuntu: `1.18.0-6+deb11u2` / `8.0.32-1~deb12u1`。

    最后一个 `-` 之后是 debian revision, 与上游漏洞窗口无关。
    """

    strip_patterns = (
        r"[-+~](?:deb|ubuntu)\d+[a-z0-9.+~]*$",
        r"[-+]\d+(?:\.[a-z0-9.]+)?(?:\+[a-z0-9.+~]+)?$",
    )


class RhelNormalizer(Normalizer):
    """RHEL 系(Red Hat / Rocky / AlmaLinux): `1.18.0-1.el9`、`1.2.3-1.module_el9+2`。"""

    strip_patterns = (
        r"[-+]\d+(?:\.[a-z0-9.]+)?(?:\.(?:el|fc|module[_.]el)\d+[a-z0-9.+_]*)?$",
        r"[-+](?:el|fc)\d+[a-z0-9.+_]*$",
    )


class OpenEulerNormalizer(Normalizer):
    """openEuler(麒麟同源代理): `1.18.0-1.oe2203`、`2.1.0-3.oe1.aarch64`。"""

    strip_patterns = (
        r"[-+]\d+(?:\.[a-z0-9.]+)?(?:\.oe\d+[a-z0-9._]*)?$",
        r"[-+]\.oe\d+[a-z0-9._]*$",
    )


#: 生态 code → 归一化器实例
NORMALIZERS: dict[str, Normalizer] = {
    "npm": SemverNormalizer(),
    "maven": SemverNormalizer(),
    "pypi": SemverNormalizer(),
    "go": SemverNormalizer(),
    "nuget": SemverNormalizer(),
    "crates": SemverNormalizer(),
    "bitnami": SemverNormalizer(),
    "alpine": AlpineNormalizer(),
    "openeuler": OpenEulerNormalizer(),
    "redhat": RhelNormalizer(),
    "rocky": RhelNormalizer(),
    "almalinux": RhelNormalizer(),
    "debian": DebianNormalizer(),
}

#: 未知生态的兜底
_DEFAULT = Normalizer()


def get(ecosystem: str | None) -> Normalizer:
    return NORMALIZERS.get(str(ecosystem or "").lower(), _DEFAULT)
