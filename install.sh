#!/usr/bin/env bash
# AI Knowledge Compiler (AKC) —— Ubuntu / Debian 一键安装
# 一行命令运行:
#   bash <(curl -fsSL https://raw.githubusercontent.com/huigezhi/AI_Knowledge_Compiler/main/install.sh)
#
# 做的事: apt 补齐缺失的 git / python3 -> 克隆/更新代码 -> 调用仓库内
# scripts/linux/install.sh 装成 systemd 常驻服务（开机自启 + 崩溃自动拉起）。
# 后端装在 VPS 时，Chrome 扩展用 SSH 隧道连接:
#   ssh -N -L 38127:127.0.0.1:38127 user@your-vps
set -euo pipefail

REPO_URL="https://github.com/huigezhi/AI_Knowledge_Compiler.git"
SRC_DIR="$HOME/ai-knowledge-compiler"
SUDO=""
if [[ $EUID -ne 0 ]]; then SUDO="sudo"; fi

echo "=============================================================="
echo "  AI Knowledge Compiler 一键安装 (Ubuntu / Debian)"
echo "  代码目录: $SRC_DIR"
echo "=============================================================="

# ---------- 1. 基础工具（缺什么装什么） ----------
need_pkgs=()
command -v git >/dev/null 2>&1 || need_pkgs+=(git)
command -v python3 >/dev/null 2>&1 || need_pkgs+=(python3)
# venv 与 pip 在 Debian/Ubuntu 上是独立包，即便 python3 已存在也可能缺
if ! python3 -c "import venv" >/dev/null 2>&1; then need_pkgs+=(python3-venv); fi
if ! python3 -m pip --version >/dev/null 2>&1; then need_pkgs+=(python3-pip); fi
if ((${#need_pkgs[@]})); then
  echo "==> apt 安装缺失组件: ${need_pkgs[*]}"
  $SUDO apt-get update -y
  $SUDO apt-get install -y "${need_pkgs[@]}"
fi

PY_MAJOR=$(python3 -c 'import sys;print(sys.version_info.major)')
PY_MINOR=$(python3 -c 'import sys;print(sys.version_info.minor)')
if ((PY_MAJOR < 3 || (PY_MAJOR == 3 && PY_MINOR < 12))); then
  echo "需要 Python 3.12+，当前为 ${PY_MAJOR}.${PY_MINOR}" >&2
  echo "可先用 deadsnakes PPA 安装: sudo add-apt-repository ppa:deadsnakes/ppa && sudo apt install python3.12 python3.12-venv" >&2
  exit 1
fi

# ---------- 2. 获取代码 ----------
if [[ -f "$SRC_DIR/scripts/linux/install.sh" ]]; then
  echo "==> 代码已存在，拉取最新版本..."
  git -C "$SRC_DIR" pull --ff-only || echo "    git pull 失败，使用现有代码继续"
else
  echo "==> 克隆 $REPO_URL ..."
  git clone "$REPO_URL" "$SRC_DIR"
fi

# ---------- 3. 安装为 systemd 服务（内部脚本会同步到 /opt/akc 并启动） ----------
echo "==> 安装后端服务（需要 sudo/root）..."
$SUDO bash "$SRC_DIR/scripts/linux/install.sh" "$@"

# ---------- 4. 验证 ----------
sleep 2
if curl -fsS -m 8 http://127.0.0.1:38127/api/v1/health | grep -q '"ok"'; then
  echo "[OK] 后端健康检查通过: http://127.0.0.1:38127"
else
  echo "[!!] 健康检查未通过，请查看: systemctl status akc" >&2
  exit 1
fi

echo
echo "=============================================================="
echo "  安装完成!"
echo
echo "  服务管理:   systemctl status|restart|stop akc"
echo "  本地令牌:   /opt/akc/apps/backend/data/auth_token"
echo
echo "  Chrome 扩展（本地电脑上）: ssh -N -L 38127:127.0.0.1:38127 user@$(hostname -I 2>/dev/null | awk '{print $1}')"
echo "  连接 Obsidian 库:  修改 /etc/akc/akc.env 的 AKC_VAULT_PATH 后 systemctl restart akc"
echo "=============================================================="
