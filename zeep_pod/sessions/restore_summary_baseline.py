"""Mode-specific Personal Baseline and score-trend presentation helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sleep_system_policy import (
    RESTORE_BASELINE_COMPARISON_VERSION,
    RESTORE_BASELINE_MIN_COMPARISON_SESSIONS,
    RESTORE_BASELINE_STABLE_SESSIONS,
    RESTORE_TREND_MAX_SESSIONS,
)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _session_count(context: Mapping[str, Any]) -> int:
    for key in ("eligible_sessions", "sessions_used", "nights_used"):
        value = _number(context.get(key))
        if value is not None:
            return max(0, int(value))
    return 0


def _maturity(sessions: int) -> dict[str, Any]:
    if sessions >= RESTORE_BASELINE_STABLE_SESSIONS:
        key, label, confidence = "stable", "รูปแบบของคุณชัดเจนขึ้น", "high"
    elif sessions >= RESTORE_BASELINE_MIN_COMPARISON_SESSIONS:
        key, label, confidence = "active", "พร้อมเทียบกับรูปแบบของคุณ", "medium"
    elif sessions >= 3:
        key, label, confidence = "early", "เริ่มเห็นรูปแบบของคุณ", "low"
    else:
        key, label, confidence = "learning", "กำลังเรียนรู้", "insufficient"
    return {
        "key": key,
        "label": label,
        "confidence": confidence,
        "sessions_used": sessions,
        "comparison_minimum_sessions": (RESTORE_BASELINE_MIN_COMPARISON_SESSIONS),
        "stable_from_sessions": RESTORE_BASELINE_STABLE_SESSIONS,
    }


def _score_reference(
    context: Mapping[str, Any],
) -> tuple[float | None, list[float] | None]:
    reference = context.get("score_reference") or {}
    candidates = (
        reference.get("median") if isinstance(reference, Mapping) else None,
        context.get("score_median"),
        context.get("median_score"),
    )
    median = next(
        (value for item in candidates if (value := _number(item)) is not None),
        None,
    )
    raw_range = (reference.get("typical_range") if isinstance(reference, Mapping) else None) or context.get("score_typical_range")
    typical = None
    if isinstance(raw_range, (list, tuple)) and len(raw_range) == 2:
        low, high = _number(raw_range[0]), _number(raw_range[1])
        if low is not None and high is not None and low <= high:
            typical = [round(low, 1), round(high, 1)]
    return median, typical


def build_baseline_summary(
    context: Mapping[str, Any] | None,
    score: float | None,
    group: str,
) -> dict[str, Any]:
    """Compare with prior eligible Sessions selected by the caller."""
    record = dict(context or {})
    sessions = _session_count(record)
    maturity = _maturity(sessions)
    median, typical = _score_reference(record)
    comparison = {
        "available": False,
        "reason": ("ZEEP กำลังเรียนรู้รูปแบบของคุณจากการพักรูปแบบเดียวกัน และจะเปรียบเทียบได้ชัดขึ้นเมื่อมีข้อมูลจากหลายครั้ง" if sessions < RESTORE_BASELINE_MIN_COMPARISON_SESSIONS else "กำลังเตรียมค่ากลางของรูปแบบการพักนี้" if median is None else "กำลังเตรียมคะแนนของการพักครั้งนี้"),
    }
    if sessions >= RESTORE_BASELINE_MIN_COMPARISON_SESSIONS and median is not None and score is not None:
        delta = round(score - median, 1)
        if typical and score < typical[0]:
            key, label = "below_typical", "ต่ำกว่าช่วงที่พบเป็นประจำของคุณ"
        elif typical and score > typical[1]:
            key, label = "above_typical", "สูงกว่าช่วงที่พบเป็นประจำของคุณ"
        elif typical:
            key, label = "within_typical", "ใกล้ช่วงที่พบเป็นประจำของคุณ"
        elif delta >= 5:
            key, label = "above_typical", "สูงกว่าค่ากลางส่วนบุคคล"
        elif delta <= -5:
            key, label = "below_typical", "ต่ำกว่าค่ากลางส่วนบุคคล"
        else:
            key, label = "near_typical", "ใกล้ค่ากลางส่วนบุคคล"
        comparison = {
            "available": True,
            "key": key,
            "label": label,
            "current_score": round(score, 1),
            "baseline_median": round(median, 1),
            "delta_points": delta,
            "typical_range": typical,
            "mode_specific": True,
        }
    return {
        "version": RESTORE_BASELINE_COMPARISON_VERSION,
        "mode": group,
        "maturity": maturity,
        "comparison": comparison,
        "affects_source_score": False,
        "population_prior_is_cold_start_only": True,
        "must_not_mix_sleep_and_nap_sessions": True,
    }


def build_trend_summary(
    context: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Summarize 7/14/30 same-mode Sessions without a day-readiness claim."""
    values = []
    for value in (context or {}).get("scores", []):
        numeric = _number(value)
        if numeric is not None:
            values.append(max(0.0, min(100.0, numeric)))
    if len(values) < 3:
        return {
            "available": False,
            "reason": ("แนวโน้มจะพร้อมเมื่อมีผลโหมดเดียวกันอย่างน้อย 3 ครั้ง"),
            "windows": {},
        }
    windows = {}
    for size in (
        RESTORE_BASELINE_MIN_COMPARISON_SESSIONS,
        RESTORE_BASELINE_STABLE_SESSIONS,
        RESTORE_TREND_MAX_SESSIONS,
    ):
        selected = values[-size:]
        windows[str(size)] = {
            "session_count": len(selected),
            "average": round(sum(selected) / len(selected), 1),
            "latest": round(selected[-1], 1),
        }
    return {
        "available": True,
        "unit": "sessions",
        "windows": windows,
        "mode_specific": True,
        "whole_day_readiness_trend": False,
    }
