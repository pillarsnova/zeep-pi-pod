"""User-facing status, scope and recommendation copy for Restore Summary."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sleep_system_policy import (
    RESTORE_ACTION_BANDS_VERSION,
    RESTORE_RECOMMENDATION_VERSION,
)
from zeep_pod.sessions.restore_summary_policy import (
    ACTION_BANDS,
    RECOMMENDATIONS,
    STATUS_MEANINGS,
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
            "label": "ควรให้ทีมตรวจสอบสภาพแวดล้อม",
            "min_score": None,
            "max_score": None,
            "meaning": "พบค่าเกินกรอบความปลอดภัยระหว่าง Session คะแนนยังแสดงได้แต่ไม่ใช้แทนการตรวจสอบ",
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
) -> dict[str, Any]:
    """Return one bounded next action based only on available evidence."""
    attention = list(drivers.get("attention") or [])
    selected = attention[0] if attention else None
    if selected and selected.get("priority") == "safety_review":
        message = str(
            selected.get("action")
            or "ตรวจเหตุการณ์ Safety และการตอบสนองของระบบก่อนใช้งานครั้งถัดไป"
        )
    elif limited_evidence:
        message = "บันทึกความรู้สึกหลังพัก และใช้งานครั้งถัดไปตามปกติ"
    elif score is None:
        message = "บอกความรู้สึกหลังพักได้ตามจริง และลองใช้งานตามปกติอีกครั้ง"
    elif selected and selected.get("category") == "environment":
        message = str(
            selected.get("action") or "ปรับปัจจัยแวดล้อมที่ระบบระบุ แล้วเปรียบเทียบ Session ถัดไป"
        )
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
            "การนอนครั้งนี้สนับสนุนการฟื้นตัวได้ดีเพียงใด"
            if is_sleep
            else "ช่วงพักนี้ร่างกายสงบและพักได้ตามเป้าหมายเพียงใด"
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
