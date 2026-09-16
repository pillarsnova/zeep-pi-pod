"""Pure sound-level validation and packet-window aggregation."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any


def valid_sound_level(value: Any, low: float, high: float) -> bool:
    """Return whether a sound value is finite and in the display range."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        number = float(value)
    except OverflowError:
        return False
    return math.isfinite(number) and low <= number <= high


def energy_average_db(
    levels: Sequence[float],
    *,
    display_min: float,
    display_max: float,
) -> float | None:
    """Return a numerically stable energy-domain decibel average."""
    valid = [
        float(value)
        for value in levels
        if valid_sound_level(value, display_min, display_max)
    ]
    if not valid:
        return None
    peak = max(valid)
    relative_energy = sum(10 ** ((value - peak) / 10.0) for value in valid) / len(valid)
    return round(peak + 10.0 * math.log10(relative_energy), 2)


def summarize_sound_window(
    rows: Sequence[Mapping[str, Any]],
    start_s: float,
    end_s: float,
    *,
    display_min: float,
    display_max: float,
) -> dict[str, Any]:
    """Summarize immutable sound rows aligned to one analysis bucket."""
    levels = [float(row["dba"]) for row in rows if start_s < float(row["t"]) <= end_s]
    average = energy_average_db(
        levels,
        display_min=display_min,
        display_max=display_max,
    )
    if average is None:
        return {
            "method": "energy_average_leq",
            "window_s": round(end_s - start_s, 2),
            "sample_count": 0,
            "status": "no_samples",
        }
    span = max(levels) - min(levels)
    return {
        "method": "energy_average_leq",
        "window_s": round(end_s - start_s, 2),
        "sample_count": len(levels),
        "leq_dba": average,
        "min_dba": round(min(levels), 2),
        "max_dba": round(max(levels), 2),
        "span_db": round(span, 2),
        "large_step_detected": span >= 20.0,
        "status": "dynamic" if span >= 20.0 else "valid",
    }
