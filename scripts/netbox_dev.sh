#!/usr/bin/env bash
# NetBox 联动测试环境一键拉起(对应 SecReq #152/#153/#154 互通契约, 见 docs/netbox-dev.md)。
#
# 用法:
#   scripts/netbox_dev.sh up      # 首次/日常拉起(幂等: 已存在的对象自动跳过)
#   scripts/netbox_dev.sh down    # 停止并移除容器(数据卷保留)
#   scripts/netbox_dev.sh info    # 打印地址/令牌/接入配置
# 常用环境变量:
#   NETBOX_PORT=8080                       NetBox 对外端口
#   NETBOX_SUPERUSER_PASSWORD=...          NetBox admin 密码(默认 secreq-admin)
#   NETBOX_SYSTEM_SLUG=system              custom-objects 类型 slug
#   NETBOX_DIR=./netbox                    实体目录(gitignored)
#
# 拓扑: netbox/ 下克隆 netbox-docker, 以官方 netbox-custom-objects 插件提供
# /api/plugins/custom-objects/<slug>/ 系统清单端点(SecReq services/netbox.py 消费的契约)。
set -euo pipefail

NETBOX_DIR="${NETBOX_DIR:-netbox}"
REPO="$NETBOX_DIR/netbox-docker"
PORT="${NETBOX_PORT:-8080}"
SLUG="${NETBOX_SYSTEM_SLUG:-system}"
SU_PASSWORD="${NETBOX_SUPERUSER_PASSWORD:-secreq-admin}"
TOKEN_FILE="$NETBOX_DIR/api-token"
REPO_URL="https://github.com/netbox-community/netbox-docker.git"
BASE_URL="http://localhost:$PORT"

# ── docker 探测(PATH 优先, 回退 Docker Desktop 默认安装) ──
if command -v docker >/dev/null 2>&1; then
  DOCKER="docker"
elif [ -x "/c/Program Files/Docker/Docker/resources/bin/docker.exe" ]; then
  DOCKER="/c/Program Files/Docker/Docker/resources/bin/docker.exe"
else
  echo "未找到 docker, 请安装 Docker Desktop 或将其加入 PATH" >&2
  exit 1
fi

dc() { (cd "$REPO" && "$DOCKER" compose "$@"); }

# ── JSON 解析辅助: python3/python/uv 依次兜底 ──
py() {
  if command -v python3 >/dev/null 2>&1; then python3 "$@"
  elif command -v python >/dev/null 2>&1; then python "$@"
  else uv run --no-project python "$@"; fi
}

api() { # api <method> <path> [json-body]
  local method="$1" path="$2" body="${3:-}"
  if [ -n "$body" ]; then
    curl -sS -X "$method" -H "Authorization: Token $TOKEN" -H "Content-Type: application/json" \
      -d "$body" "$BASE_URL$path"
  else
    curl -sS -X "$method" -H "Authorization: Token $TOKEN" "$BASE_URL$path"
  fi
}

wait_netbox() {
  local code
  for _ in $(seq 1 60); do
    code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE_URL/api/status" || true)
    if [ "$code" = "200" ]; then return 0; fi
    sleep 5
  done
  echo "NetBox 未就绪($BASE_URL), 请查看: (cd $REPO && docker compose logs netbox)" >&2
  return 1
}

cmd="${1:-up}"
case "$cmd" in
  down)
    (cd "$REPO" 2>/dev/null && "$DOCKER" compose down) || echo "(环境未创建)"
    exit 0 ;;
  info)
    echo "NetBox:   $BASE_URL (admin 密码: $SU_PASSWORD)"
    echo "系统清单: $BASE_URL/api/plugins/custom-objects/$SLUG/"
    echo "API 令牌: $(cat "$TOKEN_FILE" 2>/dev/null || echo '(尚未生成, 先执行 up)')"
    echo "SecReq 接入(base_url=$BASE_URL):"
    echo "  PUT /api/admin/netbox-config {\"base_url\":\"$BASE_URL\",\"token\":\"<令牌>\",\"system_slug\":\"$SLUG\"}"
    echo "  或环境变量 SECREQ_NETBOX_URL=$BASE_URL SECREQ_NETBOX_TOKEN=<令牌>"
    exit 0 ;;
esac

