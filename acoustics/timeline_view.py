"""Allowlisted acoustic event cards, status text and contract metadata."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .level_events import RAPID_CHANGE_DB, SUSTAINED_LEVEL_DBA, SUSTAINED_MIN_SECONDS

MAX_VISIBLE_EVENTS = 24
DETECTOR_VERSION = "zeep-level-pattern-v1.0+dsp-label-v0.1"


def detector_block() -> dict[str, Any]:
    return {
        "version": DETECTOR_VERSION,
        "method": "deterministic_level_rules",
        "cadence_source": "per_sample_or_configured_session_cadence",
        "certified_laeq": False,
        "thresholds": {
            "rapid_change_db": RAPID_CHANGE_DB,
            "review_level_dba": SUSTAINED_LEVEL_DBA,
            "review_span_s": SUSTAINED_MIN_SECONDS,
        },
    }


def privacy_block() -> dict[str, bool]:
    return {
        "raw_audio_transmitted": False,
        "raw_audio_retained": False,
        "speech_content_processed": False,
    }


def impact_block() -> dict[str, bool]:
    return dict.fromkeys(
        ("sleep_state", "sleep_score", "recovery_score", "control"),
        False,
    )


def session_block(
    active: bool,
    recording: bool,
    session_id: str | None,
    started_at_epoch_s: float | None,
) -> dict[str, Any]:
    return {
        "active": bool(active),
        "recording": bool(recording),
        "session_id": session_id if active else None,
        "started_at_epoch_s": started_at_epoch_s,
    }


def timeline_status(active: bool, recording: bool, valid_count: int) -> str:
    if not active:
        return "no_session"
    if not recording:
        return "waiting_for_recording"
    if valid_count < 2:
        return "collecting" if valid_count else "no_data"
    return "ready"


def visible_events(events: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    quotas = {
        "missing_data": 4,
        "sustained_high": 5,
        "rapid_change": 6,
        "snore_like": 5,
        "speech_like": 5,
        "impact_like": 5,
        "steady_equipment_like": 4,
    }
    newest = sorted(
        events,
        key=lambda event: float(event.get("start_epoch_s") or 0),
        reverse=True,
    )
    selected: list[Mapping[str, Any]] = []
    for key, quota in quotas.items():
        selected.extend([event for event in newest if event.get("key") == key][:quota])
    selected_ids = {str(event.get("id")) for event in selected}
    selected.extend(
        event for event in newest if str(event.get("id")) not in selected_ids
    )
    selected = selected[:MAX_VISIBLE_EVENTS]
    return sorted(
        (dict(event) for event in selected),
        key=lambda event: float(event.get("start_epoch_s") or 0),
    )


def event_summary(
    events: Sequence[Mapping[str, Any]],
    visible: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    keys = (
        "rapid_change",
        "sustained_high",
        "missing_data",
        "snore_like",
        "speech_like",
        "impact_like",
        "steady_equipment_like",
    )
    counts = {
        key: sum(1 for event in events if event.get("key") == key) for key in keys
    }
    return {
        "total_count": len(events),
        "visible_count": len(visible),
        "truncated": len(visible) < len(events),
        "counts": counts,
    }


def timeline_message(status: str, summary: Mapping[str, Any]) -> str:
    if status == "no_session":
        return "เริ่มการพักเพื่อดูประวัติเสียงตามเวลา"
    if status == "waiting_for_recording":
        return "รอเริ่มบันทึกเมื่อสัญญาณชีพจรและการหายใจพร้อม"
    if status == "no_data":
        return "เริ่มบันทึกแล้ว แต่ยังไม่มีค่าระดับเสียงที่ใช้ได้"
    if status == "collecting":
        return "กำลังรวบรวมข้อมูลเพื่อแสดงกราฟเสียง"
    count = int(summary.get("observed_event_count") or 0)
    return (
        f"พบช่วงระดับเสียงที่ควรย้อนดู {count} ช่วง"
        if count
        else "ระดับเสียงยังไม่มีช่วงเปลี่ยนแปลงที่เด่นชัด"
    )
