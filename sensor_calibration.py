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


def sound_inspector_channel(
    hub1: Mapping[str, Any],
    environment: Mapping[str, Any],
    device: Mapping[str, Any],
) -> dict[str, Any]:
    """Describe the firmware-owned sound pipeline for Admin inspection."""
    return {
        "metric": "sound_dba_est", "device": "SPH0645",
        "device_key": "sph0645", "label": "ระดับเสียง LAeq(A)",
        "unit": "dBA est.", "raw_unit": "dBFS",
        "raw": hub1.get("sound_dbfs"), "bias": 0.0,
        "calibrated": environment.get("sound_dba_est"),
        "editable": False, "source": device.get("source_label"),
        "status": device.get("status", "offline"),
        "data_age_s": device.get("data_age_s"),
        "formula": "ESP32: I2S alignment → A-weighting → LAeq",
        "firmware_value": hub1.get("sound_laeq_dba"),
        "measurement_valid": hub1.get("sound_measurement_valid") is True,
        "invalid_reason": hub1.get("sound_invalid_reason"),
        "lock_reason": "dBFS เป็น dBA ไม่ได้; ต้องคำนวณ LAeq(A) ที่ ESP32",
    }
