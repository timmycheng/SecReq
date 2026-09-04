# -*- coding: utf-8 -*-
"""NetBox 互通客户端(#152): 资产与系统台账主数据源的旁路增强。

- 目标 NetBox 4.x, REST 认证为 Authorization: Token <token> 请求头;
- 系统清单来自官方 custom-objects 插件, 实例端点 /api/plugins/custom-objects/<slug>/;
- 异常两类, 显式故障不静默(仿 vuln_source 语义):
    NetboxUnavailable — 连接失败/超时/5xx, reason 为可读中文归因;
    NetboxApiError    — 4xx, 透传 NetBox 的 detail。

测试通过注入 httpx.MockTransport 替换网络层(见 tests/test_netbox.py)。
"""
import logging

import httpx

logger = logging.getLogger(__name__)

#: 列表分页上限(单页), 防止一次拉爆
MAX_PAGE_LIMIT = 100


class NetboxUnavailable(Exception):
    """网络层故障: 连接失败/超时/5xx。str(exc) 即可读中文归因。"""


class NetboxApiError(Exception):
    """NetBox 业务层 4xx: message 含状态码与 NetBox 透传 detail。"""


def _trim(obj: dict, *paths) -> dict:
    """按 (key, 子键) 路径从 NetBox 嵌套对象裁剪字段, 如 ("site", "name")。"""
    out: dict = {}
    for key, sub in paths:
        value = obj.get(key)
        if isinstance(value, dict) and sub is not None:
            value = value.get(sub)
        out[key] = value
    return out


class NetboxClient:
    """NetBox HTTP 客户端; transport 参数供测试注入 MockTransport。"""

    def __init__(self, base_url: str, token: str, timeout: float = 10.0, transport=None):
        self._timeout = timeout
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"), timeout=timeout, transport=transport,
            headers={
                "Authorization": f"Token {token}",
                "Accept": "application/json",
                "User-Agent": "SecReq/1.0 (security baseline generator)",
            },
        )

    def close(self) -> None:
        self._client.close()

    # ────────────────────────── 底层请求 ──────────────────────────

    def _request(self, method: str, path: str, params: dict | None = None,
                 json_body: dict | None = None) -> dict:
        """单次请求 + 错误归因映射; 成功返回 JSON 字典。

        - 连接失败/超时/5xx → NetboxUnavailable(可读中文, 仿 LLM 连接测试文案);
        - 4xx → NetboxApiError(detail 尽力透传 NetBox 返回体)。
        """
        try:
            resp = self._client.request(method, path, params=params, json=json_body)
        except httpx.ConnectError as exc:
            raise NetboxUnavailable("地址不可达(连接失败), 请检查 NetBox 地址与网络") from exc
        except httpx.TimeoutException as exc:
            raise NetboxUnavailable(f"请求超时({self._timeout:g}s), NetBox 无响应或网络不通") from exc
        except httpx.HTTPError as exc:
            raise NetboxUnavailable(f"请求失败: {exc.__class__.__name__}") from exc
        if resp.status_code >= 500:
            raise NetboxUnavailable(f"NetBox 服务异常({resp.status_code}), 请稍后重试")
        if resp.status_code >= 400:
            detail = ""
            try:
                body = resp.json()
                detail = body.get("detail") if isinstance(body, dict) else ""
            except ValueError:
                detail = resp.text[:120]
            raise NetboxApiError(f"NetBox 返回 {resp.status_code}: {detail or '请求被拒绝'}")
        if resp.status_code == 204 or not resp.content:
            return {}
        try:
            data = resp.json()
        except ValueError as exc:
            raise NetboxUnavailable("NetBox 返回非 JSON 响应") from exc
        return data if isinstance(data, dict) else {"results": data}

    def _list(self, path: str, keyword: str | None, limit: int,
              offset: int) -> dict:
        """标准 NetBox 列表分页: q= 关键字 + limit/offset, limit 封顶。"""
        return self._request("GET", path, params={
            "q": keyword or None,
            "limit": min(max(limit, 1), MAX_PAGE_LIMIT),
            "offset": max(offset, 0),
        })

    @staticmethod
    def _results(data: dict) -> list[dict]:
        rows = data.get("results")
        return rows if isinstance(rows, list) else []

    # ────────────────────────── 只读查询 ──────────────────────────

    def get_status(self) -> dict:
        """GET /api/status — 连接测试与版本探测。"""
        return self._request("GET", "/api/status")

    def list_devices(self, keyword: str | None = None, limit: int = 25,
                     offset: int = 0) -> dict:
        data = self._list("/api/dcim/devices/", keyword, limit, offset)
        data["results"] = [
            _trim(d, ("id", None), ("name", None), ("primary_ip", "address"),
                  ("site", "name"), ("role", "name"), ("device_type", "model"),
                  ("status", "value"), ("url", None))
            for d in self._results(data)
        ]
        return data

    def list_virtual_machines(self, keyword: str | None = None, limit: int = 25,
                              offset: int = 0) -> dict:
        data = self._list("/api/virtualization/virtual-machines/", keyword, limit, offset)
        data["results"] = [
            _trim(v, ("id", None), ("name", None), ("primary_ip", "address"),
                  ("site", "name"), ("role", "name"), ("platform", "name"),
                  ("status", "value"), ("url", None))
            for v in self._results(data)
        ]
        return data

    def list_ip_addresses(self, keyword: str | None = None, limit: int = 25,
                          offset: int = 0) -> dict:
        data = self._list("/api/ipam/ip-addresses/", keyword, limit, offset)
        data["results"] = [
            _trim(ip, ("id", None), ("address", None), ("dns_name", None),
                  ("status", "value"), ("url", None))
            for ip in self._results(data)
        ]
        return data

    def list_sites(self, limit: int = 100) -> list[dict]:
        data = self._list("/api/dcim/sites/", None, limit, 0)
        return [_trim(s, ("id", None), ("name", None), ("slug", None))
                for s in self._results(data)]

    def list_device_roles(self, limit: int = 100) -> list[dict]:
        data = self._list("/api/dcim/roles/", None, limit, 0)
        return [_trim(r, ("id", None), ("name", None), ("slug", None))
                for r in self._results(data)]

    def list_device_types(self, limit: int = 100) -> list[dict]:
        data = self._list("/api/dcim/device-types/", None, limit, 0)
        return [_trim(t, ("id", None), ("model", None), ("slug", None))
                for t in self._results(data)]

    def list_system_objects(self, slug: str, keyword: str | None = None,
                            limit: int = 25, offset: int = 0) -> dict:
        """custom-objects 插件系统清单: /api/plugins/custom-objects/<slug>/。"""
        return self._list(f"/api/plugins/custom-objects/{slug}/", keyword, limit, offset)

    def get_system_object_type(self, slug: str) -> dict:
        """custom-objects 类型定义(字段映射对照用): object-types/<slug>/。"""
        return self._request("GET", f"/api/plugins/custom-objects/object-types/{slug}/")

    # ────────────────────────── 写回 ──────────────────────────

    def create_device(self, payload: dict) -> dict:
        """建设备(NetBox 4.x 角色字段为 role); 4xx 由 _request 转 NetboxApiError。"""
        return self._request("POST", "/api/dcim/devices/", json_body=payload)

    def create_ip_address(self, payload: dict) -> dict:
        return self._request("POST", "/api/ipam/ip-addresses/", json_body=payload)

    def create_system_object(self, slug: str, payload: dict) -> dict:
        return self._request(
            "POST", f"/api/plugins/custom-objects/{slug}/", json_body=payload)
