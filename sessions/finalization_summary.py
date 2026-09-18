"""Pure finalization calculations shared by the live Session lifecycle.

The formulas and payload fields are extracted unchanged from the application.
Storage, occupancy, account APIs and checkpoint order remain with orchestration.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sessions.cadence import sample_interval_seconds
from sessions.ingest_payload import sample_off_bed


def build_night_summary(
    record: dict[str, Any],
    report_samples: list[dict[str, Any]],
    *,
    duration: float,
    sample_interval_s: float,
) -> dict[str, Any]:
    """Calculate onset, continuity and stage ratios with the legacy semantics."""
    # night summary (proxy จาก per-sample sleep state) — ป้อน baseline ส่วนบุคคล
    sleep_like = {"n1", "n2", "n3", "rem", "nrem_light", "nrem_deep"}
    onset_proxy_s = None
    awakenings = 0
    asleep = False
    sleep_started = False
    waso_seconds = 0.0
    try:
        started_epoch = datetime.fromisoformat(record["started_at_utc"]).timestamp()
    except (TypeError, ValueError):
        started_epoch = None
    for smp in report_samples:
        st = (
            "off_bed"
            if sample_off_bed(smp)
            else (
                smp.get("sleep")
                if smp.get("sleep_score_eligible") is not False
                else None
            )
        )
        if st in sleep_like:
            if onset_proxy_s is None and started_epoch:
                interval_s = sample_interval_seconds(
                    smp.get("sample_interval_s"), sample_interval_s
                )
                onset_proxy_s = round(
                    max(0.0, smp["t"] - interval_s - started_epoch),
                    1,
                )
            asleep = True
            sleep_started = True
        elif st in ("wake", "off_bed"):
            if sleep_started:
                waso_seconds += sample_interval_seconds(
                    smp.get("sample_interval_s"), sample_interval_s
                )
            if asleep:
                awakenings += 1
                asleep = False
    total_sleep_samples = sum(
        v
        for k, v in record["summary"]["sleep_score_state_counts"].items()
        if k in sleep_like
    )
    total_scored = total_sleep_samples + record["summary"][
        "sleep_score_state_counts"
    ].get("wake", 0)
    night_summary = {
        "sleep_onset_proxy_s": onset_proxy_s,
        "awakenings": awakenings,
        "waso_proxy_s": round(waso_seconds, 1),
        "estimated_sleep_s": round(
            min(duration, total_sleep_samples * sample_interval_s), 1
        ),
        "sleep_efficiency": (
            round(total_sleep_samples / total_scored, 3) if total_scored else None
        ),
        "deep_ratio": (
            round(
                (
                    record["summary"]["sleep_score_state_counts"].get("n3", 0)
                    + record["summary"]["sleep_score_state_counts"].get("nrem_deep", 0)
                )
                / total_sleep_samples,
                3,
            )
            if total_sleep_samples
            else None
        ),
        "rem_ratio": (
            round(
                record["summary"]["sleep_score_state_counts"].get("rem", 0)
                / total_sleep_samples,
                3,
            )
            if total_sleep_samples
            else None
        ),
    }
    return night_summary


def build_final_summary(
    record: dict[str, Any],
    *,
    sample_interval_s: float,
    acquisition_interval_s: float,
    cadence_summary: dict[str, Any],
    sample_grid_summary: dict[str, Any],
    restore_context: dict[str, Any],
    night_summary: dict[str, Any],
    session_report: dict[str, Any],
    terminal_wake: dict[str, Any] | None,
    timeline_schema_version: int,
    bed_start_seconds: float,
) -> dict[str, Any]:
    """Freeze report and provenance into the existing durable summary shape."""
    return {
        "bed_status_counts": record["summary"]["bed_status_counts"],
        "sleep_state_counts": record["summary"]["sleep_state_counts"],
        "sleep_score_state_counts": record["summary"]["sleep_score_state_counts"],
        "sleep_estimator": record.get("sleep_estimator"),
        "sleep_estimator_versions": record.get("sleep_estimator_versions") or {},
        "sleep_provenance_complete": record.get("sleep_provenance_complete", False),
        "sleep_evidence_version": record.get("sleep_evidence_version"),
        "sleep_baseline_version": record.get("sleep_baseline_version"),
        "sleep_transition_policy": record.get("sleep_transition_policy"),
        "sleep_g2_ontology": record.get("sleep_g2_ontology"),
        "terminal_wake_policy": record.get("terminal_wake_policy"),
        "rest_mode": record.get("rest_mode") or "auto",
        "target_duration_s": record.get("target_duration_s"),
        "sample_interval_s": sample_interval_s,
        "sensor_sample_interval_s": acquisition_interval_s,
        "timeline_schema_version": timeline_schema_version,
        "sample_cadence_segments": record.get("sample_cadence_segments") or [],
        "sample_cadence_summary": cadence_summary,
        "report_sample_grid": sample_grid_summary,
        # Snapshot the non-diagnostic Profile context used during this
        # Session so later account edits do not rewrite historical reports.
        "health_reference": record.get("health_reference") or {},
        # Optional, consented lifestyle context is frozen separately from
        # physiology. It may explain/report a Session but cannot create or
        # modify W/N1/N2/N3/REM.
        "wellness_context": record.get("wellness_context"),
        "restore_context": restore_context,
        "counters": record["counters"],
        "armed_at_utc": record.get("armed_at_utc"),
        "bed_start_s": bed_start_seconds,
        "night_summary": night_summary,
        "session_report": session_report,
        "terminal_wake_transition": terminal_wake,
    }
