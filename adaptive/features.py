"""Pure feature preparation for the Adaptive Learning live contract."""

from __future__ import annotations

import statistics
from collections.abc import Iterable
from typing import Any

from common.numbers import as_finite_number as finite_number
from sensors.contracts import SOUND_DBA_DISPLAY_MAX, SOUND_DBA_DISPLAY_MIN
from sensors.runtime import energy_average_db

FEATURE_SPECS = (
    (
        "heart_rate",
        "ชีพจร",
        "BPM",
        4.0,
        "BCG LSM-800-T",
        "personal physiology baseline",
        "hr",
        "personal_sleep_history",
    ),
    (
        "respiration_rate",
        "อัตราการหายใจ",
        "ครั้ง/นาที",
        1.5,
        "BCG LSM-800-T",
        "prior completed same-mode sessions",
        "rr",
        "same_mode_history",
    ),
    (
        "movement",
        "การเคลื่อนไหว",
        "% ของช่วงประเมิน",
        5.0,
        "BCG feature window",
        "personal physiology baseline",
        None,
        "personal_sleep_history",
    ),
    (
        "temperature",
        "อุณหภูมิ",
        "°C",
        1.0,
        "SHT3x-DIS",
        "prior completed same-mode sessions",
        "temp",
        "same_mode_history",
    ),
    (
        "humidity",
        "ความชื้น",
        "%RH",
        5.0,
        "SHT3x-DIS",
        "prior completed same-mode sessions",
        "hum",
        "same_mode_history",
    ),
    (
        "co2",
        "CO₂",
        "ppm",
        150.0,
        "MH-Z19C",
        "prior completed same-mode sessions",
        "co2",
        "same_mode_history",
    ),
    (
        "pm2_5",
        "PM2.5",
        "µg/m³",
        5.0,
        "PMS7003",
        "no personal reference yet",
        "pm2_5",
        "none",
    ),
    (
        "voc_index",
        "VOC Index",
        "index",
        20.0,
        "SGP40 adaptive index",
        "sensor-owned adaptive baseline",
        "voc",
        "sensor_owned",
    ),
    (
        "light",
        "ความสว่าง",
        "lux",
        1.0,
        "OPT3001",
        "prior completed same-mode sessions",
        "lux",
        "same_mode_history",
    ),
    (
        "sound",
        "เสียง",
        "dBA",
        3.0,
        "SPH0645 sound_dba",
        "prior completed same-mode sessions",
        "dba",
        "same_mode_history",
    ),
)


def mode_group(rest_mode: Any) -> str:
    mode = str(rest_mode or "auto").strip().lower()
    if mode in {"sleep", "overnight"}:
        return "sleep"
    nap_modes = {"short_nap", "cycle_nap", "nap", "nap_recovery", "shift_rest"}
    return "nap_recovery" if mode in nap_modes else mode


def _comparison(
    value: float | None,
    reference: float | None,
    tolerance: float,
) -> tuple[str, float | None, float | None]:
    if value is None:
        return "no_live_value", None, None
    if reference is None:
        return "no_reference", None, None
    delta = value - reference
    relative = (delta / abs(reference) * 100.0) if reference else None
    if abs(delta) <= tolerance:
        status = "near_reference"
    else:
        status = "above_reference" if delta > 0 else "below_reference"
    rounded = round(relative, 1) if relative is not None else None
    return status, round(delta, 2), rounded


def _reference_scope(policy: str, group: str) -> str:
    if policy == "personal_sleep_history":
        return (
            "prior_completed_same_mode_sessions"
            if group == "sleep"
            else "qualified_overnight_reference"
        )
    if policy == "same_mode_history":
        return "prior_completed_same_mode_sessions"
    return policy


def _metric(
    spec: tuple[Any, ...],
    value: Any,
    reference: Any,
    window: dict[str, Any] | None,
    group: str,
    *,
    reference_policy_override: str | None = None,
) -> dict[str, Any]:
    (
        key,
        label,
        unit,
        tolerance,
        live_source,
        reference_source,
        _,
        reference_policy,
    ) = spec
    if reference_policy_override is not None:
        reference_policy = reference_policy_override
        reference_source = (
            "personal physiology baseline"
            if reference_policy == "personal_sleep_history"
            else "prior completed same-mode sessions"
        )
    live_value = finite_number(value)
    baseline_value = finite_number(reference)
    comparison, delta, relative = _comparison(
        live_value,
        baseline_value,
        tolerance,
    )
    return {
        "key": key,
        "label": label,
        "unit": unit,
        "value": round(live_value, 2) if live_value is not None else None,
        "reference": (round(baseline_value, 2) if baseline_value is not None else None),
        "delta": delta,
        "relative_delta_pct": relative,
        "comparison": comparison,
        "tolerance": tolerance,
        "live_source": live_source,
        "reference_source": reference_source,
        "reference_scope": _reference_scope(reference_policy, group),
        "window": window,
        "medical_interpretation": False,
    }


def _sample_epoch(sample: dict[str, Any]) -> float | None:
    canonical = finite_number(sample.get("analysis_epoch_s"))
    return canonical if canonical is not None else finite_number(sample.get("t"))


