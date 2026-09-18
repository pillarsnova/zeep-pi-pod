"""Build formula-safe, target-specific personal behaviour baselines."""

from __future__ import annotations

import math
import statistics
from collections.abc import Mapping
from typing import Any

from sessions.respiratory_policy import (
    RESPIRATORY_BASELINE_MIN_COMPARISON_SESSIONS,
)
from sleep_system_policy import (
    PERSONAL_BASELINE_LEARNING_START_TIMEZONE,
    PERSONAL_REST_WINDOW_BASELINE_VERSION,
    RECOVERY_SCORE_FORMULA_VERSION,
    RESPIRATORY_WELLNESS_VERSION,
    RESTORE_BASELINE_MIN_COMPARISON_SESSIONS,
    RESTORE_BASELINE_STABLE_SESSIONS,
    SLEEP_SCORE_FORMULA_VERSION,
)

ENVIRONMENT_KEYS = (
    "temp_median",
    "humidity_median",
    "co2_median",
    "lux_median",
    "sound_median",
)


def _finite_number(value: Any) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value))
    except (OverflowError, TypeError, ValueError):
        return False


def _numbers(rows: list[Mapping[str, Any]], key: str) -> list[float]:
    return [float(row[key]) for row in rows if _finite_number(row.get(key))]


def _percentile(values: list[float], q: float) -> float | None:
    ordered = sorted(values)
    if not ordered:
        return None
    index = (len(ordered) - 1) * q
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = index - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def _typical_range(values: list[float]) -> list[float] | None:
    if not values:
        return None
    low = _percentile(values, 0.25)
    high = _percentile(values, 0.75)
    return (
        [round(low, 1), round(high, 1)]
        if low is not None and high is not None
        else None
    )


def _median(values: list[float], digits: int = 1) -> float | None:
    return round(statistics.median(values), digits) if values else None


def _circular_mean_hour(values: list[float], digits: int = 2) -> float | None:
    """Return a time-of-day mean without treating midnight as midday."""
    if not values:
        return None
    angles = [2.0 * math.pi * (value % 24.0) / 24.0 for value in values]
    x = sum(math.cos(angle) for angle in angles) / len(angles)
    y = sum(math.sin(angle) for angle in angles) / len(angles)
    if math.hypot(x, y) < 1e-12:
        return None
    hour = (math.atan2(y, x) % (2.0 * math.pi)) * 24.0 / (2.0 * math.pi)
    rounded = round(hour, digits)
    return 0.0 if rounded >= 24.0 else rounded


def _formula_for(group: str) -> str:
    return (
        SLEEP_SCORE_FORMULA_VERSION
        if group == "sleep"
        else RECOVERY_SCORE_FORMULA_VERSION
    )


def empty_respiratory_reference(status: str = "learning") -> dict[str, Any]:
    """Return the canonical cold-start contract for paired HR/RR learning."""
    return {
        "status": status,
        "sessions_used": 0,
        "minimum_sessions": RESPIRATORY_BASELINE_MIN_COMPARISON_SESSIONS,
        "median_hr_bpm": None,
        "typical_range_hr_bpm": None,
        "median_rr_brpm": None,
        "typical_range_rr_brpm": None,
        "regularity_median": None,
        "method": "median_and_interquartile_range",
        "requires_paired_hr_rr": True,
        "same_mode_only": True,
        "prior_completed_sessions_only": True,
        "direct_stage_influence": False,
        "affects_score": False,
    }


def respiratory_session_values(value: Any) -> dict[str, Any]:
    """Extract one baseline-safe HR/RR observation from a Session report."""
    source = value if isinstance(value, Mapping) else {}
    observations = source.get("observations") or {}
    confidence = source.get("confidence") or {}
    status = source.get("status") or {}
    vital = source.get("vital_summary") or {}
    eligible = bool(
        isinstance(observations, Mapping)
        and isinstance(confidence, Mapping)
        and isinstance(status, Mapping)
        and isinstance(vital, Mapping)
        and source.get("version") == RESPIRATORY_WELLNESS_VERSION
        and vital.get("available") is True
        and observations.get("paired_hr_rr_evidence_sufficient") is True
        and confidence.get("level") == "high"
        and confidence.get("direct_measurements_only") is True
        and status.get("key") in {"supportive", "observe"}
    )
    return {
        "respiratory_hr_median": (
            observations.get("median_hr_bpm") if eligible else None
        ),
        "respiratory_rr_median": (
            observations.get("median_paired_rr_brpm") if eligible else None
        ),
        "respiratory_regularity_factor": (
            observations.get("regularity_factor") if eligible else None
        ),
    }


def _respiratory_reference(
    rows: list[Mapping[str, Any]],
) -> dict[str, Any]:
    paired_rows = [
        row
        for row in rows
        if _finite_number(row.get("respiratory_hr_median"))
        and _finite_number(row.get("respiratory_rr_median"))
    ]
    heart_rates = _numbers(paired_rows, "respiratory_hr_median")
    breathing_rates = _numbers(paired_rows, "respiratory_rr_median")
    regularity = _numbers(paired_rows, "respiratory_regularity_factor")
    sessions = len(paired_rows)
    reference = empty_respiratory_reference()
    reference.update(
        {
            "status": (
                "active"
                if sessions >= RESPIRATORY_BASELINE_MIN_COMPARISON_SESSIONS
                else "learning"
            ),
            "sessions_used": sessions,
            "median_hr_bpm": _median(heart_rates),
            "typical_range_hr_bpm": _typical_range(heart_rates),
            "median_rr_brpm": _median(breathing_rates),
            "typical_range_rr_brpm": _typical_range(breathing_rates),
            "regularity_median": _median(regularity, 3),
        }
    )
    return reference


def empty_best_rest_window(
    group: str,
    target_key: str | None = None,
) -> dict[str, Any]:
    """Return the stable cold-start contract for a personal rest window."""
    return {
        "version": PERSONAL_REST_WINDOW_BASELINE_VERSION,
        "available": False,
        "status": "no_data",
        "maturity_confidence": "none",
        "sessions_compared": 0,
        "first_visible_visit": 2,
        "method": "highest_current_formula_score_then_evidence_then_most_recent",
        "same_mode_only": True,
        "same_target_only": group == "nap_recovery",
        "mode_group": group,
        "target_key": target_key,
        "timezone": PERSONAL_BASELINE_LEARNING_START_TIMEZONE,
        "outcome_supported": False,
        "affects_score": False,
        "affects_sleep_state": False,
        "current_session_excluded": True,
        "automatic_device_control": False,
        "requires_user_confirmation": True,
    }


def _best_rest_window(
    rows: list[Mapping[str, Any]],
    *,
    group: str,
    target_key: str | None,
) -> dict[str, Any]:
    """Select one prior result without calling it a proven preference."""
    formula = _formula_for(group)
    comparable = [
        row
        for row in rows
        if row.get("score_formula_version") == formula
        and _finite_number(row.get("wellness_score"))
        and _finite_number(row.get("start_local_hour"))
        and _finite_number(row.get("duration_s"))
        and float(row.get("duration_s") or 0) > 0
    ]
    empty = empty_best_rest_window(group, target_key)
    if not comparable:
        return empty

    # Rows arrive newest first. Evidence quality breaks a score tie before
    # ``max`` preserves recency for otherwise equal candidates.
    confidence_rank = {"high": 2, "medium": 1, "low": 0, "unknown": 0}
    best = max(
        comparable,
        key=lambda row: (
            float(row["wellness_score"]),
            confidence_rank.get(str(row.get("score_confidence_level")), 0),
        ),
    )
    start_minutes = int(round(float(best["start_local_hour"]) * 60.0)) % 1440
    duration_minutes = round(float(best["duration_s"]) / 60.0, 1)
    end_minutes = int(round(start_minutes + duration_minutes)) % 1440
    environment = {
        key: round(float(best[key]), 1)
        for key in ENVIRONMENT_KEYS
        if _finite_number(best.get(key))
    }
    count = len(comparable)
    confidence = str(best.get("score_confidence_level") or "unknown")
    environment_eligible = bool(
        best.get("environment_reference_eligible") is True and environment
    )
    return {
        **empty,
        "available": True,
        "status": (
            "observed_once"
            if count == 1
            else "learning"
            if count < 3
            else "early"
            if count < RESTORE_BASELINE_MIN_COMPARISON_SESSIONS
            else "active"
            if count < RESTORE_BASELINE_STABLE_SESSIONS
            else "stable"
        ),
        "maturity_confidence": (
            "low"
            if count < RESTORE_BASELINE_MIN_COMPARISON_SESSIONS
            else "medium"
            if count < RESTORE_BASELINE_STABLE_SESSIONS
            else "high"
        ),
        "sessions_compared": count,
        "start_local_minute": start_minutes,
        "end_local_minute": end_minutes,
        "duration_minutes": duration_minutes,
        "crosses_midnight": end_minutes <= start_minutes,
        "start_tolerance_minutes": 30 if group == "sleep" else 15,
        "score_type": "sleep_score" if group == "sleep" else "recovery_score",
        "score_title": "Sleep Score" if group == "sleep" else "Recovery Score",
        "score_value": round(float(best["wellness_score"]), 1),
        "score_formula_version": formula,
        "evidence_quality": confidence,
        "outcome_supported": bool(best.get("outcome_reference_eligible")),
        "environment_reference_available": environment_eligible,
        "environment": environment if environment_eligible else {},
        "environment_role": "observed_successful_session_not_confirmed_preference",
    }


