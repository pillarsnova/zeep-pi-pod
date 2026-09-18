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
    "sound": ("ลดเสียงรบกวนก่อนพัก", "ก่อนพักครั้งถัดไป ลองปิดเสียงแจ้งเตือนและเลือกมุมที่เงียบขึ้น"),
    "lux": ("ปรับแสงให้เหมาะกับการพัก", "ก่อนพักครั้งถัดไป ลองลดแสงจากหน้าจอและแสงที่ส่องเข้าตา"),
    "temperature": (
        "เลือกความเย็นที่สบายกับคุณ",
        "ก่อนพักครั้งถัดไป ลองปรับอุณหภูมิหรือเครื่องนอนทีละอย่างตามความสบาย",
    ),
    "humidity": (
        "ดูแลความสบายของห้องพัก",
        "ก่อนพักครั้งถัดไป ลองตรวจความชื้นและการระบายอากาศของห้อง",
    ),
    "co2": ("เลือกมุมพักที่อากาศถ่ายเท", "ก่อนพักครั้งถัดไป ลองเลือกห้องที่มีการระบายอากาศเหมาะสม"),
    "pm2_5": ("ลดฝุ่นบริเวณที่พัก", "ก่อนพักครั้งถัดไป ลองตรวจฝุ่นในห้องและดูแลเครื่องกรองอากาศหากมี"),
    "voc_index": ("ลดแหล่งกลิ่นในพื้นที่พัก", "ก่อนพักครั้งถัดไป ลองลดการใช้สเปรย์หรือน้ำหอมในพื้นที่พัก"),
}


def _session_tip(group, selected, quality):
    """Choose an ordinary habit from the measured Session, not score rank."""
    key = str(selected.get("key") or "")
    when = "ก่อนพักครั้งถัดไป"
    title = "เก็บช่วงพักไว้ในกิจวัตร"
    primary = "ลองจัดช่วงพักที่ทำได้สม่ำเสมอ แล้วสังเกตความรู้สึกหลังพักแต่ละครั้ง"
    reason = "ใช้รูปแบบการพักครั้งนี้เป็นจุดเริ่มต้น โดยไม่สรุปความสดชื่นจาก Sensor"
    tip = "rest_routine"
    if selected.get("category") == "environment":
        metric = key.removeprefix("environment_")
        tip = "environment_" + metric
        title, primary = ENVIRONMENT_TIPS.get(
            metric,
            (
                "ปรับพื้นที่พักทีละอย่าง",
                "ก่อนพักครั้งถัดไป ลองปรับสิ่งรบกวนที่พบทีละอย่าง แล้วสังเกตความสบาย",
            ),
        )
        reason = f"ครั้งนี้พบประเด็น {selected.get('label') or 'สภาพแวดล้อม'} เป็นบริบทประกอบ ไม่ได้ยืนยันว่าเป็นสาเหตุของการตื่น"
    elif group == "sleep" and key == "sleep_opportunity":
        tip, title = "protect_sleep_time", "เผื่อเวลาให้การนอนมากขึ้น"
        when = "ก่อนนอนครั้งถัดไป"
        primary = "ลองจัดภารกิจให้จบเร็วขึ้น เพื่อมีเวลานอนใกล้เป้าหมายที่เลือก"
        reason = "องค์ประกอบเวลาและการเริ่มหลับยังมีส่วนปรับได้ จึงแนะนำให้เริ่มจากตารางพักที่ทำได้จริง"
    elif group == "sleep" and key == "sleep_stability":
        tip, title = "reduce_interruptions", "เตรียมช่วงนอนที่ไม่ถูกรบกวน"
        when = "ก่อนนอนครั้งถัดไป"
        primary = "ลองจัดการภารกิจและปิดเสียงแจ้งเตือนก่อนนอน เพื่อลดการขัดจังหวะที่หลีกเลี่ยงได้"
        reason = "ครั้งนี้มีช่วงพักไม่ต่อเนื่อง แต่ข้อมูลยังไม่ระบุสาเหตุ จึงเสนอสิ่งที่ปรับได้ง่ายก่อน"
    elif group == "nap_recovery" and key == "goal_duration":
        tip, title = "plan_rest_break", "จัดเวลาพักให้พอดีกับวันของคุณ"
        primary = "ลองกันเวลาพักให้ใกล้เป้าหมายที่เลือก โดยไม่ต้องพยายามหลับให้ได้"
        reason = "เวลาพักครั้งนี้ยังไม่ใกล้เป้าหมาย การปรับช่วงว่างอาจทำให้พักได้สะดวกขึ้น"
    elif group == "nap_recovery" and as_number(quality.get("estimated_sleep_s")) == 0:
        key = "estimated_sleep_s"
        tip, title = "quiet_awake_break", "รักษาช่วงพักเงียบระหว่างวัน"
        primary = (
            "วันทำงานถัดไป ลองเว้นช่วงพักจากหน้าจอโดยไม่ต้องบังคับให้หลับ แล้วสังเกตความรู้สึกหลังพัก"
        )
        reason = "ครั้งนี้ระบบยังไม่พบช่วงหลับชัดเจน จึงแนะนำการพักแบบตื่นได้ แทนการพยายามหลับลึก"
    elif group == "sleep":
        key = ""
        tip, title = "regular_sleep_routine", "รักษาเวลาเข้านอนให้สม่ำเสมอ"
        when = "ก่อนนอนครั้งถัดไป"
        primary = "ลองคงเวลาเข้านอนและตื่นให้ใกล้เดิม แล้วติดตามทั้งผลการนอนและความรู้สึกของคุณ"
        reason = "ใช้ผลคืนนี้เป็นจุดเริ่มต้นของกิจวัตร ไม่จำเป็นต้องปรับทุกอย่างจากคืนเดียว"
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
        tip, basis, when = "allow_recovery_time", "self_report", "ก่อนกิจกรรมถัดไป"
        title = "ให้เวลาตัวเองก่อนเริ่มกิจกรรม"
        primary = "เริ่มกิจกรรมอย่างค่อยเป็นค่อยไป หากยังง่วงให้เลื่อนการขับรถหรืองานที่ต้องระมัดระวัง"
        reason = "คุณรายงานว่าความสดชื่นลดลงหรือยังไม่พร้อมทำกิจกรรม จึงใช้คำตอบของคุณประกอบคำแนะนำ"
    elif limited_evidence or score is None or group not in {"sleep", "nap_recovery"}:
        key = ""
        tip, basis, when = "check_feeling", "limited_data", "หลังพัก"
        title = "สังเกตความรู้สึกก่อนเริ่มกิจกรรม"
        primary = "ลองเช็กว่าตอนนี้สดชื่นหรือยังง่วง แล้วเลือกจังหวะเริ่มกิจกรรมที่สบายกับคุณ"
        reason = "ข้อมูลครั้งนี้มีจำกัด จึงไม่สรุปการฟื้นตัวหรือความพร้อมจากคะแนน"
    comparison = as_mapping(baseline.get("comparison"))
    if (
        tip in {"rest_routine", "regular_sleep_routine"}
        and comparison.get("available") is True
    ):
        key = "personal_baseline"
        basis = "personal_baseline"
        reason = f"ผลครั้งนี้{comparison.get('label') or 'เทียบกับรูปแบบเดิมได้'} โดยเทียบเฉพาะโหมดและเป้าหมายเดียวกัน"
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
