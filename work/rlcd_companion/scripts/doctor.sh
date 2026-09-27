#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
RLCD_DIR="$ROOT_DIR/work/rlcd_companion"
SERVER_DIR="$RLCD_DIR/server"
FIRMWARE_DIR="$RLCD_DIR/firmware/rlcd_client"
LOCAL_PORT="${RLCD_PORT:-8787}"

fail_count=0
warn_count=0

ok() {
  printf 'OK   %s\n' "$1"
}

warn() {
  warn_count=$((warn_count + 1))
  printf 'WARN %s\n' "$1"
}

fail() {
  fail_count=$((fail_count + 1))
  printf 'FAIL %s\n' "$1"
}

has_cmd() {
  command -v "$1" >/dev/null 2>&1
}

arduino_cli_path() {
  if [ -n "${ARDUINO_CLI:-}" ]; then
    if [ -x "$ARDUINO_CLI" ]; then
      printf '%s\n' "$ARDUINO_CLI"
      return 0
    fi
    return 1
  fi
  local bundled="$ROOT_DIR/work/tools/bin/arduino-cli"
  if [ -x "$bundled" ]; then
    printf '%s\n' "$bundled"
    return 0
  fi
  if has_cmd arduino-cli; then
    command -v arduino-cli
    return 0
  fi
  return 1
}

printf 'RLCD 桌面小伙伴环境检查\n'
printf '项目目录：%s\n\n' "$ROOT_DIR"

if [ -d "$RLCD_DIR" ]; then
  ok "找到 work/rlcd_companion"
else
  fail "缺少 work/rlcd_companion，请确认当前目录是项目根目录"
fi

if has_cmd python3; then
  ok "python3: $(python3 --version 2>&1)"
else
  fail "缺少 python3"
fi

if has_cmd curl; then
  ok "curl 可用"
else
  fail "缺少 curl"
fi

if has_cmd screen; then
  ok "screen 可用，可用于后台常驻服务"
else
  warn "缺少 screen；可以先前台运行服务，但后台常驻会不方便"
fi

if cli="$(arduino_cli_path)"; then
  ok "arduino-cli: $cli"
  if "$cli" core list 2>/tmp/rlcd-arduino-core-list.err | grep -q '^esp32:esp32'; then
    ok "Arduino ESP32 core 已安装"
  else
    warn "未检测到 Arduino ESP32 core；编译前需要安装 esp32:esp32"
  fi
  "$cli" board list >/tmp/rlcd-arduino-board-list.txt 2>/tmp/rlcd-arduino-board-list.err || true
  if [ -s /tmp/rlcd-arduino-board-list.txt ]; then
    printf '检测到的串口/开发板：\n'
    sed -n '1,12p' /tmp/rlcd-arduino-board-list.txt
  else
    warn "arduino-cli board list 没有输出；如果已接设备，优先检查 Type-C 数据线"
  fi
else
  fail "找不到 arduino-cli；请安装 Arduino CLI、设置 ARDUINO_CLI，或放到 work/tools/bin/arduino-cli"
fi

if [ -d "$ROOT_DIR/work/vendor/ESP32-S3-RLCD-4.2/01_Arduino_Libraries" ]; then
  ok "找到微雪 Arduino 库"
else
  fail "缺少 work/vendor/ESP32-S3-RLCD-4.2/01_Arduino_Libraries，固件无法编译"
fi

if [ -f "$FIRMWARE_DIR/config.example.h" ]; then
  ok "找到固件配置模板 config.example.h"
else
  fail "缺少 $FIRMWARE_DIR/config.example.h"
fi

if [ -f "$FIRMWARE_DIR/config.h" ]; then
  ok "找到本地固件配置 config.h"
  warn "config.h 可能包含 Wi-Fi 密码和 token，开源前必须删除或保持 .gitignore 忽略"
else
  warn "还没有 config.h；烧录前运行 work/rlcd_companion/scripts/write_firmware_config.sh"
fi

if [ -f "$SERVER_DIR/requirements.txt" ]; then
  ok "找到 server/requirements.txt"
else
  fail "缺少 server/requirements.txt"
fi

if [ -d "$SERVER_DIR/.venv" ]; then
  ok "找到 server/.venv"
else
  warn "还没有 server/.venv；首次运行 run_server.sh 会自动创建"
fi

if [ -f "$SERVER_DIR/config.example.yaml" ]; then
  ok "找到 Mac 服务配置模板 config.example.yaml"
else
  fail "缺少 server/config.example.yaml"
fi

if [ -f "$SERVER_DIR/config.yaml" ]; then
  ok "找到本地 Mac 服务配置 config.yaml"
  warn "config.yaml 是本地配置，开源前不要提交"
else
  warn "未找到 config.yaml；服务会使用默认配置"
fi

if [ -x /opt/homebrew/bin/lark-cli ]; then
  ok "找到飞书 CLI：/opt/homebrew/bin/lark-cli"
  /opt/homebrew/bin/lark-cli doctor >/tmp/rlcd-lark-doctor.txt 2>/tmp/rlcd-lark-doctor.err || warn "lark-cli doctor 未通过；飞书数据可能不可用"
else
  warn "未找到 /opt/homebrew/bin/lark-cli；可以先用 RLCD_FEISHU_ENABLED=0 跑示例数据"
fi

frame_result="$(curl --max-time 3 -sS -o /tmp/rlcd-doctor-frame.bin -w "%{http_code} %{size_download}" "http://127.0.0.1:${LOCAL_PORT}/frame.bin?battery=88" 2>/tmp/rlcd-doctor-curl.err || true)"
if [ "$frame_result" = "200 15000" ]; then
  ok "本地 /frame.bin 正常：200 15000"
else
  warn "本地服务未就绪或 frame 异常：${frame_result:-无响应}；启动命令：work/rlcd_companion/scripts/run_server.sh"
fi

printf '\n检查完成：%s 个失败，%s 个提醒\n' "$fail_count" "$warn_count"

if [ "$fail_count" -gt 0 ]; then
  exit 1
fi
