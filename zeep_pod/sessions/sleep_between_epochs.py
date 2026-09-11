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
    sample_seconds: float,
    required_samples: int,
    evidence_epoch_seconds: float,
    confirmation_seconds: float,
) -> dict[str, Any]:
    """Return one display result while no new evidence epoch is due."""
    if issue and restart_hold and _restart_can_bridge(issue):
        value = dict(restart_hold)
        value["current_data_status"] = issue.data_status
        value["current_data_reason"] = issue.reason
        return value
    if issue:
        return _inactive_value(cached, issue, sleep_states)
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
    return _initial_wait_value(
        sleep_states=sleep_states,
        estimator_version=estimator_version,
        evidence_version=evidence_version,
        sample_seconds=sample_seconds,
        required_samples=required_samples,
        evidence_epoch_seconds=evidence_epoch_seconds,
        confirmation_seconds=confirmation_seconds,
    )


def _restart_can_bridge(issue: BetweenEpochIssue) -> bool:
    return issue.data_status == "invalid_or_missing_current_vitals"


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
    """Keep the durable pre-restart State display-only during reconnect."""
    value = dict(restart_hold)
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
    previous_stage: str,
    hold_epochs: int,
    sleep_states: tuple[str, ...],
    estimator_version: str,
    evidence_version: str,
) -> dict[str, Any]:
    """Carry a confirmed State while fresh evidence is being rebuilt."""
    confirmation = continuity_hold_contract(
        previous_stage,
        decision="rebuilding_confirmation_window_hold",
        hold_epochs=hold_epochs,
    )
    display_probabilities = {
        stage: 1.0 if stage == previous_stage else 0.0
        for stage in sleep_states
    }
    return {
        "state": previous_stage,
        "confirmed_state": previous_stage,
        "version": estimator_version,
        "evidence_version": evidence_version,
        "classification_active": True,
        "evidence_active": False,
        "probabilities": display_probabilities,
        "evidence_probabilities": {stage: 0.0 for stage in sleep_states},
        "confirmed_probabilities": display_probabilities,
        "confidence": "low",
        "provisional": bool(confirmation.get("provisional")),
        "held_previous_state": True,
        "continuity_hold_epochs": int(
            confirmation.get("continuity_hold_epochs") or 1
        ),
        "score_attribution_state": previous_stage,
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
            "ข้อมูลสดกลับมาแล้ว · ยึด State ที่ยืนยันก่อนหน้า"
            "ระหว่างรอ Evidence epoch ถัดไป"
        ),
        "confirmation": confirmation,
        "display_probability_basis": "previous_confirmed_state",
        "evidence_held_between_epochs": True,
    }


def _cached_value(cached: dict[str, Any]) -> dict[str, Any]:
    """Expose the last evidence result with an honest continuity status."""
    value = dict(cached)
    if value.get("display_only_after_restart"):
        value["data_status"] = "restored_confirmed_state"
    elif value.get("held_previous_state"):
        value["data_status"] = value.get("data_status") or (
            "provisional_hold"
            if value.get("provisional")
            else "continuity_hold"
        )
    elif value.get("classification_active"):
        value["data_status"] = "live"
    else:
        value["data_status"] = (
            value.get("data_status") or "confirming_initial_state"
        )
    value["evidence_held_between_epochs"] = True
    return value


def _initial_wait_value(
    *,
    sleep_states: tuple[str, ...],
    estimator_version: str,
    evidence_version: str,
    sample_seconds: float,
    required_samples: int,
    evidence_epoch_seconds: float,
    confirmation_seconds: float,
) -> dict[str, Any]:
    """Describe the bounded first evidence accumulation interval."""
    return {
        "state": "no_data",
        "confirmed_state": None,
        "version": estimator_version,
        "evidence_version": evidence_version,
        "classification_active": False,
        "evidence_active": False,
        "probabilities": {key: 0.0 for key in sleep_states},
        "evidence_probabilities": {key: 0.0 for key in sleep_states},
        "confidence": "low",
        "provisional": True,
        "score_eligible": False,
        "excluded_from_score": True,
        "excluded_from_personal_baseline": True,
        "data_status": "collecting_evidence_epoch",
        "reason": (
            "กำลังสะสม Sensor 10 วินาทีเพื่อสร้าง Evidence epoch 30 วินาที"
        ),
        "sample_s": sample_seconds,
        "required_samples": required_samples,
        "evidence_epoch_s": evidence_epoch_seconds,
        "confirmation_s": confirmation_seconds,
    }
