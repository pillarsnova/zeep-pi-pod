"""Byte-level parsing for the deployed LSM-800-T BCG sensor."""

from __future__ import annotations

import struct
from typing import Any


def parse_lsm800t_frame(frame: bytes) -> dict[str, Any]:
    """Parse one byte-exact deployed LSM-800-T frame without calibration."""
    if len(frame) != 66:
        raise ValueError(f"LSM-800-T frame must be 66 bytes, got {len(frame)}")
    if frame[:5] != b"Odata" or frame[57:62] != b"Bdata":
        raise ValueError("LSM-800-T frame header mismatch")
    return {
        "samples": list(struct.unpack("<25h", frame[5:55])),
        "sensor_packet_id": int(frame[62]),
        "status_code": int(frame[63]),
        "heart_rate_bpm": int(frame[64]) or None,
        "respiration_raw": int(frame[65]),
        "respiration_rate": (int(frame[65]) / 10.0) or None,
    }


__all__ = ("parse_lsm800t_frame",)
