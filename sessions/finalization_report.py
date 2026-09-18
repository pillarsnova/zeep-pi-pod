"""Assemble the existing live report without changing formulas or provenance."""

from __future__ import annotations

from collections import Counter
from typing import Any

from sessions.cadence import sample_interval_seconds
from sessions.finalization_contracts import FinalizationPolicy, SessionFinalizationPorts
from sessions.finalization_summary import build_final_summary, build_night_summary
from sleep_signal_features import terminal_occupancy_timeline, terminal_wake_transition


def prepare_record(
    active: dict[str, Any],
    projection: dict[str, Any],
    *,
    reason: str,
    ended_at_utc: str,
    duration: float,
    acquisition_interval_s: float,
    ports: SessionFinalizationPorts,
    policy: FinalizationPolicy,
) -> dict[str, Any] | None:
    """Freeze projected samples and the same time-weighted summary fields."""
    record = active["record"]
    samples = projection["samples"]
    report_samples = projection["report_samples"]
    estimator_versions = Counter(
        sample.get("sleep_estimator_version")
        for sample in samples
        if sample.get("sleep_estimator_version")
    )
    latest_version = next(
        (
            sample.get("sleep_estimator_version")
            for sample in reversed(samples)
            if sample.get("sleep_estimator_version")
        ),
        policy.estimator_version,
    )
    record.update(
        {
            "ended_at_utc": ended_at_utc,
            "end_reason": reason,
            "duration_s": round(duration, 1),
            "sample_interval_s": projection["report_interval_s"],
            "sensor_sample_interval_s": acquisition_interval_s,
            "sample_cadence_segments": record.get("sample_cadence_segments") or [],
            "sample_cadence_summary": projection["cadence_summary"],
            "report_sample_grid": projection["grid_summary"],
            "samples": samples,
            "summary": {
                # Calculation uses time-weighted rows; stored samples stay auditable.
                "temperature_c": ports.series_stats(
                    [s["temp"] for s in report_samples]
                ),
                "humidity_rh": ports.series_stats([s["hum"] for s in report_samples]),
                "sound_dba_est": ports.series_stats([s["dba"] for s in report_samples]),
                "lux": ports.series_stats([s["lux"] for s in report_samples]),
                "heart_rate_bpm": ports.series_stats([s["hr"] for s in report_samples]),
                "respiration_rate": ports.series_stats(
                    [s["rr"] for s in report_samples]
                ),
                "bed_status_counts": projection["bed_status_counts"],
                "sleep_state_counts": projection["sleep_state_counts"],
                "sleep_score_state_counts": projection["sleep_score_state_counts"],
            },
            "sleep_estimator": latest_version,
            "sleep_estimator_versions": dict(estimator_versions),
            "sleep_provenance_complete": bool(samples)
            and sum(estimator_versions.values()) == len(samples),
            "sleep_evidence_version": policy.evidence_version,
            "sleep_baseline_version": policy.baseline_version,
            "sleep_transition_policy": policy.transition_policy,
            "sleep_g2_ontology": policy.g2_ontology,
            "terminal_wake_policy": policy.terminal_wake_policy,
            "counters": active["counters"],
        }
    )
    # The explicit End/terminal exit is an operational boundary, not an AASM
    # epoch. Keep the final Wake marker out of all stage totals and scores.
    terminal_occupancy = terminal_occupancy_timeline(
        samples,
        session_end=record["ended_at_utc"],
        sample_interval_s=sample_interval_seconds(
            samples[-1].get("sample_interval_s") if samples else None,
            acquisition_interval_s,
        ),
    )
    terminal_wake = terminal_wake_transition(
        ({"state": sample.get("sleep")} for sample in samples),
        terminal_occupancy=terminal_occupancy,
        session_end=record["ended_at_utc"],
        end_reason=reason,
    )
    record["terminal_wake_transition"] = terminal_wake
    return terminal_wake


def build_recorded_report(
    record: dict[str, Any],
    projection: dict[str, Any],
    *,
    duration: float,
    acquisition_interval_s: float,
    terminal_wake: dict[str, Any] | None,
    ports: SessionFinalizationPorts,
    policy: FinalizationPolicy,
) -> dict[str, Any]:
    """Build score/report before learning from this Session; return DB summary."""
    report_samples = projection["report_samples"]
    interval_s = projection["report_interval_s"]
    night = build_night_summary(
        record, report_samples, duration=duration, sample_interval_s=interval_s
    )
    quality = ports.build_quality(
        record["duration_s"],
        night,
        record["summary"]["sleep_state_counts"],
        completed=True,
        rest_mode=record.get("rest_mode") or "auto",
        stage_sequence=report_samples,
        sensor_samples=report_samples,
        sample_interval_s=sample_interval_seconds(interval_s, policy.sample_interval_s),
        target_duration_s=record.get("target_duration_s"),
        score_state_counts=record["summary"]["sleep_score_state_counts"],
    )
    night["sleep_quality"] = quality
    night["wellness_score"] = quality.get("score")
    record["sleep_quality"] = quality
    context = ports.baseline_context(
        record["username_key"],
        record.get("rest_mode") or "auto",
        record.get("target_duration_s"),
    )
    report = ports.build_report(
        record["duration_s"],
        report_samples,
        night,
        record["summary"]["sleep_state_counts"],
        quality,
        rest_mode=record.get("rest_mode") or "auto",
        sample_interval_s=interval_s,
        estimator_version=record.get("sleep_estimator"),
        completed=True,
        timeline_schema_version=policy.timeline_schema_version,
        target_duration_s=record.get("target_duration_s"),
        personal_context=context,
        trend_context=context,
        health_reference=record.get("health_reference"),
        sleep_score_state_counts=record["summary"]["sleep_score_state_counts"],
    )
    record["session_report"] = report
    return build_final_summary(
        record,
        sample_interval_s=interval_s,
        acquisition_interval_s=acquisition_interval_s,
        cadence_summary=projection["cadence_summary"],
        sample_grid_summary=projection["grid_summary"],
        restore_context=context,
        night_summary=night,
        session_report=report,
        terminal_wake=terminal_wake,
        timeline_schema_version=policy.timeline_schema_version,
        bed_start_seconds=policy.bed_start_seconds,
    )
