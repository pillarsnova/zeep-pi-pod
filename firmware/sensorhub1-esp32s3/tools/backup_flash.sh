#!/usr/bin/env bash

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=flash_common.sh
source "$SCRIPT_DIR/flash_common.sh"

require_command
assert_pod_unoccupied

BACKUP_ROOT="${BACKUP_ROOT:-/home/pod1/firmware-backups/sensorhub1}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUTPUT_DIR="${1:-$BACKUP_ROOT/$STAMP}"
IMAGE="$OUTPUT_DIR/esp32s3-full-flash-16mb.bin"
mkdir -p "$OUTPUT_DIR"

restart_required=false
cleanup() {
  if [[ "$restart_required" == true ]]; then
    start_service
  fi
}
trap cleanup EXIT

stop_service
restart_required=true
assert_device_identity

"$ESPTOOL" --port "$PORT" read-flash \
  0 "$EXPECTED_FLASH_BYTES" "$IMAGE" \
  >"$OUTPUT_DIR/read-flash.log" 2>&1

actual_size="$(stat --format='%s' "$IMAGE")"
[[ "$actual_size" == "$EXPECTED_FLASH_BYTES" ]] || {
  echo "ERROR: backup size $actual_size, expected $EXPECTED_FLASH_BYTES" >&2
  exit 5
}

(cd "$OUTPUT_DIR" && sha256sum "$(basename "$IMAGE")" >SHA256SUMS)
"$ESPTOOL" --port "$PORT" verify-flash 0 "$IMAGE" \
  >"$OUTPUT_DIR/verify-flash.log" 2>&1

{
  echo "created_utc=$STAMP"
  echo "chip=$EXPECTED_CHIP"
  echo "mac=$EXPECTED_MAC"
  echo "flash_bytes=$EXPECTED_FLASH_BYTES"
  echo "port=$PORT"
} >"$OUTPUT_DIR/HARDWARE.txt"

echo "BACKUP_VERIFIED=$OUTPUT_DIR"
