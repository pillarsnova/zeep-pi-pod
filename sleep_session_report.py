"""Explainable post-session report for the ZEEP Pod.

The report intentionally keeps three concerns separate:

1. Sleep results come from the versioned BCG sleep-state estimator.
2. SPH0645 and Bed Status may corroborate a disturbance.
3. Pod environment values explain possible disturbance and data context only;
   they never determine Wake/N1/N2/N3/REM.

All thresholds below are ZEEP operating targets already shown on the
dashboard. They are not medical diagnostic limits.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

from sleep_signal_features import (
    HR_SANITY_RANGE_BPM,
    RR_SANITY_RANGE_PER_MIN,
    bed_exit_event_summary,
    filter_vital_values,
)
from sleep_system_policy import (
    ENVIRONMENT_ACCEPTABLE_MIN_LEVEL,
    ENVIRONMENT_CONTEXT_CRITERIA,
    ENVIRONMENT_CONTEXT_POLICY_VERSION,
    ENVIRONMENT_LEVELS,
    OVERNIGHT_ARCHITECTURE_MAX_POINTS,
    OVERNIGHT_N2_FULL_CREDIT_PCT,
    OVERNIGHT_N3_FULL_CREDIT_FROM_PCT,
    OVERNIGHT_N3_ZERO_BELOW_PCT,
    OVERNIGHT_REM_FULL_CREDIT_PCT,
    REST_MODE_LEGACY_ALIASES,
    REST_MODE_PROTOCOLS,
    REST_SESSION_GROUPS,
    REST_MODE_DURATION_TARGETS_S,
    SESSION_REPORT_VERSION,
    SLEEP_QUALITY_COMPONENT_MAX_POINTS,
    SLEEP_QUALITY_VERSION,
    environment_criterion,
    environment_level_for_value,
    environment_policy_snapshot,
)

STAGE_ORDER = ("wake", "n1", "n2", "n3", "rem")
SLEEP_STAGES = {"n1", "n2", "n3", "rem"}
REST_MODE_LABELS = {
    "auto": "ZEEP Smart Mode · วิเคราะห์ตามการพักจริง",
    "sleep": REST_SESSION_GROUPS["sleep"]["label"],
    "nap_recovery": REST_SESSION_GROUPS["nap_recovery"]["label"],
    "general_rest": "Nap & Refresh · พักขณะตื่น",
    "short_nap": "Nap & Refresh · พบการหลับ",
    "cycle_nap": "Nap & Refresh · พักต่อเนื่อง",
    "shift_rest": "พักจากการเข้าเวร",
    "jet_lag": "พักเพื่อปรับ Jet lag",
    "overnight": "นอนค้างคืน",
}
REST_MODE_ALIASES = {
    **REST_MODE_LEGACY_ALIASES,
    "nap": "nap_recovery",
    "nap_rest": "nap_recovery",
    "power_nap": "short_nap",
    "shift": "shift_rest",
    "jetlag": "jet_lag",
    "night": "overnight",
}

_SLEEP_MODE_GROUPS = {
    "sleep": "sleep",
    "short_nap": "nap_recovery",
    "cycle_nap": "nap_recovery",
    "shift_rest": "nap_recovery",
    "jet_lag": "nap_recovery",
    "overnight": "sleep",
}
_AWAKE_REST_MODES = {
    "general_rest", "nap_recovery",
}

def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _percent(numerator: float, denominator: float) -> int:
    if denominator <= 0:
        return 0
    return max(0, min(100, round(numerator * 100.0 / denominator)))


def _values(samples: Iterable[Dict[str, Any]], key: str) -> list[float]:
    result = []
    for sample in samples:
        value = _number(sample.get(key))
        if value is not None:
            result.append(value)
    return result


def _normalise_stage_counts(raw: Optional[Dict[str, Any]]) -> Dict[str, float]:
    counts = {stage: 0.0 for stage in STAGE_ORDER}
    aliases = {"nrem_light": "n2", "nrem_deep": "n3"}
    for name, value in (raw or {}).items():
        stage = aliases.get(str(name), str(name))
        amount = _number(value)
        if stage in counts and amount is not None and amount > 0:
            counts[stage] += amount
    return counts


def _stage_percentages(counts: Dict[str, float]) -> Dict[str, int]:
    """Round five percentages while preserving an exact total of 100."""
    total = sum(counts.values())
    if total <= 0:
        return {stage: 0 for stage in STAGE_ORDER}
    raw = {stage: counts[stage] * 100.0 / total for stage in STAGE_ORDER}
    rounded = {stage: int(raw[stage]) for stage in STAGE_ORDER}
    remainder = 100 - sum(rounded.values())
    order = sorted(STAGE_ORDER, key=lambda stage: raw[stage] - rounded[stage], reverse=True)
    for stage in order[:remainder]:
        rounded[stage] += 1
    return rounded


def normalise_rest_mode(value: Any) -> str:
    """Return a supported rest intent or raise for an invalid API value."""
    mode = str(value or "auto").strip().lower()
    mode = REST_MODE_ALIASES.get(mode, mode)
    if mode not in REST_MODE_LABELS:
        raise ValueError(f"unsupported rest mode: {value}")
    return mode


def _resolve_rest_mode(
    requested: Any,
    actual_scored_s: float,
    estimated_sleep_s: Optional[float] = None,
) -> Dict[str, Any]:
    """Resolve the user goal separately from the observed Session character.

    Sleep sub-modes are selected from actual sleep duration.  A Session with no
    detected sleep remains a valid awake-rest experience instead of being
    forced into an overnight sleep score.  This changes reporting only; it
    never changes the estimator's W/N1/N2/N3/REM decisions.
    """
    requested_mode = normalise_rest_mode(requested)
    sleep_s = max(0.0, _number(estimated_sleep_s) or 0.0)
    sleep_detected = sleep_s > 0
    if requested_mode == "sleep" and sleep_detected:
        resolved = "overnight"
        reason = "ผู้ใช้เลือกการนอนหลัก; ระยะเวลาที่บันทึกใช้ตรวจขั้นต่ำ 5 ชั่วโมงแยกต่างหาก"
    elif requested_mode == "nap_recovery" and sleep_detected:
        resolved = "short_nap"
        reason = "ผู้ใช้เลือก Nap & Refresh; การหลับเป็นผลที่อาจเกิดขึ้น ไม่ใช่ข้อบังคับของโหมด"
    elif requested_mode == "sleep":
        resolved = "overnight"
        reason = "ผู้ใช้เลือกการนอน แต่ยังไม่พบ Sleep State"
    elif requested_mode != "auto":
        resolved = requested_mode
        reason = "ผู้ใช้เลือกวัตถุประสงค์ของการพักก่อนเริ่ม Session"
    elif not sleep_detected:
        resolved = "general_rest"
        reason = "ไม่พบ Sleep State จึงประเมินเป็นการพักขณะตื่น"
    elif sleep_s <= 60 * 60:
        resolved = "short_nap"
        reason = "เวลาหลับที่ตรวจพบไม่เกิน 60 นาที จัดเป็นงีบสั้น"
    elif sleep_s < 5 * 3600:
        resolved = "cycle_nap"
        reason = "เวลาหลับที่ตรวจพบมากกว่า 60 นาที แต่ยังไม่ถึงขั้นต่ำการนอนหลัก 5 ชั่วโมง"
    else:
        resolved = "overnight"
        reason = "เวลาหลับที่ตรวจพบตั้งแต่ 5 ชั่วโมง จัดเป็นการนอนหลัก"
    if requested_mode in REST_SESSION_GROUPS:
        group = requested_mode
    elif requested_mode == "auto":
        # ``auto`` is retained only as a legacy input.  Product reporting has
        # exactly two public outcomes: long sleep or daytime recovery.
        group = "sleep" if resolved == "overnight" else "nap_recovery"
    else:
        group = _SLEEP_MODE_GROUPS.get(resolved, "nap_recovery")
    group_policy = REST_SESSION_GROUPS.get(group, {
        "label": "พักผ่อนทั่วไป", "score_title": "คะแนนการพัก",
        "score_scope": "ค่าประเมินการพักจาก Sensor",
        "description": "พักใน ZEEP ตามข้อมูลที่บันทึกได้",
    })
    return {
        "requested": requested_mode,
        "resolved": resolved,
        "group": group,
        "label": group_policy["label"],
        "resolved_label": REST_MODE_LABELS[resolved],
        "score_title": group_policy["score_title"],
        "score_scope": group_policy.get("score_scope"),
        "description": group_policy["description"],
        "sleep_required": bool(group_policy.get("sleep_required", False)),
        "sleep_detected": sleep_detected,
        "reason": reason,
        "protocol": dict(REST_MODE_PROTOCOLS[group]) if group in REST_MODE_PROTOCOLS else None,
    }


def _protocol_status(mode: Dict[str, Any], observed_s: float) -> Dict[str, Any]:
    """Describe timing compliance without discarding an interrupted Session."""
    group = str(mode.get("group") or "")
    protocol = REST_MODE_PROTOCOLS.get(group)
    if not protocol:
        return {
            "available": False,
            "canonical_mode": group or None,
            "observed_seconds": round(max(0.0, observed_s), 1),
        }
    observed = max(0.0, observed_s)
    minimum = _number(protocol.get("minimum_seconds"))
    maximum = _number(protocol.get("maximum_seconds"))
    recommended = protocol.get("recommended_range_seconds") or []
    recommended_low = _number(recommended[0]) if len(recommended) > 0 else None
    recommended_high = _number(recommended[1]) if len(recommended) > 1 else None
    below_minimum = minimum is not None and observed < minimum
    above_maximum = maximum is not None and observed > maximum
    in_recommended = (
        recommended_low is not None
        and recommended_high is not None
        and recommended_low <= observed <= recommended_high
    )
    if below_minimum:
        status = "too_short"
    elif above_maximum:
        status = "over_limit"
    elif in_recommended:
        status = "recommended"
    else:
        status = "allowed"
    return {
        "available": True,
        "canonical_mode": group,
        "observed_seconds": round(observed, 1),
        "minimum_seconds": minimum,
        "maximum_seconds": maximum,
        "recommended_range_seconds": list(recommended),
        "within_operational_window": not below_minimum and not above_maximum,
        "within_recommended_range": in_recommended,
        "status": status,
    }


def _range_fit(value: float, low: float, high: float,
               soft_low: float, soft_high: float) -> float:
    """Broad, non-clinical fit used only for the ZEEP Wellness balance score."""
    if low <= value <= high:
        return 1.0
    if value < low:
        return max(0.0, min(1.0, (value - soft_low) / max(0.0001, low - soft_low)))
    return max(0.0, min(1.0, (soft_high - value) / max(0.0001, soft_high - high)))


def _average(values: list[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


def _regularity(values: list[float], *, soft_cv: float) -> Optional[float]:
    """Return a transparent stability factor; this is not beat-to-beat HRV."""
    if len(values) < 3:
        return None
    mean = _average(values) or 0.0
    if mean <= 0:
        return None
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    cv = variance ** 0.5 / mean
    return max(0.0, min(1.0, 1.0 - cv / max(0.0001, soft_cv)))


def _score_confidence(
    coverage_ratio: float,
    paired_vital_ratio: float,
) -> Dict[str, Any]:
    """Describe score evidence completeness without suppressing the score.

    Session coverage remains visible to Admin QA and already contributes a
    bounded score component.  It must not become a second, hidden veto after
    minimum paired HR/RR evidence has passed.
    """
    evidence_floor = min(coverage_ratio, paired_vital_ratio)
    if evidence_floor >= 0.80:
        level, label = "high", "หลักฐานสูง"
    elif evidence_floor >= 0.50:
        level, label = "medium", "หลักฐานปานกลาง"
    else:
        level, label = "low", "หลักฐานจำกัด"
    return {
        "level": level,
        "label": label,
        "session_coverage_pct": round(coverage_ratio * 100.0, 1),
        "paired_hr_rr_coverage_pct": round(
            paired_vital_ratio * 100.0, 1
        ),
        "coverage_is_admin_qa_context": True,
        "coverage_can_hide_score": False,
    }


def _settling(values: list[float], *, scale: float) -> Optional[float]:
    """Compare early/late thirds; stable is neutral, a gentle fall is positive."""
    if len(values) < 6:
        return None
    window = max(2, len(values) // 3)
    first = _average(values[:window]) or 0.0
    last = _average(values[-window:]) or 0.0
    return max(0.0, min(1.0, 0.5 + (first - last) / max(0.1, scale)))


def _rest_goal_seconds(group: str) -> float:
    """Return the full-credit rest goal for a Recovery Score.

    The product exposes one Nap & Refresh goal: 30 minutes.  Legacy recovery
    aliases use the same target so historical reports remain comparable.
    """
    protocol = (
        REST_MODE_PROTOCOLS.get(group)
        or REST_MODE_PROTOCOLS["nap_recovery"]
    )
    target = _number(protocol.get("full_credit_target_seconds")) or 30 * 60
    return max(1.0, target)


def _eligible_rest_seconds(
    rows: list[Dict[str, Any]], interval: float, duration: float,
) -> float:
    """Count recorded time with evidence that the user remained in ZEEP.

    Nap & Refresh may be quiet wakefulness, so sleep stages are deliberately
    not required.  Moving, weak breathing and snoring still mean the user is
    on the bed.  For legacy rows without Bed Status, valid paired HR/RR is the
    occupancy fallback.  Confirmed ``Get out of bed`` and unknown rows do not
    earn goal-duration time.
    """
    occupied_labels = {"on bed", "moving", "weak breathing", "snoring"}
    eligible_rows = 0
    for row in rows:
        bed = str(row.get("bed") or row.get("bed_status") or "").strip().casefold()
        if bed in occupied_labels:
            eligible_rows += 1
            continue
        if bed:
            continue
        hr_ok = bool(filter_vital_values([row.get("hr")], HR_SANITY_RANGE_BPM))
        rr_ok = bool(filter_vital_values([row.get("rr")], RR_SANITY_RANGE_PER_MIN))
        if hr_ok and rr_ok:
            eligible_rows += 1
    return min(max(0.0, duration), eligible_rows * interval)


def _build_awake_rest_quality(
    duration: float,
    mode: Dict[str, Any],
    counts: Dict[str, float],
    rows: list[Dict[str, Any]],
    interval: float,
) -> Dict[str, Any]:
    """Score an awake wellness Session without inventing sleep architecture.

    The score reflects goal duration, coarse HR/RR settling, bed stillness,
    environment support, and coverage.  Air Sensor values remain explanatory
    context and never feed the Sleep State estimator.
    """
    group = mode.get("group") or mode.get("resolved") or "general_rest"
    policy = REST_SESSION_GROUPS.get(group, {
        "label": "พักผ่อนทั่วไป", "score_title": "คะแนนการพัก",
        "score_scope": "ค่าประเมินการพักจาก Sensor",
        "description": "พักใน ZEEP ตามข้อมูลที่บันทึกได้",
    })
    # Legacy callers may only have aggregate Wake counts.  Without the raw
    # Sensor rows there is no defensible evidence for an awake-rest score, so
    # keep the historical zero instead of awarding duration-only points.
    no_sensor_evidence = not rows
    duration_goal_s = _rest_goal_seconds(group)
    eligible_rest_s = _eligible_rest_seconds(rows, interval, duration)
    duration_factor = min(1.0, eligible_rest_s / duration_goal_s)
    duration_points = 0.0 if no_sensor_evidence else round(20.0 * duration_factor, 1)

    hr = [value for value in _values(rows, "hr") if 30 <= value <= 220]
    rr = [value for value in _values(rows, "rr") if 4 <= value <= 60]
    hr_regularity = _regularity(hr, soft_cv=0.12)
    rr_regularity = _regularity(rr, soft_cv=0.18)
    regularity_parts = [
        value for value in (hr_regularity, rr_regularity)
        if value is not None
    ]
    settling_parts = [
        value for value in (
            _settling(hr, scale=10.0),
            _settling(rr, scale=5.0),
        ) if value is not None
    ]
    regularity = _average(regularity_parts)
    settling = _average(settling_parts)
    if regularity is None:
        physiology_factor = 0.0
    else:
        # Nap & Refresh accepts quiet wakefulness. Stable HR/RR matters more
        # than forcing heart rate to fall, which meditation does not guarantee.
        physiology_factor = 0.85 * regularity + 0.15 * (settling if settling is not None else 0.5)
    physiology_points = round(30.0 * physiology_factor, 1)

    bed_labels = [str(row.get("bed") or "") for row in rows if row.get("bed")]
    moving = sum(label == "Moving" for label in bed_labels)
    exit_summary = bed_exit_event_summary(bed_labels)
    exits = exit_summary["event_count"]
    if bed_labels:
        movement_ratio = moving / len(bed_labels)
        stillness_factor = max(0.0, 1.0 - 1.5 * movement_ratio - 0.15 * exits)
    else:
        movement_ratio = None
        stillness_factor = 0.0
    stillness_points = round(20.0 * stillness_factor, 1)

    # Broad ZEEP comfort targets. These support the experience and explain a
    # low score; they do not label or re-label any Sleep Stage.
    environment_factors: Dict[str, float] = {}
    environment_bands = {
        "temp": (18.0, 27.0, 14.0, 32.0),
        "hum": (40.0, 60.0, 25.0, 80.0),
        "co2": (350.0, 1000.0, 250.0, 1800.0),
        "dba": (0.0, 40.0, 0.0, 65.0),
        "lux": (0.0, 10.0, 0.0, 60.0),
    }
    environment_averages: Dict[str, float] = {}
    for key, band in environment_bands.items():
        values = _values(rows, key)
        if values:
            average = _average(values) or 0.0
            environment_averages[key] = round(average, 1)
            environment_factors[key] = _range_fit(average, *band)
    environment_factor = _average(list(environment_factors.values())) or 0.0
    environment_points = round(20.0 * environment_factor, 1)

    recorded_s = len(rows) * interval
    state_s = sum(counts.values()) * interval
    coverage_ratio = max(0.0, min(1.0, max(recorded_s, state_s) / max(1.0, duration)))
    source_vital_samples = sum(
        max(1, int(_number(row.get("_source_rows")) or 1)) for row in rows
    )
    paired_vital_samples = sum(
        max(0, int(_number(row.get("_paired_hr_rr_rows")) or 0))
        if "_paired_hr_rr_rows" in row else int(
            isinstance(row.get("hr"), (int, float))
            and 30 <= float(row["hr"]) <= 220
            and isinstance(row.get("rr"), (int, float))
            and 4 <= float(row["rr"]) <= 60
        )
        for row in rows
    )
    paired_vital_ratio = (
        paired_vital_samples / source_vital_samples
        if source_vital_samples else 0.0
    )
    coverage_points = 0.0 if no_sensor_evidence else round(10.0 * coverage_ratio, 1)
    component_points = {
        "goal_duration": duration_points,
        "physiological_response": physiology_points,
        "body_stillness": stillness_points,
        "environment_support": environment_points,
        "data_coverage": coverage_points,
    }
    component_max = {
        "goal_duration": 20.0,
        "physiological_response": 30.0,
        "body_stillness": 20.0,
        "environment_support": 20.0,
        "data_coverage": 10.0,
    }
    earned = round(sum(component_points.values()), 1)
    score = max(0, min(100, int(round(earned))))
    if score >= 85:
        level, level_key = "ดีมาก", "very_good"
    elif score >= 70:
        level, level_key = "ดี", "good"
    elif score >= 55:
        level, level_key = "ปานกลาง", "fair"
    else:
        level, level_key = "ควรปรับปรุง", "low"

    lowest = min(component_points, key=lambda key: (
        component_points[key] / max(1.0, component_max[key])))
    insights = {
        "goal_duration": "ระยะเวลาพักยังไม่เหมาะกับเป้าหมายที่เลือก",
        "physiological_response": "ข้อมูลชีพจรหรือการหายใจยังไม่แสดงความนิ่งเพียงพอ",
        "body_stillness": "พบการเคลื่อนไหวหรือลุกจากเตียงระหว่างพัก",
        "environment_support": "สภาพแวดล้อมบางส่วนยังไม่เอื้อต่อเป้าหมายการพัก",
        "data_coverage": "ข้อมูล Sensor ยังครอบคลุม Session ไม่เพียงพอ",
    }
    sleep_s = sum(counts[stage] for stage in SLEEP_STAGES) * interval
    score_available = bool(
        not no_sensor_evidence
        and paired_vital_samples >= 6
        and hr_regularity is not None
        and rr_regularity is not None
    )
    score_confidence = _score_confidence(
        coverage_ratio, paired_vital_ratio
    )
    return {
        "available": score_available,
        "score": score if score_available else None,
        "engineering_shadow_score": score,
        "score_releasable": score_available,
        "score_confidence": score_confidence,
        "release_requirements": {
            "minimum_coverage_pct_for_high_confidence": 80,
            "session_coverage_blocks_score": False,
            "minimum_paired_hr_rr_coverage_pct_for_high_confidence": 80,
            "paired_hr_rr_coverage_blocks_score": False,
            "minimum_paired_samples": 6,
            "paired_hr_rr_required": True,
            "passed": score_available,
        },
        "reason": (
            None if score_available else
            "ข้อมูล HR/RR ที่จับคู่กันยังไม่พอสำหรับคำนวณ Recovery Score"
        ),
        "score_title": policy["score_title"],
        "score_scope": policy.get("score_scope"),
        "validation_status": "preliminary_wellness_estimate",
        "clinical_validated": False,
        "quality_type": "rest_goal",
        "session_character": "hybrid" if sleep_s > 0 else "awake_rest",
        "sleep_detected": sleep_s > 0,
        "level": level,
        "level_key": level_key,
        "insight": insights[lowest] if score < 85 else f"{policy['label']}โดยรวมสอดคล้องกับเป้าหมายที่เลือก",
        "estimated_sleep_s": round(sleep_s, 1),
        "actual_scored_s": round(sum(counts.values()) * interval, 1),
        "rest_mode": {
            **mode,
            "protocol_status": _protocol_status(mode, duration),
        },
        "duration_target": {
            "seconds": round(duration_goal_s, 1),
            "target_minutes": round(duration_goal_s / 60.0, 1),
            "recommended_range_minutes": [25, 35],
            "eligible_rest_seconds": round(eligible_rest_s, 1),
            "eligible_rest_minutes": round(eligible_rest_s / 60.0, 1),
            "completion_pct": round(100.0 * duration_factor, 1),
            "basis": (
                f"เป้าหมาย {policy['label']} 30 นาที; "
                "นับเวลาที่มีหลักฐานว่าอยู่ใน ZEEP และไม่หักเมื่อพักเกินเป้าหมาย"
            ),
        },
        "physiology": {
            "available": hr_regularity is not None and rr_regularity is not None,
            "heart_rate_average": round(_average(hr), 1) if hr else None,
            "respiration_average": round(_average(rr), 1) if rr else None,
            "regularity_factor": round(regularity, 3) if regularity is not None else None,
            "heart_rate_regularity_factor": (
                round(hr_regularity, 3) if hr_regularity is not None else None
            ),
            "respiration_regularity_factor": (
                round(rr_regularity, 3) if rr_regularity is not None else None
            ),
            "settling_factor": round(settling, 3) if settling is not None else None,
            "paired_hr_rr_samples": paired_vital_samples,
            "source_sensor_samples": source_vital_samples,
            "paired_hr_rr_coverage_pct": round(paired_vital_ratio * 100.0, 1),
            "method": "ความนิ่งและแนวโน้ม HR/RR ระดับ Sample; ไม่ใช่ True HRV/RMSSD/SDNN",
        },
        "body_response": {
            "available": bool(bed_labels),
            "movement_pct": round((movement_ratio or 0.0) * 100.0, 1) if bed_labels else None,
            "bed_exit_events": exits if bed_labels else None,
            "transient_bed_exit_samples": (
                exit_summary["transient_samples"] if bed_labels else None),
        },
        "environment_support": {
            "available": bool(environment_factors),
            "averages": environment_averages,
            "fit": {key: round(value, 3) for key, value in environment_factors.items()},
            "context_only": True,
        },
        "data_coverage": {
            "ratio": round(coverage_ratio, 3),
            "pct": round(coverage_ratio * 100.0, 1),
            "points": coverage_points,
            "max_points": 10.0,
        },
        "component_points": component_points,
        "component_max_points": component_max,
        "component_order": list(component_points),
        "component_labels": {
            "goal_duration": "เวลาพักตามเป้าหมาย",
            "physiological_response": "การตอบสนองของร่างกาย",
            "body_stillness": "ความนิ่งระหว่างพัก",
            "environment_support": "สภาพแวดล้อมสนับสนุน",
            "data_coverage": "ความครบของข้อมูล",
        },
        "score_unrounded": earned,
        "score_basis": (
            "เวลาพักที่มีหลักฐานเทียบเป้าหมาย 30 นาที 20 + "
            "การตอบสนอง HR/RR 30 + ความต่อเนื่อง 20 + "
            "สภาพแวดล้อม 20 + ข้อมูล 10"
        ),
        "version": SLEEP_QUALITY_VERSION,
        "outcome_interpretation": "Nap & Refresh ไม่บังคับให้หลับหรือมี N3/REM; ความสดชื่นจริงใช้คำตอบหลัง Session ประกอบ",
        "disclaimer": "Recovery Score เป็นการประเมิน ZEEP Wellness จาก Sensor ไม่ใช่การวินิจฉัย การรักษา หรือผล AASM/PSG",
    }


def _stage_balance_factor(mode: str, sleep_pct: Dict[str, float]) -> float:
    """Score broad stage balance without demanding overnight stages from a nap.

    These are intentionally permissive ZEEP operating bands for an estimator,
    not AASM reference ranges and not medical cut-offs.  Wake is evaluated by
    efficiency/continuity, while this function uses percentages of actual TST.
    """
    if mode == "short_nap":
        # A brief nap may appropriately remain N1/N2 and should not lose points
        # merely because it ended before N3 or REM appeared.
        n1 = _range_fit(sleep_pct["n1"], 0.05, 0.70, 0.0, 0.95)
        n2 = _range_fit(sleep_pct["n2"], 0.20, 0.90, 0.0, 1.0)
        return 0.40 * n1 + 0.60 * n2

    if mode in {"cycle_nap", "shift_rest", "jet_lag"}:
        # For recovery/shift/jet-lag rest, N3 and REM are useful when observed
        # but their absence in one short opportunity is not treated as failure.
        n1 = _range_fit(sleep_pct["n1"], 0.02, 0.35, 0.0, 0.70)
        n2 = _range_fit(sleep_pct["n2"], 0.30, 0.85, 0.10, 1.0)
        restorative = min(1.0, (sleep_pct["n3"] + sleep_pct["rem"]) / 0.15)
        return 0.20 * n1 + 0.55 * n2 + 0.25 * restorative

    # Wide overnight bands prevent over-rewarding a single stage while also
    # acknowledging that age, timing and individual physiology vary.
    fits = {
        "n1": _range_fit(sleep_pct["n1"], 0.02, 0.15, 0.0, 0.30),
        "n2": _range_fit(sleep_pct["n2"], 0.35, 0.70, 0.20, 0.85),
        "n3": _range_fit(sleep_pct["n3"], 0.05, 0.30, 0.0, 0.45),
        "rem": _range_fit(sleep_pct["rem"], 0.10, 0.30, 0.03, 0.45),
    }
    return 0.15 * fits["n1"] + 0.30 * fits["n2"] + 0.25 * fits["n3"] + 0.30 * fits["rem"]


def _duration_target(mode: str, actual_scored_s: float) -> Dict[str, Any]:
    """Return an explicit, mode-aware ZEEP target for score reproducibility."""
    if mode == "jet_lag":
        # Jet-lag recovery may be a strategic cycle nap or the main sleep.  The
        # recorded opportunity selects the appropriate target without changing
        # any raw stage labels.
        target_s = 90 * 60 if actual_scored_s <= 3 * 3600 else 7 * 3600
        basis = "Jet lag: พักไม่เกิน 3 ชม. ใช้ 90 นาที; Main sleep ใช้ AASM 7 ชั่วโมงขึ้นไป"
    else:
        target_s = REST_MODE_DURATION_TARGETS_S.get(mode, 7 * 3600)
        basis = {
            "short_nap": "ZEEP target สำหรับงีบสั้น 30 นาที",
            "cycle_nap": "ZEEP target สำหรับพักหนึ่งรอบ 90 นาที",
            "shift_rest": "ZEEP target ขั้นต่ำสำหรับพักจากการเข้าเวร 90 นาที",
            "overnight": "AASM/SRS สำหรับผู้ใหญ่: นอน 7 ชั่วโมงขึ้นไปอย่างสม่ำเสมอ",
        }.get(mode, "AASM/SRS adult overnight target 7 ชั่วโมงขึ้นไป")
    return {"seconds": target_s, "hours": round(target_s / 3600.0, 2), "basis": basis}


def _latency_points(mode: str, onset_s: Any) -> Dict[str, Any]:
    """Score the observed time to first sleep without inventing missing data.

    Short naps use a tighter ZEEP operating target.  A missing onset receives a
    neutral half score and is explicitly marked unavailable; this avoids both a
    false maximum and a technical zero for legacy Sessions.
    """
    onset = _number(onset_s)
    ideal_s, ceiling_s = ((10 * 60, 30 * 60) if mode == "short_nap"
                          else (20 * 60, 60 * 60))
    if onset is None:
        return {
            "available": False,
            "seconds": None,
            "points": 2.5,
            "max_points": 5.0,
            "basis": "ไม่มีเวลาหลับครั้งแรก; ใช้คะแนนกลางและแสดงว่าไม่มีข้อมูล",
        }
    onset = max(0.0, onset)
    if onset <= ideal_s:
        points = 5.0
    elif onset >= ceiling_s:
        points = 0.0
    else:
        points = 5.0 * (ceiling_s - onset) / (ceiling_s - ideal_s)
    return {
        "available": True,
        "seconds": round(onset, 1),
        "points": round(points, 1),
        "max_points": 5.0,
        "basis": f"เต็มเมื่อหลับภายใน {int(ideal_s / 60)} นาที; ลดจนเป็นศูนย์ที่ {int(ceiling_s / 60)} นาที",
    }


def _balanced_architecture_points(mode: str, sleep_pct: Dict[str, float]) -> Dict[str, Any]:
    """Return the 30-point restorative component for ZEEP-balanced v4.

    Overnight sleep keeps conservative N2/N3/REM guards.  Brief-rest modes use
    broad stage balance instead, because a valid nap may end before N3 or REM.
    These are project wellness rules, not AASM stage norms.
    """
    if mode != "overnight":
        factor = _stage_balance_factor(mode, sleep_pct)
        total = round(30.0 * factor, 1)
        return {
            "points": {"mode_adjusted_balance": total},
            "max_points": {"mode_adjusted_balance": 30.0},
            "total": total,
            "method": "สัดส่วน Stage ตาม Rest Mode; ไม่บังคับ N3/REM ในการพักสั้น",
            "mode_adjusted": True,
        }

    pct = {stage: sleep_pct[stage] * 100.0 for stage in SLEEP_STAGES}
    n2_low, n2_high = OVERNIGHT_N2_FULL_CREDIT_PCT
    n2_distance = n2_low - pct["n2"] if pct["n2"] < n2_low else max(0.0, pct["n2"] - n2_high)
    n2_points = max(0.0, OVERNIGHT_ARCHITECTURE_MAX_POINTS["n2"] - 0.35 * n2_distance)

    if pct["n3"] < OVERNIGHT_N3_ZERO_BELOW_PCT:
        n3_points = 0.0
    elif pct["n3"] < OVERNIGHT_N3_FULL_CREDIT_FROM_PCT:
        n3_points = (
            OVERNIGHT_ARCHITECTURE_MAX_POINTS["n3"]
            * pct["n3"] / OVERNIGHT_N3_FULL_CREDIT_FROM_PCT
        )
    else:
        n3_points = OVERNIGHT_ARCHITECTURE_MAX_POINTS["n3"]

    rem_low, rem_high = OVERNIGHT_REM_FULL_CREDIT_PCT
    rem_distance = rem_low - pct["rem"] if pct["rem"] < rem_low else max(0.0, pct["rem"] - rem_high)
    rem_points = max(0.0, OVERNIGHT_ARCHITECTURE_MAX_POINTS["rem"] - 0.40 * rem_distance)
    points = {
        "n2": round(n2_points, 1),
        "n3": round(n3_points, 1),
        "rem": round(rem_points, 1),
    }
    return {
        "points": points,
        "max_points": dict(OVERNIGHT_ARCHITECTURE_MAX_POINTS),
        "total": round(sum(points.values()), 1),
        "method": "N2 45–75% · N3 ≥10% · REM 15–25% ของ TST (ZEEP conservative proxy)",
        "mode_adjusted": False,
    }


def analyse_arousal_proxy(
    stage_sequence: Optional[Iterable[Any]],
    *,
    sample_interval_s: float = 5.0,
    shift_threshold: float = 0.12,
    movement_threshold: float = 0.15,
    prior_sleep_s: float = 10.0,
    quiet_gap_s: float = 30.0,
) -> Dict[str, Any]:
    """Reduce cadence-versioned BCG/motion flags into disturbance episodes.

    One episode remains active until the evidence has been absent for 30 seconds,
    preventing a sustained amplitude shift from being counted every sample.
    Requiring 10 seconds of prior sleep mirrors the temporal guard used for an
    AASM arousal, but the result remains a non-EEG BCG disturbance proxy.
    """
    interval = max(0.1, _number(sample_interval_s) or 5.0)
    minimum_sleep_ticks = max(1, int(round(prior_sleep_s / interval)))
    quiet_ticks = max(1, int(round(quiet_gap_s / interval)))
    sleep_run_ticks = 0
    quiet_run_ticks = quiet_ticks
    active = False
    episodes = 0
    evidence_windows = 0
    available_windows = 0
    sleep_ticks = 0

    for raw in stage_sequence or []:
        if isinstance(raw, dict):
            stage = raw.get("sleep") or raw.get("state")
            metrics = raw.get("metrics") if isinstance(raw.get("metrics"), dict) else raw
            proxy = metrics.get("arousal_proxy") if isinstance(metrics.get("arousal_proxy"), dict) else {}
            shift = _number(metrics.get("bcg_amplitude_shift_ratio"))
            if shift is None:
                shift = _number(proxy.get("bcg_amplitude_shift_ratio"))
            movement = _number(metrics.get("movement_ratio"))
            if movement is None:
                movement = _number(proxy.get("movement_ratio"))
            bed_status = str(metrics.get("bed_status") or raw.get("bed") or "")
            available = shift is not None or movement is not None or bool(bed_status)
        else:
            stage, shift, movement, bed_status, available = raw, None, None, "", False
        stage = {"nrem_light": "n2", "nrem_deep": "n3"}.get(str(stage), str(stage))
        prior_sleep_ticks = sleep_run_ticks
        if stage in SLEEP_STAGES:
            sleep_run_ticks += 1
            sleep_ticks += 1
        else:
            sleep_run_ticks = 0
        if not available:
            continue
        available_windows += 1
        flag = bool(
            (shift is not None and shift >= shift_threshold)
            or (movement is not None and movement >= movement_threshold)
            or bed_status.casefold() == "get out of bed"
        )
        if flag:
            evidence_windows += 1
            if prior_sleep_ticks >= minimum_sleep_ticks and (not active or quiet_run_ticks >= quiet_ticks):
                episodes += 1
                active = True
            quiet_run_ticks = 0
        elif active:
            quiet_run_ticks += 1

    sleep_hours = sleep_ticks * interval / 3600.0
    index = episodes / sleep_hours if sleep_hours > 0 and available_windows else None
    return {
        "available": bool(available_windows and sleep_hours > 0),
        "episodes": episodes if available_windows else None,
        "index_per_hour": round(index, 2) if index is not None else None,
        "evidence_windows": evidence_windows if available_windows else None,
        "available_windows": available_windows,
        "penalty_points": round(min(10.0, 0.5 * index), 1) if index is not None else 0.0,
        "thresholds": {
            "bcg_amplitude_shift_ratio": shift_threshold,
            "movement_ratio": movement_threshold,
            "prior_sleep_s": prior_sleep_s,
            "quiet_gap_s": quiet_gap_s,
        },
        "validated_cortical_arousal": False,
        "method": "BCG amplitude shift / movement / bed exit episode; ไม่ใช่ EEG arousal",
    }


def analyse_sleep_cycles(
    stage_sequence: Optional[Iterable[Any]],
    *,
    sample_interval_s: float = 5.0,
    minimum_nrem_s: float = 45 * 60,
) -> Dict[str, Any]:
    """Find conservative NREM→REM opportunities without counting REM flicker.

    A new cycle is counted only after at least 45 accumulated minutes of NREM.
    Resetting that accumulator after the first REM prevents short REM/N2
    oscillation from being reported as many sleep cycles. This is a ZEEP proxy,
    not a PSG/AASM cycle count.
    """
    sequence = []
    aliases = {"nrem_light": "n2", "nrem_deep": "n3"}
    for raw in stage_sequence or []:
        stage = (raw.get("sleep") or raw.get("state")) if isinstance(raw, dict) else raw
        stage = aliases.get(str(stage), str(stage))
        if stage in STAGE_ORDER:
            sequence.append(stage)
    if not sequence:
        return {
            "available": False,
            "completed_nrem_rem_cycles": None,
            "minimum_nrem_s": minimum_nrem_s,
            "method": "≥45 min accumulated NREM before REM",
            "clinical_equivalent": False,
        }

    completed = 0
    nrem_s = 0.0
    in_rem = False
    for stage in sequence:
        if stage in {"n1", "n2", "n3"}:
            nrem_s += sample_interval_s
            in_rem = False
        elif stage == "rem":
            if not in_rem and nrem_s >= minimum_nrem_s:
                completed += 1
                nrem_s = 0.0
            in_rem = True
        else:
            in_rem = False
    return {
        "available": True,
        "completed_nrem_rem_cycles": completed,
        "minimum_nrem_s": minimum_nrem_s,
        "method": "≥45 min accumulated NREM before REM",
        "clinical_equivalent": False,
    }


def build_sleep_quality(
    duration_s: Any,
    night_summary: Optional[Dict[str, Any]],
    sleep_state_counts: Optional[Dict[str, Any]] = None,
    *,
    completed: bool = True,
    rest_mode: Any = "auto",
    stage_sequence: Optional[Iterable[Any]] = None,
    sensor_samples: Optional[Iterable[Dict[str, Any]]] = None,
    sample_interval_s: float = 5.0,
) -> Dict[str, Any]:
    """Build the mode-aware ZEEP-balanced post-session wellness score.

    The five visible components mirror the product promise without claiming a
    clinical diagnosis: sleep opportunity/onset 20, stability 30, restorative
    architecture 30, cycle expression 15, and data coverage 5. Rest Mode keeps
    a short nap from being judged as an incomplete overnight sleep. Raw
    W/N1/N2/N3/REM decisions are inputs only and are never rewritten here.
    """
    requested_mode = normalise_rest_mode(rest_mode)
    unavailable = {
        "available": False,
        "score": None,
        "level": "ข้อมูลไม่พอ",
        "level_key": "unavailable",
        "reason": "Session ยังไม่สิ้นสุด" if not completed else "ไม่มี Sleep State เพียงพอสำหรับประเมิน",
        "version": SLEEP_QUALITY_VERSION,
        "score_title": (
            REST_SESSION_GROUPS.get(requested_mode, {}).get("score_title")
            or "คุณภาพการพัก"
        ),
    }
    duration = _number(duration_s)
    if not completed or duration is None or duration <= 0:
        return unavailable

    night = dict(night_summary or {})
    counts = _normalise_stage_counts(sleep_state_counts)
    total_sleep_samples = sum(counts[stage] for stage in SLEEP_STAGES)
    total_scored_samples = total_sleep_samples + counts["wake"]
    interval = max(0.1, _number(sample_interval_s) or 5.0)
    actual_scored_s = total_scored_samples * interval
    estimated_sleep_s = total_sleep_samples * interval
    rows = list(sensor_samples or [])
    source_vital_rows = 0
    paired_vital_rows = 0
    for row in rows:
        source_rows = max(1, int(_number(row.get("_source_rows")) or 1))
        source_vital_rows += source_rows
        explicit_paired = _number(row.get("_paired_hr_rr_rows"))
        if explicit_paired is not None:
            paired_vital_rows += max(0, min(source_rows, int(explicit_paired)))
            continue
        if (
            filter_vital_values([row.get("hr")], HR_SANITY_RANGE_BPM)
            and filter_vital_values([row.get("rr")], RR_SANITY_RANGE_PER_MIN)
        ):
            paired_vital_rows += source_rows
    paired_vital_ratio = (
        paired_vital_rows / source_vital_rows if source_vital_rows else 0.0
    )
    mode = _resolve_rest_mode(rest_mode, actual_scored_s, estimated_sleep_s)
    mode["protocol_status"] = _protocol_status(mode, duration)
    # Nap & Refresh always uses Recovery Score, whether the Session remained
    # awake, contained N1/N2, or became a short nap. Sleep is an optional
    # observation and must not switch the user onto Overnight architecture.
    if mode.get("group") == "nap_recovery" or mode["resolved"] in _AWAKE_REST_MODES:
        if not rows and total_scored_samples <= 0:
            unavailable["reason"] = "ไม่มีข้อมูล Sensor เพียงพอสำหรับประเมินการพัก"
            return unavailable
        return _build_awake_rest_quality(duration, mode, counts, rows, interval)
    if total_scored_samples <= 0:
        return unavailable

    # Every term deliberately comes from the same recorded state rounds. It is
    # not mixed with user-reported sleep before/after Sensor recording.
    efficiency = max(0.0, min(1.0, total_sleep_samples / total_scored_samples))
    awakenings = max(0, int(_number(night.get("awakenings")) or 0))
    sleep_pct = {
        stage: (counts[stage] / total_sleep_samples if total_sleep_samples else 0.0)
        for stage in SLEEP_STAGES
    }

    # 1) Sleep opportunity + onset — 20 points. Duration contributes 15 instead
    # of the old 40, so a partly recorded but physiologically stable sleep is not
    # overwhelmed by one duration term. The AASM/SRS 7-hour threshold applies
    # only to overnight/main-sleep mode.
    duration_target = _duration_target(mode["resolved"], actual_scored_s)
    duration_points = round(
        15.0 * min(1.0, estimated_sleep_s / max(1.0, duration_target["seconds"])), 1)
    latency = _latency_points(mode["resolved"], night.get("sleep_onset_proxy_s"))
    opportunity_points = round(duration_points + latency["points"], 1)

    # 2) Stability — 30 points: efficiency 20 + continuity 10. BCG disturbance
    # episodes can remove at most five points and are explicitly not EEG arousal.
    efficiency_points = round(20.0 * efficiency, 1)
    wake_pct = counts["wake"] * 100.0 / total_scored_samples
    wake_points = 10.0 if wake_pct <= 10.0 else max(0.0, 10.0 - (wake_pct - 10.0))
    arousal = analyse_arousal_proxy(stage_sequence, sample_interval_s=interval)
    balanced_arousal_penalty = (
        round(min(5.0, 0.25 * arousal["index_per_hour"]), 1)
        if arousal.get("index_per_hour") is not None else 0.0
    )
    continuity_points = round(max(0.0, wake_points - balanced_arousal_penalty), 1)
    stability_points = round(efficiency_points + continuity_points, 1)

    # 3) Restorative architecture — 30 points. Conservative N2/N3/REM bands
    # apply only to overnight; short-rest modes never require N3 or REM.
    architecture = (
        _balanced_architecture_points(mode["resolved"], sleep_pct)
        if total_sleep_samples else {
            "points": {"mode_adjusted_balance": 0.0},
            "max_points": {"mode_adjusted_balance": 30.0},
            "total": 0.0,
            "method": "ไม่มี Sleep State",
            "mode_adjusted": mode["resolved"] != "overnight",
        }
    )

    # 4) Cycle expression / readiness proxy — 15 points. It describes whether a
    # recorded opportunity expressed plausible NREM→REM progression. It is not a
    # direct measurement that the user woke refreshed; subjective alertness must
    # be collected separately if that claim is required.
    cycles = analyse_sleep_cycles(stage_sequence, sample_interval_s=interval)
    expected_cycles = (
        max(1, int((estimated_sleep_s + 45 * 60) // (90 * 60)))
        if mode["resolved"] == "overnight" and estimated_sleep_s > 0 else 1
    )
    completed_cycles = cycles.get("completed_nrem_rem_cycles")
    cycles["expected_for_score"] = expected_cycles if mode["resolved"] != "short_nap" else 0
    if mode["resolved"] == "short_nap":
        # A power nap is rewarded for staying efficient and expressing a broad
        # N1/N2 balance; it is never required to reach REM/N3 or a full cycle.
        nap_factor = 0.5 * efficiency + 0.5 * _stage_balance_factor("short_nap", sleep_pct)
        cycle_points = round(15.0 * nap_factor, 1)
        cycles["score_note"] = "งีบสั้นใช้ความต่อเนื่องและ N1/N2; ไม่บังคับ NREM→REM"
    elif completed_cycles is None:
        cycle_points = 7.5
        cycles["score_note"] = "ไม่มีลำดับ Stage; ใช้คะแนนกลางและระบุว่าไม่มีหลักฐานรอบ"
    else:
        cycle_points = round(15.0 * min(1.0, completed_cycles / max(1, expected_cycles)), 1)
        cycles["score_note"] = "คะแนน ZEEP proxy จาก NREM→REM ที่ตรวจพบเทียบรอบที่คาดตามเวลาหลับ"
    cycles["points"] = cycle_points
    cycles["max_points"] = 15.0

    # 5) Data coverage — 5 points. A wall-clock gap cannot silently receive a
    # perfect score even when the available Sleep State rounds look good.
    coverage_ratio = max(0.0, min(1.0, actual_scored_s / max(1.0, duration)))
    coverage_points = round(5.0 * coverage_ratio, 1)

    component_points = {
        "sleep_opportunity": opportunity_points,
        "sleep_stability": stability_points,
        "restorative_architecture": architecture["total"],
        "cycle_expression": cycle_points,
        "data_coverage": coverage_points,
    }
    component_max = dict(SLEEP_QUALITY_COMPONENT_MAX_POINTS)
    component_order = list(component_points)
    nap_mode = mode.get("group") == "nap_recovery"
    component_labels = ({
        "sleep_opportunity": "เวลาและการเข้าสู่การพัก",
        "sleep_stability": "ความต่อเนื่องของการพัก",
        "restorative_architecture": "รูปแบบการพักที่ตรวจพบ",
        "cycle_expression": "การตอบสนองระหว่างพัก",
        "data_coverage": "ความครบของข้อมูล",
    } if nap_mode else {
        "sleep_opportunity": "หลับไวและเวลาพัก",
        "sleep_stability": "หลับดีและต่อเนื่อง",
        "restorative_architecture": "โครงสร้าง N2/N3/REM",
        "cycle_expression": "รอบการนอนที่ตรวจพบ",
        "data_coverage": "ความครบของข้อมูล",
    })
    earned_points = round(sum(component_points.values()), 1)
    score = 0 if estimated_sleep_s <= 0 else max(0, min(100, int(round(earned_points))))

    if score >= 85:
        level, level_key = "ดีมาก", "very_good"
    elif score >= 70:
        level, level_key = "ดี", "good"
    elif score >= 55:
        level, level_key = "ปานกลาง", "fair"
    else:
        level, level_key = "ควรปรับปรุง", "low"

    if nap_mode:
        if latency["available"] and latency["points"] < 3.0:
            insight = "ใช้เวลานานกว่าจะเข้าสู่การพัก ควรปรับช่วงเตรียมตัวและสภาพแวดล้อม"
        elif duration_points < 10.5:
            insight = "เวลาที่ Sensor ประเมินว่าพักยังต่ำกว่าเป้าหมาย Nap & Refresh"
        elif stability_points < 21.0:
            insight = "การพักยังไม่ต่อเนื่องเมื่อเทียบกับเวลาที่บันทึก"
        elif architecture["total"] < 18.0:
            insight = "รูปแบบการพักที่ตรวจพบยังกระจุกตัวและควรอ่านร่วมกับความรู้สึกหลังพัก"
        elif cycle_points < 9.0:
            insight = "การตอบสนองระหว่างพักยังไม่เด่นชัดจากข้อมูล Sensor"
        else:
            insight = "เวลา ความต่อเนื่อง และการตอบสนองระหว่างพักโดยรวมอยู่ในเกณฑ์ดี"
    elif latency["available"] and latency["points"] < 3.0:
        insight = "ใช้เวลาหลับนาน ควรปรับช่วงเตรียมตัวและสภาพแวดล้อมก่อนพัก"
    elif duration_points < 10.5:
        insight = f"เวลาหลับยังต่ำกว่าเป้าหมายของ {mode['label']}"
    elif stability_points < 21.0:
        insight = "พบช่วงตื่นมากเมื่อเทียบกับเวลาที่บันทึก"
    elif continuity_points < 7.0:
        insight = "พบ Wake หรือ BCG disturbance proxy หลายครั้งใน Session"
    elif architecture["total"] < 18.0:
        insight = f"สัดส่วนการฟื้นฟูของ {mode['label']} ยังไม่สมดุลในข้อมูลที่บันทึกได้"
    elif cycle_points < 9.0:
        insight = "รอบการนอนที่ตรวจพบยังไม่เต็มตามโอกาสการพักครั้งนี้"
    else:
        insight = f"หลับไว ความต่อเนื่อง และการฟื้นฟูของ {mode['label']} โดยรวมอยู่ในเกณฑ์ดี"

    score_available = bool(
        estimated_sleep_s > 0
        and paired_vital_rows >= 6
    )
    score_confidence = _score_confidence(
        coverage_ratio, paired_vital_ratio
    )
    return {
        "available": score_available,
        "score": score if score_available else None,
        "engineering_shadow_score": score,
        "score_releasable": score_available,
        "score_confidence": score_confidence,
        "release_requirements": {
            "minimum_confirmed_stage_coverage_pct_for_high_confidence": 80,
            "confirmed_stage_coverage_blocks_score": False,
            "confirmed_sleep_required": True,
            "minimum_paired_hr_rr_coverage_pct_for_high_confidence": 80,
            "paired_hr_rr_coverage_blocks_score": False,
            "minimum_paired_samples": 6,
            "paired_hr_rr_required": True,
            "paired_hr_rr_rows": paired_vital_rows,
            "source_vital_rows": source_vital_rows,
            "paired_hr_rr_coverage_pct": round(paired_vital_ratio * 100.0, 1),
            "passed": score_available,
        },
        "reason": (
            None if score_available else
            "ยังไม่พบ Sleep State หรือข้อมูล HR/RR ที่จับคู่กันไม่พอสำหรับคำนวณ Sleep Score"
        ),
        "score_title": mode.get("score_title") or "คุณภาพการนอน",
        "score_scope": mode.get("score_scope") or "ค่าประเมินการนอนจาก Sensor",
        "validation_status": "preliminary_wellness_estimate",
        "clinical_validated": False,
        "quality_type": "sleep",
        "session_character": "sleep",
        "sleep_detected": estimated_sleep_s > 0,
        "level": level,
        "level_key": level_key,
        "insight": insight,
        "estimated_sleep_s": round(estimated_sleep_s, 1),
        "actual_scored_s": round(actual_scored_s, 1),
        "wake_s": round(counts["wake"] * interval, 1),
        "wake_pct_recorded": round(wake_pct, 1),
        "sleep_efficiency_pct": round(efficiency * 100.0),
        "awakenings": awakenings,
        "wake_entries": awakenings,
        # Keep one decimal here because the scoring gate uses the unrounded
        # percentage. Showing 3% when the true value is 2.9% would make the
        # conservative N3 <3% rule appear inconsistent to the user.
        "deep_pct": round(sleep_pct["n3"] * 100.0, 1),
        "rem_pct": round(sleep_pct["rem"] * 100.0, 1),
        "stage_pct_of_sleep": {
            stage: round(sleep_pct[stage] * 100.0, 1) for stage in ("n1", "n2", "n3", "rem")
        },
        "rest_mode": mode,
        "duration_target": duration_target,
        "sleep_opportunity": {
            "duration_points": duration_points,
            "duration_max_points": 15.0,
            "latency": latency,
        },
        "architecture": architecture,
        "continuity": {
            "wake_points": round(wake_points, 1),
            "wake_max_points": 10.0,
            "efficiency_points": efficiency_points,
            "efficiency_max_points": 20.0,
            "balanced_arousal_penalty_points": balanced_arousal_penalty,
            "arousal_proxy": arousal,
        },
        "data_coverage": {
            "ratio": round(coverage_ratio, 3),
            "pct": round(coverage_ratio * 100.0, 1),
            "points": coverage_points,
            "max_points": 5.0,
        },
        "cycles": cycles,
        "component_points": component_points,
        "component_max_points": component_max,
        "component_order": component_order,
        "component_labels": component_labels,
        "score_unrounded": earned_points,
        "score_basis": (
            "เวลา/การเข้าสู่การพัก 20 + ความต่อเนื่อง 30 + รูปแบบการพัก 30 + การตอบสนอง 15 + ข้อมูล 5"
            if nap_mode else
            "หลับไว/เวลาพัก 20 + หลับต่อเนื่อง 30 + ฟื้นฟู 30 + รอบการนอน 15 + ข้อมูล 5"
        ),
        "version": SLEEP_QUALITY_VERSION,
        "outcome_interpretation": (
            "Nap & Refresh ไม่บังคับ N3/REM; Recovery Score สะท้อนสัญญาณสนับสนุนการฟื้นตัว และต้องอ่านร่วมกับคำตอบก่อน–หลัง Session"
            if nap_mode else
            "ความสดชื่นหลังตื่นต้องใช้คำตอบหลัง Session ประกอบ"
        ),
        "disclaimer": (
            f"{mode.get('score_title') or 'Sleep Score'} เป็นการประเมิน ZEEP Wellness "
            "จาก BCG/Sensor ไม่ใช่ PSG หรือผลวินิจฉัย"
        ),
    }


def _post_session_guidance(
    quality: Dict[str, Any],
    findings: list[Dict[str, Any]],
) -> Dict[str, Any]:
    """Return practical, non-diagnostic guidance for the next activity.

    Advice is intentionally derived from the selected Session goal, released
    wellness score and explanatory environment findings. It never changes a
    Sleep State and it never claims readiness from Sensor data alone.
    """
    mode = quality.get("rest_mode") or {}
    group = str(mode.get("group") or mode.get("requested") or "nap_recovery")
    score = _number(quality.get("score"))
    released = bool(quality.get("available") and score is not None)
    if not released:
        primary = (
            "ผล Sensor ยังไม่ครบพอสำหรับสรุปคะแนน ให้ใช้ความรู้สึกหลังพักประกอบก่อนทำกิจกรรมถัดไป"
        )
    elif group == "sleep" and score >= 85:
        primary = "เริ่มเช้าวันใหม่ตามปกติ และบันทึกความสดชื่นเพื่อเทียบกับ Sleep Score"
    elif group == "sleep" and score >= 70:
        primary = "ให้เวลาร่างกายตื่นตัว ดื่มน้ำ รับแสงธรรมชาติ และเช็กความง่วงก่อนเริ่มงาน"
    elif group == "sleep":
        primary = "เริ่มกิจกรรมแบบค่อยเป็นค่อยไป และหลีกเลี่ยงงานเสี่ยงหากยังง่วงมาก"
    elif score >= 85:
        primary = "พักปรับตัวสั้น ๆ แล้วกลับสู่กิจกรรม พร้อมบันทึกความสดชื่นหลัง Nap & Refresh"
    elif score >= 70:
        primary = "ลุกขยับเบา ๆ ดื่มน้ำ และประเมินพลังงานของตนเองก่อนทำกิจกรรมถัดไป"
    else:
        primary = "ให้เวลาปรับตัว 5–10 นาที รับแสงหรือขยับเบา ๆ แล้วประเมินความพร้อมอีกครั้ง"

    environment_action = next(
        (
            item.get("action") for item in findings
            if item.get("decision") in {"required", "optimise", "sensor_check"}
            and item.get("action")
        ),
        None,
    )
    next_session = (
        f"ครั้งถัดไป: {environment_action}"
        if environment_action else
        "ครั้งถัดไป: รักษาการตั้งค่าที่สบายและตอบแบบประเมินหลังพักเพื่อเพิ่มบริบทส่วนบุคคล"
    )
    return {
        "primary": primary,
        "next_session": next_session,
        "self_check": (
            "ก่อนขับรถ ใช้เครื่องจักร หรือทำกิจกรรมเสี่ยง ให้ยึดความตื่นตัวจริงของตนเอง ไม่ใช้คะแนนแทนการตัดสินใจ"
        ),
        "mode": group,
        "score_used": int(score) if released else None,
        "score_released": released,
        "basis": (
            "ZEEP Wellness & Longevity · Sensor + เป้าหมายการพัก + สภาพแวดล้อม; "
            "ควรอ่านร่วมกับ self-report หลังพัก"
        ),
        "medical_diagnosis": False,
    }


def _environment_metric(
    samples: list[Dict[str, Any]],
    *,
    criterion_key: str,
    rest_mode: Any,
) -> Dict[str, Any]:
    criterion = environment_criterion(criterion_key, rest_mode)
    key = criterion["sample_key"]
    values = _values(samples, key)
    total = len(samples)
    if not values:
        return {
            "key": criterion_key,
            "sample_key": key,
            "label": criterion["label"],
            "unit": criterion["unit"],
            "source": criterion["source"],
            "available": False,
            "coverage_pct": 0,
            "status_key": "unavailable",
            "status": "ไม่มีข้อมูล",
            "decision": "sensor_check",
        }
    levels = [environment_level_for_value(criterion_key, value, rest_mode) for value in values]
    level_counts = {name: levels.count(name) for name in ENVIRONMENT_LEVELS}
    ranks = sorted(ENVIRONMENT_LEVELS[name]["rank"] for name in levels)
    # Use a 90%-of-time floor so one transient packet does not downgrade a
    # whole Session. A Critical sample remains visible regardless of duration.
    floor_index = max(0, min(len(ranks) - 1, int((len(ranks) * 0.10 + 0.999999)) - 1))
    floor_rank = 0 if level_counts["critical"] else ranks[floor_index]
    status_key = next(
        name for name, definition in ENVIRONMENT_LEVELS.items()
        if definition["rank"] == floor_rank
    )
    level = ENVIRONMENT_LEVELS[status_key]
    outside_pct = _percent(sum(level_counts[name] for name in ("critical", "poor", "fair", "good")), len(values))
    below_expected_pct = _percent(level_counts["critical"] + level_counts["poor"], len(values))
    average = sum(values) / len(values)
    midpoint = None
    first_band = criterion["selected_bands"][0]
    if criterion["kind"] == "range":
        midpoint = (first_band[0] + first_band[1]) / 2.0
        direction = "high" if average > midpoint else "low"
    else:
        direction = "high"
    action = criterion.get("action_high") if direction == "high" else criterion.get("action_low")
    policy = environment_policy_snapshot(rest_mode)
    policy_criterion = next(item for item in policy["criteria"] if item["key"] == criterion_key)
    return {
        "key": criterion_key,
        "sample_key": key,
        "label": criterion["label"],
        "unit": criterion["unit"],
        "source": criterion["source"],
        "mode": criterion["mode"],
        "target": policy_criterion["excellent_target"],
        "expected_floor": policy_criterion["acceptable_floor"],
        "bands": policy_criterion["bands_text"],
        "available": True,
        "coverage_pct": _percent(len(values), total),
        "average": round(average, 1),
        "minimum": round(min(values), 1),
        "maximum": round(max(values), 1),
        "outside_target_pct": outside_pct,
        "below_expected_pct": below_expected_pct,
        "outside_direction": direction if outside_pct else None,
        "status_key": status_key,
        "status": level["label"],
        "rank": level["rank"],
        "decision": level["decision"],
        "meets_expected": level["rank"] >= ENVIRONMENT_LEVELS[ENVIRONMENT_ACCEPTABLE_MIN_LEVEL]["rank"],
        "level_distribution_pct": {
            name: _percent(count, len(values)) for name, count in level_counts.items()
        },
        "action": (
            action if level["decision"] in {"required", "optimise"}
            else "รักษาการตั้งค่าปัจจุบัน"
        ),
    }


def _bed_events(samples: list[Dict[str, Any]]) -> Dict[str, Any]:
    labels = [str(sample.get("bed") or "") for sample in samples]
    moving = sum(label == "Moving" for label in labels)
    exit_summary = bed_exit_event_summary(labels)
    return {
        "movement_pct": _percent(moving, len(labels)),
        "bed_exit_events": exit_summary["event_count"],
        "transient_bed_exit_samples": exit_summary["transient_samples"],
        "confirmed_bed_exit_samples": exit_summary["confirmed_samples"],
        "weak_breathing_samples": sum(label == "Weak breathing" for label in labels),
        "snoring_samples": sum(label == "Snoring" for label in labels),
    }


def build_session_report(
    duration_s: Any,
    samples: Optional[list[Dict[str, Any]]],
    night_summary: Optional[Dict[str, Any]],
    sleep_state_counts: Optional[Dict[str, Any]],
    sleep_quality: Optional[Dict[str, Any]],
    *,
    rest_mode: Any = "auto",
    sample_interval_s: float = 5.0,
    estimator_version: Optional[str] = None,
    completed: bool = True,
    timeline_schema_version: int = 4,
) -> Dict[str, Any]:
    """Return the compact, explainable report shown after a Session ends."""
    rows = list(samples or [])
    duration = _number(duration_s) or 0.0
    counts = _normalise_stage_counts(sleep_state_counts)
    scored_count = sum(counts.values())
    quality = dict(sleep_quality or {})
    night = dict(night_summary or {})
    stage_percentages = _stage_percentages(counts)
    total_sleep_count = sum(counts[stage] for stage in SLEEP_STAGES)

    if not completed:
        return {
            "available": False,
            "reason": "Session ยังไม่สิ้นสุด",
            "version": SESSION_REPORT_VERSION,
        }

    stages = []
    for stage in STAGE_ORDER:
        count = counts[stage]
        stages.append({
            "state": stage,
            "samples": int(count),
            "duration_s": round(count * sample_interval_s, 1),
            # pct_scored uses all actual W/N1/N2/N3/REM rounds. pct_sleep
            # excludes W and is provided for sleep-architecture inspection.
            "pct_scored": stage_percentages[stage],
            "pct_sleep": (
                round(count * 100.0 / total_sleep_count, 1)
                if stage in SLEEP_STAGES and total_sleep_count else None
            ),
        })

    estimated_sleep = _number(night.get("estimated_sleep_s"))
    if estimated_sleep is None:
        estimated_sleep = sum(counts[stage] for stage in SLEEP_STAGES) * sample_interval_s
    estimated_sleep = max(0.0, min(duration, estimated_sleep)) if duration else max(0.0, estimated_sleep)
    wake_s = counts["wake"] * sample_interval_s
    quality_mode = quality.get("rest_mode") or _resolve_rest_mode(
        rest_mode, scored_count * sample_interval_s, estimated_sleep)
    environment_mode = quality_mode.get("group") or quality_mode.get("resolved") or rest_mode

    waso_samples = 0
    sleep_started = False
    for sample in rows:
        stage = sample.get("sleep")
        if stage in SLEEP_STAGES or stage in {"nrem_light", "nrem_deep"}:
            sleep_started = True
        elif sleep_started and stage == "wake":
            waso_samples += 1

    environment = [
        _environment_metric(rows, criterion_key=key, rest_mode=environment_mode)
        for key in ENVIRONMENT_CONTEXT_CRITERIA
    ]

    corroborated_sound_events = sum(bool(sample.get("acoustic_corroborated")) for sample in rows)
    findings = []
    for metric in environment:
        if not metric.get("available"):
            legacy_unstored = bool(
                timeline_schema_version < 4
                and metric["key"] in {"pm25", "voc"}
            )
            findings.append({
                "key": metric["key"], "severity": "unavailable",
                "level_key": "unavailable", "decision": "sensor_check",
                "title": (
                    f"{metric['label']} · Timeline รุ่นเดิมไม่ได้บันทึก"
                    if legacy_unstored else f"{metric['label']} · ไม่มีข้อมูล"
                ),
                "detail": (
                    f"Session นี้ใช้ Timeline schema v{timeline_schema_version}; "
                    f"ขณะนั้นระบบยังไม่เก็บค่าจาก {metric['source']} ลงรายงาน"
                    if legacy_unstored
                    else f"ยังประเมิน {metric['source']} ในโหมดนี้ไม่ได้"
                ),
                "action": (
                    "ใช้ Session ใหม่หลังอัปเดต Timeline schema v4"
                    if legacy_unstored
                    else f"ตรวจ {metric['source']} และ freshness"
                ),
                "context_only": True,
                "legacy_timeline_not_persisted": legacy_unstored,
            })
            continue
        unit = f" {metric['unit']}" if metric.get("unit") else ""
        decision = metric["decision"]
        action = metric.get("action")
        if decision == "required":
            action_text = action or "ตรวจสาเหตุและแก้ไข"
        elif decision == "optimise":
            action_text = f"ผ่านขั้นต่ำ · {action}" if action else "ผ่านขั้นต่ำ · ติดตามแนวโน้ม"
        else:
            action_text = "รักษาการตั้งค่าปัจจุบัน"
        findings.append({
            "key": metric["key"],
            "severity": metric["status_key"],
            "level_key": metric["status_key"],
            "decision": decision,
            "title": f"{metric['label']} · {metric['status']}",
            "detail": (
                f"เฉลี่ย {metric['average']:g}{unit} · ช่วง "
                f"{metric['minimum']:g}–{metric['maximum']:g}{unit} · "
                + (
                    f"ต่ำกว่าพอใช้ {metric['below_expected_pct']}% · "
                    if metric["below_expected_pct"] else ""
                )
                + "ผ่านขั้นต่ำ "
                f"{metric['expected_floor']} · เป้าหมายสูงสุด {metric['target']}"
            ),
            "action": action_text,
            "context_only": True,
        })
    if corroborated_sound_events:
        findings.insert(0, {
            "key": "acoustic_corroborated",
            "severity": "fair",
            "level_key": "fair",
            "decision": "investigate",
            "title": "พบเสียงตรงกับการตอบสนองจากเตียง",
            "detail": f"SPH0645 และ BCG/Bed Status ตรงกัน {corroborated_sound_events} รอบข้อมูล",
            "action": "ตรวจ Timeline เพื่อหาแหล่งเสียงหรือการสั่นในช่วงเดียวกัน",
            "context_only": False,
        })
    findings.sort(key=lambda item: {
        "critical": 0, "poor": 1, "unavailable": 2, "fair": 3,
        "good": 4, "excellent": 5,
    }.get(item["severity"], 6))
    available_environment = [metric for metric in environment if metric.get("available")]
    unavailable_environment = [metric for metric in environment if not metric.get("available")]
    minimum_metric = min(available_environment, key=lambda item: item["rank"], default=None)
    required_metrics = [metric for metric in available_environment if metric["decision"] == "required"]
    optimisation_metrics = [metric for metric in available_environment if metric["decision"] == "optimise"]
    environment_assessment = {
        "version": ENVIRONMENT_CONTEXT_POLICY_VERSION,
        "mode": environment_mode,
        "mode_label": quality_mode.get("label"),
        "acceptable_min_level": ENVIRONMENT_ACCEPTABLE_MIN_LEVEL,
        "acceptable_min_label": ENVIRONMENT_LEVELS[ENVIRONMENT_ACCEPTABLE_MIN_LEVEL]["label"],
        "overall_level": minimum_metric["status_key"] if minimum_metric else "unknown",
        "overall_label": minimum_metric["status"] if minimum_metric else "รอข้อมูล",
        "meets_expected": bool(
            available_environment and not unavailable_environment and not required_metrics
        ),
        "required_count": len(required_metrics) + len(unavailable_environment),
        "optimisation_count": len(optimisation_metrics),
        "maintain_count": len(available_environment) - len(required_metrics) - len(optimisation_metrics),
        "available_count": len(available_environment),
        "expected_count": len(environment),
        "context_only": True,
        "direct_stage_influence": False,
        "safety_thresholds_unchanged": True,
    }

    total_rows = len(rows)
    bcg_rows = sum(
        sample.get("bed") is not None
        and (sample.get("hr") is not None or sample.get("rr") is not None)
        for sample in rows
    )
    stage_rows = sum(sample.get("sleep") in STAGE_ORDER for sample in rows)
    if stage_rows == 0 and total_rows:
        stage_rows = min(total_rows, int(scored_count))
    environment_coverages = [item["coverage_pct"] for item in environment if item.get("available")]
    recording_coverage = _percent(total_rows * sample_interval_s, duration) if duration else 0
    coverage = {
        "recording_pct": recording_coverage,
        "bcg_pct": _percent(bcg_rows, total_rows),
        "sleep_stage_pct": _percent(stage_rows, total_rows),
        "environment_pct": (
            round(sum(environment_coverages) / len(environment_coverages))
            if environment_coverages else 0
        ),
    }
    confidence_counts = {"high": 0, "medium": 0, "low": 0}
    for sample in rows:
        confidence = sample.get("sleep_confidence")
        if confidence in confidence_counts:
            confidence_counts[confidence] += 1
    confidence_total = sum(confidence_counts.values())
    confidence_pct = {
        name: _percent(value, confidence_total) for name, value in confidence_counts.items()
    } if confidence_total else None

    core_coverage = min(coverage["recording_pct"], coverage["bcg_pct"], coverage["sleep_stage_pct"])
    if core_coverage >= 90:
        data_level, data_label = "high", "ความครอบคลุมดี"
    elif core_coverage >= 70:
        data_level, data_label = "medium", "ความครอบคลุมพอใช้"
    else:
        data_level, data_label = "low", "ความครอบคลุมจำกัด"

    bed = _bed_events(rows)
    insight = quality.get("insight") or "สรุปจากข้อมูลที่ระบบบันทึกได้ใน Session นี้"
    post_session_guidance = _post_session_guidance(quality, findings)
    return {
        "available": bool(duration > 0 and (rows or scored_count)),
        "version": SESSION_REPORT_VERSION,
        "product_positioning": "ZEEP Wellness & Longevity",
        "intended_use": "wellness_sleep_and_recovery_estimation_not_diagnosis",
        "timeline_schema_version": timeline_schema_version,
        "estimator_version": estimator_version,
        "headline": quality.get("level") or ("ข้อมูลพร้อมสรุป" if scored_count else "ข้อมูลไม่พอ"),
        "insight": insight,
        "quality": quality,
        "rest_mode": quality_mode,
        "sleep": {
            "recording_s": round(duration, 1),
            "estimated_sleep_s": round(estimated_sleep, 1),
            "wake_s": round(wake_s, 1),
            "sleep_onset_proxy_s": _number(night.get("sleep_onset_proxy_s")),
            "waso_proxy_s": round(waso_samples * sample_interval_s, 1),
            "sleep_efficiency_pct": quality.get("sleep_efficiency_pct"),
            "actual_scored_s": round(scored_count * sample_interval_s, 1),
            "wake_pct_recorded": stage_percentages["wake"],
            "cycles": quality.get("cycles"),
            # wake_s is total Stage-W duration; wake_entries is the number of
            # sleep -> W transitions. Keep awakenings as a compatibility key.
            "wake_entries": int(_number(night.get("awakenings")) or 0),
            "awakenings": int(_number(night.get("awakenings")) or 0),
            **bed,
        },
        "stages": stages,
        "environment": environment,
        "environment_assessment": environment_assessment,
        "findings": findings,
        "post_session_guidance": post_session_guidance,
        "data_quality": {
            "level": data_level,
            "label": data_label,
            "coverage": coverage,
            "confidence_pct": confidence_pct,
            "note": "BCG กำหนด Sleep Stage; เสียง/Bed Status ใช้ยืนยันเหตุรบกวน; Sensor อากาศเป็นบริบทเท่านั้น",
        },
        "disclaimer": (
            "ผล Wake/N1/N2/N3/REM เป็นค่าประเมินเชิงแนวโน้มจาก BCG ไม่ใช่ผล AASM/PSG "
            "และสภาพแวดล้อมไม่ถูกใช้กำหนด Sleep Stage โดยตรง"
        ),
    }
