"""Pure assembly helpers for the Session history-detail endpoint."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Any

from sleep_system_policy import ZEEP_SLEEP_STATES
from sleep_signal_features import (
    terminal_occupancy_timeline,
    terminal_wake_transition,
)

from .cadence import sample_interval_seconds
from .history_sleep_timeline import (
    clip_history_sleep_timeline,
    fill_history_sleep_timeline_continuity,
    history_sleep_timeline,
)
from .report_projection import project_report_samples


AnnotationApplier = Callable[..., tuple[dict[str, Any], Any]]


def history_samples_from_rows(
    rows: Sequence[Mapping[str, Any]],
    bed_labels: Sequence[str],
    *,
    sample_interval_s: float,
    include_raw_bed_status: bool,
) -> list[dict[str, Any]]:
    """Translate persisted Timeline rows to report Sensor names."""
    samples: list[dict[str, Any]] = []
    for row, bed_label in zip(rows, bed_labels, strict=False):
        sample = {
            "t": datetime.fromisoformat(str(row["timestamp"])).timestamp(),
            "temp": row["temperature"], "hum": row["humidity"],
            "co2": row["co2"], "pm2_5": row["pm2_5"],
            "voc": row["voc_index"], "lux": row["lux"],
            "dba": row["sound"], "hr": row["heart_rate"],
            "rr": row["respiration_rate"], "bed": bed_label,
            "sample_interval_s": sample_interval_s,
        }
        if include_raw_bed_status:
            sample["raw_bed_status"] = row["bed_status"]
        samples.append(sample)
    return samples


def latest_final_summary(
    events: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Read the most recent valid final-summary payload."""
    for event in reversed(events):
        if event["type"] == "final_summary":
            return _json_event_value(event)
    return {}


def parse_history_sleep_events(
    events: Sequence[Mapping[str, Any]],
    *,
    annotations: Any,
    sample_interval_s: float,
    apply_annotations: AnnotationApplier,
) -> dict[str, Any]:
    """Partition durable events into stage, status, terminal and counters."""
    stages: list[dict[str, Any]] = []
    statuses: list[dict[str, Any]] = []
    terminal = None
    counters: dict[str, int] = {}
    for event in events:
        event_type = str(event["type"])
        if event_type == "final_summary":
            continue
        value = _json_event_value(event)
        if event_type == "sleep_stage":
            point = _stage_point(
                event, value, annotations, sample_interval_s,
                apply_annotations,
            )
            if point is not None:
                stages.append(point)
            continue
        if event_type == "sleep_stage_status":
            point = _status_point(event, value, sample_interval_s)
            if point is not None:
                statuses.append(point)
            continue
        if event_type == "session_terminal_wake":
            if value.get("state") == "wake":
                terminal = value
            continue
        kind = event_type.removeprefix("legacy_counter:")
        amount = int(event["value"]) if event_type.startswith(
            "legacy_counter:"
        ) else 1
        counters[kind] = counters.get(kind, 0) + amount
    return {
        "stage_points": stages,
        "status_points": statuses,
        "terminal_wake_event": terminal,
        "counters": counters,
    }


def _json_event_value(event: Mapping[str, Any]) -> dict[str, Any]:
    value = event.get("value")
    if isinstance(value, Mapping):
        return dict(value)
    try:
        decoded = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _stage_point(
    event: Mapping[str, Any],
    value: dict[str, Any],
    annotations: Any,
    fallback_interval_s: float,
    apply_annotations: AnnotationApplier,
) -> dict[str, Any] | None:
    interval = sample_interval_seconds(
        value.get("sample_interval_s"), fallback_interval_s
    )
    value, _ = apply_annotations(
        value,
        event["timestamp"],
        annotations,
        sample_interval_s=interval,
    )
    value["sample_interval_s"] = interval
    if value.get("state") not in ZEEP_SLEEP_STATES:
        return None
    return {"timestamp": event["timestamp"], **value}


def _status_point(
    event: Mapping[str, Any],
    value: dict[str, Any],
    fallback_interval_s: float,
) -> dict[str, Any] | None:
    state = value.get("state")
    if state not in {"wait", "no_data", "off_bed"}:
        return None
    interval = sample_interval_seconds(
        value.get("sample_interval_s"), fallback_interval_s
    )
    value.update({
        "sample_interval_s": interval,
        "data_status": value.get("data_status") or (
            "off_bed" if state == "off_bed" else None
        ),
        "window_start": (
            value.get("attribution_start") or value.get("window_start")
        ),
        "window_end": (
            value.get("attribution_end")
            or value.get("window_end")
            or event["timestamp"]
        ),
        "score_eligible": False,
        "excluded_from_score": True,
        "excluded_from_personal_baseline": True,
        "sleep_stage": False,
    })
    return {"timestamp": event["timestamp"], **value}


def history_bed_counts(
    samples: Sequence[Mapping[str, Any]],
    persisted_counts: Any,
) -> dict[str, Any]:
    """Rebuild canonical display counts, falling back for empty timelines."""
    counts: dict[str, Any] = {}
    for sample in samples:
        status = sample.get("bed")
        if status:
            counts[str(status)] = counts.get(str(status), 0) + 1
    return counts or (
        dict(persisted_counts) if isinstance(persisted_counts, Mapping) else {}
    )


