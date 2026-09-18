"""Runtime contracts for closing a live Session without changing its policy."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class FinalizationPolicy:
    """Values supplied from the existing deployment and Sleep policy owners."""

    pod_id: str
    sample_interval_s: float
    evidence_interval_s: float
    heart_rate_range: tuple[float, float]
    respiration_rate_range: tuple[float, float]
    required_packets: int
    timeline_schema_version: int
    bed_start_seconds: float
    baseline_start_utc: str
    estimator_version: str
    evidence_version: str
    baseline_version: str
    transition_policy: str
    g2_ontology: str
    terminal_wake_policy: str


@dataclass(frozen=True)
class SessionFinalizationPorts:
    """State, persistence, report and account boundaries; no import-time I/O."""

    session_lock: Any
    state_lock: Any
    profile_lock: Any
    get_active: Callable[[], dict[str, Any] | None]
    set_active: Callable[[dict[str, Any] | None], None]
    reserve_share: Callable[..., None]
    discard_share: Callable[..., None]
    fulfil_share: Callable[..., None]
    flush: Callable[[float], bool]
    writer_health: Callable[[], dict[str, Any]]
    flush_failure: Callable[[str], Exception]
    read_sessions: Callable[..., list[dict[str, Any]]]
    clear_checkpoint: Callable[[], None]
    recover_active: Callable[[dict[str, Any]], None]
    commit: Callable[..., None]
    project_samples: Callable[..., dict[str, Any]]
    series_stats: Callable[..., Any]
    end_bcg: Callable[[str], None]
    vital_gate: Callable[[dict[str, Any]], dict[str, Any]]
    build_quality: Callable[..., dict[str, Any]]
    build_report: Callable[..., dict[str, Any]]
    baseline_context: Callable[..., dict[str, Any]]
    update_baseline: Callable[..., dict[str, Any]]
    availability: Callable[..., dict[str, Any]]
    load_profiles: Callable[[], dict[str, Any]]
    save_profiles: Callable[[dict[str, Any]], None]
    release_lease: Callable[..., Any]
    logout_account: Callable[[dict[str, Any]], None]
    enqueue_ingest: Callable[..., None]
    replace_projection: Callable[[dict[str, Any]], None]
    reset_inference: Callable[..., None]
    log_event: Callable[..., None]
    clock: Callable[[], float]
    monotonic: Callable[[], float]
    utc_now: Callable[[], datetime]
