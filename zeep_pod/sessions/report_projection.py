"""One projection pipeline shared by final and historical Session reports."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sleep_system_policy import ZEEP_OFF_BED_DATA_STATUSES

from .cadence import (
    materialise_report_sample_grid,
    normalise_samples_for_report,
    sample_interval_seconds,
)
from .sleep_decision_projection import (
    DEFAULT_HEART_RATE_RANGE,
    DEFAULT_RESPIRATION_RATE_RANGE,
    SLEEP_STATES,
    apply_sleep_decisions_to_samples,
)
from .sleep_event_data import decision_interval, event_value


def decision_split_boundaries(
    events: Sequence[Mapping[str, Any]],
    *,
    fallback_interval_s: float,
) -> list[float]:
    """Return exact start/end boundaries for durable decision intervals."""
    boundaries: list[float] = []
    for event in events:
        interval = decision_interval(
            event,
            event_value(event),
            fallback_interval_s=fallback_interval_s,
        )
        if interval is not None:
            boundaries.extend(interval)
    return boundaries


def weighted_sleep_state_counts(
    samples: Sequence[Mapping[str, Any]],
    *,
    sample_interval_s: float,
) -> tuple[dict[str, float], dict[str, float]]:
    """Count display and score states in report-interval units."""
    interval = sample_interval_seconds(sample_interval_s, 5.0)
    display: dict[str, float] = {}
    scored: dict[str, float] = {}
    for sample in samples:
        state = sample.get("sleep")
        if state not in SLEEP_STATES:
            continue
        weight = sample_interval_seconds(
            sample.get("sample_interval_s"), interval
        ) / interval
        display[str(state)] = display.get(str(state), 0.0) + weight
        if sample.get("sleep_score_eligible") is not False:
            scored[str(state)] = scored.get(str(state), 0.0) + weight
    return display, scored


def weighted_bed_status_counts(
    samples: Sequence[Mapping[str, Any]],
    *,
    sample_interval_s: float,
) -> dict[str, float]:
    """Count Bed Status in report-interval units."""
    interval = sample_interval_seconds(sample_interval_s, 5.0)
    counts: dict[str, float] = {}
    for sample in samples:
        status = sample.get("bed")
        if not status:
            continue
        weight = sample_interval_seconds(
            sample.get("sample_interval_s"), interval
        ) / interval
        counts[str(status)] = counts.get(str(status), 0.0) + weight
    return counts


def sleep_attribution_accounting(
    samples: Sequence[Mapping[str, Any]],
    *,
    fallback_interval_s: float,
) -> dict[str, Any]:
    """Account every materialised second as State, OFF BED or invalid."""
    state_seconds = 0.0
    off_bed_seconds = 0.0
    unattributed_seconds = 0.0
    for sample in samples:
        seconds = sample_interval_seconds(
            sample.get("sample_interval_s"), fallback_interval_s
        )
        if sample.get("sleep") in SLEEP_STATES:
            state_seconds += seconds
        elif str(sample.get("sleep_data_status") or "").lower() in (
            ZEEP_OFF_BED_DATA_STATUSES
        ):
            off_bed_seconds += seconds
        else:
            unattributed_seconds += seconds
    return {
        "five_state_seconds": round(state_seconds, 3),
        "off_bed_seconds": round(off_bed_seconds, 3),
        "unattributed_seconds": round(unattributed_seconds, 3),
        "classification_complete": unattributed_seconds <= 0.001,
    }


def project_report_samples(
    samples: list[dict[str, Any]],
    *,
    start_at: Any,
    end_at: Any,
    cadence_segments: Any,
    split_boundaries: Any = (),
    sensor_interval_s: float,
    decision_interval_s: float,
    stage_events: Sequence[Mapping[str, Any]],
    status_events: Sequence[Mapping[str, Any]],
    heart_rate_range: tuple[float, float] = DEFAULT_HEART_RATE_RANGE,
    respiration_rate_range: tuple[float, float] = (
        DEFAULT_RESPIRATION_RATE_RANGE
    ),
) -> dict[str, Any]:
    """Materialise, label and normalise one complete report stream."""
    explicit_boundaries = (
        list(split_boundaries)
        if isinstance(split_boundaries, (list, tuple, set, frozenset))
        else []
    )
    exact_boundaries = decision_split_boundaries(
        [*stage_events, *status_events],
        fallback_interval_s=decision_interval_s,
    )
    projected, grid_summary = materialise_report_sample_grid(
        samples,
        start_at=start_at,
        end_at=end_at,
        cadence_segments=cadence_segments,
        split_boundaries=[*explicit_boundaries, *exact_boundaries],
        fallback_interval_s=sensor_interval_s,
    )
    apply_sleep_decisions_to_samples(
        projected,
        stage_events=stage_events,
        status_events=status_events,
        fallback_interval_s=decision_interval_s,
        heart_rate_range=heart_rate_range,
        respiration_rate_range=respiration_rate_range,
    )
    grid_summary.update(sleep_attribution_accounting(
        projected,
        fallback_interval_s=sensor_interval_s,
    ))
    report_samples, report_interval_s, cadence_summary = (
        normalise_samples_for_report(projected, sensor_interval_s)
    )
    display_counts, score_counts = weighted_sleep_state_counts(
        report_samples,
        sample_interval_s=report_interval_s,
    )
    return {
        "samples": projected,
        "report_samples": report_samples,
        "report_interval_s": report_interval_s,
        "cadence_summary": cadence_summary,
        "grid_summary": grid_summary,
        "sleep_state_counts": display_counts,
        "sleep_score_state_counts": score_counts,
        "bed_status_counts": weighted_bed_status_counts(
            report_samples,
            sample_interval_s=report_interval_s,
        ),
    }
