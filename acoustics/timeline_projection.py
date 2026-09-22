"""Compose the existing Admin acoustic timeline from pure domain modules."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from .label_events import detect_label_events, latest_classification
from .level_events import (
    DEFAULT_CADENCE_SECONDS,
    describe_level_pattern,
    detect_level_events,
    normalise_level_samples,
)
from .timeline_series import build_timeline_series, compact_points, summarize_levels
from .timeline_view import (
    DETECTOR_VERSION as DETECTOR_VERSION,
)
from .timeline_view import (
    MAX_VISIBLE_EVENTS as MAX_VISIBLE_EVENTS,
)
from .timeline_view import (
    detector_block,
    event_summary,
    impact_block,
    privacy_block,
    session_block,
    timeline_message,
    timeline_status,
    visible_events,
)

TIMELINE_SCHEMA = "zeep.acoustic.level-timeline"
TIMELINE_SCHEMA_VERSION = "1.1"
DEFAULT_DISPLAY_RANGE = (30.0, 130.0)
DEFAULT_MAX_POINTS = 240


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
    """Return an allowlisted level timeline with provisional firmware labels."""
    generated = (generated_at or datetime.now(UTC)).astimezone(UTC)
    low, high = display_range
    cadence_s = max(1.0, float(cadence_s))
    rows = normalise_level_samples(
        samples,
        display_min=low,
        display_max=high,
        fallback_cadence_s=cadence_s,
    )
    valid_levels = [float(row["dba"]) for row in rows if row.get("dba") is not None]
    level_events = detect_level_events(rows, cadence_s=cadence_s)
    label_events = detect_label_events(samples, cadence_s=cadence_s)
    events = sorted(
        [*level_events, *label_events],
        key=lambda event: (event["start_epoch_s"], event["key"]),
    )
    pattern = describe_level_pattern(rows, events)
    points = compact_points(
        rows,
        cadence_s=cadence_s,
        display_range=display_range,
        max_points=max_points,
    )
    summary = summarize_levels(
        rows,
        valid_levels,
        events,
        pattern,
        cadence_s=cadence_s,
        display_range=display_range,
    )
    status = timeline_status(session_active, recording, len(valid_levels))
    start_epoch_s = (
        float(rows[0]["t"]) if rows else _positive_number(started_at_epoch_s)
    )
    end_epoch_s = float(rows[-1]["t"]) if rows else start_epoch_s

    visible = visible_events(events)
    return {
        "schema": TIMELINE_SCHEMA,
        "schema_version": TIMELINE_SCHEMA_VERSION,
        "generated_at": generated.isoformat(timespec="milliseconds"),
        "status": status,
        "analysis_scope": "sound_level_and_firmware_dsp_labels",
        "detector": detector_block(),
        "session": session_block(session_active, recording, session_id, start_epoch_s),
        "summary": summary,
        "timeline": build_timeline_series(
            start_epoch_s,
            end_epoch_s,
            cadence_s,
            display_range,
            valid_levels,
            rows,
            points,
        ),
        "events": visible,
        "event_summary": event_summary(events, visible),
        "classification": latest_classification(samples),
        "privacy": privacy_block(),
        "impact": impact_block(),
        "message": timeline_message(status, summary),
    }


def _positive_number(value: Any) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    number = float(value)
    return number if math.isfinite(number) and number > 0 else None