def history_continuity_accounting(
    periods: Sequence[Mapping[str, Any]],
    *,
    session_start: Any,
    classification_end: Any,
) -> dict[str, Any]:
    """Compare visible State/OFF BED periods with the classification wall time."""
    try:
        expected = max(0.0, (
            datetime.fromisoformat(str(classification_end))
            - datetime.fromisoformat(str(session_start))
        ).total_seconds())
    except (TypeError, ValueError):
        expected = 0.0
    accounted = sum(
        max(0.0, float(period.get("duration_s") or 0.0))
        for period in periods
        if period.get("state") in {*ZEEP_SLEEP_STATES, "off_bed"}
    )
    return {
        "version": "zeep-history-continuity-v1.0",
        "expected_seconds": round(expected, 3),
        "accounted_seconds": round(accounted, 3),
        "unattributed_seconds": round(max(0.0, expected - accounted), 3),
        "continuity_synthesized_periods": sum(
            bool(period.get("continuity_synthesized")) for period in periods
        ),
    }


def assemble_history_sleep_timeline(
    stage_points: list[dict[str, Any]],
    status_points: list[dict[str, Any]],
    *,
    raw_timeline: Sequence[Mapping[str, Any]],
    report_end: str,
    session_start: str,
    session_end: Any,
    end_reason: Any,
    sample_interval_s: float,
    fallback_estimator: Any,
    persisted_terminal_wake: Any,
    terminal_wake_event: Any,
) -> dict[str, Any]:
    """Assemble visible continuity and its separate terminal occupancy."""
    periods, _ = history_sleep_timeline(
        stage_points,
        status_points,
        report_end=report_end,
        sample_interval_s=sample_interval_s,
        fallback_estimator=fallback_estimator,
    )
    terminal_occupancy = terminal_occupancy_timeline(
        raw_timeline,
        session_end=report_end,
        sample_interval_s=sample_interval_s,
    )
    classification_end = (
        terminal_occupancy[0].get("start_time")
        if terminal_occupancy else report_end
    )
    if terminal_occupancy:
        periods = clip_history_sleep_timeline(
            periods,
            classification_end=classification_end,
        )
    periods = fill_history_sleep_timeline_continuity(
        periods,
        session_start=session_start,
        classification_end=classification_end,
        fallback_estimator=fallback_estimator,
    )
    terminal_wake = persisted_terminal_wake
    if not isinstance(terminal_wake, dict):
        terminal_wake = terminal_wake_event
    if not isinstance(terminal_wake, dict) and session_end:
        terminal_wake = terminal_wake_transition(
            periods,
            terminal_occupancy=terminal_occupancy,
            session_end=report_end,
            end_reason=end_reason,
        )
        if terminal_wake:
            terminal_wake["display_reconstructed"] = True
            terminal_wake["persisted_record_unchanged"] = True
    if (
        isinstance(terminal_wake, dict)
        and terminal_wake.get("state") == "wake"
        and periods
        and periods[-1].get("state") != "wake"
    ):
        periods.append(terminal_wake)
    return {
        "sleep_timeline": periods,
        "terminal_occupancy": terminal_occupancy,
        "classification_end": classification_end,
        "terminal_wake": terminal_wake,
    }


def project_history_report_samples(
    samples: list[dict[str, Any]],
    *,
    start_at: Any,
    end_at: Any,
    cadence_segments: Any,
    sensor_interval_s: float,
    decision_interval_s: float,
    stage_points: Sequence[Mapping[str, Any]],
    status_points: Sequence[Mapping[str, Any]],
    timeline_periods: Sequence[Mapping[str, Any]],
    terminal_occupancy: Sequence[Mapping[str, Any]],
    heart_rate_range: tuple[float, float],
    respiration_rate_range: tuple[float, float],
) -> dict[str, Any]:
    """Build the same complete projected stream used by live finalization."""
    stages = [
        {"timestamp": point.get("timestamp"), "value": point}
        for point in stage_points
    ]
    statuses = [
        {"timestamp": point.get("timestamp"), "value": point}
        for point in status_points
    ]
    if terminal_occupancy:
        occupancy = terminal_occupancy[0]
        statuses.append({
            "timestamp": occupancy.get("end_time") or end_at,
            "value": {
                "state": "off_bed",
                "data_status": "confirmed_off_bed",
                "attribution_start": occupancy.get("start_time"),
                "attribution_end": occupancy.get("end_time") or end_at,
                "score_eligible": False,
                "excluded_from_score": True,
                "excluded_from_personal_baseline": True,
            },
        })
    boundaries = [
        period.get(boundary)
        for period in [*timeline_periods, *terminal_occupancy]
        for boundary in ("start_time", "end_time")
        if period.get(boundary)
    ]
    return project_report_samples(
        samples,
        start_at=start_at,
        end_at=end_at,
        cadence_segments=cadence_segments,
        split_boundaries=boundaries,
        sensor_interval_s=sensor_interval_s,
        decision_interval_s=decision_interval_s,
        stage_events=stages,
        status_events=statuses,
        heart_rate_range=heart_rate_range,
        respiration_rate_range=respiration_rate_range,
    )
