"""User-facing explanations for a candidate supported by sleep evidence."""

_CANDIDATE_REASONS = {
    "wake": "หลักฐานใกล้ Awake baseline เด่นที่สุด",
    "n1": "หลักฐานกำลังลดจาก Awake baseline และอยู่ในช่วงเปลี่ยนผ่าน",
    "n2": "หลักฐาน HR/RR และ BCG คงที่ต่อเนื่อง",
    "n3": ("ชีพจรและการหายใจสอดคล้องกับช่วงอ้างอิง N3 พร้อมหลักฐานความนิ่งและการหายใจสม่ำเสมอ"),
    "rem": "RR แปรปรวนบนเตียงที่นิ่งและ REM gate ผ่าน",
}


def sleep_candidate_reason(candidate: str | None) -> str | None:
    """Return no physiological claim when there is no supported candidate."""
    return _CANDIDATE_REASONS.get(candidate)
