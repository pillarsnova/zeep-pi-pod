"""Project durable Sleep decisions onto the Session Sensor timeline."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from sleep_system_policy import (
    ZEEP_OFF_BED_DATA_STATUSES,
    continuity_hold_contract,
)

from .sleep_event_data import decision_interval, event_value, finite_number
from .sleep_occupancy import (
    CONFIRMED_RETURN_PROVENANCE as _CONFIRMED_RETURN_PROVENANCE,
    DEFAULT_HEART_RATE_RANGE,
    DEFAULT_RESPIRATION_RATE_RANGE,
    SLEEP_STATES,
    confirmed_bed_exit_evidence as _confirmed_bed_exit_evidence,
    sample_confirms_fresh_on_bed_return,
    sample_confirms_off_bed,
)

INITIAL_CONFIRMATION_MAX_SECONDS = 120.0
EVIDENCE_EPOCH_SECONDS = 30.0

_PROVENANCE_FIELDS = {
    "sleep_estimator_version": "estimator_version",
    "sleep_evidence_version": "evidence_version",
    "sleep_baseline_version": "baseline_version",
    "sleep_transition_policy": "transition_policy_version",
}
_VERSION_FIELDS = tuple(_PROVENANCE_FIELDS)
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
    "sleep_pending_state",
    "sleep_occupancy_provenance",
    "acoustic_corroborated",
)


@dataclass
class _ProjectionCursor:
    """State needed while filling gaps in timestamp order."""

    previous_stage: str | None = None
    previous_versions: dict[str, Any] = field(default_factory=dict)
    off_bed_latched: bool = False
    occupied_return_provenance: str | None = None


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
    metrics = value.get("metrics") or {}
    auxiliary = (
        metrics.get("auxiliary_evidence")
        if isinstance(metrics, Mapping)
        else {}
    ) or {}
    acoustic = (
        auxiliary.get("acoustic")
        if isinstance(auxiliary, Mapping)
        else {}
    ) or {}
    held = bool(value.get("held_previous_state"))
    provisional = bool(value.get("provisional"))
    baseline_excluded = bool(
        held
        or provisional
        or value.get("excluded_from_personal_baseline", False)
    )
    return {
        "sleep": stage,
        "sleep_confirmed_state": stage,
        **_event_provenance(value),
        "sleep_confidence": value.get("confidence"),
        "sleep_probability": (value.get("probabilities") or {}).get(stage),
        "sleep_confirmation": confirmation,
        "sleep_evidence_candidate": (
            confirmation.get("pending_state") or value.get("pending_state")
        ),
        "sleep_decision_kind": value.get("decision_kind"),
        "sleep_occupancy_provenance": "durable_stage_event",
        "acoustic_corroborated": bool(
            isinstance(acoustic, Mapping) and acoustic.get("corroborated")
        ),
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
        # Every durable five-state decision owns occupied Session time.  Old
        # events may carry v1.28 provisional-exclusion flags; those flags are
        # compatibility provenance, not authority to reopen a time gap under
        # the complete occupied-epoch contract.
        "sleep_score_eligible": True,
        "sleep_excluded_from_score": False,
        "sleep_excluded_from_personal_baseline": baseline_excluded,
        "_sleep_attribution_projected": True,
    }


def _apply_status_events(
    samples: list[dict[str, Any]],
    events: Sequence[Mapping[str, Any]],
    *,
    fallback_interval_s: float,
) -> None:
    """Apply only explicit occupancy boundaries over five-state continuity.

    Historical WAIT/NO DATA rows are evidence-quality metadata. They no longer
    erase an occupied Epoch; the gap filler below attributes that time to W or
    the last confirmed State. Confirmed OFF BED remains authoritative.
    """
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
        ).strip().lower()
        if not _status_ends_occupancy(status, value):
            continue
        if status not in ZEEP_OFF_BED_DATA_STATUSES:
            # Confirmed evidence and legacy durable state=off_bed are both
            # authoritative even when they lack a modern canonical status.
            status = "confirmed_off_bed"
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
    """Fill every leftover row with continuity or confirmed OFF BED."""
    ordered = sorted(
        range(len(samples)),
        key=lambda index: _sample_time(samples[index]),
    )
    cursor = _ProjectionCursor()
    for index in ordered:
        sample = samples[index]
        confirmed_off_bed = sample_confirms_off_bed(sample)
        return_confirmed = sample_confirms_fresh_on_bed_return(
            sample,
            heart_rate_range=heart_rate_range,
            respiration_rate_range=respiration_rate_range,
        )
        projected = bool(sample.pop("_sleep_attribution_projected", False))
        if projected:
            stage = sample.get("sleep")
            if confirmed_off_bed and stage in SLEEP_STATES:
                cursor.off_bed_latched = True
                cursor.occupied_return_provenance = None
                sample.update(_operational_updates(
                    "empty_bed",
                    provenance={
                        **cursor.previous_versions,
                        **_sample_provenance(sample),
                    },
                ))
            elif cursor.off_bed_latched and stage in SLEEP_STATES:
                # This stage exists only because _apply_stage_events projected
                # a durable decision; cached/raw sample stages were reset. Live
                # commits a stage only from valid occupied evidence, so the
                # event is canonical return proof even when old Timeline rows
                # lack bcg_analysis_valid.
                cursor.off_bed_latched = False
            _remember_projected_state(cursor, sample)
            continue
        updates = _fallback_updates(
            sample,
            cursor=cursor,
            return_confirmed=return_confirmed,
        )
        sample.update(updates)
        _remember_projected_state(cursor, sample)


def _remember_projected_state(
    cursor: _ProjectionCursor,
    sample: Mapping[str, Any],
) -> None:
    """Advance continuity only through an explicit Stage decision."""
    stage = sample.get("sleep")
    provenance = _sample_provenance(sample)
    if stage in SLEEP_STATES:
        cursor.previous_stage = str(stage)
        cursor.previous_versions = {
            **cursor.previous_versions,
            **provenance,
        }
        return_source = sample.get("sleep_occupancy_provenance")
        cursor.occupied_return_provenance = (
            str(return_source)
            if return_source in _CONFIRMED_RETURN_PROVENANCE
            else None
        )
        return
    if sample_confirms_off_bed(sample):
        cursor.off_bed_latched = True
        cursor.occupied_return_provenance = None
        cursor.previous_versions = {
            **cursor.previous_versions,
            **provenance,
        }
    cursor.previous_stage = None


def _fallback_updates(
    sample: Mapping[str, Any],
    *,
    cursor: _ProjectionCursor,
    return_confirmed: bool,
) -> dict[str, Any]:
    """Give every non-OFF-BED Session row a scoreable five-state label."""
    if sample_confirms_off_bed(sample):
        cursor.off_bed_latched = True
        cursor.occupied_return_provenance = None
        return _operational_updates(
            "empty_bed", provenance=cursor.previous_versions
        )
    if cursor.off_bed_latched and not return_confirmed:
        return _operational_updates(
            "empty_bed", provenance=cursor.previous_versions
        )
    if return_confirmed:
        cursor.off_bed_latched = False
        cursor.occupied_return_provenance = (
            "fresh_same_packet_hr_rr_bcg"
        )
    return _carry_updates(cursor)


def _carry_updates(cursor: _ProjectionCursor) -> dict[str, Any]:
    """Carry the last State, or anchor initial occupied time at Wake."""
    confirmation = continuity_hold_contract(
        cursor.previous_stage,
        decision="projected_occupied_gap_hold",
    )
    stage = str(confirmation["confirmed_state"])
    return {
        "sleep": stage,
        "sleep_confirmed_state": stage,
        "sleep_evidence_candidate": None,
        "sleep_confirmation": confirmation,
        "sleep_provisional": False,
        "sleep_held_previous_state": bool(
            confirmation["held_previous_state"]
        ),
        "sleep_data_status": str(confirmation["data_status"]),
        "sleep_score_attribution_state": stage,
        "sleep_challenger_counted_as_new_state": False,
        "sleep_score_eligible": True,
        "sleep_excluded_from_score": False,
        "sleep_excluded_from_personal_baseline": True,
        "sleep_confidence": "low",
        "sleep_probability": None,
        "sleep_decision_kind": confirmation["decision_kind"],
        "sleep_occupancy_provenance": (
            cursor.occupied_return_provenance
        ),
        "acoustic_corroborated": False,
        **cursor.previous_versions,
    }


def _status_ends_occupancy(
    status: str,
    value: Mapping[str, Any],
) -> bool:
    """Return whether a durable status explicitly proves no occupant."""
    state = str(value.get("state") or "").strip().lower()
    explicit_status = value.get("data_status") or value.get("status")
    return bool(
        status.strip().lower() in ZEEP_OFF_BED_DATA_STATUSES
        # Older canonical status events stored only state=off_bed. Accept that
        # durable representation, but never let an explicitly contradictory
        # data-quality status manufacture a latch.
        or (state == "off_bed" and explicit_status is None)
        or _confirmed_bed_exit_evidence(value)
    )


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
        **_event_provenance(value),
        "sleep_occupancy_provenance": "canonical_off_bed_status",
        "acoustic_corroborated": False,
        "sleep_confidence": value.get("confidence") or "low",
        "sleep_probability": None,
        "_sleep_attribution_projected": True,
    }


def _operational_updates(
    data_status: str,
    *,
    provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
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
        "sleep_occupancy_provenance": "confirmed_off_bed_continuity",
        "acoustic_corroborated": False,
        **dict(provenance or {}),
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


def _event_provenance(value: Mapping[str, Any]) -> dict[str, Any]:
    """Translate all durable decision-version fields to Timeline names."""
    return {
        timeline_field: value.get(event_field)
        for timeline_field, event_field in _PROVENANCE_FIELDS.items()
        if value.get(event_field) is not None
    }


def _sample_provenance(sample: Mapping[str, Any]) -> dict[str, Any]:
    """Keep known provenance while extending a durable decision or status."""
    return {
        field: sample.get(field)
        for field in _VERSION_FIELDS
        if sample.get(field) is not None
    }
