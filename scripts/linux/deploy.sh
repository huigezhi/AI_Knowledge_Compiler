#!/usr/bin/env bash
# 从本机把代码同步到 VPS 并重启服务（改完代码后一条命令生效）
#
#   ./deploy.sh user@1.2.3.4                 # 默认远端目录 /opt/akc
#   ./deploy.sh user@1.2.3.4 --dir /srv/akc
#   ./deploy.sh user@1.2.3.4 --no-build      # 跳过远端依赖重建
#
# 依赖：ssh + rsync（Windows 可用 Git Bash / WSL）
set -euo pipefail

TARGET="${1:-}"
REMOTE_DIR="/opt/akc"
REBUILD=1

if [[ -z "$TARGET" ]]; then
  echo "用法: $0 <user@host> [--dir /opt/akc] [--no-build]" >&2
  exit 2
fi
shift
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dir) REMOTE_DIR="$2"; shift 2 ;;
    --no-build) REBUILD=0; shift ;;
    *) echo "未知参数: $1" >&2; exit 2 ;;
  esac
done

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

echo "==> 同步 ${SRC} → ${TARGET}:${REMOTE_DIR}"
rsync -az --delete \
  --exclude '.git' --exclude 'apps/backend/.venv' --exclude 'apps/backend/data' \
  --exclude 'apps/extension/node_modules' --exclude 'apps/extension/dist' \
  --exclude '__pycache__' --exclude '*.egg-info' \
  -e ssh "$SRC/" "${TARGET}:${REMOTE_DIR}/"

if (( REBUILD )); then
  echo "==> 远端重建依赖"
  ssh "$TARGET" "${REMOTE_DIR}/apps/backend/.venv/bin/pip install -q -e ${REMOTE_DIR}/apps/backend"
fi

echo "==> 重启服务"
ssh "$TARGET" "sudo systemctl restart akc && sleep 2 && curl -fsS http://127.0.0.1:38127/api/v1/health"

echo "部署完成。日志：ssh $TARGET 'journalctl -u akc -f'"
