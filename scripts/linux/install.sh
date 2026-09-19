#!/usr/bin/env bash
# AKC 后端 —— VPS 一键安装为 systemd 常驻服务（开机自启 + 崩溃自动拉起）
#
# 用法（需 root）：
#   sudo ./install.sh                                  # 默认安装到 /opt/akc
#   sudo ./install.sh --vault /opt/akc/vault           # 同时指定 Obsidian Vault
#   sudo ./install.sh --domain akc.example.com         # 额外安装 Caddy 自动 HTTPS
#   sudo ./install.sh --dir /srv/akc --user akc --port 38127
#
# 幂等：重复执行只会更新代码、依赖与服务配置，不覆盖已有 /etc/akc/akc.env。
set -euo pipefail

# 允许外层一键脚本指定解释器（如 deadsnakes 装出的 python3.12）：
# Ubuntu 22.04 自带 3.10、Debian 12 自带 3.11，都达不到 3.12+ 的硬性要求。
PYTHON="${PYTHON:-python3}"

DIR="/opt/akc"
USER="akc"
PORT="38127"
VAULT=""
DOMAIN=""
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"   # 仓库根目录

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dir)    DIR="$2"; shift 2 ;;
    --user)   USER="$2"; shift 2 ;;
    --port)   PORT="$2"; shift 2 ;;
    --vault)  VAULT="$2"; shift 2 ;;
    --domain) DOMAIN="$2"; shift 2 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "未知参数: $1" >&2; exit 2 ;;
  esac
done

if [[ $EUID -ne 0 ]]; then echo "请使用 sudo 运行" >&2; exit 1; fi
command -v systemctl >/dev/null || { echo "需要 systemd" >&2; exit 1; }
command -v "$PYTHON" >/dev/null || { echo "找不到解释器: $PYTHON" >&2; exit 1; }

PY_MAJOR=$("$PYTHON" -c 'import sys;print(sys.version_info.major)')
PY_MINOR=$("$PYTHON" -c 'import sys;print(sys.version_info.minor)')
if (( PY_MAJOR < 3 || (PY_MAJOR == 3 && PY_MINOR < 12) )); then
  echo "需要 Python 3.12+，当前 $PYTHON 为 ${PY_MAJOR}.${PY_MINOR}" >&2
  echo "可用 PYTHON=/usr/bin/python3.12 环境变量指定其它解释器" >&2
  exit 1
fi

echo "==> 同步代码到 ${DIR}"
mkdir -p "$DIR"
if command -v rsync >/dev/null; then
  rsync -a --delete \
    --exclude '.git' --exclude 'apps/backend/.venv' --exclude 'apps/backend/data' \
    --exclude 'apps/extension/node_modules' --exclude 'apps/extension/dist' \
    --exclude '__pycache__' --exclude '*.egg-info' \
    "$SRC/" "$DIR/"
else
  (cd "$SRC" && tar --exclude='.git' --exclude='apps/backend/.venv' \
      --exclude='apps/backend/data' --exclude='apps/extension/node_modules' \
      --exclude='apps/extension/dist' -cf - .) | (cd "$DIR" && tar -xf -)
fi

echo "==> 创建系统用户 ${USER}"
if ! id -u "$USER" >/dev/null 2>&1; then
  useradd --system --home-dir "$DIR" --shell /usr/sbin/nologin "$USER"
fi

echo "==> 创建虚拟环境并安装依赖"
# 国内 VPS 访问 pypi.org 慢/不通时：PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple bash install.sh
PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.org/simple}"
"$PYTHON" -m venv "$DIR/apps/backend/.venv"
"$DIR/apps/backend/.venv/bin/pip" install --disable-pip-version-check -q -i "$PIP_INDEX_URL" -e "$DIR/apps/backend"
echo "    依赖安装完成"

DATA_DIR="$DIR/apps/backend/data"
VAULT_DIR="${VAULT:-$DIR/vault}"
mkdir -p "$DATA_DIR" "$VAULT_DIR"

echo "==> 写入环境配置 /etc/akc/akc.env"
mkdir -p /etc/akc
if [[ ! -f /etc/akc/akc.env ]]; then
  TOKEN="$("$PYTHON" -c 'import secrets;print(secrets.token_urlsafe(32))')"
  cat > /etc/akc/akc.env <<EOF
