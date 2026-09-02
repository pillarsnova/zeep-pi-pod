"""One-time, non-destructive sessions.jsonl to sessions.db migration."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from database import DatabaseManager


def _iso_from_sample(value: Any) -> str:
    try:
        return datetime.fromtimestamp(float(value), timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return datetime.now(timezone.utc).isoformat()


def migrate_jsonl(database: DatabaseManager, source: Path) -> dict[str, Any]:
    """Import every valid legacy record atomically, then rename the source."""
    if not source.exists():
        return {"status": "not_found", "imported": 0}
    records: list[dict[str, Any]] = []
    with source.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"sessions.jsonl line {line_number} is invalid: {exc}") from exc
            if not isinstance(record, dict) or not record.get("session_id"):
                raise RuntimeError(f"sessions.jsonl line {line_number} has no session_id")
            records.append(record)

    connection = DatabaseManager._connect(database.sessions_path)
    imported = 0
    try:
        connection.execute("BEGIN IMMEDIATE")
        for record in records:
            cursor = connection.execute(
                """INSERT OR IGNORE INTO sessions
                   (session_id,user,username_key,gender,start_time,end_time,duration,note,
                    end_reason,created_at,schema_version) VALUES (?,?,?,?,?,?,?,?,?,?,2)""",
                (record["session_id"], record.get("username") or "Unknown",
                 record.get("username_key") or str(record.get("username", "Unknown")).casefold(),
                 record.get("gender"), record.get("started_at_utc") or _iso_from_sample(None),
                 record.get("ended_at_utc"), record.get("duration_s"), record.get("note"),
                 record.get("end_reason"), record.get("started_at_utc") or _iso_from_sample(None)),
            )
            if not cursor.rowcount:
                continue
            imported += 1
            for sample in record.get("samples") or []:
                connection.execute(
                    """INSERT INTO timeline
                       (session_id,timestamp,temperature,humidity,co2,pm2_5,voc_index,
                        lux,sound,heart_rate,respiration_rate,bed_status)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (record["session_id"], _iso_from_sample(sample.get("t")), sample.get("temp"),
                     sample.get("hum"), sample.get("co2"), sample.get("pm2_5"),
                     sample.get("voc"), sample.get("lux"), sample.get("dba"),
                     sample.get("hr"), sample.get("rr"), sample.get("bed")),
                )
            for event_type, count in (record.get("counters") or {}).items():
                connection.execute(
                    "INSERT INTO events(session_id,timestamp,type,value) VALUES (?,?,?,?)",
                    (record["session_id"], record.get("ended_at_utc") or record.get("started_at_utc"),
                     f"legacy_counter:{event_type}", str(count)),
                )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    backup = source.with_name(source.name + ".bak")
    if backup.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = source.with_name(f"{source.name}.{stamp}.bak")
    source.replace(backup)
    return {"status": "migrated", "imported": imported, "backup": str(backup)}
