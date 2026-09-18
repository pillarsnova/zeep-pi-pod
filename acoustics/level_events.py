"""Detect reviewable sound-level patterns without inferring a sound source.

The production microphone currently publishes one scalar ``sound_dba`` value
per Sensor frame.  These helpers therefore describe only changes in level and
data continuity.  They deliberately do not manufacture speech, snore,
equipment, spectral, or clinical labels from scalar dBA.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

DEFAULT_CADENCE_SECONDS = 10.0
RAPID_CHANGE_DB = 6.0
SUSTAINED_LEVEL_DBA = 50.0
SUSTAINED_MIN_SECONDS = 30.0
GAP_MIN_SAMPLES = 2


def finite_number(value: Any) -> float | None:
    """Return a finite float while rejecting booleans and malformed values."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (OverflowError, ValueError):
        return None
    return number if math.isfinite(number) else None


def normalise_level_samples(
    samples: Sequence[Mapping[str, Any]],
    *,
    display_min: float,
    display_max: float,
    fallback_cadence_s: float = DEFAULT_CADENCE_SECONDS,
) -> list[dict[str, float | None]]:
    """Return sorted, de-duplicated time/dBA samples within the valid range."""
    by_time: dict[float, dict[str, float | None]] = {}
    for sample in samples:
        timestamp = finite_number(sample.get("t"))
        if timestamp is None or timestamp <= 0:
            continue
        level = finite_number(sample.get("dba"))
        if level is None or not display_min <= level <= display_max:
            level = None
        cadence = finite_number(sample.get("sample_interval_s"))
        if cadence is None or not 1.0 <= cadence <= 120.0:
            cadence = fallback_cadence_s
        by_time[timestamp] = {
            "t": timestamp,
            "dba": level,
            "sample_interval_s": cadence,
        }
    return [by_time[key] for key in sorted(by_time)]


def percentile(values: Sequence[float], ratio: float) -> float | None:
    """Return a linearly interpolated percentile for a finite value list."""
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = min(1.0, max(0.0, ratio)) * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + fraction * (ordered[upper] - ordered[lower])


def detect_level_events(
    samples: Sequence[Mapping[str, float | None]],
    *,
    cadence_s: float,
) -> list[dict[str, Any]]:
    """Detect level-only events that can be audited against the timeline."""
    events = [
        *_missing_intervals(samples, cadence_s=cadence_s),
        *_sustained_intervals(samples, cadence_s=cadence_s),
        *_rapid_changes(samples, cadence_s=cadence_s),
    ]
    return sorted(events, key=lambda event: (event["start_epoch_s"], event["key"]))


def describe_level_pattern(
    samples: Sequence[Mapping[str, float | None]],
    events: Sequence[Mapping[str, Any]],
) -> dict[str, str]:
    """Summarize the observed level shape in plain, non-source language."""
    values = [
        float(sample["dba"]) for sample in samples if sample.get("dba") is not None
    ]
    if len(values) < 2:
        return {
            "key": "insufficient_data",
            "label": "ข้อมูลยังไม่พอสรุป",
            "detail": "รอระดับเสียงอย่างน้อย 2 จุด",
        }

    p10 = percentile(values, 0.10)
    p90 = percentile(values, 0.90)
    spread = (p90 - p10) if p10 is not None and p90 is not None else 0.0
    sustained = [event for event in events if event["key"] == "sustained_high"]
    rapid = [event for event in events if event["key"] == "rapid_change"]
    average = sum(values) / len(values)

    if sustained:
        return {
            "key": "elevated_intervals",
            "label": "มีค่าระดับเสียงสูงหลายจุด",
            "detail": f"พบ {len(sustained)} ช่วงจากค่าที่วัดติดต่อกัน",
        }
    if len(rapid) >= 3:
        return {
            "key": "intermittent_changes",
            "label": "ระดับเสียงเปลี่ยนชัดเป็นช่วง",
            "detail": f"พบการเปลี่ยนระดับชัด {len(rapid)} ช่วง",
        }
    if spread <= 3.0:
        label = "ค่อนข้างเงียบและคงที่" if average < 40.0 else "ระดับเสียงค่อนข้างคงที่"
        return {
            "key": "quiet_steady" if average < 40.0 else "steady",
            "label": label,
            "detail": f"ช่วงกลางของข้อมูลต่างกันประมาณ {spread:.1f} dB",
        }
    return {
        "key": "variable",
        "label": "ระดับเสียงเปลี่ยนตามช่วงเวลา",
        "detail": f"ช่วงกลางของข้อมูลต่างกันประมาณ {spread:.1f} dB",
    }