mkdir -p "$NETBOX_DIR"
if [ ! -d "$REPO" ]; then
  git clone --depth 1 "$REPO_URL" "$REPO"
fi

# superuser + 插件声明 + 端口发布(全部幂等)
(cd "$REPO" && sed -i 's|^SKIP_SUPERUSER=.*|SKIP_SUPERUSER=false|' env/netbox.env)
ensure_env() {
  local f="$REPO/env/netbox.env" key="$1" val="$2"
  if grep -q "^$key=" "$f"; then sed -i "s|^$key=.*|$key=$val|" "$f"; else echo "$key=$val" >> "$f"; fi
}
ensure_env SUPERUSER_NAME admin
ensure_env SUPERUSER_EMAIL admin@example.com
ensure_env "SUPERUSER_PASSWORD" "$SU_PASSWORD"
printf '# SecReq 联动测试环境自动生成(scripts/netbox_dev.sh)\nPLUGINS = ["netbox_custom_objects"]\n' > "$REPO/configuration/plugins.py"
printf 'services:\n  netbox:\n    ports:\n      - "%s:8080"\n' "$PORT" > "$REPO/docker-compose.override.yml"

echo ">> 启动容器(首次会拉取镜像, 视网络可能数分钟)..."
dc up -d

echo ">> 等待 NetBox 就绪..."
wait_netbox

# custom-objects 插件(容器内 venv 安装; down 重建容器后需重装, 本步骤幂等)
if ! dc exec -T netbox /opt/netbox/venv/bin/python -c "import netbox_custom_objects" 2>/dev/null; then
  echo ">> 安装 netbox-custom-objects 插件..."
  dc exec --user root -T netbox /opt/netbox/venv/bin/pip install --no-cache-dir netbox-custom-objects
  dc restart netbox
  sleep 5
  echo ">> 等待插件迁移后重新就绪..."
  wait_netbox
fi

# ── 令牌(固定 key 的 v1 令牌, 幂等; SecReq 以 Authorization: Token <key> 认证) ──
if [ ! -s "$TOKEN_FILE" ]; then openssl rand -hex 20 > "$TOKEN_FILE"; fi
TOKEN=$(cat "$TOKEN_FILE")
dc exec --user root -T netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py shell -c "
from django.contrib.auth import get_user_model
from users.models import Token
u = get_user_model().objects.get(username='admin')
key = '$TOKEN'
if not Token.objects.filter(user=u, key=key).exists():
    try:
        Token.objects.create(user=u, key=key, version='v1')
    except Exception:
        Token.objects.create(user=u, key=key)
print('token-ready')
" | grep -q token-ready || { echo "令牌创建失败" >&2; exit 1; }

# ── custom object type(slug=$SLUG) + 字段(name/code/owner, 对应 field_map 默认值) ──
TYPE_ID=$(api GET "/api/plugins/custom-objects/custom-object-types/?slug=$SLUG" \
  | py -c 'import sys,json; d=json.load(sys.stdin); r=d.get("results") or []; print(r[0]["id"] if r else "")')
if [ -z "$TYPE_ID" ]; then
  TYPE_ID=$(api POST "/api/plugins/custom-objects/custom-object-types/" \
    "{\"name\":\"系统\",\"slug\":\"$SLUG\",\"verbose_name\":\"系统\",\"verbose_name_plural\":\"系统\"}" \
    | py -c 'import sys,json; print(json.load(sys.stdin)["id"])')
  echo "+ 类型 $SLUG(id=$TYPE_ID)"
fi
ensure_type_field() {
  local type_id="$1" fname="$2" label="$3" req="$4"
  local exists
  exists=$(api GET "/api/plugins/custom-objects/custom-object-type-fields/?custom_object_type_id=$type_id" \
    | py -c 'import sys,json; d=json.load(sys.stdin); rows=[r for r in d.get("results",[]) if r.get("name")=="'"$fname"'"]; print("yes" if rows else "no")')
  if [ "$exists" != "yes" ]; then
    api POST "/api/plugins/custom-objects/custom-object-type-fields/" \
      "{\"custom_object_type\":$type_id,\"name\":\"$fname\",\"label\":\"$label\",\"type\":\"text\",\"required\":$req}" >/dev/null
    echo "+ 字段 $fname"
  fi
}
ensure_type_field "$TYPE_ID" name  "系统名称" true
ensure_type_field "$TYPE_ID" code  "系统编号" false
ensure_type_field "$TYPE_ID" owner "负责人"   false

