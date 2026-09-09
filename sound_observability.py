"""Admin-only observability for SPH0645 engineering telemetry.

The sound pressure value shown to users has a strict, separate contract in
``sensor_runtime``. This module only normalises diagnostic names emitted by
released and candidate Sensor Hub 1 firmware, so signed dBFS and PCM health
can be inspected without ever becoming a health-facing dBA value.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence


FieldSpec = tuple[str, str, Sequence[str], str, int]


SOUND_ENGINEERING_FIELDS: tuple[FieldSpec, ...] = (
    ("level", "RAW Z", ("sound_dbfs",), "dBFS", 2),
    (
        "level",
        "RAW A",
        ("sound_dbfs_a", "sound_a_weighted_dbfs"),
        "dBFS(A)",
        2,
    ),
    ("level", "RMS Z", ("sound_rms",), "FS", 6),
    ("level", "RMS A", ("sound_rms_a",), "FS", 6),
    ("level", "PEAK Z", ("sound_peak",), "FS", 6),
    ("level", "PEAK A", ("sound_peak_a",), "FS", 6),
    (
        "capture",
        "Sample rate",
        ("sound_sample_rate_hz",),
        "Hz",
        0,
    ),
    ("capture", "Samples", ("sound_samples",), "samples", 0),
    ("capture", "Window", ("sound_window_ms",), "ms", 0),
    ("capture", "Zero ratio", ("mic_zero_ratio",), "ratio", 4),
    ("capture", "Change ratio", ("mic_change_ratio",), "ratio", 4),
    (
        "capture",
        "Zero samples",
        ("mic_zero_samples", "sound_zero_samples"),
        "samples",
        0,
    ),
    (
        "capture",
        "Changed samples",
        ("mic_raw_changes",),
        "samples",
        0,
    ),
    (
        "capture",
        "Repeated samples",
        ("sound_repeated_samples",),
        "samples",
        0,
    ),
    (
        "capture",
        "Clipped",
        ("raw_clip_count", "sound_clipped_samples"),
        "samples",
        0,
    ),
    (
        "capture",
        "Read errors",
        ("mic_read_errors", "sound_read_errors"),
        "count",
        0,
    ),
    (
        "calibration",
        "Firmware LAeq(A)",
        ("sound_laeq_dba", "sound_dba"),
        "dBA est.",
        2,
    ),
    (
        "calibration",
        "Firmware offset",
        ("sound_calibration_offset_db",),
        "dB",
        2,
    ),
)


SOUND_ENGINEERING_FLAGS: tuple[
    tuple[str, str, Sequence[str], bool], ...
] = (
    ("capture_ok", "Capture", ("mic_capture_ok", "stream_active"), True),
    (
        "signal_valid",
        "Signal",
        ("mic_signal_valid", "sound_valid", "measurement_valid"),
        True,
    ),
    ("stuck_zero", "Stuck zero", ("mic_stuck_zero",), False),
    ("stuck_constant", "Stuck constant", ("mic_stuck_constant",), False),
)


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
    "sound_window_ms",
)


def _first_finite(payload: Mapping[str, Any], keys: Sequence[str]) -> float | None:
    for key in keys:
        value = payload.get(key)
        if value is None or isinstance(value, bool):
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            return number
    return None


def _first_boolean(
    sources: Sequence[Mapping[str, Any]],
    keys: Sequence[str],
) -> bool | None:
    for source in sources:
        for key in keys:
            value = source.get(key)
            if isinstance(value, bool):
                return value
    return None


def sound_engineering_snapshot(
    hub1: Mapping[str, Any],
    device: Mapping[str, Any],
) -> dict[str, Any]:
    """Return one allowlisted, firmware-compatible Admin diagnostic view."""
    nested = device.get("diagnostics")
    diagnostics = nested if isinstance(nested, Mapping) else {}
    fields = []
    for group, label, aliases, unit, digits in SOUND_ENGINEERING_FIELDS:
        fields.append({
            "key": aliases[0],
            "label": label,
            "value": _first_finite(hub1, aliases),
            "unit": unit,
            "digits": digits,
            "group": group,
        })
    flags = []
    for key, label, aliases, healthy_value in SOUND_ENGINEERING_FLAGS:
        value = _first_boolean((hub1, diagnostics), aliases)
        flags.append({
            "key": key,
            "label": label,
            "value": value,
            "healthy": None if value is None else value is healthy_value,
        })
    return {
        "fields": fields,
        "flags": flags,
        "firmware_dba_calibrated": _first_boolean(
            (hub1, diagnostics),
            ("sound_dba_calibrated",),
        ),
        "profile": hub1.get("profile"),
        "firmware_version": hub1.get("firmware_version"),
        "sequence": hub1.get("seq", hub1.get("sound_window_sequence")),
        "boot_id": hub1.get("boot_id"),
    }


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
