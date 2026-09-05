#!/usr/bin/env bash
# NetBox 联动测试环境一键拉起 —— 直跑版(不依赖 Docker)。
# 对应 SecReq #152/#153/#154 互通契约, 见 docs/netbox-dev.md。
#
# 架构: 真实 NetBox(pip 包) + 官方 netboxlabs-netbox-custom-objects 插件,
# 直接跑在 Linux/WSL 上(NetBox 需要 PostgreSQL + Redis, Windows 原生不 supported):
#   - Linux 环境: 本脚本直接执行;
#   - Windows: 自动经 `wsl -d <发行版> -u root` 重入本脚本(Ubuntu 24.04 验证过),
#     宿主用 localhost:8080 访问(WSL2 localhost 转发; 失败时用 `info` 里的 WSL IP)。
#
# 用法:
#   scripts/netbox_dev.sh up      # 拉起(幂等: 重复执行安全)
#   scripts/netbox_dev.sh down    # 停止 runserver 与 postgres/redis
#   scripts/netbox_dev.sh info    # 地址/令牌/接入配置
# 环境变量:
#   NETBOX_PORT=8080  NETBOX_SUPERUSER_PASSWORD=secreq-admin
#   NETBOX_SYSTEM_SLUG=system  NETBOX_DIR=./netbox(gitignored)
#   NETBOX_HOME=~/.secreq-netbox(venv/配置/DB 无关产物; Linux 本地路径, 不入仓)
set -euo pipefail

NETBOX_DIR="${NETBOX_DIR:-netbox}"
PORT="${NETBOX_PORT:-8080}"
SLUG="${NETBOX_SYSTEM_SLUG:-system}"
SU_PASSWORD="${NETBOX_SUPERUSER_PASSWORD:-secreq-admin}"
NETBOX_HOME="${NETBOX_HOME:-$HOME/.secreq-netbox}"
TOKEN_FILE="$NETBOX_DIR/api-token"
NB_VERSION="4.7.0"
NB_DB="${NETBOX_DB:-netbox_secreq}"      # 专属库, 不复用宿主机可能存在的 netbox 库
NB_DB_USER="${NETBOX_DB_USER:-netbox_secreq}"
NB_DB_PASSWORD="${NETBOX_DB_PASSWORD:-secreq-netbox}"
PLUGIN_VERSION="0.6.1"
BASE_URL="http://localhost:$PORT"

# ── Windows 宿主: 重入 WSL(Linux 侧继续往下走) ──
if [ "$(uname -s)" != "Linux" ]; then
  WSL_DISTRO="${NETBOX_WSL_DISTRO:-Ubuntu}"
  REPO_WIN="$(cd "$(dirname "$0")/.." && pwd)"
  REPO_WSL="$(wsl.exe -d "$WSL_DISTRO" -u root -- wslpath -a "$REPO_WIN" 2>/dev/null | tr -d '\r\n')"
  if [ -z "$REPO_WSL" ]; then
    echo "未找到 WSL 发行版 $WSL_DISTRO; 请安装 Ubuntu 或在 Linux 上运行本脚本" >&2
    exit 1
  fi
  echo ">> 经 WSL($WSL_DISTRO) 直跑 NetBox: $REPO_WSL"
  wsl.exe -d "$WSL_DISTRO" -u root -- bash -lc \
    "export NETBOX_DIR='$REPO_WSL/$NETBOX_DIR' NETBOX_PORT='$PORT' NETBOX_SYSTEM_SLUG='$SLUG' \
     NETBOX_SUPERUSER_PASSWORD='$SU_PASSWORD'; \
     cd '$REPO_WSL' && bash scripts/netbox_dev.sh __inner__"
  # 内层已就绪; 宿主侧确认 localhost 转发
  code=$(curl -sL -o /dev/null -w '%{http_code}' --max-time 5 "$BASE_URL/api/status" || true)
  if [ "$code" != "000" ]; then
    echo ">> 宿主 localhost:$PORT 可达"
  else
    WSL_IP=$(wsl.exe -d "$WSL_DISTRO" -u root -- hostname -I 2>/dev/null | tr -d '\r\n' | awk '{print $1}')
    echo "!! localhost:$PORT 暂不可达(WSL2 转发可能未生效), 可改用 WSL IP: http://$WSL_IP:$PORT" >&2
  fi
  exit 0
fi

# ── Linux/WSL 内层 ──
if [ "${1:-}" = "__inner__" ]; then set -- up; fi
if [ "$(id -u)" != "0" ] && ! sudo -n true 2>/dev/null; then
  echo "需要 root(或免密 sudo): 安装 postgres/redis 与启动服务用" >&2
  exit 1
