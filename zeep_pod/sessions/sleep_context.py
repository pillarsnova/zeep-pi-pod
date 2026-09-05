"""Pure restart-continuity rules for the five-state Sleep estimator."""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Any

SLEEP_STATES = frozenset({"wake", "n1", "n2", "n3", "rem"})

SessionReader = Callable[..., list[dict[str, Any]]]


def checkpoint_sleep_context(
    path: Mapping[str, Any],
    session_id: str | None,
) -> dict[str, Any] | None:
    """Copy only physiology needed to continue one active Session."""
    if not session_id or path.get("session_id") != session_id:
        return None
    return {
        "session_id": session_id,
        "awake_vital_pairs": list(path.get("awake_vital_pairs") or []),
        "awake_hr_reference": path.get("awake_hr_reference"),
        "awake_rr_reference": path.get("awake_rr_reference"),
        "sleep_onset_at": path.get("sleep_onset_at"),
        "last_valid_frame_t": path.get("last_valid_frame_t"),
    }


def restore_sleep_context(
    session_id: str,
    *,
    stage_events: Sequence[Mapping[str, Any]],
    evidence_events: Sequence[Mapping[str, Any]],
    samples: Sequence[Mapping[str, Any]],
    checkpoint_context: Mapping[str, Any] | None,
    heart_rate_range: tuple[float, float],
    respiration_rate_range: tuple[float, float],
) -> dict[str, Any]:
    """Rebuild confirmed path and frozen Awake references from durable data."""
    path = _replay_confirmed_path(session_id, stage_events)
    context = checkpoint_context or {}
    context_matches = context.get("session_id") == session_id

    saved_onset = context.get("sleep_onset_at") if context_matches else None
    if _finite_number(saved_onset):
        path["sleep_onset_at"] = float(saved_onset)
    onset = path.get("sleep_onset_at")

    saved_pairs = context.get("awake_vital_pairs") if context_matches else []
    pairs = _valid_vital_pairs(
        saved_pairs or [],
        heart_rate_range=heart_rate_range,
        respiration_rate_range=respiration_rate_range,
    )
    if not pairs and _finite_number(onset):
        pairs = _pre_onset_pairs(
            samples,
            onset=float(onset),
            heart_rate_range=heart_rate_range,
            respiration_rate_range=respiration_rate_range,
        )
    pairs = sorted(pairs, key=lambda item: item[0])[-720:]

    saved_hr = context.get("awake_hr_reference") if context_matches else None
    saved_rr = context.get("awake_rr_reference") if context_matches else None
    if len(pairs) >= 6:
        saved_hr = _upper_quartile([item[1] for item in pairs])
        saved_rr = _upper_quartile([item[2] for item in pairs])
    if not (_finite_number(saved_hr) and _finite_number(saved_rr)):
        saved_hr, saved_rr = _evidence_awake_references(evidence_events)

    path.update(
        {
            "awake_vital_pairs": pairs,
            "awake_hr_reference": saved_hr,
            "awake_rr_reference": saved_rr,
        }
    )
    saved_last_frame = (
        context.get("last_valid_frame_t") if context_matches else None
    )
    if _finite_number(saved_last_frame):
        path["last_valid_frame_t"] = float(saved_last_frame)

    source = "unavailable"
    if context_matches and saved_pairs:
        source = "checkpoint"
    elif pairs:
        source = "pre_onset_timeline"
    elif _finite_number(saved_hr) and _finite_number(saved_rr):
        source = "durable_evidence"
    return {
        "path": path,
        "provenance": {
            "source": source,
            "awake_reference_pairs": len(pairs),
            "awake_hr_reference": saved_hr,
            "awake_rr_reference": saved_rr,
            "sleep_onset_at": path.get("sleep_onset_at"),
            "last_confirmed_state": path.get("last"),
        },
    }


def restore_session_sleep_context(
    read_sessions: SessionReader,
    session_id: str,
    *,
    samples: list[dict[str, Any]],
    checkpoint_context: Mapping[str, Any] | None,
    heart_rate_range: tuple[float, float],
    respiration_rate_range: tuple[float, float],
    fallback_interval_s: float,
) -> dict[str, Any]:
    """Load durable decisions, restore Timeline labels and rebuild context."""
    stage_events = read_sessions(
        """SELECT timestamp,value FROM events
           WHERE session_id=? AND type='sleep_stage' ORDER BY timestamp""",
        (session_id,),
    )
    evidence_events = read_sessions(
        """SELECT timestamp,value FROM events
           WHERE session_id=? AND type='sleep_stage_evidence'
           ORDER BY timestamp DESC""",
        (session_id,),
    )
    _apply_confirmed_stages_to_samples(
        samples,
        stage_events,
        fallback_interval_s=fallback_interval_s,
    )
    return restore_sleep_context(
        session_id,
        stage_events=stage_events,
        evidence_events=evidence_events,
        samples=samples,
        checkpoint_context=checkpoint_context,
        heart_rate_range=heart_rate_range,
        respiration_rate_range=respiration_rate_range,
    )


