#!/usr/bin/env bash

set -euo pipefail

readonly EXPECTED_CHIP="ESP32-S3"
readonly EXPECTED_FLASH_BYTES=16777216
readonly DEFAULT_EXPECTED_MAC="44:1b:f6:8c:0c:54"
readonly DEFAULT_PORT=\
"/dev/serial/by-id/usb-Espressif_USB_JTAG_serial_debug_unit_44:1B:F6:8C:0C:54-if00"

ESPTOOL="${ESPTOOL:-/home/pod1/.venvs/esptool/bin/esptool}"
PORT="${PORT:-$DEFAULT_PORT}"
EXPECTED_MAC="${EXPECTED_MAC:-$DEFAULT_EXPECTED_MAC}"
ZEEP_SERVICE="${ZEEP_SERVICE:-zeep-pod.service}"

require_command() {
  if [[ ! -x "$ESPTOOL" ]]; then
    echo "ERROR: esptool not executable: $ESPTOOL" >&2
    exit 2
  fi
  command -v curl >/dev/null || {
    echo "ERROR: curl is required" >&2
    exit 2
  }
}

assert_device_identity() {
  [[ -e "$PORT" ]] || {
    echo "ERROR: serial device not found: $PORT" >&2
    exit 3
  }
  local chip_output
  chip_output="$($ESPTOOL --port "$PORT" chip-id 2>&1)"
  grep -q "$EXPECTED_CHIP" <<<"$chip_output" || {
    echo "ERROR: expected $EXPECTED_CHIP" >&2
    echo "$chip_output" >&2
    exit 3
  }
  grep -qi "$EXPECTED_MAC" <<<"$chip_output" || {
    echo "ERROR: expected MAC $EXPECTED_MAC" >&2
    echo "$chip_output" >&2
    exit 3
  }
}

assert_pod_unoccupied() {
  local status
  status="$(curl --fail --silent --max-time 3 \
    http://127.0.0.1:8000/api/public/status)" || {
      echo "ERROR: cannot verify Pod occupancy; refusing Flash operation" >&2
      exit 4
    }
  if ! grep -Eq '"occupied"[[:space:]]*:[[:space:]]*false' <<<"$status"; then
    echo "ERROR: Pod is occupied or status is ambiguous; refusing Flash operation" >&2
    echo "$status" >&2
    exit 4
  fi
}

stop_service() {
  sudo systemctl stop "$ZEEP_SERVICE"
}

start_service() {
  sudo systemctl start "$ZEEP_SERVICE"
}