fi
SUDO=""
[ "$(id -u)" != "0" ] && SUDO="sudo"

as_root() { if [ -n "$SUDO" ]; then "$SUDO" "$@"; else "$@"; fi; }
pg_psql() { # 以 postgres 系统用户执行 psql
  if [ "$(id -u)" = "0" ]; then runuser -u postgres -- psql "$@"
  else "$SUDO" -u postgres psql "$@"; fi
}

py() {
  if command -v python3 >/dev/null 2>&1; then python3 "$@"
  elif command -v python >/dev/null 2>&1; then python "$@"
  else uv run --no-project python "$@"; fi
}

cmd="${1:-up}"
case "$cmd" in
  down)
    pkill -f "netbox runserver" 2>/dev/null || true
    pkill -f "manage.py runserver" 2>/dev/null || true
    redis-cli shutdown nosave 2>/dev/null || true
    "$SUDO" service postgresql stop 2>/dev/null || true
    echo "NetBox 测试环境已停止(数据保留: $NETBOX_HOME 与 postgres 库)"
    exit 0 ;;
  info)
    echo "NetBox:   $BASE_URL (admin 密码: $SU_PASSWORD)"
    echo "系统清单: $BASE_URL/api/plugins/custom-objects/$SLUG/"
    echo "API 令牌: $(cat "$TOKEN_FILE" 2>/dev/null || echo '(尚未生成, 先执行 up)')"
    echo "SecReq 接入(base_url=$BASE_URL):"
    echo "  PUT /api/admin/netbox-config {\"base_url\":\"$BASE_URL\",\"token\":\"<令牌>\",\"system_slug\":\"$SLUG\",\"field_map\":{\"name\":\"name\",\"code\":\"code\",\"owner\":\"owner_name\"}}  (NetBox 4.5+ 自带 owner 对象字段, 故 owner 映射到 owner_name)"
    echo "  或环境变量 SECREQ_NETBOX_URL=$BASE_URL SECREQ_NETBOX_TOKEN=<令牌>"
    exit 0 ;;
esac

# ── up ──
echo ">> 安装系统依赖(幂等)..."
export DEBIAN_FRONTEND=noninteractive
as_root apt-get update -qq
as_root apt-get install -y -qq --no-install-recommends \
  python3 python3-venv python3-dev postgresql redis-server \
  build-essential libpq-dev libxml2-dev libxslt1-dev libldap2-dev libsasl2-dev \
  libssl-dev pkg-config curl git >/dev/null

echo ">> 启动 postgres / redis..."
as_root service postgresql start >/dev/null 2>&1 || as_root service postgresql start
if ! redis-cli ping >/dev/null 2>&1; then redis-server --daemonize yes; fi

echo ">> 准备数据库 netbox(幂等)..."
pg_psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='netbox'" | grep -q 1 \
  || pg_psql -c "CREATE USER netbox WITH PASSWORD 'secreq-netbox';" >/dev/null
pg_psql -tAc "SELECT 1 FROM pg_database WHERE datname='netbox'" | grep -q 1 \
  || pg_psql -c "CREATE DATABASE netbox OWNER netbox;" >/dev/null

echo ">> 安装 NetBox $NB_VERSION + custom-objects 插件 $PLUGIN_VERSION(pip)..."
mkdir -p "$NETBOX_HOME"
if [ ! -x "$NETBOX_HOME/venv/bin/python" ]; then
  python3 -m venv "$NETBOX_HOME/venv"
  "$NETBOX_HOME/venv/bin/pip" -q install --upgrade pip
fi
"$NETBOX_HOME/venv/bin/pip" -q install "netbox==$NB_VERSION" \
  "netboxlabs-netbox-custom-objects==$PLUGIN_VERSION"
mkdir -p "$NETBOX_HOME/media" "$NETBOX_HOME/static" "$NETBOX_HOME/reports" "$NETBOX_HOME/scripts"

echo ">> 写配置(configuration.py)..."
if [ ! -f "$NETBOX_HOME/configuration.py" ]; then
  SECRET=$("$NETBOX_HOME/venv/bin/netbox" secret-key 2>/dev/null || openssl rand -hex 32)
  cat > "$NETBOX_HOME/configuration.py" <<EOF
