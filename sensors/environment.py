"""Compose the canonical environment view from detached Hub payloads."""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from sensors.contracts import SOUND_SENSOR_MODEL
from sensors.values import first_numeric

ACOUSTIC_LABELS = frozenset(
    {
        "quiet",
        "steady_equipment_like",
        "speech_like",
        "snore_like",
        "impact_like",
        "unknown",
    }
)


def _acoustic_projection(
    hub1: Mapping[str, Any],
    *,
    source_live: bool,
    sound_live: bool,
) -> dict[str, Any]:
    """Expose only versioned DSP metadata; never PCM or speech content."""
    label = str(hub1.get("sound_class") or "unknown").strip().lower()
    state = str(hub1.get("sound_class_state") or "insufficient_input").strip()
    confidence = hub1.get("sound_class_confidence")
    if label not in ACOUSTIC_LABELS:
        label = "unknown"
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        confidence = 0.0
    confidence = max(0.0, min(1.0, float(confidence)))
    valid = bool(
        source_live
        and sound_live
        and state == "provisional"
        and label != "unknown"
    )
    numeric_fields = (
        "sound_low_band_ratio",
        "sound_mid_band_ratio",
        "sound_high_band_ratio",
        "sound_spectral_centroid_hz",
        "sound_spectral_flatness",
        "sound_spectral_flux",
        "sound_crest_factor",
        "sound_syllabic_modulation",
        "sound_breathing_periodicity",
        "sound_breathing_period_s",
    )
    features = {
        key.removeprefix("sound_"): first_numeric(hub1, (key,))
        for key in numeric_fields
    }
    rms = first_numeric(hub1, ("sound_rms",))
    peak = first_numeric(hub1, ("sound_peak",))
    crest_factor = (
        peak / rms
        if rms is not None and rms > 0 and peak is not None
        else None
    )
    window_features = {
        "rms": rms,
        "rms_a": first_numeric(hub1, ("sound_rms_a",)),
        "peak": peak,
        "peak_a": first_numeric(hub1, ("sound_peak_a",)),
        "crest_factor": crest_factor,
        "dbfs_a": first_numeric(hub1, ("sound_dbfs_a",)),
        "sample_rate_hz": first_numeric(hub1, ("sound_sample_rate_hz",)),
        "sample_count": first_numeric(hub1, ("sound_samples",)),
        "window_ms": first_numeric(hub1, ("sound_window_ms",)),
        "laeq_dba_reported": first_numeric(hub1, ("sound_laeq_dba",)),
        "calibrated_dba_reported": first_numeric(
            hub1,
            ("sound_dba_calibrated",),
        ),
        "calibration_offset_db": first_numeric(
            hub1,
            ("sound_calibration_offset_db",),
        ),
    }
    window_features = {
        key: round(value, 6) if isinstance(value, float) else value
        for key, value in window_features.items()
        if value is not None
    }
    return {
        "label": label if valid else "unknown",
        "state": "provisional" if valid else "insufficient_input",
        "confidence": round(confidence, 4) if valid else 0.0,
        "event_detected": bool(valid and hub1.get("sound_event_detected")),
        "classifier_version": str(
            hub1.get("sound_classifier_version") or "unavailable"
        ),
        "window_sequence": first_numeric(hub1, ("sound_window_sequence",)),
        "features": {**window_features, **features} if valid else window_features,
        "feature_source": (
            "firmware_dsp" if valid else "esp32_window_summary"
            if window_features else "unavailable"
        ),
        "raw_audio_transmitted": False,
    }


def source_freshness(
    payload: Mapping[str, Any],
    stale_s: float,
    now: float,
) -> dict[str, Any]:
    last = payload.get("last_update")
    age = max(0.0, now - last) if isinstance(last, (int, float)) else None
    live = bool(payload.get("connected") and age is not None and age <= stale_s)
    return {
        "live": live,
        "age_s": round(age, 1) if age is not None else None,
        "has_history": last is not None,
    }


