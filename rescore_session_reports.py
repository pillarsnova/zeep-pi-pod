#!/usr/bin/env python3
"""Rebuild completed Session quality reports with the current score version.

Only the derived ``final_summary`` is replaced. Raw BCG packets, timeline rows
and every versioned-cadence sleep-stage event remain byte-for-byte untouched. The
previous quality object is retained in an audit event so the calculation can
be inspected or reversed without inventing historical Sensor evidence.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import statistics
from typing import Any, Dict

from sleep_session_report import (
    SLEEP_QUALITY_VERSION,
    build_session_report,
    build_sleep_quality,
    normalise_rest_mode,
)
from sleep_system_policy import (
    NAP_RECOVERY_LEGACY_HARD_MAX_SECONDS,
    NAP_RECOVERY_MINIMUM_SCORE_SECONDS,
    SLEEP_EVIDENCE_VERSION,
    SLEEP_G2_ONTOLOGY_VERSION,
    ZEEP_SLEEP_BASELINE_VERSION,
    ZEEP_SLEEP_TRANSITION_POLICY_VERSION,
    is_approved_sleep_result_version,
    resolve_rest_target,
    rest_mode_group,
)
from sleep_stage_annotations import apply_annotations, load_annotations
from sleep_signal_features import (
    HR_SANITY_RANGE_BPM,
    RR_SANITY_RANGE_PER_MIN,
    terminal_occupancy_timeline,
)
from zeep_pod.sessions.cadence import timeline_sample_interval
from zeep_pod.sessions.report_projection import project_report_samples
from zeep_pod.sessions.report_timeline import (
    sensor_samples as shared_sensor_samples,
    timeline_projection as shared_timeline_projection,
)
from zeep_pod.sessions.sleep_event_data import decision_interval


MAINTENANCE_TOOL_NAME = "rescore_session_reports.py"
STAGES = ("wake", "n1", "n2", "n3", "rem")
SLEEP_STAGES = {"n1", "n2", "n3", "rem"}
LEGACY_SAMPLE_SECONDS = 5.0


class HistoricalModeReviewRequired(ValueError):
    """The stored Session intent is insufficient for an automatic rewrite."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _json(value: Any) -> Dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _positive_seconds(value: Any, fallback: float) -> float:
    """Return a finite positive cadence without trusting legacy metadata."""
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return fallback
    return seconds if seconds > 0 else fallback


def _stage_cadence(values: list[Dict[str, Any]], fallback: float) -> float:
    """Infer the cadence of derived stages independently from Sensor cadence.

    Since stable-30s-epoch, Timeline Sensor samples arrive every 10 seconds but
    one confirmed Sleep State represents 30 seconds.  Historical summaries may
    still carry the Sensor cadence in ``sample_interval_s``; using that value
    for state durations shortens TST and coverage by threefold.
    """
    intervals = [
        _positive_seconds(value.get("sample_interval_s"), fallback)
        for value in values
        if value.get("sample_interval_s") is not None
    ]
    for value in values:
        start_value = value.get("attribution_start") or value.get(
            "window_start"
        )
        end_value = value.get("attribution_end") or value.get("window_end")
        if not start_value or not end_value:
            continue
        try:
            duration = (
                _timestamp(str(end_value)) - _timestamp(str(start_value))
            ).total_seconds()
        except (TypeError, ValueError):
            continue
        if duration > 0:
            intervals.append(duration)
    return float(statistics.median(intervals)) if intervals else fallback


def _timeline_projection(connection: sqlite3.Connection) -> str:
    """Compatibility wrapper for the shared immutable Timeline projection."""
    return shared_timeline_projection(connection)


