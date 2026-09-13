"""Stable, user-friendly wording for ZEEP Wellness results.

Internal keys, quality gates and safety severities remain authoritative.  This
module only translates those results for customers and application clients so
that engineering vocabulary does not become a judgement about the person.
"""

from __future__ import annotations

import math
from typing import Any

PRODUCT_LANGUAGE_VERSION = "zeep-product-language-v1.0"

USER_SCORE_LEVELS = {
    "very_good": "ดีมาก",
    "good": "ดี",
    "fair": "พอใช้",
    "low": "ให้เวลากับการพักเพิ่ม",
    "unavailable": "กำลังเตรียมผลสรุป",
    "unknown": "ผลการพักครั้งนี้",
}

USER_ENVIRONMENT_LEVELS = {
    "excellent": "ยอดเยี่ยม",
    "good": "ดี",
    "fair": "พอใช้",
    "poor": "ควรปรับ",
    "critical": "แนะนำให้ปรับตอนนี้",
    "unavailable": "กำลังรวบรวมข้อมูล",
    "unknown": "กำลังรวบรวมข้อมูล",
}

USER_CONFIDENCE_LEVELS = {
    "high": "ข้อมูลชัดเจน",
    "medium": "ข้อมูลเพียงพอ",
    "low": "กำลังรวบรวมข้อมูลเพิ่ม",
    "unknown": "กำลังเตรียมผลสรุป",
}

USER_REST_MODE_LABELS = {
    "sleep": "Overnight Recovery",
    "nap_recovery": "Nap & Refresh",
}

USER_SCORE_COMPONENT_LABELS = {
    "sleep_opportunity": "เวลาและการเข้าสู่การพัก",
    "sleep_stability": "ความต่อเนื่องของการพัก",
    "restorative_architecture": "รูปแบบการพัก",
    "cycle_expression": "ลำดับการพักที่ประเมินได้",
    "data_coverage": "ความครบถ้วนของข้อมูล",
    "goal_duration": "เวลาพักตามเป้าหมาย",
    "physiological_response": "การตอบสนองระหว่างพัก",
    "body_stillness": "ความนิ่งระหว่างพัก",
    "rest_continuity": "ความต่อเนื่องในการพัก",
    "environment_support": "บรรยากาศระหว่างพัก",
}

USER_WELLNESS_DISCLAIMER = "ผลประเมินเพื่อ Wellness · ไม่ใช่การวินิจฉัยหรือทดแทนผลตรวจทางการแพทย์"

RESPIRATORY_AGE_LABELS = {
    "18-29": "วัยผู้ใหญ่ 18–29 ปี",
    "30-44": "วัยผู้ใหญ่ 30–44 ปี",
    "45-59": "วัยผู้ใหญ่ 45–59 ปี",
    "60+": "วัยผู้ใหญ่ 60 ปีขึ้นไป",
}

RESPIRATORY_AGE_GUIDANCE = {
    "18-29": "สังเกตจังหวะการหายใจตามการพักและกิจกรรมของคุณ",
    "30-44": "ดูแนวโน้มร่วมกับการนอน ภาระงาน และกิจกรรมในแต่ละวัน",
    "45-59": "ดูแนวโน้มหลายครั้งร่วมกับความรู้สึกหลังพัก",
    "60+": "เทียบกับรูปแบบที่พบเป็นประจำของคุณมากกว่าค่าครั้งเดียว",
}

RESPIRATORY_STATUS_LABELS = {
    "insufficient": "กำลังเรียนรู้รูปแบบของคุณ",
    "needs_recheck": "แนะนำให้เช็กอีกครั้ง",
    "supportive": "จังหวะการหายใจค่อนข้างสม่ำเสมอ",
    "observe": "มีการเปลี่ยนแปลงบางช่วง",
}

RESPIRATORY_BASELINE_LABELS = {
    "below": "ช้ากว่ารูปแบบที่พบเป็นประจำของคุณ",
    "within": "ใกล้รูปแบบที่พบเป็นประจำของคุณ",
    "above": "เร็วกว่ารูปแบบที่พบเป็นประจำของคุณ",
}

RESPIRATORY_RECOMMENDATIONS = {
    "supportive": "รักษารูปแบบการพักที่สบายนี้ไว้",
    "observe": "ติดตามอีก 2–3 ครั้งร่วมกับความรู้สึกหลังพัก",
    "needs_recheck": "ลองติดตามอีกครั้งขณะพักนิ่ง หากรู้สึกไม่สบายให้ปรึกษาผู้เชี่ยวชาญ",
    "insufficient": "พักตามปกติ เพื่อให้ ZEEP เรียนรู้เพิ่ม",
}

PAIRED_VITAL_STATUS_LABELS = {
    "available": "พร้อมดูแนวโน้ม",
    "needs_recheck": "แนะนำให้เช็กอีกครั้ง",
    "insufficient": "กำลังรวบรวมข้อมูล",
}

