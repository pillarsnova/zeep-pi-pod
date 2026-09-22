"""Allowlisted session, device-intent and provenance projection for Admin."""

from __future__ import annotations

from typing import Any

ADAPTIVE_LEARNING_VERSION = "zeep.adaptive-learning-live.v1"


def device_intent(snapshot: dict[str, Any]) -> dict[str, Any]:
    aircon = snapshot.get("aircon") or {}
    music = snapshot.get("music") or {}
    bed = snapshot.get("bed_control") or {}
    return {
        "aircon": {
            "connected": bool(aircon.get("connected")),
            "power": aircon.get("power"),
            "desired_temperature_c": aircon.get("desired_temperature_c"),
            "fan_level_reference": aircon.get("fan_level"),
            "command_pending": bool(aircon.get("command_pending")),
            "state_kind": "last_acknowledged_intent",
        },
        "music": {
            "playing": bool(music.get("playing")),
            "paused": bool(music.get("paused")),
            "volume_pct": music.get("volume"),
            "track": music.get("track"),
            "mode": music.get("mode"),
        },
        "bed": {
            "connected": bool(bed.get("connected")),
            "active_command": bed.get("active_command"),
            "command_pending": bool(bed.get("command_pending")),
            "adaptive_motion_allowed": False,
        },
        "gpio": dict(snapshot.get("gpio") or {}),
    }


def learning_versions(snapshot: dict[str, Any]) -> dict[str, Any]:
    smart = snapshot.get("smart_response") or {}
    sleep = snapshot.get("sleep") or {}
    baseline = sleep.get("baseline_definition") or {}
    frame = snapshot.get("sensor_frame") or {}
    return {
        "adaptive_learning": ADAPTIVE_LEARNING_VERSION,
        "smart_response_policy": smart.get("policy_version"),
        "sleep_estimator": sleep.get("version"),
        "sleep_evidence": sleep.get("evidence_version"),
        "sleep_baseline": baseline.get("version"),
        "sleep_transition_policy": baseline.get("transition_policy"),
        "sensor_frame_source": frame.get("source"),
        "sensor_frame_sequence": frame.get("sequence"),
    }


def build_observation_id(snapshot: dict[str, Any]) -> str:
    session = snapshot.get("session") or {}
    frame = snapshot.get("sensor_frame") or {}
    sequence = frame.get("sequence")
    return ":".join(
        (
            str(session.get("session_id") or "idle"),
            str(sequence if sequence is not None else "waiting"),
        )
    )


def session_summary(
    session: dict[str, Any],
    smart: dict[str, Any],
    group: str,
) -> dict[str, Any]:
    return {
        "active": bool(session.get("active")),
        "recording": bool(session.get("recording")),
        "session_id": session.get("session_id"),
        "rest_mode": session.get("rest_mode"),
        "mode_group": group,
        "target_duration_s": session.get("target_duration_s"),
        "phase": smart.get("phase"),
    }


def sleep_estimator_context(sleep: dict[str, Any]) -> dict[str, Any]:
    return {
        "state": sleep.get("state"),
        "confirmed_state": sleep.get("confirmed_state"),
        "confidence": sleep.get("confidence"),
        "provisional": bool(sleep.get("provisional")),
        "classification_active": bool(sleep.get("classification_active")),
        "role": "wellness_proxy_not_ground_truth",
    }