def _annotated_stage_events(
    stage_rows: list[sqlite3.Row],
    stage_values: list[Dict[str, Any]],
    annotations: list[Dict[str, Any]],
    *,
    fallback_interval_s: float,
    fallback_estimator: Any,
) -> tuple[
    list[Dict[str, Any]],
    list[Dict[str, Any]],
    int,
    Any,
    Dict[str, int],
]:
    """Apply annotations while preserving durable attribution intervals."""
    events: list[Dict[str, Any]] = []
    sequence: list[Dict[str, Any]] = []
    annotated_rounds = 0
    estimator_version = fallback_estimator
    estimator_versions: Dict[str, int] = {}
    for row, parsed_value in zip(stage_rows, stage_values):
        value, annotation = apply_annotations(
            parsed_value,
            row["timestamp"],
            annotations,
            sample_interval_s=_positive_seconds(
                parsed_value.get("sample_interval_s"),
                fallback_interval_s,
            ),
        )
        if annotation is not None:
            annotated_rounds += 1
        stage = value.get("state")
        if stage not in STAGES:
            continue
        events.append({"timestamp": row["timestamp"], "value": value})
        owned_interval = decision_interval(
            {"timestamp": row["timestamp"], "value": value},
            value,
            fallback_interval_s=fallback_interval_s,
        )
        owned_seconds = (
            owned_interval[1] - owned_interval[0]
            if owned_interval is not None
            else _positive_seconds(
                value.get("sample_interval_s"), fallback_interval_s
            )
        )
        # A durable five-state event owns occupied time in the current
        # continuity contract. Legacy provisional/exclusion flags remain in
        # ``value`` for audit, but cannot reopen a scoring gap during rescore.
        sequence.append({
            "state": stage,
            "timestamp": row["timestamp"],
            # Stage analysis runs on the 30-second decision clock while the
            # report rows normally run on the 10-second Sensor clock.  Keep
            # each event's owned duration explicit so arousal/cycle scoring
            # cannot silently shrink every State by threefold.
            "sample_interval_s": owned_seconds,
            "metrics": value.get("metrics") or {},
            "score_eligible": True,
            "provisional": False,
            "held_previous_state": bool(value.get("held_previous_state")),
        })
        estimator_version = value.get("estimator_version") or estimator_version
        if value.get("estimator_version"):
            version = str(value["estimator_version"])
            estimator_versions[version] = estimator_versions.get(version, 0) + 1
    return (
        events,
        sequence,
        annotated_rounds,
        estimator_version,
        estimator_versions,
    )


def _sensor_samples(
    timeline: list[sqlite3.Row],
) -> tuple[list[Dict[str, Any]], Dict[str, int], Dict[str, int]]:
    """Translate Timeline rows through the shared Shadow/Rescore adapter."""
    return shared_sensor_samples(
        timeline,
        timestamp_parser=lambda value: _timestamp(value).timestamp(),
    )


def _projected_night_summary(
    samples: list[Dict[str, Any]],
    *,
    start: datetime,
    interval_s: float,
    score_counts: Dict[str, float],
) -> Dict[str, Any]:
    """Derive duration-aware onset, WASO and architecture from one stream."""
    first_sleep_at: datetime | None = None
    awakenings = 0
    waso_s = 0.0
    asleep = False
    sleep_started = False
    for sample in samples:
        if sample.get("sleep_score_eligible") is False:
            continue
        stage = sample.get("sleep")
        if stage not in STAGES:
            continue
        row_seconds = _positive_seconds(
            sample.get("sample_interval_s"), interval_s
        )
        if stage in SLEEP_STAGES:
            if first_sleep_at is None:
                first_sleep_at = datetime.fromtimestamp(
                    float(sample["t"]) - row_seconds,
                    timezone.utc,
                )
            asleep = True
            sleep_started = True
        elif sleep_started:
            waso_s += row_seconds
            if asleep:
                awakenings += 1
                asleep = False

    total_sleep = sum(score_counts[stage] for stage in SLEEP_STAGES)
    total_scored = total_sleep + score_counts["wake"]
    return {
        "sleep_onset_proxy_s": (
            round(max(0.0, (first_sleep_at - start).total_seconds()), 1)
            if first_sleep_at else None
        ),
        "awakenings": awakenings,
        "waso_proxy_s": round(waso_s, 1),
        "estimated_sleep_s": round(total_sleep * interval_s, 1),
        "sleep_efficiency": (
            round(total_sleep / total_scored, 3) if total_scored else None
        ),
        "deep_ratio": (
            round(score_counts["n3"] / total_sleep, 3)
            if total_sleep else None
        ),
        "rem_ratio": (
            round(score_counts["rem"] / total_sleep, 3)
            if total_sleep else None
        ),
    }


