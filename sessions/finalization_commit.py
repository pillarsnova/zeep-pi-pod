"""Atomic persistence boundary for a completed live Session.

Report projection and scoring stay with their existing owners.  This module
only commits an already-built final summary and controls when restart recovery
may be removed.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, MutableMapping
from dataclasses import dataclass
from typing import Any

FinalizePayload = dict[str, Any]
Enqueue = Callable[[str, str, FinalizePayload], None]
Flush = Callable[[float], bool]
FlushFailure = Callable[[str], Exception]
RecoverActive = Callable[[MutableMapping[str, Any]], None]
ClearCheckpoint = Callable[[], None]


@dataclass(frozen=True)
class FinalizationPorts:
    """Injected persistence and recovery boundaries for one finalization."""

    enqueue: Enqueue
    flush: Flush
    flush_failure: FlushFailure
    recover_active: RecoverActive
    clear_checkpoint: ClearCheckpoint


def build_session_finalize_payload(
    record: Mapping[str, Any],
    final_summary: Mapping[str, Any],
    terminal_wake: Mapping[str, Any] | None,
) -> FinalizePayload:
    """Build the existing SQLite finalization command without reshaping results."""
    terminal_event = None
    if terminal_wake is not None:
        terminal_event = {
            "timestamp": terminal_wake["start_time"],
            "value": terminal_wake,
        }
    return {
        "session_id": record["session_id"],
        "end_time": record["ended_at_utc"],
        "duration": record["duration_s"],
        "note": record.get("note"),
        "end_reason": record["end_reason"],
        "terminal_wake": terminal_event,
        "final_summary": final_summary,
    }


def commit_live_session_finalization(
    active: MutableMapping[str, Any],
    final_summary: dict[str, Any],
    terminal_wake: dict[str, Any] | None,
    *,
    ports: FinalizationPorts,
    flush_timeout_s: float = 30,
) -> None:
    """Commit the close before removing its retry origin and checkpoint.

    Persistence failures restore the live Session through the injected
    composition-root callback.  Once the database flush succeeds, its row is
    authoritative even if checkpoint removal subsequently fails.
    """
    record = active["record"]
    # Keep payload validation outside the recovery block, matching the legacy
    # behavior for malformed trusted inputs such as terminal_wake.
    payload = build_session_finalize_payload(record, final_summary, terminal_wake)
    try:
        ports.enqueue("sessions", "session_finalize", payload)
        if not ports.flush(flush_timeout_s):
            raise ports.flush_failure("before Session finalization")
    except Exception:
        ports.recover_active(active)
        raise

    record.pop("started_monotonic", None)
    ports.clear_checkpoint()
