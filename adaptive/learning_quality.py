"""Live data quality, reference readiness and learning blockers."""

from __future__ import annotations

from typing import Any

from common.numbers import as_finite_number as finite_number


def data_quality(
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


def baseline_summary(
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


def learning_blockers(
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
