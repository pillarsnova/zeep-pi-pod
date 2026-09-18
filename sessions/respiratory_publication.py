"""Canonical customer projection for respiratory Wellness summaries."""

from __future__ import annotations

import math
from typing import Any

from presentation.language import (
    user_confidence_level,
    user_paired_vital_status,
    user_respiratory_age_context,
    user_respiratory_baseline_copy,
    user_respiratory_interpretation,
    user_respiratory_recommendation,
    user_respiratory_status,
)
from sessions.publication_values import mapping, scalar_list
from sessions.respiratory_policy import (
    RESPIRATORY_ADULT_CONTEXT_RANGE_BRPM,
    RESPIRATORY_ADULT_RECHECK_RANGE_BRPM,
    RESPIRATORY_BASELINE_MIN_COMPARISON_SESSIONS,
    RESPIRATORY_MINIMUM_CONTEXT_COVERAGE_PCT,
    RESPIRATORY_MINIMUM_PAIRED_RUN_SECONDS,
    RESPIRATORY_MINIMUM_VALID_SAMPLES,
    RESPIRATORY_MINIMUM_VALID_SECONDS,
)
from sleep_system_policy import RESPIRATORY_WELLNESS_VERSION

REGULARITY_KEYS = {"stable", "mixed", "variable", "insufficient"}
REASON_CODES = {
    "no_sensor_samples",
    "no_confirmed_occupancy",
    "historical_provenance_unavailable",
    "insufficient_valid_duration",
    "low_valid_coverage",
    "needs_standard_recheck",
}


def _bounded_number(
    value: Any,
    *,
    minimum: float,
    maximum: float,
) -> float | None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
    ):
        return None
    number = float(value)
    return number if minimum <= number <= maximum else None


def _numeric_pair(
    value: Any,
    *,
    minimum: float,
    maximum: float,
) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    low = _bounded_number(value[0], minimum=minimum, maximum=maximum)
    high = _bounded_number(value[1], minimum=minimum, maximum=maximum)
    if low is None or high is None or low > high:
        return None
    return [low, high]


def _session_count(value: Any) -> int:
    number = _bounded_number(value, minimum=0.0, maximum=10_000.0)
    return int(number) if number is not None and number.is_integer() else 0


def _number_or(
    value: Any,
    *,
    minimum: float,
    maximum: float,
    default: float = 0.0,
) -> float:
    number = _bounded_number(value, minimum=minimum, maximum=maximum)
    return number if number is not None else default


def _observation_numbers(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "valid_samples": _session_count(raw.get("valid_samples")),
        "paired_hr_rr_samples": _session_count(raw.get("paired_hr_rr_samples")),
        "paired_hr_rr_minutes": _number_or(
            raw.get("paired_hr_rr_minutes"), minimum=0.0, maximum=10_000.0
        ),
        "paired_hr_rr_coverage_pct": _number_or(
            raw.get("paired_hr_rr_coverage_pct"), minimum=0.0, maximum=100.0
        ),
        "longest_paired_hr_rr_run_seconds": _number_or(
            raw.get("longest_paired_hr_rr_run_seconds"),
            minimum=0.0,
            maximum=1_000_000.0,
        ),
        "longest_valid_run_samples": _session_count(
            raw.get("longest_valid_run_samples")
        ),
        "longest_valid_run_seconds": _number_or(
            raw.get("longest_valid_run_seconds"),
            minimum=0.0,
            maximum=1_000_000.0,
        ),
        "valid_minutes": _number_or(
            raw.get("valid_minutes"), minimum=0.0, maximum=10_000.0
        ),
        "occupied_minutes": _number_or(
            raw.get("occupied_minutes"), minimum=0.0, maximum=10_000.0
        ),
        "coverage_pct": _number_or(raw.get("coverage_pct"), minimum=0.0, maximum=100.0),
        "excluded_motion_or_weak_signal_minutes": _number_or(
            raw.get("excluded_motion_or_weak_signal_minutes"),
            minimum=0.0,
            maximum=10_000.0,
        ),
        "excluded_invalid_or_held_minutes": _number_or(
            raw.get("excluded_invalid_or_held_minutes"),
            minimum=0.0,
            maximum=10_000.0,
        ),
    }


