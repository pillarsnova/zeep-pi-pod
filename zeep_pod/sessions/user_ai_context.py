"""Allowlist-only personal context for future advisory AI inference."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from typing import Any

from sleep_system_policy import (
    APPROVED_SCORE_FORMULA_VERSIONS_BY_GROUP,
    PERSONAL_BEHAVIOUR_BASELINE_VERSION,
)
from zeep_pod.sessions.user_ai_response_models import UserAiContext

USER_AI_CONTEXT_VERSION = "zeep.user-ai-context.v1"
SOURCE_PROFILE_VERSION = "zeep.user-learning-profile.v1"
SOURCE_POLICY_VERSION = "zeep.user-learning-policy.v1"
MODE_KEYS = ("sleep", "nap_recovery")
NAP_TARGET_MINUTES = {"nap_30": 30.0, "nap_90": 90.0}
TREND_DIRECTIONS = {
    "higher",
    "lower",
    "stable",
    "insufficient_history",
    "formula_changed",
    "formula_unverified",
    "target_specific_only",
}
BASELINE_STATUSES = {"no_data", "learning", "active", "target_required"}
BASELINE_TARGET_KEYS = {"overnight_7h", *NAP_TARGET_MINUTES}
READINESS_STATUSES = {"no_data", "learning", "growing", "established"}
APPROVED_FORMULAS = frozenset().union(
    *APPROVED_SCORE_FORMULA_VERSIONS_BY_GROUP.values()
)


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _items(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list | tuple) else []


def _number(
    value: Any,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    if minimum is not None and number < minimum:
        return None
    if maximum is not None and number > maximum:
        return None
    return number


def _count(value: Any, default: int = 0) -> int:
    number = _number(value, minimum=0)
    return int(number) if number is not None else default


def _flag(value: Any) -> bool:
    return value is True


def _allowed(value: Any, allowed: set[str] | frozenset[str], default: str):
    candidate = value if isinstance(value, str) else None
    return candidate if candidate in allowed else default


def _formula(value: Any) -> str | None:
    candidate = value if isinstance(value, str) else None
    return candidate if candidate in APPROVED_FORMULAS else None


def _score(value: Any) -> float | None:
    return _number(value, minimum=0, maximum=100)


def _trend(value: Any) -> dict[str, Any]:
    source = _mapping(value)
    direction = _allowed(
        source.get("direction"),
        TREND_DIRECTIONS,
        "insufficient_history",
    )
    formula = _formula(source.get("formula_version"))
    available = bool(
        _flag(source.get("available"))
        and direction in {"higher", "lower", "stable"}
        and formula is not None
    )
    return {
        "available": available,
        "direction": direction,
        "change_points": (_number(source.get("change_points")) if available else None),
        "formula_version": formula,
        "comparable_scores": _count(source.get("comparable_scores")),
    }


def _environment(value: Any) -> dict[str, float | None]:
    source = _mapping(value)
    return {
        key: _number(source.get(key))
        for key in (
            "temp_median",
            "humidity_median",
            "co2_median",
            "lux_median",
            "sound_median",
        )
    }


def _baseline(value: Any) -> dict[str, Any]:
    source = _mapping(value)
    target_key = source.get("target_key")
    target_key = (
        target_key
        if isinstance(target_key, str) and target_key in BASELINE_TARGET_KEYS
        else None
    )
    policy = source.get("baseline_policy_version")
    return {
        "status": _allowed(
            source.get("status"),
            BASELINE_STATUSES,
            "no_data",
        ),
        "sessions_used": _count(source.get("sessions_used")),
        "minimum_sessions": max(
            1,
            _count(source.get("minimum_sessions"), 3),
        ),
        "typical_duration_minutes": _number(
            source.get("typical_duration_minutes"),
            minimum=0,
        ),
        "typical_environment": _environment(source.get("typical_environment")),
        "target_specific": _flag(source.get("target_specific")),
        "target_key": target_key,
        "baseline_policy_version": (
            PERSONAL_BEHAVIOUR_BASELINE_VERSION
            if policy == PERSONAL_BEHAVIOUR_BASELINE_VERSION
            else None
        ),
        "score_formula_version": _formula(source.get("score_formula_version")),
        "score_reference_status": _allowed(
            source.get("score_reference_status"),
            BASELINE_STATUSES,
            "no_data",
        ),
        "score_sessions_used": _count(source.get("score_sessions_used")),
        "score_minimum_sessions": max(
            1,
            _count(source.get("score_minimum_sessions"), 7),
        ),
        "environment_is_observed_exposure": True,
    }


def _target(value: Any) -> dict[str, Any] | None:
    source = _mapping(value)
    target_key = source.get("key")
    if not isinstance(target_key, str) or target_key not in NAP_TARGET_MINUTES:
        return None
    return {
        "key": target_key,
        "minutes": NAP_TARGET_MINUTES[target_key],
        "session_count": max(1, _count(source.get("session_count"), 1)),
        "scored_count": _count(source.get("scored_count")),
        "comparable_scored_count": _count(source.get("comparable_scored_count")),
        "without_score_count": _count(source.get("without_score_count")),
        "latest_score": _score(source.get("latest_score")),
        "average_score": _score(source.get("average_score")),
        "median_score": _score(source.get("median_score")),
        "active_formula_version": _formula(source.get("active_formula_version")),
        "trend": _trend(source.get("trend")),
        "baseline": _baseline(source.get("baseline")),
    }


def _mode(value: Any, expected_key: str) -> dict[str, Any]:
    source = _mapping(value)
    targets = []
    if expected_key == "nap_recovery":
        targets = [
            target
            for item in _items(source.get("targets"))
            if (target := _target(item)) is not None
        ]
    return {
        "key": expected_key,
        "score_type": ("sleep_score" if expected_key == "sleep" else "recovery_score"),
        "session_count": _count(source.get("session_count")),
        "data_backed_session_count": _count(source.get("data_backed_session_count")),
        "without_sensor_data_count": _count(source.get("without_sensor_data_count")),
        "scored_count": _count(source.get("scored_count")),
        "latest_score": _score(source.get("latest_score")),
        "average_score": _score(source.get("average_score")),
        "median_score": _score(source.get("median_score")),
        "active_formula_version": _formula(source.get("active_formula_version")),
        "trend": _trend(source.get("trend")),
        "targets": targets,
        "unresolved_target_session_count": _count(
            source.get("unresolved_target_session_count")
        ),
        "baseline": _baseline(source.get("baseline")),
    }


def _gap_codes(
    profile: Mapping[str, Any],
    history: Mapping[str, Any],
    modes: Mapping[str, Mapping[str, Any]],
    ready_modes: list[str],
    ready_targets: list[str],
) -> list[str]:
    codes = []
    if _count(history.get("session_count")) == 0:
        codes.append("no_completed_session_history")
    modes_used = _items(history.get("modes_used"))
    if "sleep" in modes_used and "sleep" not in ready_modes:
        codes.append("sleep_personal_baseline_insufficient")
    nap_targets = {item["key"] for item in modes["nap_recovery"]["targets"]}
    for target_key in ("nap_30", "nap_90"):
        if target_key in nap_targets and target_key not in ready_targets:
            codes.append(f"{target_key}_personal_baseline_insufficient")
    if modes["nap_recovery"]["unresolved_target_session_count"]:
        codes.append("nap_target_unresolved")
    if _count(history.get("without_sensor_data_count")):
        codes.append("sensor_data_missing")
    if _count(history.get("without_score_count")):
        codes.append("score_missing")
    questionnaire = _mapping(
        _mapping(profile.get("profile_context")).get("questionnaire")
    )
    if questionnaire.get("consent_status") != "granted":
        codes.append("lifestyle_context_consent_unavailable")
    return codes


def _readiness(
    profile: Mapping[str, Any],
    source: Mapping[str, Any],
    history: Mapping[str, Any],
    modes: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    ready_modes = [
        key
        for key in _items(source.get("personal_comparison_ready_modes"))
        if key in MODE_KEYS
    ]
    ready_targets = [
        key
        for key in _items(source.get("personal_comparison_ready_targets"))
        if key in NAP_TARGET_MINUTES
    ]
    return {
        "data_sufficiency_status": _allowed(
            source.get("status"),
            READINESS_STATUSES,
            "no_data",
        ),
        "personal_comparison_ready_modes": ready_modes,
        "personal_comparison_ready_targets": ready_targets,
        "multi_mode_context_ready": _flag(source.get("multi_mode_context_ready")),
        "personalization_data_ready": bool(ready_modes),
        "personalization_inference_authorized": False,
        "inference_authorization_status": ("purpose_specific_consent_unavailable"),
        "data_gap_codes": _gap_codes(
            profile,
            history,
            modes,
            ready_modes,
            ready_targets,
        ),
    }


def _project_user_ai_context(profile: Mapping[str, Any]) -> dict[str, Any]:
    history_source = _mapping(profile.get("observed_history"))
    modes_source = _mapping(profile.get("modes"))
    readiness_source = _mapping(profile.get("learning_readiness"))
    history = {
        "session_count": _count(history_source.get("session_count")),
        "data_backed_session_count": _count(
            history_source.get("data_backed_session_count")
        ),
        "without_sensor_data_count": _count(
            history_source.get("without_sensor_data_count")
        ),
        "scored_count": _count(history_source.get("scored_count")),
        "without_score_count": _count(history_source.get("without_score_count")),
        "usage_minutes": _number(
            history_source.get("usage_minutes"),
            minimum=0,
        )
        or 0.0,
        "modes_used": [
            key for key in _items(history_source.get("modes_used")) if key in MODE_KEYS
        ],
    }
    modes = {key: _mode(modes_source.get(key), key) for key in MODE_KEYS}
    return {
        "contract_version": USER_AI_CONTEXT_VERSION,
        "source_profile_version": SOURCE_PROFILE_VERSION,
        "source_policy_version": SOURCE_POLICY_VERSION,
        "observed_history": history,
        "modes": modes,
        "learning_readiness": _readiness(
            profile,
            readiness_source,
            history,
            modes,
        ),
        "guardrails": {
            "wellness_advisory_only": True,
            "privacy_classification": (
                "direct_identifier_free_linkable_personal_wellness_data"
            ),
            "direct_identifiers_included": False,
            "linkable_personal_wellness_data": True,
            "anonymous_or_deidentified": False,
            "session_identifiers_included": False,
            "exact_session_timestamps_included": False,
            "questionnaire_answers_included": False,
            "demographics_included": False,
            "medical_inference_allowed": False,
            "personalized_inference_allowed": False,
            "model_training_allowed": False,
            "cross_user_learning_allowed": False,
            "automatic_device_control_allowed": False,
            "recommendation_requires_user_confirmation": True,
        },
    }


def validated_user_ai_context(profile: Mapping[str, Any]) -> dict[str, Any]:
    """Return only validated, JSON-compatible AI egress data (no envelope)."""
    payload = _project_user_ai_context(profile)
    validate = getattr(UserAiContext, "model_validate", None)
    model = (
        validate(payload) if validate is not None else UserAiContext.parse_obj(payload)
    )
    dump = getattr(model, "model_dump", None)
    if dump is not None:
        return dump(mode="json", by_alias=True)
    return json.loads(model.json(by_alias=True))


def build_user_ai_context(profile: Mapping[str, Any]) -> dict[str, Any]:
    """Backward-compatible name for the validated data-only projection."""
    return validated_user_ai_context(profile)