def _rebuild(
    connection: sqlite3.Connection,
    session: sqlite3.Row,
    requested_mode: str | None,
    requested_target_minutes: int | None = None,
    *,
    report_only: bool = False,
) -> Dict[str, Any]:
    session_id = session["session_id"]
    final_row = connection.execute(
        "SELECT id,value FROM events WHERE session_id=? AND type='final_summary' "
        "ORDER BY timestamp DESC,id DESC LIMIT 1", (session_id,),
    ).fetchone()
    if final_row is None:
        raise ValueError(f"completed Session has no final_summary: {session_id}")
    old_final = _json(final_row["value"])
    start = _timestamp(session["start_time"])
    sensor_sample_seconds = _positive_seconds(
        old_final.get("sensor_sample_interval_s")
        or old_final.get("sample_interval_s"),
        LEGACY_SAMPLE_SECONDS,
    )
    session_fields = set(session.keys())
    stored_mode = (
        (session["rest_mode"] if "rest_mode" in session_fields else None)
        or old_final.get("rest_mode")
        or "auto"
    )
    mode = normalise_rest_mode(requested_mode or stored_mode)
    if mode == "auto" and not report_only:
        raise HistoricalModeReviewRequired(
            "unresolved_rest_mode",
            "Session เดิมไม่ได้เก็บ Mode; ห้ามอนุมาน Nap/Overnight จากเวลา",
        )
    old_report = old_final.get("session_report") or {}
    old_quality = old_report.get("quality") or {}
    old_duration_target = old_quality.get("duration_target") or {}
    legacy_target = old_final.get("target_duration_s")
    if legacy_target is None:
        legacy_target = old_duration_target.get("seconds")
    stored_target = (
        session["target_duration_s"]
        if (
            "target_duration_s" in session_fields
            and session["target_duration_s"] is not None
        )
        else legacy_target
    )
    target_seconds = (
        requested_target_minutes * 60
        if requested_target_minutes is not None
        else stored_target
    )
    target = resolve_rest_target(mode, target_seconds)
    duration_s = max(0.0, float(session["duration"] or 0.0))
    hard_timing_guard = (
        duration_s < NAP_RECOVERY_MINIMUM_SCORE_SECONDS
        or duration_s > NAP_RECOVERY_LEGACY_HARD_MAX_SECONDS
    )
    if (
        rest_mode_group(mode) == "nap_recovery"
        and not target.get("available")
        and not hard_timing_guard
        and not report_only
    ):
        raise HistoricalModeReviewRequired(
            "missing_recovery_target",
            "Session เดิมไม่ได้เก็บเป้าหมาย Nap 30/90 นาที; รักษาผลเดิมไว้รอตรวจ",
        )

    stage_rows = connection.execute(
        "SELECT timestamp,value FROM events WHERE session_id=? AND type='sleep_stage' "
        "ORDER BY timestamp,id", (session_id,),
    ).fetchall()
    stage_values = [_json(row["value"]) for row in stage_rows]
    status_rows = connection.execute(
        "SELECT timestamp,value FROM events WHERE session_id=? "
        "AND type='sleep_stage_status' ORDER BY timestamp,id",
        (session_id,),
    ).fetchall()
    status_values = [_json(row["value"]) for row in status_rows]
    stage_sample_seconds = _stage_cadence(
        [*stage_values, *status_values], sensor_sample_seconds
    )
    annotation_rows = connection.execute(
        "SELECT value FROM events WHERE session_id=? AND type='sleep_stage_annotation' "
        "ORDER BY timestamp,id", (session_id,),
    ).fetchall()
    annotations = load_annotations(annotation_rows)
    timeline = connection.execute(
        f"SELECT {_timeline_projection(connection)} FROM timeline "
        "WHERE session_id=? ORDER BY timestamp,id",
        (session_id,),
    ).fetchall()
    raw_samples, raw_bed_status_counts, canonical_bed_status_counts = (
        _sensor_samples(timeline)
    )
    if timeline:
        sensor_sample_seconds = timeline_sample_interval(
            [dict(row) for row in timeline],
            sensor_sample_seconds,
        )
    (
        stage_events,
        sequence,
        annotated_rounds,
        estimator_version,
        estimator_versions,
    ) = _annotated_stage_events(
        stage_rows,
        stage_values,
        annotations,
        fallback_interval_s=stage_sample_seconds,
        fallback_estimator=old_final.get("sleep_estimator"),
    )
    status_events = [
        {"timestamp": row["timestamp"], "value": value}
        for row, value in zip(status_rows, status_values)
    ]
    projection = project_report_samples(
        raw_samples,
        start_at=start,
        # ``duration`` is persisted at display precision and can differ from
        # the authoritative Session boundary by a few milliseconds.  Using
        # start + rounded duration makes a terminal attribution boundary look
        # like an interior split and creates a synthetic sliver row.  Shadow
        # replay is bounded by end_time, so Rescore must use the same boundary
        # for exact coverage/report parity.
        end_at=_timestamp(session["end_time"]),
        cadence_segments=old_final.get("sample_cadence_segments") or [],
        sensor_interval_s=sensor_sample_seconds,
        decision_interval_s=stage_sample_seconds,
        stage_events=stage_events,
        status_events=status_events,
        heart_rate_range=HR_SANITY_RANGE_BPM,
        respiration_rate_range=RR_SANITY_RANGE_PER_MIN,
    )
    if not projection["grid_summary"]["classification_complete"]:
        raise RuntimeError(
            f"rescore continuity invariant failed: {session_id}"
        )
    samples = projection["report_samples"]
    stage_sample_seconds = projection["report_interval_s"]
    counts = {
        stage: projection["sleep_state_counts"].get(stage, 0.0)
        for stage in STAGES
    }
    score_counts = {
        stage: projection["sleep_score_state_counts"].get(stage, 0.0)
        for stage in STAGES
    }
    total_scored = sum(score_counts.values())
    night = dict(old_final.get("night_summary") or {})
    night.update(_projected_night_summary(
        samples,
        start=start,
        interval_s=stage_sample_seconds,
        score_counts=score_counts,
    ))
    previous_quality = (old_final.get("night_summary") or {}).get(
        "sleep_quality"
    )
    if report_only:
        if not isinstance(previous_quality, dict):
            raise ValueError(
                f"report-only requires persisted sleep_quality: {session_id}"
            )
        quality = previous_quality
    else:
        quality = build_sleep_quality(
            duration_s,
            night,
            counts,
            completed=True,
            rest_mode=mode,
            stage_sequence=sequence,
            sensor_samples=samples,
            sample_interval_s=stage_sample_seconds,
            # Preserve provenance: an Overnight policy default is not a
            # user-persisted target merely because it resolves to 7 hours.
            target_duration_s=target_seconds,
            score_state_counts=score_counts,
        )
        timing = (
            (quality.get("rest_mode") or {}).get("protocol_status") or {}
        )
        if (
            timing.get("review_required")
            and duration_s <= NAP_RECOVERY_LEGACY_HARD_MAX_SECONDS
        ):
            raise HistoricalModeReviewRequired(
                "recovery_timing_review",
                str(
                    timing.get("reason")
                    or "Recovery Session ต้องตรวจ Mode/เป้าหมาย"
                ),
            )
    night["sleep_quality"] = quality
    night["wellness_score"] = quality.get("score")
    report = build_session_report(
        duration_s, samples, night, counts, quality,
        rest_mode=mode,
        sample_interval_s=stage_sample_seconds, estimator_version=estimator_version,
        completed=True,
        timeline_schema_version=int(old_final.get("timeline_schema_version") or 3),
        target_duration_s=target_seconds,
        personal_context=(
            old_final.get("restore_context")
            if isinstance(old_final.get("restore_context"), dict)
            else None
        ),
        trend_context=(
            old_final.get("restore_context")
            if isinstance(old_final.get("restore_context"), dict)
            else None
        ),
        health_reference=(
            old_final.get("health_reference")
            if isinstance(old_final.get("health_reference"), dict)
            else None
        ),
        sleep_score_state_counts=score_counts,
    )
    if report_only and not is_approved_sleep_result_version(
        report.get("version"), quality.get("version")
    ):
        raise ValueError(
            "report-only would pair the current report contract with a stale "
            f"sleep_quality version for {session_id}; run a full rescore"
        )
    terminal_occupancy = terminal_occupancy_timeline(
        timeline,
        session_end=session["end_time"],
        sample_interval_s=sensor_sample_seconds,
    )
    now = datetime.now(timezone.utc).isoformat()
    if report_only:
        quality_hash = _canonical_sha256(previous_quality)
        previous_report = old_final.get("session_report") or {}
        previous_report_hash = _canonical_sha256(previous_report)
        new_report_hash = _canonical_sha256(report)
        old_final["session_report"] = report
        old_final["session_report_refreshed_at_utc"] = now
        if _canonical_sha256(
            (old_final.get("night_summary") or {}).get("sleep_quality")
        ) != quality_hash:
            raise RuntimeError("report-only changed persisted sleep_quality")
        audit = {
            "version": report.get("version"),
            "refreshed_at_utc": now,
            "report_only": True,
            "previous_report_version": previous_report.get("version"),
            "new_report_version": report.get("version"),
            "previous_report_sha256": previous_report_hash,
            "new_report_sha256": new_report_hash,
            "previous_report": previous_report,
            "report_refresh_scope": "full_derived_session_report",
            "quality_sha256_before": quality_hash,
            "quality_sha256_after": quality_hash,
            "score_preserved": quality.get("score"),
            "raw_sleep_stage_events_changed": False,
            "raw_timeline_changed": False,
        }
        return {
            "session_id": session_id,
            "final_event_id": final_row["id"],
            "final_summary": old_final,
            "audit": audit,
            "audit_event_type": "session_report_refreshed",
            "audit_timestamp": now,
            "status": "report_refreshed",
            "old_score": quality.get("score"),
            "new_score": quality.get("score"),
            "score_title": quality.get("score_title"),
            "estimated_sleep_s": quality.get("estimated_sleep_s"),
            "actual_scored_s": quality.get("actual_scored_s"),
            "rest_mode": report.get("rest_mode"),
            "quality": quality,
            "report": report,
            "rounds": total_scored,
            "counts": counts,
            "sleep_stage_annotations_used": len(annotations),
            "annotated_rounds": annotated_rounds,
        }
    old_final.update({
        "sleep_state_counts": counts,
        "sleep_score_state_counts": score_counts,
        "sleep_estimator": estimator_version,
        "sleep_estimator_versions": estimator_versions,
        "sleep_provenance_complete": bool(stage_rows) and sum(
            estimator_versions.values()) == len(stage_rows),
        "sleep_evidence_version": SLEEP_EVIDENCE_VERSION,
        "sleep_baseline_version": ZEEP_SLEEP_BASELINE_VERSION,
        "sleep_transition_policy": ZEEP_SLEEP_TRANSITION_POLICY_VERSION,
        "sleep_g2_ontology": SLEEP_G2_ONTOLOGY_VERSION,
        "rest_mode": mode,
        "target_duration_s": target.get("seconds"),
        "sample_interval_s": stage_sample_seconds,
        "sensor_sample_interval_s": sensor_sample_seconds,
        "sample_cadence_summary": projection["cadence_summary"],
        "report_sample_grid": projection["grid_summary"],
        "bed_status_counts": canonical_bed_status_counts,
        "terminal_occupancy_timeline": terminal_occupancy,
        "night_summary": night,
        "session_report": report,
        "quality_rescored_at_utc": now,
    })
    # One development-only Session previously carried a manually entered
    # seven-hour duration. Reports now use Sensor evidence exclusively.
    old_final.pop("user_report", None)
    audit = {
        "version": SLEEP_QUALITY_VERSION,
        "rescored_at_utc": now,
        "rest_mode": mode,
        "target_duration_s": target.get("seconds"),
        "rounds": total_scored,
        "raw_sleep_stage_events_changed": False,
        "sleep_stage_annotations_used": len(annotations),
        "annotated_rounds": annotated_rounds,
        "previous_quality": previous_quality,
        "new_quality": quality,
        "raw_bed_status_counts": raw_bed_status_counts,
        "canonical_bed_status_counts": canonical_bed_status_counts,
        "terminal_occupancy_periods": len(terminal_occupancy),
        "raw_timeline_changed": False,
    }
    return {
        "session_id": session_id,
        "final_event_id": final_row["id"],
        "final_summary": old_final,
        "audit": audit,
        "audit_event_type": "session_report_rescored",
        "audit_timestamp": now,
        "status": "rescored",
        "old_score": (previous_quality or {}).get("score"),
        "new_score": quality.get("score"),
        "score_title": quality.get("score_title"),
        "estimated_sleep_s": quality.get("estimated_sleep_s"),
        "actual_scored_s": quality.get("actual_scored_s"),
        "rest_mode": quality.get("rest_mode"),
        "quality": quality,
        "report": report,
        "rounds": total_scored,
        "counts": counts,
        "sleep_stage_annotations_used": len(annotations),
        "annotated_rounds": annotated_rounds,
    }


