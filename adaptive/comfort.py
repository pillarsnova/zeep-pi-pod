"""Personal comfort evidence from explicit, optional user feedback only."""

from __future__ import annotations

import statistics
from typing import Any

from adaptive.outcomes import window_summary
from sessions.sleep_event_data import event_value, parse_timestamp

VERSION = "zeep.personal-comfort.v1"
COMFORT_METRICS = ("temperature", "humidity", "lux", "sound")


def cohort(session: dict[str, Any]) -> str:
    """Keep modes and Nap targets separate; never coerce auto into Nap."""
    mode = session.get("rest_mode")
    if mode in {"sleep", "overnight"}:
        return "overnight"
    if mode in {"nap_recovery", "nap", "short_nap", "cycle_nap", "shift_rest"}:
        seconds = session.get("target_duration_s")
        if isinstance(seconds, (int, float)) and not isinstance(seconds, bool):
            return f"nap_{round(seconds / 60)}"
        return "nap_unspecified"
    return "unknown"


def feedback_evidence(
    session: dict[str, Any],
    samples: list[dict[str, Any]],
    *,
    now: float,
    response: str,
    actor_role: str,
) -> dict[str, Any]:
    """Bind a response to the explicitly described last-five-minute window."""
    end = min(now, parse_timestamp(session.get("end_time")) or now)
    start = end - 300
    return {
        "version": VERSION,
        "response": response,
        "cohort": cohort(session),
        "source": "self_report" if actor_role == "user" else "staff_observation",
        "use_for_personalization": True,
        "window_start": start,
        "window_end": end,
        "metrics": {
            key: window_summary(samples, key, start, end) for key in COMFORT_METRICS
        },
        "scope": "last_five_minutes_of_recording",
        "not_a_health_score": True,
    }


def build_comfort_reference(
    current: dict[str, Any],
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Use latest self-report per prior completed same-cohort Session."""
    current_start = parse_timestamp(current.get("start_time")) or 0
    latest = {}
    for row in rows:
        ended = parse_timestamp(row.get("end_time"))
        answered = parse_timestamp(row.get("timestamp"))
        if (
            not ended
            or ended >= current_start
            or (answered is not None and answered >= current_start)
            or cohort(current) == "unknown"
        ):
            continue
        value = event_value(row)
        if (
            value.get("source") == "self_report"
            and value.get("use_for_personalization") is True
            and value.get("cohort") == cohort(current)
        ):
            latest[row["session_id"]] = value
    accepted = [
        value for value in latest.values() if value.get("response") == "comfortable"
    ]
    ranges = {}
    for key in COMFORT_METRICS:
        values = []
        for record in accepted:
            metric = (record.get("metrics") or {}).get(key) or {}
            value = metric.get("value")
            if (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and metric.get("coverage", 0) >= 0.8
            ):
                values.append(value)
        if values:
            ranges[key] = {
                "low": min(values),
                "high": max(values),
                "typical": round(statistics.median(values), 2),
                "sessions": len(values),
                "basis": "user_reported_comfort",
            }
    count = len(accepted)
    return {
        "version": VERSION,
        "cohort": cohort(current),
        "sessions": count,
        "status": "learning" if count < 3 else "personal_reference",
        "ranges": ranges,
        "minimum_for_reference": 3,
        "message": (
            "ยังไม่มีความเห็นจากการพักก่อนหน้า"
            if not count
            else f"อ้างอิงช่วงที่คุณบอกว่าสบายจาก {count} ครั้งก่อน"
        ),
        "score_used_as_preference": False,
        "current_session_used": False,
    }