# AKC 后端配置（安装脚本生成；修改后执行 systemctl restart akc）
AKC_ENV=production
# 生产环境强制回环监听 —— 对外访问请走反向代理或 SSH 隧道，不要改成 0.0.0.0
AKC_HOST=127.0.0.1
AKC_PORT=${PORT}
AKC_DATA_DIR=${DATA_DIR}
AKC_DATABASE_URL=sqlite+pysqlite:///${DATA_DIR}/akc.db
AKC_LOG_LEVEL=INFO
AKC_LOG_JSON=true

# 本地访问令牌（扩展必须携带 X-AKC-Token）
AKC_AUTH_TOKEN=${TOKEN}

# Obsidian Vault（容器内路径；需与本地 Vault 通过 Git/Syncthing 同步）
AKC_VAULT_PATH=${VAULT_DIR}

# CORS：扩展来源，形如 chrome-extension://<你的扩展ID>
AKC_CORS_ORIGINS=chrome-extension://placeholder

# Claude 编译（按需填写；不填则只能采集不能编译）
AKC_CLAUDE_ENABLED=false
AKC_CLAUDE_MODEL=
AKC_CLAUDE_API_KEY=
AKC_CLAUDE_BASE_URL=https://api.anthropic.com
EOF
  chmod 600 /etc/akc/akc.env
  echo "    已生成（含随机令牌）"
else
  echo "    已存在，保留原配置"
fi

echo "==> 安装 systemd 服务"
UNIT_SRC="$(dirname "${BASH_SOURCE[0]}")/akc.service"
UNIT="/etc/systemd/system/akc.service"
sed -e "s|__AKC_USER__|${USER}|g" \
    -e "s|__AKC_DIR__|${DIR}|g" \
    -e "s|__AKC_ENVFILE__|/etc/akc/akc.env|g" \
    -e "s|__AKC_DATA_DIR__|${DATA_DIR}|g" \
    -e "s|__AKC_VAULT_DIR__|${VAULT_DIR}|g" \
    "$UNIT_SRC" > "$UNIT"
# Vault 若位于 /home 或 /root，ProtectHome 会挡住写入，此时移除该限制
if [[ "$VAULT_DIR" == /home/* || "$VAULT_DIR" == /root/* ]]; then
  sed -i '/^ProtectHome=/d' "$UNIT"
fi
chown -R "$USER":"$USER" "$DIR"
systemctl daemon-reload
systemctl enable --now akc

if [[ -n "$DOMAIN" ]]; then
  echo "==> 安装 Caddy 反向代理（${DOMAIN} 自动 HTTPS）"
  if ! command -v caddy >/dev/null; then
    apt-get update -qq && apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https curl
    curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/gpg.key | gpg --dearmor -o /usr/share/keyrings/caddy-archive-keyring.gpg
    curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt | tee /etc/apt/sources.list.d/caddy-stable.list
    apt-get update -qq && apt-get install -y -qq caddy
  fi
  cat > /etc/caddy/Caddyfile <<EOF
${DOMAIN} {
    reverse_proxy 127.0.0.1:${PORT}
}
EOF
  systemctl enable --now caddy
  echo "    Caddy 已就绪：https://${DOMAIN}"
fi

sleep 2
echo
echo "================ 安装完成 ================"
systemctl --no-pager status akc | head -12 || true
echo
echo "常用命令："
echo "  systemctl status|restart|stop akc     # 服务管理"
echo "  journalctl -u akc -f                  # 实时日志"
echo "  cat /etc/akc/akc.env                  # 查看配置（含令牌，权限 600）"
echo
echo "接入方式（二选一，推荐第一种）："
echo "  1) SSH 隧道（零改动，最安全）："
echo "     ssh -N -L ${PORT}:127.0.0.1:${PORT} <user>@<vps>"
echo "     扩展 Options 仍填 http://127.0.0.1:${PORT}，无需改任何配置"
echo "  2) HTTPS 域名：先装 Caddy（--domain），再把扩展地址改成 https://${DOMAIN:-你的域名}"
echo
echo "别忘了：把 /etc/akc/akc.env 里的 AKC_CORS_ORIGINS 改成你的扩展 ID 来源后重启服务。"
