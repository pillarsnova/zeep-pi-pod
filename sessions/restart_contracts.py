"""Explicit runtime dependencies for resuming an existing Pod Session."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class RestartPolicy:
    """Existing deployment settings, not a separate set of restart thresholds."""

    pod_id: str
    sample_interval_s: float
    sample_limit: int
    required_packets: int
    heart_rate_range: tuple[float, float]
    respiration_rate_range: tuple[float, float]
    evidence_interval_s: float
    baseline_start_utc: str


@dataclass(frozen=True)
class RestartPorts:
    """I/O and shared-state ownership supplied per call by the composition root."""

    session_lock: Any
    state_lock: Any
    profile_lock: Any
    sleep_path_lock: Any
    state: dict[str, Any]
    sleep_path: dict[str, Any]
    get_active: Callable[[], dict[str, Any] | None]
    set_active: Callable[[dict[str, Any]], None]
    load_checkpoint: Callable[[], dict[str, Any] | None]
    clear_checkpoint: Callable[[], None]
    save_checkpoint: Callable[[dict[str, Any]], Any]
    restore_safety: Callable[[dict[str, Any]], dict[str, Any]]
    current_safety: Callable[[], dict[str, Any]]
    read_sessions: Callable[..., list[dict[str, Any]]]
    enqueue: Callable[..., None]
    flush: Callable[[float], bool]
    load_profiles: Callable[[], dict[str, Any]]
    save_profiles: Callable[[dict[str, Any]], None]
    age_group: Callable[[Any], Any]
    health_reference: Callable[[dict[str, Any]], dict[str, Any]]
    resolve_target: Callable[..., dict[str, Any]]
    rest_baseline: Callable[..., Any]
    acquire_lease: Callable[..., Any]
    availability: Callable[..., dict[str, Any]]
    reset_inference: Callable[..., None]
    reset_sleep_path: Callable[[str], None]
    restore_sleep_context: Callable[..., dict[str, Any]]
    start_bcg: Callable[[str], None]
    vital_gate: Callable[[dict[str, Any]], dict[str, Any]]
    replace_projection: Callable[[dict[str, Any]], None]
    log_event: Callable[..., None]
    clock: Callable[[], float]
    monotonic: Callable[[], float]
    utc_now: Callable[[], datetime]