USER_ENVIRONMENT_METRIC_LABELS = {
    "temperature": "อุณหภูมิ",
    "temp": "อุณหภูมิ",
    "humidity": "ความชื้น",
    "hum": "ความชื้น",
    "sound": "เสียง",
    "dba": "เสียง",
    "co2": "CO₂",
    "pm25": "PM2.5",
    "pm2_5": "PM2.5",
    "voc": "VOC Index",
}


def user_score_level(level_key: Any, fallback: Any = None) -> str | None:
    """Return canonical customer copy without trusting persisted prose.

    ``fallback`` remains in the signature for source compatibility only.  Raw
    historical labels belong to Admin/Audit surfaces and must not bypass the
    public product-language contract when a new or missing key is observed.
    """
    key = str(level_key or "").strip().casefold()
    if key in USER_SCORE_LEVELS:
        return USER_SCORE_LEVELS[key]
    return USER_SCORE_LEVELS["unknown"]


def user_environment_level(level_key: Any, fallback: Any = None) -> str:
    """Translate a Wellness band without exposing persisted fallback prose."""
    key = str(level_key or "").strip().casefold()
    if key in USER_ENVIRONMENT_LEVELS:
        return USER_ENVIRONMENT_LEVELS[key]
    return USER_ENVIRONMENT_LEVELS["unknown"]


def user_environment_finding_copy(
    title: Any,
    severity: Any,
    decision: Any,
    metric_key: Any = None,
) -> tuple[str, str, str | None, bool]:
    """Project an internal environment finding into calm product language."""
    key = str(metric_key or "").removesuffix("_safety_excursion").casefold()
    metric = USER_ENVIRONMENT_METRIC_LABELS.get(key, "สภาพแวดล้อม")
    level_key = str(severity or "unavailable").strip().casefold()
    safety_review = str(decision or "") == "safety_review"
    level = "ควรให้ทีมตรวจสอบ" if safety_review else user_environment_level(level_key)
    if safety_review:
        message = "มีค่าบางช่วงแตะเกณฑ์ความปลอดภัย กรุณาแจ้งทีมงานก่อนใช้งานครั้งถัดไป"
        action = "กรุณาแจ้งทีมงาน"
    elif level_key == "unavailable":
        message, action = "ZEEP กำลังรวบรวมข้อมูลส่วนนี้", None
    elif level_key in {"good", "excellent"}:
        message, action = "อยู่ในช่วงที่เหมาะกับการพักครั้งนี้", None
    elif level_key == "fair":
        message, action = "ยังปรับให้เหมาะกับการพักได้อีกเล็กน้อย", None
    else:
        message = "มีปัจจัยที่ปรับให้การพักสบายขึ้นได้"
        action = "ทีมงานช่วยปรับค่านี้ให้เหมาะกับครั้งถัดไปได้"
    return f"{metric} · {level}", message, action, safety_review


def user_report_finding_copy(
    finding_key: Any,
    severity: Any,
    decision: Any,
) -> tuple[str, str, str | None]:
    """Build public finding prose from stable keys, never stored prose."""
    key = str(finding_key or "").strip().casefold()
    base_key = key.removesuffix("_safety_excursion")
    if base_key in USER_ENVIRONMENT_METRIC_LABELS:
        title, detail, action, _ = user_environment_finding_copy(
            None,
            severity,
            decision,
            base_key,
        )
        return title, detail, action

    if str(decision or "").strip().casefold() == "safety_review":
        return (
            "ข้อมูลด้านความปลอดภัย · ควรให้ทีมตรวจสอบ",
            "มีข้อมูลบางช่วงแตะเกณฑ์ความปลอดภัย กรุณาแจ้งทีมงานก่อนใช้งานครั้งถัดไป",
            "กรุณาแจ้งทีมงาน",
        )

    if key == "acoustic_corroborated":
        return (
            "เสียงและการขยับบนเตียง · ลองสังเกตเพิ่มเติม",
            "พบเสียงและการตอบสนองจากเตียงในช่วงเวลาใกล้กัน",
            "ลองสังเกตแหล่งเสียงหรือแรงสั่นรอบตัวในการพักครั้งถัดไป",
        )

    level_key = str(severity or "").strip().casefold()
    if level_key == "unavailable":
        return (
            "ข้อมูลประกอบ · กำลังรวบรวมข้อมูล",
            "ZEEP กำลังรวบรวมข้อมูลส่วนนี้",
            None,
        )
    if level_key in {"good", "excellent"}:
        return (
            "ข้อมูลประกอบ · อยู่ในช่วงที่เหมาะกับการพัก",
            "ข้อมูลส่วนนี้สอดคล้องกับการพักครั้งนี้",
            None,
        )
    return (
        "ข้อมูลประกอบ · ลองสังเกตเพิ่มเติม",
        "มีข้อมูลบางส่วนที่ลองดูร่วมกับความรู้สึกหลังพักได้",
        "ลองติดตามแนวโน้มนี้ในการพักครั้งถัดไป",
    )


