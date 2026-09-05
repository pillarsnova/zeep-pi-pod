"""Detect the historical long-Wake lock-in signature without relabelling it.

This is an engineering QA rule for ZEEP's non-EEG estimator.  It raises a
review flag only; it never changes W/N1/N2/N3/REM, WASO, scores or raw data.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any


AUDIT_POLICY_VERSION = "zeep-wake-lock-shadow-audit-v1.0"
SLEEP_STATES = frozenset({"n1", "n2", "n3", "rem"})
OFF_BED_LABELS = frozenset(
    {"off", "off_bed", "off bed", "empty", "out", "no user"}
)


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _timestamp(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError, OverflowError):
        return None


def _ratio(items: Iterable[bool]) -> float:
    values = list(items)
    return sum(values) / len(values) if values else 0.0


def _is_on_bed(value: Any) -> bool:
    label = str(value or "").strip().casefold()
    return bool(label and label not in OFF_BED_LABELS and "off" not in label)


def normalise_stage_event(row: dict[str, Any]) -> dict[str, Any] | None:
    """Return the small, auditable subset needed by the detector."""
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else row
    state = str(payload.get("state") or "").strip().casefold()
    when = _timestamp(
        payload.get("window_end") or row.get("timestamp") or row.get("t")
    )
    if state not in {"wake", *SLEEP_STATES} or when is None:
        return None
    metrics = payload.get("metrics")
    if not isinstance(metrics, dict):
        metrics = {}
    interval = _finite_number(payload.get("sample_interval_s")) or 30.0
    return {
        "session_id": str(row.get("session_id") or ""),
        "event_id": int(row.get("id") or 0),
        "t": when,
        "state": state,
        "interval_s": max(1.0, interval),
        "estimator_version": payload.get("estimator_version"),
        "sleep_onset_established": metrics.get("sleep_onset_established"),
        "bed_status": metrics.get("bed_status"),
        "movement_ratio": _finite_number(metrics.get("movement_ratio")),
        "mean_hr": _finite_number(metrics.get("mean_hr")),
        "awake_hr_reference": _finite_number(
            metrics.get("awake_hr_reference")
        ),
    }


def deduplicate_stage_events(
    rows: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep the newest persisted decision per Session/window boundary."""
    latest: dict[tuple[str, float], dict[str, Any]] = {}
    for row in rows:
        event = normalise_stage_event(row)
        if event is None or not event["session_id"]:
            continue
        key = (event["session_id"], event["t"])
        previous = latest.get(key)
        if previous is None or event["event_id"] >= previous["event_id"]:
            latest[key] = event
    return sorted(latest.values(), key=lambda event: (event["session_id"], event["t"]))


def _case_reference(session_id: str) -> str:
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
    return f"WL-{digest[:12]}"


def find_suspected_wake_lock_ins(
    rows: Iterable[dict[str, Any]],
    *,
    minimum_duration_s: float = 600.0,
    maximum_gap_s: float = 45.0,
    maximum_movement_ratio: float = 0.10,
    required_evidence_ratio: float = 0.90,
    estimator_version: str | None = None,
) -> list[dict[str, Any]]:
    """Return coded review findings matching the old Wake lock-in signature."""
    events = deduplicate_stage_events(rows)
    by_session: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        if estimator_version and event["estimator_version"] != estimator_version:
            continue
        by_session.setdefault(event["session_id"], []).append(event)

    findings: list[dict[str, Any]] = []
    for session_id, session_events in by_session.items():
        sleep_seen = False
        bouts: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []
        for event in session_events:
            if event["state"] in SLEEP_STATES:
                sleep_seen = True
            if event["state"] == "wake" and sleep_seen:
                if current and event["t"] - current[-1]["t"] <= maximum_gap_s:
                    current.append(event)
                else:
                    if current:
                        bouts.append(current)
                    current = [event]
            else:
                if current:
                    bouts.append(current)
                    current = []
        if current:
            bouts.append(current)

        for bout in bouts:
            duration_s = bout[-1]["t"] - bout[0]["t"] + bout[-1]["interval_s"]
            if duration_s < minimum_duration_s:
                continue
            onset_lost_ratio = _ratio(
                event["sleep_onset_established"] is False for event in bout
            )
            on_bed_ratio = _ratio(_is_on_bed(event["bed_status"]) for event in bout)
            quiet_ratio = _ratio(
                event["movement_ratio"] is not None
                and event["movement_ratio"] <= maximum_movement_ratio
                for event in bout
            )
            below_reference_ratio = _ratio(
                event["mean_hr"] is not None
                and event["awake_hr_reference"] is not None
                and event["mean_hr"] < event["awake_hr_reference"]
                for event in bout
            )
            ratios = (
                onset_lost_ratio,
                on_bed_ratio,
                quiet_ratio,
                below_reference_ratio,
            )
            if min(ratios) < required_evidence_ratio:
                continue
            findings.append(
                {
                    "case_ref": _case_reference(session_id),
                    "start_utc": datetime.fromtimestamp(
                        bout[0]["t"], UTC
                    ).isoformat(),
                    "end_utc": datetime.fromtimestamp(
                        bout[-1]["t"] + bout[-1]["interval_s"], UTC
                    ).isoformat(),
                    "duration_s": round(duration_s, 1),
                    "epoch_count": len(bout),
                    "onset_lost_ratio": round(onset_lost_ratio, 4),
                    "on_bed_ratio": round(on_bed_ratio, 4),
                    "quiet_ratio": round(quiet_ratio, 4),
                    "hr_below_awake_reference_ratio": round(
                        below_reference_ratio,
                        4,
                    ),
                    "classification": "suspected_wake_lock_in",
                    "action": "admin_review_only",
                    "automatic_relabel": False,
                }
            )
    return findings
