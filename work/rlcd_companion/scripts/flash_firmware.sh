#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
ARDUINO_CONFIG="$PROJECT_ROOT/work/tools/arduino/arduino-cli.yaml"
LIBRARIES="$PROJECT_ROOT/work/vendor/ESP32-S3-RLCD-4.2/01_Arduino_Libraries"
SKETCH="$PROJECT_ROOT/work/rlcd_companion/firmware/rlcd_client"
FQBN="${FQBN:-esp32:esp32:esp32s3:CDCOnBoot=cdc,FlashSize=16M,PartitionScheme=app3M_fat9M_16MB,PSRAM=opi}"
PORT="${PORT:-/dev/cu.usbmodem2101}"

if [ -n "${ARDUINO_CLI:-}" ] && [ -x "$ARDUINO_CLI" ]; then
  ARDUINO_CLI="$ARDUINO_CLI"
elif [ -x "$PROJECT_ROOT/work/tools/bin/arduino-cli" ]; then
  ARDUINO_CLI="$PROJECT_ROOT/work/tools/bin/arduino-cli"
elif command -v arduino-cli >/dev/null 2>&1; then
  ARDUINO_CLI="$(command -v arduino-cli)"
else
  echo "找不到 arduino-cli。请安装 Arduino CLI、设置 ARDUINO_CLI，或放到 work/tools/bin/arduino-cli。" >&2
  exit 2
fi

CONFIG_ARGS=()
if [ -f "$ARDUINO_CONFIG" ]; then
  CONFIG_ARGS=(--config-file "$ARDUINO_CONFIG")
fi

if [ ! -f "$SKETCH/config.h" ]; then
  echo "缺少 $SKETCH/config.h"
  echo "请先运行：work/rlcd_companion/scripts/write_firmware_config.sh"
  exit 1
fi

exec "$ARDUINO_CLI" \
  "${CONFIG_ARGS[@]}" \
  compile \
  --upload \
  --fqbn "$FQBN" \
  --port "$PORT" \
  --libraries "$LIBRARIES" \
  "$SKETCH"
