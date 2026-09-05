"""Pure Sensor Hub normalization and environment composition.

Hardware readers own transport and timing.  This module receives ordinary
dictionaries and produces deterministic values, so the same rules are reused
by Dashboard, Session recording, Safety and offline tests without importing
GPIO, MQTT, serial or FastAPI.
"""

from __future__ import annotations

import math
import time
from typing import Any, Callable, Mapping, Optional, Sequence


HUB1_ALIASES: dict[str, tuple[str, ...]] = {
    "temperature": ("temperature_c", "temperature", "temp", "temp_c"),
    "humidity": ("humidity", "hum", "rh", "humidity_rh"),
    "lux": ("lux", "light", "illuminance"),
    "co2": ("co2", "co2_ppm", "carbon_dioxide"),
    "sound_dbfs": ("sound_dbfs",),
    "sound_laeq_dba": ("sound_laeq_dba", "laeq_dba"),
    "sound_rms": ("sound_rms",),
    "sound_peak": ("sound_peak",),
}

SOUND_REQUIRED_WEIGHTING = "A"
SOUND_REQUIRED_METRIC = "LAEQ"


def first_numeric(obj: Mapping[str, Any], keys: Sequence[str]) -> Optional[float]:
    for key in keys:
        value = obj.get(key)
        if value is None or isinstance(value, bool):
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def source_freshness(payload: Mapping[str, Any], stale_s: float, now: float) -> dict[str, Any]:
    last = payload.get("last_update")
    age = max(0.0, now - last) if isinstance(last, (int, float)) else None
    live = bool(payload.get("connected") and age is not None and age <= stale_s)
    return {
        "live": live,
        "age_s": round(age, 1) if age is not None else None,
        "has_history": last is not None,
    }


def sensor_flag(payload: Mapping[str, Any], keys: Sequence[str]) -> Optional[bool]:
    status = payload.get("sensor_status")
    if not isinstance(status, dict):
        return None
    for key in keys:
        if key in status:
            return bool(status[key])
    return None


def bounded_number(
    payload: Mapping[str, Any], aliases: Sequence[str], low: float, high: float,
) -> tuple[Optional[float], Optional[float]]:
    value = first_numeric(payload, aliases)
    if value is None or not math.isfinite(value):
        return None, value
    if value < low or value > high:
        return None, value
    return value, None