def user_rest_mode_label(mode_key: Any) -> str:
    """Return a canonical public mode label without trusting stored labels."""
    key = str(mode_key or "").strip().casefold()
    return USER_REST_MODE_LABELS.get(key, "รูปแบบการพักครั้งนี้")


def user_score_component_label(component_key: Any) -> str:
    """Return calm score-component copy from its stable key."""
    key = str(component_key or "").strip().casefold()
    return USER_SCORE_COMPONENT_LABELS.get(key, "รายละเอียดคะแนน")


def user_confidence_level(level_key: Any, fallback: Any = None) -> str:
    """Return calm public copy; unknown keys never echo historical wording."""
    key = str(level_key or "").strip().casefold()
    if key in USER_CONFIDENCE_LEVELS:
        return USER_CONFIDENCE_LEVELS[key]
    return USER_CONFIDENCE_LEVELS["unknown"]


def user_respiratory_status(status_key: Any) -> tuple[str, str]:
    """Return a supported respiratory status key and its canonical label."""
    key = str(status_key or "").strip().casefold()
    if key not in RESPIRATORY_STATUS_LABELS:
        key = "insufficient"
    return key, RESPIRATORY_STATUS_LABELS[key]


def user_respiratory_age_context(age_band: Any) -> tuple[str | None, str, str]:
    """Project an age band without reusing persisted Profile prose."""
    band = str(age_band or "").strip()
    if band not in RESPIRATORY_AGE_LABELS:
        return None, "บริบทตามช่วงวัย", "เพิ่มข้อมูลอายุเพื่อให้คำแนะนำเหมาะกับช่วงวัยมากขึ้น"
    return band, RESPIRATORY_AGE_LABELS[band], RESPIRATORY_AGE_GUIDANCE[band]


def user_respiratory_baseline_copy(
    status_key: Any,
    *,
    available: bool,
) -> tuple[str | None, str | None]:
    """Return canonical Baseline wording from a stable comparison key."""
    key = str(status_key or "").strip().casefold()
    if available and key in RESPIRATORY_BASELINE_LABELS:
        return RESPIRATORY_BASELINE_LABELS[key], None
    return None, (
        "กำลังเรียนรู้รูปแบบของคุณ เมื่อมีข้อมูลการพักรูปแบบนี้จากหลายครั้ง ZEEP จะเปรียบเทียบแนวโน้มได้ชัดขึ้น"
    )


def user_respiratory_interpretation(
    status_key: Any,
    median_hr_bpm: Any,
    median_rr_brpm: Any,
) -> str:
    """Build one claim-bounded HR/RR summary line from direct aggregates."""
    key, _ = user_respiratory_status(status_key)
    try:
        heart_rate = float(median_hr_bpm)
        respiration_rate = float(median_rr_brpm)
    except (TypeError, ValueError):
        heart_rate = respiration_rate = math.nan
    paired_values_available = (
        math.isfinite(heart_rate)
        and 30.0 <= heart_rate <= 220.0
        and math.isfinite(respiration_rate)
        and 4.0 <= respiration_rate <= 60.0
    )
    if key == "insufficient" or not paired_values_available:
        return "ข้อมูลชีพจรและการหายใจยังไม่พอสรุป"
    if key == "needs_recheck":
        return "รูปแบบการหายใจต่างจากช่วงอ้างอิง ลองติดตามอีกครั้ง"
    if key == "supportive":
        return "จังหวะหายใจค่อนข้างสม่ำเสมอระหว่างพัก"
    return "จังหวะหายใจเปลี่ยนแปลงบางช่วง"


def user_paired_vital_status(
    respiratory_status_key: Any,
    median_hr_bpm: Any,
    median_rr_brpm: Any,
) -> tuple[str, str]:
    """Describe joint HR/RR availability without inventing a health grade."""
    try:
        heart_rate = float(median_hr_bpm)
        respiration_rate = float(median_rr_brpm)
    except (TypeError, ValueError):
        heart_rate = respiration_rate = math.nan
    complete = (
        math.isfinite(heart_rate)
        and 30.0 <= heart_rate <= 220.0
        and math.isfinite(respiration_rate)
        and 4.0 <= respiration_rate <= 60.0
    )
    respiratory_key, _ = user_respiratory_status(respiratory_status_key)
    if not complete or respiratory_key == "insufficient":
        key = "insufficient"
    elif respiratory_key == "needs_recheck":
        key = "needs_recheck"
    else:
        key = "available"
    return key, PAIRED_VITAL_STATUS_LABELS[key]


def user_respiratory_recommendation(status_key: Any) -> str:
    """Return one calm, claim-bounded next step from a stable status key."""
    key, _ = user_respiratory_status(status_key)
    return RESPIRATORY_RECOMMENDATIONS[key]
