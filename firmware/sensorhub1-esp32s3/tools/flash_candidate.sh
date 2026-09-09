#!/usr/bin/env bash

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=flash_common.sh
source "$SCRIPT_DIR/flash_common.sh"

require_command
assert_pod_unoccupied

ARTIFACT_DIR="${1:?usage: flash_candidate.sh ARTIFACT_DIR CEM_RESULT_JSON}"
CEM_RESULT="${2:?usage: flash_candidate.sh ARTIFACT_DIR CEM_RESULT_JSON}"
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

python3 - "$CEM_RESULT" "$ARTIFACT_DIR/firmware.bin" <<'PY'
import hashlib
import json
import pathlib
import sys

result_path = pathlib.Path(sys.argv[1])
firmware_path = pathlib.Path(sys.argv[2])
result = json.loads(result_path.read_text(encoding="utf-8"))
digest = hashlib.sha256(firmware_path.read_bytes()).hexdigest()
if result.get("decision") != "PASS":
    raise SystemExit("ERROR: CEM acceptance decision is not PASS")
if result.get("firmware_sha256") != digest:
    raise SystemExit("ERROR: CEM result belongs to a different firmware image")
if result.get("meter", {}).get("model") != "CEM DT-8852":
    raise SystemExit("ERROR: CEM result does not identify the approved meter")
PY

[[ "${CONFIRM_FLASH:-}" == "$EXPECTED_MAC" ]] || {
  echo "ERROR: set CONFIRM_FLASH=$EXPECTED_MAC to authorize Production Flash" >&2
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
"$ESPTOOL" --port "$PORT" write-flash \
  0x0000 "$ARTIFACT_DIR/bootloader.bin" \
  0x8000 "$ARTIFACT_DIR/partitions.bin" \
  0xe000 "$ARTIFACT_DIR/boot_app0.bin" \
  0x10000 "$ARTIFACT_DIR/firmware.bin"
"$ESPTOOL" --port "$PORT" verify-flash \
  0x0000 "$ARTIFACT_DIR/bootloader.bin" \
  0x8000 "$ARTIFACT_DIR/partitions.bin" \
  0xe000 "$ARTIFACT_DIR/boot_app0.bin" \
  0x10000 "$ARTIFACT_DIR/firmware.bin"
echo "CANDIDATE_FLASH_VERIFIED=$ARTIFACT_DIR"
