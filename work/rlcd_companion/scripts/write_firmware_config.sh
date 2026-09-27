#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_PATH="${CONFIG_PATH:-$ROOT_DIR/firmware/rlcd_client/config.h}"

if [ -z "${WIFI_SSID:-}" ]; then
  read -r -p "Wi-Fi 名称: " WIFI_SSID
fi

if [ -z "${WIFI_PASSWORD:-}" ]; then
  read -r -s -p "Wi-Fi 密码: " WIFI_PASSWORD
  echo
fi

if [ -n "${HOTSPOT_SSID_CONTAINS:-}" ] && [ -z "${HOTSPOT_PASSWORD:-}" ]; then
  read -r -s -p "手机热点密码: " HOTSPOT_PASSWORD
  echo
fi

FRAME_BASE_URL="${FRAME_BASE_URL:-}"
MAC_IP="${MAC_IP:-}"
if [ -z "$FRAME_BASE_URL" ]; then
  MAC_IP="${MAC_IP:-$(ipconfig getifaddr en0 2>/dev/null || true)}"
  if [ -z "$MAC_IP" ]; then
    read -r -p "Mac 局域网 IP: " MAC_IP
  fi
fi

PORT="${RLCD_PORT:-8787}"
REFRESH_MS="${FRAME_REFRESH_MS:-3000}"
PET_ANIMATION_MS="${PET_ANIMATION_MS:-700}"

python3 - "$CONFIG_PATH" "$WIFI_SSID" "$WIFI_PASSWORD" "$MAC_IP" "$PORT" "$REFRESH_MS" "$PET_ANIMATION_MS" "$FRAME_BASE_URL" "${HOTSPOT_SSID_CONTAINS:-}" "${HOTSPOT_PASSWORD:-}" <<'PY'
from pathlib import Path
import sys

(
    path,
    ssid,
    password,
    mac_ip,
    port,
    refresh_ms,
    pet_animation_ms,
    frame_base_url,
    hotspot_ssid_contains,
    hotspot_password,
) = sys.argv[1:]

def c_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')

def c_bool(value: bool) -> str:
    return "true" if value else "false"

def network_line(network_ssid: str, network_password: str, match_contains: bool) -> str:
    return f'  {{"{c_string(network_ssid)}", "{c_string(network_password)}", {c_bool(match_contains)}}},'

base_url = frame_base_url.rstrip("/")
if not base_url:
    base_url = f"http://{mac_ip}:{port}"

networks = [network_line(ssid, password, False)]
if hotspot_ssid_contains:
    networks.append(network_line(hotspot_ssid_contains, hotspot_password, True))
network_block = "\n".join(networks)

content = f"""#pragma once

// 本文件由 scripts/write_firmware_config.sh 生成。
// 注意：这里包含 Wi-Fi 密码，不要提交到公开仓库。

#define WIFI_SSID "{c_string(ssid)}"
#define WIFI_PASSWORD "{c_string(password)}"

static const WifiNetworkConfig WIFI_NETWORKS[] = {{
{network_block}
}};
#define WIFI_NETWORK_COUNT (sizeof(WIFI_NETWORKS) / sizeof(WIFI_NETWORKS[0]))

#define FRAME_URL "{c_string(base_url)}/frame.bin"
#define ACK_URL "{c_string(base_url)}/ack"

#define FRAME_REFRESH_MS {int(refresh_ms)}
#define PET_ANIMATION_MS {int(pet_animation_ms)}
"""

Path(path).write_text(content, encoding="utf-8")
PY

echo "已写入 $CONFIG_PATH"
if [ -n "$FRAME_BASE_URL" ]; then
  echo "ESP32 将请求：${FRAME_BASE_URL%/}/frame.bin"
else
  echo "ESP32 将请求：http://${MAC_IP}:${PORT}/frame.bin"
fi
if [ -n "${HOTSPOT_SSID_CONTAINS:-}" ]; then
  echo "已添加手机热点匹配：SSID 包含 ${HOTSPOT_SSID_CONTAINS}"
fi