# SecReq NetBox 联动测试环境配置(scripts/netbox_dev.sh 生成, 本地测试用途)
ALLOWED_HOSTS = ["*"]
DEBUG = True  # 测试环境: 由 runserver 直接服务静态文件
SECRET_KEY = "$SECRET"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "$NB_DB",
        "USER": "$NB_DB_USER",
        "PASSWORD": "$NB_DB_PASSWORD",
        "HOST": "127.0.0.1",
        "PORT": "",
        "CONN_MAX_AGE": 300,
    }
}
REDIS = {
    "tasks": {"HOST": "localhost", "PORT": 6379, "PASSWORD": "", "DATABASE": 0, "SSL": False, "SKIP_TLS_VERIFY": False},
    "caching": {"HOST": "localhost", "PORT": 6379, "PASSWORD": "", "DATABASE": 1, "SSL": False, "SKIP_TLS_VERIFY": False},
}
MEDIA_ROOT = "$NETBOX_HOME/media"
STATIC_ROOT = "$NETBOX_HOME/static"
REPORTS_ROOT = "$NETBOX_HOME/reports"
SCRIPTS_ROOT = "$NETBOX_HOME/scripts"
PLUGINS = ["netbox_custom_objects"]
EOF
fi
# 统一调用: cli.py 把未知子命令代理到 Django manage(需 NETBOX_CONFIGURATION 可导入)
nb() {
  env NETBOX_CONFIGURATION=configuration PYTHONPATH="$NETBOX_HOME" \
    "$NETBOX_HOME/venv/bin/python" -m netbox "$@"
}

echo ">> 数据库迁移(首次较慢)..."
nb migrate --noinput >/dev/null

echo ">> 管理员与令牌..."
nb shell -c "
from django.contrib.auth import get_user_model
u, _ = get_user_model().objects.get_or_create(
    username='admin', defaults={'email': 'admin@example.com', 'is_superuser': True})
u.is_superuser = True
u.set_password('$SU_PASSWORD')
u.save()
print('admin-ready')
" | grep -q admin-ready || { echo "管理员创建失败" >&2; exit 1; }

