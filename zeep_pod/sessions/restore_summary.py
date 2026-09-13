"""Explain one released ZEEP Session score without creating another score.

``Sleep Score`` remains the primary result for Overnight Recovery and
``Recovery Score`` remains the primary result for Nap & Refresh.  This module
adds a versioned presentation layer: actionable status, score drivers,
personal-baseline context and one bounded recommendation.  It is deliberately
pure and never reads a database, changes Sleep State, or controls hardware.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from sleep_system_policy import (
    RECOVERY_SCORE_FORMULA_VERSION,
    RESTORE_ACTION_BANDS_VERSION,
    RESTORE_DRIVER_POLICY_VERSION,
    RESTORE_RECOMMENDATION_VERSION,
    RESTORE_SUMMARY_VERSION,
    SLEEP_SCORE_FORMULA_VERSION,
    rest_mode_group,
)
from zeep_pod.product_language import (
    user_confidence_level,
    user_environment_finding_copy,
)
from zeep_pod.sessions.restore_summary_baseline import (
    build_baseline_summary,
    build_trend_summary,
)
from zeep_pod.sessions.restore_summary_policy import (
    ACTION_BANDS,
    COMPONENT_COPY,
    RECOMMENDATIONS,
    STATUS_MEANINGS,
)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _mode_group(
    quality: Mapping[str, Any],
    mode: Any,
) -> str:
    source = mode if mode is not None else quality.get("rest_mode")
    selected = dict(source) if isinstance(source, Mapping) else {}
    raw_mode = selected.get("group") or selected.get("requested") or selected.get("resolved") or source
    group = rest_mode_group(raw_mode)
    if group == "sleep" or quality.get("quality_type") == "sleep":
        return "sleep"
    if group == "nap_recovery" or quality.get("quality_type") == "rest_goal":
        return "nap_recovery"
    return "unknown"


def _source_score(quality: Mapping[str, Any], group: str) -> dict[str, Any]:
    available = quality.get("available") is True
    score = _number(quality.get("score"))
    if not available or score is None or not 0.0 <= score <= 100.0:
        score = None
    is_sleep = group == "sleep"
    is_recovery = group == "nap_recovery"
    return {
        "type": ("sleep_score" if is_sleep else "recovery_score" if is_recovery else "unresolved_score"),
        "title": ("Sleep Score" if is_sleep else "Recovery Score" if is_recovery else "Session Score"),
        "value": int(round(score)) if score is not None else None,
        "available": bool(score is not None and group != "unknown"),
        "formula_version": (quality.get("formula_version") or (SLEEP_SCORE_FORMULA_VERSION if is_sleep else RECOVERY_SCORE_FORMULA_VERSION if is_recovery else None)),
        "copied_without_recalculation": True,
    }


def _status(group: str, score: float | None) -> dict[str, Any]:
    if score is None or group == "unknown":
        return {
            "key": "unavailable",
            "label": "กำลังเตรียมผลสรุป",
            "min_score": None,
            "max_score": None,
            "meaning": ("เลือกรูปแบบการพักเพื่อให้ ZEEP แสดงผลได้เหมาะสม" if group == "unknown" else "ZEEP กำลังรวบรวมข้อมูลสำหรับสรุปผลการพักครั้งนี้"),
            "version": RESTORE_ACTION_BANDS_VERSION,
        }
    bands = ACTION_BANDS[group]
    for index, (minimum, key, label) in enumerate(bands):
        if score < minimum:
            continue
        maximum = 100 if index == 0 else bands[index - 1][0] - 1
        return {
            "key": key,
            "label": label,
            "min_score": minimum,
            "max_score": maximum,
            "meaning": STATUS_MEANINGS[key],
            "version": RESTORE_ACTION_BANDS_VERSION,
        }
    raise AssertionError("action bands must include a zero floor")


def _component_drivers(
    quality: Mapping[str, Any],
    group: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    points = quality.get("component_points") or {}
    maxima = quality.get("component_max_points") or {}
    copy = COMPONENT_COPY.get(group, {})
    drivers = []
    for key, text in copy.items():
        earned = _number(points.get(key))
        maximum = _number(maxima.get(key))
        if earned is None or maximum is None or maximum <= 0:
            continue
        ratio = max(0.0, min(1.0, earned / maximum))
        drivers.append(
            {
                "key": key,
                "category": "score_component",
                "label": text[0],
                "message": text[1] if ratio >= 0.70 else text[2],
                "direction": "positive" if ratio >= 0.70 else "attention",
                "earned_points": round(earned, 1),
                "max_points": round(maximum, 1),
                "attainment_pct": round(ratio * 100.0, 1),
                "affects_source_score": True,
                "causal_claim": False,
            }
        )
    positive = sorted(
        (item for item in drivers if item["direction"] == "positive"),
        key=lambda item: item["attainment_pct"],
        reverse=True,
    )
    attention = sorted(
        (item for item in drivers if item["direction"] == "attention"),
        key=lambda item: item["attainment_pct"],
    )
    return positive, attention


def _environment_driver_copy(
    finding: Mapping[str, Any],
    severity: str,
    decision: str,
) -> tuple[str, str, str | None, bool]:
    return user_environment_finding_copy(
        finding.get("title"),
        severity,
        decision,
        finding.get("metric_key") or finding.get("key"),
    )


def _environment_drivers(
    findings: Iterable[Mapping[str, Any]],
    group: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    positive = []
    attention = []
    for finding in findings:
        severity = str(finding.get("severity") or "")
        decision = str(finding.get("decision") or "")
        if severity not in {
            "excellent",
            "good",
            "fair",
            "poor",
            "critical",
            "unavailable",
        }:
            continue
        direction = (
            "attention"
            if severity == "unavailable"
            or decision
            in {
                "required",
                "optimise",
                "sensor_check",
                "safety_review",
                "investigate",
            }
            else "positive"
        )
        affects_source_score = bool(finding.get("contributes_to_primary_score"))
        label, message, action, safety_review = _environment_driver_copy(
            finding,
            severity,
            decision,
        )
        item = {
            "key": f"environment_{finding.get('key') or 'unknown'}",
            "category": "environment",
            "label": label,
            "message": message,
            "direction": direction,
            "severity": severity,
            "decision": decision,
            "action": action,
            "affects_source_score": affects_source_score,
            "relationship": ("recovery_score_component_and_session_context" if group == "nap_recovery" and affects_source_score else "session_context_only"),
            "causal_claim": False,
        }
        if safety_review:
            item["priority"] = "safety_review"
            for field in (
                "threshold",
                "critical_below",
                "critical_above",
                "minimum",
                "maximum",
                "sample_count",
                "sample_pct",
            ):
                if finding.get(field) is not None:
                    item[field] = finding[field]
        (attention if direction == "attention" else positive).append(item)
    priority = {
        "safety_review": 0,
        "critical": 1,
        "poor": 2,
        "unavailable": 3,
        "fair": 4,
    }
    attention.sort(key=lambda item: (0 if item.get("priority") == "safety_review" else priority.get(str(item.get("severity")), 5)))
    return positive, attention


def _merge_drivers(
    quality: Mapping[str, Any],
    findings: Iterable[Mapping[str, Any]],
    group: str,
) -> dict[str, Any]:
    component_positive, component_attention = _component_drivers(quality, group)
    environment_positive, environment_attention = _environment_drivers(list(findings), group)

    # A concrete environmental issue is more useful than repeating the generic
    # Environment component. Keep the point-bearing generic component only when
    # there is no metric-level issue to show.
    if any(item.get("affects_source_score") for item in environment_attention):
        component_attention = [item for item in component_attention if item["key"] != "environment_support"]
    attention = (environment_attention + component_attention)[:2]
    positive = (component_positive + environment_positive)[:2]
    return {
        "positive": positive,
        "attention": attention,
        "explainability_available": bool(positive or attention),
        "selection": "highest_two_strengths_and_highest_two_attention_items",
        "policy_version": RESTORE_DRIVER_POLICY_VERSION,
        "environment_never_determines_sleep_state": True,
        "events_are_associations_not_proven_causes": True,
    }


def _confidence(quality: Mapping[str, Any]) -> dict[str, Any]:
    source = dict(quality.get("score_confidence") or {})
    level = source.get("level") or "unknown"
    return {
        "level": level,
        "label": user_confidence_level(level),
        "session_coverage_pct": source.get("session_coverage_pct"),
        "paired_hr_rr_coverage_pct": source.get("paired_hr_rr_coverage_pct"),
        "changes_source_score": False,
        "admin_qa_context": True,
    }


def _subjective_outcome(
    outcome: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if not outcome or outcome.get("status") in {
        "not_measured",
        "unavailable",
    }:
        return {
            "status": "not_measured",
            "label": "ยังไม่ได้บันทึกความรู้สึกหลังพัก",
            "freshness_delta": None,
            "activity_readiness": None,
            "sensor_inferred": False,
        }
    return {
        "status": "measured",
        "label": "บันทึกความรู้สึกก่อน–หลังการพักแล้ว",
        "freshness_delta": outcome.get("freshness_delta"),
        "activity_readiness": outcome.get("activity_readiness"),
        "source": outcome.get("source") or "session_questionnaire",
        "sensor_inferred": False,
    }


def _recommendation(
    group: str,
    score: float | None,
    drivers: Mapping[str, Any],
) -> dict[str, Any]:
    attention = list(drivers.get("attention") or [])
    selected = attention[0] if attention else None
    if selected and selected.get("priority") == "safety_review":
        message = str(selected.get("action") or "ตรวจเหตุการณ์ Safety และการตอบสนองของระบบก่อนใช้งานครั้งถัดไป")
    elif score is None:
        message = "บอกความรู้สึกหลังพักได้ตามจริง และลองใช้งานตามปกติอีกครั้ง"
    elif selected and selected.get("category") == "environment":
        message = str(selected.get("action") or "ปรับปัจจัยแวดล้อมที่ระบบระบุ แล้วเปรียบเทียบ Session ถัดไป")
    elif selected:
        message = RECOMMENDATIONS.get(group, {}).get(
            str(selected.get("key")),
            "ทบทวนปัจจัยที่ได้คะแนนต่ำสุด แล้วเปรียบเทียบกับ Session ถัดไป",
        )
    elif group == "sleep":
        message = "รักษารูปแบบที่ได้ผลและติดตามแนวโน้มจากหลายคืน"
    elif group == "nap_recovery":
        message = "รักษารูปแบบการพักที่ได้ผลและบันทึกความรู้สึกหลังพัก"
    else:
        message = "เลือกรูปแบบการพักเพื่อรับคำแนะนำที่เหมาะกับครั้งนี้"
    return {
        "primary": message,
        "source_driver_key": selected.get("key") if selected else None,
        "version": RESTORE_RECOMMENDATION_VERSION,
        "one_action_only": True,
        "automatic_actuation": False,
        "medical_advice": False,
    }


def build_restore_summary(
    quality: Mapping[str, Any] | None,
    *,
    mode: Mapping[str, Any] | None = None,
    findings: Iterable[Mapping[str, Any]] | None = None,
    personal_context: Mapping[str, Any] | None = None,
    trend_context: Mapping[str, Any] | None = None,
    subjective_outcome: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a user-facing explanation around an existing primary score.

    The caller must select mode-specific personal/trend data before passing it
    here.  This prevents accidental comparison of Nap & Refresh with Overnight
    Recovery and keeps storage concerns outside the scoring layer.
    """
    score_quality = dict(quality or {})
    mode_source = mode if mode is not None else score_quality.get("rest_mode")
    group = _mode_group(score_quality, mode_source)
    source_score = _source_score(score_quality, group)
    score = _number(source_score["value"])
    driver_summary = _merge_drivers(
        score_quality,
        list(findings or []),
        group,
    )
    is_sleep = group == "sleep"
    is_recovery = group == "nap_recovery"
    return {
        "version": RESTORE_SUMMARY_VERSION,
        "available": source_score["available"],
        "name": "ZEEP Restore Summary",
        "creates_independent_score": False,
        "source_score": source_score,
        "status": _status(group, score),
        "session_scope": {
            "mode": group,
            "label": ("Overnight Recovery" if is_sleep else "Nap & Refresh" if is_recovery else "ผลการพักครั้งนี้"),
            "question": ("การนอนครั้งนี้สนับสนุนการฟื้นตัวได้ดีเพียงใด" if is_sleep else "ช่วงพักนี้ร่างกายสงบและพักได้ตามเป้าหมายเพียงใด" if is_recovery else "เลือกรูปแบบการพักเพื่อดูผลสรุปที่เหมาะสม"),
            "whole_day_readiness": False,
            "clinical_readiness": False,
            "updates_during_day": False,
        },
        "drivers": driver_summary,
        "personal_baseline": build_baseline_summary(personal_context, score, group),
        "trend": build_trend_summary(trend_context),
        "recommendation": _recommendation(group, score, driver_summary),
        "confidence": _confidence(score_quality),
        "subjective_outcome": _subjective_outcome(subjective_outcome),
        "claim_boundary": {
            "wellness_estimate": True,
            "medical_diagnosis": False,
            "whole_day_readiness": False,
            "training_load_included": False,
            "daytime_activity_included": False,
            "freshness_not_inferred_from_sensor": True,
            "environment_association_is_not_causation": True,
        },
    }
