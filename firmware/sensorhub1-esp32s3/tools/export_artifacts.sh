#!/usr/bin/env bash

set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENVIRONMENT="${1:-release}"
BUILD_DIR="$PROJECT_DIR/.pio/build/$ENVIRONMENT"
OUTPUT_DIR="$PROJECT_DIR/dist/$ENVIRONMENT"

mkdir -p "$OUTPUT_DIR"
cp "$BUILD_DIR/bootloader.bin" "$OUTPUT_DIR/"
cp "$BUILD_DIR/partitions.bin" "$OUTPUT_DIR/"
cp "$BUILD_DIR/firmware.bin" "$OUTPUT_DIR/"

BOOT_APP0="$(find "$PROJECT_DIR/.pio-core/packages" -path '*/partitions/boot_app0.bin' \
  -print -quit)"
[[ -n "$BOOT_APP0" ]] || {
  echo "ERROR: boot_app0.bin not found in PlatformIO packages" >&2
  exit 2
}
cp "$BOOT_APP0" "$OUTPUT_DIR/boot_app0.bin"

if command -v sha256sum >/dev/null; then
  (cd "$OUTPUT_DIR" && sha256sum \
    bootloader.bin partitions.bin boot_app0.bin firmware.bin >MANIFEST.sha256)
else
  (cd "$OUTPUT_DIR" && shasum -a 256 \
    bootloader.bin partitions.bin boot_app0.bin firmware.bin >MANIFEST.sha256)
fi
echo "$OUTPUT_DIR"
