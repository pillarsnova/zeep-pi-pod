"""Pure helpers for live Sleep evidence and operational attribution."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any

from sleep_system_policy import assess_environment_values

INITIAL_WAIT_HARD_CAP_SECONDS = 120.0
INITIAL_WAIT_STATUSES = frozenset({
    "collecting_evidence_epoch",
    "confirming_initial_state",
    "initial_confirmation_wait",
})


def enforce_initial_wait_hard_cap(
    sleep_result: Mapping[str, Any],
    *,
    elapsed_seconds: float | None,
    maximum_seconds: float,
    sleep_states: Sequence[str],
) -> dict[str, Any]:
    """Turn an overlong initial WAIT into explicit, unscored NO DATA."""
    value = dict(sleep_result)
    if elapsed_seconds is None or elapsed_seconds < maximum_seconds:
        return value
    confirmed = value.get("confirmed_state") or (
        value.get("state") if value.get("classification_active") else None
    )
    if confirmed in sleep_states:
        return value
    if str(value.get("data_status") or "") not in INITIAL_WAIT_STATUSES:
        return value
    confirmation = dict(value.get("confirmation") or {})
    confirmation.update({
        "initial_wait_timed_out": True,
        "initial_wait_max_seconds": maximum_seconds,
    })
    value.update({
        "state": "no_data",
        "confirmed_state": None,
        "classification_active": False,
        "probabilities": {state: 0.0 for state in sleep_states},
        "confidence": "low",
        "provisional": False,
        "score_eligible": False,
        "excluded_from_score": True,
        "excluded_from_personal_baseline": True,
        "data_status": "initial_confirmation_timeout",
        "reason": (
            "ครบเวลายืนยันสถานะเริ่มต้น 120 วินาทีแล้ว · "
            "แสดง NO DATA จนกว่าจะยืนยัน State แรกได้"
        ),
        "initial_wait_elapsed_s": round(max(0.0, elapsed_seconds), 1),
        "initial_wait_max_s": maximum_seconds,
        "confirmation": confirmation,
    })
    return value


def baseline_interval_proximity(
    value: float,
    pair: Sequence[float],
) -> tuple[float, dict[str, float]]:
    """Measure proximity to a baseline interval with a midpoint tie-breaker."""
    lo, hi = sorted((float(pair[0]), float(pair[1])))
    midpoint = (lo + hi) / 2.0
    half_span = max((hi - lo) / 2.0, 0.5)
    outside_distance = max(lo - value, 0.0, value - hi)
    midpoint_distance = abs(value - midpoint)
    normalized_distance = (
        outside_distance / half_span
        + 0.35 * midpoint_distance / half_span
    )
    proximity = math.exp(-1.2 * normalized_distance**2)
    return proximity, {
        "min": round(lo, 2),
        "max": round(hi, 2),
        "midpoint": round(midpoint, 2),
        "distance_to_range": round(outside_distance, 2),
        "distance_to_midpoint": round(midpoint_distance, 2),
        "proximity_percent": round(proximity * 100.0, 1),
    }


def sleep_environment_context(
    environment: Mapping[str, Any],
    rest_mode: Any,
    *,
    context_version: str,
    baseline_version: str,
) -> dict[str, Any]:
    """Build the versioned, Mode-aware environmental context baseline."""
    values = dict(environment)
    if values.get("sound_dba_est") is None:
        values["sound_dba_est"] = values.get("sound_dba")
    assessment = assess_environment_values(values, rest_mode)
    factors: dict[str, Any] = {}
    deviations: list[float] = []
    for metric in assessment["evaluations"]:
        factors[metric["key"]] = _environment_factor(metric, deviations)
    disruption = (
        round(sum(deviations) / len(deviations), 3)
        if deviations
        else None
    )
    expected = len(assessment["evaluations"])
    available = len(deviations)
    return {
        "version": context_version,
        "sleep_baseline_version": baseline_version,
        "role": "context_and_confidence_only",
        "mode": assessment["mode"],
        "acceptable_min_level": assessment["acceptable_min_level"],
        "factors": factors,
        "available_factors": available,
        "expected_factors": expected,
        "coverage_percent": round(available / expected * 100, 1),
        "disruption_index": disruption,
        "sleep_support_score": (
            round((1.0 - disruption) * 100)
            if disruption is not None
            else None
        ),
        "overall_level": assessment["key"],
        "meets_expected": assessment["meets_expected"],
        "assessment_quality": assessment.get("assessment_quality"),
        "required_count": assessment.get("required_count", 0),
        "advisory_count": assessment.get("advisory_count", 0),
        "optimisation_count": assessment.get("optimisation_count", 0),
        "direct_stage_influence": False,
        "wake_prior": 0.0,
    }


def _environment_factor(
    metric: Mapping[str, Any],
    deviations: list[float],
) -> dict[str, Any]:
    """Translate one assessment metric into the public context contract."""
    if metric["status"] != "live":
        return {
            "available": False,
            "value": None,
            "target": metric["target"],
            "expected_floor": metric["expected_floor"],
            "deviation": None,
            "level": "unavailable",
        }
    deviation = round((4 - metric["score"]) / 4.0, 3)
    deviations.append(deviation)
    return {
        "available": True,
        "value": round(float(metric["value"]), 2),
        "target": metric["target"],
        "expected_floor": metric["expected_floor"],
        "deviation": deviation,
        "level": metric["level"]["key"],
        "decision": metric["decision"],
    }


def sleep_auxiliary_evidence(
    frames: Sequence[Mapping[str, Any]],
    statuses: Sequence[int],
    movement_ratio: float,
    waveform_signal: Mapping[str, Any],
    *,
    acoustic_disturbance_dba: float,
    acoustic_min_coverage: float,
    acoustic_wake_support_max: float,
    move_wake_ratio: float,
) -> dict[str, Any]:
    """Build auditable SPH0645 and Bed Status corroboration for BCG."""
    acoustic = _acoustic_evidence(
        frames,
        disturbance_dba=acoustic_disturbance_dba,
        minimum_coverage=acoustic_min_coverage,
    )
    shift_ratio = waveform_signal.get("bcg_amplitude_shift_ratio")
    bcg_shift = bool(
        isinstance(shift_ratio, (int, float))
        and not isinstance(shift_ratio, bool)
        and float(shift_ratio) >= 0.12
    )
    bed_motion = bool(
        movement_ratio >= move_wake_ratio
        or (statuses and statuses[-1] == 2)
    )
    corroborated = bool(
        acoustic["disturbance_detected"] and (bcg_shift or bed_motion)
    )
    acoustic["bcg_or_motion_corroborated"] = corroborated
    status_counts = _bed_status_counts(frames)
    wake_support = acoustic_wake_support_max if corroborated else 0.0
    return {
        "version": "zeep-bcg-audio-bed-evidence-v1.2-bed-exit-event-guarded",
        "role": "bcg_corroboration_and_quality",
        "direct_stage_sources": ["bcg", "bed_motion"],
        "operational_occupancy_sources": ["bed_exit"],
        "acoustic": acoustic,
        "bed_status": {
            "source": "LSM-800-T",
            **status_counts,
            "weak_breathing_is_diagnostic": False,
            "snoring_is_stage_evidence": False,
        },
        "bcg_corroboration": {
            "amplitude_shift": bcg_shift,
            "bed_motion": bed_motion,
        },
        "corroborated_acoustic_wake_support": round(wake_support, 4),
    }


def _acoustic_evidence(
    frames: Sequence[Mapping[str, Any]],
    *,
    disturbance_dba: float,
    minimum_coverage: float,
) -> dict[str, Any]:
    """Summarise valid in-window sound observations."""
    total_frames = max(1, len(frames))
    values = [
        float(frame["sound_leq_dba"])
        for frame in frames
        if isinstance(frame.get("sound_leq_dba"), (int, float))
        and not isinstance(frame.get("sound_leq_dba"), bool)
        and math.isfinite(float(frame["sound_leq_dba"]))
    ]
    coverage = len(values) / total_frames
    high_frames = sum(value >= disturbance_dba for value in values)
    dynamic_frames = sum(bool(frame.get("sound_large_step")) for frame in frames)
    return {
        "source": "SPH0645",
        "available_frames": len(values),
        "total_frames": len(frames),
        "coverage_percent": round(coverage * 100.0, 1),
        "mean_leq_dba": round(sum(values) / len(values), 2) if values else None,
        "max_leq_dba": round(max(values), 2) if values else None,
        "high_sound_frames": high_frames,
        "dynamic_frames": dynamic_frames,
        "disturbance_detected": bool(
            coverage >= minimum_coverage
            and (high_frames > 0 or dynamic_frames > 0)
        ),
        "standalone_stage_influence": False,
    }


def _bed_status_counts(
    frames: Sequence[Mapping[str, Any]],
) -> dict[str, int]:
    """Count operational and vendor Bed Status evidence."""
    status_sets = [set(frame.get("status_codes_seen") or []) for frame in frames]
    return {
        "moving_frames": sum(2 in values for values in status_sets),
        "bed_exit_frames": sum(
            bool((frame.get("bed_exit_evidence") or {}).get("confirmed"))
            for frame in frames
        ),
        "raw_bed_exit_frames": sum(1 in values for values in status_sets),
        "weak_breathing_frames": sum(3 in values for values in status_sets),
        "snoring_frames": sum(5 in values for values in status_sets),
    }


def sleep_status_event(
    sleep_result: Mapping[str, Any],
    *,
    session_id: str,
    epoch_s: float,
    evidence_epoch_s: float,
    provenance: Mapping[str, str],
    created_at: datetime | None = None,
) -> dict[str, Any]:
    """Build one canonical WAIT, NO DATA or OFF BED derived event."""
    data_status = str(sleep_result.get("data_status") or "no_data")
    state, label = _operational_state(data_status)
    attribution_end = datetime.fromtimestamp(epoch_s, timezone.utc)
    attribution_start = attribution_end - timedelta(seconds=evidence_epoch_s)
    return {
        "session_id": session_id,
        "timestamp": (created_at or datetime.now(timezone.utc)).isoformat(),
        "type": "sleep_stage_status",
        "value": {
            "state": state,
            "label": label,
            "data_status": data_status,
            "reason": sleep_result.get("reason"),
            "confidence": sleep_result.get("confidence") or "unavailable",
            "candidate": (sleep_result.get("evidence") or {}).get("candidate"),
            "confirmation": sleep_result.get("confirmation") or {},
            "provisional": bool(sleep_result.get("provisional", True)),
            "sleep_stage": False,
            "excluded_from_stage_statistics": True,
            "score_eligible": False,
            "excluded_from_score": True,
            "excluded_from_personal_baseline": True,
            "display_only_after_restart": bool(
                sleep_result.get("display_only_after_restart")
            ),
            "attribution_start": attribution_start.isoformat(),
            "attribution_end": attribution_end.isoformat(),
            "sample_interval_s": evidence_epoch_s,
            **provenance,
            "decision_kind": "operational_status",
        },
    }


def _operational_state(data_status: str) -> tuple[str, str]:
    """Map estimator status to the three operational display classes."""
    if data_status in {
        "collecting_evidence_epoch",
        "confirming_initial_state",
        "initial_confirmation_wait",
    }:
        return "wait", "WAIT · กำลังยืนยันสถานะ"
    if data_status in {"empty_bed", "confirmed_off_bed", "no_session"}:
        return "off_bed", "OFF BED · ไม่มีผู้ใช้งานบนเตียง"
    return "no_data", "NO DATA · หลักฐานไม่ครบ"