def _apply_confirmed_stages_to_samples(
    samples: list[dict[str, Any]],
    events: Sequence[Mapping[str, Any]],
    *,
    fallback_interval_s: float,
) -> None:
    """Restore historical labels without creating any new Sleep decisions."""
    for event in events:
        value = _event_value(event)
        stage = value.get("state")
        if stage not in SLEEP_STATES:
            continue
        end_epoch = _event_epoch(event, value)
        if end_epoch is None:
            continue
        start_epoch = _timestamp(value.get("window_start"))
        if start_epoch is None:
            interval = value.get("sample_interval_s")
            if not _finite_number(interval) or float(interval) <= 0:
                interval = fallback_interval_s
            start_epoch = end_epoch - float(interval)
        for sample in samples:
            timestamp = sample.get("t")
            if _finite_number(timestamp) and (
                start_epoch < float(timestamp) <= end_epoch + 0.001
            ):
                sample.update(
                    {
                        "sleep": stage,
                        "sleep_confirmed_state": stage,
                        "sleep_estimator_version": value.get(
                            "estimator_version"
                        ),
                        "sleep_evidence_version": value.get(
                            "evidence_version"
                        ),
                        "sleep_confidence": value.get("confidence"),
                        "sleep_probability": (
                            value.get("probabilities") or {}
                        ).get(stage),
                    }
                )


def _replay_confirmed_path(
    session_id: str,
    events: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    path: dict[str, Any] = {
        "session_id": session_id,
        "seen": [],
        "last": None,
        "stage_since": None,
        "cycle_has_n1": False,
        "sleep_onset_at": None,
        "awake_vital_pairs": [],
        "awake_hr_reference": None,
        "awake_rr_reference": None,
        "last_valid_frame_t": None,
    }
    for event in events:
        value = _event_value(event)
        stage = value.get("state")
        if stage not in SLEEP_STATES:
            continue
        event_epoch = _event_epoch(event, value)
        if stage == "wake":
            path["seen"].clear()
            path["cycle_has_n1"] = False
        elif stage == "n1":
            path["cycle_has_n1"] = True
            if path["sleep_onset_at"] is None:
                path["sleep_onset_at"] = event_epoch
        if path["last"] != stage:
            path["seen"].append(stage)
            del path["seen"][:-8]
            path["stage_since"] = event_epoch
        path["last"] = stage
    return path


def _pre_onset_pairs(
    samples: Sequence[Mapping[str, Any]],
    *,
    onset: float,
    heart_rate_range: tuple[float, float],
    respiration_rate_range: tuple[float, float],
) -> list[tuple[float, float, float]]:
    raw_pairs = [
        (sample.get("t"), sample.get("hr"), sample.get("rr"))
        for sample in samples
        if _finite_number(sample.get("t")) and float(sample["t"]) < onset
    ]
    return _valid_vital_pairs(
        raw_pairs,
        heart_rate_range=heart_rate_range,
        respiration_rate_range=respiration_rate_range,
    )


def _valid_vital_pairs(
    pairs: Sequence[Any],
    *,
    heart_rate_range: tuple[float, float],
    respiration_rate_range: tuple[float, float],
) -> list[tuple[float, float, float]]:
    valid = []
    for pair in pairs:
        try:
            timestamp, heart_rate, respiration_rate = map(float, pair)
        except (TypeError, ValueError):
            continue
        if (
            math.isfinite(timestamp)
            and heart_rate_range[0] <= heart_rate <= heart_rate_range[1]
            and respiration_rate_range[0]
            <= respiration_rate
            <= respiration_rate_range[1]
        ):
            valid.append((timestamp, heart_rate, respiration_rate))
    return valid


def _evidence_awake_references(
    evidence_events: Sequence[Mapping[str, Any]],
) -> tuple[float | None, float | None]:
    for event in evidence_events:
        metrics = _event_value(event).get("metrics") or {}
        heart_rate = metrics.get("awake_hr_reference")
        respiration_rate = metrics.get("awake_rr_reference")
        if _finite_number(heart_rate) and _finite_number(respiration_rate):
            return float(heart_rate), float(respiration_rate)
    return None, None


def _event_value(event: Mapping[str, Any]) -> dict[str, Any]:
    value = event.get("value")
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return {}
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _event_epoch(
    event: Mapping[str, Any],
    value: Mapping[str, Any],
) -> float | None:
    for candidate in (value.get("window_end"), event.get("timestamp")):
        parsed = _timestamp(candidate)
        if parsed is not None:
            return parsed
    return None


def _timestamp(value: Any) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)).timestamp()
    except (TypeError, ValueError):
        return None


def _upper_quartile(values: Sequence[float]) -> float | None:
    ordered = sorted(float(value) for value in values if _finite_number(value))
    if not ordered:
        return None
    index = min(len(ordered) - 1, int(round((len(ordered) - 1) * 0.75)))
    return ordered[index]


def _finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )
