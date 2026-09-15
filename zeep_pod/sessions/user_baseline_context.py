"""Publish bounded, target-specific user behaviour Baseline context."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from sleep_system_policy import (
    PERSONAL_BASELINE_LEARNING_START_TIMEZONE,
    PERSONAL_REST_WINDOW_BASELINE_VERSION,
    RECOVERY_SCORE_FORMULA_VERSION,
    RESTORE_BASELINE_MIN_COMPARISON_SESSIONS,
    RESTORE_BASELINE_STABLE_SESSIONS,
    SLEEP_SCORE_FORMULA_VERSION,
    resolve_rest_target,
    rest_mode_group,
)

ENVIRONMENT_FIELDS = (
    "temp_median",
    "humidity_median",
    "co2_median",
    "lux_median",
    "sound_median",
)
REST_WINDOW_TARGETS = {"overnight_7h", "nap_30", "nap_90"}
REST_WINDOW_SCORE_IDENTITIES = {
    "sleep": (
        "sleep_score",
        "Sleep Score",
        SLEEP_SCORE_FORMULA_VERSION,
        30.0,
    ),
    "nap_recovery": (
        "recovery_score",
        "Recovery Score",
        RECOVERY_SCORE_FORMULA_VERSION,
        15.0,
    ),
}


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _window_maturity(sessions: int) -> tuple[str, str]:
    if sessions <= 0:
        return "no_data", "none"
    if sessions == 1:
        return "observed_once", "low"
    if sessions < 3:
        return "learning", "low"
    if sessions < RESTORE_BASELINE_MIN_COMPARISON_SESSIONS:
        return "early", "low"
    if sessions < RESTORE_BASELINE_STABLE_SESSIONS:
        return "active", "medium"
    return "stable", "high"


def _session_count(source: Mapping[str, Any]) -> int:
    try:
        return max(0, int(source.get("sessions_compared") or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


def _window_identity(
    source: Mapping[str, Any],
    fallback_mode_group: str | None,
    fallback_target_key: str | None,
) -> tuple[str, str | None, tuple[str, str, str, float] | None, bool]:
    mode_group = str(
        source.get("mode_group") or fallback_mode_group or "unknown"
    )
    if mode_group not in REST_WINDOW_SCORE_IDENTITIES:
        mode_group = "unknown"
    source_target = (
        source.get("target_key")
        if "target_key" in source
        else fallback_target_key
    )
    target_key = source_target if source_target in REST_WINDOW_TARGETS else None
    target_valid = bool(
        (mode_group == "sleep" and source_target in {None, "overnight_7h"})
        or (
            mode_group == "nap_recovery"
            and source_target in {"nap_30", "nap_90"}
        )
    )
    return (
        mode_group,
        target_key,
        REST_WINDOW_SCORE_IDENTITIES.get(mode_group),
        target_valid,
    )


def _window_observation(
    source: Mapping[str, Any],
    sessions: int,
    score_identity: tuple[str, str, str, float] | None,
    target_valid: bool,
) -> tuple[bool, float | None, float | None, float | None, float | None]:
    start = _number(source.get("start_local_minute"))
    end = _number(source.get("end_local_minute"))
    duration = _number(source.get("duration_minutes"))
    score = _number(source.get("score_value"))
    available = bool(
        source.get("version") == PERSONAL_REST_WINDOW_BASELINE_VERSION
        and source.get("available") is True
        and sessions >= 1
        and score_identity is not None
        and target_valid
        and start is not None
        and 0 <= start < 1440
        and end is not None
        and 0 <= end < 1440
        and duration is not None
        and duration > 0
        and score is not None
        and 0 <= score <= 100
        and source.get("score_type") == score_identity[0]
        and source.get("score_title") == score_identity[1]
        and source.get("score_formula_version") == score_identity[2]
    )
    if available:
        return True, start, end, duration, score
    return False, None, None, None, None


def _window_environment(
    source: Mapping[str, Any],
    outcome_supported: bool,
) -> tuple[bool, dict[str, float]]:
    environment = _mapping(source.get("environment"))
    filtered = {
        key: number
        for key in ENVIRONMENT_FIELDS
        if (number := _number(environment.get(key))) is not None
    }
    available = bool(
        outcome_supported
        and source.get("environment_reference_available")
        and filtered
    )
    return available, filtered if available else {}


def best_rest_window_context(
    value: Any,
    *,
    fallback_target_key: str | None = None,
    fallback_mode_group: str | None = None,
) -> dict[str, Any]:
    source = _mapping(value)
    sessions = _session_count(source)
    mode_group, target_key, score_identity, target_valid = _window_identity(
        source,
        fallback_mode_group,
        fallback_target_key,
    )
    available, start, end, duration, score = _window_observation(
        source,
        sessions,
        score_identity,
        target_valid,
    )
    if not available:
        sessions = 0
    status, maturity = _window_maturity(sessions)
    evidence_quality = str(source.get("evidence_quality") or "unknown")
    if evidence_quality not in {"unknown", "low", "medium", "high"}:
        evidence_quality = "unknown"
    if not available:
        evidence_quality = "unknown"
    outcome_supported = bool(available and source.get("outcome_supported"))
    environment_available, environment = _window_environment(
        source,
        outcome_supported,
    )
    return {
        "version": PERSONAL_REST_WINDOW_BASELINE_VERSION,
        "available": available,
        "status": status,
        "maturity_confidence": maturity,
        "sessions_compared": sessions,
        "first_visible_visit": 2,
        "method": "highest_current_formula_score_then_evidence_then_most_recent",
        "same_mode_only": True,
        "same_target_only": mode_group == "nap_recovery",
        "mode_group": mode_group,
        "target_key": target_key,
        "timezone": PERSONAL_BASELINE_LEARNING_START_TIMEZONE,
        "start_local_minute": start,
        "end_local_minute": end,
        "duration_minutes": duration,
        "crosses_midnight": bool(available and end <= start),
        "start_tolerance_minutes": score_identity[3] if available else None,
        "score_type": score_identity[0] if available else None,
        "score_title": score_identity[1] if available else None,
        "score_value": score,
        "score_formula_version": score_identity[2] if available else None,
        "evidence_quality": evidence_quality,
        "outcome_supported": outcome_supported,
        "environment_reference_available": environment_available,
        "environment": environment,
        "environment_role": (
            "observed_successful_session_not_confirmed_preference"
        ),
        "affects_score": False,
        "affects_sleep_state": False,
        "current_session_excluded": True,
        "automatic_device_control": False,
        "requires_user_confirmation": True,
    }


def rest_window(
    baseline_store: Any,
    account_key: str,
    rest_mode: str,
    target_duration_s: Any,
) -> dict[str, Any]:
    """Resolve one bounded window without exposing the stored cohort."""
    target = resolve_rest_target(rest_mode, target_duration_s)
    target_key = target.get("key") if target.get("available") else None
    try:
        baseline_store.ensure_rest_window_current(account_key)
        behaviour = baseline_store.behaviour_context(
            account_key,
            rest_mode,
            target_duration_s,
        )
    except Exception:
        behaviour = {}
    return best_rest_window_context(
        behaviour.get("best_rest_window"),
        fallback_target_key=target_key,
        fallback_mode_group=rest_mode_group(rest_mode),
    )


def _source(
    baseline: Mapping[str, Any],
    mode: str,
    target_key: str | None = None,
) -> dict[str, Any]:
    grouped = _mapping(baseline.get("behaviour_by_mode"))
    source = _mapping(grouped.get(mode))
    if mode == "nap_recovery" and target_key:
        source = _mapping(_mapping(source.get("by_target")).get(target_key))
    return source


def baseline_context(
    baseline: Mapping[str, Any],
    mode: str,
    target_key: str | None = None,
) -> dict[str, Any]:
    """Return one allowlisted behavior reference, never a preference claim."""
    source = _source(baseline, mode, target_key)
    environment = _mapping(source.get("typical_environment"))
    score_reference = _mapping(source.get("score_reference"))
    return {
        "status": str(source.get("status") or "no_data"),
        "sessions_used": max(0, int(source.get("sessions_used") or 0)),
        "minimum_sessions": max(1, int(source.get("minimum_sessions") or 3)),
        "typical_duration_minutes": _number(source.get("typical_duration_minutes")),
        "typical_start_local_hour": _number(source.get("typical_start_local_hour")),
        "typical_environment": {
            key: number
            for key in ENVIRONMENT_FIELDS
            if (number := _number(environment.get(key))) is not None
        },
        "best_rest_window": best_rest_window_context(
            source.get("best_rest_window"),
            fallback_target_key=target_key,
            fallback_mode_group=mode,
        ),
        "reference_scope": (
            "prior_completed_same_mode_and_target_sessions_only"
            if target_key
            else "prior_completed_same_mode_sessions_only"
        ),
        "environment_role": "observed_exposure_not_user_preference",
        "target_specific": bool(
            target_key or source.get("target_specific", mode == "sleep")
        ),
        "target_key": target_key or source.get("target_key"),
        "baseline_policy_version": baseline.get("behaviour_policy_version"),
        "score_formula_version": score_reference.get("formula_version"),
        "score_reference_status": str(score_reference.get("status") or "no_data"),
        "score_sessions_used": max(
            0,
            int(score_reference.get("sessions_used") or 0),
        ),
        "score_minimum_sessions": max(
            1,
            int(score_reference.get("minimum_sessions") or 7),
        ),
        "direct_device_control": False,
    }
