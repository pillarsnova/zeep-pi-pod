"""Build one non-repeating result view for users and one Admin QA view."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from zeep_pod.product_language import USER_WELLNESS_DISCLAIMER
from zeep_pod.sessions.presentation_metrics import overview_metrics

PRESENTATION_CONTRACT_VERSION = "zeep.usage-presentation.v1"
STAGE_COPY = {
    "wake": "W · ตื่น",
    "n1": "N1 · หลับตื้น / เคลิ้มหลับ",
    "n2": "N2 · หลับสนิทขึ้น",
    "n3": "N3 · หลับลึก",
    "rem": "REM · หลับฝัน",
}


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _number_in_range(
    value: Any,
    minimum: float,
    maximum: float,
) -> float | None:
    number = _number(value)
    return number if number is not None and minimum <= number <= maximum else None


def _sleep_stages(detail: Mapping[str, Any]) -> dict[str, Any] | None:
    if _mapping(detail.get("mode")).get("key") != "sleep":
        return None
    report = _mapping(detail.get("report"))
    items = []
    for stored in report.get("stages") or []:
        stage = _mapping(stored)
        key = str(stage.get("state") or "").strip().casefold()
        if key not in STAGE_COPY:
            continue
        duration = _number(stage.get("duration_s"))
        if duration is None:
            continue
        items.append(
            {
                "key": key,
                "label": STAGE_COPY[key],
                "duration_s": max(0.0, duration),
                "percentage": _number(stage.get("pct_scored")),
            }
        )
    return {
        "available": any(item["duration_s"] > 0 for item in items),
        "basis": "display_attributed_time",
        "wellness_estimate": True,
        "medical_diagnosis": False,
        "items": items,
    }


def _rest_profile(detail: Mapping[str, Any]) -> dict[str, Any] | None:
    if _mapping(detail.get("mode")).get("key") != "nap_recovery":
        return None
    durations = {key: 0.0 for key in STAGE_COPY}
    report = _mapping(detail.get("report"))
    for stored in report.get("stages") or []:
        stage = _mapping(stored)
        key = str(stage.get("state") or "").strip().casefold()
        duration = _number(stage.get("duration_s"))
        if key in durations and duration is not None:
            durations[key] += max(0.0, duration)
    items = [
        {
            "key": "awake_rest",
            "label": "พักขณะตื่น",
            "duration_s": durations["wake"],
        },
        {
            "key": "drowsy",
            "label": "เคลิ้ม",
            "duration_s": durations["n1"],
        },
        {
            "key": "estimated_sleep",
            "label": "ช่วงหลับที่ประเมินได้",
            "duration_s": (
                durations["n2"] + durations["n3"] + durations["rem"]
            ),
        },
    ]
    total = sum(item["duration_s"] for item in items)
    for item in items:
        item["percentage"] = (
            100.0 * item["duration_s"] / total if total > 0 else None
        )
    return {
        "available": total > 0,
        "basis": "display_attributed_time",
        "sleep_not_required": True,
        "items": items,
    }


def _drivers(summary: Mapping[str, Any], direction: str) -> list[dict[str, Any]]:
    source = _mapping(summary.get("drivers"))
    items = []
    for value in source.get(direction) or []:
        driver = _mapping(value)
        if not driver.get("key") or not driver.get("message"):
            continue
        items.append(
            {
                "key": str(driver["key"]),
                "label": str(
                    driver.get("label") or "ข้อมูลประกอบ"
                ),
                "message": str(driver["message"]),
                "direction": direction,
            }
        )
    return items[:2]


def _baseline(summary: Mapping[str, Any]) -> dict[str, Any]:
    baseline = _mapping(summary.get("personal_baseline"))
    maturity = _mapping(baseline.get("maturity"))
    comparison = _mapping(baseline.get("comparison"))
    available = comparison.get("available") is True
    return {
        "available": available,
        "label": str(
            comparison.get("label")
            or comparison.get("reason")
            or "กำลังเรียนรู้รูปแบบการพักของคุณ"
        ),
        "maturity_label": str(
            maturity.get("label")
            or "กำลังเรียนรู้รูปแบบของคุณ"
        ),
        "sessions_used": int(maturity.get("sessions_used") or 0),
        "delta_points": (
            _number(comparison.get("delta_points")) if available else None
        ),
        "typical_range": (
            comparison.get("typical_range") if available else None
        ),
    }


def _trend(summary: Mapping[str, Any]) -> dict[str, Any]:
    trend = _mapping(summary.get("trend"))
    available = trend.get("available") is True
    windows = {}
    if available:
        for key, value in _mapping(trend.get("windows")).items():
            window = _mapping(value)
            count = int(window.get("session_count") or 0)
            average = _number_in_range(window.get("average"), 0, 100)
            if count > 0 and average is not None:
                windows[str(key)] = {
                    "session_count": count,
                    "average": average,
                }
    return {
        "available": bool(windows),
        "label": (
            "ดูแนวโน้มจากการพักรูปแบบเดียวกัน"
            if windows
            else str(
                trend.get("reason")
                or "ต้องมีข้อมูลเพิ่มเพื่อดูแนวโน้ม"
            )
        ),
        "windows": windows,
    }


def _subjective(summary: Mapping[str, Any]) -> dict[str, Any]:
    outcome = _mapping(summary.get("subjective_outcome"))
    measured = outcome.get("status") == "measured"
    return {
        "status": "measured" if measured else "not_measured",
        "label": str(
            outcome.get("label")
            or (
                "บันทึกความรู้สึกก่อน–หลังการพักแล้ว"
                if measured
                else "ยังไม่ได้บันทึกความรู้สึกหลังพัก"
            )
        ),
        "freshness_delta": (
            _number_in_range(outcome.get("freshness_delta"), -10, 10)
            if measured
            else None
        ),
        "activity_readiness": (
            _number_in_range(outcome.get("activity_readiness"), 0, 10)
            if measured
            else None
        ),
        "sensor_inferred": False,
    }


def _environment(detail: Mapping[str, Any]) -> dict[str, Any]:
    report = _mapping(detail.get("report"))
    assessment = _mapping(report.get("environment_assessment"))
    metrics = []
    for value in report.get("environment") or []:
        metric = _mapping(value)
        if not metric.get("key"):
            continue
        available = metric.get("available") is True
        metrics.append(
            {
                "key": str(metric["key"]),
                "label": str(metric.get("label") or metric["key"]),
                "average": _number(metric.get("average")) if available else None,
                "unit": str(metric["unit"]) if metric.get("unit") else None,
                "status": (
                    str(metric.get("status") or "ดูรายละเอียด")
                    if available
                    else "ยังไม่มีข้อมูล"
                ),
                "available": available,
            }
        )
    available = any(metric["available"] for metric in metrics)
    return {
        "available": available,
        "status": (
            str(
                assessment.get("overall_label")
                or "ดูรายละเอียดบรรยากาศระหว่างพัก"
            )
            if available
            else "ไม่มีข้อมูลสภาพแวดล้อมสำหรับครั้งนี้"
        ),
        "meets_expected": (
            assessment.get("meets_expected")
            if available
            and isinstance(assessment.get("meets_expected"), bool)
            else None
        ),
        "metrics": metrics,
    }


def _vital_signals(detail: Mapping[str, Any]) -> dict[str, Any]:
    report = _mapping(detail.get("report"))
    respiratory = _mapping(report.get("respiratory_wellness"))
    vital = _mapping(respiratory.get("vital_summary"))
    available = vital.get("available") is True
    return {
        "available": available,
        "status": (
            str(vital.get("status_label") or "สรุปแนวโน้มแล้ว")
            if available
            else "ข้อมูลยังไม่พอสรุป"
        ),
        "heart_rate_bpm": (
            _number_in_range(vital.get("heart_rate_bpm"), 30, 220)
            if available
            else None
        ),
        "respiration_rate_brpm": (
            _number_in_range(vital.get("respiration_rate_brpm"), 4, 60)
            if available
            else None
        ),
        "summary": (
            str(vital.get("summary") or "ดูแนวโน้มระหว่างพัก")
            if available
            else "ข้อมูลชีพจรและการหายใจยังไม่พอสรุป"
        ),
        "wellness_only": True,
    }


def _unavailable_result_copy(
    detail: Mapping[str, Any],
) -> tuple[str, str]:
    if detail.get("session_closed") is not True:
        return (
            "session_not_closed",
            "ผลสรุปจะพร้อมหลังจบการพักครั้งนี้",
        )
    mode = _mapping(detail.get("mode"))
    if mode.get("validation_status") == "mode_metadata_conflict":
        return (
            "mode_metadata_conflict",
            "ครั้งนี้ยังไม่มีคะแนน เพราะข้อมูลรูปแบบการพัก"
            "ต้องได้รับการตรวจสอบ",
        )
    if mode.get("key") == "unknown":
        return (
            "mode_unresolved",
            "ครั้งนี้ยังไม่มีคะแนน เพราะยังระบุรูปแบบการพักไม่ครบ",
        )
    protocol = _mapping(_mapping(mode.get("target")).get("protocol_status"))
    timing_status = str(protocol.get("status") or "")
    if timing_status in {"insufficient", "too_short"}:
        return (
            "session_too_short",
            "ครั้งนี้ยังไม่มีคะแนน เพราะเวลาที่บันทึก"
            "สั้นกว่าเกณฑ์ของรูปแบบการพัก",
        )
    if timing_status == "target_unknown":
        return (
            "target_unknown",
            "ครั้งนี้ยังไม่มีคะแนน เพราะ Session เดิม"
            "ไม่ได้บันทึกเป้าหมายเวลาไว้",
        )
    if timing_status in {"out_of_protocol", "implausible_outlier", "over_limit"}:
        return (
            "duration_out_of_protocol",
            "ครั้งนี้ยังไม่มีคะแนน เพราะระยะเวลาที่บันทึก"
            "ไม่ตรงกับรูปแบบการพักที่เลือก",
        )
    report = _mapping(detail.get("report"))
    quality = _mapping(report.get("quality"))
    physiology = _mapping(quality.get("physiology"))
    if physiology.get("available") is False or not physiology:
        return (
            "insufficient_physiological_evidence",
            "ครั้งนี้ยังไม่มีคะแนน เพราะข้อมูลชีพจร"
            "และการหายใจยังไม่ครบพอ",
        )
    return (
        "result_unavailable",
        "ครั้งนี้ยังไม่มีคะแนน ระบบเก็บข้อมูลที่บันทึกไว้"
        "สำหรับการตรวจสอบแล้ว",
    )


def _primary_result(
    detail: Mapping[str, Any],
    score: Mapping[str, Any],
    summary: Mapping[str, Any],
) -> tuple[bool, dict[str, Any]]:
    available = bool(
        detail.get("session_closed") is True
        and score.get("available") is True
    )
    reason_code, unavailable_reason = (
        ("available", "") if available else _unavailable_result_copy(detail)
    )
    reason = None if available else unavailable_reason
    status = _mapping(summary.get("status"))
    return available, {
        "type": score.get("type") or "unresolved_score",
        "title": score.get("title") or "Session Score",
        "available": available,
        "value": _number(score.get("value")) if available else None,
        "status": (
            str(status.get("label") or "ผลการพักครั้งนี้")
            if available
            else "ยังไม่มีคะแนนสำหรับครั้งนี้"
        ),
        "meaning": (
            str(status.get("meaning") or "ดูภาพรวมจากการพักครั้งนี้")
            if available
            else str(reason)
        ),
        "reason_code": reason_code,
        "reason": reason,
    }


def _result_context(
    summary: Mapping[str, Any],
    *,
    available: bool,
    closed: bool,
) -> dict[str, Any]:
    recommendation = _mapping(summary.get("recommendation"))
    confidence = _mapping(summary.get("confidence"))
    return {
        "positive_drivers": _drivers(summary, "positive") if available else [],
        "attention_drivers": (
            _drivers(summary, "attention") if available else []
        ),
        "personal_baseline": _baseline(summary if available else {}),
        "trend": _trend(summary if available else {}),
        "subjective_outcome": _subjective(summary if available else {}),
        "recommendation": (
            str(
                recommendation.get("primary")
                or "ดูแนวโน้มร่วมกับความรู้สึกหลังพัก"
            )
            if available
            else (
                "ดูรายละเอียดที่บันทึกไว้หลังจบการพักครั้งนี้"
                if closed
                else "ดูผลสรุปหลังจบการพักครั้งนี้"
            )
        ),
        "confidence_label": (
            str(
                confidence.get("label")
                or "ข้อมูลสำหรับครั้งนี้ยังมีจำกัด"
            )
            if available
            else (
                "ข้อมูลยังไม่พอสรุปคะแนน"
                if closed
                else "กำลังบันทึกข้อมูล"
            )
        ),
    }


def build_usage_presentation(detail: Mapping[str, Any]) -> dict[str, Any]:
    """Create the canonical user hierarchy from a sanitized v1 detail."""
    mode = _mapping(detail.get("mode"))
    score = _mapping(detail.get("score"))
    summary = _mapping(detail.get("restore_summary"))
    timing_target = _mapping(mode.get("target"))
    closed = detail.get("session_closed") is True
    available, primary_result = _primary_result(
        detail,
        score,
        summary,
    )
    return {
        "contract_version": PRESENTATION_CONTRACT_VERSION,
        "audience": "user_summary",
        "session_id": str(detail.get("session_id") or ""),
        "mode": {
            "key": mode.get("key") or "unknown",
            "label": (
                mode.get("label") or "รูปแบบการพักครั้งนี้"
            ),
            "sleep_required": bool(mode.get("sleep_required")),
        },
        "timing": {
            "started_at_utc": detail.get("started_at_utc"),
            "ended_at_utc": detail.get("ended_at_utc"),
            "duration_s": _number(detail.get("duration_s")),
            "target_duration_s": _number(timing_target.get("seconds")),
            "target_label": timing_target.get("label"),
        },
        "primary_result": primary_result,
        "overview_metrics": overview_metrics(detail),
        "sleep_stages": _sleep_stages(detail),
        "rest_profile": _rest_profile(detail),
        **_result_context(summary, available=available, closed=closed),
        "environment": _environment(detail),
        "vital_signals": _vital_signals(detail),
        "disclaimer": USER_WELLNESS_DISCLAIMER,
    }
