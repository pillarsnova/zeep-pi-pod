"""Canonical normalization rules for Sensor Hub 1 payloads."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from sensors.contracts import SOUND_SENSOR_MODEL
from sensors.sound import valid_sound_level
from sensors.values import first_numeric

HUB1_ALIASES: dict[str, tuple[str, ...]] = {
    "temperature": ("temperature_c", "temperature", "temp", "temp_c"),
    "humidity": ("humidity", "hum", "rh", "humidity_rh"),
    "lux": ("lux", "light", "illuminance"),
    "co2": ("co2", "co2_ppm", "carbon_dioxide"),
    "sound_dbfs": ("sound_dbfs",),
    "sound_rms": ("sound_rms",),
    "sound_peak": ("sound_peak",),
}


def _copy_aliases(
    payload: Mapping[str, Any],
    result: dict[str, Any],
) -> None:
    for target, keys in HUB1_ALIASES.items():
        value = first_numeric(payload, keys)
        if value is not None:
            result[target] = value


def _clear_legacy_sound_fields(result: dict[str, Any]) -> None:
    for key in (
        "sound_dba_est",
        "sound_dba_firmware_est",
        "sound_preview_evidence_count",
        "sound_dba",
        "sound_invalid_value",
    ):
        result.pop(key, None)


def _sanitize_sound_diagnostics(result: dict[str, Any]) -> None:
    for key in (
        "sound_dbfs",
        "sound_dbfs_a",
        "sound_rms",
        "sound_rms_a",
        "sound_peak",
        "sound_peak_a",
        "sound_sample_rate_hz",
        "sound_samples",
        "sound_window_ms",
        "sound_calibration_offset_db",
        "sound_reference_spl_db",
        "sound_sensitivity_dbfs",
        "sound_datasheet_offset_db",
        "sound_rms_correction_db",
        "sound_laeq_dba",
        "sound_feature_window_ms",
        "sound_feature_sequence",
        "sound_feature_age_ms",
        "sound_alignment_errors",
        "sound_debug_dbfs_right24",
        "sound_debug_dbfs_high16",
        "sound_debug_dbfs_low16",
        "sound_debug_raw_min",
        "sound_debug_raw_max",
        "sound_debug_raw_changes",
        "sound_debug_low_byte_nonzero",
    ):
        value = result.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            result.pop(key, None)
            continue
        try:
            finite = math.isfinite(float(value))
        except OverflowError:
            finite = False
        if not finite:
            result.pop(key, None)


def _sound_value(
    payload: Mapping[str, Any],
    normalized: Mapping[str, Any],
    *,
    display_min: float,
    display_max: float,
) -> tuple[float | None, str | None]:
    raw = payload.get("sound_dba")
    sound_dba = None
    overflow = False
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        try:
            sound_dba = float(raw)
        except OverflowError:
            overflow = True
    if raw is None:
        firmware_reason = str(payload.get("sound_invalid_reason") or "").strip()
        reason = firmware_reason or (
            "legacy_dbfs_only"
            if first_numeric(normalized, ("sound_dbfs",)) is not None
            else "missing_sound_dba"
        )
    elif overflow:
        reason = "sound_dba_out_of_range"
    elif sound_dba is None:
        reason = "invalid_sound_dba_type"
    elif not math.isfinite(sound_dba):
        reason = "non_finite_sound_dba"
    elif not display_min <= sound_dba <= display_max:
        reason = "sound_dba_out_of_range"
    else:
        reason = None
    return sound_dba, reason


def _publish_valid_sound(
    result: dict[str, Any],
    sound_dba: float,
) -> None:
    result["sound_dba"] = sound_dba
    result["sound_dba_est"] = sound_dba
    result["sound_measurement_valid"] = True
    result["sound_status"] = "valid"
    result["sound_processing_source"] = "esp32_sound_dba_direct"
    result.pop("sound_invalid_reason", None)
    result.pop("sound_invalid_value", None)

    sensor_status = result.get("sensor_status")
    if isinstance(sensor_status, Mapping):
        sensor_status = dict(sensor_status)
        if sensor_status.get("sph0645") is False:
            result["sound_firmware_reported_status"] = False
        sensor_status["sph0645"] = True
        result["sensor_status"] = sensor_status

    diagnostics = result.get("sensor_diagnostics")
    if not isinstance(diagnostics, Mapping):
        return
    diagnostics = dict(diagnostics)
    microphone = diagnostics.get("sph0645")
    if isinstance(microphone, Mapping):
        microphone = dict(microphone)
        if microphone.get("reason"):
            result["sound_firmware_reported_reason"] = microphone["reason"]
        diagnostics["sph0645"] = {
            **microphone,
            "status": "live",
            "reason": None,
        }
    result["sensor_diagnostics"] = diagnostics


def normalize_hub1_sensor(
    payload: Mapping[str, Any],
    *,
    sound_display_min: float,
    sound_display_max: float,
) -> dict[str, Any]:
    """Copy direct ESP32 ``sound_dba`` into the canonical Pi channel."""
    result = dict(payload)
    _copy_aliases(payload, result)
    _clear_legacy_sound_fields(result)
    _sanitize_sound_diagnostics(result)
    result["sound_sensor_model"] = SOUND_SENSOR_MODEL
    result["sound_measurement_valid"] = False
    result["sound_value_held"] = False

    sound_dba, invalid_reason = _sound_value(
        payload,
        result,
        display_min=sound_display_min,
        display_max=sound_display_max,
    )
    if invalid_reason is not None:
        result["sound_status"] = "invalid"
        result["sound_invalid_reason"] = invalid_reason
        if sound_dba is not None and math.isfinite(sound_dba):
            result["sound_invalid_value"] = sound_dba
        return result

    _publish_valid_sound(result, sound_dba)
    return result


def hold_last_valid_sound(
    current: dict[str, Any],
    previous: Mapping[str, Any],
    *,
    display_min: float,
    display_max: float,
) -> dict[str, Any]:
    """Retain prior sound for Admin diagnostics without presenting it Live."""
    value = current.get("sound_dba_est")
    if current.get("sound_measurement_valid") is True and valid_sound_level(
        value, display_min, display_max
    ):
        current["sound_value_held"] = False
        return current
    old = previous.get("sound_dba_est")
    if valid_sound_level(old, display_min, display_max):
        current["sound_last_valid_dba"] = old
    current.pop("sound_dba_est", None)
    current["sound_value_held"] = False
    current["sound_measurement_valid"] = False
    current.setdefault("sound_status", "invalid")
    current.setdefault("sound_invalid_reason", "untrusted_sound_measurement")
    return current
