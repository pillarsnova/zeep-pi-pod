#!/usr/bin/env python3
"""Trim a completed ZEEP Session at a verified local cutoff time.

This maintenance tool removes timeline/events/raw BCG at-or-after the cutoff,
repairs a BCG epoch that crosses the boundary, and regenerates final_summary
from the retained data. It intentionally does not create a data backup because
the operator is fulfilling a deletion/correction request.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

from sleep_session_report import build_session_report, build_sleep_quality
from sleep_system_policy import (
    SLEEP_EVIDENCE_EPOCH_SECONDS,
    ZEEP_OFF_BED_DATA_STATUSES,
)
from zeep_pod.sessions.report_projection import project_report_samples


MAINTENANCE_TOOL_NAME = "trim_session.py"
STAGES = ("wake", "n1", "n2", "n3", "rem")
SLEEP_STAGES = {"n1", "n2", "n3", "rem"}
LEGACY_SAMPLE_SECONDS = 5.0


def _iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp requires timezone: {value}")
    return parsed


def _cutoff_utc(value: str, timezone_name: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(timezone_name))
    return parsed.astimezone(timezone.utc)


def _stats(values: list[Any]) -> Optional[Dict[str, Any]]:
    numeric = [float(value) for value in values
               if isinstance(value, (int, float)) and not isinstance(value, bool)]
    if not numeric:
        return None
    return {
        "avg": round(sum(numeric) / len(numeric), 2),
        "min": round(min(numeric), 2),
        "max": round(max(numeric), 2),
        "n": len(numeric),
    }


def _load_json(value: Any) -> Dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


def _event_mappings(rows: list[sqlite3.Row]) -> list[Dict[str, Any]]:
    """Convert SQLite rows into the Mapping contract used by projection."""
    return [
        {"timestamp": row["timestamp"], "value": _load_json(row["value"])}
        for row in rows
    ]


def _positive_seconds(value: Any, fallback: float) -> float:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return fallback
    return seconds if seconds > 0 else fallback


def _night_summary_from_projection(
    samples: list[Dict[str, Any]],
    *,
    started_epoch: float,
    duration_s: float,
    sample_interval_s: float,
    score_counts: Dict[str, float],
) -> Dict[str, Any]:
    """Derive score inputs from the same complete stream as the report."""
    onset_s = None
    awakenings = 0
    asleep = False
    sleep_started = False
    waso_s = 0.0
    for sample in samples:
        status = str(sample.get("sleep_data_status") or "").lower()
        state = (
            "off_bed"
            if status in ZEEP_OFF_BED_DATA_STATUSES
            else sample.get("sleep")
            if sample.get("sleep_score_eligible") is not False
            else None
        )
        interval_s = _positive_seconds(
            sample.get("sample_interval_s"), sample_interval_s
        )
        if state in SLEEP_STAGES:
            if onset_s is None:
                onset_s = round(
                    max(
                        0.0,
                        float(sample["t"])
                        - interval_s
                        - started_epoch,
                    ),
                    1,
                )
            asleep = True
            sleep_started = True
        elif state in {"wake", "off_bed"}:
            if sleep_started:
                waso_s += interval_s
            if asleep:
                awakenings += 1
                asleep = False

    total_sleep = sum(score_counts.get(stage, 0.0) for stage in SLEEP_STAGES)
    total_scored = total_sleep + score_counts.get("wake", 0.0)
    return {
        "sleep_onset_proxy_s": onset_s,
        "awakenings": awakenings,
        "waso_proxy_s": round(waso_s, 1),
        "estimated_sleep_s": round(
            min(duration_s, total_sleep * sample_interval_s), 1
        ),
        "sleep_efficiency": (
            round(total_sleep / total_scored, 3) if total_scored else None
        ),
        "deep_ratio": (
            round(score_counts.get("n3", 0.0) / total_sleep, 3)
            if total_sleep
            else None
        ),
        "rem_ratio": (
            round(score_counts.get("rem", 0.0) / total_sleep, 3)
            if total_sleep
            else None
        ),
    }


def _snapshot(connection: sqlite3.Connection, session_id: str, cutoff: str) -> Dict[str, Any]:
    timeline_after = connection.execute(
        "SELECT COUNT(*) FROM timeline WHERE session_id=? AND timestamp>=?",
        (session_id, cutoff)).fetchone()[0]
    events_after = connection.execute(
        "SELECT COUNT(*) FROM events WHERE session_id=? AND timestamp>=?",
        (session_id, cutoff)).fetchone()[0]
    packets_after = connection.execute(
        "SELECT COUNT(*) FROM bcg.bcg_packets p JOIN bcg.bcg_epochs e ON e.epoch_id=p.epoch_id "
        "WHERE e.session_id=? AND p.timestamp>=?", (session_id, cutoff)).fetchone()[0]
    return {
        "timeline_after_cutoff": timeline_after,
        "events_after_cutoff": events_after,
        "bcg_packets_after_cutoff": packets_after,
        "timeline_total": connection.execute(
            "SELECT COUNT(*) FROM timeline WHERE session_id=?", (session_id,)).fetchone()[0],
        "sleep_stage_total": connection.execute(
            "SELECT COUNT(*) FROM events WHERE session_id=? AND type='sleep_stage'",
            (session_id,)).fetchone()[0],
        "bcg_packets_total": connection.execute(
            "SELECT COUNT(*) FROM bcg.bcg_packets p JOIN bcg.bcg_epochs e ON e.epoch_id=p.epoch_id "
            "WHERE e.session_id=?", (session_id,)).fetchone()[0],
    }


def _rebuild_final_summary(
    connection: sqlite3.Connection,
    session: sqlite3.Row,
    cutoff: datetime,
    old_final: Dict[str, Any],
    reason: str,
) -> Dict[str, Any]:
    session_id = session["session_id"]
    sensor_interval_s = _positive_seconds(
        old_final.get("sensor_sample_interval_s")
        or old_final.get("sample_interval_s"),
        LEGACY_SAMPLE_SECONDS,
    )
    timeline = connection.execute(
        "SELECT timestamp,temperature,humidity,co2,lux,sound,heart_rate,"
        "respiration_rate,bed_status FROM timeline WHERE session_id=? ORDER BY timestamp",
        (session_id,)).fetchall()
    stage_rows = connection.execute(
        "SELECT timestamp,value FROM events WHERE session_id=? AND type='sleep_stage' "
        "ORDER BY timestamp", (session_id,)).fetchall()
    status_rows = connection.execute(
        "SELECT timestamp,value FROM events WHERE session_id=? "
        "AND type='sleep_stage_status' ORDER BY timestamp",
        (session_id,),
    ).fetchall()

    stage_events = [
        event
        for event in _event_mappings(stage_rows)
        if event["value"].get("state") in STAGES
    ]
    status_events = _event_mappings(status_rows)
    estimator_version = old_final.get("sleep_estimator")
    for event in stage_events:
        value = event["value"]
        estimator_version = value.get("estimator_version") or estimator_version

    samples = []
    for row in timeline:
        bed = row["bed_status"]
        samples.append({
            "t": _iso(row["timestamp"]).timestamp(),
            "temp": row["temperature"], "hum": row["humidity"],
            "co2": row["co2"], "lux": row["lux"], "dba": row["sound"],
            "hr": row["heart_rate"], "rr": row["respiration_rate"],
            "bed": bed,
        })

    started = _iso(session["start_time"]).astimezone(timezone.utc)
    duration_s = max(0.0, (cutoff - started.astimezone(timezone.utc)).total_seconds())
    cadence_segments = old_final.get("sample_cadence_segments") or []
    projection = project_report_samples(
        samples,
        start_at=started.timestamp(),
        end_at=cutoff.timestamp(),
        cadence_segments=cadence_segments,
        sensor_interval_s=sensor_interval_s,
        decision_interval_s=SLEEP_EVIDENCE_EPOCH_SECONDS,
        stage_events=stage_events,
        status_events=status_events,
    )
    if not projection["grid_summary"]["classification_complete"]:
        raise RuntimeError(
            "trim report continuity invariant failed: unattributed recording time"
        )
    projected_samples = projection["samples"]
    report_samples = projection["report_samples"]
    report_interval_s = projection["report_interval_s"]
    counts = {
        stage: projection["sleep_state_counts"].get(stage, 0.0)
        for stage in STAGES
    }
    score_counts = {
        stage: projection["sleep_score_state_counts"].get(stage, 0.0)
        for stage in STAGES
    }
    bed_counts = projection["bed_status_counts"]
    night_summary = _night_summary_from_projection(
        projected_samples,
        started_epoch=started.timestamp(),
        duration_s=duration_s,
        sample_interval_s=sensor_interval_s,
        score_counts=score_counts,
    )
    rest_mode = old_final.get("rest_mode") or "auto"
    session_fields = set(session.keys())
    target_duration_s = old_final.get("target_duration_s")
    if target_duration_s is None and "target_duration_s" in session_fields:
        target_duration_s = session["target_duration_s"]
    sleep_quality = build_sleep_quality(
        duration_s, night_summary, counts, completed=True,
        rest_mode=rest_mode, stage_sequence=report_samples,
        sensor_samples=report_samples,
        sample_interval_s=report_interval_s,
        target_duration_s=target_duration_s,
        score_state_counts=score_counts,
    )
    night_summary["sleep_quality"] = sleep_quality
    night_summary["wellness_score"] = sleep_quality.get("score")
    report = build_session_report(
        duration_s, report_samples, night_summary, counts, sleep_quality,
        rest_mode=rest_mode,
        sample_interval_s=report_interval_s,
        estimator_version=estimator_version,
        completed=True,
        timeline_schema_version=int(old_final.get("timeline_schema_version") or 3),
        target_duration_s=target_duration_s,
        sleep_score_state_counts=score_counts,
    )

    counter_rows = connection.execute(
        "SELECT type,COUNT(*) AS n FROM events WHERE session_id=? "
        "AND type NOT IN ('final_summary') GROUP BY type", (session_id,)).fetchall()
    counters = {row["type"]: row["n"] for row in counter_rows}
    summary = {
        "bed_status_counts": bed_counts,
        "sleep_state_counts": counts,
        "sleep_score_state_counts": score_counts,
        "sleep_estimator": estimator_version,
        "rest_mode": rest_mode,
        "target_duration_s": target_duration_s,
        "sample_interval_s": report_interval_s,
        "sensor_sample_interval_s": sensor_interval_s,
        "sample_cadence_segments": cadence_segments,
        "sample_cadence_summary": projection["cadence_summary"],
        "report_sample_grid": projection["grid_summary"],
        "counters": counters,
        "armed_at_utc": old_final.get("armed_at_utc"),
        "bed_start_s": old_final.get("bed_start_s"),
        "night_summary": night_summary,
        "session_report": report,
        "manual_trim": {
            "cutoff_utc": cutoff.isoformat(),
            "reason": reason,
            "regenerated_at_utc": datetime.now(timezone.utc).isoformat(),
        },
    }
    return {
        "value": summary,
        "duration_s": round(duration_s, 1),
        "counts": counts,
        "score_counts": score_counts,
        "bed_counts": bed_counts,
        "timeline_rows": len(timeline),
        "stage_rows": len(stage_events),
        "projected_rows": len(projected_samples),
    }


def trim_session(
    data_dir: Path,
    session_id: str,
    cutoff: datetime,
    reason: str,
    *,
    apply: bool,
) -> Dict[str, Any]:
    sessions_path = data_dir / "sessions.db"
    bcg_path = data_dir / "bcg.db"
    connection = sqlite3.connect(sessions_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("ATTACH DATABASE ? AS bcg", (str(bcg_path),))
    cutoff_iso = cutoff.astimezone(timezone.utc).isoformat()
    try:
        session = connection.execute(
            "SELECT * FROM sessions WHERE session_id=?", (session_id,)).fetchone()
        if session is None:
            raise ValueError(f"session not found: {session_id}")
        start = _iso(session["start_time"]).astimezone(timezone.utc)
        end = _iso(session["end_time"]).astimezone(timezone.utc) if session["end_time"] else None
        if end is None:
            raise ValueError("refusing to trim an active Session")
        if not start < cutoff < end:
            raise ValueError(f"cutoff must be inside Session: {start.isoformat()} .. {end.isoformat()}")
        before = _snapshot(connection, session_id, cutoff_iso)
        if not apply:
            return {"applied": False, "session_id": session_id, "cutoff_utc": cutoff_iso,
                    "before": before}

        connection.execute("BEGIN IMMEDIATE")
        final_row = connection.execute(
            "SELECT value FROM events WHERE session_id=? AND type='final_summary' "
            "ORDER BY timestamp DESC LIMIT 1", (session_id,)).fetchone()
        old_final = _load_json(final_row["value"] if final_row else None)

        affected = connection.execute(
            "SELECT DISTINCT e.epoch_id,e.packet_count,e.sample_count,e.tx_label "
            "FROM bcg.bcg_epochs e JOIN bcg.bcg_packets p ON p.epoch_id=e.epoch_id "
            "WHERE e.session_id=? AND p.timestamp>=?", (session_id, cutoff_iso)).fetchall()
        connection.execute(
            "DELETE FROM timeline WHERE session_id=? AND timestamp>=?", (session_id, cutoff_iso))
        connection.execute(
            "DELETE FROM events WHERE session_id=? AND timestamp>=?", (session_id, cutoff_iso))
        connection.execute(
            "DELETE FROM bcg.bcg_packets WHERE id IN ("
            "SELECT p.id FROM bcg.bcg_packets p JOIN bcg.bcg_epochs e ON e.epoch_id=p.epoch_id "
            "WHERE e.session_id=? AND p.timestamp>=?)", (session_id, cutoff_iso))
        connection.execute(
            "DELETE FROM bcg.bcg_epochs WHERE session_id=? AND NOT EXISTS ("
            "SELECT 1 FROM bcg.bcg_packets p WHERE p.epoch_id=bcg.bcg_epochs.epoch_id)",
            (session_id,))
        for epoch in affected:
            remaining = connection.execute(
                "SELECT COUNT(*) AS n,MAX(timestamp) AS end_time,AVG(heart_rate) AS hr,"
                "AVG(respiration_rate) AS rr FROM bcg.bcg_packets WHERE epoch_id=?",
                (epoch["epoch_id"],)).fetchone()
            if not remaining["n"]:
                continue
            samples_per_packet = max(1, round(epoch["sample_count"] / epoch["packet_count"]))
            label = epoch["tx_label"]
            if remaining["n"] < epoch["packet_count"] and not label.endswith("_partial"):
                label += "_partial"
            connection.execute(
                "UPDATE bcg.bcg_epochs SET tx_label=?,end_time=?,packet_count=?,sample_count=?,"
                "average_hr=?,average_rr=? WHERE epoch_id=?",
                (label, remaining["end_time"], remaining["n"],
                 remaining["n"] * samples_per_packet, remaining["hr"], remaining["rr"],
                 epoch["epoch_id"]),
            )

        rebuilt = _rebuild_final_summary(connection, session, cutoff, old_final, reason)
        connection.execute(
            "UPDATE sessions SET end_time=?,duration=?,end_reason=?,note=? WHERE session_id=?",
            (cutoff_iso, rebuilt["duration_s"], reason,
             f"Session trimmed at {cutoff_iso}: {reason}", session_id),
        )
        connection.execute(
            "INSERT INTO events(session_id,timestamp,type,value) VALUES (?,?,?,?)",
            (session_id, cutoff_iso, "final_summary",
             json.dumps(rebuilt["value"], ensure_ascii=False, separators=(",", ":"))),
        )
        connection.commit()
        after = _snapshot(connection, session_id, cutoff_iso)
        return {
            "applied": True, "session_id": session_id, "cutoff_utc": cutoff_iso,
            "duration_s": rebuilt["duration_s"], "sleep_state_counts": rebuilt["counts"],
            "sleep_score_state_counts": rebuilt["score_counts"],
            "timeline_rows": rebuilt["timeline_rows"], "stage_rows": rebuilt["stage_rows"],
            "before": before, "after": after,
        }
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--cutoff", required=True,
                        help="Local ISO time, e.g. 2026-08-26T09:07:00")
    parser.add_argument("--timezone", default="Asia/Bangkok")
    parser.add_argument("--reason", default="manual_end_awake_battery_depleted")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = trim_session(
        Path(args.data_dir), args.session_id,
        _cutoff_utc(args.cutoff, args.timezone), args.reason, apply=args.apply)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
