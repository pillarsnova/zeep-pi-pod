"""Evidence-linked everyday tips, separate from scores and device control."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from common.mappings import as_mapping
from common.numbers import as_number
from sleep_system_policy import RESTORE_RECOMMENDATION_VERSION

# General wellness habits, not treatment or causal claims about this Session.
# References and selection policy: docs/zeep-post-rest-advice.md.
ENVIRONMENT_TIPS = {
    "sound": ("ลดเสียงรบกวน", "ปิดเสียงแจ้งเตือนและเลือกบริเวณที่เงียบสำหรับพัก"),
    "lux": ("ลดแสงรบกวน", "ลดแสงหน้าจอและแสงที่ส่องเข้าตาขณะพัก"),
    "temperature": (
        "ปรับอุณหภูมิให้สบาย",
        "ปรับอุณหภูมิหรือผ้าห่มทีละอย่าง ให้รู้สึกสบาย ไม่ร้อนหรือหนาวเกินไป",
    ),
    "humidity": (
        "ตรวจความชื้นในห้อง",
        "ตรวจความชื้นและการระบายอากาศบริเวณที่พัก",
    ),
    "co2": ("ดูแลการระบายอากาศ", "เลือกพักในห้องที่มีการระบายอากาศเหมาะสม"),
    "pm2_5": ("ลดฝุ่นบริเวณที่พัก", "ตรวจฝุ่นในห้องและดูแลเครื่องกรองอากาศหากมี"),
    "voc_index": ("ลดแหล่งกลิ่นในห้อง", "ลดการใช้สเปรย์หรือน้ำหอมบริเวณที่พัก"),
}


def _session_tip(group, selected, quality):
    """Choose an ordinary habit from the measured Session, not score rank."""
    key = str(selected.get("key") or "")
    when = "ก่อนพักครั้งถัดไป"
    title = "จัดเวลาพักระหว่างวัน"
    primary = "เว้นช่วงพักจากงานหรือหน้าจอในเวลาที่สะดวก"
    reason = "คำแนะนำทั่วไปสำหรับการพักระหว่างวัน"
    tip = "rest_routine"
    if selected.get("category") == "environment":
        metric = key.removeprefix("environment_")
        metric = {"voc": "voc_index", "pm25": "pm2_5"}.get(metric, metric)
        tip = "environment_" + metric
        title, primary = ENVIRONMENT_TIPS.get(
            metric,
            (
                "ปรับพื้นที่พักทีละอย่าง",
                "ปรับสิ่งรบกวนที่พบทีละอย่าง แล้วสังเกตว่าพักสบายขึ้นหรือไม่",
            ),
        )
        label = selected.get("label") or "สภาพแวดล้อม"
        reason = f"มีข้อสังเกตเรื่อง{label}ในบางช่วง ยังไม่ยืนยันว่าเป็นสาเหตุของการตื่น"
    elif group == "sleep" and key == "sleep_opportunity":
        tip, title = "protect_sleep_time", "เผื่อเวลาให้การนอนมากขึ้น"
        when = "ก่อนนอนครั้งถัดไป"
        primary = "จัดธุระให้เสร็จก่อนเข้านอน เพื่อให้มีเวลาพักตามที่ตั้งใจ"
        reason = "เวลานอนหรือระยะก่อนหลับครั้งนี้ยังไม่ใกล้เป้าหมายที่กำหนด"
    elif group == "sleep" and key == "sleep_stability":
        tip, title = "reduce_interruptions", "ลดสิ่งรบกวนก่อนนอน"
        when = "ก่อนนอนครั้งถัดไป"
        primary = "จัดธุระให้เรียบร้อยและปิดเสียงแจ้งเตือนก่อนนอน"
        reason = "พบการนอนขาดช่วง แต่ยังระบุสาเหตุไม่ได้"
    elif group == "nap_recovery" and key == "goal_duration":
        tip, title = "plan_rest_break", "เผื่อเวลาพักให้พอ"
        primary = "เลือกช่วงที่มีเวลาพักใกล้กับเป้าหมายที่ตั้งไว้ โดยไม่ต้องฝืนให้หลับ"
        reason = "ระยะเวลาพักครั้งนี้ต่างจากเป้าหมายที่เลือกไว้"
    elif group == "nap_recovery" and as_number(quality.get("estimated_sleep_s")) == 0:
        key = "estimated_sleep_s"
        tip, title = "quiet_awake_break", "พักสายตาระหว่างวัน"
        primary = "วางหน้าจอและพักในมุมเงียบ ๆ โดยไม่ต้องฝืนให้หลับ"
        reason = "ครั้งนี้ยังไม่พบช่วงหลับชัดเจน จึงแนะนำการพักสายตาโดยไม่ต้องหลับ"
    elif group == "sleep":
        key = ""
        tip, title = "regular_sleep_routine", "รักษาเวลาเข้านอนให้สม่ำเสมอ"
        when = "ก่อนนอนครั้งถัดไป"
        primary = "เข้านอนและตื่นใกล้เวลาเดิมในแต่ละวัน"
        reason = "คำแนะนำทั่วไปสำหรับการนอน ควรดูผลหลายคืนประกอบกัน"
    return tip, title, primary, reason, when, key


def _self_report_needs_time(subjective):
    """Only validated self-report can describe the user's perceived recovery."""
    freshness = as_number(subjective.get("freshness_delta"))
    readiness = as_number(subjective.get("activity_readiness"))
    return (
        subjective.get("status") == "measured"
        and subjective.get("sensor_inferred") is False
        and subjective.get("source")
        in {
            "pre_post_questionnaire",
            "session_questionnaire",
            "zeep_pre_post_questionnaire",
        }
        and (freshness is not None and -10 <= freshness < 0 or readiness == 0)
    )


