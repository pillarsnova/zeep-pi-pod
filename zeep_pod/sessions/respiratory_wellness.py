"""Age-aware, non-diagnostic interpretation of BCG breathing patterns.

This Wellness summary never changes a State, Score, or hardware command.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from sleep_system_policy import (
    RESPIRATORY_WELLNESS_VERSION,
    RESTORE_BASELINE_MIN_COMPARISON_SESSIONS,
    rest_mode_group,
)
from zeep_pod.product_language import (
    RESPIRATORY_AGE_GUIDANCE,
    RESPIRATORY_AGE_LABELS,
    RESPIRATORY_STATUS_LABELS,
    user_paired_vital_status,
    user_respiratory_interpretation,
    user_respiratory_recommendation,
)
from zeep_pod.sessions.respiratory_evidence import (
    finite_number,
    sample_interval,
    weighted_quantile,
)
from zeep_pod.sessions.respiratory_metrics import (
    build_observations,
    collect_metrics,
)

ADULT_CONTEXT_RANGE_BRPM = (12.0, 20.0)
ADULT_RECHECK_RANGE_BRPM = (8.0, 25.0)
MINIMUM_VALID_SECONDS = 120.0
RECHECK_MINIMUM_VALID_SECONDS = 300.0
# Four 30-second rows equal twelve 10-second frames; time and coverage remain
# the primary gate while this count rejects a few oversized legacy rows.
MINIMUM_VALID_SAMPLES = 4
MINIMUM_CONTEXT_COVERAGE_PCT = 50.0
HIGH_CONTEXT_COVERAGE_PCT = 80.0

def _age_band(reference: Mapping[str, Any]) -> str | None:
    age = finite_number(reference.get("age_years"))
    if age is not None:
        if age < 18 or age > 120:
            return None
        if age < 30:
            return "18-29"
        if age < 45:
            return "30-44"
        if age < 60:
            return "45-59"
        return "60+"
    stored = str(reference.get("age_group") or "").strip()
    return stored if stored in RESPIRATORY_AGE_LABELS else None


def _age_context(reference: Mapping[str, Any]) -> dict[str, Any]:
    band = _age_band(reference)
    return {
        "available": band is not None,
        "age_band": band,
        "label": RESPIRATORY_AGE_LABELS.get(band, "ยังไม่มีข้อมูลช่วงอายุ"),
        "guidance": RESPIRATORY_AGE_GUIDANCE.get(
            band,
            "เพิ่มข้อมูลอายุเพื่อรับคำแนะนำที่เหมาะกับช่วงวัย",
        ),
        "role": "context_only",
        "threshold_adjustment_applied": False,
        "note": (
            "ใช้ช่วงอายุช่วยอธิบายและจัดกลุ่มแนวโน้มเท่านั้น "
            "ไม่เปลี่ยนเกณฑ์ RR หรือคะแนนจากอายุ"
        ),
    }


def _mode_context(mode: Any) -> str:
    source = dict(mode) if isinstance(mode, Mapping) else {}
    raw = (
        source.get("group")
        or source.get("resolved")
        or source.get("requested")
        or mode
    )
    group = rest_mode_group(raw)
    if group == "sleep":
        return "overnight_sleep"
    if group == "nap_recovery":
        return "nap_or_rest"
    return "unknown"


def _personal_baseline(
    context: Mapping[str, Any],
    current_median: float | None,
) -> dict[str, Any]:
    reference = context.get("respiratory_reference")
    source = dict(reference) if isinstance(reference, Mapping) else {}
    sessions = finite_number(source.get("sessions_used")) or 0.0
    baseline_median = finite_number(source.get("median_rr_brpm"))
    raw_range = source.get("typical_range_rr_brpm")
    typical_range = None
    if isinstance(raw_range, list | tuple) and len(raw_range) == 2:
        low, high = finite_number(raw_range[0]), finite_number(raw_range[1])
        if (
            low is not None
            and high is not None
            and 4.0 <= low <= high <= 60.0
        ):
            typical_range = [round(low, 1), round(high, 1)]
    ready = bool(
        source.get("status") == "active"
        and sessions >= RESTORE_BASELINE_MIN_COMPARISON_SESSIONS
        and baseline_median is not None
        and 4.0 <= baseline_median <= 60.0
        and current_median is not None
        and typical_range is not None
        and source.get("same_mode_only") is True
        and source.get("prior_completed_sessions_only") is True
    )
    if not ready:
        return {
            "available": False,
            "status": "not_ready",
            "sessions_used": int(sessions),
            "minimum_sessions": RESTORE_BASELINE_MIN_COMPARISON_SESSIONS,
            "reason": (
                "กำลังเรียนรู้รูปแบบของคุณ · เมื่อมีข้อมูลการพักรูปแบบนี้จากหลายครั้ง "
                "ZEEP จะเปรียบเทียบแนวโน้มได้ชัดขึ้น"
            ),
            "affects_score": False,
        }
    delta = round(float(current_median) - float(baseline_median), 1)
    if typical_range and current_median < typical_range[0]:
        status, label = "below", "ช้ากว่ารูปแบบที่พบเป็นประจำของคุณ"
    elif typical_range and current_median > typical_range[1]:
        status, label = "above", "เร็วกว่ารูปแบบที่พบเป็นประจำของคุณ"
    else:
        status, label = "within", "ใกล้รูปแบบที่พบเป็นประจำของคุณ"
    return {
        "available": True,
        "status": status,
        "label": label,
        "sessions_used": int(sessions),
        "minimum_sessions": RESTORE_BASELINE_MIN_COMPARISON_SESSIONS,
        "median_rr_brpm": round(float(baseline_median), 1),
        "typical_range_rr_brpm": typical_range,
        "delta_rr_brpm": delta,
        "same_mode_only": True,
        "prior_sessions_only": True,
        "affects_score": False,
    }


def _status(
    median: float | None,
    regularity_factor: float | None,
    valid_seconds: float,
    coverage_pct: float,
    valid_samples: int,
    longest_valid_run_seconds: float,
) -> dict[str, str]:
    if (
        median is None
        or valid_seconds < MINIMUM_VALID_SECONDS
        or valid_samples < MINIMUM_VALID_SAMPLES
        or longest_valid_run_seconds < 30.0
        or coverage_pct < MINIMUM_CONTEXT_COVERAGE_PCT
    ):
        return {
            "key": "insufficient",
            "label": RESPIRATORY_STATUS_LABELS["insufficient"],
        }
    if (
        valid_seconds >= RECHECK_MINIMUM_VALID_SECONDS
        and coverage_pct >= 70.0
        and (
            median <= ADULT_RECHECK_RANGE_BRPM[0]
            or median >= ADULT_RECHECK_RANGE_BRPM[1]
        )
    ):
        return {
            "key": "needs_recheck",
            "label": RESPIRATORY_STATUS_LABELS["needs_recheck"],
        }
    within_context = ADULT_CONTEXT_RANGE_BRPM[0] <= median <= (
        ADULT_CONTEXT_RANGE_BRPM[1]
    )
    if within_context and coverage_pct >= 70.0 and (
        regularity_factor is not None and regularity_factor >= 0.5
    ):
        return {
            "key": "supportive",
            "label": RESPIRATORY_STATUS_LABELS["supportive"],
        }
    return {
        "key": "observe",
        "label": RESPIRATORY_STATUS_LABELS["observe"],
    }


def _recommendation(status_key: str) -> dict[str, Any]:
    return {
        "primary": user_respiratory_recommendation(status_key),
        "medical_advice": False,
        "automatic_actuation": False,
    }


def _reason_codes(
    *,
    row_count: int,
    occupied_seconds: float,
    valid_seconds: float,
    coverage_pct: float,
    status_key: str,
    legacy_rr_without_provenance: bool,
) -> list[str]:
    reasons: list[str] = []
    if row_count == 0:
        reasons.append("no_sensor_samples")
    if occupied_seconds <= 0:
        reasons.append("no_confirmed_occupancy")
    if legacy_rr_without_provenance:
        reasons.append("historical_provenance_unavailable")
    if 0 < valid_seconds < MINIMUM_VALID_SECONDS:
        reasons.append("insufficient_valid_duration")
    if occupied_seconds > 0 and coverage_pct < MINIMUM_CONTEXT_COVERAGE_PCT:
        reasons.append("low_valid_coverage")
    if status_key == "needs_recheck":
        reasons.append("needs_standard_recheck")
    return reasons


def _confidence(available: bool, coverage_pct: float) -> dict[str, Any]:
    if not available:
        level = "low"
    elif coverage_pct >= HIGH_CONTEXT_COVERAGE_PCT:
        level = "high"
    elif coverage_pct >= MINIMUM_CONTEXT_COVERAGE_PCT:
        level = "medium"
    else:
        level = "low"
    labels = {
        "high": "ความชัดเจนของข้อมูลดี",
        "medium": "ความชัดเจนของข้อมูลเพียงพอ",
        "low": "กำลังสะสมข้อมูลเพิ่ม",
    }
    return {
        "level": level,
        "label": labels[level],
        "direct_measurements_only": True,
        "carried_state_excluded": True,
    }


def _fixed_contract() -> dict[str, Any]:
    return {
        "reference_context": {
            "adult_orientation_range_brpm": list(ADULT_CONTEXT_RANGE_BRPM),
            "recheck_range_brpm": list(ADULT_RECHECK_RANGE_BRPM),
            "ranges_are_diagnostic": False,
            "age_specific_cutoff_applied": False,
            "regularity_is_internal_wellness_policy": True,
        },
        "measurement_requirements": {
            "lung_function": "Spirometry/PFT เช่น FEV1, FVC และ FEV1/FVC",
            "oxygenation": "SpO2 จากอุปกรณ์ที่ผ่านการตรวจสอบ",
            "whole_body_fitness": "กิจกรรมระหว่างวันและการทดสอบสมรรถภาพเพิ่มเติม",
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
    observations: Mapping[str, Any],
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


def build_respiratory_wellness(
    samples: Iterable[Mapping[str, Any]] | None,
    *,
    sample_interval_s: float,
    health_reference: Mapping[str, Any] | None = None,
    personal_context: Mapping[str, Any] | None = None,
    rest_mode: Any = None,
) -> dict[str, Any]:
    """Build an age-aware respiratory pattern summary from direct BCG RR."""
    rows = [dict(row) for row in samples or [] if isinstance(row, Mapping)]
    metrics = collect_metrics(rows, sample_interval(sample_interval_s))
    observations = build_observations(
        metrics,
        minimum_valid_samples=MINIMUM_VALID_SAMPLES,
        minimum_valid_seconds=MINIMUM_VALID_SECONDS,
        minimum_context_coverage_pct=MINIMUM_CONTEXT_COVERAGE_PCT,
    )
    median = weighted_quantile(metrics["measured"], 0.5)
    occupied_seconds = metrics["occupied_seconds"]
    coverage_pct = (
        100.0 * metrics["valid_seconds"] / occupied_seconds
        if occupied_seconds
        else 0.0
    )
    age = _age_context(dict(health_reference or {}))
    baseline = _personal_baseline(dict(personal_context or {}), median)
    context = _mode_context(rest_mode)
    status = _status(
        median,
        observations["regularity_factor"],
        metrics["valid_seconds"],
        coverage_pct,
        observations["valid_samples"],
        observations["longest_valid_run_seconds"],
    )
    available = status["key"] != "insufficient"
    reason_codes = _reason_codes(
        row_count=len(rows),
        occupied_seconds=metrics["occupied_seconds"],
        valid_seconds=metrics["valid_seconds"],
        coverage_pct=coverage_pct,
        status_key=status["key"],
        legacy_rr_without_provenance=metrics[
            "legacy_rr_without_provenance"
        ],
    )
    vital_summary = _vital_summary(status["key"], observations)
    result = {
        "version": RESPIRATORY_WELLNESS_VERSION,
        "available": available,
        "label": "ชีพจรและการหายใจระหว่างพัก",
        "intended_use": "age_contextual_wellness_pattern_not_lung_function",
        "context": context,
        "status": status,
        "reason_codes": reason_codes,
        "interpretation": vital_summary["summary"],
        "observations": observations,
        "vital_summary": vital_summary,
        "confidence": _confidence(available, coverage_pct),
        "age_context": age,
        "personal_baseline": baseline,
        "recommendation": {
            **_recommendation(status["key"]),
            "primary": vital_summary["recommendation"],
        },
    }
    result.update(_fixed_contract())
    return result