def compose_environment_snapshot(
    hub1: Mapping[str, Any],
    hub2: Mapping[str, Any],
    *,
    now: Optional[float],
    hub1_stale_s: float,
    hub2_stale_s: float,
    device_specs: Mapping[str, Mapping[str, Any]],
    calibration_metrics: Sequence[str],
    apply_bias: Callable[[str, Optional[float]], Optional[float]],
    bias_value: Callable[[str], float],
    bias_sources: Mapping[str, str],
) -> dict[str, Any]:
    """Compose the single validated environment view used by the whole Pod."""
    evaluated_at = time.time() if now is None else now
    sources: dict[str, dict[str, Any]] = {
        "hub1": {
            "payload": hub1, "label": "Hub 1 · USB",
            **source_freshness(hub1, hub1_stale_s, evaluated_at),
        },
        "hub2": {
            "payload": hub2, "label": "Hub 2 · MQTT",
            **source_freshness(hub2, hub2_stale_s, evaluated_at),
        },
    }
    values: dict[str, Optional[float]] = {}
    devices: dict[str, dict[str, Any]] = {}
    for key, spec in device_specs.items():
        attempts: list[dict[str, Any]] = []
        for source_id in spec["sources"]:
            source = sources[source_id]
            payload = source["payload"]
            field_values: dict[str, Optional[float]] = {}
            invalid_values: dict[str, Any] = {}
            for field, (aliases, low, high) in spec["fields"].items():
                value, invalid = bounded_number(payload, aliases, low, high)
                field_values[field] = value
                if invalid is not None:
                    invalid_values[field] = invalid
            flag = sensor_flag(payload, spec["status"])
            attempts.append({
                "source": source_id,
                "source_label": source["label"],
                "live": source["live"],
                "age_s": source["age_s"],
                "has_history": source["has_history"],
                "flag": flag,
                "valid": all(value is not None for value in field_values.values()),
                "values": field_values,
                "invalid_values": invalid_values,
            })
        selected = next(
            (item for item in attempts
             if item["live"] and item["flag"] is not False and item["valid"]),
            None,
        )
        if selected is None:
            selected = next(
                (item for item in attempts if item["flag"] is not False and item["valid"]),
                None,
            )
        primary = attempts[0]
        chosen = selected or primary
        warmup = False
        if key == "mhz19c":
            selected_payload = sources[chosen["source"]]["payload"]
            warmup = bool(selected_payload.get("co2_warmup"))
            warmup = warmup or bool((selected_payload.get("warmup") or {}).get("mhz19c"))
        if selected and selected["live"]:
            status = "live"
        elif selected:
            status = "stale"
        elif warmup and primary["live"]:
            status = "warming"
        elif primary["live"] and primary["flag"] is False:
            status = "fault"
        elif primary["live"]:
            status = "invalid" if primary["invalid_values"] else "no_data"
        elif primary["has_history"]:
            status = "stale"
        else:
            status = "offline"
        if key == "sph0645" and hub1.get("sound_measurement_valid") is False:
            # A live USB packet is not automatically a valid acoustic
            # measurement. Legacy dBFS-only packets and malformed LAeq
            # packets remain visible to Admin as raw diagnostics, but they
            # must never appear as dBA on health-facing screens.
            selected = None
            chosen = primary
            status = "invalid" if primary["live"] else status
            primary["invalid_values"]["sound_dba_est"] = hub1.get(
                "sound_invalid_reason", "untrusted_sound_measurement")
        for field in spec["fields"]:
            values[field] = selected["values"].get(field) if selected else None
        devices[key] = {
            "model": spec["model"],
            "status": status,
            "source": chosen["source"],
            "source_label": chosen["source_label"],
            "data_age_s": chosen["age_s"],
            "invalid_values": chosen["invalid_values"],
        }

    live_count = sum(1 for item in devices.values() if item["status"] == "live")
    stale_count = sum(1 for item in devices.values() if item["status"] in ("stale", "held"))
    overall = (
        "live" if live_count == len(devices)
        else "degraded" if live_count or stale_count
        else "offline"
    )
    raw_values = dict(values)
    for metric in calibration_metrics:
        values[metric] = apply_bias(metric, values.get(metric))
    return {
        **values,
        "temperature": values.get("temperature_c"),
        "humidity": values.get("humidity_rh"),
        "co2": values.get("co2_ppm"),
        "pm2_5": values.get("pm2_5_ug_m3"),
        "raw_values": raw_values,
        "calibration": {
            metric: {"bias": bias_value(metric), "source": bias_sources.get(metric, "default")}
            for metric in calibration_metrics
        },
        "devices": devices,
        "live_count": live_count,
        "total_count": len(devices),
        "status": overall,
        "sources": {
            key: {name: value for name, value in source.items() if name != "payload"}
            for key, source in sources.items()
        },
    }


