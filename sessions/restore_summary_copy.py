"""User-facing status, scope and recommendation copy for Restore Summary."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sessions.post_rest_advice import build_post_rest_advice
from sessions.restore_summary_policy import (
    ACTION_BANDS,
    STATUS_MEANINGS,
)
from sleep_system_policy import (
    RESTORE_ACTION_BANDS_VERSION,
)


def build_status(
    group: str,
    score: float | None,
    *,
    safety_review: bool = False,
    limited_evidence: bool = False,
) -> dict[str, Any]:
    """Describe a score without overstating missing evidence."""
    if safety_review:
        return {
            "key": "safety_review",
            "label": "ตรวจสอบก่อนใช้งานครั้งถัดไป",
            "min_score": None,
            "max_score": None,
            "meaning": (
                "พบค่าบางช่วงแตะเกณฑ์ความปลอดภัย กรุณาแจ้งทีมงานและตรวจเหตุการณ์"
                "ก่อนใช้งานครั้งถัดไป คะแนนแสดงเพื่อประกอบข้อมูลเท่านั้น"
            ),
            "version": RESTORE_ACTION_BANDS_VERSION,
        }
    if limited_evidence and score is not None and group != "unknown":
        return {
            "key": "limited_evidence",
            "label": "สรุปการพักครั้งนี้แล้ว",
            "min_score": None,
            "max_score": None,
            "meaning": "เวลาบันทึกครบขั้นต่ำ แต่ข้อมูล Sensor ครั้งนี้มีจำกัด",
            "version": RESTORE_ACTION_BANDS_VERSION,
        }
    if score is None or group == "unknown":
        return {
            "key": "unavailable",
            "label": "กำลังเตรียมผลสรุป",
            "min_score": None,
            "max_score": None,
            "meaning": (
                "เลือกรูปแบบการพักเพื่อให้ ZEEP แสดงผลได้เหมาะสม"
                if group == "unknown"
                else "ZEEP กำลังรวบรวมข้อมูลสำหรับสรุปผลการพักครั้งนี้"
            ),
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


def build_recommendation(
    group: str,
    score: float | None,
    drivers: Mapping[str, Any],
    *,
    limited_evidence: bool = False,
    quality: Mapping[str, Any] | None = None,
    baseline: Mapping[str, Any] | None = None,
    subjective: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compatibility facade for the single after-rest recommendation policy."""
    return build_post_rest_advice(
        group,
        score,
        drivers,
        quality=quality,
        baseline=baseline,
        subjective=subjective,
        limited_evidence=limited_evidence,
    )


def session_scope(group: str) -> dict[str, Any]:
    """Name the product question answered by each canonical mode."""
    is_sleep = group == "sleep"
    is_recovery = group == "nap_recovery"
    return {
        "mode": group,
        "label": (
            "Overnight Recovery"
            if is_sleep
            else "Nap & Refresh"
            if is_recovery
            else "ผลการพักครั้งนี้"
        ),
        "question": (
            "ข้อมูลการนอนครั้งนี้เป็นอย่างไร"
            if is_sleep
            else "ช่วงพักนี้นิ่ง ต่อเนื่อง และใกล้เป้าหมายเพียงใด"
            if is_recovery
            else "เลือกรูปแบบการพักเพื่อดูผลสรุปที่เหมาะสม"
        ),
        "whole_day_readiness": False,
        "clinical_readiness": False,
        "updates_during_day": False,
    }


def claim_boundary() -> dict[str, bool]:
    """Keep the public Wellness scope explicit and stable."""
    return {
        "wellness_estimate": True,
        "medical_diagnosis": False,
        "whole_day_readiness": False,
        "training_load_included": False,
        "daytime_activity_included": False,
        "freshness_not_inferred_from_sensor": True,
        "environment_association_is_not_causation": True,
    }
