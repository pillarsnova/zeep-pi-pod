"""Project durable Sleep decisions onto the Session Sensor timeline."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .sleep_event_data import decision_interval, event_value, finite_number

SLEEP_STATES = frozenset({"wake", "n1", "n2", "n3", "rem"})
DEFAULT_HEART_RATE_RANGE = (25.0, 220.0)
DEFAULT_RESPIRATION_RATE_RANGE = (2.0, 60.0)
INITIAL_CONFIRMATION_MAX_SECONDS = 120.0
EVIDENCE_EPOCH_SECONDS = 30.0

_OFF_BED_LABELS = frozenset(
    {"get out of bed", "off bed", "off_bed", "empty bed"}
)
_VERSION_FIELDS = (
    "sleep_estimator_version",
    "sleep_evidence_version",
    "sleep_baseline_version",
    "sleep_transition_policy",
)
_SLEEP_PROJECTION_FIELDS = (
    "sleep",
    "sleep_confirmed_state",
    "sleep_evidence_candidate",
    "sleep_confirmation",
    "sleep_provisional",
    "sleep_held_previous_state",
    "sleep_data_status",
    "sleep_score_attribution_state",
    "sleep_challenger_counted_as_new_state",
    "sleep_score_eligible",
    "sleep_excluded_from_score",
    "sleep_excluded_from_personal_baseline",
    "sleep_estimator_version",
    "sleep_evidence_version",
    "sleep_baseline_version",
    "sleep_transition_policy",
    "sleep_confidence",
    "sleep_probability",
    "sleep_decision_kind",
)


@dataclass
class _ProjectionCursor:
    """State needed while filling gaps in timestamp order."""

    first_projected: int | None
    last_projected: int | None
    first_sample_time: float
    previous_stage: str | None = None
    previous_versions: dict[str, Any] = field(default_factory=dict)


def apply_sleep_decisions_to_samples(
    samples: list[dict[str, Any]],
    *,
    stage_events: Sequence[Mapping[str, Any]],
    status_events: Sequence[Mapping[str, Any]] = (),
    fallback_interval_s: float,
    heart_rate_range: tuple[float, float] = DEFAULT_HEART_RATE_RANGE,
    respiration_rate_range: tuple[float, float] = (
        DEFAULT_RESPIRATION_RATE_RANGE
    ),
) -> None:
    """Project right-closed 30-second decisions onto 10-second samples.

    Session sampling and estimator analysis are asynchronous. Persisted
    attribution intervals, rather than cached Dashboard state, therefore own
    the labels used by reports, scores and restart recovery. Operational
    status is applied last so it wins over a stale Stage snapshot.
    """
    _reset_projection_fields(samples)
    _apply_stage_events(
        samples,
        stage_events,
        fallback_interval_s=fallback_interval_s,
    )
    _apply_status_events(
        samples,
        status_events,
        fallback_interval_s=fallback_interval_s,
    )
    _fill_unattributed_samples(
        samples,
        fallback_interval_s=fallback_interval_s,
        heart_rate_range=heart_rate_range,
        respiration_rate_range=respiration_rate_range,
    )


def _reset_projection_fields(samples: list[dict[str, Any]]) -> None:
    """Discard forward-looking UI snapshots before durable replay."""
    for sample in samples:
        for key in _SLEEP_PROJECTION_FIELDS:
            sample.pop(key, None)


def _apply_stage_events(
    samples: list[dict[str, Any]],
    events: Sequence[Mapping[str, Any]],
    *,
    fallback_interval_s: float,
) -> None:
    """Apply persisted five-state decisions to their owned samples."""
    for event in events:
        value = event_value(event)
        stage = value.get("state")
        if stage not in SLEEP_STATES:
            continue
        interval = decision_interval(
            event,
            value,
            fallback_interval_s=fallback_interval_s,
        )
        if interval is None:
            continue
        start_epoch, end_epoch = interval
        updates = _stage_updates(str(stage), value)
        for sample in samples:
            if _sample_owned_by_interval(sample, start_epoch, end_epoch):
                sample.update(updates)


def _stage_updates(
    stage: str,
    value: Mapping[str, Any],
) -> dict[str, Any]:
    """Build timeline fields for one confirmed or held Stage event."""
    confirmation = value.get("confirmation") or {}
    held = bool(value.get("held_previous_state"))
    provisional = bool(value.get("provisional"))
    return {
        "sleep": stage,
        "sleep_confirmed_state": stage,
        "sleep_estimator_version": value.get("estimator_version"),
        "sleep_evidence_version": value.get("evidence_version"),
        "sleep_confidence": value.get("confidence"),
        "sleep_probability": (value.get("probabilities") or {}).get(stage),
        "sleep_confirmation": confirmation,
        "sleep_evidence_candidate": (
            confirmation.get("pending_state") or value.get("pending_state")
        ),
        "sleep_decision_kind": value.get("decision_kind"),
        "sleep_held_previous_state": held,
        "sleep_provisional": provisional,
        "sleep_pending_state": value.get("pending_state"),
        "sleep_data_status": (
            "provisional_hold"
            if held and provisional
            else "continuity_hold"
            if held
            else "live"
        ),
        "sleep_score_attribution_state": (
            value.get("score_attribution_state") or stage
        ),
        "sleep_challenger_counted_as_new_state": bool(
            value.get("challenger_counted_as_new_state")
        ),
        "sleep_score_eligible": bool(value.get("score_eligible", True)),
        "sleep_excluded_from_score": bool(
            value.get("excluded_from_score", False)
        ),
        "sleep_excluded_from_personal_baseline": bool(
            value.get("excluded_from_personal_baseline", False)
        ),
        "_sleep_attribution_projected": True,
    }


def _apply_status_events(
    samples: list[dict[str, Any]],
    events: Sequence[Mapping[str, Any]],
    *,
    fallback_interval_s: float,
) -> None:
    """Apply WAIT/NO DATA/OFF BED without inventing a Sleep Stage."""
    for event in events:
        value = event_value(event)
        interval = decision_interval(
            event,
            value,
            fallback_interval_s=fallback_interval_s,
        )
        if interval is None:
            continue
        start_epoch, end_epoch = interval
        status = str(
            value.get("data_status") or value.get("status") or "no_data"
        )
        updates = _status_event_updates(status, value)
        for sample in samples:
            if _sample_owned_by_interval(sample, start_epoch, end_epoch):
                sample.update(updates)


def _fill_unattributed_samples(
    samples: list[dict[str, Any]],
    *,
    fallback_interval_s: float,
    heart_rate_range: tuple[float, float],
    respiration_rate_range: tuple[float, float],
) -> None:
    """Fill every leftover row with a bounded hold or explicit status."""
    ordered = sorted(
        range(len(samples)),
        key=lambda index: _sample_time(samples[index]),
    )
    cursor = _projection_cursor(samples, ordered)
    for position, index in enumerate(ordered):
        sample = samples[index]
        projected = bool(sample.pop("_sleep_attribution_projected", False))
        if projected:
            _remember_projected_state(cursor, sample)
            continue
        updates = _fallback_updates(
            sample,
            position=position,
            ordered=ordered,
            samples=samples,
            cursor=cursor,
            fallback_interval_s=fallback_interval_s,
            heart_rate_range=heart_rate_range,
            respiration_rate_range=respiration_rate_range,
        )
        sample.update(updates)


def _projection_cursor(
    samples: Sequence[Mapping[str, Any]],
    ordered: Sequence[int],
) -> _ProjectionCursor:
    """Locate the durable portion of the timeline before gap filling."""
    positions = [
        position
        for position, index in enumerate(ordered)
        if samples[index].get("_sleep_attribution_projected")
    ]
    return _ProjectionCursor(
        first_projected=positions[0] if positions else None,
        last_projected=positions[-1] if positions else None,
        first_sample_time=(
            _sample_time(samples[ordered[0]]) if ordered else math.inf
        ),
    )


def _remember_projected_state(
    cursor: _ProjectionCursor,
    sample: Mapping[str, Any],
) -> None:
    """Advance continuity only through an explicit Stage decision."""
    stage = sample.get("sleep")
    if stage in SLEEP_STATES:
        cursor.previous_stage = str(stage)
        cursor.previous_versions = {
            key: sample.get(key) for key in _VERSION_FIELDS
        }
        return
    cursor.previous_stage = None
    cursor.previous_versions = {}


def _fallback_updates(
    sample: Mapping[str, Any],
    *,
    position: int,
    ordered: Sequence[int],
    samples: Sequence[Mapping[str, Any]],
    cursor: _ProjectionCursor,
    fallback_interval_s: float,
    heart_rate_range: tuple[float, float],
    respiration_rate_range: tuple[float, float],
) -> dict[str, Any]:
    """Choose a safe attribution for one row lacking a durable decision."""
    off_bed = _is_off_bed(sample)
    paired_vitals = _paired_vitals(
        sample,
        heart_rate_range=heart_rate_range,
        respiration_rate_range=respiration_rate_range,
    )
    bcg_valid = sample.get("bcg_analysis_valid") is True
    if (
        cursor.previous_stage in SLEEP_STATES
        and paired_vitals
        and bcg_valid
        and not off_bed
        and _within_partial_tail(
            position,
            ordered=ordered,
            samples=samples,
            cursor=cursor,
            fallback_interval_s=fallback_interval_s,
        )
    ):
        return _tail_hold_updates(cursor)
    if off_bed:
        return _operational_updates("empty_bed")
    if not paired_vitals:
        return _operational_updates("invalid_or_missing_current_vitals")
    if not bcg_valid:
        return _operational_updates("invalid_current_bcg")
    if cursor.first_projected is None or position < cursor.first_projected:
        return _initial_status_updates(sample, cursor=cursor)
    return _operational_updates("missing_durable_sleep_decision")


def _within_partial_tail(
    position: int,
    *,
    ordered: Sequence[int],
    samples: Sequence[Mapping[str, Any]],
    cursor: _ProjectionCursor,
    fallback_interval_s: float,
) -> bool:
    """Allow display continuity only in the unfinished acquisition tail."""
    if cursor.last_projected is None or position <= cursor.last_projected:
        return False
    tail_start = _sample_time(samples[ordered[cursor.last_projected]])
    current_time = _sample_time(samples[ordered[position]])
    limit = max(EVIDENCE_EPOCH_SECONDS, float(fallback_interval_s))
    return current_time - tail_start <= limit + 0.001


def _initial_status_updates(
    sample: Mapping[str, Any],
    *,
    cursor: _ProjectionCursor,
) -> dict[str, Any]:
    """Bound the initial WAIT label to at most 120 wall-clock seconds."""
    interval = max(0.1, float(sample.get("sample_interval_s") or 10.0))
    elapsed = _sample_time(sample) - cursor.first_sample_time + interval
    status = (
        "confirming_initial_state"
        if elapsed <= INITIAL_CONFIRMATION_MAX_SECONDS
        else "initial_confirmation_timeout"
    )
    return _operational_updates(status)


def _tail_hold_updates(cursor: _ProjectionCursor) -> dict[str, Any]:
    """Keep the prior State visible while excluding the partial epoch."""
    stage = cursor.previous_stage
    return {
        "sleep": stage,
        "sleep_confirmed_state": stage,
        "sleep_evidence_candidate": None,
        "sleep_confirmation": {
            "decision": "partial_epoch_continuity_hold",
            "decision_kind": "continuity_hold",
            "held_previous_state": True,
            "provisional": True,
            "score_eligible": False,
            "excluded_from_score": True,
        },
        "sleep_provisional": True,
        "sleep_held_previous_state": True,
        "sleep_data_status": "provisional_hold",
        "sleep_score_attribution_state": stage,
        "sleep_challenger_counted_as_new_state": False,
        "sleep_score_eligible": False,
        "sleep_excluded_from_score": True,
        "sleep_excluded_from_personal_baseline": True,
        "sleep_confidence": "low",
        "sleep_probability": None,
        "sleep_decision_kind": "continuity_hold",
        **cursor.previous_versions,
    }


def _status_event_updates(
    data_status: str,
    value: Mapping[str, Any],
) -> dict[str, Any]:
    """Build fields for one persisted operational-status event."""
    return {
        "sleep": None,
        "sleep_confirmed_state": None,
        "sleep_evidence_candidate": value.get("candidate"),
        "sleep_confirmation": value.get("confirmation") or {},
        "sleep_provisional": bool(value.get("provisional", True)),
        "sleep_held_previous_state": False,
        "sleep_data_status": data_status,
        "sleep_score_attribution_state": None,
        "sleep_challenger_counted_as_new_state": False,
        "sleep_score_eligible": False,
        "sleep_excluded_from_score": True,
        "sleep_excluded_from_personal_baseline": True,
        "sleep_estimator_version": value.get("estimator_version"),
        "sleep_evidence_version": value.get("evidence_version"),
        "sleep_baseline_version": value.get("baseline_version"),
        "sleep_transition_policy": value.get("transition_policy_version"),
        "sleep_confidence": value.get("confidence") or "low",
        "sleep_probability": None,
        "_sleep_attribution_projected": True,
    }


def _operational_updates(data_status: str) -> dict[str, Any]:
    """Build fields for an inferred non-scoring operational status."""
    return {
        "sleep": None,
        "sleep_confirmed_state": None,
        "sleep_evidence_candidate": None,
        "sleep_confirmation": {},
        "sleep_provisional": True,
        "sleep_held_previous_state": False,
        "sleep_data_status": data_status,
        "sleep_score_attribution_state": None,
        "sleep_challenger_counted_as_new_state": False,
        "sleep_score_eligible": False,
        "sleep_excluded_from_score": True,
        "sleep_excluded_from_personal_baseline": True,
        "sleep_confidence": "low",
        "sleep_probability": None,
        "sleep_decision_kind": "operational_status",
    }


def _sample_owned_by_interval(
    sample: Mapping[str, Any],
    start_epoch: float,
    end_epoch: float,
) -> bool:
    """Return whether a Sensor row belongs to a right-closed interval."""
    timestamp = _sample_time(sample)
    return math.isfinite(timestamp) and start_epoch < timestamp <= end_epoch + 0.001


def _sample_time(sample: Mapping[str, Any]) -> float:
    """Prefer the Session acquisition clock over lagging analysis time."""
    value = sample.get("t")
    if not finite_number(value):
        value = sample.get("analysis_epoch_s")
    return float(value) if finite_number(value) else math.inf


def _is_off_bed(sample: Mapping[str, Any]) -> bool:
    return str(sample.get("bed") or "").strip().lower() in _OFF_BED_LABELS


def _paired_vitals(
    sample: Mapping[str, Any],
    *,
    heart_rate_range: tuple[float, float],
    respiration_rate_range: tuple[float, float],
) -> bool:
    """Require a physiologically plausible paired HR/RR observation."""
    heart_rate = sample.get("hr")
    respiration_rate = sample.get("rr")
    return bool(
        finite_number(heart_rate)
        and heart_rate_range[0] <= float(heart_rate) <= heart_rate_range[1]
        and finite_number(respiration_rate)
        and respiration_rate_range[0]
        <= float(respiration_rate)
        <= respiration_rate_range[1]
    )
