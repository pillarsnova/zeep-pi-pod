"""Calibration definitions and persistence helpers for ZEEP sensors.

This module owns calibration *data mechanics* only.  It never reads live
hardware and never mutates the application state.  ``app.py`` remains the
orchestrator that authorizes Admin changes and publishes them to connected
clients.  Keeping this boundary small makes calibration rules testable without
starting FastAPI, GPIO, serial readers or MQTT threads.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any, Mapping, Optional

from sensor_contracts import (
    SOUND_DBA_DISPLAY_MAX,
    SOUND_DBA_DISPLAY_MIN,
    SOUND_SENSOR_MODEL,
)
from sound_observability import sound_engineering_snapshot


# Calibration trust is deliberately fail-closed.  Substring matching is unsafe
# here (for example, ``unverified`` contains ``verified``), so only explicitly
# versioned/approved states may turn the Admin badge green.
VERIFIED_SOUND_CALIBRATION_STATES = frozenset({
    "cem_verified",
    "cem_dt_8852_verified",
    "approved_cem_calibration",
    "verified_against_cem_dt_8852",
})
PENDING_SOUND_CALIBRATION_STATES = frozenset({
    "pending",
    "pending_cem_recalibration",
    "pending_cem_recalibration_after_sensor_replacement",
    "sensor_replaced_contract_and_cem_revalidation_required",
})
APPROVED_SOUND_WINDOW_MS = 10_000.0
SOUND_PREVIEW_MIN_OBSERVATIONS = 3


def _first_finite_metric(
    payload: Mapping[str, Any],
    *keys: str,
) -> Optional[float]:
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


# Plain dictionaries are retained at this boundary because the Admin API and
# existing tests expose these fields as JSON.  The source of truth now lives in
# one module instead of being embedded in the server orchestrator.
SENSOR_CALIBRATION_SPECS: dict[str, dict[str, Any]] = {
    "temperature_c": {
        "device": "SHT3x-DIS", "device_key": "sht3x_dis",
        "label": "อุณหภูมิ", "unit": "°C", "config_key": "temperature_c_bias",
        "default": 0.0, "bias_min": -20.0, "bias_max": 20.0,
        "value_min": -40.0, "value_max": 125.0, "step": 0.1,
    },
    "humidity_rh": {
        "device": "SHT3x-DIS", "device_key": "sht3x_dis",
        "label": "ความชื้น", "unit": "%RH", "config_key": "humidity_rh_bias",
        "default": 0.0, "bias_min": -20.0, "bias_max": 20.0,
        "value_min": 0.0, "value_max": 100.0, "step": 0.1,
    },
    "lux": {
        "device": "OPT3001", "device_key": "opt3001",
        "label": "ความสว่าง", "unit": "lux", "config_key": "lux_bias",
        "default": 0.0, "bias_min": -5000.0, "bias_max": 5000.0,
        "value_min": 0.0, "value_max": 83865.0, "step": 0.1,
    },
    "co2_ppm": {
        "device": "MH-Z19C", "device_key": "mhz19c",
        "label": "คาร์บอนไดออกไซด์", "unit": "ppm", "config_key": "co2_ppm_bias",
        "default": 0.0, "bias_min": -2000.0, "bias_max": 2000.0,
        "value_min": 400.0, "value_max": 5000.0, "step": 1.0,
    },
    "pm1_0_ug_m3": {
        "device": "PMS7003", "device_key": "pms7003",
        "label": "PM1.0", "unit": "µg/m³", "config_key": "pm1_0_bias",
        "default": 0.0, "bias_min": -500.0, "bias_max": 500.0,
        "value_min": 0.0, "value_max": 1000.0, "step": 0.1,
    },
    "pm2_5_ug_m3": {
        "device": "PMS7003", "device_key": "pms7003",
        "label": "PM2.5", "unit": "µg/m³", "config_key": "pm2_5_bias",
        "default": 0.0, "bias_min": -500.0, "bias_max": 500.0,
        "value_min": 0.0, "value_max": 1000.0, "step": 0.1,
    },
    "pm10_ug_m3": {
        "device": "PMS7003", "device_key": "pms7003",
        "label": "PM10", "unit": "µg/m³", "config_key": "pm10_bias",
        "default": 0.0, "bias_min": -500.0, "bias_max": 500.0,
        "value_min": 0.0, "value_max": 1000.0, "step": 0.1,
    },
}


def load_calibration(path: Path) -> dict[str, Any]:
    """Load a JSON calibration document; an absent file means defaults."""
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return {}
    if not isinstance(data, dict):
        raise ValueError("calibration document must contain a JSON object")
    return data


def persist_calibration(path: Path, data: Mapping[str, Any]) -> None:
    """Atomically replace calibration JSON so power loss cannot truncate it."""
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(dict(data), handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def resolve_biases(
    calibration: Mapping[str, Any],
    *,
    humidity_bias: float,
    humidity_source: str,
) -> tuple[dict[str, float], dict[str, str]]:
    """Resolve and validate every editable calibration parameter once."""
    biases: dict[str, float] = {}
    sources: dict[str, str] = {}
    for metric, spec in SENSOR_CALIBRATION_SPECS.items():
        if metric == "humidity_rh":
            value, source = humidity_bias, humidity_source
        elif spec["config_key"] in calibration:
            value, source = float(calibration[spec["config_key"]]), "calibration.json"
        else:
            value, source = float(spec["default"]), "default"
        if not math.isfinite(value) or not spec["bias_min"] <= value <= spec["bias_max"]:
            raise RuntimeError(
                f"{spec['config_key']} must be finite and between "
                f"{spec['bias_min']} and {spec['bias_max']}"
            )
        biases[metric] = float(value)
        sources[metric] = source
    return biases, sources


def apply_additive_bias(
    metric: str,
    raw_value: Optional[float],
    *,
    biases: Mapping[str, float],
) -> Optional[float]:
    """Apply a bounded additive adjustment to an already validated reading."""
    if raw_value is None:
        return None
    spec = SENSOR_CALIBRATION_SPECS.get(metric)
    if spec is None:
        return raw_value
    adjusted = float(raw_value) + float(biases.get(metric, 0.0))
    adjusted = min(float(spec["value_max"]), max(float(spec["value_min"]), adjusted))
    return round(adjusted, 2)


def _sound_pipeline_state(
    measurement_valid: bool,
    device: Mapping[str, Any],
    engineering: Mapping[str, Any],
) -> str:
    """Classify transport/PCM health separately from CEM calibration."""
    device_status = str(device.get("status") or "").strip().lower()
    if device_status == "offline":
        return "offline"
    if device_status in {"stale", "held", "warming"}:
        return "stale"
    if device_status == "fault":
        return "sensor_fault"
    if measurement_valid:
        return "valid"

    flags = {
        item["key"]: item["value"]
        for item in engineering.get("flags", [])
    }
    raw_is_healthy = bool(
        flags.get("capture_ok") is True
        and flags.get("signal_valid") is True
        and flags.get("stuck_zero") is not True
        and flags.get("stuck_constant") is not True
    )
    return "raw_ok_output_blocked" if raw_is_healthy else "invalid"


def sound_calibration_state(
    calibration: Mapping[str, Any] | None,
) -> str:
    """Report CEM provenance without treating a firmware flag as approval."""
    processing = calibration or {}
    status = str(
        processing.get("calibration_status")
        or processing.get("status")
        or ""
    ).strip().lower()
    if status in VERIFIED_SOUND_CALIBRATION_STATES:
        return "verified"
    if status in PENDING_SOUND_CALIBRATION_STATES:
        return "pending"
    return "unknown"


def sound_runtime_policy(
    calibration: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Translate approved provenance into fail-closed runtime gates."""
    processing = calibration or {}
    configured_window = processing.get("required_window_ms")
    try:
        required_window_ms = float(configured_window)
    except (TypeError, ValueError):
        required_window_ms = float("nan")
    window_contract_valid = bool(
        not isinstance(configured_window, bool)
        and math.isfinite(required_window_ms)
        and required_window_ms == APPROVED_SOUND_WINDOW_MS
    )
    return {
        "sound_required_window_ms": APPROVED_SOUND_WINDOW_MS,
        "sound_calibration_verified": (
            sound_calibration_state(processing) == "verified"
            and window_contract_valid
        ),
    }