def normalize_hub1_sensor(
    payload: Mapping[str, Any],
    *,
    sound_display_min: float,
    sound_display_max: float,
) -> dict[str, Any]:
    """Preserve Hub 1 raw values and validate firmware-computed LAeq(A).

    ``sound_dbfs`` is an electrical full-scale ratio, not sound pressure. It
    is intentionally never converted with ``abs()`` or published as dBA. The
    Pi accepts a health-facing sound value only when ESP32 explicitly marks a
    finite, in-range, A-weighted LAeq window as valid.
    """
    result = dict(payload)
    for target, keys in HUB1_ALIASES.items():
        value = first_numeric(payload, keys)
        if value is not None:
            result[target] = value
    result.pop("sound_dba_est", None)
    result["sound_measurement_valid"] = False
    result["sound_value_held"] = False

    laeq = first_numeric(result, ("sound_laeq_dba", "laeq_dba"))
    if laeq is None:
        reason = (
            "legacy_dbfs_only"
            if first_numeric(result, ("sound_dbfs",)) is not None
            else "missing_laeq"
        )
        result["sound_status"] = "invalid"
        result["sound_invalid_reason"] = reason
        return result

    declared_valid = payload.get("sound_valid") is True
    weighting = str(payload.get("sound_weighting") or "").strip().upper()
    metric = str(payload.get("sound_metric") or "").strip().upper()
    window_ms = first_numeric(payload, ("sound_window_ms",))
    if window_ms is None:
        window_s = first_numeric(payload, ("sound_window_s",))
        window_ms = window_s * 1000.0 if window_s is not None else None

    invalid_reason: Optional[str] = None
    if not declared_valid:
        invalid_reason = str(payload.get("sound_invalid_reason") or "firmware_invalid")
    elif weighting != SOUND_REQUIRED_WEIGHTING:
        invalid_reason = "weighting_must_be_A"
    elif metric != SOUND_REQUIRED_METRIC:
        invalid_reason = "metric_must_be_LAeq"
    elif window_ms is None or not math.isfinite(window_ms) or window_ms <= 0:
        invalid_reason = "invalid_integration_window"
    elif not math.isfinite(laeq) or not sound_display_min <= laeq <= sound_display_max:
        invalid_reason = "laeq_out_of_range"

    if invalid_reason:
        result["sound_status"] = "invalid"
        result["sound_invalid_reason"] = invalid_reason
        result["sound_invalid_value"] = laeq
        return result

    result["sound_laeq_dba"] = round(laeq, 2)
    result["sound_dba_est"] = round(laeq, 2)
    result["sound_window_ms"] = round(window_ms, 1)
    result["sound_measurement_valid"] = True
    result["sound_status"] = "valid"
    result["sound_processing_source"] = "esp32_a_weighted_laeq"
    return result


def hold_last_valid_sound(
    current: dict[str, Any],
    previous: Mapping[str, Any],
    *,
    display_min: float,
    display_max: float,
) -> dict[str, Any]:
    """Fail closed on invalid sound without presenting a stale value as live.

    The last valid value is retained under an Admin-only diagnostic key, but
    is never copied into ``sound_dba_est`` and is never recorded in a Session.
    """
    value = current.get("sound_dba_est")
    if (
        current.get("sound_measurement_valid") is True
        and valid_sound_level(value, display_min, display_max)
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


def valid_sound_level(value: Any, low: float, high: float) -> bool:
    """Return whether a value is a finite LAeq(A) value in the approved range."""
    return bool(
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and low <= float(value) <= high
    )


def energy_average_db(
    levels: Sequence[float], *, display_min: float, display_max: float,
) -> Optional[float]:
    """Return a numerically stable energy-domain decibel average."""
    valid = [
        float(value)
        for value in levels
        if valid_sound_level(value, display_min, display_max)
    ]
    if not valid:
        return None
    peak = max(valid)
    relative_energy = sum(10 ** ((value - peak) / 10.0) for value in valid) / len(valid)
    return round(peak + 10.0 * math.log10(relative_energy), 2)


def summarize_sound_window(
    rows: Sequence[Mapping[str, Any]],
    start_s: float,
    end_s: float,
    *,
    display_min: float,
    display_max: float,
) -> dict[str, Any]:
    """Summarize immutable sound rows aligned to one analysis bucket."""
    levels = [
        float(row["dba"]) for row in rows
        if start_s < float(row["t"]) <= end_s
    ]
    leq = energy_average_db(levels, display_min=display_min, display_max=display_max)
    if leq is None:
        return {
            "method": "energy_average_leq",
            "window_s": round(end_s - start_s, 2),
            "sample_count": 0,
            "status": "no_samples",
        }
    span = max(levels) - min(levels)
    return {
        "method": "energy_average_leq",
        "window_s": round(end_s - start_s, 2),
        "sample_count": len(levels),
        "leq_dba": leq,
        "min_dba": round(min(levels), 2),
        "max_dba": round(max(levels), 2),
        "span_db": round(span, 2),
        "large_step_detected": span >= 20.0,
        "status": "dynamic" if span >= 20.0 else "valid",
    }
