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
    sample_seconds = float(old_final.get("sample_interval_s") or LEGACY_SAMPLE_SECONDS)
    if sample_seconds <= 0:
        sample_seconds = LEGACY_SAMPLE_SECONDS
    timeline = connection.execute(
        "SELECT timestamp,temperature,humidity,co2,lux,sound,heart_rate,"
        "respiration_rate,bed_status FROM timeline WHERE session_id=? ORDER BY timestamp",
        (session_id,)).fetchall()
    stage_rows = connection.execute(
        "SELECT timestamp,value FROM events WHERE session_id=? AND type='sleep_stage' "
        "ORDER BY timestamp", (session_id,)).fetchall()

    stage_points = []
    counts = {stage: 0 for stage in STAGES}
    estimator_version = old_final.get("sleep_estimator")
    for row in stage_rows:
        value = _load_json(row["value"])
        stage = value.get("state")
        if stage not in counts:
            continue
        counts[stage] += 1
        estimator_version = value.get("estimator_version") or estimator_version
        stage_points.append((row["timestamp"], stage, value))

    stage_by_bucket = {}
    for timestamp, stage, value in stage_points:
        bucket = int(_iso(timestamp).timestamp() // sample_seconds)
        auxiliary = ((value.get("metrics") or {}).get("auxiliary_evidence") or {})
        acoustic = auxiliary.get("acoustic") or {}
        stage_by_bucket[bucket] = {
            "sleep": stage,
            "sleep_confidence": value.get("confidence"),
            "acoustic_corroborated": bool(acoustic.get("corroborated")),
        }

    samples = []
    bed_counts: Dict[str, int] = {}
    for row in timeline:
        bed = row["bed_status"]
        if bed:
            bed_counts[bed] = bed_counts.get(bed, 0) + 1
        bucket = int(_iso(row["timestamp"]).timestamp() // sample_seconds)
        samples.append({
            "t": _iso(row["timestamp"]).timestamp(),
            "temp": row["temperature"], "hum": row["humidity"],
            "co2": row["co2"], "lux": row["lux"], "dba": row["sound"],
            "hr": row["heart_rate"], "rr": row["respiration_rate"],
            "bed": bed, **stage_by_bucket.get(bucket, {}),
        })

    started = _iso(session["start_time"])
    duration_s = max(0.0, (cutoff - started.astimezone(timezone.utc)).total_seconds())
    first_sleep = next(
        (_iso(timestamp) for timestamp, stage, _ in stage_points if stage in SLEEP_STAGES), None)
    onset_s = round(max(0.0, (first_sleep - started).total_seconds()), 1) if first_sleep else None
    awakenings = 0
    asleep = False
    sleep_started = False
    waso_rounds = 0
    for _, stage, _ in stage_points:
        if stage in SLEEP_STAGES:
            asleep = True
            sleep_started = True
        elif stage == "wake":
            if sleep_started:
                waso_rounds += 1
            if asleep:
                awakenings += 1
                asleep = False
    total_sleep = sum(counts[stage] for stage in SLEEP_STAGES)
    total_scored = total_sleep + counts["wake"]
    night_summary = {
        "sleep_onset_proxy_s": onset_s,
        "awakenings": awakenings,
        "waso_proxy_s": round(waso_rounds * sample_seconds, 1),
        "estimated_sleep_s": round(min(duration_s, total_sleep * sample_seconds), 1),
        "sleep_efficiency": round(total_sleep / total_scored, 3) if total_scored else None,
        "deep_ratio": round(counts["n3"] / total_sleep, 3) if total_sleep else None,
        "rem_ratio": round(counts["rem"] / total_sleep, 3) if total_sleep else None,
    }
    rest_mode = old_final.get("rest_mode") or "auto"
    stage_sequence = [
        {"state": stage, "metrics": value.get("metrics") or {}}
        for _, stage, value in stage_points
    ]
    sleep_quality = build_sleep_quality(
        duration_s, night_summary, counts, completed=True,
        rest_mode=rest_mode, stage_sequence=stage_sequence,
        sample_interval_s=sample_seconds,
    )
    night_summary["sleep_quality"] = sleep_quality
    night_summary["wellness_score"] = sleep_quality.get("score")
    report = build_session_report(
        duration_s, samples, night_summary, counts, sleep_quality,
        rest_mode=rest_mode,
        sample_interval_s=sample_seconds, estimator_version=estimator_version,
        completed=True,
        timeline_schema_version=int(old_final.get("timeline_schema_version") or 3))

    counter_rows = connection.execute(
        "SELECT type,COUNT(*) AS n FROM events WHERE session_id=? "
        "AND type NOT IN ('final_summary') GROUP BY type", (session_id,)).fetchall()
    counters = {row["type"]: row["n"] for row in counter_rows}
    summary = {
        "bed_status_counts": bed_counts,
        "sleep_state_counts": counts,
        "sleep_estimator": estimator_version,
        "rest_mode": rest_mode,
        "sample_interval_s": sample_seconds,
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
    return {"value": summary, "duration_s": round(duration_s, 1), "counts": counts,
            "bed_counts": bed_counts, "timeline_rows": len(timeline),
            "stage_rows": len(stage_points)}


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
