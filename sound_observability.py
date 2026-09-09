"""Consumer redaction boundary for Sensor Hub engineering telemetry."""

from __future__ import annotations

from typing import Any


CONSUMER_ESP32_FIELDS = (
    "connected",
    "last_update",
    "data_age_s",
    "fallback_active",
    "fallback_reason",
    "error",
    "sensor_status",
    "sound_measurement_valid",
    "sound_status",
    "sound_invalid_reason",
)


def sanitize_consumer_sound(sensor: dict[str, Any]) -> None:
    """Remove engineering telemetry from a detached consumer snapshot."""
    environment = sensor.get("environment") or {}
    environment.pop("raw_values", None)
    environment.pop("calibration", None)
    environment.pop("sound_dbfs_raw", None)
    for device in (environment.get("devices") or {}).values():
        if not isinstance(device, dict):
            continue
        device.pop("diagnostics", None)
        device.pop("invalid_values", None)

    esp32 = sensor.get("esp32") or {}
    sensor["esp32"] = {
        key: esp32.get(key)
        for key in CONSUMER_ESP32_FIELDS
        if key in esp32
    }
