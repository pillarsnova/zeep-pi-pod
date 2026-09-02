"""Auditable overrides for confirmed ZEEP Sleep State ground truth.

The estimator's original versioned-cadence decisions remain immutable evidence. A
later confirmation (for example, the occupant reports that they were awake)
is stored as a separate ``sleep_stage_annotation`` event and overlaid only in
derived reports.  This keeps the original BCG inference available for model
evaluation while allowing the user-facing Session report to reflect confirmed
facts.

Annotations are ZEEP project ground truth, not retrospective AASM/PSG scores.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from typing import Any, Iterable, Mapping, Optional


ANNOTATION_EVENT_TYPE = "sleep_stage_annotation"
ANNOTATION_VERSION = "zeep-sleep-stage-annotation-v1.0"
VALID_STAGES = frozenset({"wake", "n1", "n2", "n3", "rem"})


def parse_timestamp(value: Any) -> datetime:
    """Return an aware UTC timestamp or raise ``ValueError``."""
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def build_annotation(
    *,
    state: str,
    start_time: str,
    end_time: str,
    source: str,
    reason: str,
    created_at_utc: Optional[str] = None,
    created_by: str = "admin",
) -> dict[str, Any]:
    """Validate and build the persisted annotation payload."""
    stage = str(state or "").strip().lower()
    if stage not in VALID_STAGES:
        raise ValueError(f"invalid Sleep State: {state}")
    start = parse_timestamp(start_time)
    end = parse_timestamp(end_time)
    if end <= start:
        raise ValueError("annotation end_time must be after start_time")
    source_value = str(source or "").strip()
    reason_value = str(reason or "").strip()
    if not source_value or not reason_value:
        raise ValueError("annotation source and reason are required")
    created = parse_timestamp(
        created_at_utc or datetime.now(timezone.utc).isoformat()
    )
    return {
        "version": ANNOTATION_VERSION,
        "status": "active",
        "state": stage,
        "start_time": start.isoformat(),
        "end_time": end.isoformat(),
        "source": source_value,
        "reason": reason_value,
        "created_at_utc": created.isoformat(),
        "created_by": str(created_by or "admin"),
        "ground_truth_scope": "reported_wakefulness_or_observed_state",
        "raw_sleep_stage_events_changed": False,
        "aasm_psg_equivalent": False,
    }


def load_annotations(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Parse valid annotation rows in database order; ignore malformed rows."""
    annotations: list[dict[str, Any]] = []
    for row in rows:
        try:
            raw = row.get("value") if hasattr(row, "get") else row["value"]
            value = json.loads(raw or "{}") if isinstance(raw, str) else dict(raw or {})
            if str(value.get("status") or "active").lower() != "active":
                continue
            if value.get("state") not in VALID_STAGES:
                continue
            value["_start"] = parse_timestamp(value["start_time"])
            value["_end"] = parse_timestamp(value["end_time"])
            if value["_end"] <= value["_start"]:
                continue
            annotations.append(value)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue
    return annotations


def matching_annotation(
    event_timestamp: str,
    annotations: Iterable[dict[str, Any]],
    *,
    sample_interval_s: float = 5.0,
) -> Optional[dict[str, Any]]:
    """Return the newest annotation covering a versioned-cadence decision.

    A persisted Sleep State timestamp is the end of its analysis window.
    Matching by the window midpoint makes a human-entered report interval such
    as 09:06:28–09:06:58 cover the six decisions whose displayed period has
    exactly those boundaries, without also changing the preceding decision.
    """
    midpoint = parse_timestamp(event_timestamp) - timedelta(
        seconds=max(0.0, float(sample_interval_s)) / 2.0
    )
    matched = None
    for annotation in annotations:
        try:
            start = annotation.get("_start") or parse_timestamp(annotation["start_time"])
            end = annotation.get("_end") or parse_timestamp(annotation["end_time"])
        except (KeyError, TypeError, ValueError):
            continue
        if start <= midpoint <= end:
            matched = annotation
    return matched


def apply_annotations(
    value: Mapping[str, Any],
    event_timestamp: str,
    annotations: Iterable[dict[str, Any]],
    *,
    sample_interval_s: float = 5.0,
) -> tuple[dict[str, Any], Optional[dict[str, Any]]]:
    """Overlay confirmed ground truth while retaining the estimator result."""
    original = dict(value)
    annotation = matching_annotation(
        event_timestamp, annotations, sample_interval_s=sample_interval_s
    )
    if annotation is None:
        return original, None
    stage = str(annotation["state"])
    public_annotation = {
        key: item for key, item in annotation.items() if not key.startswith("_")
    }
    updated = dict(original)
    updated.update({
        "state": stage,
        "probabilities": {
            candidate: 1.0 if candidate == stage else 0.0
            for candidate in ("wake", "n1", "n2", "n3", "rem")
        },
        "confidence": "high",
        # Keep provenance in ``stage_annotation`` for Admin/Audit. The normal
        # Session report should explain the observed boundary, not imply that
        # every future Sleep State was manually confirmed by its occupant.
        "reason": str(annotation.get("reason") or "ปรับสถานะจากหลักฐานช่วงจบ Session"),
        "state_changed": original.get("state") != stage,
        "stage_annotation": {
            **public_annotation,
            "original_state": original.get("state"),
            "original_probabilities": original.get("probabilities"),
            "original_confidence": original.get("confidence"),
        },
    })
    return updated, annotation