def _window_samples(
    samples: Iterable[dict[str, Any]],
    *,
    now: float,
    window_seconds: int,
) -> list[dict[str, Any]]:
    start = now - max(1, window_seconds)
    unique: dict[tuple[str, float], dict[str, Any]] = {}
    for sample in samples:
        epoch = _sample_epoch(sample)
        if epoch is None or epoch < start or epoch > now + 10:
            continue
        canonical = finite_number(sample.get("analysis_epoch_s"))
        key = (
            ("frame", canonical)
            if canonical is not None
            else ("sample", round(epoch, 1))
        )
        unique[key] = dict(sample)
    return sorted(unique.values(), key=lambda item: _sample_epoch(item) or 0.0)


def _window_stats(
    samples: Iterable[dict[str, Any]],
    field: str | None,
    expected_samples: int,
) -> dict[str, Any] | None:
    if not field:
        return None
    values = []
    for item in samples:
        if field in {"hr", "rr"} and item.get("bcg_analysis_valid") is not True:
            continue
        number = finite_number(item.get(field))
        if number is not None:
            values.append(number)
    if not values:
        return None
    mean = (
        energy_average_db(
            values,
            display_min=SOUND_DBA_DISPLAY_MIN,
            display_max=SOUND_DBA_DISPLAY_MAX,
        )
        if field == "dba"
        else round(statistics.fmean(values), 2)
    )
    if mean is None:
        return None
    return {
        "mean": mean,
        "method": "energy_average_leq" if field == "dba" else "arithmetic_mean",
        "minimum": round(min(values), 2),
        "maximum": round(max(values), 2),
        "samples": len(values),
        "expected_samples": expected_samples,
        "coverage_pct": round(
            min(1.0, len(values) / max(1, expected_samples)) * 100.0,
            1,
        ),
    }


def _feature_value_maps(
    snapshot: dict[str, Any],
    baseline: dict[str, Any],
    behaviour: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], str]:
    environment = (snapshot.get("sensor") or {}).get("environment") or {}
    bcg = (snapshot.get("sensor") or {}).get("bcg") or {}
    frame = snapshot.get("sensor_frame") or {}
    sleep = snapshot.get("sleep") or {}
    devices = environment.get("devices") or {}
    best_window = behaviour.get("best_rest_window") or {}
    best_environment = (
        best_window.get("environment") or {}
        if (
            best_window.get("outcome_supported") is True
            and best_window.get("environment_reference_available") is True
        )
        else {}
    )
    typical = best_environment or behaviour.get("typical_environment") or {}
    respiratory = behaviour.get("respiratory_reference") or {}
    rr_reference = respiratory.get("median_rr_brpm")
    rr_reference_policy = "same_mode_history"
    if finite_number(rr_reference) is None:
        rr_reference = baseline.get("rr_sleep_median")
        rr_reference_policy = "personal_sleep_history"
    frame_live = not frame.get("stale")
    bcg_live = bool(
        frame_live
        and bcg.get("connected")
        and not bcg.get("stale")
        and bcg.get("analysis_valid")
    )

    def environment_value(device: str, field: str) -> Any:
        status = (devices.get(device) or {}).get("status")
        return environment.get(field) if frame_live and status == "live" else None

    movement = finite_number(sleep.get("movement_ratio")) if bcg_live else None
    movement_reference = finite_number(baseline.get("move_ratio_median"))
    live = {
        "heart_rate": bcg.get("heart_rate_bpm") if bcg_live else None,
        "respiration_rate": bcg.get("respiration_rate") if bcg_live else None,
        "movement": movement * 100.0 if movement is not None else None,
        "temperature": environment_value("sht3x_dis", "temperature_c"),
        "humidity": environment_value("sht3x_dis", "humidity_rh"),
        "co2": environment_value("mhz19c", "co2_ppm"),
        "pm2_5": environment_value("pms7003", "pm2_5_ug_m3"),
        "voc_index": environment_value("sgp40", "voc_index"),
        "light": environment_value("opt3001", "lux"),
        "sound": environment_value("sph0645", "sound_dba_est"),
    }
    references = {
        "heart_rate": baseline.get("hr_sleep_median"),
        "respiration_rate": rr_reference,
        "movement": (
            movement_reference * 100.0 if movement_reference is not None else None
        ),
        "temperature": typical.get("temp_median"),
        "humidity": typical.get("humidity_median"),
        "co2": typical.get("co2_median"),
        "pm2_5": None,
        "voc_index": None,
        "light": typical.get("lux_median"),
        "sound": typical.get("sound_median"),
    }
    return live, references, rr_reference_policy


def prepare_live_features(
    snapshot: dict[str, Any],
    baseline: dict[str, Any],
    behaviour: dict[str, Any],
    recent_samples: Iterable[dict[str, Any]],
    *,
    now: float,
    window_seconds: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int, str]:
    """Return valid live metrics and one deduplicated canonical window."""
    group = mode_group((snapshot.get("session") or {}).get("rest_mode"))
    expected = max(1, int(window_seconds / 10))
    samples = _window_samples(
        recent_samples,
        now=now,
        window_seconds=window_seconds,
    )
    live, references, rr_reference_policy = _feature_value_maps(
        snapshot, baseline, behaviour
    )
    metrics = [
        _metric(
            spec,
            live[spec[0]],
            references[spec[0]],
            _window_stats(samples, spec[6], expected),
            group,
            reference_policy_override=(
                rr_reference_policy if spec[0] == "respiration_rate" else None
            ),
        )
        for spec in FEATURE_SPECS
    ]
    return metrics, samples, expected, group
