"""Restart-safe Session lifecycle primitives.

The composition root owns hardware, databases and logging.  This module owns
only deterministic lifecycle rules and durable checkpoint I/O, which keeps it
usable in tests without importing or starting the FastAPI application.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Callable, Collection, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SESSION_CHECKPOINT_VERSION = 1
CHECKPOINT_RECORD_FIELDS = frozenset(
    {
        "session_id",
        "username",
        "username_key",
        "display_name",
        "gender",
        "age",
        "age_group",
        "health_reference",
        "wellness_context",
        "rest_mode",
        "auth_source",
        "zeep_public_id",
        "identity_subject",
        "pod_id",
        "armed_at_utc",
        "started_at_utc",
        "sample_interval_s",
        "sample_cadence_segments",
    }
)
RESTART_SAFE_PHASES = frozenset({"waiting_bed", "recording"})
REQUIRED_IDENTITY_FIELDS = frozenset(
    {"session_id", "username", "username_key", "identity_subject", "pod_id"}
)

InvalidCheckpointHandler = Callable[[Exception], None]


class SessionCheckpointStore:
    """Persist the minimum non-secret state needed after a service restart."""

    def __init__(
        self,
        path: Path,
        bed_start_seconds: float,
        on_invalid: InvalidCheckpointHandler | None = None,
    ) -> None:
        self.path = path
        self.bed_start_seconds = bed_start_seconds
        self.on_invalid = on_invalid
        self.lock = threading.Lock()

    def build_payload(self, active: Mapping[str, Any]) -> dict[str, Any]:
        """Build a restart checkpoint without persisting credentials."""
        record = dict(active.get("record") or {})
        safe_record = {
            key: record.get(key) for key in CHECKPOINT_RECORD_FIELDS if key in record
        }
        phase = active.get("phase")
        if phase not in RESTART_SAFE_PHASES:
            raise ValueError("active session phase is not restart-safe")
        elapsed = self._waiting_bed_elapsed(active, phase)
        return {
            "schema_version": SESSION_CHECKPOINT_VERSION,
            "saved_at_utc": datetime.now(UTC).isoformat(),
            "phase": phase,
            "owner_auth_session_id": active.get("owner_auth_session_id"),
            "onbed_elapsed_s": round(min(elapsed, self.bed_start_seconds), 3),
            "record": safe_record,
        }

    def save(self, active: Mapping[str, Any]) -> dict[str, Any]:
        """Atomically persist the active Login/Session link."""
        payload = self.build_payload(active)
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".json.tmp")
            with temporary.open("w", encoding="utf-8") as handle:
                json.dump(
                    payload,
                    handle,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        return payload

    def load(self) -> dict[str, Any] | None:
        """Load and validate a checkpoint; invalid data is never restored."""
        try:
            with self.lock, self.path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            self._validate(payload)
            return payload
        except FileNotFoundError:
            return None
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            if self.on_invalid is not None:
                self.on_invalid(exc)
            return None

    def clear(self) -> None:
        """Remove a checkpoint after an explicit Session completion."""
        with self.lock:
            self.path.unlink(missing_ok=True)

    @staticmethod
    def _waiting_bed_elapsed(active: Mapping[str, Any], phase: Any) -> float:
        onbed_since = active.get("onbed_since")
        if phase != "waiting_bed" or not isinstance(onbed_since, (int, float)):
            return 0.0
        return max(0.0, time.monotonic() - float(onbed_since))

    @staticmethod
    def _validate(payload: Any) -> None:
        if not isinstance(payload, dict):
            raise ValueError("checkpoint is not an object")
        if payload.get("schema_version") != SESSION_CHECKPOINT_VERSION:
            raise ValueError("unsupported checkpoint version")
        if payload.get("phase") not in RESTART_SAFE_PHASES:
            raise ValueError("invalid checkpoint phase")
        record = payload.get("record")
        if not isinstance(record, dict):
            raise ValueError("checkpoint record is missing")
        if any(not record.get(key) for key in REQUIRED_IDENTITY_FIELDS):
            raise ValueError("checkpoint identity is incomplete")


def bed_is_occupied(
    bcg: Mapping[str, Any],
    *,
    now_epoch_s: float,
    stale_seconds: float,
    on_bed_codes: Collection[Any],
) -> bool:
    """Return whether a fresh BCG packet reports an occupied bed."""
    last_update = bcg.get("last_update")
    return bool(
        bcg.get("connected")
        and isinstance(last_update, (int, float))
        and now_epoch_s - last_update <= stale_seconds
        and bcg.get("status_code") in on_bed_codes
    )


def service_resume_event(
    session_id: str,
    timestamp: str,
) -> dict[str, Any]:
    """Build the audit event for a recording restored after restart."""
    return {
        "session_id": session_id,
        "timestamp": timestamp,
        "type": "service_resume",
        "value": {
            "reason": "server_restart",
            "continuity": "hold_last_confirmed_state_for_display_only",
            "excluded_from_score": True,
        },
    }


def evaluate_vital_start_gate(
    bcg: Mapping[str, Any],
    active: Mapping[str, Any] | None,
    *,
    now_epoch_s: float,
    stale_seconds: float,
    on_bed_codes: Collection[Any],
    required_packets: int,
) -> dict[str, Any]:
    """Evaluate the fresh Bed + HR + RR gate for Session recording."""
    last_update = bcg.get("last_update")
    fresh = bool(
        bcg.get("connected")
        and isinstance(last_update, (int, float))
        and now_epoch_s - last_update <= stale_seconds
    )
    on_bed = bool(fresh and bcg.get("status_code") in on_bed_codes)
    hr_valid = bool(
        on_bed
        and bcg.get("heart_rate_current_valid")
        and not bcg.get("heart_rate_held")
    )
    rr_valid = bool(
        on_bed
        and bcg.get("respiration_current_valid")
        and not bcg.get("respiration_held")
    )
    packet_count = int(bcg.get("packets") or 0)
    start_packet_count = _start_packet_count(active, packet_count)
    packets_since_start = max(0, packet_count - start_packet_count)
    confirmed_packets = (
        min(packets_since_start, int(bcg.get("vital_valid_streak") or 0))
        if hr_valid and rr_valid
        else 0
    )
    ready = bool(
        on_bed and hr_valid and rr_valid and confirmed_packets >= required_packets
    )
    return {
        "ready": ready,
        "heart_rate_valid": hr_valid,
        "respiration_rate_valid": rr_valid,
        "confirmed_packets": confirmed_packets,
        "required_packets": required_packets,
        "packets_since_login": packets_since_start,
        "bcg_fresh": fresh,
        "on_bed": on_bed,
        "reason": _vital_gate_reason(fresh, on_bed, hr_valid, rr_valid, ready),
    }


def _start_packet_count(
    active: Mapping[str, Any] | None,
    packet_count: int,
) -> int:
    raw_count = (active or {}).get("vital_gate_start_packet_count")
    if isinstance(raw_count, (int, float)):
        return int(raw_count)
    return packet_count


def _vital_gate_reason(
    fresh: bool,
    on_bed: bool,
    hr_valid: bool,
    rr_valid: bool,
    ready: bool,
) -> str:
    if not fresh:
        return "waiting_for_bcg"
    if not on_bed:
        return "waiting_for_bed"
    if not hr_valid and not rr_valid:
        return "waiting_for_hr_rr"
    if not hr_valid:
        return "waiting_for_hr"
    if not rr_valid:
        return "waiting_for_rr"
    if not ready:
        return "confirming_hr_rr"
    return "ready"
