"""Compose read-only Smart Senses observations for the Admin monitor.

Feature preparation, quality checks, advice and projection have separate owners.
This facade preserves the existing public function and payload.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from adaptive.control_policy import advisory_control_policy
from adaptive.features import finite_number, prepare_live_features
from adaptive.learning_context import (
    ADAPTIVE_LEARNING_VERSION,
    build_observation_id,
    device_intent,
    learning_versions,
    session_summary,
    sleep_estimator_context,
)
from adaptive.learning_quality import baseline_summary, data_quality, learning_blockers
from adaptive.learning_recommendations import build_candidate_recommendations

DEFAULT_WINDOW_SECONDS = 300


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
    quality = data_quality(snapshot, samples, expected)
    observation_id = build_observation_id(snapshot)
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
        "session": session_summary(session, smart, group),
        "cadence": {
            "sensor_frame_s": frame.get("refresh_s") or 10,
            "rolling_window_s": window_seconds,
            "sleep_evidence_epoch_s": sleep.get("evidence_epoch_s") or 30,
            "sleep_confirmation_s": sleep.get("confirmation_s") or 60,
        },
        "data_quality": quality,
        "baseline": baseline_summary(
            baseline_data,
            behaviour_data,
            metrics,
            group,
        ),
        "live_features": metrics,
        "sleep_estimator": sleep_estimator_context(sleep),
        "device_intent": device_intent(snapshot),
        "candidate_recommendations": build_candidate_recommendations(
            snapshot, metrics, behaviour_data, observation_id
        ),
        "blockers": learning_blockers(snapshot, quality),
        "versions": learning_versions(snapshot),
        "guardrails": [
            "Admin telemetry only; not shown as a consumer health result",
            "No automatic device command is generated or executed",
            "Every Baseline value exposes its reference scope",
            "Stale or invalid values are excluded instead of treated as zero",
            "Sleep State is a wellness proxy and never overrides Safety",
        ],
    }
