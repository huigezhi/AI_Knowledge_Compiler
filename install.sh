#!/usr/bin/env bash
# AI Knowledge Compiler (AKC) —— Ubuntu / Debian 一键安装
# 推荐一行命令（下载到临时文件再执行，兼容没有 /dev/fd 的 VPS）:
#   curl -fsSL https://raw.githubusercontent.com/huigezhi/AI_Knowledge_Compiler/main/install.sh -o /tmp/akc-install.sh && bash /tmp/akc-install.sh
#
# 做的事: apt 补齐缺失的 git / curl / python3 -> 自动准备 Python 3.12+ ->
# 克隆/更新代码 -> 调用仓库内 scripts/linux/install.sh 装成 systemd 常驻服务
# （开机自启 + 崩溃自动拉起）。
# 后端装在 VPS 时，Chrome 扩展用 SSH 隧道连接:
#   ssh -N -L 38127:127.0.0.1:38127 user@your-vps
#
# 可选环境变量:
#   PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple   # 国内 VPS 加速
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
command -v curl >/dev/null 2>&1 || need_pkgs+=(curl)
if ((${#need_pkgs[@]})); then
  echo "==> apt 安装缺失组件: ${need_pkgs[*]}"
  $SUDO apt-get update -y
  $SUDO apt-get install -y "${need_pkgs[@]}"
fi

# ---------- 2. 找一个 >= 3.12 的 Python ----------
# Ubuntu 22.04 自带 3.10、Debian 12 自带 3.11，都不够；依次探测更近的版本。
PYBIN=""
for cand in python3.13 python3.12 python3; do
  if command -v "$cand" >/dev/null 2>&1 \
     && "$cand" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)' >/dev/null 2>&1; then
    PYBIN="$cand"
    break
  fi
done

# 没有可用的 >= 3.12 时，Ubuntu 走 deadsnakes 自动装 3.12；其它系统给出明确指引
if [[ -z "$PYBIN" ]]; then
  if [[ -r /etc/os-release ]] && source /etc/os-release && [[ "${ID:-}" == ubuntu ]]; then
    echo "==> 系统自带 Python 过旧，自动安装 Python 3.12 (deadsnakes PPA)..."
    $SUDO apt-get update -y
    $SUDO apt-get install -y software-properties-common
    $SUDO add-apt-repository -y ppa:deadsnakes/ppa
    $SUDO apt-get install -y "python3.12-venv"
    PYBIN="python3.12"
  else
    echo "需要 Python 3.12+，但未在系统中找到，且当前不是 Ubuntu（无法自动装）。" >&2
    echo "Debian 12 用户可先手动安装：" >&2
    echo "  echo 'deb https://deb.debian.org/debian trixie main' | sudo tee /etc/apt/sources.list.d/trixie.list" >&2
    echo "  sudo apt update && sudo apt install -y python3.12 python3.12-venv" >&2
    exit 1
  fi
fi
echo "==> 使用 Python 解释器: $PYBIN ($($PYBIN -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")'))"

# venv 能力：Debian/Ubuntu 把 venv 拆在独立包里，缺了就按解释器版本补
if ! "$PYBIN" -c "import venv" >/dev/null 2>&1; then
  PYVER=$("$PYBIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
  echo "==> 补装 venv 支持 (python${PYVER}-venv)..."
  $SUDO apt-get update -y
  $SUDO apt-get install -y "python${PYVER}-venv" || $SUDO apt-get install -y python3-venv
fi

# ---------- 3. 获取代码 ----------
if [[ -f "$SRC_DIR/scripts/linux/install.sh" ]]; then
  echo "==> 代码已存在，拉取最新版本..."
  git -C "$SRC_DIR" pull --ff-only || echo "    git pull 失败，使用现有代码继续"
else
  echo "==> 克隆 $REPO_URL ..."
  git clone "$REPO_URL" "$SRC_DIR"
fi

# ---------- 4. 安装为 systemd 服务（内部脚本会同步到 /opt/akc 并启动） ----------
# PYTHON 用 env 传递：sudo 默认会剥离环境变量；PIP_INDEX_URL 只在用户给了时透传
echo "==> 安装后端服务（需要 sudo/root）..."
if [[ -n "${PIP_INDEX_URL:-}" ]]; then
  $SUDO env PYTHON="$PYBIN" PIP_INDEX_URL="$PIP_INDEX_URL" \
    bash "$SRC_DIR/scripts/linux/install.sh" "$@"
else
  $SUDO env PYTHON="$PYBIN" \
    bash "$SRC_DIR/scripts/linux/install.sh" "$@"
fi

# ---------- 5. 验证 ----------
sleep 2
if curl -fsS -m 8 http://127.0.0.1:38127/api/v1/health | grep -q '"ok"'; then
  echo "[OK] 后端健康检查通过: http://127.0.0.1:38127"
else
  echo "[!!] 健康检查未通过，请查看: systemctl status akc" >&2
  exit 1
fi

HOST_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
echo
echo "=============================================================="
echo "  安装完成!"
echo
echo "  服务管理:   systemctl status|restart|stop akc"
echo "  本地令牌:   /opt/akc/apps/backend/data/auth_token"
echo
echo "  Chrome 扩展（本地电脑上）: ssh -N -L 38127:127.0.0.1:38127 user@${HOST_IP:-<vps-ip>}"
echo "  连接 Obsidian 库:  修改 /etc/akc/akc.env 的 AKC_VAULT_PATH 后 systemctl restart akc"
echo "=============================================================="
