#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVER_DIR="$ROOT_DIR/server"
LOCAL_PORT="${RLCD_LOCAL_PORT:-8787}"
REMOTE_BIND_PORT="${RLCD_REMOTE_BIND_PORT:-18787}"
TUNNEL_HOST="${RLCD_TUNNEL_HOST:-}"
TUNNEL_USER="${RLCD_TUNNEL_USER:-}"
REMOTE_BIND_HOST="${RLCD_REMOTE_BIND_HOST:-127.0.0.1}"
TOKEN_PATH="${RLCD_TOKEN_PATH:-}"

stop_local() {
  screen -S rlcd_server -X quit 2>/dev/null || true
  screen -S rlcd_tunnel -X quit 2>/dev/null || true
  pkill -f "uvicorn app:app --host 0.0.0.0 --port ${LOCAL_PORT}" 2>/dev/null || true
  pkill -f "work/rlcd_companion/scripts/run_server.sh" 2>/dev/null || true
  pkill -f "work/rlcd_companion/scripts/run_tunnel.sh" 2>/dev/null || true
  pkill -f "scripts/run_tunnel.sh" 2>/dev/null || true
  pkill -f "ssh .*${REMOTE_BIND_HOST}:${REMOTE_BIND_PORT}:127.0.0.1:${LOCAL_PORT}" 2>/dev/null || true
}

stop_remote_port() {
  if [ -z "$TUNNEL_HOST" ] || [ -z "$TUNNEL_USER" ]; then
    echo "未设置 RLCD_TUNNEL_HOST/RLCD_TUNNEL_USER，跳过远端端口清理"
    return 0
  fi
  ssh -o ConnectTimeout=10 "${TUNNEL_USER}@${TUNNEL_HOST}" bash -s -- "$REMOTE_BIND_HOST" "$REMOTE_BIND_PORT" <<'REMOTE' || true
bind_host="$1"
port="$2"
pids=$(ss -ltnp 2>/dev/null | awk -v bind_host="$bind_host" -v port="$port" '$4 == bind_host ":" port { if (match($0,/pid=[0-9]+/)) { print substr($0, RSTART+4, RLENGTH-4) } }')
if [ -n "$pids" ]; then
  echo "kill remote pids: $pids"
  kill $pids 2>/dev/null || true
fi
sleep 1
ss -ltnp | grep "${bind_host}:${port}" || true
REMOTE
}

start_server() {
  : > "$SERVER_DIR/rlcd_server.log"
  : > "$SERVER_DIR/rlcd_server.err.log"
  screen -dmS rlcd_server bash -lc "cd '$SERVER_DIR' && env RLCD_FEISHU_ENABLED=1 .venv/bin/uvicorn app:app --host 0.0.0.0 --port ${LOCAL_PORT} > rlcd_server.log 2> rlcd_server.err.log"
}

start_tunnel() {
  if [ -z "$TUNNEL_HOST" ] || [ -z "$TUNNEL_USER" ]; then
    echo "未设置 RLCD_TUNNEL_HOST/RLCD_TUNNEL_USER，跳过公网隧道启动"
    return 0
  fi
  : >> "$ROOT_DIR/rlcd_tunnel.log"
  screen -dmS rlcd_tunnel bash -lc "cd '$ROOT_DIR' && env RLCD_LOCAL_PORT='${LOCAL_PORT}' RLCD_REMOTE_BIND_HOST='${REMOTE_BIND_HOST}' RLCD_REMOTE_BIND_PORT='${REMOTE_BIND_PORT}' RLCD_TUNNEL_HOST='${TUNNEL_HOST}' RLCD_TUNNEL_USER='${TUNNEL_USER}' scripts/run_tunnel.sh >> rlcd_tunnel.log 2>&1"
}

verify_services() {
  screen -ls || true
  local local_result=""
  local remote_result=""
  for _ in $(seq 1 12); do
    local_result=$(curl --max-time 10 -sS -o /tmp/rlcd-local-frame.bin -w "local %{http_code} %{size_download}" "http://127.0.0.1:${LOCAL_PORT}/frame.bin?battery=88" || true)
    echo "$local_result"
    if [[ "$local_result" == "local 200 15000" ]]; then
      break
    fi
    sleep 5
  done
  if [[ "$local_result" != "local 200 15000" ]]; then
    echo "本地 RLCD 服务验证未通过：${local_result}" >&2
    return 1
  fi

  if [ -z "$TUNNEL_HOST" ] || [ -z "$TOKEN_PATH" ]; then
    echo "未设置 RLCD_TUNNEL_HOST/RLCD_TOKEN_PATH，跳过公网入口验证"
    return 0
  fi

  for _ in $(seq 1 12); do
    remote_result=$(curl --max-time 10 -sS -o /tmp/rlcd-remote-frame.bin -w "remote %{http_code} %{size_download}" "http://${TUNNEL_HOST}${TOKEN_PATH}/frame.bin?battery=88" || true)
    echo "$remote_result"
    if [[ "$remote_result" == "remote 200 15000" ]]; then
      return 0
    fi
    sleep 5
  done
  echo "公网 RLCD 入口验证未通过：${remote_result}" >&2
  return 1
}

stop_local
stop_remote_port
start_server
start_tunnel
verify_services
