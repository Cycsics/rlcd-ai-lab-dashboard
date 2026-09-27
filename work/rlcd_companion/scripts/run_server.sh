#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVER_DIR="$ROOT_DIR/server"

cd "$SERVER_DIR"

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
pip install -q -r requirements.txt

HOST="${RLCD_HOST:-0.0.0.0}"
PORT="${RLCD_PORT:-8787}"
export RLCD_FEISHU_ENABLED="${RLCD_FEISHU_ENABLED:-1}"

echo "启动 RLCD 本地服务：http://127.0.0.1:${PORT}/preview.png"
echo "真实飞书模式：RLCD_FEISHU_ENABLED=${RLCD_FEISHU_ENABLED}"

exec uvicorn app:app --host "$HOST" --port "$PORT"
