"""Pure level statistics and gap-preserving chart compaction."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from sensors.sound import energy_average_db

from .level_events import SUSTAINED_LEVEL_DBA


def build_timeline_series(
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
            {float(row.get("sample_interval_s") or cadence_s) for row in rows}
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


def summarize_levels(
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
            round(min(100.0, valid_count * 100.0 / expected), 1) if expected else 0.0
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


def compact_points(
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
        expected = float(active[-1].get("sample_interval_s") if active else cadence_s)
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
