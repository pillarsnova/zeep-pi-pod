#!/usr/bin/env python3
"""Add an auditable Sleep State annotation and rebuild one Session report.

Run without ``--apply`` first. Applying creates an online SQLite backup,
inserts a separate annotation event, and rebuilds only the selected Session's
derived final summary. Raw BCG, timeline rows and original ``sleep_stage``
events are never rewritten.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any

from rescore_session_reports import _rebuild
from sleep_stage_annotations import (
    ANNOTATION_EVENT_TYPE,
    apply_annotations,
    build_annotation,
    load_annotations,
    parse_timestamp,
)


MAINTENANCE_TOOL_NAME = "annotate_sleep_stage.py"


def annotate(
    data_dir: Path,
    session_id: str,
    *,
    state: str,
    start_time: str,
    end_time: str,
    source: str,
    reason: str,
    created_by: str,
    supersede_overlapping: bool,
    apply: bool,
) -> dict[str, Any]:
    data_dir = data_dir.resolve()
    database_path = data_dir / "sessions.db"
    connection = sqlite3.connect(database_path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=30000")
    session = connection.execute(
        "SELECT * FROM sessions WHERE session_id=? AND end_time IS NOT NULL",
        (session_id,),
    ).fetchone()
    if session is None:
        connection.close()
        raise ValueError(f"completed Session not found: {session_id}")
    annotation = build_annotation(
        state=state,
        start_time=start_time,
        end_time=end_time,
        source=source,
        reason=reason,
        created_by=created_by,
    )
    existing_rows = connection.execute(
        "SELECT id,value FROM events WHERE session_id=? AND type=? ORDER BY timestamp,id",
        (session_id, ANNOTATION_EVENT_TYPE),
    ).fetchall()
    annotation_start = parse_timestamp(annotation["start_time"])
    annotation_end = parse_timestamp(annotation["end_time"])
    overlapping_rows: list[tuple[int, dict[str, Any]]] = []
    for row in existing_rows:
        try:
            value = json.loads(row["value"] or "{}")
            if str(value.get("status") or "active").lower() != "active":
                continue
            existing_start = parse_timestamp(value["start_time"])
            existing_end = parse_timestamp(value["end_time"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue
        if existing_start < annotation_end and annotation_start < existing_end:
            overlapping_rows.append((int(row["id"]), value))
    session_start = parse_timestamp(session["start_time"])
    session_end = parse_timestamp(session["end_time"])
    if (parse_timestamp(annotation["start_time"]) < session_start
            or parse_timestamp(annotation["end_time"]) > session_end):
        connection.close()
        raise ValueError("annotation interval must be inside the completed Session")

    stage_rows = connection.execute(
        "SELECT timestamp,value FROM events WHERE session_id=? AND type='sleep_stage' "
        "ORDER BY timestamp,id", (session_id,),
    ).fetchall()
    annotations = load_annotations([{"value": json.dumps(annotation)}])
    affected = []
    transitions: Counter[str] = Counter()
    for row in stage_rows:
        try:
            value = json.loads(row["value"] or "{}")
        except (TypeError, json.JSONDecodeError):
            continue
        updated, matched = apply_annotations(value, row["timestamp"], annotations)
        if matched is None:
            continue
        affected.append(row["timestamp"])
        transitions[f"{value.get('state')}->{updated.get('state')}"] += 1
    if not affected:
        connection.close()
        raise ValueError("annotation interval does not cover a Sleep State round")

    result: dict[str, Any] = {
        "status": "applied" if apply else "dry_run",
        "session_id": session_id,
        "annotation": annotation,
        "affected_rounds": len(affected),
        "first_affected_round": affected[0],
        "last_affected_round": affected[-1],
        "changes": dict(sorted(transitions.items())),
        "raw_sleep_stage_events_changed": False,
        "overlapping_active_annotation_ids": [row_id for row_id, _ in overlapping_rows],
        "supersede_overlapping": bool(supersede_overlapping),
        "backup": None,
    }
    if not apply:
        connection.close()
        return result
    if overlapping_rows and not supersede_overlapping:
        connection.close()
        raise ValueError(
            "active annotation overlaps this interval; inspect dry-run and pass "
            "--supersede-overlapping to retain it as superseded audit history"
        )

    backup_dir = data_dir.parent / "backup"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = backup_dir / f"sessions-pre-stage-annotation-{stamp}.db"
    backup = sqlite3.connect(backup_path)
    try:
        connection.backup(backup)
    finally:
        backup.close()
    result["backup"] = str(backup_path)

    try:
        connection.execute("BEGIN IMMEDIATE")
        for event_id, old_value in overlapping_rows:
            superseded = {
                **old_value,
                "status": "superseded",
                "superseded_at_utc": annotation["created_at_utc"],
                "superseded_by": {
                    "state": annotation["state"],
                    "start_time": annotation["start_time"],
                    "end_time": annotation["end_time"],
                    "source": annotation["source"],
                },
            }
            connection.execute(
                "UPDATE events SET value=? WHERE id=?",
                (json.dumps(superseded, ensure_ascii=False, separators=(",", ":")), event_id),
            )
        connection.execute(
            "INSERT INTO events(session_id,timestamp,type,value) VALUES (?,?,?,?)",
            (
                session_id,
                annotation["created_at_utc"],
                ANNOTATION_EVENT_TYPE,
                json.dumps(annotation, ensure_ascii=False, separators=(",", ":")),
            ),
        )
        rebuilt = _rebuild(connection, session, None)
        connection.execute(
            "UPDATE events SET value=? WHERE id=?",
            (
                json.dumps(
                    rebuilt["final_summary"], ensure_ascii=False, separators=(",", ":")
                ),
                rebuilt["final_event_id"],
            ),
        )
        connection.execute(
            "INSERT INTO events(session_id,timestamp,type,value) VALUES (?,?,?,?)",
            (
                session_id,
                rebuilt["audit"]["rescored_at_utc"],
                "session_report_rescored",
                json.dumps(rebuilt["audit"], ensure_ascii=False, separators=(",", ":")),
            ),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    result.update({
        "old_score": rebuilt["old_score"],
        "new_score": rebuilt["new_score"],
        "new_counts": rebuilt["counts"],
        "superseded_annotation_ids": [row_id for row_id, _ in overlapping_rows],
    })
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--state", default="wake", choices=("wake", "n1", "n2", "n3", "rem"))
    parser.add_argument("--start-time", required=True)
    parser.add_argument("--end-time", required=True)
    parser.add_argument("--source", default="user_reported_ground_truth")
    parser.add_argument("--reason", required=True)
    parser.add_argument("--created-by", default="admin")
    parser.add_argument(
        "--supersede-overlapping", action="store_true",
        help="Mark active overlapping annotations as superseded before inserting this one",
    )
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = annotate(
        args.data_dir,
        args.session_id,
        state=args.state,
        start_time=args.start_time,
        end_time=args.end_time,
        source=args.source,
        reason=args.reason,
        created_by=args.created_by,
        supersede_overlapping=args.supersede_overlapping,
        apply=args.apply,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
