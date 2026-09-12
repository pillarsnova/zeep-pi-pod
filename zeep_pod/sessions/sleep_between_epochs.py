"""Resolve Dashboard Sleep output between canonical evidence epochs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sleep_system_policy import continuity_hold_contract


@dataclass(frozen=True)
class BetweenEpochIssue:
    """Reason why the current frame cannot extend physiological evidence."""

    reason: str
    data_status: str
    display_state: str = "no_data"


def current_frame_issue(
    *,
    session_active: bool,
    session_recording: bool,
    exit_confirmed: bool,
    current_vitals_valid: bool,
) -> BetweenEpochIssue | None:
    """Classify operational state before resolving display continuity."""
    if not session_active:
        return BetweenEpochIssue(
            "ไม่มีผู้ใช้งาน Session · ไม่ประเมิน Sleep State",
            "no_session",
            "off_bed",
        )
    if not session_recording:
        return BetweenEpochIssue(
            "รอเริ่มบันทึก Session ก่อนสะสม Evidence epoch",
            "waiting_for_vitals",
        )
    if exit_confirmed:
        return BetweenEpochIssue(
            "Bed Status ยืนยันว่าไม่มีผู้ใช้งานบนเตียง · "
            "ไม่ประเมิน Sleep State",
            "empty_bed",
            "off_bed",
        )
    if not current_vitals_valid:
        return BetweenEpochIssue(
            "รอบ Sensor ปัจจุบันไม่มี HR/RR สด · "
            "ยกเลิก Evidence ที่กำลังรอยืนยัน",
            "invalid_or_missing_current_vitals",
        )
    return None


def between_evidence_epoch_value(
    *,
    issue: BetweenEpochIssue | None,
    restart_hold: dict[str, Any] | None,
    cached: dict[str, Any] | None,
    previous_stage: str | None,
    continuity_hold_epochs: int,
    sleep_states: tuple[str, ...],
    estimator_version: str,
    evidence_version: str,
) -> dict[str, Any]:
    """Return one display result while no new evidence epoch is due."""
    if issue and restart_hold and _restart_can_bridge(issue):
        value = _restart_rebuild_value(restart_hold)
        value["current_data_status"] = issue.data_status
        value["current_data_reason"] = issue.reason
        return value
    if issue:
        if _issue_ends_occupied_continuity(issue):
            return _inactive_value(cached, issue, sleep_states)
        return _continuity_value(
            previous_stage=_last_known_stage(
                cached,
                previous_stage,
                sleep_states,
            ),
            hold_epochs=max(1, continuity_hold_epochs + 1),
            sleep_states=sleep_states,
            estimator_version=estimator_version,
            evidence_version=evidence_version,
            current_data_status=issue.data_status,
            current_data_reason=issue.reason,
        )
    if restart_hold:
        return _restart_rebuild_value(restart_hold)
    if _needs_continuity_hold(cached, previous_stage, sleep_states):
        return _continuity_value(
            previous_stage=str(previous_stage),
            hold_epochs=max(1, continuity_hold_epochs + 1),
            sleep_states=sleep_states,
            estimator_version=estimator_version,
            evidence_version=evidence_version,
        )
    if cached is not None:
        return _cached_value(cached)
    return _continuity_value(
        previous_stage=None,
        hold_epochs=1,
        sleep_states=sleep_states,
        estimator_version=estimator_version,
        evidence_version=evidence_version,
    )


def sensor_frame_wait_value(
    *,
    recording: bool,
    sleep_states: tuple[str, ...],
    estimator_version: str,
    evidence_version: str,
) -> dict[str, Any]:
    """Return W during Recording, otherwise the pre-recording wait state."""
    if recording:
        return _continuity_value(
            previous_stage=None,
            hold_epochs=1,
            sleep_states=sleep_states,
            estimator_version=estimator_version,
            evidence_version=evidence_version,
        )
    return {
        "state": "no_data",
        "confirmed_state": None,
        "version": estimator_version,
        "evidence_version": evidence_version,
        "classification_active": False,
        "evidence_active": False,
        "probabilities": {state: 0.0 for state in sleep_states},
        "confidence": "low",
        "data_status": "waiting_for_sensor_frame",
        "reason": "รอ Sensor frame 10 วินาที",
        "score_eligible": False,
        "excluded_from_score": True,
        "excluded_from_personal_baseline": True,
    }


def _restart_can_bridge(issue: BetweenEpochIssue) -> bool:
    return issue.data_status == "invalid_or_missing_current_vitals"


def _issue_ends_occupied_continuity(issue: BetweenEpochIssue) -> bool:
    """Keep only explicit lifecycle/occupancy boundaries outside five-state."""
    return issue.data_status in {
        "no_session",
        "waiting_for_vitals",
        "empty_bed",
    }


def _last_known_stage(
    cached: dict[str, Any] | None,
    previous_stage: str | None,
    sleep_states: tuple[str, ...],
) -> str | None:
    """Prefer the durable path, then a valid cached State, else initial W."""
    if previous_stage in sleep_states:
        return previous_stage
    if isinstance(cached, dict):
        cached_stage = cached.get("confirmed_state") or cached.get("state")
        if cached_stage in sleep_states:
            return str(cached_stage)
    return None


def _inactive_value(
    cached: dict[str, Any] | None,
    issue: BetweenEpochIssue,
    sleep_states: tuple[str, ...],
) -> dict[str, Any]:
    """Expose an operational status without inventing a Sleep Stage."""
    value = dict(cached or {})
    value.update({
        "state": issue.display_state,
        "confirmed_state": None,
        "classification_active": False,
        "evidence_active": False,
        "probabilities": {key: 0.0 for key in sleep_states},
        "evidence_probabilities": {key: 0.0 for key in sleep_states},
        "confidence": "low",
        "provisional": True,
        "score_eligible": False,
        "excluded_from_score": True,
        "excluded_from_personal_baseline": True,
        "data_status": issue.data_status,
        "reason": issue.reason,
    })
    return value

def _restart_rebuild_value(restart_hold: dict[str, Any]) -> dict[str, Any]:
    """Keep the durable pre-restart State scoreable during reconnect."""
    value = dict(restart_hold)
    stage = value.get("confirmed_state") or value.get("state")
    confirmation = continuity_hold_contract(
        stage,
        decision="restart_continuity_hold",
    )
    value.update({
        "state": confirmation["confirmed_state"],
        "confirmed_state": confirmation["confirmed_state"],
        "classification_active": True,
        "provisional": False,
        "held_previous_state": bool(
            confirmation["held_previous_state"]
        ),
        "score_attribution_state": confirmation[
            "score_attribution_state"
        ],
        "score_eligible": True,
        "excluded_from_score": False,
        "excluded_from_personal_baseline": True,
        "confirmation": confirmation,
    })
    value["data_status"] = "restored_confirmed_state"
    value["current_data_status"] = "rebuilding_confirmation_window"
    value["current_data_reason"] = (
        "กำลังสร้างหน้าต่าง HR/RR + BCG สดหลัง Restart"
    )
    value["evidence_held_between_epochs"] = True
    return value


def _needs_continuity_hold(
    cached: dict[str, Any] | None,
    previous_stage: str | None,
    sleep_states: tuple[str, ...],
) -> bool:
    return bool(
        previous_stage in sleep_states
        and not (
            isinstance(cached, dict)
            and cached.get("classification_active")
            and cached.get("state") == previous_stage
        )
    )


def _continuity_value(
    *,
    previous_stage: str | None,
    hold_epochs: int,
    sleep_states: tuple[str, ...],
    estimator_version: str,
    evidence_version: str,
    current_data_status: str | None = None,
    current_data_reason: str | None = None,
) -> dict[str, Any]:
    """Carry one State for every occupied frame without changing its label."""
    confirmation = continuity_hold_contract(
        previous_stage,
        decision=(
            "sensor_evidence_gap_hold"
            if current_data_status
            else "rebuilding_confirmation_window_hold"
        ),
        hold_epochs=hold_epochs,
    )
    attributed_stage = str(confirmation["confirmed_state"])
    display_probabilities = {
        stage: 1.0 if stage == attributed_stage else 0.0
        for stage in sleep_states
    }
    value = {
        "state": attributed_stage,
        "confirmed_state": attributed_stage,
        "version": estimator_version,
        "evidence_version": evidence_version,
        "classification_active": True,
        "evidence_active": False,
        "probabilities": display_probabilities,
        "evidence_probabilities": {stage: 0.0 for stage in sleep_states},
        "confirmed_probabilities": display_probabilities,
        "confidence": "low",
        "provisional": bool(confirmation.get("provisional")),
        "held_previous_state": bool(confirmation["held_previous_state"]),
        "continuity_hold_epochs": int(
            confirmation.get("continuity_hold_epochs") or 1
        ),
        "score_attribution_state": attributed_stage,
        "challenger_counted_as_new_state": False,
        "score_eligible": bool(confirmation.get("score_eligible")),
        "excluded_from_score": bool(
            confirmation.get("excluded_from_score", True)
        ),
        "excluded_from_personal_baseline": True,
        "data_status": str(
            confirmation.get("data_status") or "provisional_hold"
        ),
        "reason": (
            "เริ่ม Recording ที่ W · รอ Evidence ยืนยัน State ถัดไป"
            if confirmation.get("state_source") == "initial_awake_anchor"
            else "ยึด State ที่ยืนยันก่อนหน้า · รอ Evidence ยืนยัน State ใหม่"
        ),
        "confirmation": confirmation,
        "display_probability_basis": "previous_confirmed_state",
        "evidence_held_between_epochs": True,
    }
    if current_data_status:
        value["current_data_status"] = current_data_status
        value["current_data_reason"] = current_data_reason
    return value


def _cached_value(cached: dict[str, Any]) -> dict[str, Any]:
    """Expose the last evidence result with an honest continuity status."""
    value = dict(cached)
    if value.get("display_only_after_restart"):
        value["data_status"] = "restored_confirmed_state"
    elif value.get("held_previous_state"):
        value.update({
            "provisional": False,
            "score_eligible": True,
            "excluded_from_score": False,
            "excluded_from_personal_baseline": True,
            "data_status": "continuity_hold",
        })
    elif value.get("classification_active"):
        value["data_status"] = "live"
    else:
        value["data_status"] = (
            value.get("data_status") or "confirming_initial_state"
        )
    value["evidence_held_between_epochs"] = True
    return value
