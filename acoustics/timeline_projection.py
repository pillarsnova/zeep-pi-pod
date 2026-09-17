"""Build a compact Admin projection of sound level across one live Session."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from sensors.sound import energy_average_db

from .label_events import detect_label_events, latest_classification
from .level_events import (
    DEFAULT_CADENCE_SECONDS,
    RAPID_CHANGE_DB,
    SUSTAINED_LEVEL_DBA,
    SUSTAINED_MIN_SECONDS,
    describe_level_pattern,
    detect_level_events,
    normalise_level_samples,
)

TIMELINE_SCHEMA = "zeep.acoustic.level-timeline"
TIMELINE_SCHEMA_VERSION = "1.1"
DEFAULT_DISPLAY_RANGE = (30.0, 130.0)
DEFAULT_MAX_POINTS = 240
MAX_VISIBLE_EVENTS = 24
DETECTOR_VERSION = "zeep-level-pattern-v1.0+dsp-label-v0.1"


def build_acoustic_timeline_snapshot(
    samples: Sequence[Mapping[str, Any]],
    *,
    session_id: str | None,
    session_active: bool,
    recording: bool,
    started_at_epoch_s: float | None = None,
    generated_at: datetime | None = None,
    display_range: tuple[float, float] = DEFAULT_DISPLAY_RANGE,
    cadence_s: float = DEFAULT_CADENCE_SECONDS,
    max_points: int = DEFAULT_MAX_POINTS,
) -> dict[str, Any]:
    """Return an allowlisted level timeline with no source classification."""
    generated = (generated_at or datetime.now(UTC)).astimezone(UTC)
    low, high = display_range
    cadence_s = max(1.0, float(cadence_s))
    rows = normalise_level_samples(
        samples,
        display_min=low,
        display_max=high,
        fallback_cadence_s=cadence_s,
    )
    valid_levels = [
        float(row["dba"]) for row in rows if row.get("dba") is not None
    ]
    level_events = detect_level_events(rows, cadence_s=cadence_s)
    label_events = detect_label_events(samples, cadence_s=cadence_s)
    events = sorted(
        [*level_events, *label_events],
        key=lambda event: (event["start_epoch_s"], event["key"]),
    )
    pattern = describe_level_pattern(rows, events)
    points = _compact_points(
        rows,
        cadence_s=cadence_s,
        display_range=display_range,
        max_points=max_points,
    )
    summary = _summary(
        rows,
        valid_levels,
        events,
        pattern,
        cadence_s=cadence_s,
        display_range=display_range,
    )
    status = _status(session_active, recording, len(valid_levels))
    start_epoch_s = (
        float(rows[0]["t"])
        if rows
        else _positive_number(started_at_epoch_s)
    )
    end_epoch_s = float(rows[-1]["t"]) if rows else start_epoch_s

    visible_events = _visible_events(events)
    return {
        "schema": TIMELINE_SCHEMA,
        "schema_version": TIMELINE_SCHEMA_VERSION,
        "generated_at": generated.isoformat(timespec="milliseconds"),
        "status": status,
        "analysis_scope": "sound_level_and_firmware_dsp_labels",
        "detector": _detector_block(),
        "session": _session_block(
            session_active, recording, session_id, start_epoch_s
        ),
        "summary": summary,
        "timeline": _timeline_block(
            start_epoch_s,
            end_epoch_s,
            cadence_s,
            display_range,
            valid_levels,
            rows,
            points,
        ),
        "events": visible_events,
        "event_summary": _event_summary(events, visible_events),
        "classification": latest_classification(samples),
        "privacy": _privacy_block(),
        "impact": _impact_block(),
        "message": _message(status, summary),
    }


def _detector_block() -> dict[str, Any]:
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


def _privacy_block() -> dict[str, bool]:
    return {
        "raw_audio_transmitted": False,
        "raw_audio_retained": False,
        "speech_content_processed": False,
    }


def _impact_block() -> dict[str, bool]:
    return dict.fromkeys(
        ("sleep_state", "sleep_score", "recovery_score", "control"),
        False,
    )


def _session_block(
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


def _timeline_block(
    start: float | None,
    end: float | None,
    cadence_s: float,
    display_range: tuple[float, float],
    levels: Sequence[float],
    rows: Sequence[Mapping[str, float | None]],
    points: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    low, high = display_range
    return {
        "start_epoch_s": start,
        "end_epoch_s": end,
        "cadence_s": cadence_s,
        "cadences_s": sorted(
            {
                float(row.get("sample_interval_s") or cadence_s)
                for row in rows
            }
        ),
        "display_range_dba": [low, high],
        "chart_range_dba": _chart_range(levels, low=low, high=high),
        "reference_lines": [
            {"value_dba": SUSTAINED_LEVEL_DBA, "label": "ทบทวน ≥50 dBA"}
        ],
        "points": list(points),
        "point_count_before_compaction": len(rows),
        "compacted": len(points) < len(rows),
    }


def _status(active: bool, recording: bool, valid_count: int) -> str:
    if not active:
        return "no_session"
    if not recording:
        return "waiting_for_recording"
    if valid_count < 2:
        return "collecting" if valid_count else "no_data"
    return "ready"


def _positive_number(value: Any) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    number = float(value)
    return number if math.isfinite(number) and number > 0 else None


def _summary(
    rows: Sequence[Mapping[str, float | None]],
    valid_levels: Sequence[float],
    events: Sequence[Mapping[str, Any]],
    pattern: Mapping[str, str],
    *,
    cadence_s: float,
    display_range: tuple[float, float],
) -> dict[str, Any]:
    expected = _expected_sample_count(rows, cadence_s=cadence_s)
    valid_count = len(valid_levels)
    observed = [
        event
        for event in events
        if event["category"] in {"observed_level", "dsp_label"}
    ]
    missing = [event for event in events if event["category"] == "sensor_quality"]
    average = energy_average_db(
        valid_levels,
        display_min=display_range[0],
        display_max=display_range[1],
    )
    return {
        "current_dba": (
            round(float(rows[-1]["dba"]), 1)
            if rows and rows[-1].get("dba") is not None
            else None
        ),
        "average_dba": round(average, 1) if average is not None else None,
        "minimum_dba": round(min(valid_levels), 1) if valid_levels else None,
        "peak_dba": round(max(valid_levels), 1) if valid_levels else None,
        "valid_sample_count": valid_count,
        "expected_sample_count": expected,
        "coverage_pct": (
            round(min(100.0, valid_count * 100.0 / expected), 1)
            if expected
            else 0.0
        ),
        "observed_event_count": len(observed),
        "missing_interval_count": len(missing),
        "pattern": dict(pattern),
    }


def _expected_sample_count(
    rows: Sequence[Mapping[str, float | None]],
    *,
    cadence_s: float,
) -> int:
    if not rows:
        return 0
    expected = 1
    for previous, current in zip(rows, rows[1:], strict=False):
        interval = float(previous.get("sample_interval_s") or cadence_s)
        delta = max(0.0, float(current["t"]) - float(previous["t"]))
        expected += max(1, int(round(delta / interval)))
    return max(len(rows), expected)


def _compact_points(
    rows: Sequence[Mapping[str, float | None]],
    *,
    cadence_s: float,
    display_range: tuple[float, float],
    max_points: int,
) -> list[dict[str, Any]]:
    if not rows:
        return []
    limit = max(24, int(max_points))
    runs = _continuous_level_runs(rows, cadence_s=cadence_s)
    if not runs:
        return []
    if len(runs) > limit:
        step = len(runs) / limit
        runs = [runs[min(len(runs) - 1, int(index * step))] for index in range(limit)]
    valid_count = sum(len(run) for run in runs)
    bucket_size = max(1, math.ceil(valid_count / limit))

    while _compacted_count(runs, bucket_size) > limit:
        bucket_size += 1

    points: list[dict[str, Any]] = []
    for run_index, run in enumerate(runs):
        for offset in range(0, len(run), bucket_size):
            bucket = run[offset : offset + bucket_size]
            points.append(
                _compact_bucket(
                    bucket,
                    display_range=display_range,
                    gap_before=run_index > 0 and offset == 0,
                )
            )
    return points


def _continuous_level_runs(
    rows: Sequence[Mapping[str, float | None]],
    *,
    cadence_s: float,
) -> list[list[Mapping[str, float | None]]]:
    runs: list[list[Mapping[str, float | None]]] = []
    active: list[Mapping[str, float | None]] = []
    for row in rows:
        timestamp = float(row["t"])
        expected = float(
            active[-1].get("sample_interval_s") if active else cadence_s
        )
        contiguous = not active or timestamp - float(active[-1]["t"]) <= expected * 2.5
        if row.get("dba") is not None and contiguous:
            active.append(row)
            continue
        if active:
            runs.append(active)
            active = []
        if row.get("dba") is not None:
            active = [row]
    if active:
        runs.append(active)
    return runs


def _compacted_count(
    runs: Sequence[Sequence[Mapping[str, float | None]]],
    bucket_size: int,
) -> int:
    return sum(math.ceil(len(run) / bucket_size) for run in runs)


def _compact_bucket(
    bucket: Sequence[Mapping[str, float | None]],
    *,
    display_range: tuple[float, float],
    gap_before: bool,
) -> dict[str, Any]:
    start, end = float(bucket[0]["t"]), float(bucket[-1]["t"])
    levels = [float(row["dba"]) for row in bucket if row.get("dba") is not None]
    average = energy_average_db(
        levels,
        display_min=display_range[0],
        display_max=display_range[1],
    )
    return {
        "t": round((start + end) / 2.0, 1),
        "dba": round(average, 1) if average is not None else None,
        "min_dba": round(min(levels), 1),
        "max_dba": round(max(levels), 1),
        "sample_count": len(levels),
        "gap_before": gap_before,
    }


def _chart_range(values: Sequence[float], *, low: float, high: float) -> list[float]:
    if not values:
        return [low, min(high, low + 30.0)]
    chart_low = max(low, math.floor((min(values) - 5.0) / 5.0) * 5.0)
    chart_high = min(high, math.ceil((max(values) + 5.0) / 5.0) * 5.0)
    if chart_high - chart_low < 20.0:
        midpoint = (chart_high + chart_low) / 2.0
        chart_low = max(low, math.floor((midpoint - 10.0) / 5.0) * 5.0)
        chart_high = min(high, chart_low + 20.0)
        chart_low = max(low, chart_high - 20.0)
    return [round(chart_low, 1), round(chart_high, 1)]


def _visible_events(events: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
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
        selected.extend(
            [event for event in newest if event.get("key") == key][:quota]
        )
    selected_ids = {str(event.get("id")) for event in selected}
    selected.extend(
        event
        for event in newest
        if str(event.get("id")) not in selected_ids
    )
    selected = selected[:MAX_VISIBLE_EVENTS]
    return sorted(
        (dict(event) for event in selected),
        key=lambda event: float(event.get("start_epoch_s") or 0),
    )


def _event_summary(
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
        key: sum(1 for event in events if event.get("key") == key)
        for key in keys
    }
    return {
        "total_count": len(events),
        "visible_count": len(visible),
        "truncated": len(visible) < len(events),
        "counts": counts,
    }


def _message(status: str, summary: Mapping[str, Any]) -> str:
    if status == "no_session":
        return (
            "เริ่ม Session เพื่อดูภาพระดับเสียงตลอดช่วงที่ระบบบันทึก"
        )
    if status == "waiting_for_recording":
        return "รอ Session เริ่มบันทึกหลัง HR และ RR ผ่านเกณฑ์"
    if status == "no_data":
        return "Session เริ่มแล้ว แต่ยังไม่ได้รับ sound_dba ที่ใช้ได้"
    if status == "collecting":
        return "กำลังสะสมข้อมูลระดับเสียงเพื่อสร้าง Timeline"
    count = int(summary.get("observed_event_count") or 0)
    return (
        f"พบช่วงระดับเสียงที่ควรย้อนดู {count} ช่วง"
        if count
        else "ระดับเสียงยังไม่มีช่วงเปลี่ยนแปลงที่เด่นชัด"
    )
