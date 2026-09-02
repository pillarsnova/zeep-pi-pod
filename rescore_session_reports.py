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
import json
from pathlib import Path
import sqlite3
from typing import Any, Dict

from sleep_session_report import (
    SLEEP_QUALITY_VERSION,
    build_session_report,
    build_sleep_quality,
    normalise_rest_mode,
)
from sleep_system_policy import (
    SLEEP_EVIDENCE_VERSION,
    SLEEP_G2_ONTOLOGY_VERSION,
    ZEEP_SLEEP_BASELINE_VERSION,
    ZEEP_SLEEP_TRANSITION_POLICY_VERSION,
)
from sleep_stage_annotations import apply_annotations, load_annotations
from sleep_signal_features import (
    debounced_bed_status_labels,
    terminal_occupancy_timeline,
)


MAINTENANCE_TOOL_NAME = "rescore_session_reports.py"
STAGES = ("wake", "n1", "n2", "n3", "rem")
SLEEP_STAGES = {"n1", "n2", "n3", "rem"}
LEGACY_SAMPLE_SECONDS = 5.0


def _json(value: Any) -> Dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _rebuild(connection: sqlite3.Connection, session: sqlite3.Row,
             requested_mode: str | None) -> Dict[str, Any]:
    session_id = session["session_id"]
    final_row = connection.execute(
        "SELECT id,value FROM events WHERE session_id=? AND type='final_summary' "
        "ORDER BY timestamp DESC,id DESC LIMIT 1", (session_id,),
    ).fetchone()
    if final_row is None:
        raise ValueError(f"completed Session has no final_summary: {session_id}")
    old_final = _json(final_row["value"])
    sample_seconds = float(old_final.get("sample_interval_s") or LEGACY_SAMPLE_SECONDS)
    if sample_seconds <= 0:
        sample_seconds = LEGACY_SAMPLE_SECONDS
    mode = normalise_rest_mode(requested_mode or old_final.get("rest_mode") or "auto")

    stage_rows = connection.execute(
        "SELECT timestamp,value FROM events WHERE session_id=? AND type='sleep_stage' "
        "ORDER BY timestamp,id", (session_id,),
    ).fetchall()
    annotation_rows = connection.execute(
        "SELECT value FROM events WHERE session_id=? AND type='sleep_stage_annotation' "
        "ORDER BY timestamp,id", (session_id,),
    ).fetchall()
    annotations = load_annotations(annotation_rows)
    annotated_rounds = 0
    counts = {stage: 0 for stage in STAGES}
    sequence: list[Dict[str, Any]] = []
    stage_by_bucket: Dict[int, Dict[str, Any]] = {}
    estimator_version = old_final.get("sleep_estimator")
    estimator_versions: Dict[str, int] = {}
    first_sleep_at = None
    awakenings = 0
    waso_rounds = 0
    asleep = False
    sleep_started = False
    for row in stage_rows:
        value = _json(row["value"])
        value, annotation = apply_annotations(
            value, row["timestamp"], annotations,
            sample_interval_s=float(value.get("sample_interval_s") or sample_seconds),
        )
        if annotation is not None:
            annotated_rounds += 1
        stage = value.get("state")
        if stage not in counts:
            continue
        counts[stage] += 1
        sequence.append({"state": stage, "metrics": value.get("metrics") or {}})
        estimator_version = value.get("estimator_version") or estimator_version
        if value.get("estimator_version"):
            version = str(value["estimator_version"])
            estimator_versions[version] = estimator_versions.get(version, 0) + 1
        when = _timestamp(row["timestamp"])
        if stage in SLEEP_STAGES:
            if first_sleep_at is None:
                first_sleep_at = when
            asleep = True
            sleep_started = True
        elif stage == "wake":
            if sleep_started:
                waso_rounds += 1
            if asleep:
                awakenings += 1
                asleep = False
        auxiliary = ((value.get("metrics") or {}).get("auxiliary_evidence") or {})
        acoustic = auxiliary.get("acoustic") or {}
        stage_by_bucket[int(when.timestamp() // sample_seconds)] = {
            "sleep": stage,
            "sleep_confidence": value.get("confidence"),
            "acoustic_corroborated": bool(acoustic.get("corroborated")),
        }

    timeline = connection.execute(
        "SELECT timestamp,temperature,humidity,co2,lux,sound,heart_rate,"
        "respiration_rate,bed_status FROM timeline WHERE session_id=? ORDER BY timestamp,id",
        (session_id,),
    ).fetchall()
    canonical_bed_labels = debounced_bed_status_labels(
        [row["bed_status"] for row in timeline])
    raw_bed_status_counts: Dict[str, int] = {}
    canonical_bed_status_counts: Dict[str, int] = {}
    samples = []
    for row, canonical_bed in zip(timeline, canonical_bed_labels):
        when = _timestamp(row["timestamp"])
        raw_bed = str(row["bed_status"] or "")
        if raw_bed:
            raw_bed_status_counts[raw_bed] = raw_bed_status_counts.get(raw_bed, 0) + 1
        if canonical_bed:
            canonical_bed_status_counts[canonical_bed] = (
                canonical_bed_status_counts.get(canonical_bed, 0) + 1
            )
        samples.append({
            "t": when.timestamp(), "temp": row["temperature"], "hum": row["humidity"],
            "co2": row["co2"], "lux": row["lux"], "dba": row["sound"],
            "hr": row["heart_rate"], "rr": row["respiration_rate"],
            # Report/quality functions apply the shared debounce helper and
            # retain the rejected count for Admin audit. User history is
            # canonicalised independently by the read API.
            "bed": raw_bed,
            **stage_by_bucket.get(int(when.timestamp() // sample_seconds), {}),
        })

    duration_s = max(0.0, float(session["duration"] or 0.0))
    start = _timestamp(session["start_time"])
    total_sleep = sum(counts[stage] for stage in SLEEP_STAGES)
    total_scored = total_sleep + counts["wake"]
    night = dict(old_final.get("night_summary") or {})
    night.update({
        "sleep_onset_proxy_s": (
            round(max(0.0, (first_sleep_at - start).total_seconds()), 1)
            if first_sleep_at else None
        ),
        "awakenings": awakenings,
        "waso_proxy_s": round(waso_rounds * sample_seconds, 1),
        "estimated_sleep_s": round(total_sleep * sample_seconds, 1),
        "sleep_efficiency": round(total_sleep / total_scored, 3) if total_scored else None,
        "deep_ratio": round(counts["n3"] / total_sleep, 3) if total_sleep else None,
        "rem_ratio": round(counts["rem"] / total_sleep, 3) if total_sleep else None,
    })
    quality = build_sleep_quality(
        duration_s, night, counts, completed=True, rest_mode=mode,
        stage_sequence=sequence, sensor_samples=samples,
        sample_interval_s=sample_seconds,
    )
    night["sleep_quality"] = quality
    night["wellness_score"] = quality.get("score")
    report = build_session_report(
        duration_s, samples, night, counts, quality,
        rest_mode=mode,
        sample_interval_s=sample_seconds, estimator_version=estimator_version,
        completed=True,
        timeline_schema_version=int(old_final.get("timeline_schema_version") or 3),
    )
    terminal_occupancy = terminal_occupancy_timeline(
        timeline,
        session_end=session["end_time"],
        sample_interval_s=sample_seconds,
    )
    now = datetime.now(timezone.utc).isoformat()
    previous_quality = (old_final.get("night_summary") or {}).get("sleep_quality")
    old_final.update({
        "sleep_state_counts": counts,
        "sleep_estimator": estimator_version,
        "sleep_estimator_versions": estimator_versions,
        "sleep_provenance_complete": bool(stage_rows) and sum(
            estimator_versions.values()) == len(stage_rows),
        "sleep_evidence_version": SLEEP_EVIDENCE_VERSION,
        "sleep_baseline_version": ZEEP_SLEEP_BASELINE_VERSION,
        "sleep_transition_policy": ZEEP_SLEEP_TRANSITION_POLICY_VERSION,
        "sleep_g2_ontology": SLEEP_G2_ONTOLOGY_VERSION,
        "rest_mode": mode,
        "sample_interval_s": sample_seconds,
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
        "old_score": (previous_quality or {}).get("score"),
        "new_score": quality.get("score"),
        "rest_mode": quality.get("rest_mode"),
        "rounds": total_scored,
        "counts": counts,
        "sleep_stage_annotations_used": len(annotations),
        "annotated_rounds": annotated_rounds,
    }


def rescore(data_dir: Path, session_ids: list[str] | None, *,
            requested_mode: str | None, apply: bool) -> Dict[str, Any]:
    connection = sqlite3.connect(data_dir / "sessions.db", timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=30000")
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
        raise ValueError(f"completed Session not found: {sorted(set(session_ids) - found)}")

    results = []
    try:
        for session in sessions:
            rebuilt = _rebuild(connection, session, requested_mode)
            results.append({key: rebuilt[key] for key in (
                "session_id", "old_score", "new_score", "rest_mode", "rounds", "counts",
                "sleep_stage_annotations_used", "annotated_rounds")})
            if not apply:
                continue
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "UPDATE events SET value=? WHERE id=?",
                (json.dumps(rebuilt["final_summary"], ensure_ascii=False, separators=(",", ":")),
                 rebuilt["final_event_id"]),
            )
            connection.execute(
                "INSERT INTO events(session_id,timestamp,type,value) VALUES (?,?,?,?)",
                (rebuilt["session_id"], rebuilt["audit"]["rescored_at_utc"],
                 "session_report_rescored",
                 json.dumps(rebuilt["audit"], ensure_ascii=False, separators=(",", ":"))),
            )
            connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return {"applied": apply, "version": SLEEP_QUALITY_VERSION,
            "sessions": results, "count": len(results)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--session-id", action="append", dest="session_ids")
    parser.add_argument("--all", action="store_true", help="Rescore every completed Session")
    parser.add_argument("--rest-mode", choices=(
        "auto", "short_nap", "cycle_nap", "shift_rest", "jet_lag", "overnight"))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not args.all and not args.session_ids:
        parser.error("provide --session-id (repeatable) or --all")
    result = rescore(
        args.data_dir, None if args.all else args.session_ids,
        requested_mode=args.rest_mode, apply=args.apply,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