def _observations(source: dict[str, Any], *, trusted_version: bool) -> dict[str, Any]:
    raw = mapping(source.get("observations")) if trusted_version else {}
    public = _observation_numbers(raw)
    public.update(
        {
            "median_hr_bpm": _bounded_number(
                raw.get("median_hr_bpm"), minimum=30.0, maximum=220.0
            ),
            "median_paired_rr_brpm": _bounded_number(
                raw.get("median_paired_rr_brpm"), minimum=4.0, maximum=60.0
            ),
            "median_rr_brpm": _bounded_number(
                raw.get("median_rr_brpm"), minimum=4.0, maximum=60.0
            ),
            "p10_rr_brpm": _bounded_number(
                raw.get("p10_rr_brpm"), minimum=4.0, maximum=60.0
            ),
            "p90_rr_brpm": _bounded_number(
                raw.get("p90_rr_brpm"), minimum=4.0, maximum=60.0
            ),
            "regularity_factor": _bounded_number(
                raw.get("regularity_factor"), minimum=0.0, maximum=1.0
            ),
            "regularity_key": (
                raw.get("regularity_key")
                if raw.get("regularity_key") in REGULARITY_KEYS
                else "insufficient"
            ),
        }
    )
    paired_minutes = public["paired_hr_rr_minutes"]
    internally_consistent = bool(
        public["paired_hr_rr_samples"] <= public["valid_samples"]
        and paired_minutes <= public["valid_minutes"]
        and paired_minutes <= public["occupied_minutes"]
    )
    sufficient = bool(
        raw.get("paired_hr_rr_evidence_sufficient") is True
        and public["median_hr_bpm"] is not None
        and public["median_paired_rr_brpm"] is not None
        and public["paired_hr_rr_samples"] >= RESPIRATORY_MINIMUM_VALID_SAMPLES
        and paired_minutes * 60.0 >= RESPIRATORY_MINIMUM_VALID_SECONDS
        and public["longest_paired_hr_rr_run_seconds"]
        >= RESPIRATORY_MINIMUM_PAIRED_RUN_SECONDS
        and public["paired_hr_rr_coverage_pct"]
        >= RESPIRATORY_MINIMUM_CONTEXT_COVERAGE_PCT
        and internally_consistent
    )
    public["paired_hr_rr_evidence_sufficient"] = sufficient
    if not sufficient:
        public["median_hr_bpm"] = None
        public["median_paired_rr_brpm"] = None
    return public


def _personal_baseline(source: dict[str, Any]) -> dict[str, Any]:
    raw = mapping(source.get("personal_baseline"))
    status = str(raw.get("status") or "not_ready")
    sessions_used = _session_count(raw.get("sessions_used"))
    hr_median = _bounded_number(raw.get("median_hr_bpm"), minimum=30.0, maximum=220.0)
    rr_median = _bounded_number(raw.get("median_rr_brpm"), minimum=4.0, maximum=60.0)
    hr_pair = _numeric_pair(
        raw.get("typical_range_hr_bpm"), minimum=30.0, maximum=220.0
    )
    rr_pair = _numeric_pair(raw.get("typical_range_rr_brpm"), minimum=4.0, maximum=60.0)
    delta_hr = _bounded_number(raw.get("delta_hr_bpm"), minimum=-190.0, maximum=190.0)
    delta_rr = _bounded_number(raw.get("delta_rr_brpm"), minimum=-56.0, maximum=56.0)
    reference_ready = bool(
        raw.get("reference_ready") is True
        and sessions_used >= RESPIRATORY_BASELINE_MIN_COMPARISON_SESSIONS
        and raw.get("requires_paired_hr_rr") is True
        and raw.get("same_mode_only") is True
        and raw.get("prior_sessions_only") is True
        and raw.get("affects_score") is False
        and hr_median is not None
        and rr_median is not None
        and hr_pair is not None
        and rr_pair is not None
    )
    available = bool(
        reference_ready
        and raw.get("available") is True
        and status in {"below", "within", "above"}
    )
    published_sessions = (
        sessions_used
        if reference_ready
        or sessions_used < RESPIRATORY_BASELINE_MIN_COMPARISON_SESSIONS
        else 0
    )
    public = {
        "available": available,
        "reference_ready": reference_ready,
        "status": status if available else "not_ready",
        "sessions_used": published_sessions,
        "minimum_sessions": RESPIRATORY_BASELINE_MIN_COMPARISON_SESSIONS,
        "requires_paired_hr_rr": True,
        "affects_score": False,
    }
    public["label"], public["reason"] = user_respiratory_baseline_copy(
        status,
        available=available,
        reference_ready=reference_ready,
    )
    if reference_ready:
        public.update(
            {
                "median_hr_bpm": hr_median,
                "typical_range_hr_bpm": hr_pair,
                "median_rr_brpm": rr_median,
                "typical_range_rr_brpm": rr_pair,
                "same_mode_only": True,
                "prior_sessions_only": True,
            }
        )
    if available:
        if delta_hr is not None:
            public["delta_hr_bpm"] = delta_hr
        if delta_rr is not None:
            public["delta_rr_brpm"] = delta_rr
    return public


def _age_context(source: dict[str, Any]) -> dict[str, Any]:
    raw = mapping(source.get("age_context"))
    band, label, guidance = user_respiratory_age_context(
        raw.get("age_band") if raw.get("available") is True else None
    )
    return {
        "available": band is not None,
        "age_band": band,
        "label": label,
        "guidance": guidance,
        "role": "context_only",
        "threshold_adjustment_applied": False,
        "note": ("ช่วงอายุใช้ช่วยอธิบายแนวโน้มเท่านั้น ไม่ได้เปลี่ยนคะแนนหรือเกณฑ์การหายใจ"),
    }


def _confidence(source: dict[str, Any]) -> dict[str, Any]:
    level = str(mapping(source.get("confidence")).get("level") or "low")
    if level not in {"high", "medium", "low"}:
        level = "low"
    return {
        "level": level,
        "label": user_confidence_level(level),
        "direct_measurements_only": True,
        "carried_state_excluded": True,
    }


