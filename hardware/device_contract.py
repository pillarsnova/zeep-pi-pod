"""Versioned health contract shared by every ZEEP embedded device."""

from __future__ import annotations

import math
import time
from typing import Any

DEVICE_CONTRACT_VERSION = "zeep.device-health.v1"


def device_health_contract(
    payload: dict[str, Any] | None,
    *,
    pod_id: str,
    device_id: str,
    device_type: str,
    transport: str,
    stale_seconds: float,
    now: float | None = None,
    board_model: str | None = None,
    board_revision: str | None = None,
    firmware_sha256: str | None = None,
    config_sha256: str | None = None,
) -> dict[str, Any]:
    """Project one adapter payload into the common fleet contract."""
    source = dict(payload or {})
    observed_at = float(now if now is not None else time.time())
    last_update = _number(source.get("last_update"))
    data_age = max(0.0, observed_at - last_update) if last_update else None
    connected = bool(source.get("connected", source.get("online", False)))
    stale = bool(data_age is None or data_age > stale_seconds)
    error = source.get("error") or source.get("mqtt_error")
    quality_valid = bool(connected and not stale and not error)
    return {
        "schema_version": DEVICE_CONTRACT_VERSION,
        "pod_id": pod_id,
        "device_id": str(source.get("device_id") or device_id),
        "device_type": device_type,
        "board": {
            "model": source.get("board_model") or board_model,
            "revision": source.get("board_revision") or board_revision,
        },
        "firmware": {
            "version": source.get("firmware_version") or source.get("profile"),
            "sha256": source.get("firmware_sha256") or firmware_sha256,
            "config_sha256": source.get("config_sha256") or config_sha256,
        },
        "runtime": {
            "boot_id": source.get("boot_id"),
            "sequence": source.get("sequence", source.get("seq")),
            "uptime_ms": source.get("uptime_ms"),
            "rssi_dbm": source.get("rssi", source.get("wifi_rssi")),
            "free_heap": source.get("free_heap"),
        },
        "transport": {
            "kind": transport,
            "connected": connected,
            "data_age_s": round(data_age, 3) if data_age is not None else None,
            "stale_after_s": stale_seconds,
        },
        "quality": {
            "valid": quality_valid,
            "state": "live" if quality_valid else "unavailable",
            "reason": _quality_reason(connected, stale, error),
            "error": str(error) if error else None,
            "reset_count": source.get("reset_count"),
            "packet_loss_count": source.get("packet_loss_count"),
        },
    }


def _quality_reason(connected: bool, stale: bool, error: Any) -> str:
    if error:
        return "device_error"
    if not connected:
        return "disconnected"
    if stale:
        return "stale"
    return "ok"


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None
