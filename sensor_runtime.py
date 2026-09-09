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

from sensor_contracts import SOUND_SENSOR_MODEL


HUB1_ALIASES: dict[str, tuple[str, ...]] = {
    "temperature": ("temperature_c", "temperature", "temp", "temp_c"),
    "humidity": ("humidity", "hum", "rh", "humidity_rh"),
    "lux": ("lux", "light", "illuminance"),
    "co2": ("co2", "co2_ppm", "carbon_dioxide"),
    "sound_dbfs": ("sound_dbfs",),
    "sound_rms": ("sound_rms",),
    "sound_peak": ("sound_peak",),
}


def first_numeric(obj: Mapping[str, Any], keys: Sequence[str]) -> Optional[float]:
    for key in keys:
        value = obj.get(key)
        if value is None or isinstance(value, bool):
            continue
        try:
            return float(value)
        except (TypeError, ValueError, OverflowError):
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


def sensor_diagnostic(
    payload: Mapping[str, Any], keys: Sequence[str],
) -> Mapping[str, Any]:
    """Return per-device firmware diagnostics without coupling peer sensors."""
    diagnostics = payload.get("sensor_diagnostics")
    if not isinstance(diagnostics, Mapping):
        return {}
    for key in keys:
        value = diagnostics.get(key)
        if isinstance(value, Mapping):
            return value
    return {}


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
            if (
                key == "sph0645"
                and payload.get("sound_measurement_valid") is True
                and all(value is not None for value in field_values.values())
            ):
                # The direct ``sound_dba`` contract is authoritative. Legacy
                # per-device flags from older firmware must not reintroduce a
                # hidden approval gate after the numeric value passed checks.
                flag = True
            diagnostic = sensor_diagnostic(payload, spec["status"])
            attempts.append({
                "source": source_id,
                "source_label": source["label"],
                "live": source["live"],
                "age_s": source["age_s"],
                "has_history": source["has_history"],
                "flag": flag,
                "declared_status": str(
                    diagnostic.get("status") or "").strip().lower(),
                "reason": diagnostic.get("reason"),
                "sensor_age_ms": diagnostic.get("age_ms"),
                "diagnostics": diagnostic.get("diagnostics"),
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
        if selected and selected["live"] and selected["declared_status"] in {
            "degraded", "held",
        }:
            status = selected["declared_status"]
        elif selected and selected["live"]:
            status = "live"
        elif selected:
            status = "stale"
        elif warmup and primary["live"]:
            status = "warming"
        elif primary["live"] and primary["declared_status"] in {
            "fault", "invalid", "no_data", "offline", "stale", "warming",
        }:
            status = primary["declared_status"]
        elif primary["live"] and primary["flag"] is False:
            status = "fault"
        elif primary["live"]:
            status = "invalid" if primary["invalid_values"] else "no_data"
        elif primary["has_history"]:
            status = "stale"
        else:
            status = "offline"
        if key == "sph0645" and hub1.get("sound_measurement_valid") is False:
            # A missing, non-finite or out-of-range ``sound_dba`` value is
            # unavailable. Other metadata is intentionally not a runtime gate.
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
            "sensor_age_ms": chosen["sensor_age_ms"],
            "reason": chosen["reason"],
            "diagnostics": chosen["diagnostics"],
            "invalid_values": chosen["invalid_values"],
        }

    live_count = sum(1 for item in devices.values() if item["status"] == "live")
    usable_degraded_count = sum(
        1 for item in devices.values()
        if item["status"] in ("degraded", "stale", "held")
    )
    overall = (
        "live" if live_count == len(devices)
        else "degraded" if live_count or usable_degraded_count
        else "offline"
    )
    raw_values = dict(values)
    # Keep signed dBFS for Admin diagnostics only. It is never transformed with
    # abs() and never substitutes for the ESP32-provided ``sound_dba`` value.
    sound_dbfs_raw = first_numeric(hub1, ("sound_dbfs",))
    if (
        not sources["hub1"]["live"]
        or sound_dbfs_raw is None
        or not math.isfinite(sound_dbfs_raw)
        or not -160.0 <= sound_dbfs_raw <= 0.0
    ):
        sound_dbfs_raw = None
    for metric in calibration_metrics:
        values[metric] = apply_bias(metric, values.get(metric))
    return {
        **values,
        "sound_dbfs_raw": sound_dbfs_raw,
        "sound_sensor_model": SOUND_SENSOR_MODEL,
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
    """Copy the ESP32 ``sound_dba`` field into the canonical Pi channel.

    Sensor Hub 1 owns microphone processing. The Pi does not apply ``abs()``,
    bias, profile matching, CEM approval, weighting checks or packet-count
    gates. It only rejects missing, non-finite or out-of-display-range values.
    Signed dBFS and any extra firmware diagnostics remain available to Admin.
    """
    result = dict(payload)
    for target, keys in HUB1_ALIASES.items():
        value = first_numeric(payload, keys)
        if value is not None:
            result[target] = value
    result.pop("sound_dba_est", None)
    result.pop("sound_dba_firmware_est", None)
    result.pop("sound_preview_evidence_count", None)
    # Never republish an unvalidated source value. Python's JSON decoder accepts
    # NaN/Infinity by default, while Starlette correctly refuses to serialize
    # them. Removing the source key first keeps one bad microphone sample from
    # poisoning the complete Hub 1 API state (including SHT3x and OPT3001).
    result.pop("sound_dba", None)
    result.pop("sound_laeq_dba", None)
    result.pop("sound_invalid_value", None)
    for diagnostic_key in ("sound_dbfs", "sound_rms", "sound_peak"):
        diagnostic_value = result.get(diagnostic_key)
        if (
            not isinstance(diagnostic_value, (int, float))
            or isinstance(diagnostic_value, bool)
        ):
            result.pop(diagnostic_key, None)
            continue
        try:
            diagnostic_is_finite = math.isfinite(float(diagnostic_value))
        except OverflowError:
            diagnostic_is_finite = False
        if not diagnostic_is_finite:
            result.pop(diagnostic_key, None)
    result["sound_sensor_model"] = SOUND_SENSOR_MODEL
    result["sound_measurement_valid"] = False
    result["sound_value_held"] = False

    sound_raw = payload.get("sound_dba")
    sound_dba = None
    sound_overflow = False
    if isinstance(sound_raw, (int, float)) and not isinstance(sound_raw, bool):
        try:
            sound_dba = float(sound_raw)
        except OverflowError:
            sound_overflow = True
    if sound_raw is None:
        firmware_reason = str(
            payload.get("sound_invalid_reason") or ""
        ).strip()
        invalid_reason = firmware_reason or (
            "legacy_dbfs_only"
            if first_numeric(result, ("sound_dbfs",)) is not None
            else "missing_sound_dba"
        )
    elif sound_overflow:
        invalid_reason = "sound_dba_out_of_range"
    elif sound_dba is None:
        invalid_reason = "invalid_sound_dba_type"
    elif not math.isfinite(sound_dba):
        invalid_reason = "non_finite_sound_dba"
    elif not sound_display_min <= sound_dba <= sound_display_max:
        invalid_reason = "sound_dba_out_of_range"
    else:
        invalid_reason = None

    if invalid_reason is not None:
        result["sound_status"] = "invalid"
        result["sound_invalid_reason"] = invalid_reason
        if sound_dba is not None and math.isfinite(sound_dba):
            result["sound_invalid_value"] = sound_dba
        return result

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
        firmware_status = sensor_status.get("sph0645")
        if firmware_status is False:
            result["sound_firmware_reported_status"] = False
        sensor_status["sph0645"] = True
        result["sensor_status"] = sensor_status
    diagnostics = result.get("sensor_diagnostics")
    if isinstance(diagnostics, Mapping):
        diagnostics = dict(diagnostics)
        sph_diagnostic = diagnostics.get("sph0645")
        if isinstance(sph_diagnostic, Mapping):
            sph_diagnostic = dict(sph_diagnostic)
            if sph_diagnostic.get("reason"):
                result["sound_firmware_reported_reason"] = sph_diagnostic["reason"]
            diagnostics["sph0645"] = {
                **sph_diagnostic,
                "status": "live",
                "reason": None,
            }
        result["sensor_diagnostics"] = diagnostics
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
    """Return whether a sound value is finite and in the display range."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        number = float(value)
    except OverflowError:
        return False
    return math.isfinite(number) and low <= number <= high


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