def sound_preview_policy(
    calibration: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Authorize a display-only ESP32 level after three reviewed packets.

    This policy is deliberately independent from the CEM/LAeq health gate.
    It only permits a finite firmware value to be shown as provisional when
    the configured microphone identity and three-packet smoke test are
    recorded in ``calibration.json``. It never approves Session recording,
    scoring, environment grading or automatic control.
    """
    processing = calibration or {}
    observation = processing.get("sensor_replacement_observation")
    if not isinstance(observation, Mapping):
        observation = {}
    samples = observation.get("firmware_dba_samples")
    samples = samples if isinstance(samples, list) else []
    finite_samples = [
        float(value)
        for value in samples
        if (
            not isinstance(value, bool)
            and isinstance(value, (int, float))
            and math.isfinite(float(value))
            and SOUND_DBA_DISPLAY_MIN <= float(value) <= SOUND_DBA_DISPLAY_MAX
        )
    ]
    model_matches = (
        observation.get("configured_sensor_model") == SOUND_SENSOR_MODEL
    )
    decision_matches = (
        observation.get("firmware_dba_decision")
        == "display_as_provisional_only_do_not_score"
    )
    profile = str(observation.get("profile") or "").strip()
    return {
        "sound_preview_enabled": bool(
            model_matches
            and decision_matches
            and profile
            and len(finite_samples) >= SOUND_PREVIEW_MIN_OBSERVATIONS
        ),
        "sound_preview_evidence_count": len(finite_samples),
        "sound_preview_profile": profile or None,
    }


def sound_inspector_channel(
    hub1: Mapping[str, Any],
    environment: Mapping[str, Any],
    device: Mapping[str, Any],
    calibration: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Describe validated LAeq and Admin-only signed PCM diagnostics."""
    measurement_valid = hub1.get("sound_measurement_valid") is True
    firmware_laeq = _first_finite_metric(
        hub1,
        "sound_dba_firmware_est",
        "sound_laeq_dba",
        "sound_dba",
    )
    engineering = sound_engineering_snapshot(hub1, device)
    return {
        "metric": "sound_dba_est", "device": SOUND_SENSOR_MODEL,
        "device_key": "sph0645", "label": "ระดับเสียง LAeq(A)",
        "unit": "dBA est.", "raw_unit": "dBA est.",
        "raw": firmware_laeq, "bias": 0.0,
        "calibrated": environment.get("sound_dba_est"),
        "editable": False, "source": device.get("source_label"),
        "status": device.get("status", "offline"),
        "data_age_s": device.get("data_age_s"),
        "formula": "ESP32: I2S alignment → A-weighting → LAeq",
        "firmware_value": firmware_laeq,
        "measurement_valid": measurement_valid,
        "invalid_reason": hub1.get("sound_invalid_reason"),
        "pipeline_state": _sound_pipeline_state(
            measurement_valid,
            device,
            engineering,
        ),
        "calibration_state": sound_calibration_state(calibration),
        "engineering": engineering,
        "lock_reason": (
            "Firmware LAeq(A) ใช้ตรวจวินิจฉัยเท่านั้น · ค่าเสียงฝั่งสุขภาพ"
            "และผู้ใช้ต้องผ่านสัญญา 10 วินาทีและสอบเทียบ CEM DT-8852"
        ),
    }
