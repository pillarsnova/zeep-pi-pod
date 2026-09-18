"""Explicit inputs and runtime ports for Login-to-waiting Session creation."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol


class StartOwner(Protocol):
    """Only the authenticated ownership fields needed by Session creation."""

    account_key: str
    email: str | None
    subject: str
    session_id: str


class SessionStartRejected(Exception):
    """Domain rejection translated into the existing HTTP contract by app.py."""

    def __init__(self, status_code: int, detail: str | dict[str, Any]) -> None:
        super().__init__(str(detail))
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class StartRequest:
    """Caller intent; tokens remain outside the persisted/public Session record."""

    username: str
    gender: str | None
    age: int | None
    age_group: str | None
    owner: StartOwner
    auth: dict[str, Any] | None = None
    health_reference: dict[str, Any] | None = None
    rest_mode: str = "nap_recovery"
    target_duration_minutes: int | None = None


@dataclass(frozen=True)
class ValidatedStart:
    """Normalized input using existing mode, identity and demographic rules."""

    username: str
    key: str
    email: str | None
    gender: str | None
    age: int | None
    age_group: str | None
    incoming_health: dict[str, Any]
    rest_mode: str
    target_duration_s: int | float | None


@dataclass(frozen=True)
class StartPolicy:
    """Existing deployment constants, not new Login or safety policy."""

    pod_id: str
    sample_interval_s: float
    bed_start_seconds: float
    age_groups: Mapping[str, Any]
    default_ages: Mapping[str, int]
    genders: tuple[str, ...]


@dataclass(frozen=True)
class StartPorts:
    """Per-call state, identity, persistence and projection dependencies."""

    session_lock: Any
    state_lock: Any
    profile_lock: Any
    state: dict[str, Any]
    get_active: Callable[[], dict[str, Any] | None]
    set_active: Callable[[dict[str, Any] | None], None]
    normalize_username: Callable[[str], str]
    normalize_email: Callable[[str], str]
    normalize_mode: Callable[[str], str]
    resolve_target: Callable[..., dict[str, Any]]
    age_group: Callable[[Any], Any]
    date_of_birth: Callable[[Any], Any]
    body_measurement: Callable[..., Any]
    blood_group: Callable[[Any], Any]
    health_reference: Callable[[dict[str, Any]], dict[str, Any]]
    wellness_context: Callable[[dict[str, Any]], Any]
    load_profiles: Callable[[], dict[str, Any]]
    save_profiles: Callable[[dict[str, Any]], None]
    rest_baseline: Callable[..., Any]
    acquire_lease: Callable[..., Any]
    release_lease: Callable[[Any], None]
    occupancy_mode: Callable[[], str]
    current_safety: Callable[[], dict[str, Any]]
    save_checkpoint: Callable[[dict[str, Any]], Any]
    reset_inference: Callable[[str], None]
    vital_gate: Callable[[dict[str, Any]], dict[str, Any]]
    replace_projection: Callable[[dict[str, Any]], None]
    snapshot: Callable[[], dict[str, Any]]
    log_event: Callable[..., None]
    clock: Callable[[], float]
    monotonic: Callable[[], float]
    utc_now: Callable[[], datetime]
    session_suffix: Callable[[], str]
