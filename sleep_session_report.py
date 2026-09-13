"""Explainable post-session report for the ZEEP Pod.

The report intentionally keeps three concerns separate:

1. Sleep results come from the versioned BCG sleep-state estimator.
2. SPH0645 and Bed Status may corroborate a disturbance.
3. Pod environment values never determine Wake/N1/N2/N3/REM. They explain
   possible disturbance in Overnight and contribute a bounded 10 points to
   the separate Nap & Refresh Recovery Score.

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
    ENVIRONMENT_SESSION_AGGREGATION_VERSION,
    NAP_RECOVERY_LEGACY_HARD_MAX_SECONDS,
    NAP_RECOVERY_MINIMUM_SCORE_SECONDS,
    OVERNIGHT_ARCHITECTURE_MAX_POINTS,
    OVERNIGHT_N2_FULL_CREDIT_PCT,
    OVERNIGHT_N3_FULL_CREDIT_FROM_PCT,
    OVERNIGHT_N3_ZERO_BELOW_PCT,
    OVERNIGHT_REM_FULL_CREDIT_PCT,
    RECOVERY_SCORE_COMPONENT_MAX_POINTS,
    RECOVERY_SCORE_FORMULA_VERSION,
    REST_MODE_DURATION_TARGETS_S,
    REST_MODE_LEGACY_ALIASES,
    REST_MODE_PROTOCOLS,
    REST_SESSION_GROUPS,
    SESSION_REPORT_VERSION,
    SLEEP_QUALITY_COMPONENT_MAX_POINTS,
    SLEEP_QUALITY_VERSION,
    SLEEP_SCORE_FORMULA_VERSION,
    ZEEP_OFF_BED_DATA_STATUSES,
    environment_criterion,
    environment_level_for_value,
    environment_policy_snapshot,
    resolve_rest_target,
    summarize_environment_session_levels,
)
from zeep_pod.sessions.environment_safety import (
    safety_limit_text,
    summarize_safety_excursions,
)
from zeep_pod.sessions.respiratory_wellness import (
    build_respiratory_wellness,
)
from zeep_pod.sessions.restore_summary import build_restore_summary
from zeep_pod.sessions.sleep_occupancy import sample_confirms_off_bed

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
    "unknown_legacy": "กำลังระบุรูปแบบการพัก",
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
    "general_rest",
    "nap_recovery",
}

_TARGET_UNSET = object()
CLASSIFICATION_ACCOUNTING_VERSION = "zeep-classification-accounting-v1.1-complete-occupied-epochs"

_RESTART_DISPLAY_STATUSES = {
    "service_restart_hold",
    "restored_confirmed_state",
    "restored_waiting_live_frame",
    "restart_hold",
}
_NO_DATA_STATUSES = {
    "incomplete_current_epoch",
    "incomplete_current_epoch_evidence",
    "invalid_or_missing_current_vitals",
    "invalid_or_missing_current_vitals_or_bcg",
    "invalid_or_missing_vitals",
    "insufficient_paired_vital_coverage",
    "insufficient_vital_coverage",
    "missing_bed_status",
    "missing_current_vitals",
    "missing_vitals",
    "no_data",
    "no_data_unconfirmed_evidence",
    "no_frame",
    "no_session",
    "sensor_gap",
    "sensor_unavailable",
    "stale",
    "unconfirmed_evidence",
    "waiting_for_sensor_frame",
    "waiting_for_vitals",
}
_INITIAL_WAIT_STATUSES = {
    "collecting_evidence_epoch",
    "confirming_initial_state",
    "initial_confirmation_wait",
}


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _row_duration_seconds(
    row: Dict[str, Any],
    fallback_interval_s: float,
) -> float:
    """Return the exact report time owned by one normalized row."""
    value = _number(row.get("sample_interval_s"))
    if value is None or value <= 0:
        value = max(0.1, float(fallback_interval_s))
    return value


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


def _score_eligible_stage_sequence(
    stage_sequence: Optional[Iterable[Any]],
) -> list[Any]:
    """Keep every score-attributed State in sequence-facing score metrics.

    Under the complete occupied-epoch contract, ``provisional`` describes
    confidence in the evidence for a *new* State.  It does not, by itself,
    remove the already-attributed State from Sleep Score.  Only an explicit
    score exclusion may remove a row from arousal/cycle calculations.
    """
    eligible = []
    for item in stage_sequence or []:
        if not isinstance(item, dict):
            eligible.append(item)
            continue
        confirmation = item.get("sleep_confirmation")
        confirmation = confirmation if isinstance(confirmation, dict) else {}
        explicit = item.get("sleep_score_eligible")
        if explicit is None:
            explicit = item.get("score_eligible")
        if explicit is None:
            explicit = confirmation.get("score_eligible")
        excluded = bool(item.get("sleep_excluded_from_score") or item.get("excluded_from_score") or confirmation.get("excluded_from_score"))
        if explicit is False or excluded:
            continue
        eligible.append(item)
    return eligible


def _row_data_status(sample: Dict[str, Any]) -> str:
    """Return the most specific persisted Sleep classification status."""
    confirmation = sample.get("sleep_confirmation")
    confirmation = confirmation if isinstance(confirmation, dict) else {}
    value = sample.get("sleep_data_status") or sample.get("data_status") or confirmation.get("data_status") or confirmation.get("decision_kind") or ""
    return str(value).strip().lower()


def _row_sleep_stage(sample: Dict[str, Any]) -> Optional[str]:
    stage = str(sample.get("sleep") or "").strip().lower()
    if stage not in {*STAGE_ORDER, "nrem_light", "nrem_deep"}:
        return None
    return {"nrem_light": "n2", "nrem_deep": "n3"}.get(stage, stage)


def _paired_vitals_available(sample: Dict[str, Any]) -> bool:
    return bool(filter_vital_values([sample.get("hr")], HR_SANITY_RANGE_BPM) and filter_vital_values([sample.get("rr")], RR_SANITY_RANGE_PER_MIN))


def _row_has_measured_paired_vitals(sample: Dict[str, Any]) -> bool:
    """Accept paired HR/RR only from a measured, occupied BCG row.

    Projected continuity rows can legitimately retain a Sleep State, but they
    are not new physiological evidence.  Likewise, a confirmed OFF BED row or
    an explicitly invalid BCG analysis must never satisfy a score-release
    gate merely because stale HR/RR values remain on the row.
    """
    if sample.get("synthetic_sleep_gap") is True or sample.get("bcg_analysis_valid") is False or sample.get("heart_rate_held") is True or sample.get("respiration_held") is True or sample.get("heart_rate_current_valid") is False or sample.get("respiration_current_valid") is False or sample_confirms_off_bed(sample):
        return False
    explicit_paired = _number(sample.get("_paired_hr_rr_rows"))
    if explicit_paired is not None:
        return explicit_paired > 0
    return _paired_vitals_available(sample)


def _explicitly_excluded_from_score(sample: Dict[str, Any]) -> bool:
    """Return whether persisted decision metadata explicitly excludes a row.

    Operational rows can still contain a valid current HR/RR pair, especially
    when a rolling window loses coverage or a historical status event is
    joined to Timeline.  Those vitals must not make the legacy continuity
    fallback silently score a row that the estimator explicitly withheld.
    """
    confirmation = sample.get("sleep_confirmation")
    confirmation = confirmation if isinstance(confirmation, dict) else {}
    eligible_values = (
        sample.get("sleep_score_eligible"),
        sample.get("score_eligible"),
        confirmation.get("score_eligible"),
    )
    excluded_values = (
        sample.get("sleep_excluded_from_score"),
        sample.get("excluded_from_score"),
        confirmation.get("excluded_from_score"),
    )
    return bool(any(value is False for value in eligible_values) or any(value is True for value in excluded_values))


def _is_no_data_status(status: str) -> bool:
    """Recognise canonical acquisition/gating failures as operational time."""
    return bool(status in _NO_DATA_STATUSES or status.startswith("invalid_or_missing_") or status.startswith("insufficient_") or status.startswith("incomplete_") or status.startswith("missing_") or status.startswith("no_data_"))


def _classification_accounting(
    rows: list[Dict[str, Any]],
    *,
    duration_s: float,
    sample_interval_s: float,
    display_count: float,
    scored_count: float,
) -> Dict[str, Any]:
    """Reconcile every report second to one classification-time category.

    A carried-forward State remains attributed to the last confirmed State
    and is scoreable; an unconfirmed challenger receives no new-State time.
    Missing/stale/restart intervals therefore remain continuous State time at
    low confidence while confirmed OFF BED remains operational and unscored.
    Measured physiological-evidence coverage is calculated separately, so a
    complete State timeline never pretends that missing HR/RR/BCG was observed.

    Older reports may contain Stage totals without row-level labels.  Those
    reports use a clearly identified count fallback rather than inventing
    direct-versus-carry provenance.
    """
    interval = max(0.1, float(sample_interval_s or 0.1))
    recording_s = max(0.0, float(duration_s or 0.0))
    if recording_s <= 0 and rows:
        recording_s = sum(_row_duration_seconds(row, interval) for row in rows)

    categories = {
        "direct_confirmed_s": 0.0,
        "continuity_carried_forward_s": 0.0,
        "initial_wait_s": 0.0,
        "no_data_s": 0.0,
        "off_bed_s": 0.0,
        "restart_display_hold_s": 0.0,
        "sensor_gap_s": 0.0,
    }
    provisional_hold_s = 0.0
    score_eligible_s = 0.0
    has_row_stage = any(_row_sleep_stage(sample) for sample in rows)
    method = "row_level_classification_metadata"
    restart_status_seen = False

    if not has_row_stage and display_count > 0:
        # Legacy Session reports expose aggregate Stage totals but not the
        # per-row decision metadata required to separate direct and carried
        # time. Allocate any explicit operational rows first so a stale
        # aggregate count cannot overwrite NO DATA/OFF BED. Preserve only the
        # non-overlapping remainder as direct-compatible history; never claim
        # that historical carry provenance was observed.
        method = "legacy_stage_count_fallback"
        remaining = recording_s
        explicit = {
            "restart_display_hold_s": 0.0,
            "off_bed_s": 0.0,
            "no_data_s": 0.0,
            "initial_wait_s": 0.0,
        }
        for sample in rows:
            seconds = _row_duration_seconds(sample, interval)
            status = _row_data_status(sample)
            if sample.get("display_only_after_restart") or sample.get("sleep_display_only_after_restart") or status in _RESTART_DISPLAY_STATUSES:
                explicit["restart_display_hold_s"] += seconds
            elif status in ZEEP_OFF_BED_DATA_STATUSES or sample_confirms_off_bed(sample):
                explicit["off_bed_s"] += seconds
            elif status in _INITIAL_WAIT_STATUSES:
                explicit["initial_wait_s"] += seconds
            elif _is_no_data_status(status) or _explicitly_excluded_from_score(sample):
                explicit["no_data_s"] += seconds
        for key in (
            "restart_display_hold_s",
            "off_bed_s",
            "no_data_s",
            "initial_wait_s",
        ):
            allocated = min(remaining, explicit[key])
            categories[key] = allocated
            remaining -= allocated
        restart_status_seen = categories["restart_display_hold_s"] > 0
        categories["direct_confirmed_s"] = min(
            remaining,
            max(0.0, float(display_count)) * interval,
        )
        score_eligible_s = min(
            categories["direct_confirmed_s"],
            max(0.0, float(scored_count)) * interval,
        )
        remaining -= categories["direct_confirmed_s"]
        categories["sensor_gap_s"] = remaining
    else:
        remaining = recording_s
        previous_stage: Optional[str] = None
        for sample in rows:
            if remaining <= 0:
                break
            seconds = min(
                _row_duration_seconds(sample, interval),
                remaining,
            )
            remaining -= seconds
            status = _row_data_status(sample)
            stage = _row_sleep_stage(sample)
            confirmation = sample.get("sleep_confirmation")
            confirmation = confirmation if isinstance(confirmation, dict) else {}
            explicitly_scoreable = bool(sample.get("sleep_score_eligible") is True or sample.get("score_eligible") is True)
            restart_display = bool(sample.get("display_only_after_restart") or sample.get("sleep_display_only_after_restart") or (status in _RESTART_DISPLAY_STATUSES and not explicitly_scoreable))
            if restart_display:
                categories["restart_display_hold_s"] += seconds
                restart_status_seen = True
                continue

            # An operational status takes precedence over a stale/cached Stage
            # label.  Likewise, an explicit score exclusion must be honoured
            # before the compatibility fallback considers valid HR/RR as a
            # carried-forward State.
            if status in ZEEP_OFF_BED_DATA_STATUSES or sample_confirms_off_bed(sample):
                categories["off_bed_s"] += seconds
                continue
            if _is_no_data_status(status):
                categories["no_data_s"] += seconds
                continue

            if stage is not None:
                held = bool(sample.get("sleep_held_previous_state") or confirmation.get("held_previous_state") or confirmation.get("decision_kind") == "continuity_hold" or status in {"continuity_hold", "provisional_hold"})
                key = "continuity_carried_forward_s" if held else "direct_confirmed_s"
                categories[key] += seconds
                provisional = bool(held and (sample.get("sleep_provisional") or confirmation.get("provisional") or status == "provisional_hold"))
                if provisional:
                    provisional_hold_s += seconds
                if not _explicitly_excluded_from_score(sample):
                    score_eligible_s += seconds
                previous_stage = stage
                continue

            if _explicitly_excluded_from_score(sample):
                if status in _INITIAL_WAIT_STATUSES or previous_stage is None:
                    categories["initial_wait_s"] += seconds
                else:
                    categories["no_data_s"] += seconds
                continue
            if not _paired_vitals_available(sample):
                categories["no_data_s"] += seconds
                continue
            if previous_stage is not None:
                # This is the continuity rule itself: valid on-bed evidence
                # after the first confirmed State cannot create a timeline
                # hole merely because the next challenger is not yet clear.
                categories["continuity_carried_forward_s"] += seconds
                provisional = status == "provisional_hold"
                if provisional:
                    provisional_hold_s += seconds
                else:
                    score_eligible_s += seconds
                continue
            if status in _INITIAL_WAIT_STATUSES or previous_stage is None:
                categories["initial_wait_s"] += seconds

        categories["sensor_gap_s"] = max(0.0, remaining)

    classified_s = categories["direct_confirmed_s"] + categories["continuity_carried_forward_s"]
    accounted_s = sum(categories.values())
    display_stage_total_s = max(0.0, float(display_count)) * interval
    score_stage_total_s = max(0.0, float(scored_count)) * interval
    delta_s = accounted_s - recording_s
    rounded = {key: round(value, 1) for key, value in categories.items()}
    return {
        "version": CLASSIFICATION_ACCOUNTING_VERSION,
        "method": method,
        **rounded,
        "provisional_hold_s": round(provisional_hold_s, 1),
        "classified_s": round(classified_s, 1),
        "display_attributed_s": round(classified_s, 1),
        "score_eligible_s": round(score_eligible_s, 1),
        "excluded_from_score_s": round(
            recording_s - score_eligible_s,
            1,
        ),
        "operational_unscored_s": round(accounted_s - classified_s, 1),
        "accounted_s": round(accounted_s, 1),
        "recording_s": round(recording_s, 1),
        "display_stage_total_s": round(display_stage_total_s, 1),
        "display_stage_total_delta_s": round(
            classified_s - display_stage_total_s,
            1,
        ),
        "display_stage_total_reconciles": abs(classified_s - display_stage_total_s) <= 0.11,
        "score_stage_total_s": round(score_stage_total_s, 1),
        "score_stage_total_delta_s": round(
            score_eligible_s - score_stage_total_s,
            1,
        ),
        "score_stage_total_reconciles": abs(score_eligible_s - score_stage_total_s) <= 0.11,
        "restart_display_hold_derived": restart_status_seen,
        "arithmetic_invariant": {
            "expression": ("direct_confirmed_s + continuity_carried_forward_s + initial_wait_s + no_data_s + off_bed_s + restart_display_hold_s + sensor_gap_s = recording_s"),
            "left_s": round(accounted_s, 1),
            "right_s": round(recording_s, 1),
            "delta_s": round(delta_s, 3),
            "holds": abs(delta_s) <= 0.001,
        },
        "challenger_time_before_confirmation_s": 0.0,
        "legacy_carry_provenance_available": method != ("legacy_stage_count_fallback"),
    }


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
    else:
        # Historical ``auto`` means the user goal was never persisted. Elapsed
        # time or an estimator output cannot safely choose a product mode, so it
        # remains unresolved until an operator links protocol evidence.
        resolved = "unknown_legacy"
        reason = "ไม่พบรูปแบบการพักที่เลือกไว้ จึงไม่อนุมานจากระยะเวลาหรือ Sleep State"
    if requested_mode in REST_SESSION_GROUPS:
        group = requested_mode
    elif requested_mode in {"auto", "unknown_legacy"}:
        group = None
    else:
        group = _SLEEP_MODE_GROUPS.get(resolved, "nap_recovery")
    group_policy = REST_SESSION_GROUPS.get(
        group,
        {
            "label": "พักผ่อนทั่วไป",
            "score_title": "คะแนนการพัก",
            "score_scope": "ค่าประเมินการพักจาก Sensor",
            "description": "พักใน ZEEP ตามข้อมูลที่บันทึกได้",
        },
    )
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
        "protocol": (dict(REST_MODE_PROTOCOLS[group]) if group in REST_MODE_PROTOCOLS else None),
    }


def _protocol_status(
    mode: Dict[str, Any],
    observed_s: float,
    target: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
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
    if group == "nap_recovery":
        return _nap_protocol_status(observed, target or {})
    minimum = _number(protocol.get("minimum_seconds"))
    maximum = _number(protocol.get("maximum_seconds"))
    recommended = protocol.get("recommended_range_seconds") or []
    recommended_low = _number(recommended[0]) if len(recommended) > 0 else None
    recommended_high = _number(recommended[1]) if len(recommended) > 1 else None
    below_minimum = minimum is not None and observed < minimum
    above_maximum = maximum is not None and observed > maximum
    in_recommended = recommended_low is not None and recommended_high is not None and recommended_low <= observed <= recommended_high
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
        "review_required": False,
        "score_releasable": True,
    }


def _nap_protocol_status(
    observed_s: float,
    target: Dict[str, Any],
) -> Dict[str, Any]:
    """Classify Nap timing without guessing a missing 30/90-minute target."""
    observed = max(0.0, observed_s)
    common = {
        "available": True,
        "canonical_mode": "nap_recovery",
        "observed_seconds": round(observed, 1),
        "minimum_score_seconds": NAP_RECOVERY_MINIMUM_SCORE_SECONDS,
        "legacy_hard_max_seconds": NAP_RECOVERY_LEGACY_HARD_MAX_SECONDS,
        "target": dict(target),
    }
    if observed < NAP_RECOVERY_MINIMUM_SCORE_SECONDS:
        return {
            **common,
            "status": "insufficient",
            "within_operational_window": False,
            "within_recommended_range": False,
            "review_required": False,
            "score_releasable": False,
            "reason": "บันทึกไม่ถึง 10 นาที จึงยังไม่ออก Recovery Score",
        }
    if observed > NAP_RECOVERY_LEGACY_HARD_MAX_SECONDS:
        return {
            **common,
            "status": "implausible_outlier",
            "within_operational_window": False,
            "within_recommended_range": False,
            "review_required": True,
            "score_releasable": False,
            "reason": "เกิน 120 นาที ต้องตรวจ Session lifecycle และ Mode",
        }
    if not target.get("available"):
        extended_unknown = observed > 45 * 60
        return {
            **common,
            "status": "target_unknown",
            "display_status": ("TARGET_UNKNOWN/extended" if extended_unknown else "TARGET_UNKNOWN"),
            "observed_timing_band": ("extended_unknown_target" if extended_unknown else "target_unknown"),
            "within_operational_window": None,
            "within_recommended_range": None,
            "review_required": True,
            "score_releasable": False,
            "reason": "Session เดิมไม่ได้เก็บเป้าหมาย 30/90 นาที ห้ามเดาจากเวลาที่ผ่านไป",
        }

    recommended = target.get("recommended_range_seconds") or []
    recommended_low = _number(recommended[0]) if len(recommended) > 0 else None
    recommended_high = _number(recommended[1]) if len(recommended) > 1 else None
    extended_max = _number(target.get("extended_max_seconds"))
    if recommended_low is not None and recommended_high is not None and recommended_low <= observed <= recommended_high:
        status = "recommended"
    elif recommended_low is not None and observed < recommended_low:
        status = "partial"
    elif extended_max is not None and observed <= extended_max:
        status = "extended"
    else:
        status = "out_of_protocol"
    review_required = status == "out_of_protocol"
    return {
        **common,
        "status": status,
        "recommended_range_seconds": list(recommended),
        "extended_max_seconds": extended_max,
        "within_operational_window": not review_required,
        "within_recommended_range": status == "recommended",
        "review_required": review_required,
        "score_releasable": not review_required,
        "reason": ("ระยะเวลาอยู่นอกกรอบของเป้าหมายที่เลือก ต้องตรวจโดยผู้ดูแล" if review_required else None),
    }


def _range_fit(value: float, low: float, high: float, soft_low: float, soft_high: float) -> float:
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
    cv = variance**0.5 / mean
    return max(0.0, min(1.0, 1.0 - cv / max(0.0001, soft_cv)))


def _physiological_evidence_coverage(
    rows: list[Dict[str, Any]],
    *,
    duration_s: float,
    sample_interval_s: float,
) -> Dict[str, Any]:
    """Measure real paired HR/RR time without counting projected gap rows.

    Sleep-State attribution may intentionally cover an occupied wall-clock gap
    by carrying the last confirmed State.  That continuity is useful for the
    timeline, but it is not newly observed physiology.  Keep both denominators
    explicit so a complete State timeline cannot masquerade as complete Sensor
    evidence.
    """
    source_samples = 0
    paired_samples = 0
    evidence_seconds = 0.0
    fallback_interval = max(0.1, float(sample_interval_s or 0.1))
    for row in rows:
        source_count = max(1, int(_number(row.get("_source_rows")) or 1))
        explicit_paired = _number(row.get("_paired_hr_rr_rows"))
        if explicit_paired is not None:
            paired_count = max(0, min(source_count, int(explicit_paired))) if _row_has_measured_paired_vitals(row) else 0
        else:
            paired_count = source_count * int(_row_has_measured_paired_vitals(row))
        source_samples += source_count
        paired_samples += paired_count

        row_interval = max(
            0.0,
            _number(row.get("sample_interval_s")) or fallback_interval,
        )
        evidence_seconds += row_interval * paired_count / source_count

    duration = max(0.0, float(duration_s or 0.0))
    evidence_seconds = min(duration, evidence_seconds)
    return {
        "source_samples": source_samples,
        "paired_samples": paired_samples,
        "paired_ratio": (paired_samples / source_samples if source_samples else 0.0),
        "evidence_seconds": evidence_seconds,
        "evidence_ratio": (evidence_seconds / duration if duration > 0.0 else 0.0),
    }


def _score_confidence(
    timeline_coverage_ratio: float,
    physiological_evidence_ratio: float,
    *,
    paired_vital_ratio: Optional[float] = None,
    state_attribution_ratio: Optional[float] = None,
) -> Dict[str, Any]:
    """Describe score evidence completeness without suppressing the score.

    Session coverage remains visible to Admin QA and already contributes a
    bounded score component.  It must not become a second, hidden veto after
    minimum paired HR/RR evidence has passed.
    """
    evidence_floor = min(
        timeline_coverage_ratio,
        physiological_evidence_ratio,
    )
    attribution_ratio = timeline_coverage_ratio if state_attribution_ratio is None else state_attribution_ratio
    if evidence_floor >= 0.80:
        level, label = "high", "หลักฐานสูง"
    elif evidence_floor >= 0.50:
        level, label = "medium", "หลักฐานปานกลาง"
    else:
        level, label = "low", "หลักฐานจำกัด"
    return {
        "level": level,
        "label": label,
        # Backward-compatible alias: historically this field meant attributed
        # Session time, not direct physiology.
        "session_coverage_pct": round(timeline_coverage_ratio * 100.0, 1),
        "timeline_coverage_pct": round(timeline_coverage_ratio * 100.0, 1),
        "state_attribution_coverage_pct": round(attribution_ratio * 100.0, 1),
        "physiological_evidence_coverage_pct": round(physiological_evidence_ratio * 100.0, 1),
        "paired_hr_rr_coverage_pct": round(
            (physiological_evidence_ratio if paired_vital_ratio is None else paired_vital_ratio) * 100.0,
            1,
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


def _rest_goal_seconds(target: Dict[str, Any]) -> Optional[float]:
    """Return a validated, persisted Recovery target or ``None``."""
    value = _number(target.get("seconds"))
    return max(1.0, value) if target.get("available") and value else None


def _recovery_environment_summary(
    rows: list[Dict[str, Any]],
    rest_mode: str,
) -> Dict[str, Any]:
    """Score available environment values with the canonical policy bands.

    Quality and Sensor coverage intentionally remain separate. Missing channels
    reduce confidence/coverage but do not masquerade as a poor measured value.
    """
    averages: Dict[str, float] = {}
    metrics = []
    for criterion_key, criterion in ENVIRONMENT_CONTEXT_CRITERIA.items():
        sample_key = criterion["sample_key"]
        values = _values(rows, sample_key)
        if not values:
            continue
        average = _average(values) or 0.0
        averages[sample_key] = round(average, 1)
        levels = [environment_level_for_value(criterion_key, value, rest_mode) for value in values]
        aggregate = summarize_environment_session_levels(levels)
        safety = summarize_safety_excursions(values, criterion)
        metrics.append(
            {
                "key": criterion_key,
                "sample_key": sample_key,
                "average": round(average, 1),
                "required_for_overall": bool(criterion.get("required_for_overall", True)),
                "safety_threshold": safety["threshold"],
                "critical_below": safety["critical_below"],
                "critical_above": safety["critical_above"],
                "safety_excursion_observed": safety["excursion_observed"],
                "safety_excursion_sample_count": safety["excursion_sample_count"],
                "safety_excursion_sample_pct": safety["excursion_sample_pct"],
                **aggregate,
            }
        )
    expected = len(ENVIRONMENT_CONTEXT_CRITERIA)
    quality_factor = _average([float(metric["rank"]) / 4.0 for metric in metrics]) if metrics else None
    minimum = min(metrics, key=lambda metric: metric["rank"], default=None)
    required_keys = {key for key, criterion in ENVIRONMENT_CONTEXT_CRITERIA.items() if criterion.get("required_for_overall", True)}
    available_keys = {metric["key"] for metric in metrics}
    missing_required = required_keys - available_keys
    missing_optional = set(ENVIRONMENT_CONTEXT_CRITERIA) - required_keys - available_keys
    safety_excursions = [
        {
            "key": metric["key"],
            "threshold": metric["safety_threshold"],
            "critical_below": metric["critical_below"],
            "critical_above": metric["critical_above"],
            "sample_count": metric["safety_excursion_sample_count"],
            "sample_pct": metric["safety_excursion_sample_pct"],
        }
        for metric in metrics
        if metric["safety_excursion_observed"]
    ]
    return {
        "available": bool(metrics),
        "averages": averages,
        "metrics": metrics,
        "quality_factor": (round(quality_factor, 3) if quality_factor is not None else None),
        "coverage_pct": round(100.0 * len(metrics) / expected, 1),
        "available_factors": len(metrics),
        "expected_factors": expected,
        "policy_version": ENVIRONMENT_CONTEXT_POLICY_VERSION,
        "aggregation_version": ENVIRONMENT_SESSION_AGGREGATION_VERSION,
        "overall_level": (minimum.get("status_key") if minimum else "unknown"),
        "overall_label": (ENVIRONMENT_LEVELS[minimum["status_key"]]["label"] if minimum else "รอข้อมูล"),
        "meets_expected": bool(minimum and not missing_required and minimum["rank"] >= ENVIRONMENT_LEVELS[ENVIRONMENT_ACCEPTABLE_MIN_LEVEL]["rank"]),
        "context_only": False,
        "sleep_stage_context_only": True,
        "contributes_to_primary_score": True,
        "primary_score": "Recovery Score",
        "max_points": 10.0,
        "assessment_quality": ("incomplete_required" if missing_required else "degraded_optional" if missing_optional else "complete"),
        "blocking_unavailable_count": len(missing_required),
        "optional_unavailable_count": len(missing_optional),
        "safety_excursion_observed": bool(safety_excursions),
        "safety_review_required": bool(safety_excursions),
        "safety_excursions": safety_excursions,
        "safety_excursions_change_score": False,
    }


def _row_has_recovery_presence(row: Dict[str, Any]) -> bool:
    """Return whether one row belongs to the user's Recovery exposure.

    A complete projected W/N1/N2/N3/REM row is occupied time even when its
    physiology is carried through a Sensor gap.  Legacy rows may instead use
    affirmative Bed Status or a sane HR/RR pair.  A raw vendor Bed label never
    overrides a projected State; only canonical confirmed OFF BED does.
    """
    if sample_confirms_off_bed(row):
        return False
    if _row_sleep_stage(row) is not None:
        return True
    bed = str(row.get("bed") or row.get("bed_status") or "").strip().casefold()
    if bed in {"on bed", "moving", "weak breathing", "snoring"}:
        return True
    return _paired_vitals_available(row)


def _recovery_presence_rows(
    rows: list[Dict[str, Any]],
) -> list[Dict[str, Any]]:
    """Select rows that may contribute to the Recovery experience score."""
    return [row for row in rows if _row_has_recovery_presence(row)]


def _confirmed_exit_summary(
    rows: list[Dict[str, Any]],
) -> Dict[str, int]:
    """Count canonical OFF BED bouts and retain raw-only labels as QA."""
    event_count = 0
    confirmed_samples = 0
    transient_samples = 0
    in_exit = False
    for row in rows:
        confirmed = sample_confirms_off_bed(row)
        if confirmed:
            confirmed_samples += 1
            if not in_exit:
                event_count += 1
            in_exit = True
            continue
        in_exit = False
        bed = str(row.get("bed") or row.get("bed_status") or "").strip().casefold()
        if bed in {"get out of bed", "off bed", "off_bed", "empty bed"}:
            transient_samples += 1
    return {
        "event_count": event_count,
        "confirmed_samples": confirmed_samples,
        "transient_samples": transient_samples,
    }


def _eligible_rest_seconds(
    rows: list[Dict[str, Any]],
    interval: float,
    duration: float,
) -> float:
    """Count all attributed rest time except confirmed OFF BED.

    Nap & Refresh may be quiet wakefulness, so sleep stages are deliberately
    not required. Under the complete occupied-epoch contract, a projected
    W/N1/N2/N3/REM row remains eligible through a Sensor/restart gap because
    the gap carries the preceding occupied State at low confidence. A raw
    Bed Status label alone cannot remove that time; only canonical confirmed
    OFF BED does. Legacy rows may still use affirmative Bed Status or paired
    HR/RR as their occupancy fallback.
    """
    eligible_seconds = sum(_row_duration_seconds(row, interval) for row in rows if _row_has_recovery_presence(row))
    return min(max(0.0, duration), eligible_seconds)


def _build_awake_rest_quality(
    duration: float,
    mode: Dict[str, Any],
    counts: Dict[str, float],
    rows: list[Dict[str, Any]],
    interval: float,
) -> Dict[str, Any]:
    """Score an awake wellness Session without inventing sleep architecture.

    The score reflects goal duration, coarse HR/RR settling, bed stillness and
    environment support. Coverage is reported independently as QA/confidence
    and contributes zero points. Air Sensor values contribute only to the
    bounded Recovery component and never feed the Sleep State estimator.
    """
    group = mode.get("group") or mode.get("resolved") or "general_rest"
    policy = REST_SESSION_GROUPS.get(
        group,
        {
            "label": "พักผ่อนทั่วไป",
            "score_title": "คะแนนการพัก",
            "score_scope": "ค่าประเมินการพักจาก Sensor",
            "description": "พักใน ZEEP ตามข้อมูลที่บันทึกได้",
        },
    )
    # Legacy callers may only have aggregate Wake counts.  Without the raw
    # Sensor rows there is no defensible evidence for an awake-rest score, so
    # keep the historical zero instead of awarding duration-only points.
    no_sensor_evidence = not rows
    target = dict(mode.get("target") or {})
    duration_goal_s = _rest_goal_seconds(target)
    presence_rows = _recovery_presence_rows(rows)
    eligible_rest_s = _eligible_rest_seconds(rows, interval, duration)
    duration_factor = min(1.0, eligible_rest_s / duration_goal_s) if duration_goal_s is not None else 0.0
    duration_points = 0.0 if no_sensor_evidence else round(25.0 * duration_factor, 1)

    physiology_rows = [row for row in presence_rows if _row_has_measured_paired_vitals(row)]
    hr = [value for value in _values(physiology_rows, "hr") if 30 <= value <= 220]
    rr = [value for value in _values(physiology_rows, "rr") if 4 <= value <= 60]
    hr_regularity = _regularity(hr, soft_cv=0.12)
    rr_regularity = _regularity(rr, soft_cv=0.18)
    regularity_parts = [value for value in (hr_regularity, rr_regularity) if value is not None]
    settling_parts = [
        value
        for value in (
            _settling(hr, scale=10.0),
            _settling(rr, scale=5.0),
        )
        if value is not None
    ]
    regularity = _average(regularity_parts)
    settling = _average(settling_parts)
    if regularity is None:
        physiology_factor = 0.0
    else:
        # Nap & Refresh accepts quiet wakefulness. Stable HR/RR matters more
        # than forcing heart rate to fall, which meditation does not guarantee.
        physiology_factor = 0.85 * regularity + 0.15 * (settling if settling is not None else 0.5)
    physiology_points = round(35.0 * physiology_factor, 1)

    # A materialised restart/Sensor gap may carry the preceding Sleep State so
    # elapsed rest remains complete, but it must not fabricate extra stillness
    # or repeat a stale ``Moving`` label.  Body-response evidence therefore
    # uses only rows that came from an actual Sensor observation.
    body_rows = [row for row in presence_rows if not row.get("synthetic_sleep_gap")]
    bed_labels = [str(row.get("bed") or row.get("bed_status") or "") for row in body_rows if row.get("bed") or row.get("bed_status")]
    moving = sum(label.strip().casefold() == "moving" for label in bed_labels)
    exit_summary = _confirmed_exit_summary(rows)
    exits = exit_summary["event_count"]
    if bed_labels:
        movement_ratio = moving / len(bed_labels)
        stillness_factor = max(0.0, 1.0 - 1.5 * movement_ratio - 0.15 * exits)
    else:
        movement_ratio = None
        stillness_factor = 0.0
    continuity_points = round(30.0 * stillness_factor, 1)

    # Use the same versioned bands as Dashboard/Session findings. Quality is
    # calculated only from available channels; missing channels are coverage,
    # not a fabricated poor measurement.
    # Environment can explain and support Recovery only while the user has an
    # attributed presence interval. Confirmed OFF BED and materialised Sensor
    # gaps remain visible to Admin QA in the full Session report, but cannot
    # add or remove points from the user's Recovery exposure.
    environment_rows = [row for row in presence_rows if not row.get("synthetic_sleep_gap")]
    environment = _recovery_environment_summary(
        environment_rows,
        "nap_recovery",
    )
    environment_factor = _number(environment.get("quality_factor"))
    environment_points = round(10.0 * environment_factor, 1) if environment_factor is not None else None

    recorded_s = sum(_row_duration_seconds(row, interval) for row in rows)
    state_s = sum(counts.values()) * interval
    state_attribution_ratio = max(
        0.0,
        min(1.0, state_s / max(1.0, duration)),
    )
    recording_coverage_ratio = max(
        0.0,
        min(1.0, recorded_s / max(1.0, duration)),
    )
    evidence_coverage = _physiological_evidence_coverage(
        rows,
        duration_s=duration,
        sample_interval_s=interval,
    )
    source_vital_samples = int(evidence_coverage["source_samples"])
    paired_vital_samples = int(evidence_coverage["paired_samples"])
    paired_vital_ratio = float(evidence_coverage["paired_ratio"])
    physiological_evidence_ratio = float(evidence_coverage["evidence_ratio"])
    component_points = {
        "goal_duration": duration_points,
        "physiological_response": physiology_points,
        "rest_continuity": continuity_points,
        "environment_support": environment_points,
    }
    component_max = dict(RECOVERY_SCORE_COMPONENT_MAX_POINTS)
    scored_components = [key for key, points in component_points.items() if points is not None]
    scored_max = sum(component_max[key] for key in scored_components)
    earned = round(sum(component_points[key] for key in scored_components), 1)
    normalized_unrounded = 100.0 * earned / max(1.0, scored_max)
    score = max(0, min(100, int(round(normalized_unrounded))))
    if score >= 85:
        level, level_key = "ดีมาก", "very_good"
    elif score >= 70:
        level, level_key = "ดี", "good"
    elif score >= 55:
        level, level_key = "ปานกลาง", "fair"
    else:
        level, level_key = "ยังมีจุดที่ปรับได้", "low"

    lowest = min(
        scored_components,
        key=lambda key: component_points[key] / max(1.0, component_max[key]),
    )
    insights = {
        "goal_duration": "เวลาพักครั้งนี้ยังสั้นกว่าเป้าหมายที่เลือก",
        "physiological_response": ("ชีพจรหรือการหายใจเปลี่ยนแปลงในบางช่วงระหว่างพัก"),
        "rest_continuity": "มีการเคลื่อนไหวหรือลุกจากเตียงระหว่างพัก",
        "environment_support": ("สภาพแวดล้อมบางส่วนยังปรับให้สบายขึ้นได้"),
    }
    sleep_s = sum(counts[stage] for stage in SLEEP_STAGES) * interval
    protocol_status = dict(mode.get("protocol_status") or {})
    evidence_available = bool(not no_sensor_evidence and paired_vital_samples >= 6 and hr_regularity is not None and rr_regularity is not None)
    timing_releasable = bool(protocol_status.get("score_releasable"))
    eligible_duration_releasable = eligible_rest_s >= NAP_RECOVERY_MINIMUM_SCORE_SECONDS
    score_available = bool(evidence_available and timing_releasable and eligible_duration_releasable)
    score_confidence = _score_confidence(
        recording_coverage_ratio,
        physiological_evidence_ratio,
        paired_vital_ratio=paired_vital_ratio,
        state_attribution_ratio=state_attribution_ratio,
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
            "state_attribution_coverage_pct": round(state_attribution_ratio * 100.0, 1),
            "physiological_evidence_coverage_pct": round(physiological_evidence_ratio * 100.0, 1),
            "minimum_session_seconds": NAP_RECOVERY_MINIMUM_SCORE_SECONDS,
            "eligible_rest_seconds": round(eligible_rest_s, 1),
            "eligible_duration_releasable": eligible_duration_releasable,
            "timing_status": protocol_status.get("status"),
            "timing_releasable": timing_releasable,
            "review_required": bool(protocol_status.get("review_required")),
            "passed": score_available,
        },
        "reason": (None if score_available else protocol_status.get("reason") or ("เวลาพักที่ยืนยันได้ยังไม่ถึง 10 นาที จึงยังไม่ออก Recovery Score" if not eligible_duration_releasable else None) or "ข้อมูล HR/RR ที่จับคู่กันยังไม่พอสำหรับคำนวณ Recovery Score"),
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
            "protocol_status": protocol_status,
        },
        "duration_target": {
            **target,
            "seconds": round(duration_goal_s, 1) if duration_goal_s else None,
            "target_minutes": (round(duration_goal_s / 60.0, 1) if duration_goal_s else None),
            "recommended_range_minutes": [round(value / 60.0, 1) for value in target.get("recommended_range_seconds", [])],
            "eligible_rest_seconds": round(eligible_rest_s, 1),
            "eligible_rest_minutes": round(eligible_rest_s / 60.0, 1),
            "completion_pct": round(100.0 * duration_factor, 1),
            "basis": (f"เป้าหมาย {target.get('label') or policy['label']}; นับทุก State attribution ที่ไม่ใช่ confirmed OFF BED; Continuity แสดง confidence แยกและไม่หักเมื่อพักเกินเป้าหมาย"),
        },
        "physiology": {
            "available": hr_regularity is not None and rr_regularity is not None,
            "heart_rate_average": round(_average(hr), 1) if hr else None,
            "respiration_average": round(_average(rr), 1) if rr else None,
            "regularity_factor": round(regularity, 3) if regularity is not None else None,
            "heart_rate_regularity_factor": (round(hr_regularity, 3) if hr_regularity is not None else None),
            "respiration_regularity_factor": (round(rr_regularity, 3) if rr_regularity is not None else None),
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
            "transient_bed_exit_samples": (exit_summary["transient_samples"] if bed_labels else None),
        },
        "environment_support": {
            **environment,
            "points": environment_points,
            "max_points": 10.0,
        },
        "data_coverage": {
            "ratio": round(physiological_evidence_ratio, 3),
            "pct": round(physiological_evidence_ratio * 100.0, 1),
            "physiological_evidence_ratio": round(physiological_evidence_ratio, 3),
            "physiological_evidence_pct": round(physiological_evidence_ratio * 100.0, 1),
            "state_attribution_ratio": round(state_attribution_ratio, 3),
            "state_attribution_pct": round(state_attribution_ratio * 100.0, 1),
            "recording_ratio": round(recording_coverage_ratio, 3),
            "recording_pct": round(recording_coverage_ratio * 100.0, 1),
            "paired_hr_rr_pct": round(paired_vital_ratio * 100.0, 1),
            "score_component": False,
            "environment_pct": environment["coverage_pct"],
            "basis": ("Physiological evidence นับเฉพาะเวลาที่มี HR/RR คู่จริง; State attribution แสดงแยกและอาจรวม continuity carry"),
        },
        "component_points": component_points,
        "component_max_points": component_max,
        "component_order": list(component_points),
        "component_labels": {
            "goal_duration": "เวลาพักตามเป้าหมาย",
            "physiological_response": "การตอบสนองของร่างกาย",
            "rest_continuity": "ความต่อเนื่องในการพัก",
            "environment_support": "สภาพแวดล้อมสนับสนุน",
        },
        "formula_version": RECOVERY_SCORE_FORMULA_VERSION,
        "raw_component_points": earned,
        "score_unrounded": round(normalized_unrounded, 1),
        "scored_max_points": scored_max,
        "score_normalized_for_available_components": scored_max < 100.0,
        "score_basis": ("เวลาพักตามเป้าหมาย 25 + การตอบสนอง HR/RR 35 + ความต่อเนื่อง 30 + สภาพแวดล้อม 10; Coverage แสดงแยกและไม่ให้คะแนน"),
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
    ideal_s, ceiling_s = (10 * 60, 30 * 60) if mode == "short_nap" else (20 * 60, 60 * 60)
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
        n3_points = OVERNIGHT_ARCHITECTURE_MAX_POINTS["n3"] * pct["n3"] / OVERNIGHT_N3_FULL_CREDIT_FROM_PCT
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
    sleep_run_s = 0.0
    quiet_run_s = quiet_gap_s
    active = False
    episodes = 0
    evidence_windows = 0
    available_windows = 0
    sleep_seconds = 0.0

    for raw in stage_sequence or []:
        if isinstance(raw, dict):
            row_duration = _row_duration_seconds(raw, interval)
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
            row_duration = interval
        stage = {"nrem_light": "n2", "nrem_deep": "n3"}.get(str(stage), str(stage))
        prior_sleep_duration = sleep_run_s
        if stage in SLEEP_STAGES:
            sleep_run_s += row_duration
            sleep_seconds += row_duration
        else:
            sleep_run_s = 0.0
        if not available:
            continue
        available_windows += 1
        flag = bool((shift is not None and shift >= shift_threshold) or (movement is not None and movement >= movement_threshold) or bed_status.casefold() == "get out of bed")
        if flag:
            evidence_windows += 1
            if prior_sleep_duration >= prior_sleep_s and (not active or quiet_run_s >= quiet_gap_s):
                episodes += 1
                active = True
            quiet_run_s = 0.0
        elif active:
            quiet_run_s += row_duration

    sleep_hours = sleep_seconds / 3600.0
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
    sequence: list[tuple[str, float]] = []
    aliases = {"nrem_light": "n2", "nrem_deep": "n3"}
    for raw in stage_sequence or []:
        stage = (raw.get("sleep") or raw.get("state")) if isinstance(raw, dict) else raw
        stage = aliases.get(str(stage), str(stage))
        if stage in STAGE_ORDER:
            duration = _row_duration_seconds(raw, sample_interval_s) if isinstance(raw, dict) else sample_interval_s
            sequence.append((stage, duration))
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
    for stage, duration in sequence:
        if stage in {"n1", "n2", "n3"}:
            nrem_s += duration
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
    target_duration_s: Any = _TARGET_UNSET,
    score_state_counts: Optional[Dict[str, Any]] = None,
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
        "score_releasable": False,
        "level": "กำลังเตรียมผลสรุป",
        "level_key": "unavailable",
        "reason": ("คะแนนจะแสดงเมื่อจบการพัก" if not completed else "ZEEP กำลังรวบรวมข้อมูลสำหรับสรุปผลการพักครั้งนี้"),
        "version": SLEEP_QUALITY_VERSION,
        "score_title": (REST_SESSION_GROUPS.get(requested_mode, {}).get("score_title") or "คุณภาพการพัก"),
    }
    duration = _number(duration_s)
    if not completed or duration is None or duration <= 0:
        return unavailable

    night = dict(night_summary or {})
    counts = _normalise_stage_counts(score_state_counts if score_state_counts is not None else sleep_state_counts)
    total_sleep_samples = sum(counts[stage] for stage in SLEEP_STAGES)
    total_scored_samples = total_sleep_samples + counts["wake"]
    interval = max(0.1, _number(sample_interval_s) or 5.0)
    actual_scored_s = total_scored_samples * interval
    estimated_sleep_s = total_sleep_samples * interval
    rows = list(sensor_samples or [])
    score_stage_sequence = _score_eligible_stage_sequence(stage_sequence)
    state_attribution_ratio = max(
        0.0,
        min(1.0, actual_scored_s / max(1.0, duration)),
    )
    evidence_coverage = _physiological_evidence_coverage(
        rows,
        duration_s=duration,
        sample_interval_s=interval,
    )
    source_vital_rows = int(evidence_coverage["source_samples"])
    paired_vital_rows = int(evidence_coverage["paired_samples"])
    paired_vital_ratio = float(evidence_coverage["paired_ratio"])
    physiological_evidence_ratio = float(evidence_coverage["evidence_ratio"])
    mode = _resolve_rest_mode(rest_mode, actual_scored_s, estimated_sleep_s)
    target = resolve_rest_target(
        rest_mode,
        None if target_duration_s is _TARGET_UNSET else target_duration_s,
        use_mode_default=target_duration_s is _TARGET_UNSET,
    )
    mode["target"] = target
    mode["protocol_status"] = _protocol_status(mode, duration, target)
    if mode.get("group") is None:
        return {
            **unavailable,
            "reason": ("ไม่พบรูปแบบการพักที่เลือกไว้ จึงไม่อนุมาน Sleep Score หรือ Recovery Score จากระยะเวลา"),
            "rest_mode": mode,
            "review_required": True,
            "validation_status": "legacy_mode_unresolved",
        }
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
    sleep_pct = {stage: (counts[stage] / total_sleep_samples if total_sleep_samples else 0.0) for stage in SLEEP_STAGES}

    # 1) Sleep opportunity + onset — 20 points. Duration contributes 15 instead
    # of the old 40, so a partly recorded but physiologically stable sleep is not
    # overwhelmed by one duration term. The AASM/SRS 7-hour threshold applies
    # only to overnight/main-sleep mode.
    duration_target = _duration_target(mode["resolved"], actual_scored_s)
    duration_points = round(15.0 * min(1.0, estimated_sleep_s / max(1.0, duration_target["seconds"])), 1)
    latency = _latency_points(mode["resolved"], night.get("sleep_onset_proxy_s"))
    opportunity_points = round(duration_points + latency["points"], 1)

    # 2) Stability — 30 points: efficiency 20 + continuity 10. BCG disturbance
    # episodes can remove at most five points and are explicitly not EEG arousal.
    efficiency_points = round(20.0 * efficiency, 1)
    wake_pct = counts["wake"] * 100.0 / total_scored_samples
    wake_points = 10.0 if wake_pct <= 10.0 else max(0.0, 10.0 - (wake_pct - 10.0))
    arousal = analyse_arousal_proxy(
        score_stage_sequence,
        sample_interval_s=interval,
    )
    balanced_arousal_penalty = round(min(5.0, 0.25 * arousal["index_per_hour"]), 1) if arousal.get("index_per_hour") is not None else 0.0
    continuity_points = round(max(0.0, wake_points - balanced_arousal_penalty), 1)
    stability_points = round(efficiency_points + continuity_points, 1)

    # 3) Restorative architecture — 30 points. Conservative N2/N3/REM bands
    # apply only to overnight; short-rest modes never require N3 or REM.
    architecture = (
        _balanced_architecture_points(mode["resolved"], sleep_pct)
        if total_sleep_samples
        else {
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
    cycles = analyse_sleep_cycles(
        score_stage_sequence,
        sample_interval_s=interval,
    )
    expected_cycles = max(1, int((estimated_sleep_s + 45 * 60) // (90 * 60))) if mode["resolved"] == "overnight" and estimated_sleep_s > 0 else 1
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

    # 5) Data coverage — 5 points. Continuity carry can fill the State timeline,
    # but only paired, non-synthetic HR/RR time earns evidence coverage points.
    coverage_points = round(5.0 * physiological_evidence_ratio, 1)

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
    component_labels = (
        {
            "sleep_opportunity": "เวลาและการเข้าสู่การพัก",
            "sleep_stability": "ความต่อเนื่องของการพัก",
            "restorative_architecture": "รูปแบบการพักที่ตรวจพบ",
            "cycle_expression": "การตอบสนองระหว่างพัก",
            "data_coverage": "ความครบของข้อมูล",
        }
        if nap_mode
        else {
            "sleep_opportunity": "หลับไวและเวลาพัก",
            "sleep_stability": "หลับดีและต่อเนื่อง",
            "restorative_architecture": "โครงสร้าง N2/N3/REM",
            "cycle_expression": "รอบการนอนที่ตรวจพบ",
            "data_coverage": "ความครบของข้อมูล",
        }
    )
    earned_points = round(sum(component_points.values()), 1)
    score = 0 if estimated_sleep_s <= 0 else max(0, min(100, int(round(earned_points))))

    if score >= 85:
        level, level_key = "ดีมาก", "very_good"
    elif score >= 70:
        level, level_key = "ดี", "good"
    elif score >= 55:
        level, level_key = "ปานกลาง", "fair"
    else:
        level, level_key = "ยังมีจุดที่ปรับได้", "low"

    if nap_mode:
        if latency["available"] and latency["points"] < 3.0:
            insight = "ร่างกายใช้เวลาสักพักจึงเริ่มผ่อนลง ครั้งถัดไปลองเพิ่มช่วงเตรียมตัวอีกนิด"
        elif duration_points < 10.5:
            insight = "เวลาพักครั้งนี้ยังสั้นกว่าเป้าหมาย Nap & Refresh"
        elif stability_points < 21.0:
            insight = "การพักต่อเนื่องได้เป็นบางช่วง"
        elif architecture["total"] < 18.0:
            insight = "รูปแบบการพักเปลี่ยนแปลงในบางช่วง ลองดูร่วมกับความรู้สึกหลังพัก"
        elif cycle_points < 9.0:
            insight = "การตอบสนองของร่างกายเปลี่ยนแปลงในบางช่วง"
        else:
            insight = "เวลา ความต่อเนื่อง และการตอบสนองระหว่างพักโดยรวมอยู่ในเกณฑ์ดี"
    elif latency["available"] and latency["points"] < 3.0:
        insight = "ร่างกายใช้เวลาสักพักจึงเข้าสู่การนอน ครั้งถัดไปลองเพิ่มช่วงผ่อนคลายก่อนนอน"
    elif duration_points < 10.5:
        insight = f"เวลาหลับยังต่ำกว่าเป้าหมายของ {mode['label']}"
    elif stability_points < 21.0:
        insight = "การนอนขาดช่วงมากกว่าคืนที่พักต่อเนื่อง"
    elif continuity_points < 7.0:
        insight = "พบช่วงตื่นหรือการเคลื่อนไหวหลายครั้งระหว่างการนอน"
    elif architecture["total"] < 18.0:
        insight = f"รูปแบบการนอนที่ประเมินได้ของ {mode['label']} ต่างจากช่วงเป้าหมายบางส่วน"
    elif cycle_points < 9.0:
        insight = "รอบการนอนที่ตรวจพบยังไม่เต็มตามโอกาสการพักครั้งนี้"
    else:
        insight = f"ภาพรวมเวลา ความต่อเนื่อง และรูปแบบการนอนของ {mode['label']} อยู่ในระดับดี"

    score_available = bool(estimated_sleep_s > 0 and paired_vital_rows >= 6)
    score_confidence = _score_confidence(
        state_attribution_ratio,
        physiological_evidence_ratio,
        paired_vital_ratio=paired_vital_ratio,
        state_attribution_ratio=state_attribution_ratio,
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
            "state_attribution_coverage_pct": round(state_attribution_ratio * 100.0, 1),
            "physiological_evidence_coverage_pct": round(physiological_evidence_ratio * 100.0, 1),
            "passed": score_available,
        },
        "reason": (None if score_available else "ยังไม่พบ Sleep State หรือข้อมูล HR/RR ที่จับคู่กันไม่พอสำหรับคำนวณ Sleep Score"),
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
        "stage_pct_of_sleep": {stage: round(sleep_pct[stage] * 100.0, 1) for stage in ("n1", "n2", "n3", "rem")},
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
            "ratio": round(physiological_evidence_ratio, 3),
            "pct": round(physiological_evidence_ratio * 100.0, 1),
            "physiological_evidence_ratio": round(physiological_evidence_ratio, 3),
            "physiological_evidence_pct": round(physiological_evidence_ratio * 100.0, 1),
            "state_attribution_ratio": round(state_attribution_ratio, 3),
            "state_attribution_pct": round(state_attribution_ratio * 100.0, 1),
            "paired_hr_rr_pct": round(paired_vital_ratio * 100.0, 1),
            "points": coverage_points,
            "max_points": 5.0,
            "basis": ("คะแนนความครบของข้อมูลใช้เวลาที่มี HR/RR คู่จริง; State attribution แสดงแยกและอาจรวม continuity carry"),
        },
        "cycles": cycles,
        "component_points": component_points,
        "component_max_points": component_max,
        "component_order": component_order,
        "component_labels": component_labels,
        "score_unrounded": earned_points,
        "score_basis": ("เวลา/การเข้าสู่การพัก 20 + ความต่อเนื่อง 30 + รูปแบบการพัก 30 + การตอบสนอง 15 + ข้อมูล 5" if nap_mode else "หลับไว/เวลาพัก 20 + หลับต่อเนื่อง 30 + ฟื้นฟู 30 + รอบการนอน 15 + ข้อมูล 5"),
        "formula_version": SLEEP_SCORE_FORMULA_VERSION,
        "version": SLEEP_QUALITY_VERSION,
        "outcome_interpretation": ("Nap & Refresh ไม่บังคับ N3/REM; Recovery Score สะท้อนสัญญาณสนับสนุนการฟื้นตัว และต้องอ่านร่วมกับคำตอบก่อน–หลัง Session" if nap_mode else "ความสดชื่นหลังตื่นต้องใช้คำตอบหลัง Session ประกอบ"),
        "disclaimer": (f"{mode.get('score_title') or 'Sleep Score'} เป็นการประเมิน ZEEP Wellness จาก BCG/Sensor ไม่ใช่ PSG หรือผลวินิจฉัย"),
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
        primary = "ผล Sensor ยังไม่ครบพอสำหรับสรุปคะแนน ให้ใช้ความรู้สึกหลังพักประกอบก่อนทำกิจกรรมถัดไป"
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
            item.get("action")
            for item in findings
            if item.get("decision")
            in {
                "required",
                "optimise",
                "sensor_check",
                "safety_review",
            }
            and item.get("action")
        ),
        None,
    )
    next_session = f"ครั้งถัดไป: {environment_action}" if environment_action else "ครั้งถัดไป: รักษาการตั้งค่าที่สบายและตอบแบบประเมินหลังพักเพื่อเพิ่มบริบทส่วนบุคคล"
    return {
        "primary": primary,
        "next_session": next_session,
        "self_check": ("ก่อนขับรถ ใช้เครื่องจักร หรือทำกิจกรรมเสี่ยง ให้ยึดความตื่นตัวจริงของตนเอง ไม่ใช้คะแนนแทนการตัดสินใจ"),
        "mode": group,
        "score_used": int(score) if released else None,
        "score_released": released,
        "basis": ("ZEEP Wellness & Longevity · Sensor + เป้าหมายการพัก + สภาพแวดล้อม; ควรอ่านร่วมกับ self-report หลังพัก"),
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
    safety = summarize_safety_excursions(values, criterion)
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
            "required_for_overall": bool(criterion.get("required_for_overall", True)),
            "safety_threshold": safety["threshold"],
            "critical_below": safety["critical_below"],
            "critical_above": safety["critical_above"],
            "safety_excursion_observed": False,
            "safety_excursion_sample_count": 0,
            "safety_excursion_sample_pct": 0,
        }
    levels = [environment_level_for_value(criterion_key, value, rest_mode) for value in values]
    aggregate = summarize_environment_session_levels(levels)
    level_counts = aggregate["level_counts"]
    status_key = aggregate["status_key"]
    level = ENVIRONMENT_LEVELS[status_key]
    outside_pct = _percent(
        sum(level_counts[name] for name in ("critical", "poor", "fair", "good")),
        len(values),
    )
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
        "required_for_overall": bool(criterion.get("required_for_overall", True)),
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
        "level_distribution_pct": {name: _percent(count, len(values)) for name, count in level_counts.items()},
        "aggregation_version": aggregate["version"],
        "aggregation_method": aggregate["method"],
        "peak_status_key": aggregate["peak_status_key"],
        "critical_sample_count": aggregate["critical_sample_count"],
        "critical_sample_pct": aggregate["critical_sample_pct"],
        "transient_critical_observed": aggregate["transient_critical_observed"],
        "safety_threshold": safety["threshold"],
        "critical_below": safety["critical_below"],
        "critical_above": safety["critical_above"],
        "safety_excursion_observed": safety["excursion_observed"],
        "safety_excursion_sample_count": safety["excursion_sample_count"],
        "safety_excursion_sample_pct": safety["excursion_sample_pct"],
        "action": (action if level["decision"] in {"required", "optimise"} else "รักษาการตั้งค่าปัจจุบัน"),
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
    target_duration_s: Any = _TARGET_UNSET,
    personal_context: Optional[Dict[str, Any]] = None,
    trend_context: Optional[Dict[str, Any]] = None,
    subjective_outcome: Optional[Dict[str, Any]] = None,
    health_reference: Optional[Dict[str, Any]] = None,
    sleep_score_state_counts: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return the compact, explainable report shown after a Session ends."""
    rows = list(samples or [])
    duration = _number(duration_s) or 0.0
    counts = _normalise_stage_counts(sleep_state_counts)
    score_counts = _normalise_stage_counts(sleep_score_state_counts if sleep_score_state_counts is not None else sleep_state_counts)
    display_count = sum(counts.values())
    scored_count = sum(score_counts.values())
    quality = dict(sleep_quality or {})
    night = dict(night_summary or {})
    stage_percentages = _stage_percentages(counts)
    score_stage_percentages = _stage_percentages(score_counts)
    total_sleep_count = sum(counts[stage] for stage in SLEEP_STAGES)
    total_score_sleep_count = sum(score_counts[stage] for stage in SLEEP_STAGES)

    if not completed:
        return {
            "available": False,
            "reason": "Session ยังไม่สิ้นสุด",
            "version": SESSION_REPORT_VERSION,
        }

    classification_accounting = _classification_accounting(
        rows,
        duration_s=duration,
        sample_interval_s=sample_interval_s,
        display_count=display_count,
        scored_count=scored_count,
    )

    stages = []
    for stage in STAGE_ORDER:
        count = counts[stage]
        score_count = score_counts[stage]
        stages.append(
            {
                "state": stage,
                "samples": int(count),
                "duration_s": round(count * sample_interval_s, 1),
                # pct_scored uses all actual W/N1/N2/N3/REM rounds. pct_sleep
                # excludes W and is provided for sleep-architecture inspection.
                "pct_scored": stage_percentages[stage],
                "pct_sleep": (round(count * 100.0 / total_sleep_count, 1) if stage in SLEEP_STAGES and total_sleep_count else None),
                # Every occupied five-state attribution is scoreable.  Low-
                # confidence continuity remains separately visible in accounting
                # and is excluded only from Personal Baseline learning.
                "score_eligible_samples": int(score_count),
                "score_eligible_duration_s": round(score_count * sample_interval_s, 1),
                "pct_score_eligible": score_stage_percentages[stage],
                "pct_score_eligible_sleep": (
                    round(
                        score_count * 100.0 / total_score_sleep_count,
                        1,
                    )
                    if stage in SLEEP_STAGES and total_score_sleep_count
                    else None
                ),
            }
        )

    estimated_sleep = _number(quality.get("estimated_sleep_s"))
    if estimated_sleep is None:
        estimated_sleep = _number(night.get("estimated_sleep_s"))
    if estimated_sleep is None:
        estimated_sleep = sum(score_counts[stage] for stage in SLEEP_STAGES) * sample_interval_s
    estimated_sleep = max(0.0, min(duration, estimated_sleep)) if duration else max(0.0, estimated_sleep)
    wake_s = counts["wake"] * sample_interval_s
    score_wake_s = score_counts["wake"] * sample_interval_s
    quality_mode = dict(quality.get("rest_mode") or _resolve_rest_mode(rest_mode, scored_count * sample_interval_s, estimated_sleep))
    if target_duration_s is not _TARGET_UNSET:
        quality_mode["target"] = resolve_rest_target(
            rest_mode,
            target_duration_s,
        )
    elif not quality_mode.get("target"):
        quality_mode["target"] = resolve_rest_target(
            rest_mode,
            None,
            use_mode_default=True,
        )
    quality_mode["protocol_status"] = _protocol_status(
        quality_mode,
        duration,
        quality_mode["target"],
    )
    environment_mode = quality_mode.get("group") or quality_mode.get("resolved") or rest_mode
    # ``report.environment`` is the full-Session Sensor QA/context view.  The
    # only environment values allowed to affect Recovery Score live in
    # ``quality.environment_support``, which is scoped to eligible rest rows.
    # Keeping these roles separate prevents confirmed OFF BED measurements
    # from being described as score drivers while retaining Admin visibility.
    report_environment_contributes = False

    waso_seconds = 0.0
    sleep_started = False
    for sample in rows:
        stage = "off_bed" if sample_confirms_off_bed(sample) else _row_sleep_stage(sample) if not _explicitly_excluded_from_score(sample) else None
        if stage in SLEEP_STAGES or stage in {"nrem_light", "nrem_deep"}:
            sleep_started = True
        elif sleep_started and stage in {"wake", "off_bed"}:
            waso_seconds += _row_duration_seconds(
                sample,
                sample_interval_s,
            )

    environment = [_environment_metric(rows, criterion_key=key, rest_mode=environment_mode) for key in ENVIRONMENT_CONTEXT_CRITERIA]

    corroborated_sound_events = sum(bool(sample.get("acoustic_corroborated")) for sample in rows)
    findings = []
    for metric in environment:
        if not metric.get("available"):
            blocks_overall = metric["required_for_overall"]
            legacy_unstored = bool(timeline_schema_version < 4 and metric["key"] in {"pm25", "voc"})
            findings.append(
                {
                    "key": metric["key"],
                    "severity": "unavailable",
                    "level_key": "unavailable",
                    "decision": ("sensor_check" if blocks_overall else "advisory"),
                    "title": (f"{metric['label']} · Timeline รุ่นเดิมไม่ได้บันทึก" if legacy_unstored else f"{metric['label']} · ไม่มีข้อมูล"),
                    "detail": (f"Session นี้ใช้ Timeline schema v{timeline_schema_version}; ขณะนั้นระบบยังไม่เก็บค่าจาก {metric['source']} ลงรายงาน" if legacy_unstored else f"ยังประเมิน {metric['source']} ในโหมดนี้ไม่ได้"),
                    "action": ("ใช้ Session ใหม่หลังอัปเดต Timeline schema v4" if legacy_unstored else f"ตรวจ {metric['source']} และ freshness"),
                    "context_only": True,
                    "sleep_stage_context_only": True,
                    # Recovery normalises its environment component across the
                    # channels that are available. Missing Sensor data therefore
                    # lowers QA/confidence; it is not itself a score penalty.
                    "contributes_to_primary_score": False,
                    "legacy_timeline_not_persisted": legacy_unstored,
                    "blocks_overall": blocks_overall,
                }
            )
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
        findings.append(
            {
                "key": metric["key"],
                "severity": metric["status_key"],
                "level_key": metric["status_key"],
                "decision": decision,
                "title": f"{metric['label']} · {metric['status']}",
                "detail": (
                    f"เฉลี่ย {metric['average']:g}{unit} · ช่วง "
                    f"{metric['minimum']:g}–{metric['maximum']:g}{unit} · " + (f"ต่ำกว่าพอใช้ {metric['below_expected_pct']}% · " if metric["below_expected_pct"] else "") + "ผ่านขั้นต่ำ "
                    f"{metric['expected_floor']} · เป้าหมายสูงสุด {metric['target']}" + (" · พบสไปก์ Critical ชั่วคราว; เก็บค่าสูงสุดไว้ตรวจ แต่ไม่ใช้สไปก์เดียวตัดสินทั้ง Session" if metric["transient_critical_observed"] else "")
                ),
                "action": action_text,
                "context_only": True,
                "sleep_stage_context_only": True,
                "contributes_to_primary_score": report_environment_contributes,
                "aggregation_version": metric["aggregation_version"],
                "peak_status_key": metric["peak_status_key"],
                "transient_critical_observed": metric["transient_critical_observed"],
                "blocks_overall": False,
            }
        )
        if metric["safety_excursion_observed"]:
            threshold = metric["safety_threshold"]
            safety_rule = safety_limit_text(metric, unit)
            findings.append(
                {
                    "key": f"{metric['key']}_safety_excursion",
                    "metric_key": metric["key"],
                    "severity": "critical",
                    "level_key": "critical",
                    "decision": "safety_review",
                    "title": f"{metric['label']} · พบ Safety excursion",
                    "detail": (f"พบ {metric['safety_excursion_sample_count']} รอบข้อมูล ({metric['safety_excursion_sample_pct']}%) {safety_rule} · ช่วงที่บันทึก {metric['minimum']:g}–{metric['maximum']:g}{unit} · ระดับรวมทั้ง Session ยังคำนวณด้วยเกณฑ์ sustained"),
                    "action": ("ตรวจ Timeline การเติม/ระบายอากาศและบันทึกการตอบสนอง ของระบบ Safety ก่อนใช้งานครั้งถัดไป"),
                    "context_only": False,
                    "sleep_stage_context_only": True,
                    "contributes_to_primary_score": False,
                    "blocks_overall": False,
                    "changes_sustained_assessment": False,
                    "changes_score": False,
                    "threshold": threshold,
                    "critical_below": metric["critical_below"],
                    "critical_above": metric["critical_above"],
                    "minimum": metric["minimum"],
                    "maximum": metric["maximum"],
                    "sample_count": metric["safety_excursion_sample_count"],
                    "sample_pct": metric["safety_excursion_sample_pct"],
                }
            )
    if corroborated_sound_events:
        findings.insert(
            0,
            {
                "key": "acoustic_corroborated",
                "severity": "fair",
                "level_key": "fair",
                "decision": "investigate",
                "title": "พบเสียงตรงกับการตอบสนองจากเตียง",
                "detail": f"SPH0645 และ BCG/Bed Status ตรงกัน {corroborated_sound_events} รอบข้อมูล",
                "action": "ตรวจ Timeline เพื่อหาแหล่งเสียงหรือการสั่นในช่วงเดียวกัน",
                "context_only": False,
                "sleep_stage_context_only": False,
                "contributes_to_primary_score": False,
            },
        )
    findings.sort(
        key=lambda item: {
            "critical": 0,
            "poor": 1,
            "unavailable": 2,
            "fair": 3,
            "good": 4,
            "excellent": 5,
        }.get(item["severity"], 6)
    )
    available_environment = [metric for metric in environment if metric.get("available")]
    unavailable_environment = [metric for metric in environment if not metric.get("available")]
    blocking_unavailable = [metric for metric in unavailable_environment if metric["required_for_overall"]]
    optional_unavailable = [metric for metric in unavailable_environment if not metric["required_for_overall"]]
    minimum_metric = min(
        available_environment,
        key=lambda item: item["rank"],
        default=None,
    )
    required_metrics = [metric for metric in available_environment if metric["decision"] == "required"]
    optimisation_metrics = [metric for metric in available_environment if metric["decision"] == "optimise"]
    safety_excursions = [
        {
            "key": metric["key"],
            "label": metric["label"],
            "threshold": metric["safety_threshold"],
            "critical_below": metric["critical_below"],
            "critical_above": metric["critical_above"],
            "minimum": metric["minimum"],
            "maximum": metric["maximum"],
            "sample_count": metric["safety_excursion_sample_count"],
            "sample_pct": metric["safety_excursion_sample_pct"],
        }
        for metric in available_environment
        if metric["safety_excursion_observed"]
    ]
    environment_assessment = {
        "version": ENVIRONMENT_CONTEXT_POLICY_VERSION,
        "aggregation_version": ENVIRONMENT_SESSION_AGGREGATION_VERSION,
        "aggregation_method": "sustained_lower_decile_of_sample_levels",
        "mode": environment_mode,
        "mode_label": quality_mode.get("label"),
        "acceptable_min_level": ENVIRONMENT_ACCEPTABLE_MIN_LEVEL,
        "acceptable_min_label": ENVIRONMENT_LEVELS[ENVIRONMENT_ACCEPTABLE_MIN_LEVEL]["label"],
        "overall_level": minimum_metric["status_key"] if minimum_metric else "unknown",
        "overall_label": minimum_metric["status"] if minimum_metric else "รอข้อมูล",
        "meets_expected": bool(available_environment and not blocking_unavailable and not required_metrics),
        "required_count": len(required_metrics) + len(blocking_unavailable),
        "advisory_count": len(optional_unavailable),
        "optimisation_count": len(optimisation_metrics),
        "maintain_count": (len(available_environment) - len(required_metrics) - len(optimisation_metrics)),
        "available_count": len(available_environment),
        "expected_count": len(environment),
        "required_expected_count": sum(metric["required_for_overall"] for metric in environment),
        "blocking_unavailable_count": len(blocking_unavailable),
        "optional_unavailable_count": len(optional_unavailable),
        "assessment_quality": ("incomplete_required" if blocking_unavailable else "degraded_optional" if optional_unavailable else "complete"),
        "safety_excursion_observed": bool(safety_excursions),
        "safety_review_required": bool(safety_excursions),
        "safety_excursion_count": sum(item["sample_count"] for item in safety_excursions),
        "safety_excursions": safety_excursions,
        "safety_excursions_change_sustained_assessment": False,
        "safety_excursions_change_score": False,
        "context_only": True,
        "sleep_stage_context_only": True,
        "contributes_to_primary_score": report_environment_contributes,
        "primary_score": None,
        "max_score_points": 0.0,
        "direct_stage_influence": False,
        "safety_thresholds_unchanged": True,
    }

    total_rows = len(rows)
    total_row_seconds = sum(_row_duration_seconds(sample, sample_interval_s) for sample in rows)
    stage_seconds = float(classification_accounting["display_attributed_s"])
    evidence_coverage = _physiological_evidence_coverage(
        rows,
        duration_s=duration,
        sample_interval_s=sample_interval_s,
    )
    environment_coverages = [item["coverage_pct"] for item in environment if item.get("available")]
    recording_coverage = _percent(total_row_seconds, duration) if duration else 0
    state_attribution_coverage = _percent(stage_seconds, duration) if duration else 0
    physiological_evidence_coverage = round(float(evidence_coverage["evidence_ratio"]) * 100.0)
    coverage = {
        "recording_pct": recording_coverage,
        # Compatibility aliases now use direct physiological evidence and
        # explicit State attribution instead of treating carried State as BCG.
        "bcg_pct": physiological_evidence_coverage,
        "sleep_stage_pct": state_attribution_coverage,
        "state_attribution_pct": state_attribution_coverage,
        "physiological_evidence_pct": physiological_evidence_coverage,
        "environment_pct": (round(sum(environment_coverages) / len(environment_coverages)) if environment_coverages else 0),
    }
    confidence_counts = {"high": 0, "medium": 0, "low": 0}
    for sample in rows:
        confidence = sample.get("sleep_confidence")
        if confidence in confidence_counts:
            confidence_counts[confidence] += 1
    confidence_total = sum(confidence_counts.values())
    confidence_pct = {name: _percent(value, confidence_total) for name, value in confidence_counts.items()} if confidence_total else None

    core_coverage = min(
        coverage["recording_pct"],
        coverage["physiological_evidence_pct"],
        coverage["state_attribution_pct"],
    )
    if core_coverage >= 90:
        data_level, data_label = "high", "ความครอบคลุมดี"
    elif core_coverage >= 70:
        data_level, data_label = "medium", "ความครอบคลุมพอใช้"
    else:
        data_level, data_label = "low", "ความครอบคลุมจำกัด"

    bed = _bed_events(rows)
    insight = quality.get("insight") or "สรุปจากข้อมูลที่ระบบบันทึกได้ใน Session นี้"
    post_session_guidance = _post_session_guidance(quality, findings)
    effective_personal_context = personal_context or quality.get("personal_context") or night.get("personal_context")
    effective_trend_context = trend_context or quality.get("trend_context") or night.get("trend_context") or effective_personal_context
    effective_subjective_outcome = subjective_outcome or quality.get("subjective_outcome") or night.get("subjective_outcome")
    effective_health_reference = health_reference or quality.get("health_reference") or night.get("health_reference")
    respiratory_wellness = build_respiratory_wellness(
        rows,
        sample_interval_s=sample_interval_s,
        health_reference=effective_health_reference,
        personal_context=effective_personal_context,
        rest_mode=quality_mode,
    )
    restore_summary = build_restore_summary(
        quality,
        mode=quality_mode,
        findings=findings,
        personal_context=effective_personal_context,
        trend_context=effective_trend_context,
        subjective_outcome=effective_subjective_outcome,
    )
    return {
        "available": bool(duration > 0 and (rows or scored_count)),
        "version": SESSION_REPORT_VERSION,
        "product_positioning": "ZEEP Wellness & Longevity",
        "intended_use": "wellness_sleep_and_recovery_estimation_not_diagnosis",
        "timeline_schema_version": timeline_schema_version,
        "estimator_version": estimator_version,
        "headline": quality.get("level") or ("ข้อมูลพร้อมสรุป" if scored_count else "กำลังเตรียมผลสรุป"),
        "insight": insight,
        "quality": quality,
        "rest_mode": quality_mode,
        "sleep": {
            "recording_s": round(duration, 1),
            "estimated_sleep_s": round(estimated_sleep, 1),
            "wake_s": round(wake_s, 1),
            "score_wake_s": round(score_wake_s, 1),
            "sleep_onset_proxy_s": _number(night.get("sleep_onset_proxy_s")),
            "waso_proxy_s": round(waso_seconds, 1),
            "score_waso_proxy_s": _number(night.get("waso_proxy_s")),
            "sleep_efficiency_pct": quality.get("sleep_efficiency_pct"),
            "actual_scored_s": classification_accounting["score_eligible_s"],
            "direct_confirmed_s": classification_accounting["direct_confirmed_s"],
            "continuity_carried_forward_s": classification_accounting["continuity_carried_forward_s"],
            "initial_wait_s": classification_accounting["initial_wait_s"],
            "no_data_s": classification_accounting["no_data_s"],
            "off_bed_s": classification_accounting["off_bed_s"],
            "restart_display_hold_s": classification_accounting["restart_display_hold_s"],
            "sensor_gap_s": classification_accounting["sensor_gap_s"],
            "provisional_hold_s": classification_accounting["provisional_hold_s"],
            "excluded_from_score_s": classification_accounting["excluded_from_score_s"],
            "classification_accounting": classification_accounting,
            "wake_pct_recorded": stage_percentages["wake"],
            "score_wake_pct": score_stage_percentages["wake"],
            "cycles": quality.get("cycles"),
            # wake_s is total Stage-W duration; wake_entries is the number of
            # sleep -> W transitions. Keep awakenings as a compatibility key.
            "wake_entries": int(_number(night.get("awakenings")) or 0),
            "awakenings": int(_number(night.get("awakenings")) or 0),
            **bed,
        },
        "stages": stages,
        "respiratory_wellness": respiratory_wellness,
        "environment": environment,
        "environment_assessment": environment_assessment,
        "findings": findings,
        "post_session_guidance": post_session_guidance,
        "restore_summary": restore_summary,
        "data_quality": {
            "level": data_level,
            "label": data_label,
            "coverage": coverage,
            "confidence_pct": confidence_pct,
            "note": "BCG กำหนด Sleep Stage; เสียง/Bed Status ใช้ยืนยันเหตุรบกวน; Sensor อากาศเป็นบริบทเท่านั้น",
        },
        "disclaimer": ("ผล Wake/N1/N2/N3/REM เป็นค่าประเมินเชิงแนวโน้มจาก BCG ไม่ใช่ผล AASM/PSG และสภาพแวดล้อมไม่ถูกใช้กำหนด Sleep Stage โดยตรง"),
    }
