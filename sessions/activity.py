"""Session activity audit adapter shared by legacy device handlers."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any


def record_session_activity(
    kind: str,
    value: Any,
    *,
    lock: Any,
    active_session: Callable[[], dict[str, Any] | None],
    database: Any,
) -> None:
    """Preserve counters and timestamped event semantics outside app.py."""
    session_id = None
    with lock:
        active = active_session()
        if active is not None:
            counters = active["counters"]
            counters[kind] = counters.get(kind, 0) + 1
            if active.get("phase") == "recording":
                session_id = active["record"]["session_id"]
    if session_id:
        database.enqueue(
            "sessions",
            "event",
            {
                "session_id": session_id,
                "timestamp": datetime.now(UTC).isoformat(),
                "type": kind,
                "value": value,
            },
        )
