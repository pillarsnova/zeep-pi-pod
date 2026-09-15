"""Publish bounded, target-specific user behaviour Baseline context."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

ENVIRONMENT_FIELDS = (
    "temp_median",
    "humidity_median",
    "co2_median",
    "lux_median",
    "sound_median",
)


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


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
        "score_reference_status": str(
            score_reference.get("status") or "no_data"
        ),
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