def sensor_flag(
    payload: Mapping[str, Any],
    keys: Sequence[str],
) -> bool | None:
    status = payload.get("sensor_status")
    if not isinstance(status, dict):
        return None
    for key in keys:
        if key in status:
            return bool(status[key])
    return None


def sensor_diagnostic(
    payload: Mapping[str, Any],
    keys: Sequence[str],
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
    payload: Mapping[str, Any],
    aliases: Sequence[str],
    low: float,
    high: float,
) -> tuple[float | None, float | None]:
    value = first_numeric(payload, aliases)
    if value is None or not math.isfinite(value):
        return None, value
    if value < low or value > high:
        return None, value
    return value, None


def _source_views(
    hub1: Mapping[str, Any],
    hub2: Mapping[str, Any],
    *,
    evaluated_at: float,
    hub1_stale_s: float,
    hub2_stale_s: float,
) -> dict[str, dict[str, Any]]:
    return {
        "hub1": {
            "payload": hub1,
            "label": "Hub 1 · USB",
            **source_freshness(hub1, hub1_stale_s, evaluated_at),
        },
        "hub2": {
            "payload": hub2,
            "label": "Hub 2 · MQTT",
            **source_freshness(hub2, hub2_stale_s, evaluated_at),
        },
    }


def _source_attempt(
    device_key: str,
    spec: Mapping[str, Any],
    source_id: str,
    sources: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    source = sources[source_id]
    payload = source["payload"]
    values: dict[str, float | None] = {}
    invalid_values: dict[str, Any] = {}
    for field, (aliases, low, high) in spec["fields"].items():
        value, invalid = bounded_number(payload, aliases, low, high)
        values[field] = value
        if invalid is not None:
            invalid_values[field] = invalid
    flag = sensor_flag(payload, spec["status"])
    if (
        device_key == "sph0645"
        and payload.get("sound_measurement_valid") is True
        and all(value is not None for value in values.values())
    ):
        flag = True
    diagnostic = sensor_diagnostic(payload, spec["status"])
    return {
        "source": source_id,
        "source_label": source["label"],
        "live": source["live"],
        "age_s": source["age_s"],
        "has_history": source["has_history"],
        "flag": flag,
        "declared_status": str(diagnostic.get("status") or "").strip().lower(),
        "reason": diagnostic.get("reason"),
        "sensor_age_ms": diagnostic.get("age_ms"),
        "diagnostics": diagnostic.get("diagnostics"),
        "valid": all(value is not None for value in values.values()),
        "values": values,
        "invalid_values": invalid_values,
    }


def _select_attempt(attempts: list[dict[str, Any]]) -> dict[str, Any] | None:
    selected = next(
        (
            item
            for item in attempts
            if item["live"] and item["flag"] is not False and item["valid"]
        ),
        None,
    )
    if selected is not None:
        return selected
    return next(
        (item for item in attempts if item["flag"] is not False and item["valid"]),
        None,
    )


def _device_status(
    key: str,
    selected: Mapping[str, Any] | None,
    primary: Mapping[str, Any],
    sources: Mapping[str, Mapping[str, Any]],
) -> str:
    chosen = selected or primary
    warming = False
    if key == "mhz19c":
        payload = sources[chosen["source"]]["payload"]
        warming = bool(payload.get("co2_warmup"))
        warming = warming or bool((payload.get("warmup") or {}).get("mhz19c"))
    declared = selected.get("declared_status") if selected else None
    if selected and selected["live"] and declared in {"degraded", "held"}:
        return str(declared)
    if selected and selected["live"]:
        return "live"
    if selected:
        return "stale"
    if warming and primary["live"]:
        return "warming"
    if primary["live"] and primary["declared_status"] in {
        "fault",
        "invalid",
        "no_data",
        "offline",
        "stale",
        "warming",
    }:
        return str(primary["declared_status"])
    if primary["live"] and primary["flag"] is False:
        return "fault"
    if primary["live"]:
        return "invalid" if primary["invalid_values"] else "no_data"
    return "stale" if primary["has_history"] else "offline"


def _device_projection(
    key: str,
    spec: Mapping[str, Any],
    sources: Mapping[str, Mapping[str, Any]],
    hub1: Mapping[str, Any],
) -> tuple[dict[str, float | None], dict[str, Any]]:
    attempts = [
        _source_attempt(key, spec, source_id, sources) for source_id in spec["sources"]
    ]
    primary = attempts[0]
    selected = _select_attempt(attempts)
    status = _device_status(key, selected, primary, sources)
    if key == "sph0645" and hub1.get("sound_measurement_valid") is False:
        selected = None
        status = "invalid" if primary["live"] else status
        primary["invalid_values"]["sound_dba_est"] = hub1.get(
            "sound_invalid_reason",
            "untrusted_sound_measurement",
        )
    chosen = selected or primary
    values = {
        field: selected["values"].get(field) if selected else None
        for field in spec["fields"]
    }
    device = {
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
    return values, device


def _environment_status(devices: Mapping[str, Mapping[str, Any]]) -> str:
    live_count = sum(item["status"] == "live" for item in devices.values())
    degraded_count = sum(
        item["status"] in {"degraded", "stale", "held"} for item in devices.values()
    )
    if live_count == len(devices):
        return "live"
    if live_count or degraded_count:
        return "degraded"
    return "offline"


def _sound_dbfs_raw(
    hub1: Mapping[str, Any],
    *,
    source_live: bool,
) -> float | None:
    value = first_numeric(hub1, ("sound_dbfs",))
    if (
        not source_live
        or value is None
        or not math.isfinite(value)
        or not -160.0 <= value <= 0.0
    ):
        return None
    return value


def compose_environment_snapshot(
    hub1: Mapping[str, Any],
    hub2: Mapping[str, Any],
    *,
    now: float | None,
    hub1_stale_s: float,
    hub2_stale_s: float,
    device_specs: Mapping[str, Mapping[str, Any]],
    calibration_metrics: Sequence[str],
    apply_bias: Callable[[str, float | None], float | None],
    bias_value: Callable[[str], float],
    bias_sources: Mapping[str, str],
) -> dict[str, Any]:
    """Compose the single validated environment view used by the whole Pod."""
    evaluated_at = time.time() if now is None else now
    sources = _source_views(
        hub1,
        hub2,
        evaluated_at=evaluated_at,
        hub1_stale_s=hub1_stale_s,
        hub2_stale_s=hub2_stale_s,
    )
    values: dict[str, float | None] = {}
    devices: dict[str, dict[str, Any]] = {}
    for key, spec in device_specs.items():
        device_values, device = _device_projection(key, spec, sources, hub1)
        values.update(device_values)
        devices[key] = device

    live_count = sum(item["status"] == "live" for item in devices.values())
    raw_values = dict(values)
    for metric in calibration_metrics:
        values[metric] = apply_bias(metric, values.get(metric))
    result = {
        **values,
        "sound_dbfs_raw": _sound_dbfs_raw(
            hub1,
            source_live=bool(sources["hub1"]["live"]),
        ),
        "sound_sensor_model": SOUND_SENSOR_MODEL,
        "temperature": values.get("temperature_c"),
        "humidity": values.get("humidity_rh"),
        "co2": values.get("co2_ppm"),
        "pm2_5": values.get("pm2_5_ug_m3"),
        "raw_values": raw_values,
        "calibration": {
            metric: {
                "bias": bias_value(metric),
                "source": bias_sources.get(metric, "default"),
            }
            for metric in calibration_metrics
        },
        "devices": devices,
        "live_count": live_count,
        "total_count": len(devices),
        "status": _environment_status(devices),
        "sources": {
            key: {name: value for name, value in source.items() if name != "payload"}
            for key, source in sources.items()
        },
    }
    result["acoustic"] = _acoustic_projection(
        hub1,
        source_live=bool(sources["hub1"]["live"]),
        sound_live=devices.get("sph0645", {}).get("status") == "live",
    )
    return result