def _cohort(
    rows: list[Mapping[str, Any]],
    *,
    group: str,
    minimum_sessions: int,
    score_minimum_sessions: int,
    target_specific: bool,
    target_key: str | None = None,
) -> dict[str, Any]:
    formula = _formula_for(group)
    reference_rows = [
        row
        for row in rows
        if row.get("baseline_reference_eligible") is not False
        and _finite_number(row.get("duration_s"))
        and float(row.get("duration_s") or 0) > 0
        and _finite_number(row.get("start_local_hour"))
    ]
    comparable = [
        row
        for row in reference_rows
        if row.get("score_formula_version") == formula
        and _finite_number(row.get("wellness_score"))
    ]
    scores = [float(row["wellness_score"]) for row in reversed(comparable)]
    score_range = _typical_range(scores)
    score_count = len(scores)
    durations = _numbers(reference_rows, "duration_s")
    onset = _numbers(reference_rows, "onset_proxy_s")
    start_hours = _numbers(reference_rows, "start_local_hour")
    return {
        "status": ("active" if len(reference_rows) >= minimum_sessions else "learning"),
        "sessions_used": len(reference_rows),
        "minimum_sessions": minimum_sessions,
        "session_ids": [str(row["session_id"]) for row in reference_rows],
        "target_specific": target_specific,
        "target_key": target_key,
        "scores": scores,
        "score_median": _median(scores),
        "score_typical_range": score_range,
        "score_reference": {
            "status": (
                "active" if score_count >= score_minimum_sessions else "learning"
            ),
            "sessions_used": score_count,
            "minimum_sessions": score_minimum_sessions,
            "median": _median(scores),
            "typical_range": score_range,
            "method": "median_and_interquartile_range",
            "same_mode_only": True,
            "same_target_only": target_specific,
            "prior_completed_sessions_only": True,
            "formula_version": formula,
        },
        "score_formula_versions": sorted(
            {
                str(row["score_formula_version"])
                for row in rows
                if row.get("score_formula_version")
            }
        ),
        "expected_onset_minutes": (
            round(statistics.median(onset) / 60.0, 1) if onset else None
        ),
        "typical_duration_minutes": (
            round(statistics.median(durations) / 60.0, 1) if durations else None
        ),
        "typical_start_local_hour": _circular_mean_hour(start_hours),
        "typical_environment": {
            key: _median(_numbers(reference_rows, key)) for key in ENVIRONMENT_KEYS
        },
        # Paired HR/RR has its own evidence gate. A low-confidence score must
        # not hide otherwise valid vital evidence from this reference.
        "respiratory_reference": _respiratory_reference(rows),
        "best_rest_window": _best_rest_window(
            rows,
            group=group,
            target_key=target_key,
        ),
        "direct_stage_influence": False,
        "role": "expectation_report_and_confidence_context_only",
    }


def aggregate_behaviour_by_mode(
    sessions: list[Mapping[str, Any]],
    *,
    minimum_sessions: int,
    score_minimum_sessions: int,
    max_sessions: int,
) -> dict[str, dict[str, Any]]:
    """Partition behaviour by mode, formula and persisted Nap target."""
    grouped: dict[str, dict[str, Any]] = {}
    groups = sorted({str(row.get("mode_group") or "unknown") for row in sessions})
    for group in groups:
        group_rows = [
            row for row in sessions if str(row.get("mode_group") or "unknown") == group
        ]
        rows = group_rows[:max_sessions]
        context = _cohort(
            rows,
            group=group,
            minimum_sessions=minimum_sessions,
            score_minimum_sessions=score_minimum_sessions,
            target_specific=group == "sleep",
            target_key="overnight_7h" if group == "sleep" else None,
        )
        if group == "nap_recovery":
            context["scores"] = []
            context["score_median"] = None
            context["score_typical_range"] = None
            # Nap 30 and Nap 90 answer different rest goals. The parent cohort
            # is navigation/QA only and must never publish a mixed-target window.
            context["best_rest_window"] = empty_best_rest_window(group)
            context["score_reference"] = {
                **context["score_reference"],
                "status": "target_required",
                "sessions_used": 0,
                "median": None,
                "typical_range": None,
                "same_target_only": True,
            }
            context["by_target"] = {
                target_key: _cohort(
                    [row for row in group_rows if row.get("target_key") == target_key][
                        :max_sessions
                    ],
                    group=group,
                    minimum_sessions=minimum_sessions,
                    score_minimum_sessions=score_minimum_sessions,
                    target_specific=True,
                    target_key=target_key,
                )
                for target_key in ("nap_30", "nap_90")
            }
            context["unresolved_target_sessions"] = sum(
                row.get("target_key") not in {"nap_30", "nap_90"} for row in group_rows
            )
        grouped[group] = context
    return grouped