def _reference_context(source: dict[str, Any]) -> dict[str, Any]:
    raw = mapping(source.get("reference_context"))
    public = {
        "adult_orientation_range_brpm": list(RESPIRATORY_ADULT_CONTEXT_RANGE_BRPM),
        "recheck_range_brpm": list(RESPIRATORY_ADULT_RECHECK_RANGE_BRPM),
        "ranges_are_diagnostic": False,
        "age_specific_cutoff_applied": False,
        "regularity_is_internal_wellness_policy": True,
    }
    for field in ("adult_orientation_range_brpm", "recheck_range_brpm"):
        pair = _numeric_pair(raw.get(field), minimum=4.0, maximum=60.0)
        if pair is not None:
            public[field] = pair
    return public


def _fixed_sections(status_key: str) -> dict[str, Any]:
    return {
        "recommendation": {
            "primary": user_respiratory_recommendation(status_key),
            "medical_advice": False,
            "automatic_actuation": False,
        },
        "measurement_requirements": {
            "lung_function": "ต้องใช้การตรวจสมรรถภาพปอด เช่น Spirometry/PFT",
            "oxygenation": "ต้องใช้เครื่องวัด SpO₂ ที่เหมาะสม",
            "whole_body_fitness": "ต้องมีข้อมูลกิจกรรมและการประเมินสมรรถภาพเพิ่มเติม",
        },
        "capabilities": {
            "breathing_pattern": "estimated_from_direct_bcg_hr_rr",
            "lung_function": "not_measured",
            "blood_oxygen": "not_measured",
            "whole_body_fitness": "not_measured",
        },
        "claim_boundary": {
            "wellness_estimate": True,
            "lung_strength_assessed": False,
            "oxygen_saturation_measured": False,
            "sleep_apnea_screening": False,
            "medical_diagnosis": False,
            "changes_sleep_state": False,
            "changes_sleep_score": False,
            "changes_recovery_score": False,
        },
    }


def _vital_summary(
    status_key: str,
    observations: dict[str, Any],
) -> dict[str, Any]:
    paired_ready = observations.get("paired_hr_rr_evidence_sufficient") is True
    heart_rate = observations.get("median_hr_bpm") if paired_ready else None
    respiration_rate = (
        observations.get("median_paired_rr_brpm") if paired_ready else None
    )
    combined_key, combined_label = user_paired_vital_status(
        status_key,
        heart_rate,
        respiration_rate,
    )
    recommendation_key = (
        status_key if combined_key != "insufficient" else "insufficient"
    )
    return {
        "available": combined_key != "insufficient",
        "status": combined_key,
        "status_label": combined_label,
        "heart_rate_bpm": heart_rate,
        "respiration_rate_brpm": respiration_rate,
        "summary": user_respiratory_interpretation(
            status_key,
            heart_rate,
            respiration_rate,
        ),
        "recommendation": user_respiratory_recommendation(recommendation_key),
        "basis": "direct_paired_hr_rr",
        "aggregation": "weighted_median",
        "wellness_only": True,
        "medical_diagnosis": False,
    }


def public_respiratory_wellness(value: Any) -> dict[str, Any]:
    """Publish respiratory aggregates without trusting persisted prose."""
    source = mapping(value)
    trusted_version = source.get("version") == RESPIRATORY_WELLNESS_VERSION
    status_key, status_label = user_respiratory_status(
        mapping(source.get("status")).get("key") if trusted_version else None
    )
    context = str(source.get("context") or "unknown")
    if context not in {"overnight_sleep", "nap_or_rest", "unknown"}:
        context = "unknown"
    observations = _observations(source, trusted_version=trusted_version)
    baseline = _personal_baseline(source if trusted_version else {})
    vital_summary = _vital_summary(status_key, observations)
    source_available = bool(
        trusted_version
        and source.get("available") is True
        and status_key != "insufficient"
    )
    if not source_available or vital_summary["available"] is not True:
        status_key, status_label = user_respiratory_status("insufficient")
        vital_summary = _vital_summary(status_key, observations)
    reason_codes = [
        item for item in scalar_list(source.get("reason_codes")) if item in REASON_CODES
    ]
    if not trusted_version and "historical_provenance_unavailable" not in reason_codes:
        reason_codes.append("historical_provenance_unavailable")
    public = {
        "version": RESPIRATORY_WELLNESS_VERSION,
        "available": vital_summary["available"],
        "label": "ชีพจรและการหายใจขณะพัก",
        "intended_use": "age_contextual_wellness_pattern_not_lung_function",
        "context": context,
        "status": {"key": status_key, "label": status_label},
        "reason_codes": reason_codes,
        "interpretation": vital_summary["summary"],
        "observations": observations,
        "vital_summary": vital_summary,
        "confidence": _confidence(
            source if trusted_version and vital_summary["available"] is True else {}
        ),
        "age_context": _age_context(source),
        "personal_baseline": baseline,
        "reference_context": _reference_context(source),
    }
    public.update(_fixed_sections(status_key))
    public["recommendation"]["primary"] = vital_summary["recommendation"]
    return public
