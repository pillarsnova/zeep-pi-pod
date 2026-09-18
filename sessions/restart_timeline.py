"""Pure reconstruction of persisted samples and their original cadence."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sessions import respiratory_evidence as rr_evidence
from sessions.cadence import (
    cadence_interval_at,
    normalise_cadence_segments,
    sample_interval_seconds,
    timeline_sample_interval,
)


@dataclass(frozen=True)
class RestartTimeline:
    """Historic samples remain at their cadence; only future samples migrate."""

    samples: list[dict[str, Any]]
    cadence_segments: list[dict[str, Any]]
    previous_interval_s: float
    upgraded: bool
    resumed_at_utc: str


def restore_timeline(
    rows: list[dict[str, Any]],
    checkpoint_record: dict[str, Any],
    *,
    start_at_utc: str,
    resumed_at_utc: str,
    live_interval_s: float,
) -> RestartTimeline:
    """Apply the existing mixed-cadence rules without writing stored samples."""
    original_interval = sample_interval_seconds(
        checkpoint_record.get("sample_interval_s"), timeline_sample_interval(rows, 5.0)
    )
    segments = normalise_cadence_segments(
        checkpoint_record.get("sample_cadence_segments"),
        start_at_utc=start_at_utc,
        fallback_interval_s=original_interval,
    )
    previous_interval = (
        sample_interval_seconds(
            segments[-1].get("sample_interval_s"), original_interval
        )
        if segments
        else original_interval
    )
    upgraded = not math.isclose(
        previous_interval, live_interval_s, rel_tol=0.0, abs_tol=0.001
    )
    if upgraded:
        segments.append(
            {"start_at_utc": resumed_at_utc, "sample_interval_s": live_interval_s}
        )
    return RestartTimeline(
        samples=[_restore_sample(row, segments, original_interval) for row in rows],
        cadence_segments=segments,
        previous_interval_s=previous_interval,
        upgraded=upgraded,
        resumed_at_utc=resumed_at_utc,
    )


def _restore_sample(
    row: dict[str, Any], segments: list[dict[str, Any]], interval_s: float
) -> dict[str, Any]:
    epoch_s = datetime.fromisoformat(row["timestamp"]).timestamp()
    return {
        "t": epoch_s,
        "temp": row.get("temperature"),
        "hum": row.get("humidity"),
        "co2": row.get("co2"),
        "pm2_5": row.get("pm2_5"),
        "voc": row.get("voc_index"),
        "lux": row.get("lux"),
        "dba": row.get("sound"),
        "acoustic_label": row.get("acoustic_label"),
        "acoustic_state": row.get("acoustic_state"),
        "acoustic_confidence": row.get("acoustic_confidence"),
        "acoustic_event_detected": bool(row.get("acoustic_event_detected")),
        "acoustic_classifier_version": row.get("acoustic_classifier_version"),
        "acoustic_window_sequence": row.get("acoustic_window_sequence"),
        "acoustic_features": (
            json.loads(row["acoustic_features_json"])
            if row.get("acoustic_features_json")
            else {}
        ),
        "hr": row.get("heart_rate"),
        "rr": row.get("respiration_rate"),
        "bed": row.get("bed_status"),
        "sleep": None,
        **rr_evidence.persisted_evidence_fields(row),
        "sample_interval_s": cadence_interval_at(epoch_s, segments, interval_s),
    }
