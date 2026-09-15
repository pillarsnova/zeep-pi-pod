"""Formula-safe score history for longitudinal user summaries."""

from __future__ import annotations

import statistics
from collections.abc import Mapping
from typing import Any

from zeep_pod.sessions.user_baseline_context import baseline_context


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def score_entry(session: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return one data-backed canonical score, or no learning evidence."""
    if int(session.get("sample_count") or 0) <= 0:
        return None
    score = _mapping(session.get("score"))
    value = _number(score.get("value"))
    if score.get("available") is not True or value is None:
        return None
    return {
        "session_id": session.get("session_id"),
        "ended_at_utc": session.get("ended_at_utc"),
        "value": round(value, 1),
        "formula_version": score.get("formula_version"),
    }


def score_trend(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Compare only the latest two results using the same named formula."""
    if entries and not entries[0].get("formula_version"):
        return _unavailable_trend(
            "formula_unverified",
            "ยังเทียบแนวโน้มไม่ได้ เพราะไม่พบรุ่นสูตรคะแนน",
        )
    if len(entries) < 2:
        formula = entries[0].get("formula_version") if entries else None
        return _unavailable_trend(
            "insufficient_history",
            "กำลังสะสมข้อมูลในรูปแบบนี้",
            formula=formula,
            count=len(entries),
        )
    latest = entries[0]
    formula = latest.get("formula_version")
    previous = next(
        (item for item in entries[1:] if item.get("formula_version") == formula),
        None,
    )
    if previous is None:
        return _unavailable_trend(
            "formula_changed",
            "เริ่มแนวโน้มใหม่หลังปรับสูตรคะแนน",
            formula=formula,
            count=1,
        )
    delta = round(float(latest["value"]) - float(previous["value"]), 1)
    direction = "higher" if delta >= 2 else "lower" if delta <= -2 else "stable"
    labels = {
        "higher": "คะแนนที่สรุปล่าสุดสูงขึ้น",
        "lower": "คะแนนที่สรุปล่าสุดลดลงเล็กน้อย",
        "stable": "คะแนนที่สรุปล่าสุดใกล้เคียงครั้งก่อน",
    }
    comparable = sum(item.get("formula_version") == formula for item in entries)
    return {
        "available": True,
        "direction": direction,
        "label": labels[direction],
        "change_points": delta,
        "formula_version": formula,
        "comparable_scores": comparable,
        "method": "latest_vs_previous_same_formula",
    }


def _unavailable_trend(
    direction: str,
    label: str,
    *,
    formula: str | None = None,
    count: int = 0,
) -> dict[str, Any]:
    return {
        "available": False,
        "direction": direction,
        "label": label,
        "change_points": None,
        "formula_version": formula,
        "comparable_scores": count,
        "method": "latest_vs_previous_same_formula",
    }


def _nap_target(session: Mapping[str, Any]) -> tuple[str, float] | None:
    target = _mapping(_mapping(session.get("mode")).get("target"))
    minutes = _number(target.get("minutes"))
    key = str(target.get("key") or "").strip().casefold()
    if key in {"nap_30", "nap_30m"} or minutes == 30:
        return "nap_30", 30.0
    if key in {"nap_90", "nap_90m"} or minutes == 90:
        return "nap_90", 90.0
    return None


def nap_target_histories(
    sessions: list[Mapping[str, Any]],
    baseline: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Publish independent 30- and 90-minute score cohorts."""
    histories = []
    for target_key, minutes in (("nap_30", 30.0), ("nap_90", 90.0)):
        target_sessions = [
            session
            for session in sessions
            if _nap_target(session) == (target_key, minutes)
        ]
        if not target_sessions:
            continue
        entries = [
            entry
            for session in target_sessions
            if (entry := score_entry(session)) is not None
        ]
        active_formula = entries[0].get("formula_version") if entries else None
        comparable = (
            [
                entry
                for entry in entries
                if entry.get("formula_version") == active_formula
            ]
            if active_formula
            else []
        )
        values = [float(entry["value"]) for entry in comparable]
        latest = score_entry(target_sessions[0])
        histories.append({
            "key": target_key,
            "minutes": minutes,
            "session_count": len(target_sessions),
            "scored_count": len(entries),
            "comparable_scored_count": len(comparable),
            "without_score_count": len(target_sessions) - len(entries),
            "latest_score": latest["value"] if latest else None,
            "average_score": (
                round(sum(values) / len(values), 1) if values else None
            ),
            "median_score": (
                round(statistics.median(values), 1) if values else None
            ),
            "active_formula_version": active_formula,
            "trend": score_trend(entries),
            "baseline": baseline_context(
                baseline,
                "nap_recovery",
                target_key=target_key,
            ),
            "recent_scores": comparable[:5],
        })
    return histories
