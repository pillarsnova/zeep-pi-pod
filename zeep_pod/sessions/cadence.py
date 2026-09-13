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
    cadence_intervals = [
        interval
        for sample, interval in zip(samples, intervals, strict=True)
        if not sample.get("report_grid_partial")
    ] or [sample_interval_seconds(fallback_interval_s)]
    base_ms = max(100, int(round(cadence_intervals[0] * 1000)))
    for interval in cadence_intervals[1:]:
        interval_ms = max(100, int(round(interval * 1000)))
        base_ms = math.gcd(base_ms, interval_ms)

    report_interval_s = base_ms / 1000.0
    normalised: list[dict[str, Any]] = []
    summary: dict[float, dict[str, Any]] = {}
    for sample, interval in zip(samples, intervals, strict=True):
        full_units = min(
            120,
            max(0, int(math.floor(interval / report_interval_s + 1e-9))),
        )
        remainder = max(0.0, interval - full_units * report_interval_s)
        for _ in range(full_units):
            unit = dict(sample)
            unit["sample_interval_s"] = report_interval_s
            normalised.append(unit)
        if remainder > 0.0005:
            unit = dict(sample)
            unit["sample_interval_s"] = remainder
            unit["report_grid_partial"] = True
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


def materialise_report_sample_grid(
    samples: list[dict[str, Any]],
    *,
    start_at: Any,
    end_at: Any,
    cadence_segments: Any = (),
    split_boundaries: Any = (),
    fallback_interval_s: Any = 10.0,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build a complete, right-closed report grid without inventing Sensor data.

    A service interruption can leave no Timeline rows for several minutes.
    Reports still need one derived Sleep attribution for that wall-clock time,
    but must not copy temperature, HR/RR, occupancy, or any other measurement.
    Missing slots are therefore explicit empty rows which the Sleep decision
    projector can label by continuity after this function returns.
    """
    bounds = _report_grid_bounds(start_at, end_at)
    if bounds is None:
        copied = [dict(sample) for sample in samples]
        return copied, _invalid_grid_summary(len(samples))
    start_epoch, end_epoch = bounds
    source_rows = _report_grid_sources(samples)
    used: set[int] = set()
    grid: list[dict[str, Any]] = []
    boundaries = _report_grid_boundaries(
        split_boundaries, start_epoch, end_epoch
    )
    cursor = start_epoch
    slot_number = 0
    while cursor < end_epoch - 0.0005:
        nominal, slot_end, upper_tolerance = _report_grid_slot(
            cursor,
            end_epoch=end_epoch,
            cadence_segments=cadence_segments,
            boundaries=boundaries,
            fallback_interval_s=fallback_interval_s,
        )
        slot_duration = slot_end - cursor
        candidate = _report_grid_candidate(
            source_rows,
            used,
            cursor=cursor,
            slot_end=slot_end,
            lower_tolerance=nominal * 0.45,
            upper_tolerance=upper_tolerance,
        )
        slot_number += 1
        row = _report_grid_row(
            source_rows,
            candidate,
            slot_end=slot_end,
            slot_duration=slot_duration,
            slot_number=slot_number,
        )
        if candidate is not None:
            used.add(candidate)
        row["report_grid_partial"] = slot_duration < nominal - 0.0005
        grid.append(row)
        cursor = slot_end
    return grid, _complete_grid_summary(
        samples, source_rows, used, grid, start_epoch, end_epoch
    )


def _report_grid_bounds(start_at: Any, end_at: Any) -> tuple[float, float] | None:
    start_epoch = _timestamp_epoch(start_at)
    end_epoch = _timestamp_epoch(end_at)
    if start_epoch is None or end_epoch is None or end_epoch <= start_epoch:
        return None
    return start_epoch, end_epoch


def _invalid_grid_summary(row_count: int) -> dict[str, Any]:
    return {
        "version": "zeep-report-sample-grid-v1.0",
        "status": "invalid_bounds",
        "source_rows": row_count,
        "grid_rows": row_count,
        "synthetic_rows": 0,
        "covered_seconds": 0.0,
    }


def _report_grid_sources(
    samples: list[dict[str, Any]],
) -> list[tuple[float, dict[str, Any]]]:
    return sorted(
        (
            (float(sample["t"]), dict(sample))
            for sample in samples
            if _finite_epoch(sample.get("t"))
        ),
        key=lambda item: item[0],
    )


def _report_grid_boundaries(
    values: Any,
    start_epoch: float,
    end_epoch: float,
) -> list[float]:
    candidates = (
        values if isinstance(values, (list, tuple, set, frozenset)) else ()
    )
    return sorted({
        value
        for raw in candidates
        if (value := _timestamp_epoch(raw)) is not None
        and start_epoch < value < end_epoch
    })


def _report_grid_slot(
    cursor: float,
    *,
    end_epoch: float,
    cadence_segments: Any,
    boundaries: list[float],
    fallback_interval_s: Any,
) -> tuple[float, float, float]:
    nominal = cadence_interval_at(
        cursor + 0.001, cadence_segments, fallback_interval_s
    )
    segment_start = _next_cadence_segment_start(cursor, cadence_segments)
    split = next(
        (value for value in boundaries if value > cursor + 0.0005), None
    )
    natural_end = min(
        end_epoch,
        cursor + nominal,
        segment_start if segment_start is not None else math.inf,
    )
    slot_end = min(
        natural_end,
        split if split is not None else math.inf,
    )
    # A canonical 30-second decision boundary often coincides with a regular
    # 10-second acquisition endpoint.  Timeline timestamps contain normal
    # scheduler/write jitter, so a sample nominally ending at that boundary
    # may be a fraction of a second late.  Treat it like every other regular
    # slot.  The strict upper bound is required only when an off-grid decision
    # actually shortens the acquisition slot; otherwise every third Sensor row
    # can be discarded and physiological coverage is understated.
    truncated_by_split = (
        split is not None
        and abs(slot_end - split) <= 0.0005
        and slot_end < natural_end - 0.0005
    )
    return (
        nominal,
        slot_end,
        0.001 if truncated_by_split else nominal * 0.45,
    )


def _report_grid_candidate(
    sources: list[tuple[float, dict[str, Any]]],
    used: set[int],
    *,
    cursor: float,
    slot_end: float,
    lower_tolerance: float,
    upper_tolerance: float,
) -> int | None:
    candidate = None
    candidate_distance = math.inf
    for index, (source_epoch, _) in enumerate(sources):
        if index in used or source_epoch < cursor - lower_tolerance:
            continue
        if source_epoch > slot_end + upper_tolerance:
            break
        distance = abs(source_epoch - slot_end)
        if distance < candidate_distance:
            candidate = index
            candidate_distance = distance
    return candidate


def _report_grid_row(
    sources: list[tuple[float, dict[str, Any]]],
    candidate: int | None,
    *,
    slot_end: float,
    slot_duration: float,
    slot_number: int,
) -> dict[str, Any]:
    if candidate is not None:
        source_epoch, row = sources[candidate]
        row.update({
            "source_t": source_epoch,
            "t": slot_end,
            "sample_interval_s": slot_duration,
            "synthetic_sleep_gap": False,
            "sleep_gap_slot": slot_number,
        })
        return row
    return {
        "t": slot_end,
        "sample_interval_s": slot_duration,
        "synthetic_sleep_gap": True,
        "sleep_gap_slot": slot_number,
        **{key: None for key in (
            "temp", "hum", "co2", "pm2_5", "voc", "lux", "dba", "hr",
            "rr", "bed",
        )},
        "bcg_analysis_valid": False,
    }


def _complete_grid_summary(
    samples: list[dict[str, Any]],
    sources: list[tuple[float, dict[str, Any]]],
    used: set[int],
    grid: list[dict[str, Any]],
    start_epoch: float,
    end_epoch: float,
) -> dict[str, Any]:
    return {
        "version": "zeep-report-sample-grid-v1.0",
        "status": "complete",
        "source_rows": len(samples),
        "matched_source_rows": len(used),
        "unmatched_source_rows": max(0, len(sources) - len(used)),
        "grid_rows": len(grid),
        "synthetic_rows": sum(
            bool(row.get("synthetic_sleep_gap")) for row in grid
        ),
        "covered_seconds": round(sum(
            sample_interval_seconds(row.get("sample_interval_s"), 0.1)
            for row in grid
        ), 3),
        "requested_seconds": round(end_epoch - start_epoch, 3),
    }


def _timestamp_epoch(value: Any) -> float | None:
    if _finite_epoch(value):
        return float(value)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.timestamp()


def _finite_epoch(value: Any) -> bool:
    return bool(
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _next_cadence_segment_start(
    cursor: float,
    segments: Any,
) -> float | None:
    """Return the next declared cadence boundary after ``cursor``."""
    candidates: list[float] = []
    for raw in segments if isinstance(segments, list) else []:
        if not isinstance(raw, dict):
            continue
        value = _timestamp_epoch(raw.get("start_at_utc"))
        if value is not None and value > cursor + 0.0005:
            candidates.append(value)
    return min(candidates) if candidates else None
