"""Pure contracts and builders for the live Session projection.

The composition root owns locks and publication.  This module owns the
complete projection shape so Login, restart recovery and finalization cannot
silently drift apart.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, NotRequired, TypedDict, cast

from identity.baseline_context import project_health_reference

__all__ = (
    "LiveSessionProjection",
    "SessionPublicIdentity",
    "VitalGateProjection",
    "active_session_projection",
    "inactive_session_projection",
    "recording_vital_gate",
)

_VITAL_GATE_REQUIRED_FIELDS = (
    "ready",
    "heart_rate_valid",
    "respiration_rate_valid",
    "confirmed_packets",
    "required_packets",
    "reason",
)
_VITAL_GATE_OPTIONAL_FIELDS = (
    "packets_since_login",
    "bcg_fresh",
    "on_bed",
)


class VitalGateProjection(TypedDict):
    """Public vital-start gate, including optional live diagnostics."""

    ready: bool
    heart_rate_valid: bool | None
    respiration_rate_valid: bool | None
    confirmed_packets: int
    required_packets: int
    reason: str
    packets_since_login: NotRequired[int]
    bcg_fresh: NotRequired[bool]
    on_bed: NotRequired[bool]


class LiveSessionProjection(TypedDict):
    """Complete Session state published to snapshots and WebSocket clients."""

    active: bool
    username: str | None
    account_key: str | None
    email: str | None
    display_name: str | None
    auth_source: str | None
    gender: str | None
    age: int | None
    age_group: str | None
    health_reference: dict[str, Any] | None
    wellness_context_available: bool
    rest_mode: str | None
    target_duration_s: float | None
    personal_rest_baseline: dict[str, Any] | None
    session_id: str | None
    started_at: float | None
    samples: int
    recording: bool
    bed_wait_s: int | float
    vital_gate: VitalGateProjection


@dataclass(frozen=True)
class SessionPublicIdentity:
    """Allowlisted identity and wellness-reference context for live state."""

    username: str
    account_key: str
    email: str | None
    display_name: str | None
    auth_source: str
    gender: str | None
    age: int | None
    age_group: str | None
    health_reference: Mapping[str, Any] | None


def inactive_session_projection(
    *,
    required_packets: int,
    reason: str,
) -> LiveSessionProjection:
    """Return a complete idle projection with no previous occupant data."""
    return {
        "active": False,
        "username": None,
        "account_key": None,
        "email": None,
        "display_name": None,
        "auth_source": None,
        "gender": None,
        "age": None,
        "age_group": None,
        "health_reference": None,
        "wellness_context_available": False,
        "rest_mode": None,
        "target_duration_s": None,
        "personal_rest_baseline": None,
        "session_id": None,
        "started_at": None,
        "samples": 0,
        "recording": False,
        "bed_wait_s": 0,
        "vital_gate": {
            "ready": False,
            "heart_rate_valid": False,
            "respiration_rate_valid": False,
            "confirmed_packets": 0,
            "required_packets": required_packets,
            "reason": reason,
        },
    }


def active_session_projection(
    identity: SessionPublicIdentity,
    *,
    session_id: str,
    rest_mode: str,
    target_duration_s: float | None,
    started_at: float,
    samples: int,
    recording: bool,
    vital_gate: Mapping[str, Any],
    bed_wait_s: int | float = 0,
    wellness_context_available: bool = False,
    personal_rest_baseline: Mapping[str, Any] | None = None,
) -> LiveSessionProjection:
    """Build a detached, complete projection for an active Session."""
    return {
        "active": True,
        "username": identity.username,
        "account_key": identity.account_key,
        "email": identity.email,
        "display_name": identity.display_name,
        "auth_source": identity.auth_source,
        "gender": identity.gender,
        "age": identity.age,
        "age_group": identity.age_group,
        "health_reference": project_health_reference(identity.health_reference),
        "wellness_context_available": wellness_context_available,
        "rest_mode": rest_mode,
        "target_duration_s": target_duration_s,
        "personal_rest_baseline": _copy_optional_mapping(personal_rest_baseline),
        "session_id": session_id,
        "started_at": started_at,
        "samples": samples,
        "recording": recording,
        "bed_wait_s": bed_wait_s,
        "vital_gate": _project_vital_gate(vital_gate),
    }


def recording_vital_gate(
    vital_gate: Mapping[str, Any],
    *,
    reason: str = "recording",
) -> VitalGateProjection:
    """Keep gate diagnostics while publishing the durable recording phase."""
    return _project_vital_gate({**vital_gate, "ready": True, "reason": reason})


def _project_vital_gate(
    vital_gate: Mapping[str, Any],
) -> VitalGateProjection:
    projected = {key: vital_gate.get(key) for key in _VITAL_GATE_REQUIRED_FIELDS}
    projected.update(
        {
            key: vital_gate[key]
            for key in _VITAL_GATE_OPTIONAL_FIELDS
            if key in vital_gate
        }
    )
    return cast(VitalGateProjection, projected)


def _copy_optional_mapping(
    value: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    return deepcopy(dict(value)) if value is not None else None
