"""Build the user-visible Sleep timeline from persisted decision events.

The module deliberately does not read SQLite or Raw Sensor rows. New
Recording intervals persist five-state decisions plus confirmed OFF BED;
WAIT/NO DATA are accepted only as legacy evidence-quality metadata. Callers
provide those streams after applying annotations.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from sleep_system_policy import (
    ZEEP_OFF_BED_DATA_STATUSES,
    ZEEP_SLEEP_STATES,
)

from .cadence import sample_interval_seconds
from .report_projection import weighted_sleep_state_counts


SLEEP_STATES = ("wake", "n1", "n2", "n3", "rem")


def _parse_datetime(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _decision_metadata(point: dict[str, Any], key: str) -> Any:
    """Read current metadata with a legacy nested-confirmation fallback."""
    if key in point:
        return point.get(key)
    confirmation = point.get("confirmation")
    if isinstance(confirmation, dict):
        return confirmation.get(key)
    return None


def _grouping_metadata(point: dict[str, Any]) -> tuple[Any, ...]:
    score_eligible = _decision_metadata(point, "score_eligible")
    return (
        bool(_decision_metadata(point, "held_previous_state")),
        bool(_decision_metadata(point, "provisional")),
        score_eligible if isinstance(score_eligible, bool) else None,
        str(_decision_metadata(point, "data_status") or ""),
        str(_decision_metadata(point, "pending_state") or ""),
        str(_decision_metadata(point, "decision_kind") or ""),
    )


def _group_stage_points(
    points: list[dict[str, Any]],
    fallback_interval_s: float,
) -> list[list[dict[str, Any]]]:
    groups: list[list[dict[str, Any]]] = []
    previous_time: datetime | None = None
    previous_interval = fallback_interval_s
    for point in points:
        current_time = _parse_datetime(
            point.get("window_end") or point.get("timestamp")
        )
        current_interval = sample_interval_seconds(
            point.get("sample_interval_s"), fallback_interval_s
        )
        gap_s = (
            (current_time - previous_time).total_seconds()
            if current_time is not None and previous_time is not None
            else 0.0
        )
        previous_point = groups[-1][-1] if groups else None
        begins_group = (
            previous_point is None
            or previous_point.get("state") != point.get("state")
            or _grouping_metadata(previous_point) != _grouping_metadata(point)
            or current_interval != previous_interval
            or gap_s > max(previous_interval, current_interval) * 1.8
            or gap_s <= 0.0
        )
        if begins_group:
            groups.append([point])
        else:
            groups[-1].append(point)
        previous_time = current_time
        previous_interval = current_interval
    return groups


def _mean_probabilities(points: list[dict[str, Any]]) -> dict[str, float]:
    result: dict[str, float] = {}
    for state in SLEEP_STATES:
        values = [
            float((point.get("probabilities") or {})[state])
            for point in points
            if isinstance(
                (point.get("probabilities") or {}).get(state),
                (int, float),
            )
        ]
        if values:
            result[state] = round(sum(values) / len(values), 4)
    return result


def _mean_metrics(points: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in ("mean_hr", "mean_rr", "movement_ratio"):
        values = [
            float((point.get("metrics") or {})[key])
            for point in points
            if isinstance((point.get("metrics") or {}).get(key), (int, float))
        ]
        if values:
            result[key] = round(sum(values) / len(values), 3)
    bed_statuses = [
        str((point.get("metrics") or {}).get("bed_status"))
        for point in points
        if (point.get("metrics") or {}).get("bed_status")
    ]
    if bed_statuses:
        result["bed_status"] = Counter(bed_statuses).most_common(1)[0][0]
    return result


def _period_boundaries(
    points: list[dict[str, Any]],
    report_end: str,
    fallback_interval_s: float,
) -> tuple[datetime | None, datetime | None, list[float]]:
    first, last = points[0], points[-1]
    intervals = [
        sample_interval_seconds(point.get("sample_interval_s"), fallback_interval_s)
        for point in points
    ]
    first_end = _parse_datetime(first.get("window_end") or first.get("timestamp"))
    last_end = _parse_datetime(
        last.get("window_end") or last.get("timestamp") or report_end
    )
    start = (
        first_end - timedelta(seconds=intervals[0])
        if first_end is not None
        else None
    )
    return start, last_end or _parse_datetime(report_end), intervals


def _period_from_group(
    points: list[dict[str, Any]],
    *,
    report_end: str,
    fallback_interval_s: float,
    fallback_estimator: str | None,
) -> dict[str, Any]:
    first, last = points[0], points[-1]
    start, end, intervals = _period_boundaries(
        points, report_end, fallback_interval_s
    )
    confidences = [
        point.get("confidence")
        for point in points
        if point.get("confidence")
    ]
    held_rounds = sum(
        bool(_decision_metadata(point, "held_previous_state")) for point in points
    )
    provisional_rounds = sum(
        bool(_decision_metadata(point, "provisional")) for point in points
    )
    pending_states = [
        str(_decision_metadata(point, "pending_state"))
        for point in points
        if _decision_metadata(point, "pending_state") in ZEEP_SLEEP_STATES
    ]
    score_value = _decision_metadata(first, "score_eligible")
    state = first.get("state")
    is_sleep_stage = state in ZEEP_SLEEP_STATES
    excluded_score = _decision_metadata(first, "excluded_from_score")
    excluded_baseline = _decision_metadata(
        first, "excluded_from_personal_baseline"
    )
    return {
        "start_time": start.isoformat() if start else first.get("timestamp"),
        "end_time": end.isoformat() if end else last.get("timestamp"),
        "calculated_at": last.get("timestamp"),
        "duration_s": round(sum(intervals), 1),
        "round_count": len(points),
        "sample_interval_s": (
            intervals[0] if all(value == intervals[0] for value in intervals) else None
        ),
        "state": state,
        "label": first.get("label"),
        "sleep_stage": is_sleep_stage,
        "excluded_from_stage_statistics": not is_sleep_stage,
        "excluded_from_score": (
            bool(excluded_score)
            if isinstance(excluded_score, bool)
            else not is_sleep_stage
        ),
        "excluded_from_personal_baseline": (
            bool(excluded_baseline)
            if isinstance(excluded_baseline, bool)
            else not is_sleep_stage
        ),
        "confidence": (
            Counter(confidences).most_common(1)[0][0]
            if confidences
            else None
        ),
        "probabilities": _mean_probabilities(points),
        "reason": last.get("reason"),
        "metrics": _mean_metrics(points),
        "analysis_window_samples": last.get("sample_count"),
        "state_changed": True,
        "held_previous_state": held_rounds > 0,
        "continuity_hold_rounds": held_rounds,
        "provisional_rounds": provisional_rounds,
        "provisional": provisional_rounds > 0,
        "score_eligible": score_value if isinstance(score_value, bool) else None,
        "data_status": _decision_metadata(first, "data_status"),
        "decision_kind": _decision_metadata(first, "decision_kind"),
        "pending_state": (
            Counter(pending_states).most_common(1)[0][0] if pending_states else None
        ),
        "challenger_counted_as_new_state": False if held_rounds else None,
        "estimator_version": last.get("estimator_version") or fallback_estimator,
        "stage_annotation": last.get("stage_annotation"),
    }


def compress_sleep_stage_points(
    stage_points: list[dict[str, Any]],
    *,
    report_end: str,
    sample_interval_s: float = 5.0,
    fallback_estimator: str | None = None,
) -> list[dict[str, Any]]:
    """Compress versioned decisions into contiguous, homogeneous periods."""
    if not stage_points:
        return []
    interval = max(0.1, float(sample_interval_s or 5.0))
    return [
        _period_from_group(
            points,
            report_end=report_end,
            fallback_interval_s=interval,
            fallback_estimator=fallback_estimator,
        )
        for points in _group_stage_points(stage_points, interval)
    ]


def _point_end(point: dict[str, Any]) -> tuple[str, Any]:
    value = (
        point.get("attribution_end")
        or point.get("window_end")
        or point.get("timestamp")
    )
    parsed = _parse_datetime(value)
    if parsed is None:
        return ("text", str(value))
    return ("epoch", round(parsed.timestamp(), 3))


def history_sleep_timeline(
    stage_points: list[dict[str, Any]],
    status_points: list[dict[str, Any]],
    *,
    report_end: str,
    sample_interval_s: float,
    fallback_estimator: str | None,
) -> tuple[list[dict[str, Any]], bool]:
    """Merge five-state decisions with authoritative OFF BED boundaries."""
    points_by_end = {_point_end(point): point for point in stage_points}
    for point in status_points:
        state = str(point.get("state") or "").strip().lower()
        status = str(
            _decision_metadata(point, "data_status") or ""
        ).strip().lower()
        if state == "off_bed" or status in ZEEP_OFF_BED_DATA_STATUSES:
            points_by_end[_point_end(point)] = point
    decision_points = sorted(points_by_end.values(), key=_point_end)
    periods = compress_sleep_stage_points(
        decision_points,
        report_end=report_end,
        sample_interval_s=sample_interval_s,
        fallback_estimator=fallback_estimator,
    )
    # WAIT/NO DATA remain evidence-quality metadata. They never erase an
    # occupied five-state interval in the user-visible history.
    return periods, not status_points


def history_sleep_state_counts(
    samples: list[dict[str, Any]],
    *,
    sample_interval_s: float,
) -> tuple[dict[str, float], dict[str, float]]:
    """Return display and score counts from one projected history stream.

    Mixed-cadence and partial-tail rows are expressed in units of the report
    interval, matching the live finalizer.  Operational rows have no five-state
    label and therefore remain outside both count maps.
    """
    return weighted_sleep_state_counts(
        samples,
        sample_interval_s=sample_interval_s,
    )


def fill_history_sleep_timeline_continuity(
    periods: list[dict[str, Any]],
    *,
    session_start: Any,
    classification_end: Any,
    fallback_estimator: str | None = None,
) -> list[dict[str, Any]]:
    """Partition the full recording into five-state or OFF BED periods.

    This is deliberately a small deterministic rule: before the first direct
    decision use W; between decisions hold the preceding State; after a
    confirmed OFF BED boundary remain OFF BED until a later five-state
    decision proves that the user returned. Synthetic five-state periods can
    score but never teach the Personal Baseline.
    """
    start = _parse_datetime(session_start)
    end = _parse_datetime(classification_end)
    if start is None or end is None or end <= start:
        return periods

    valid = []
    for period in periods:
        period_start = _parse_datetime(period.get("start_time"))
        period_end = _parse_datetime(period.get("end_time"))
        state = str(period.get("state") or "").strip().lower()
        if (
            period_start is None
            or period_end is None
            or period_end <= period_start
            or state not in {*SLEEP_STATES, "off_bed"}
        ):
            continue
        valid.append((period_start, period_end, state, period))
    valid.sort(key=lambda item: (item[0], item[1]))

    completed: list[dict[str, Any]] = []
    cursor = start
    held_state = "wake"
    for period_start, period_end, state, source in valid:
        if period_end <= cursor or period_start >= end:
            continue
        clipped_start = max(start, period_start)
        clipped_end = min(end, period_end)
        if clipped_start > cursor:
            completed.append(_continuity_period(
                held_state,
                cursor,
                clipped_start,
                fallback_estimator=fallback_estimator,
                initial=not completed,
            ))
        visible_start = max(cursor, clipped_start)
        if clipped_end > visible_start:
            item = dict(source)
            item["start_time"] = visible_start.isoformat()
            item["end_time"] = clipped_end.isoformat()
            item["duration_s"] = round(
                (clipped_end - visible_start).total_seconds(), 3
            )
            completed.append(item)
            cursor = clipped_end
            held_state = state
    if cursor < end:
        completed.append(_continuity_period(
            held_state,
            cursor,
            end,
            fallback_estimator=fallback_estimator,
            initial=not completed,
        ))
    return completed


def _continuity_period(
    state: str,
    start: datetime,
    end: datetime,
    *,
    fallback_estimator: str | None,
    initial: bool,
) -> dict[str, Any]:
    duration_s = round((end - start).total_seconds(), 3)
    if state == "off_bed":
        return {
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "duration_s": duration_s,
            "round_count": 0,
            "sample_interval_s": None,
            "state": "off_bed",
            "label": (
                "OFF · ไม่มีผู้ใช้งานบนเตียง"
            ),
            "sleep_stage": False,
            "excluded_from_stage_statistics": True,
            "excluded_from_score": True,
            "excluded_from_personal_baseline": True,
            "score_eligible": False,
            "confidence": "operational",
            "probabilities": {},
            "metrics": {},
            "reason": (
                "คง OFF BED จนมีหลักฐานยืนยันว่ากลับขึ้นเตียง"
            ),
            "data_status": "off_bed_latched",
            "decision_kind": "occupancy_hold",
            "continuity_synthesized": True,
        }

    labels = {
        "wake": "W · ตื่น",
        "n1": "N1 · หลับตื้น / เคลิ้มหลับ",
        "n2": "N2 · หลับตื้นต่อเนื่อง",
        "n3": "N3 · หลับลึก",
        "rem": "REM · หลับฝัน",
    }
    return {
        "start_time": start.isoformat(),
        "end_time": end.isoformat(),
        "duration_s": duration_s,
        "round_count": 0,
        "sample_interval_s": None,
        "state": state,
        "label": labels[state],
        "sleep_stage": True,
        "excluded_from_stage_statistics": False,
        "excluded_from_score": False,
        "excluded_from_personal_baseline": True,
        "score_eligible": True,
        "confidence": "low",
        "probabilities": {},
        "metrics": {},
        "reason": (
            "เริ่ม Recording ที่ W ก่อนมีหลักฐานรอบแรก"
            if initial else
            "หลักฐานใหม่ยังไม่ยืนยัน · "
            "คง State ก่อนหน้าเพื่อให้เวลาต่อเนื่อง"
        ),
        "data_status": (
            "initial_awake_anchor" if initial else "continuity_hold"
        ),
        "decision_kind": (
            "initial_awake_anchor" if initial else "continuity_hold"
        ),
        "held_previous_state": not initial,
        "continuity_synthesized": True,
        "estimator_version": fallback_estimator,
    }


def clip_history_sleep_timeline(
    periods: list[dict[str, Any]],
    *,
    classification_end: str,
) -> list[dict[str, Any]]:
    """Stop human/operational decisions before terminal occupancy begins."""
    boundary = _parse_datetime(classification_end)
    if boundary is None:
        return periods
    clipped: list[dict[str, Any]] = []
    for period in periods:
        start = _parse_datetime(period.get("start_time"))
        end = _parse_datetime(period.get("end_time"))
        if start is None or end is None:
            clipped.append(period)
            continue
        if start >= boundary:
            continue
        if end <= boundary:
            clipped.append(period)
            continue
        if period.get("state") == "off_bed":
            continue
        item = dict(period)
        item["end_time"] = boundary.isoformat()
        item["duration_s"] = round(
            min(
                float(period.get("duration_s") or 0.0),
                max(0.0, (boundary - start).total_seconds()),
            ),
            1,
        )
        clipped.append(item)
    return clipped