def build_post_rest_advice(
    group: str,
    score: float | None,
    drivers: Mapping[str, Any],
    *,
    quality: Mapping[str, Any] | None = None,
    baseline: Mapping[str, Any] | None = None,
    subjective: Mapping[str, Any] | None = None,
    limited_evidence: bool = False,
) -> dict[str, Any]:
    """Select one reproducible action; never infer feelings from vital signs."""
    baseline = as_mapping(baseline)
    attention = [as_mapping(item) for item in drivers.get("attention", [])]
    selected = attention[0] if attention else {}
    tip, title, primary, reason, when, key = _session_tip(
        group, selected, as_mapping(quality)
    )
    basis = "session_sensor"
    safety = next(
        (item for item in attention if item.get("priority") == "safety_review"), None
    )
    if safety:
        key = str(safety.get("key") or "")
        tip, basis = "team_review", "safety"
        title = "ให้ทีมช่วยตรวจสภาพแวดล้อม"
        primary = str(safety.get("action") or "กรุณาแจ้งทีมงาน")
        reason = "พบค่าสภาพแวดล้อมบางช่วงที่ควรตรวจสอบก่อนพักครั้งถัดไป"
    elif _self_report_needs_time(as_mapping(subjective)):
        key = "subjective_outcome"
        tip, basis, when = "allow_recovery_time", "self_report", "ก่อนทำกิจกรรมต่อ"
        title = "พักต่อหากยังง่วง"
        primary = "เริ่มกิจกรรมอย่างค่อยเป็นค่อยไป หากยังง่วงให้เลื่อนการขับรถหรืองานที่ต้องระมัดระวัง"
        reason = "คุณระบุว่ารู้สึกสดชื่นน้อยลง หรือยังไม่พร้อมทำกิจกรรมต่อ"
    elif limited_evidence or score is None or group not in {"sleep", "nap_recovery"}:
        key = ""
        tip, basis, when = "check_feeling", "limited_data", "หลังพัก"
        title = "ค่อย ๆ กลับไปทำกิจกรรม"
        primary = "หากยังรู้สึกง่วง ให้พักต่อก่อนเริ่มกิจกรรมที่ต้องใช้สมาธิ"
        reason = "ข้อมูลครั้งนี้มีจำกัด ควรพิจารณาความรู้สึกหลังพักร่วมด้วย"
    comparison = as_mapping(baseline.get("comparison"))
    if (
        tip in {"rest_routine", "regular_sleep_routine"}
        and comparison.get("available") is True
    ):
        key = "personal_baseline"
        basis = "personal_baseline"
        label = comparison.get("label") or "เปรียบเทียบกับครั้งก่อนได้"
        reason = f"คะแนนครั้งนี้{label} เมื่อเทียบกับการพักรูปแบบและเป้าหมายเดียวกัน"
    return {
        "primary": primary,
        "source_driver_key": key or None,
        "version": RESTORE_RECOMMENDATION_VERSION,
        "one_action_only": True,
        "automatic_actuation": False,
        "medical_advice": False,
        "tip_id": tip,
        "title": title,
        "when_label": when,
        "reason": reason,
        "basis": basis,
        "historical_session_context": True,
        "whole_day_readiness_claim": False,
    }
