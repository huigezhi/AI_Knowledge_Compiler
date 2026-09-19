#!/usr/bin/env bash
# 卸载 AKC systemd 服务
#
#   sudo ./uninstall.sh              # 停服务、删服务单元（保留 /opt/akc 与数据）
#   sudo ./uninstall.sh --purge      # 连同安装目录、配置与数据一起删除
set -euo pipefail

PURGE=0
DIR="/opt/akc"
[[ "${1:-}" == "--purge" ]] && PURGE=1
[[ "${1:-}" == "--dir"   ]] && DIR="${2:-/opt/akc}"

[[ $EUID -ne 0 ]] && { echo "请使用 sudo 运行" >&2; exit 1; }

echo "==> 停止并禁用服务"
systemctl stop akc 2>/dev/null || true
systemctl disable akc 2>/dev/null || true
rm -f /etc/systemd/system/akc.service
systemctl daemon-reload

if (( PURGE )); then
  echo "==> 删除安装目录与配置（不可恢复）"
  rm -rf "$DIR" /etc/akc
  if id -u akc >/dev/null 2>&1; then userdel akc 2>/dev/null || true; fi
else
  echo "==> 保留 ${DIR} 与 /etc/akc（数据未删除）"
fi

echo "卸载完成。如需彻底清除：sudo $0 --purge"