def _missing_intervals(
    samples: Sequence[Mapping[str, float | None]],
    *,
    cadence_s: float,
) -> list[dict[str, Any]]:
    intervals: list[tuple[float, float, float]] = []
    invalid_start: float | None = None
    invalid_end: float | None = None
    invalid_end_interval = cadence_s
    invalid_minimum = cadence_s * GAP_MIN_SAMPLES

    for sample in samples:
        timestamp = float(sample["t"])
        if sample.get("dba") is None:
            invalid_start = timestamp if invalid_start is None else invalid_start
            invalid_end = timestamp
            invalid_end_interval = float(sample.get("sample_interval_s") or cadence_s)
            invalid_minimum = min(
                invalid_minimum,
                float(sample.get("sample_interval_s") or cadence_s) * GAP_MIN_SAMPLES,
            )
        elif invalid_start is not None and invalid_end is not None:
            intervals.append(
                (invalid_start, invalid_end + invalid_end_interval, invalid_minimum)
            )
            invalid_start = invalid_end = None
            invalid_minimum = cadence_s * GAP_MIN_SAMPLES
    if invalid_start is not None and invalid_end is not None:
        intervals.append(
            (invalid_start, invalid_end + invalid_end_interval, invalid_minimum)
        )

    for previous, current in zip(samples, samples[1:], strict=False):
        previous_t = float(previous["t"])
        current_t = float(current["t"])
        expected = float(previous.get("sample_interval_s") or cadence_s)
        if current_t - previous_t > expected * 2.5:
            intervals.append(
                (previous_t + expected, current_t, expected * GAP_MIN_SAMPLES)
            )

    merged: list[list[float]] = []
    for start, end, minimum in sorted(intervals):
        merge_interval = (
            min(
                minimum,
                merged[-1][2] if merged else minimum,
            )
            / GAP_MIN_SAMPLES
        )
        if merged and start <= merged[-1][1] + merge_interval * 0.25:
            merged[-1][1] = max(merged[-1][1], end)
            merged[-1][2] = min(merged[-1][2], minimum)
        else:
            merged.append([start, end, minimum])

    return [
        {
            "id": f"missing-{int(start)}",
            "key": "missing_data",
            "category": "sensor_quality",
            "label": "ข้อมูลเสียงขาดช่วง",
            "marker": "?",
            "source_inference": False,
            "start_epoch_s": round(start, 1),
            "end_epoch_s": round(end, 1),
            "duration_s": round(end - start, 1),
            "evidence_quality": "measured_gap",
            "evidence": "ไม่พบ sound_dba ตามรอบ Sensor",
        }
        for start, end, minimum in merged
        if end - start >= minimum
    ]


def _sustained_intervals(
    samples: Sequence[Mapping[str, float | None]],
    *,
    cadence_s: float,
) -> list[dict[str, Any]]:
    segments: list[list[tuple[float, float]]] = []
    active: list[tuple[float, float]] = []
    for sample in samples:
        timestamp = float(sample["t"])
        level = sample.get("dba")
        expected = float(sample.get("sample_interval_s") or cadence_s)
        contiguous = not active or timestamp - active[-1][0] <= expected * 1.8
        if level is not None and float(level) >= SUSTAINED_LEVEL_DBA and contiguous:
            active.append((timestamp, float(level)))
            continue
        if active:
            segments.append(active)
            active = []
        if level is not None and float(level) >= SUSTAINED_LEVEL_DBA:
            active = [(timestamp, float(level))]
    if active:
        segments.append(active)

    events: list[dict[str, Any]] = []
    for segment in segments:
        # Samples are observations at their timestamps, not guaranteed
        # integration windows. Require a full observed span instead of
        # crediting an unobserved interval after the last sample.
        duration = segment[-1][0] - segment[0][0]
        if duration < SUSTAINED_MIN_SECONDS:
            continue
        levels = [level for _, level in segment]
        events.append(
            {
                "id": f"sustained-{int(segment[0][0])}",
                "key": "sustained_high",
                "category": "observed_level",
                "label": "ค่าระดับเสียงสูงหลายจุดติดกัน",
                "marker": "≈",
                "source_inference": False,
                "start_epoch_s": round(segment[0][0], 1),
                "end_epoch_s": round(segment[-1][0], 1),
                "duration_s": round(duration, 1),
                "minimum_dba": round(min(levels), 1),
                "peak_dba": round(max(levels), 1),
                "evidence_quality": "rule_match",
                "evidence": (
                    f"ค่าที่วัดอย่างน้อย {SUSTAINED_LEVEL_DBA:.0f} dBA "
                    f"ติดต่อกัน {len(levels)} จุด"
                ),
            }
        )
    return events


def _rapid_changes(
    samples: Sequence[Mapping[str, float | None]],
    *,
    cadence_s: float,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    valid = [sample for sample in samples if sample.get("dba") is not None]
    for previous, current in zip(valid, valid[1:], strict=False):
        start = float(previous["t"])
        end = float(current["t"])
        expected = float(previous.get("sample_interval_s") or cadence_s)
        if end - start > expected * 1.8:
            continue
        delta = float(current["dba"]) - float(previous["dba"])
        if abs(delta) < RAPID_CHANGE_DB:
            continue
        direction = "เพิ่มขึ้น" if delta > 0 else "ลดลง"
        candidates.append(
            {
                "id": f"rapid-{int(end)}",
                "key": "rapid_change",
                "category": "observed_level",
                "label": f"ระดับเสียง{direction}ระหว่างจุดวัด",
                "marker": "↕",
                "source_inference": False,
                "start_epoch_s": round(start, 1),
                "end_epoch_s": round(end, 1),
                "duration_s": round(end - start, 1),
                "from_dba": round(float(previous["dba"]), 1),
                "to_dba": round(float(current["dba"]), 1),
                "delta_db": round(delta, 1),
                "peak_dba": round(
                    max(float(previous["dba"]), float(current["dba"])),
                    1,
                ),
                "evidence_quality": "rule_match",
                "evidence": (f"เปลี่ยน {abs(delta):.1f} dB ภายใน {end - start:.0f} วินาที"),
            }
        )

    # One physical change can span two adjacent 10-second values. Keep only the
    # strongest change in a short cluster so the Admin list stays useful.
    coalesced: list[dict[str, Any]] = []
    for candidate in candidates:
        if (
            coalesced
            and candidate["start_epoch_s"] - coalesced[-1]["end_epoch_s"] <= cadence_s
        ):
            current_delta = abs(float(candidate["delta_db"]))
            previous_delta = abs(float(coalesced[-1]["delta_db"]))
            if current_delta > previous_delta:
                coalesced[-1] = candidate
            continue
        coalesced.append(candidate)
    return coalesced
