"""Semi-Markov transition memory for the contactless Sleep estimator."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping, Set
from typing import Any

from sleep_system_policy import continuity_hold_contract


def transition_allowed(
    candidate: str,
    *,
    previous: str | None,
    cycle_has_n1: bool,
    strong_wake: bool,
    allowed_transitions: Mapping[str, Set[str]],
) -> bool:
    """Apply the guarded transition graph to one evidence candidate."""
    if previous is None:
        return candidate == "wake"
    if candidate == "wake" and strong_wake:
        return True
    if previous == "wake":
        return candidate in {"wake", "n1"}
    if candidate in {"n2", "n3", "rem"} and not cycle_has_n1:
        return False
    return candidate in allowed_transitions.get(
        previous,
        frozenset({"wake"}),
    )


def transition_fallback_state(
    previous: str | None,
    *,
    sleep_states: Set[str],
) -> str:
    """Hold the last confirmed State instead of fabricating a bridge."""
    return previous if previous in sleep_states else "wake"


def stabilize_path_transition(
    path: MutableMapping[str, Any],
    *,
    candidate: str,
    target: str,
    allowed: bool,
    previous: str | None,
    strong_wake: bool,
    now: float,
    policy_version: str,
    stage_confirmation_seconds: Mapping[str, float],
    default_confirmation_seconds: float,
    confirm_epochs: int,
    confirm_ticks: Mapping[str, int],
    minimum_dwell_seconds: Mapping[str, float],
) -> tuple[str, dict[str, Any]]:
    """Resolve repeated evidence while the caller owns the path lock."""
    guard = _base_guard(
        candidate,
        allowed=allowed,
        previous=previous,
        strong_wake=strong_wake,
        policy_version=policy_version,
    )
    if not allowed:
        return _blocked_transition(
            path,
            guard,
            candidate=candidate,
            target=target,
            previous=previous,
            stage_confirmation_seconds=stage_confirmation_seconds,
            default_confirmation_seconds=default_confirmation_seconds,
        )
    if previous is None:
        return _initial_transition(
            path,
            guard,
            target=target,
            stage_confirmation_seconds=stage_confirmation_seconds,
            default_confirmation_seconds=default_confirmation_seconds,
            confirm_epochs=confirm_epochs,
            confirm_ticks=confirm_ticks,
        )
    if target == previous:
        return _same_state_transition(
            path,
            guard,
            previous=previous,
            stage_confirmation_seconds=stage_confirmation_seconds,
            default_confirmation_seconds=default_confirmation_seconds,
            confirm_epochs=confirm_epochs,
        )
    return _challenger_transition(
        path,
        guard,
        target=target,
        previous=previous,
        now=now,
        stage_confirmation_seconds=stage_confirmation_seconds,
        default_confirmation_seconds=default_confirmation_seconds,
        confirm_ticks=confirm_ticks,
        minimum_dwell_seconds=minimum_dwell_seconds,
    )


def _base_guard(
    candidate: str,
    *,
    allowed: bool,
    previous: str | None,
    strong_wake: bool,
    policy_version: str,
) -> dict[str, Any]:
    return {
        "raw_candidate": candidate,
        "bridge_state": None,
        "blocked_candidate": candidate if not allowed else None,
        "transition_allowed": allowed,
        "previous_state": previous,
        "strong_wake_override": strong_wake,
        "policy": policy_version,
    }


def _blocked_transition(
    path: MutableMapping[str, Any],
    guard: dict[str, Any],
    *,
    candidate: str,
    target: str,
    previous: str | None,
    stage_confirmation_seconds: Mapping[str, float],
    default_confirmation_seconds: float,
) -> tuple[str, dict[str, Any]]:
    path["candidate"] = None
    path["candidate_ticks"] = 0
    hold_ticks = int(path.get("continuity_hold_ticks") or 0) + 1
    path["continuity_hold_ticks"] = hold_ticks
    guard.update({
        "required_ticks": 0,
        "candidate_ticks": 0,
        "candidate_epochs": 0,
        "required_epochs": 0,
        "confirmation_seconds": stage_confirmation_seconds.get(
            target,
            default_confirmation_seconds,
        ),
        "confirmation_complete": False,
    })
    guard.update(continuity_hold_contract(
        previous,
        candidate=candidate,
        decision="blocked_transition_hold",
        hold_epochs=hold_ticks,
    ))
    return previous or "wake", guard


def _initial_transition(
    path: MutableMapping[str, Any],
    guard: dict[str, Any],
    *,
    target: str,
    stage_confirmation_seconds: Mapping[str, float],
    default_confirmation_seconds: float,
    confirm_epochs: int,
    confirm_ticks: Mapping[str, int],
) -> tuple[str, dict[str, Any]]:
    """Anchor the first occupied 30-second Epoch at conscious Wake.

    Login and the Session start establish that a person entered ZEEP awake.
    Requiring a second identical Wake decision used to create an artificial
    hole at the start of every Session without adding physiological evidence.
    """
    del stage_confirmation_seconds
    del default_confirmation_seconds
    del confirm_epochs
    del confirm_ticks
    target = "wake"
    path["candidate"] = None
    path["candidate_ticks"] = 0
    path["continuity_hold_ticks"] = 0
    guard.update({
        "required_ticks": 1,
        "candidate_ticks": 1,
        "candidate_epochs": 1,
        "required_epochs": 1,
        "confirmation_seconds": 0.0,
        "confirmation_complete": True,
    })
    guard.update(continuity_hold_contract(
        None,
        candidate=target,
        decision="initial_awake_anchor",
    ))
    return target, guard


def _same_state_transition(
    path: MutableMapping[str, Any],
    guard: dict[str, Any],
    *,
    previous: str,
    stage_confirmation_seconds: Mapping[str, float],
    default_confirmation_seconds: float,
    confirm_epochs: int,
) -> tuple[str, dict[str, Any]]:
    path["candidate"] = None
    path["candidate_ticks"] = 0
    path["continuity_hold_ticks"] = 0
    guard.update({
        "required_ticks": confirm_epochs,
        "candidate_ticks": confirm_epochs,
        "candidate_epochs": confirm_epochs,
        "required_epochs": confirm_epochs,
        "confirmation_seconds": stage_confirmation_seconds.get(
            previous,
            default_confirmation_seconds,
        ),
        "held": False,
        "held_previous_state": False,
        "confirmation_complete": True,
        "confirmed_state": previous,
        "provisional": False,
        "decision": "hold_confirmed",
        "decision_kind": "confirmed_state",
        "score_eligible": True,
        "excluded_from_score": False,
        "excluded_from_personal_baseline": False,
    })
    return previous, guard


def _challenger_transition(
    path: MutableMapping[str, Any],
    guard: dict[str, Any],
    *,
    target: str,
    previous: str,
    now: float,
    stage_confirmation_seconds: Mapping[str, float],
    default_confirmation_seconds: float,
    confirm_ticks: Mapping[str, int],
    minimum_dwell_seconds: Mapping[str, float],
) -> tuple[str, dict[str, Any]]:
    stage_since = path.get("stage_since")
    dwell_s = (
        max(0.0, now - stage_since)
        if isinstance(stage_since, (int, float))
        else 0.0
    )
    minimum_dwell_s = minimum_dwell_seconds.get(previous, 0.0)
    if path.get("candidate") == target:
        path["candidate_ticks"] += 1
    else:
        path["candidate"] = target
        path["candidate_ticks"] = 1
    ticks = int(path["candidate_ticks"])
    required = int(confirm_ticks.get(target, 2))
    held = dwell_s < minimum_dwell_s or ticks < required
    hold_ticks = _update_hold_ticks(path, held)
    guard.update({
        "required_ticks": required,
        "candidate_ticks": ticks,
        "candidate_epochs": ticks,
        "required_epochs": required,
        "confirmation_seconds": stage_confirmation_seconds.get(
            target,
            default_confirmation_seconds,
        ),
        "dwell_s": round(dwell_s, 1),
        "minimum_dwell_s": minimum_dwell_s,
        "held": held,
        "confirmation_complete": not held,
        "confirmed_state": previous if held else target,
    })
    if held:
        guard.update(continuity_hold_contract(
            previous,
            candidate=target,
            decision="confirming",
            hold_epochs=hold_ticks,
        ))
        return previous, guard
    guard.update({
        "held_previous_state": False,
        "provisional": False,
        "decision": "confirmed",
        "decision_kind": "confirmed_state",
        "score_attribution_state": target,
        "challenger_counted_as_new_state": True,
        "score_eligible": True,
        "excluded_from_score": False,
        "excluded_from_personal_baseline": False,
    })
    return target, guard


def _update_hold_ticks(
    path: MutableMapping[str, Any],
    held: bool,
) -> int:
    hold_ticks = int(path.get("continuity_hold_ticks") or 0) + 1 if held else 0
    path["continuity_hold_ticks"] = hold_ticks
    return hold_ticks