def rescore(
    data_dir: Path,
    session_ids: list[str] | None,
    *,
    requested_mode: str | None,
    apply: bool,
    requested_target_minutes: int | None = None,
    report_only: bool = False,
) -> Dict[str, Any]:
    if report_only and not session_ids:
        raise ValueError("--report-only requires one or more --session-id values")
    if report_only and (
        requested_mode is not None or requested_target_minutes is not None
    ):
        raise ValueError(
            "--report-only preserves Mode/target; do not pass overrides"
        )
    connection = sqlite3.connect(data_dir / "sessions.db", timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=30000")
    results = []
    try:
        # One apply request owns one SQLite transaction. If any rebuild or write
        # fails, every earlier Session in the selected cohort is rolled back.
        if apply:
            connection.execute("BEGIN IMMEDIATE")
        if session_ids:
            placeholders = ",".join("?" for _ in session_ids)
            sessions = connection.execute(
                f"SELECT * FROM sessions WHERE end_time IS NOT NULL AND session_id IN ({placeholders}) "
                "ORDER BY start_time", session_ids,
            ).fetchall()
        else:
            sessions = connection.execute(
                "SELECT * FROM sessions WHERE end_time IS NOT NULL ORDER BY start_time"
            ).fetchall()
        if session_ids and len(sessions) != len(set(session_ids)):
            found = {row["session_id"] for row in sessions}
            raise ValueError(
                f"completed Session not found: {sorted(set(session_ids) - found)}"
            )

        for session in sessions:
            try:
                rebuilt = _rebuild(
                    connection,
                    session,
                    requested_mode,
                    requested_target_minutes,
                    report_only=report_only,
                )
            except HistoricalModeReviewRequired as exc:
                results.append({
                    "session_id": session["session_id"],
                    "status": "skipped_review_required",
                    "reason_code": exc.code,
                    "reason": str(exc),
                    "persisted_record_unchanged": True,
                })
                continue
            results.append({key: rebuilt[key] for key in (
                "session_id", "status", "old_score", "new_score", "score_title",
                "estimated_sleep_s", "actual_scored_s", "rest_mode", "rounds", "counts",
                "quality", "report", "sleep_stage_annotations_used", "annotated_rounds")})
            if not apply:
                continue
            connection.execute(
                "UPDATE events SET value=? WHERE id=?",
                (json.dumps(rebuilt["final_summary"], ensure_ascii=False, separators=(",", ":")),
                 rebuilt["final_event_id"]),
            )
            connection.execute(
                "INSERT INTO events(session_id,timestamp,type,value) VALUES (?,?,?,?)",
                (rebuilt["session_id"], rebuilt["audit_timestamp"],
                 rebuilt["audit_event_type"],
                 json.dumps(rebuilt["audit"], ensure_ascii=False, separators=(",", ":"))),
            )
        if apply:
            connection.commit()
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise
    finally:
        connection.close()
    completed_count = sum("new_score" in item for item in results)
    return {
        "applied": apply,
        "version": SLEEP_QUALITY_VERSION,
        "operation": "report_only" if report_only else "rescore",
        "sessions": results,
        "count": len(results),
        "rescored_count": 0 if report_only else completed_count,
        "refreshed_count": completed_count if report_only else 0,
        "skipped_count": len(results) - completed_count,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--session-id", action="append", dest="session_ids")
    parser.add_argument("--all", action="store_true", help="Rescore every completed Session")
    parser.add_argument("--rest-mode", choices=(
        "auto", "sleep", "nap_recovery", "short_nap", "cycle_nap",
        "shift_rest", "jet_lag", "overnight"))
    parser.add_argument("--target-minutes", type=int, choices=(30, 90))
    parser.add_argument(
        "--report-only",
        action="store_true",
        help=(
            "Rebuild the full derived Session report for targeted IDs while "
            "preserving the persisted quality, score, Sleep State and Raw data"
        ),
    )
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not args.all and not args.session_ids:
        parser.error("provide --session-id (repeatable) or --all")
    result = rescore(
        args.data_dir, None if args.all else args.session_ids,
        requested_mode=args.rest_mode,
        requested_target_minutes=args.target_minutes,
        apply=args.apply,
        report_only=args.report_only,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
