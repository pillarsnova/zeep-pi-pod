"""Admin-only live dataset for future adaptive ZEEP control.

The builder is pure: it compares observations and exposes shadow
recommendations, but it cannot call hardware or issue commands.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from adaptive.control_policy import advisory_control_policy, enforce_advisory
from adaptive.features import finite_number, prepare_live_features

ADAPTIVE_LEARNING_VERSION = "zeep.adaptive-learning-live.v1"
DEFAULT_WINDOW_SECONDS = 300


def _data_quality(
    snapshot: dict[str, Any],
    samples: list[dict[str, Any]],
    expected_samples: int,
) -> dict[str, Any]:
    environment = (snapshot.get("sensor") or {}).get("environment") or {}
    bcg = (snapshot.get("sensor") or {}).get("bcg") or {}
    frame = snapshot.get("sensor_frame") or {}
    devices = environment.get("devices") or {}
    live_devices = sum(
        1
        for device in devices.values()
        if isinstance(device, dict) and device.get("status") == "live"
    )
    bcg_live = bool(
        not frame.get("stale")
        and bcg.get("connected")
        and not bcg.get("stale")
        and bcg.get("analysis_valid")
    )
    vital_pair = bool(
        bcg_live
        and finite_number(bcg.get("heart_rate_bpm")) is not None
        and finite_number(bcg.get("respiration_rate")) is not None
    )
    return {
        "environment_live": live_devices,
        "environment_total": int(environment.get("total_count") or 6),
        "bcg_live": bcg_live,
        "vital_pair_live": vital_pair,
        "sensor_frame_stale": bool(frame.get("stale")),
        "sensor_frame_age_s": frame.get("data_age_s"),
        "window_samples": len(samples),
        "window_expected_samples": expected_samples,
        "window_coverage_pct": round(
            min(1.0, len(samples) / max(1, expected_samples)) * 100.0,
            1,
        ),
        "observation_ready": bool(live_devices),
        "physiology_comparison_ready": vital_pair,
    }


def _baseline_summary(
    baseline: dict[str, Any],
    behaviour: dict[str, Any],
    metrics: list[dict[str, Any]],
    group: str,
) -> dict[str, Any]:
    sessions = int(behaviour.get("sessions_used") or baseline.get("nights_used") or 0)
    minimum = int(behaviour.get("minimum_sessions") or baseline.get("min_nights") or 3)
    status = str(behaviour.get("status") or baseline.get("status") or "no_data")
    reference_count = sum(metric["reference"] is not None for metric in metrics)
    personal_active = bool(
        baseline.get("direct_stage_influence") and baseline.get("source") == "personal"
    )
    best_window = behaviour.get("best_rest_window") or {}
    best_window_ready = bool(
        best_window.get("available")
        and best_window.get("outcome_supported")
        and best_window.get("environment_reference_available")
    )
    return {
        "status": status,
        "sessions_used": sessions,
        "minimum_sessions": minimum,
        "comparison_ready": bool(status == "active" and reference_count),
        "provisional_recommendation_ready": bool(best_window_ready and reference_count),
        "reference_metrics": reference_count,
        "behaviour_reference_same_mode_only": True,
        "physiology_reference_scope": (
            "prior_completed_same_mode_sessions"
            if group == "sleep"
            else "qualified_overnight_reference"
        ),
        "prior_completed_sessions_only": True,
        "mode_group": group,
        "policy_version": baseline.get("policy_version"),
        "score_median": behaviour.get("score_median"),
        "score_typical_range": behaviour.get("score_typical_range"),
        "active_stage_source": "personal" if personal_active else "age_gender",
        "personal_stage_candidate": baseline.get("status") or "no_data",
        "personal_direct_stage_influence": personal_active,
        "best_rest_window": dict(best_window),
    }


def _blockers(
    snapshot: dict[str, Any],
    quality: dict[str, Any],
) -> list[dict[str, Any]]:
    smart = snapshot.get("smart_response") or {}
    blockers = [
        dict(item) for item in smart.get("blockers") or [] if isinstance(item, dict)
    ]
    if not (snapshot.get("session") or {}).get("recording"):
        blockers.append(
            {
                "code": "session_not_recording",
                "message": "ยังไม่มี Session ที่กำลังบันทึก",
            }
        )
    if not quality["vital_pair_live"]:
        blockers.append(
            {
                "code": "physiology_not_live",
                "message": "HR/RR สดยังไม่ครบสำหรับเทียบการตอบสนอง",
            }
        )
    if quality["sensor_frame_stale"]:
        blockers.append(
            {
                "code": "sensor_frame_stale",
                "message": "Sensor frame ล่าสุดเป็นข้อมูลค้าง",
            }
        )
    return blockers


def _recommendations(
    snapshot: dict[str, Any],
    observation_id: str,
) -> list[dict[str, Any]]:
    smart = snapshot.get("smart_response") or {}
    return [
        {
            "decision_id": f"{observation_id}:{item.get('domain') or 'general'}",
            "domain": item.get("domain"),
            "level": item.get("level"),
            "title": item.get("title"),
            "evidence": item.get("detail"),
            "candidate": item.get("suggestion"),
            "executable": False,
        }
        for item in smart.get("recommendations") or []
        if isinstance(item, dict)
    ]


def _personal_reference_recommendations(
    metrics: list[dict[str, Any]],
    behaviour: dict[str, Any],
    observation_id: str,
) -> list[dict[str, Any]]:
    """Translate a qualified prior Session into review-only device guidance."""
    best_window = behaviour.get("best_rest_window") or {}
    if not (
        best_window.get("available") is True
        and best_window.get("outcome_supported") is True
        and best_window.get("environment_reference_available") is True
    ):
        return []

    settings = {
        "temperature": ("aircon", "อุณหภูมิ", True),
        "humidity": ("humidity", "ความชื้น", True),
        "co2": ("ventilation", "CO₂", False),
        "light": ("light", "แสง", False),
        "sound": ("sound", "เสียง", False),
    }
    recommendations = []
    for metric in metrics:
        key = metric.get("key")
        setting = settings.get(key)
        comparison = metric.get("comparison")
        if setting is None or comparison not in {"above_reference", "below_reference"}:
            continue
        domain, label, allow_both_directions = setting
        if not allow_both_directions and comparison == "below_reference":
            continue
        value = finite_number(metric.get("value"))
        reference = finite_number(metric.get("reference"))
        if value is None or reference is None:
            continue
        direction = "ลด" if value > reference else "เพิ่ม"
        unit = str(metric.get("unit") or "")
        recommendations.append(
            {
                "decision_id": f"{observation_id}:personal:{key}",
                "domain": domain,
                "level": "personal_baseline",
                "title": f"{label}ต่างจากช่วงที่เคยพักได้ดี",
                "evidence": (f"ปัจจุบัน {value:g} {unit} · ข้อมูลตั้งต้น {reference:g} {unit}"),
                "candidate": f"ลอง{direction}{label}ให้ใกล้ {reference:g} {unit}",
                "basis": "prior_completed_same_mode_best_rest_window",
                "baseline_status": best_window.get("status"),
                "requires_user_confirmation": True,
                "executable": False,
            }
        )
    return recommendations


def _device_intent(snapshot: dict[str, Any]) -> dict[str, Any]:
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


def _versions(snapshot: dict[str, Any]) -> dict[str, Any]:
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


def _observation_id(snapshot: dict[str, Any]) -> str:
    session = snapshot.get("session") or {}
    frame = snapshot.get("sensor_frame") or {}
    sequence = frame.get("sequence")
    return ":".join(
        (
            str(session.get("session_id") or "idle"),
            str(sequence if sequence is not None else "waiting"),
        )
    )


def _session_summary(
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


def _sleep_estimator(sleep: dict[str, Any]) -> dict[str, Any]:
    return {
        "state": sleep.get("state"),
        "confirmed_state": sleep.get("confirmed_state"),
        "confidence": sleep.get("confidence"),
        "provisional": bool(sleep.get("provisional")),
        "classification_active": bool(sleep.get("classification_active")),
        "role": "wellness_proxy_not_ground_truth",
    }


def build_adaptive_learning_snapshot(
    snapshot: dict[str, Any],
    *,
    baseline: dict[str, Any] | None = None,
    behaviour: dict[str, Any] | None = None,
    recent_samples: list[dict[str, Any]] | None = None,
    now: float | None = None,
    window_seconds: int = DEFAULT_WINDOW_SECONDS,
) -> dict[str, Any]:
    """Build one explainable Shadow observation for the Admin monitor."""
    generated_epoch = finite_number(now)
    if generated_epoch is None:
        generated_epoch = datetime.now(UTC).timestamp()
    baseline_data = dict(baseline or {})
    behaviour_data = dict(behaviour or {})
    valid_samples = (
        dict(item) for item in recent_samples or [] if isinstance(item, dict)
    )
    metrics, samples, expected, group = prepare_live_features(
        snapshot,
        baseline_data,
        behaviour_data,
        valid_samples,
        now=generated_epoch,
        window_seconds=window_seconds,
    )
    session = snapshot.get("session") or {}
    sleep = snapshot.get("sleep") or {}
    smart = snapshot.get("smart_response") or {}
    frame = snapshot.get("sensor_frame") or {}
    quality = _data_quality(snapshot, samples, expected)
    observation_id = _observation_id(snapshot)
    return {
        "schema_version": ADAPTIVE_LEARNING_VERSION,
        "observation_id": observation_id,
        "generated_at": datetime.fromtimestamp(
            generated_epoch,
            UTC,
        ).isoformat(timespec="milliseconds"),
        "mode": "shadow",
        "summary": (
            "พร้อมเก็บข้อมูลและเทียบ Baseline"
            if session.get("recording") and quality["environment_live"]
            else "กำลังรอข้อมูลสำหรับ Adaptive Learning"
        ),
        "control_policy": advisory_control_policy(),
        "session": _session_summary(session, smart, group),
        "cadence": {
            "sensor_frame_s": frame.get("refresh_s") or 10,
            "rolling_window_s": window_seconds,
            "sleep_evidence_epoch_s": sleep.get("evidence_epoch_s") or 30,
            "sleep_confirmation_s": sleep.get("confirmation_s") or 60,
        },
        "data_quality": quality,
        "baseline": _baseline_summary(
            baseline_data,
            behaviour_data,
            metrics,
            group,
        ),
        "live_features": metrics,
        "sleep_estimator": _sleep_estimator(sleep),
        "device_intent": _device_intent(snapshot),
        "candidate_recommendations": enforce_advisory(
            [
                *_personal_reference_recommendations(
                    metrics,
                    behaviour_data,
                    observation_id,
                ),
                *_recommendations(snapshot, observation_id),
            ]
        ),
        "blockers": _blockers(snapshot, quality),
        "versions": _versions(snapshot),
        "guardrails": [
            "Admin telemetry only; not shown as a consumer health result",
            "No automatic device command is generated or executed",
            "Every Baseline value exposes its reference scope",
            "Stale or invalid values are excluded instead of treated as zero",
            "Sleep State is a wellness proxy and never overrides Safety",
        ],
    }
