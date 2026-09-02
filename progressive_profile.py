"""Versioned, low-burden lifestyle profile for ZEEP wellness personalisation.

The account Profile remains the source for identity and body-reference facts.
This module owns optional answers that are learned gradually from the user.
Answers may explain a Session or improve recommendations, but they are never
direct Sleep Stage evidence and never trigger an actuator by themselves.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import math
import re
from typing import Any, Mapping, MutableMapping, Optional


PROFILE_SCHEMA_VERSION = 1
QUESTIONNAIRE_VERSION = "zeep-progressive-profile-v1.0"
CONSENT_VERSION = "zeep-wellness-profile-consent-v1.0"
ANSWER_COOLDOWN_HOURS = 24
DEFER_DAYS = 7


def _options(*pairs: tuple[str, str]) -> list[dict[str, str]]:
    return [{"value": value, "label": label} for value, label in pairs]


# Ordered by usefulness and burden.  The UI exposes only one due question at a
# time; users can voluntarily continue from the profile card if they prefer.
QUESTION_CATALOG: tuple[dict[str, Any], ...] = (
    {
        "id": "primary_rest_goal", "section": "goals", "priority": 10,
        "title": "ปกติคุณอยากใช้ ZEEP เพื่ออะไรที่สุด?",
        "help": "ช่วยเลือกโหมดและสรุปผลให้ตรงเป้าหมาย โดยไม่เปลี่ยนผล Sensor",
        "type": "select", "minimum_sessions": 0,
        "options": _options(
            ("sleep", "นอนหลับให้มีคุณภาพ"),
            ("nap", "งีบและฟื้นฟู"),
            ("relax", "ผ่อนคลายหรือทำสมาธิ"),
            ("readiness", "เตรียมความพร้อม"),
            ("comfort", "หาค่าสภาพแวดล้อมที่สบาย"),
        ),
    },
    {
        "id": "usual_bedtime", "section": "sleep_schedule", "priority": 20,
        "title": "โดยทั่วไปคุณเข้านอนประมาณกี่โมง?",
        "help": "ใช้เทียบจังหวะการพักของคุณเอง ไม่ใช้วินิจฉัยโรค",
        "type": "time", "minimum_sessions": 0,
    },
    {
        "id": "usual_wake_time", "section": "sleep_schedule", "priority": 30,
        "title": "โดยทั่วไปคุณตื่นประมาณกี่โมง?",
        "help": "ช่วยอ่านเวลานอนและความสม่ำเสมอในภาพรวม",
        "type": "time", "minimum_sessions": 0,
    },
    {
        "id": "schedule_regularity", "section": "sleep_schedule", "priority": 40,
        "title": "เวลาเข้านอนและตื่นของคุณสม่ำเสมอแค่ไหน?",
        "help": "เลือกภาพรวมที่ใกล้เคียงที่สุด",
        "type": "select", "minimum_sessions": 1,
        "options": _options(
            ("regular", "ใกล้เคียงกันทุกวัน (±30 นาที)"),
            ("variable", "เปลี่ยนประมาณ 1–2 ชั่วโมง"),
            ("highly_variable", "เปลี่ยนมากกว่า 2 ชั่วโมง"),
        ),
    },
    {
        "id": "chronotype", "section": "sleep_schedule", "priority": 50,
        "title": "คุณรู้สึกสดชื่นที่สุดช่วงไหน?",
        "help": "ใช้เป็นข้อมูลแนวโน้มนาฬิกาชีวิตแบบง่าย",
        "type": "select", "minimum_sessions": 1,
        "options": _options(
            ("morning", "ช่วงเช้า"), ("intermediate", "กลางวัน"),
            ("evening", "ช่วงเย็นหรือกลางคืน"), ("varies", "ไม่แน่นอน"),
        ),
    },
    {
        "id": "shift_work", "section": "sleep_schedule", "priority": 60,
        "title": "งานของคุณมีเวรหรือเวลาทำงานสลับหรือไม่?",
        "help": "ช่วยแยกการนอนหลักออกจากการพักหลังเข้าเวร",
        "type": "select", "minimum_sessions": 1,
        "options": _options(
            ("never", "ไม่มี"), ("occasional", "มีเป็นบางครั้ง"),
            ("regular", "มีเป็นประจำ"), ("prefer_not", "ไม่ต้องการระบุ"),
        ),
    },
    {
        "id": "nap_frequency", "section": "sleep_schedule", "priority": 70,
        "title": "ปกติคุณงีบระหว่างวันบ่อยแค่ไหน?",
        "help": "ช่วยให้คะแนนการงีบเทียบกับรูปแบบจริงของคุณ",
        "type": "select", "minimum_sessions": 2,
        "options": _options(
            ("never", "แทบไม่งีบ"), ("weekly_1_2", "1–2 วัน/สัปดาห์"),
            ("weekly_3_5", "3–5 วัน/สัปดาห์"), ("daily", "เกือบทุกวัน"),
        ),
    },
    {
        "id": "caffeine_daily", "section": "food_drink", "priority": 80,
        "title": "โดยทั่วไปคุณดื่มคาเฟอีนวันละกี่แก้ว?",
        "help": "รวมกาแฟ ชา เครื่องดื่มชูกำลัง และโคล่าโดยประมาณ",
        "type": "select", "minimum_sessions": 2,
        "options": _options(
            ("none", "ไม่ดื่ม"), ("one", "1 แก้ว"),
            ("two", "2 แก้ว"), ("three_plus", "3 แก้วขึ้นไป"),
        ),
    },
    {
        "id": "latest_caffeine", "section": "food_drink", "priority": 90,
        "title": "ปกติคุณดื่มคาเฟอีนแก้วสุดท้ายช่วงไหน?",
        "help": "ใช้ช่วยอธิบายการหลับช้า ไม่ใช่ข้อสรุปสาเหตุ",
        "type": "select", "minimum_sessions": 2,
        "options": _options(
            ("none", "ไม่ดื่ม"), ("before_noon", "ก่อนเที่ยง"),
            ("noon_15", "12:00–15:00"), ("15_18", "15:00–18:00"),
            ("after_18", "หลัง 18:00"),
        ),
    },
    {
        "id": "alcohol_frequency", "section": "food_drink", "priority": 100,
        "title": "โดยทั่วไปคุณดื่มแอลกอฮอล์บ่อยแค่ไหน?",
        "help": "ตอบได้โดยไม่ต้องระบุชนิดหรือปริมาณละเอียด",
        "type": "select", "minimum_sessions": 3, "sensitive": True,
        "options": _options(
            ("never", "ไม่ดื่ม"), ("monthly", "น้อยกว่า 1 ครั้ง/สัปดาห์"),
            ("weekly", "1–2 ครั้ง/สัปดาห์"),
            ("frequent", "3 ครั้ง/สัปดาห์ขึ้นไป"),
            ("prefer_not", "ไม่ต้องการระบุ"),
        ),
    },
    {
        "id": "late_meal_frequency", "section": "food_drink", "priority": 110,
        "title": "คุณทานมื้อใหญ่ภายใน 2 ชั่วโมงก่อนนอนบ่อยแค่ไหน?",
        "help": "ใช้เป็นบริบทการพักและความสบายของร่างกาย",
        "type": "select", "minimum_sessions": 3,
        "options": _options(
            ("never", "แทบไม่เคย"), ("sometimes", "บางครั้ง"),
            ("often", "บ่อย"), ("prefer_not", "ไม่ต้องการระบุ"),
        ),
    },
    {
        "id": "activity_days_week", "section": "activity", "priority": 120,
        "title": "ในหนึ่งสัปดาห์ คุณมีกิจกรรมที่ได้ขยับร่างกายกี่วัน?",
        "help": "นับการเดินเร็ว ออกกำลัง เล่นกีฬา หรือกิจกรรมที่ใกล้เคียง",
        "type": "integer", "minimum": 0, "maximum": 7,
        "suffix": "วัน/สัปดาห์", "minimum_sessions": 3,
    },
    {
        "id": "sedentary_time", "section": "activity", "priority": 130,
        "title": "โดยทั่วไปคุณนั่งหรือนิ่งต่อวันประมาณกี่ชั่วโมง?",
        "help": "เลือกช่วงโดยประมาณ ไม่ต้องจับเวลา",
        "type": "select", "minimum_sessions": 4,
        "options": _options(
            ("under_4", "น้อยกว่า 4 ชั่วโมง"), ("4_7", "4–7 ชั่วโมง"),
            ("8_10", "8–10 ชั่วโมง"), ("over_10", "มากกว่า 10 ชั่วโมง"),
        ),
    },
    {
        "id": "sleep_position", "section": "comfort", "priority": 140,
        "title": "ท่านอนที่คุณใช้บ่อยที่สุดคือแบบใด?",
        "help": "ช่วยอ่านการขยับบนเตียงและจดจำค่าความสบาย",
        "type": "select", "minimum_sessions": 4,
        "options": _options(
            ("side", "ตะแคง"), ("back", "หงาย"),
            ("stomach", "คว่ำ"), ("mixed", "เปลี่ยนหลายท่า"),
        ),
    },
    {
        "id": "night_interruption", "section": "sleep_context", "priority": 150,
        "title": "อะไรทำให้คุณตื่นหรือพักไม่ต่อเนื่องบ่อยที่สุด?",
        "help": "ใช้จัดกลุ่มบริบท ไม่ใช่การวินิจฉัยสาเหตุ",
        "type": "select", "minimum_sessions": 5, "sensitive": True,
        "options": _options(
            ("none", "ไม่ค่อยตื่น"), ("bathroom", "เข้าห้องน้ำ"),
            ("environment", "แสง เสียง หรืออุณหภูมิ"),
            ("discomfort", "ไม่สบายตัวหรือปวด"),
            ("breathing", "หายใจไม่สะดวก"), ("unknown", "ไม่แน่ใจ"),
            ("prefer_not", "ไม่ต้องการระบุ"),
        ),
    },
    {
        "id": "snoring_observed", "section": "sleep_context", "priority": 160,
        "title": "มีคนเคยสังเกตว่าคุณกรนหรือไม่?",
        "help": "เป็นข้อมูลรายงานตนเองและไม่ใช่ผลตรวจภาวะหยุดหายใจ",
        "type": "select", "minimum_sessions": 5, "sensitive": True,
        "options": _options(
            ("never", "ไม่เคย/ไม่ทราบ"), ("sometimes", "บางครั้ง"),
            ("often", "บ่อย"), ("prefer_not", "ไม่ต้องการระบุ"),
        ),
    },
)

QUESTION_BY_ID = {question["id"]: question for question in QUESTION_CATALOG}
SECTION_LABELS = {
    "goals": "เป้าหมาย", "sleep_schedule": "การนอน",
    "food_drink": "การกินและดื่ม", "activity": "กิจกรรม",
    "comfort": "ความสบาย", "sleep_context": "บริบทการพัก",
}


def _utc_now(now: Optional[datetime] = None) -> datetime:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_utc(value: Any) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _new_state() -> dict[str, Any]:
    return {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "questionnaire_version": QUESTIONNAIRE_VERSION,
        "consent": {
            "status": "pending", "version": CONSENT_VERSION,
            "updated_at_utc": None,
        },
        "answers": {}, "skipped_until": {}, "next_prompt_after_utc": None,
        "updated_at_utc": None,
    }


def normalise_state(profile: Mapping[str, Any]) -> dict[str, Any]:
    raw = profile.get("progressive_profile")
    state = deepcopy(raw) if isinstance(raw, dict) else _new_state()
    state["schema_version"] = PROFILE_SCHEMA_VERSION
    state["questionnaire_version"] = QUESTIONNAIRE_VERSION
    consent = state.get("consent") if isinstance(state.get("consent"), dict) else {}
    if consent.get("status") not in {"pending", "granted", "declined"}:
        consent["status"] = "pending"
    consent["version"] = CONSENT_VERSION
    consent.setdefault("updated_at_utc", None)
    state["consent"] = consent
    state["answers"] = {
        key: value for key, value in (state.get("answers") or {}).items()
        if key in QUESTION_BY_ID and isinstance(value, dict)
    }
    state["skipped_until"] = {
        key: value for key, value in (state.get("skipped_until") or {}).items()
        if key in QUESTION_BY_ID and _parse_utc(value)
    }
    state.setdefault("next_prompt_after_utc", None)
    state.setdefault("updated_at_utc", None)
    return state


def _relevant(question: Mapping[str, Any], profile: Mapping[str, Any]) -> bool:
    minimum_sessions = int(question.get("minimum_sessions") or 0)
    if int(profile.get("sessions") or 0) < minimum_sessions:
        return False
    genders = question.get("genders")
    return not genders or str(profile.get("gender") or "unspecified") in genders


def _question_public(question: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {
        "id", "section", "title", "help", "type", "options", "minimum",
        "maximum", "suffix", "sensitive",
    }
    return {key: deepcopy(value) for key, value in question.items() if key in allowed}


def validate_answer(question_id: str, value: Any) -> Any:
    question = QUESTION_BY_ID.get(str(question_id or ""))
    if not question:
        raise ValueError("unknown_question")
    answer_type = question["type"]
    if answer_type == "select":
        candidate = str(value or "").strip()
        if candidate not in {item["value"] for item in question.get("options") or []}:
            raise ValueError("invalid_option")
        return candidate
    if answer_type == "time":
        candidate = str(value or "").strip()
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", candidate):
            raise ValueError("invalid_time")
        return candidate
    if answer_type == "integer":
        if isinstance(value, bool):
            raise ValueError("invalid_integer")
        try:
            candidate = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid_integer") from exc
        if not math.isfinite(float(candidate)):
            raise ValueError("invalid_integer")
        if candidate < int(question["minimum"]) or candidate > int(question["maximum"]):
            raise ValueError("integer_out_of_range")
        return candidate
    raise ValueError("unsupported_question_type")


def set_consent(
    profile: MutableMapping[str, Any], granted: bool, *, now: Optional[datetime] = None,
) -> dict[str, Any]:
    timestamp = _utc_now(now).isoformat()
    state = normalise_state(profile)
    state["consent"] = {
        "status": "granted" if granted else "declined",
        "version": CONSENT_VERSION, "updated_at_utc": timestamp,
    }
    # Optional lifestyle answers have consent as their only local purpose. A
    # withdrawal therefore deletes them instead of merely hiding them.
    if not granted:
        state["answers"] = {}
        state["skipped_until"] = {}
        state["next_prompt_after_utc"] = None
    else:
        state["next_prompt_after_utc"] = None
    state["updated_at_utc"] = timestamp
    profile["progressive_profile"] = state
    return state


def apply_answer(
    profile: MutableMapping[str, Any], question_id: str, value: Any, *,
    now: Optional[datetime] = None, source: str = "user_questionnaire",
) -> dict[str, Any]:
    moment = _utc_now(now)
    state = normalise_state(profile)
    if state["consent"]["status"] != "granted":
        raise PermissionError("progressive_profile_consent_required")
    answer = validate_answer(question_id, value)
    state["answers"][question_id] = {
        "value": answer, "answered_at_utc": moment.isoformat(),
        "source": source, "questionnaire_version": QUESTIONNAIRE_VERSION,
    }
    state["skipped_until"].pop(question_id, None)
    state["next_prompt_after_utc"] = (
        moment + timedelta(hours=ANSWER_COOLDOWN_HOURS)
    ).isoformat()
    state["updated_at_utc"] = moment.isoformat()
    profile["progressive_profile"] = state
    return state


def delete_answer(
    profile: MutableMapping[str, Any], question_id: str, *,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    if question_id not in QUESTION_BY_ID:
        raise ValueError("unknown_question")
    moment = _utc_now(now)
    state = normalise_state(profile)
    state["answers"].pop(question_id, None)
    state["skipped_until"].pop(question_id, None)
    state["next_prompt_after_utc"] = None
    state["updated_at_utc"] = moment.isoformat()
    profile["progressive_profile"] = state
    return state


def defer_question(
    profile: MutableMapping[str, Any], question_id: Optional[str] = None, *,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    moment = _utc_now(now)
    state = normalise_state(profile)
    until = moment + timedelta(days=DEFER_DAYS)
    if question_id:
        if question_id not in QUESTION_BY_ID:
            raise ValueError("unknown_question")
        state["skipped_until"][question_id] = until.isoformat()
    state["next_prompt_after_utc"] = until.isoformat()
    state["updated_at_utc"] = moment.isoformat()
    profile["progressive_profile"] = state
    return state


def _next_available(
    profile: Mapping[str, Any], state: Mapping[str, Any], now: datetime,
) -> Optional[dict[str, Any]]:
    answers = state.get("answers") or {}
    skipped = state.get("skipped_until") or {}
    for question in QUESTION_CATALOG:
        question_id = question["id"]
        if question_id in answers or not _relevant(question, profile):
            continue
        skip_until = _parse_utc(skipped.get(question_id))
        if skip_until and skip_until > now:
            continue
        return _question_public(question)
    return None


def public_snapshot(
    profile: Mapping[str, Any], *, now: Optional[datetime] = None,
) -> dict[str, Any]:
    moment = _utc_now(now)
    state = normalise_state(profile)
    relevant = [q for q in QUESTION_CATALOG if _relevant(q, profile)]
    answer_ids = set(state["answers"])
    answered = sum(1 for question in relevant if question["id"] in answer_ids)
    total = len(relevant)
    available = _next_available(profile, state, moment)
    next_after = _parse_utc(state.get("next_prompt_after_utc"))
    due = not next_after or next_after <= moment
    sections = []
    for section, label in SECTION_LABELS.items():
        questions = [q for q in relevant if q["section"] == section]
        if not questions:
            continue
        completed = sum(q["id"] in answer_ids for q in questions)
        sections.append({
            "key": section, "label": label, "answered": completed,
            "total": len(questions),
            "percent": round(completed / len(questions) * 100),
        })
    return {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "questionnaire_version": QUESTIONNAIRE_VERSION,
        "consent": deepcopy(state["consent"]),
        "progress": {
            "answered": answered, "total": total,
            "percent": round(answered / total * 100) if total else 100,
            "sections": sections,
        },
        "prompt": available if due and state["consent"]["status"] == "granted" else None,
        "available_question": (
            available if state["consent"]["status"] == "granted" else None
        ),
        "next_prompt_after_utc": state.get("next_prompt_after_utc"),
        "answers": {
            question_id: deepcopy(answer)
            for question_id, answer in state["answers"].items()
        },
        "guardrails": {
            "optional": True, "blocking": False, "one_question_at_a_time": True,
            "answer_cooldown_hours": ANSWER_COOLDOWN_HOURS,
            "skip_cooldown_days": DEFER_DAYS,
            "sleep_stage_direct_input": False,
            "automatic_actuation": False,
            "intended_use": "wellness_context_and_personalised_recommendations",
        },
    }


def session_context_snapshot(profile: Mapping[str, Any]) -> Optional[dict[str, Any]]:
    """Freeze consented lifestyle context at Session start for later analysis."""
    state = normalise_state(profile)
    if state["consent"]["status"] != "granted":
        return None
    return {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "questionnaire_version": QUESTIONNAIRE_VERSION,
        "consent_version": CONSENT_VERSION,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "answers": {
            question_id: answer.get("value")
            for question_id, answer in state["answers"].items()
            if question_id in QUESTION_BY_ID
        },
        "intended_use": "session_context_not_sleep_stage_evidence",
    }


def admin_progress_summary(profile: Mapping[str, Any]) -> dict[str, Any]:
    """Return completeness only; `/api/users` must not expose raw answers."""
    snapshot = public_snapshot(profile)
    return {
        "consent_status": snapshot["consent"]["status"],
        "answered": snapshot["progress"]["answered"],
        "total": snapshot["progress"]["total"],
        "percent": snapshot["progress"]["percent"],
        "questionnaire_version": snapshot["questionnaire_version"],
    }
