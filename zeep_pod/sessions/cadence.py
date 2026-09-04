"""Pure helpers for mixed-cadence ZEEP Session timelines."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any


def sample_interval_seconds(value: Any, fallback: float = 10.0) -> float:
    """Return a positive, finite persisted acquisition interval."""
    try:
        interval = float(value)
    except (TypeError, ValueError):
        interval = float(fallback)
    if math.isfinite(interval) and interval > 0:
        return interval
    return float(fallback)


def timeline_sample_interval(
    rows: list[dict[str, Any]],
    fallback: float = 5.0,
) -> float:
    """Infer legacy Session cadence from the first valid timestamps."""
    timestamps: list[float] = []
    for row in rows[:120]:
        try:
            timestamp = datetime.fromisoformat(str(row["timestamp"]))
        except (KeyError, TypeError, ValueError):
            continue
        timestamps.append(timestamp.timestamp())

    gaps = sorted(
        current - previous
        for previous, current in zip(
            timestamps,
            timestamps[1:],
            strict=False,
        )
        if 0.5 <= current - previous <= 60.0
    )
    if not gaps:
        return sample_interval_seconds(fallback, 5.0)
    return round(gaps[len(gaps) // 2], 3)


def cadence_segment(
    start_at_utc: Any,
    sample_interval_s: Any,
) -> dict[str, Any] | None:
    """Return one validated, JSON-safe Session cadence segment."""
    try:
        start = datetime.fromisoformat(str(start_at_utc))
    except (TypeError, ValueError):
        return None
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    return {
        "start_at_utc": start.astimezone(UTC).isoformat(),
        "sample_interval_s": sample_interval_seconds(sample_interval_s),
    }


def normalise_cadence_segments(
    raw_segments: Any,
    *,
    start_at_utc: Any,
    fallback_interval_s: Any,
) -> list[dict[str, Any]]:
    """Validate persisted cadence history and ensure an initial segment."""
    segments: list[dict[str, Any]] = []
    candidates = raw_segments if isinstance(raw_segments, list) else []
    for raw in candidates:
        if not isinstance(raw, dict):
            continue
        segment = cadence_segment(
            raw.get("start_at_utc"),
            raw.get("sample_interval_s"),
        )
        if segment is not None:
            segments.append(segment)
    segments.sort(key=lambda item: item["start_at_utc"])
    if not segments:
        initial = cadence_segment(start_at_utc, fallback_interval_s)
        if initial is not None:
            segments.append(initial)
    return segments


def cadence_interval_at(
    epoch_s: Any,
    segments: Any,
    fallback_interval_s: Any,
) -> float:
    """Resolve the acquisition cadence active at one Timeline timestamp."""
    interval = sample_interval_seconds(fallback_interval_s)
    try:
        sample_epoch = float(epoch_s)
    except (TypeError, ValueError):
        return interval

    candidates = segments if isinstance(segments, list) else []
    for raw in candidates:
        if not isinstance(raw, dict):
            continue
        try:
            start_epoch = datetime.fromisoformat(
                str(raw.get("start_at_utc"))
            ).timestamp()
        except (TypeError, ValueError):
            continue
        if sample_epoch + 0.001 < start_epoch:
            break
        interval = sample_interval_seconds(
            raw.get("sample_interval_s"),
            interval,
        )
    return interval


def normalise_samples_for_report(
    samples: list[dict[str, Any]],
    fallback_interval_s: Any,
) -> tuple[list[dict[str, Any]], float, list[dict[str, Any]]]:
    """Convert mixed 5/10-second rows into equal-duration report units.

    Source rows remain unchanged.  A 10-second row becomes two 5-second units
    when a Session includes both cadences, preserving duration and weighting.
    """
    if not samples:
        interval = sample_interval_seconds(fallback_interval_s)
        return [], interval, []

    intervals = [
        sample_interval_seconds(
            sample.get("sample_interval_s"),
            fallback_interval_s,
        )
        for sample in samples
    ]
    base_ms = max(100, int(round(intervals[0] * 1000)))
    for interval in intervals[1:]:
        interval_ms = max(100, int(round(interval * 1000)))
        base_ms = math.gcd(base_ms, interval_ms)

    report_interval_s = base_ms / 1000.0
    normalised: list[dict[str, Any]] = []
    summary: dict[float, dict[str, Any]] = {}
    for sample, interval in zip(samples, intervals, strict=True):
        repeats = max(1, int(round(interval / report_interval_s)))
        repeats = min(repeats, 120)
        for _ in range(repeats):
            unit = dict(sample)
            unit["sample_interval_s"] = report_interval_s
            normalised.append(unit)

        key = round(interval, 3)
        bucket = summary.setdefault(
            key,
            {
                "sample_interval_s": key,
                "raw_samples": 0,
                "covered_seconds": 0.0,
            },
        )
        bucket["raw_samples"] += 1
        bucket["covered_seconds"] = round(
            float(bucket["covered_seconds"]) + interval,
            3,
        )

    summary_rows = [summary[key] for key in sorted(summary)]
    return normalised, report_interval_s, summary_rows
