"""Fail-closed authorization policy for adaptive recommendations."""

from __future__ import annotations

from typing import Any

ADAPTIVE_CONTROL_POLICY_VERSION = "zeep.adaptive-control-policy.v1"


def advisory_control_policy() -> dict[str, Any]:
    """Return the immutable v1 boundary exposed to Admin clients."""
    return {
        "version": ADAPTIVE_CONTROL_POLICY_VERSION,
        "automatic_actuation": False,
        "recommendation_only": True,
        "sleep_state_as_actuator_input": False,
        "command_endpoint": None,
        "safety_supervisor_authoritative": True,
        "decision_required": True,
        "allowed_decision_roles": ["user", "admin"],
    }


def enforce_advisory(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove accidental execution authority from generated output."""
    guarded = []
    for item in items:
        candidate = dict(item)
        candidate["executable"] = False
        candidate["requires_user_confirmation"] = True
        candidate["authorization_policy"] = ADAPTIVE_CONTROL_POLICY_VERSION
        candidate.pop("command", None)
        candidate.pop("command_endpoint", None)
        guarded.append(candidate)
    return guarded

