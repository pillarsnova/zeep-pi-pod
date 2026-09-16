"""Age-aware, non-diagnostic interpretation of BCG breathing patterns.

This Wellness summary never changes a State, Score, or hardware command.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from presentation.language import (
    RESPIRATORY_AGE_GUIDANCE,
    RESPIRATORY_AGE_LABELS,
    RESPIRATORY_STATUS_LABELS,
    user_paired_vital_status,
    user_respiratory_interpretation,
    user_respiratory_recommendation,
)
from sessions.respiratory_evidence import (
    finite_number,
    sample_interval,
    weighted_quantile,
)
from sessions.respiratory_metrics import (
    build_observations,
    collect_metrics,
)
from sessions.respiratory_policy import (
    RESPIRATORY_ADULT_CONTEXT_RANGE_BRPM,
    RESPIRATORY_ADULT_RECHECK_RANGE_BRPM,
    RESPIRATORY_BASELINE_MIN_COMPARISON_SESSIONS,
    RESPIRATORY_HIGH_CONTEXT_COVERAGE_PCT,
    RESPIRATORY_MINIMUM_CONTEXT_COVERAGE_PCT,
    RESPIRATORY_MINIMUM_VALID_SAMPLES,
    RESPIRATORY_MINIMUM_VALID_SECONDS,
    RESPIRATORY_RECHECK_MINIMUM_VALID_SECONDS,
)
from sleep_system_policy import (
    RESPIRATORY_WELLNESS_VERSION,
    rest_mode_group,
)

ADULT_CONTEXT_RANGE_BRPM = RESPIRATORY_ADULT_CONTEXT_RANGE_BRPM
ADULT_RECHECK_RANGE_BRPM = RESPIRATORY_ADULT_RECHECK_RANGE_BRPM
MINIMUM_VALID_SECONDS = RESPIRATORY_MINIMUM_VALID_SECONDS
RECHECK_MINIMUM_VALID_SECONDS = RESPIRATORY_RECHECK_MINIMUM_VALID_SECONDS
# Four 30-second rows equal twelve 10-second frames; time and coverage remain
# the primary gate while this count rejects a few oversized legacy rows.
MINIMUM_VALID_SAMPLES = RESPIRATORY_MINIMUM_VALID_SAMPLES
MINIMUM_CONTEXT_COVERAGE_PCT = RESPIRATORY_MINIMUM_CONTEXT_COVERAGE_PCT
HIGH_CONTEXT_COVERAGE_PCT = RESPIRATORY_HIGH_CONTEXT_COVERAGE_PCT


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
            "ไม่เปลี่ยนเกณฑ์ชีพจร การหายใจ หรือคะแนนจากอายุ"
        ),
    }


def _mode_context(mode: Any) -> str:
    source = dict(mode) if isinstance(mode, Mapping) else {}
    raw = (
        source.get("group") or source.get("resolved") or source.get("requested") or mode
    )
    group = rest_mode_group(raw)
    if group == "sleep":
        return "overnight_sleep"
    if group == "nap_recovery":
        return "nap_or_rest"
    return "unknown"


def _reference_range(
    raw: Any,
    *,
    minimum: float,
    maximum: float,
) -> list[float] | None:
    if not isinstance(raw, list | tuple) or len(raw) != 2:
        return None
    low, high = finite_number(raw[0]), finite_number(raw[1])
    if low is None or high is None or not minimum <= low <= high <= maximum:
        return None
    return [round(low, 1), round(high, 1)]


def _unavailable_personal_baseline(
    *,
    sessions: float,
    reference_ready: bool,
    baseline_hr: float | None,
    baseline_rr: float | None,
    hr_range: list[float] | None,
    rr_range: list[float] | None,
) -> dict[str, Any]:
    result = {
        "available": False,
        "status": "not_ready",
        "sessions_used": int(sessions),
        "minimum_sessions": RESPIRATORY_BASELINE_MIN_COMPARISON_SESSIONS,
        "reason": (
            "ข้อมูลอ้างอิงส่วนบุคคลพร้อมแล้ว "
            "แต่ข้อมูลครั้งนี้ยังไม่เพียงพอสำหรับเปรียบเทียบ"
            if reference_ready
            else "กำลังเก็บข้อมูลชีพจรและการหายใจจากการพักรูปแบบเดียวกัน "
            "เพื่อสร้างข้อมูลอ้างอิงส่วนบุคคล"
        ),
        "reference_ready": reference_ready,
        "requires_paired_hr_rr": True,
        "affects_score": False,
    }
    if reference_ready:
        result.update({
            "median_hr_bpm": round(float(baseline_hr), 1),
            "typical_range_hr_bpm": hr_range,
            "median_rr_brpm": round(float(baseline_rr), 1),
            "typical_range_rr_brpm": rr_range,
            "same_mode_only": True,
            "prior_sessions_only": True,
        })
    return result


def _personal_baseline(
    context: Mapping[str, Any],
    current_hr: float | None,
    current_rr: float | None,
) -> dict[str, Any]:
    reference = context.get("respiratory_reference")
    source = dict(reference) if isinstance(reference, Mapping) else {}
    sessions = finite_number(source.get("sessions_used")) or 0.0
    baseline_hr = finite_number(source.get("median_hr_bpm"))
    baseline_rr = finite_number(source.get("median_rr_brpm"))
    hr_range = _reference_range(
        source.get("typical_range_hr_bpm"),
        minimum=30.0,
        maximum=220.0,
    )
    rr_range = _reference_range(
        source.get("typical_range_rr_brpm"),
        minimum=4.0,
        maximum=60.0,
    )
    reference_ready = bool(
        source.get("status") == "active"
        and sessions >= RESPIRATORY_BASELINE_MIN_COMPARISON_SESSIONS
        and baseline_hr is not None
        and 30.0 <= baseline_hr <= 220.0
        and baseline_rr is not None
        and 4.0 <= baseline_rr <= 60.0
        and hr_range is not None
        and rr_range is not None
        and source.get("requires_paired_hr_rr") is True
        and source.get("same_mode_only") is True
        and source.get("prior_completed_sessions_only") is True
    )
    ready = bool(
        reference_ready
        and current_hr is not None
        and 30.0 <= current_hr <= 220.0
        and current_rr is not None
        and 4.0 <= current_rr <= 60.0
    )
    if not ready:
        return _unavailable_personal_baseline(
            sessions=sessions,
            reference_ready=reference_ready,
            baseline_hr=baseline_hr,
            baseline_rr=baseline_rr,
            hr_range=hr_range,
            rr_range=rr_range,
        )
    delta_hr = round(float(current_hr) - float(baseline_hr), 1)
    delta_rr = round(float(current_rr) - float(baseline_rr), 1)
    if current_rr < rr_range[0]:
        status, label = "below", "การหายใจช้ากว่ารูปแบบที่พบเป็นประจำของคุณ"
    elif current_rr > rr_range[1]:
        status, label = "above", "การหายใจเร็วกว่ารูปแบบที่พบเป็นประจำของคุณ"
    elif current_hr < hr_range[0]:
        status, label = "below", "ชีพจรต่ำกว่ารูปแบบที่พบเป็นประจำของคุณ"
    elif current_hr > hr_range[1]:
        status, label = "above", "ชีพจรสูงกว่ารูปแบบที่พบเป็นประจำของคุณ"
    else:
        status, label = "within", "ใกล้รูปแบบชีพจรและการหายใจของคุณ"
    return {
        "available": True,
        "status": status,
        "label": label,
        "sessions_used": int(sessions),
        "minimum_sessions": RESPIRATORY_BASELINE_MIN_COMPARISON_SESSIONS,
        "reference_ready": True,
        "median_hr_bpm": round(float(baseline_hr), 1),
        "typical_range_hr_bpm": hr_range,
        "delta_hr_bpm": delta_hr,
        "median_rr_brpm": round(float(baseline_rr), 1),
        "typical_range_rr_brpm": rr_range,
        "delta_rr_brpm": delta_rr,
        "same_mode_only": True,
        "prior_sessions_only": True,
        "requires_paired_hr_rr": True,
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
    within_context = (
        ADULT_CONTEXT_RANGE_BRPM[0] <= median <= (ADULT_CONTEXT_RANGE_BRPM[1])
    )
    if (
        within_context
        and coverage_pct >= 70.0
        and (regularity_factor is not None and regularity_factor >= 0.5)
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
    observations: Mapping[str, Any],
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


def build_respiratory_wellness(
    samples: Iterable[Mapping[str, Any]] | None,
    *,
    sample_interval_s: float,
    health_reference: Mapping[str, Any] | None = None,
    personal_context: Mapping[str, Any] | None = None,
    rest_mode: Any = None,
) -> dict[str, Any]:
    """Build an age-aware resting summary from paired direct BCG HR/RR."""
    rows = [dict(row) for row in samples or [] if isinstance(row, Mapping)]
    metrics = collect_metrics(rows, sample_interval(sample_interval_s))
    observations = build_observations(
        metrics,
        minimum_valid_samples=MINIMUM_VALID_SAMPLES,
        minimum_valid_seconds=MINIMUM_VALID_SECONDS,
        minimum_context_coverage_pct=MINIMUM_CONTEXT_COVERAGE_PCT,
    )
    median_rr = weighted_quantile(metrics["measured_paired_rr"], 0.5)
    occupied_seconds = metrics["occupied_seconds"]
    coverage_pct = (
        100.0 * metrics["paired_hr_rr_seconds"] / occupied_seconds
        if occupied_seconds
        else 0.0
    )
    age = _age_context(dict(health_reference or {}))
    baseline = _personal_baseline(
        dict(personal_context or {}),
        observations["median_hr_bpm"],
        observations["median_paired_rr_brpm"],
    )
    context = _mode_context(rest_mode)
    status = _status(
        median_rr,
        observations["regularity_factor"],
        metrics["paired_hr_rr_seconds"],
        coverage_pct,
        observations["paired_hr_rr_samples"],
        observations["longest_paired_hr_rr_run_seconds"],
    )
    available = status["key"] != "insufficient"
    reason_codes = _reason_codes(
        row_count=len(rows),
        occupied_seconds=metrics["occupied_seconds"],
        valid_seconds=metrics["paired_hr_rr_seconds"],
        coverage_pct=coverage_pct,
        status_key=status["key"],
        legacy_rr_without_provenance=metrics["legacy_rr_without_provenance"],
    )
    vital_summary = _vital_summary(status["key"], observations)
    result = {
        "version": RESPIRATORY_WELLNESS_VERSION,
        "available": available,
        "label": "ชีพจรและการหายใจขณะพัก",
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