# ── 样例数据(设备/IP 供导入测试; 一个 system 对象供清单展示; 均按名称幂等) ──
core_id() { # core_id <endpoint-with-query> ; 输出首个结果 id, 无则空
  api GET "$1" | py -c 'import sys,json; d=json.load(sys.stdin); r=d.get("results") or []; print(r[0]["id"] if r else "")'
}
SITE_ID=$(core_id "/api/dcim/sites/?slug=demo-site")
if [ -z "$SITE_ID" ]; then
  SITE_ID=$(api POST "/api/dcim/sites/" '{"name":"演示站点","slug":"demo-site"}' | py -c 'import sys,json; print(json.load(sys.stdin)["id"])')
  echo "+ site 演示站点"
fi
ROLE_ID=$(core_id "/api/dcim/roles/?slug=app-server")
if [ -z "$ROLE_ID" ]; then
  ROLE_ID=$(api POST "/api/dcim/roles/" '{"name":"应用服务器","slug":"app-server"}' | py -c 'import sys,json; print(json.load(sys.stdin)["id"])')
  echo "+ role 应用服务器"
fi
MFR_ID=$(core_id "/api/dcim/manufacturers/?slug=democorp")
if [ -z "$MFR_ID" ]; then
  MFR_ID=$(api POST "/api/dcim/manufacturers/" '{"name":"DemoCorp","slug":"democorp"}' | py -c 'import sys,json; print(json.load(sys.stdin)["id"])')
  echo "+ manufacturer DemoCorp"
fi
DT_ID=$(core_id "/api/dcim/device-types/?slug=appnode-1")
if [ -z "$DT_ID" ]; then
  DT_ID=$(api POST "/api/dcim/device-types/" "{\"manufacturer\":$MFR_ID,\"model\":\"AppNode 1\",\"slug\":\"appnode-1\"}" | py -c 'import sys,json; print(json.load(sys.stdin)["id"])')
  echo "+ device-type AppNode 1"
fi
DEV_N=$(api GET "/api/dcim/devices/?q=edge-app-01" | py -c 'import sys,json; d=json.load(sys.stdin); print(len(d.get("results") or []))')
if [ "$DEV_N" = "0" ]; then
  api POST "/api/dcim/devices/" "{\"name\":\"edge-app-01\",\"device_type\":$DT_ID,\"role\":$ROLE_ID,\"site\":$SITE_ID,\"status\":\"active\"}" >/dev/null
  echo "+ device edge-app-01"
fi
IP_N=$(api GET "/api/ipam/ip-addresses/?q=10.20.0.5" | py -c 'import sys,json; d=json.load(sys.stdin); print(len(d.get("results") or []))')
if [ "$IP_N" = "0" ]; then
  api POST "/api/ipam/ip-addresses/" '{"address":"10.20.0.5/24","status":"active"}' >/dev/null
  echo "+ ip 10.20.0.5/24"
fi
OBJ_N=$(api GET "/api/plugins/custom-objects/$SLUG/?q=NB-SYS-001" | py -c 'import sys,json; d=json.load(sys.stdin); print(len(d.get("results") or []))')
if [ "$OBJ_N" = "0" ]; then
  api POST "/api/plugins/custom-objects/$SLUG/" \
    '{"name":"示例系统(NetBox 侧)","code":"NB-SYS-001","owner":"安全管理员"}' >/dev/null
  echo "+ system 对象 NB-SYS-001"
fi

echo
echo "== NetBox 测试环境就绪 =="
echo "  地址:      $BASE_URL (admin / $SU_PASSWORD)"
echo "  系统清单:  $BASE_URL/api/plugins/custom-objects/$SLUG/"
echo "  API 令牌:  $TOKEN (存于 $TOKEN_FILE)"
echo "  SecReq 接入: 系统管理 -> NetBox 互通 填入上述地址与令牌, 或"
echo "    SECREQ_NETBOX_URL=$BASE_URL SECREQ_NETBOX_TOKEN=$TOKEN SECREQ_NETBOX_SYSTEM_SLUG=$SLUG"
