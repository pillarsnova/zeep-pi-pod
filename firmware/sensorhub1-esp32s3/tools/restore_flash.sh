#!/usr/bin/env bash

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=flash_common.sh
source "$SCRIPT_DIR/flash_common.sh"

require_command
assert_pod_unoccupied

BACKUP_DIR="${1:?usage: restore_flash.sh BACKUP_DIRECTORY}"
IMAGE="$BACKUP_DIR/esp32s3-full-flash-16mb.bin"
[[ -f "$IMAGE" && -f "$BACKUP_DIR/SHA256SUMS" ]] || {
  echo "ERROR: verified full-Flash backup is incomplete" >&2
  exit 5
}
(cd "$BACKUP_DIR" && sha256sum --check SHA256SUMS)

[[ "${CONFIRM_RESTORE:-}" == "$EXPECTED_MAC" ]] || {
  echo "ERROR: set CONFIRM_RESTORE=$EXPECTED_MAC to authorize restore" >&2
  exit 6
}

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
"$ESPTOOL" --port "$PORT" write-flash 0 "$IMAGE"
"$ESPTOOL" --port "$PORT" verify-flash 0 "$IMAGE"
echo "RESTORE_VERIFIED=$IMAGE"
