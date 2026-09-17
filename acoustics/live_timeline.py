"""Thread-safe adapter from the active Session to the acoustic projection."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from .level_events import DEFAULT_CADENCE_SECONDS
from .timeline_projection import (
    DEFAULT_DISPLAY_RANGE,
    build_acoustic_timeline_snapshot,
)

ActiveSessionReader = Callable[[], Mapping[str, Any] | None]
TimelineReader = Callable[[], dict[str, Any]]


def live_timeline_reader(
    lock: Any,
    active_session: ActiveSessionReader,
    *,
    display_range: tuple[float, float] = DEFAULT_DISPLAY_RANGE,
    cadence_s: float = DEFAULT_CADENCE_SECONDS,
) -> TimelineReader:
    """Create a detached live reader without coupling acoustics to ``app``."""

    def snapshot() -> dict[str, Any]:
        with lock:
            active = active_session()
            samples = [
                {
                    "t": item.get("t"),
                    "dba": item.get("dba"),
                    "sample_interval_s": item.get("sample_interval_s"),
                    "acoustic_label": item.get("acoustic_label"),
                    "acoustic_state": item.get("acoustic_state"),
                    "acoustic_confidence": item.get("acoustic_confidence"),
                    "acoustic_event_detected": item.get("acoustic_event_detected"),
                    "acoustic_classifier_version": item.get(
                        "acoustic_classifier_version"
                    ),
                    "acoustic_window_sequence": item.get(
                        "acoustic_window_sequence"
                    ),
                }
                for item in ((active or {}).get("samples") or [])
            ]
            record = dict((active or {}).get("record") or {})
            phase = str((active or {}).get("phase") or "idle")
            session_active = active is not None

        return build_acoustic_timeline_snapshot(
            samples,
            session_id=_session_id(record),
            session_active=session_active,
            recording=phase == "recording",
            started_at_epoch_s=_started_at_epoch(record),
            display_range=display_range,
            cadence_s=cadence_s,
        )

    return snapshot


def _session_id(record: Mapping[str, Any]) -> str | None:
    value = record.get("session_id")
    return str(value) if value else None


def _started_at_epoch(record: Mapping[str, Any]) -> float | None:
    value = record.get("started_at_utc")
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)).timestamp()
    except (TypeError, ValueError):
        return None
