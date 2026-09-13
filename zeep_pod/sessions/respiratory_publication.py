"""Canonical customer projection for respiratory Wellness summaries."""

from __future__ import annotations

import math
from typing import Any

from zeep_pod.product_language import (
    user_confidence_level,
    user_paired_vital_status,
    user_respiratory_age_context,
    user_respiratory_baseline_copy,
    user_respiratory_interpretation,
    user_respiratory_recommendation,
    user_respiratory_status,
)
from zeep_pod.sessions.publication_values import copy_scalars, mapping, scalar_list

OBSERVATION_FIELDS = {
    "median_hr_bpm",
    "median_paired_rr_brpm",
    "median_rr_brpm",
    "p10_rr_brpm",
    "p90_rr_brpm",
    "regularity_factor",
    "regularity_key",
    "valid_samples",
    "paired_hr_rr_samples",
    "paired_hr_rr_minutes",
    "paired_hr_rr_coverage_pct",
    "longest_paired_hr_rr_run_seconds",
    "paired_hr_rr_evidence_sufficient",
    "longest_valid_run_samples",
    "longest_valid_run_seconds",
    "valid_minutes",
    "occupied_minutes",
    "coverage_pct",
    "excluded_motion_or_weak_signal_minutes",
    "excluded_invalid_or_held_minutes",
}
REGULARITY_KEYS = {"stable", "mixed", "variable", "insufficient"}
REASON_CODES = {
    "no_sensor_samples",
    "no_confirmed_occupancy",
    "historical_provenance_unavailable",
    "insufficient_valid_duration",
    "low_valid_coverage",
    "needs_standard_recheck",
}


def _numeric_pair(value: Any) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    if any(
        isinstance(item, bool)
        or not isinstance(item, (int, float))
        or not math.isfinite(float(item))
        for item in value
    ):
        return None
    return [float(value[0]), float(value[1])]


def _observations(source: dict[str, Any]) -> dict[str, Any]:
    public = copy_scalars(source.get("observations"), OBSERVATION_FIELDS)
    for field, default in {
        "paired_hr_rr_samples": 0,
        "paired_hr_rr_minutes": 0.0,
        "paired_hr_rr_coverage_pct": 0.0,
        "longest_paired_hr_rr_run_seconds": 0.0,
        "paired_hr_rr_evidence_sufficient": False,
    }.items():
        public.setdefault(field, default)
    if public.get("regularity_key") not in REGULARITY_KEYS:
        public["regularity_key"] = "insufficient"
    return public


def _personal_baseline(source: dict[str, Any]) -> dict[str, Any]:
    raw = mapping(source.get("personal_baseline"))
    status = str(raw.get("status") or "not_ready")
    available = bool(raw.get("available") is True and status in {"below", "within", "above"})
    public = copy_scalars(
        raw,
        {
            "sessions_used",
            "minimum_sessions",
            "median_rr_brpm",
            "delta_rr_brpm",
            "same_mode_only",
            "prior_sessions_only",
            "affects_score",
        },
    )
    public["available"] = available
    public["status"] = status if available else "not_ready"
    public["label"], public["reason"] = user_respiratory_baseline_copy(
        status,
        available=available,
    )
    if not available:
        for key in (
            "median_rr_brpm",
            "delta_rr_brpm",
            "same_mode_only",
            "prior_sessions_only",
        ):
            public.pop(key, None)
    pair = _numeric_pair(raw.get("typical_range_rr_brpm"))
    if available and pair is not None:
        public["typical_range_rr_brpm"] = pair
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
        "note": "ช่วงอายุใช้ช่วยอธิบายแนวโน้มเท่านั้น ไม่ได้เปลี่ยนคะแนนหรือเกณฑ์การหายใจ",
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
        "ranges_are_diagnostic": False,
        "age_specific_cutoff_applied": False,
        "regularity_is_internal_wellness_policy": True,
    }
    for field in ("adult_orientation_range_brpm", "recheck_range_brpm"):
        pair = _numeric_pair(raw.get(field))
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
            "breathing_pattern": "estimated_from_direct_bcg_rr",
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
    respiration_rate = observations.get("median_paired_rr_brpm") if paired_ready else None
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
        "recommendation": user_respiratory_recommendation(
            recommendation_key
        ),
        "basis": "direct_paired_hr_rr",
        "aggregation": "weighted_median",
        "wellness_only": True,
        "medical_diagnosis": False,
    }


def public_respiratory_wellness(value: Any) -> dict[str, Any]:
    """Publish respiratory aggregates without trusting persisted prose."""
    source = mapping(value)
    status_key, status_label = user_respiratory_status(mapping(source.get("status")).get("key"))
    context = str(source.get("context") or "unknown")
    if context not in {"overnight_sleep", "nap_or_rest", "unknown"}:
        context = "unknown"
    observations = _observations(source)
    baseline = _personal_baseline(source)
    vital_summary = _vital_summary(status_key, observations)
    public = {
        "version": source.get("version"),
        "available": bool(source.get("available") is True and status_key != "insufficient"),
        "label": "ชีพจรและการหายใจระหว่างพัก",
        "intended_use": "age_contextual_wellness_pattern_not_lung_function",
        "context": context,
        "status": {"key": status_key, "label": status_label},
        "reason_codes": [item for item in scalar_list(source.get("reason_codes")) if item in REASON_CODES],
        "interpretation": vital_summary["summary"],
        "observations": observations,
        "vital_summary": vital_summary,
        "confidence": _confidence(source),
        "age_context": _age_context(source),
        "personal_baseline": baseline,
        "reference_context": _reference_context(source),
    }
    public.update(_fixed_sections(status_key))
    public["recommendation"]["primary"] = vital_summary["recommendation"]
    return public
