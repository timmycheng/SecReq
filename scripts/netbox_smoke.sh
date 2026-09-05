#!/usr/bin/env bash
# SecReq <-> NetBox 联动冒烟: 对着 scripts/netbox_dev.sh 拉起的真实 NetBox,
# 走一遍 配置回填 -> 状态探测 -> 系统清单导入 -> 台账系统推送回填 -> 设备代理。
#
# 前置: NetBox 测试环境已就绪(scripts/netbox_dev.sh up), SecReq 后端已运行
#       且存在安全角色账号(默认 sec_admin)。
#
# 用法:
#   SECREQ_URL=http://127.0.0.1:8000 \
#   SECREQ_USER=sec_admin SECREQ_PASSWORD=<密码> \
#   scripts/netbox_smoke.sh
# 可选环境变量:
#   NETBOX_URL(http://localhost:8080)  NETBOX_TOKEN(默认取 netbox/api-token)
#   NETBOX_SYSTEM_SLUG(system)
set -euo pipefail

SECREQ_URL="${SECREQ_URL:-http://127.0.0.1:8000}"
SECREQ_USER="${SECREQ_USER:-sec_admin}"
SECREQ_PASSWORD="${SECREQ_PASSWORD:?请设置 SECREQ_PASSWORD(安全角色账号密码)}"
NETBOX_URL="${NETBOX_URL:-http://localhost:8080}"
NETBOX_SYSTEM_SLUG="${NETBOX_SYSTEM_SLUG:-system}"
NETBOX_TOKEN="${NETBOX_TOKEN:-$(cat "${NETBOX_DIR:-netbox}/api-token" 2>/dev/null || echo "")}"

[ -n "$NETBOX_TOKEN" ] || { echo "未找到 NetBox 令牌, 请先 scripts/netbox_dev.sh up" >&2; exit 1; }

py() {
  if command -v python3 >/dev/null 2>&1; then python3 "$@"
  elif command -v python >/dev/null 2>&1; then python "$@"
  else uv run --no-project python "$@"; fi
}

sec_api() { # sec_api <method> <path> [json-body]
  local method="$1" path="$2" body="${3:-}"
  if [ -n "$body" ]; then
    curl -sS -X "$method" -H "Authorization: Bearer $SECREQ_TOKEN" \
      -H "Content-Type: application/json" -d "$body" "$SECREQ_URL$path"
  else
    curl -sS -H "Authorization: Bearer $SECREQ_TOKEN" "$SECREQ_URL$path"
  fi
}

echo "[1] 登录 SecReq($SECREQ_USER)"
SECREQ_TOKEN=$(curl -sS -X POST -H "Content-Type: application/json" \
  -d "{\"username\":\"$SECREQ_USER\",\"password\":\"$SECREQ_PASSWORD\"}" \
  "$SECREQ_URL/api/auth/login" | py -c 'import sys,json; print(json.load(sys.stdin)["token"])')
echo "    ok"

echo "[2] 回填 NetBox 配置(系统管理口径, token 只写不回显; owner 映射 owner_name 适配 NetBox 4.5+)"
sec_api PUT /api/admin/netbox-config \
  "{\"base_url\":\"$NETBOX_URL\",\"token\":\"$NETBOX_TOKEN\",\"system_slug\":\"$NETBOX_SYSTEM_SLUG\",\"field_map\":{\"name\":\"name\",\"code\":\"code\",\"owner\":\"owner_name\"}}" >/dev/null
echo "    ok"

echo "[3] 状态探测 /api/netbox/status"
sec_api GET /api/netbox/status | py -c 'import sys,json; d=json.load(sys.stdin); assert d.get("configured"), d; print("    configured, base_url =", d.get("base_url"))'

echo "[4] 系统清单导入 /api/netbox/systems"
sec_api GET /api/netbox/systems | py -c 'import sys,json; d=json.load(sys.stdin); print("    NetBox 侧系统数:", d.get("count")); assert d.get("count", 0) >= 1, "应为样例数据预留至少 1 条"'

echo "[5] 设备代理 /api/netbox/devices"
sec_api GET "/api/netbox/devices?limit=1" | py -c 'import sys,json; d=json.load(sys.stdin); print("    设备数:", d.get("count"))'

echo "[6] 台账系统推送写回(创建 -> 推送 -> 校验 netbox_object_id 回填)"
# 用例名全 ASCII: Windows 宿主 shell(Git Bash)发中文 payload 会被按本地码页编码, 稳妥起见避免
UNIQ="smoke-sys-$(date +%s)"
SYS_ID=$(sec_api POST /api/systems "{\"name\":\"$UNIQ\",\"owner_name\":\"smoke\"}" \
  | py -c 'import sys,json; print(json.load(sys.stdin)["id"])')
PUSH=$(sec_api POST /api/netbox/systems "{\"system_id\":$SYS_ID,\"name\":\"$UNIQ\"}")
echo "$PUSH" | py -c 'import sys,json; d=json.load(sys.stdin); assert d.get("netbox_object_id"), d; print("    回填 netbox_object_id =", d["netbox_object_id"])'

echo
echo "联动冒烟全部通过"
