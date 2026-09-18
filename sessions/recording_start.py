"""Durable transition from a waiting occupant to Session recording."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sessions.cadence import sample_interval_seconds
from sessions.live_projection import recording_vital_gate


@dataclass(frozen=True)
class RecordingStartPorts:
    """State ownership and I/O supplied by the composition root."""

    session_lock: Any
    state_lock: Any
    get_active: Callable[[], dict[str, Any] | None]
    vital_gate: Callable[[dict[str, Any]], dict[str, Any]]
    enqueue: Callable[..., None]
    flush: Callable[[float], bool]
    reset_inference: Callable[..., None]
    start_bcg: Callable[[str], None]
    patch_projection: Callable[[dict[str, Any]], None]
    save_checkpoint: Callable[[dict[str, Any]], Any]
    log_event: Callable[..., None]
    clock: Callable[[], float] = time.time
    monotonic: Callable[[], float] = time.monotonic
    utc_now: Callable[[], datetime] = lambda: datetime.now(UTC)


def begin_recording(
    active: dict[str, Any],
    *,
    ports: RecordingStartPorts,
    default_interval_s: float,
    bed_start_seconds: float,
    required_packets: int,
) -> None:
    """Recheck vitals, flush the DB row, then announce and checkpoint recording."""
    record = active["record"]
    gate = ports.vital_gate(active)
    if not gate["ready"]:
        raise RuntimeError(f"cannot start Session before HR/RR gate: {gate['reason']}")
    now_iso = ports.utc_now().isoformat()
    with ports.session_lock:
        active["last_sample"] = float("-inf")
        record["started_at_utc"] = now_iso
        record["started_monotonic"] = ports.monotonic()
        record["sample_cadence_segments"] = [
            {
                "start_at_utc": now_iso,
                "sample_interval_s": sample_interval_seconds(
                    record.get("sample_interval_s"), default_interval_s
                ),
            }
        ]
    ports.enqueue("sessions", "session_start", _start_payload(record, now_iso))
    if not ports.flush(30):
        raise RuntimeError("database writer did not flush Session start")
    ports.reset_inference(record["session_id"], recording=True)
    ports.start_bcg(record["session_id"])
    with ports.state_lock, ports.session_lock:
        if ports.get_active() is not active:
            raise RuntimeError("active Session changed during start")
        active["phase"] = "recording"
        ports.patch_projection(
            {
                "recording": True,
                "started_at": ports.clock(),
                "bed_wait_s": 0,
                "vital_gate": recording_vital_gate(gate),
            }
        )
    ports.save_checkpoint(active)
    ports.log_event(
        "session",
        "bed_confirmed_start",
        session_id=record["session_id"],
        user=record["username"],
        required_s=bed_start_seconds,
        vital_packets=required_packets,
    )


def _start_payload(record: dict[str, Any], now_iso: str) -> dict[str, Any]:
    return {
        "session_id": record["session_id"],
        "user": record["username"],
        "username_key": record["username_key"],
        "gender": record["gender"],
        "identity_subject": record.get("identity_subject"),
        "pod_id": record.get("pod_id"),
        "zeep_public_id": record.get("zeep_public_id"),
        "rest_mode": record.get("rest_mode"),
        "target_duration_s": record.get("target_duration_s"),
        "start_time": now_iso,
        "created_at": record["armed_at_utc"],
    }