# ── 令牌(v1, 由 NetBox 生成; netbox/api-token 是 DB 中 plaintext 的镜像, 自愈幂等) ──
# NetBox 4.4+ Token 模型: version 为整数(1=v1); 必须走 full_clean() 让 clean() 落版本字段,
# 否则 plaintext 不落库 → 认证永远 Invalid。v1 明文可从 DB 回读, 文件丢失时自动恢复。
mkdir -p "$NETBOX_DIR"
TOKEN_RAW=$(nb shell -c "
from django.contrib.auth import get_user_model
from users.models import Token
u = get_user_model().objects.get(username='admin')
t = Token.objects.filter(user=u, version=1, plaintext__gt='').first()
if t is None:
    t = Token(user=u, version=1)
    t.full_clean()
    t.save()
print(t.plaintext)
")
TOKEN=$(printf '%s' "$TOKEN_RAW" | grep -Eo '[A-Za-z0-9]{40}' | tail -1)
[ -n "$TOKEN" ] || { echo "令牌创建失败: $TOKEN_RAW" >&2; exit 1; }
printf '%s' "$TOKEN" > "$TOKEN_FILE"
# HTTP 自校验: 令牌必须能通过认证, 否则后续样例数据无从谈起
auth_code=$(curl -sL -o /dev/null -w '%{http_code}' --max-time 5   -H "Authorization: Token $TOKEN" "$BASE_URL/api/status/")
[ "$auth_code" = "200" ] || { echo "令牌认证失败(HTTP $auth_code), 请删除 $TOKEN_FILE 与 DB 中 v1 令牌后重试" >&2; exit 1; }
echo "+ v1 令牌就绪并通过认证"

echo ">> 启动 runserver($PORT)..."
pkill -f "netbox runserver" 2>/dev/null || true
# setsid 脱离 wsl 会话: 内层脚本退出/会话关闭不连带清理服务进程
setsid nohup env NETBOX_CONFIGURATION=configuration PYTHONPATH="$NETBOX_HOME" \
  "$NETBOX_HOME/venv/bin/python" -m netbox runserver "0.0.0.0:$PORT" --noreload \
  > "$NETBOX_DIR/netbox.log" 2>&1 &
echo $! > "$NETBOX_DIR/netbox.pid"

api() { # api <method> <path> [json-body]
  local method="$1" path="$2" body="${3:-}"
  if [ -n "$body" ]; then
    curl -sS -X "$method" -H "Authorization: Token $TOKEN" -H "Content-Type: application/json" \
      -d "$body" "$BASE_URL$path"
  else
    curl -sS -X "$method" -H "Authorization: Token $TOKEN" "$BASE_URL$path"
  fi
}
core_id() { api GET "$1" | py -c 'import sys,json; d=json.load(sys.stdin); r=d.get("results") or []; print(r[0]["id"] if r else "")'; }

echo ">> 等待就绪..."
code=""
for _ in $(seq 1 60); do
  # -L: /api/status 会 301 到带尾斜杠路径; NetBox 4.x 该端点需要认证, 必须带令牌(否则 403)
  code=$(curl -sL -o /dev/null -w '%{http_code}' --max-time 3     -H "Authorization: Token $TOKEN" "$BASE_URL/api/status" || true)
  [ "$code" = "200" ] && break
  sleep 3
done
[ "$code" = "200" ] || { echo "NetBox 未就绪, 日志: $NETBOX_DIR/netbox.log" >&2; exit 1; }

echo ">> custom object 类型 $SLUG 与字段(name/code/owner)..."
TYPE_ID=$(core_id "/api/plugins/custom-objects/custom-object-types/?slug=$SLUG")
if [ -z "$TYPE_ID" ]; then
  # 插件约束: name 仅小写字母数字下划线; 中文展示名放 verbose_name
  TYPE_RESP=$(api POST "/api/plugins/custom-objects/custom-object-types/" \
    "{\"name\":\"$SLUG\",\"slug\":\"$SLUG\",\"verbose_name\":\"系统\",\"verbose_name_plural\":\"系统\"}")
  TYPE_ID=$(printf '%s' "$TYPE_RESP" | py -c 'import sys,json; print(json.load(sys.stdin).get("id",""))')
  [ -n "$TYPE_ID" ] || { echo "类型创建失败: $TYPE_RESP" >&2; exit 1; }
  echo "+ 类型 $SLUG(id=$TYPE_ID)"
fi
ensure_type_field() {
  local type_id="$1" fname="$2" label="$3" req="$4"
  local exists
  exists=$(api GET "/api/plugins/custom-objects/custom-object-type-fields/?custom_object_type_id=$type_id" \
    | py -c 'import sys,json; d=json.load(sys.stdin); rows=[r for r in d.get("results",[]) if r.get("name")=="'"$fname"'"]; print("yes" if rows else "no")')
  if [ "$exists" != "yes" ]; then
    RESP=$(api POST "/api/plugins/custom-objects/custom-object-type-fields/" \
      "{\"custom_object_type\":$type_id,\"name\":\"$fname\",\"label\":\"$label\",\"type\":\"text\",\"required\":$req}")
    FID=$(printf '%s' "$RESP" | py -c 'import sys,json; print(json.load(sys.stdin).get("id",""))')
    [ -n "$FID" ] || { echo "字段 $fname 创建失败: $RESP" >&2; return 0; }
    echo "+ 字段 $fname"
  fi
}
ensure_type_field "$TYPE_ID" name       "系统名称" true
ensure_type_field "$TYPE_ID" code       "系统编号" false
# NetBox 4.5+ 自带 owner 对象引用字段, 文本负责人字段改名 owner_name;
# SecReq 侧 field_map 相应配 {"owner": "owner_name"}
ensure_type_field "$TYPE_ID" owner_name "负责人"   false

echo ">> 样例数据(幂等)..."
SITE_ID=$(core_id "/api/dcim/sites/?slug=demo-site")
if [ -z "$SITE_ID" ]; then
  SITE_ID=$(api POST "/api/dcim/sites/" '{"name":"演示站点","slug":"demo-site"}' | py -c 'import sys,json; print(json.load(sys.stdin)["id"])')
  echo "+ site 演示站点"
fi
ROLE_ID=$(core_id "/api/dcim/device-roles/?slug=app-server")
if [ -z "$ROLE_ID" ]; then
  ROLE_ID=$(api POST "/api/dcim/device-roles/" '{"name":"应用服务器","slug":"app-server"}' | py -c 'import sys,json; print(json.load(sys.stdin)["id"])')
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
    '{"name":"示例系统(NetBox 侧)","code":"NB-SYS-001","owner_name":"安全管理员"}' >/dev/null
  echo "+ system 对象 NB-SYS-001"
fi

echo
echo "== NetBox 测试环境就绪 =="
echo "  地址:      $BASE_URL (admin / $SU_PASSWORD)"
echo "  系统清单:  $BASE_URL/api/plugins/custom-objects/$SLUG/"
echo "  API 令牌:  $TOKEN (存于 $TOKEN_FILE)"
echo "  安装位置:  $NETBOX_HOME(venv/配置; PostgreSQL 库 $NB_DB / Redis db0-1)"
echo "  SecReq 接入: 系统管理 -> NetBox 互通 填入上述地址与令牌, 或"
echo "    SECREQ_NETBOX_URL=$BASE_URL SECREQ_NETBOX_TOKEN=$TOKEN SECREQ_NETBOX_SYSTEM_SLUG=$SLUG"
