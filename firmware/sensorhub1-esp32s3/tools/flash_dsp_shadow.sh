#!/usr/bin/env bash

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=flash_common.sh
source "$SCRIPT_DIR/flash_common.sh"

APPROVAL_FILE="$SCRIPT_DIR/../compatibility/PRODUCTION_APPROVED.sha256"
if [[ ! -f "$APPROVAL_FILE" ]]; then
  echo "ERROR: DSP shadow is blocked pending original-firmware parity review" >&2
  echo "Read ORIGINAL_FIRMWARE_COMPATIBILITY.md before any new Flash" >&2
  exit 4
fi

require_command
assert_pod_unoccupied

ARTIFACT_DIR="${1:?usage: flash_dsp_shadow.sh ARTIFACT_DIR BACKUP_DIRECTORY}"
BACKUP_DIR="${2:?usage: flash_dsp_shadow.sh ARTIFACT_DIR BACKUP_DIRECTORY}"
BACKUP_IMAGE="$BACKUP_DIR/esp32s3-full-flash-16mb.bin"
required_files=(
  bootloader.bin
  partitions.bin
  boot_app0.bin
  firmware.bin
  MANIFEST.sha256
)
for filename in "${required_files[@]}"; do
  [[ -f "$ARTIFACT_DIR/$filename" ]] || {
    echo "ERROR: missing artifact $filename" >&2
    exit 5
  }
done
(cd "$ARTIFACT_DIR" && sha256sum --check MANIFEST.sha256)
[[ -f "$BACKUP_IMAGE" && -f "$BACKUP_DIR/SHA256SUMS" ]] || {
  echo "ERROR: verified rollback image is incomplete" >&2
  exit 5
}
(cd "$BACKUP_DIR" && sha256sum --check SHA256SUMS)

[[ "${CONFIRM_FLASH:-}" == "$EXPECTED_MAC" ]] || {
  echo "ERROR: set CONFIRM_FLASH=$EXPECTED_MAC to authorize DSP shadow Flash" >&2
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
"$ESPTOOL" --port "$PORT" --baud "$ESPTOOL_BAUD" write_flash \
  0x0000 "$ARTIFACT_DIR/bootloader.bin" \
  0x8000 "$ARTIFACT_DIR/partitions.bin" \
  0xe000 "$ARTIFACT_DIR/boot_app0.bin" \
  0x10000 "$ARTIFACT_DIR/firmware.bin"
"$ESPTOOL" --port "$PORT" --baud "$ESPTOOL_BAUD" verify_flash \
  0x0000 "$ARTIFACT_DIR/bootloader.bin" \
  0x8000 "$ARTIFACT_DIR/partitions.bin" \
  0xe000 "$ARTIFACT_DIR/boot_app0.bin" \
  0x10000 "$ARTIFACT_DIR/firmware.bin"
echo "DSP_SHADOW_FLASH_VERIFIED=$ARTIFACT_DIR"
echo "ROLLBACK_IMAGE_VERIFIED=$BACKUP_IMAGE"
