#!/usr/bin/env bash
set -euo pipefail

LOCAL_PORT="${RLCD_LOCAL_PORT:-8787}"
REMOTE_BIND_HOST="${RLCD_REMOTE_BIND_HOST:-127.0.0.1}"
REMOTE_BIND_PORT="${RLCD_REMOTE_BIND_PORT:-18787}"
SSH_PORT="${RLCD_TUNNEL_SSH_PORT:-22}"
RETRY_DELAY="${RLCD_TUNNEL_RETRY_DELAY:-5}"

trap 'echo "停止 RLCD 反向隧道"; exit 0' INT TERM

if [ -n "${RLCD_TUNNEL_TARGET:-}" ]; then
  SSH_TARGET="$RLCD_TUNNEL_TARGET"
else
  if [ -z "${RLCD_TUNNEL_HOST:-}" ]; then
    echo "缺少 RLCD_TUNNEL_HOST，例如：你的服务器 IP 或域名" >&2
    exit 2
  fi
  if [ -z "${RLCD_TUNNEL_USER:-}" ]; then
    echo "缺少 RLCD_TUNNEL_USER，例如：root 或你服务器上的用户名" >&2
    exit 2
  fi
  SSH_TARGET="${RLCD_TUNNEL_USER}@${RLCD_TUNNEL_HOST}"
fi

echo "打开 RLCD 反向隧道：服务器 ${REMOTE_BIND_HOST}:${REMOTE_BIND_PORT} -> Mac 127.0.0.1:${LOCAL_PORT}"
echo "SSH 目标：${SSH_TARGET}"

cleanup_remote_port() {
  ssh -p "$SSH_PORT" -o ConnectTimeout=10 "$SSH_TARGET" bash -s -- "$REMOTE_BIND_HOST" "$REMOTE_BIND_PORT" <<'REMOTE' || true
bind_host="$1"
port="$2"
pids=$(ss -ltnp 2>/dev/null | awk -v bind_host="$bind_host" -v port="$port" '$4 == bind_host ":" port { if (match($0,/pid=[0-9]+/)) { print substr($0, RSTART+4, RLENGTH-4) } }')
if [ -n "$pids" ]; then
  echo "清理远端残留隧道端口 ${bind_host}:${port}: $pids"
  kill $pids 2>/dev/null || true
  sleep 1
fi
REMOTE
}

while true; do
  cleanup_remote_port
  set +e
  ssh \
    -N \
    -p "$SSH_PORT" \
    -o ExitOnForwardFailure=yes \
    -o ServerAliveInterval=30 \
    -o ServerAliveCountMax=3 \
    -R "${REMOTE_BIND_HOST}:${REMOTE_BIND_PORT}:127.0.0.1:${LOCAL_PORT}" \
    "$SSH_TARGET"
  ssh_exit=$?
  set -e

  echo "RLCD 反向隧道已断开，ssh_exit=${ssh_exit}，${RETRY_DELAY}s 后重连"
  cleanup_remote_port
  sleep "$RETRY_DELAY"
done
