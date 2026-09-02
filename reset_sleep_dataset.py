"""Offline reset of Pod sleep data while retaining one active user's new run.

The service must be stopped before this utility runs. It creates fresh SQLite
files, keeps only the selected open session from the requested timestamp, and
rebuilds raw BCG packets as one-minute tx1, tx2, ... windows. Authentication,
occupancy, output labels, and hardware calibration are intentionally untouched.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from statistics import mean
from zoneinfo import ZoneInfo


MAINTENANCE_TOOL_NAME = "reset_sleep_dataset.py"
CONFIRMATION = "DELETE-ALL-SLEEP-DATA"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--start-local", required=True, help="YYYY-MM-DDTHH:MM:SS")
    parser.add_argument("--end-local", required=True, help="YYYY-MM-DDTHH:MM:SS")
    parser.add_argument("--timezone", default="Asia/Bangkok")
    parser.add_argument("--tx-packets", type=int, default=60)
    parser.add_argument("--confirm", required=True)
    return parser.parse_args()


def utc_iso(local_text: str, timezone_name: str) -> str:
    local = datetime.fromisoformat(local_text).replace(tzinfo=ZoneInfo(timezone_name))
    return local.astimezone(ZoneInfo("UTC")).isoformat()


def rows(connection: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict]:
    connection.row_factory = sqlite3.Row
    return [dict(row) for row in connection.execute(sql, params).fetchall()]


def insert_dict(connection: sqlite3.Connection, table: str, row: dict) -> None:
    columns = list(row)
    placeholders = ",".join("?" for _ in columns)
    connection.execute(
        f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})",
        tuple(row[column] for column in columns),
    )


def positive_average(values: list[object]) -> float | None:
    valid = [float(value) for value in values if isinstance(value, (int, float)) and value > 0]
    return round(mean(valid), 2) if valid else None


def fresh_database(path: Path, schema_path: Path) -> sqlite3.Connection:
    path.unlink(missing_ok=True)
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys=ON")
    connection.executescript(schema_path.read_text(encoding="utf-8"))
    return connection


def atomic_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".reset-new")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def main() -> None:
    args = parse_args()
    if args.confirm != CONFIRMATION:
        raise SystemExit(f"Refusing destructive reset: --confirm must equal {CONFIRMATION}")
    if args.tx_packets <= 0:
        raise SystemExit("--tx-packets must be positive")

    base = Path(__file__).resolve().parent
    data_dir = args.data_dir.resolve()
    start_utc = utc_iso(args.start_local, args.timezone)
    end_utc = utc_iso(args.end_local, args.timezone)
    if end_utc <= start_utc:
        raise SystemExit("tx1 end must be later than start")

    sessions_path = data_dir / "sessions.db"
    bcg_path = data_dir / "bcg.db"
    source_sessions = sqlite3.connect(f"file:{sessions_path}?mode=ro", uri=True)
    source_bcg = sqlite3.connect(f"file:{bcg_path}?mode=ro", uri=True)
    source_sessions.row_factory = sqlite3.Row
    source_bcg.row_factory = sqlite3.Row

    selected = rows(
        source_sessions,
        "SELECT * FROM sessions WHERE session_id=? AND end_time IS NULL",
        (args.session_id,),
    )
    if len(selected) != 1:
        raise SystemExit("Selected session is missing, closed, or ambiguous")
    session = selected[0]

    tx1_packets = rows(
        source_bcg,
        """SELECT p.* FROM bcg_packets p
           JOIN bcg_epochs e ON e.epoch_id=p.epoch_id
           WHERE e.session_id=? AND p.timestamp>=? AND p.timestamp<?
           ORDER BY p.timestamp,p.id""",
        (args.session_id, start_utc, end_utc),
    )
    if len(tx1_packets) != args.tx_packets:
        raise SystemExit(
            f"tx1 validation failed: expected {args.tx_packets} packets, found {len(tx1_packets)}"
        )

    kept_timeline = rows(
        source_sessions,
        "SELECT * FROM timeline WHERE session_id=? AND timestamp>=? ORDER BY timestamp,id",
        (args.session_id, start_utc),
    )
    kept_events = rows(
        source_sessions,
        "SELECT * FROM events WHERE session_id=? AND timestamp>=? ORDER BY timestamp,id",
        (args.session_id, start_utc),
    )
    kept_packets = rows(
        source_bcg,
        """SELECT p.* FROM bcg_packets p
           JOIN bcg_epochs e ON e.epoch_id=p.epoch_id
           WHERE e.session_id=? AND p.timestamp>=?
           ORDER BY p.timestamp,p.id""",
        (args.session_id, start_utc),
    )

    sessions_new_path = data_dir / "sessions.reset-new.db"
    bcg_new_path = data_dir / "bcg.reset-new.db"
    target_sessions = fresh_database(sessions_new_path, base / "schema.sql")
    target_bcg = fresh_database(bcg_new_path, base / "bcg_schema.sql")

    session.pop("id", None)
    session.update({
        "start_time": start_utc,
        "created_at": start_utc,
        "end_time": None,
        "duration": None,
        "note": f"Fresh dataset; tx1 {args.start_local}–{args.end_local} {args.timezone}",
        "end_reason": None,
        "schema_version": 3,
    })
    insert_dict(target_sessions, "sessions", session)
    for row in kept_timeline:
        row.pop("id", None)
        insert_dict(target_sessions, "timeline", row)
    for row in kept_events:
        row.pop("id", None)
        insert_dict(target_sessions, "events", row)

    tx1_event = {
        "session_id": args.session_id,
        "timestamp": start_utc,
        "type": "tx_interval",
        "value": json.dumps({
            "tx_label": "tx1",
            "local_start": args.start_local,
            "local_end": args.end_local,
            "timezone": args.timezone,
            "packet_count": len(tx1_packets),
            "first_packet_utc": tx1_packets[0]["timestamp"],
            "last_packet_utc": tx1_packets[-1]["timestamp"],
        }, ensure_ascii=False, separators=(",", ":")),
    }
    insert_dict(target_sessions, "events", tx1_event)

    for offset in range(0, len(kept_packets), args.tx_packets):
        packet_group = kept_packets[offset:offset + args.tx_packets]
        tx_number = offset // args.tx_packets + 1
        tx_label = f"tx{tx_number}"
        if len(packet_group) < args.tx_packets:
            tx_label += "_partial"
        cursor = target_bcg.execute(
            """INSERT INTO bcg_epochs
               (session_id,epoch_index,tx_label,start_time,end_time,packet_count,
                sample_count,average_hr,average_rr)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                args.session_id, tx_number, tx_label,
                packet_group[0]["timestamp"], packet_group[-1]["timestamp"],
                len(packet_group), len(packet_group) * 25,
                positive_average([packet["heart_rate"] for packet in packet_group]),
                positive_average([packet["respiration_rate"] for packet in packet_group]),
            ),
        )
        epoch_id = cursor.lastrowid
        for packet_index, packet in enumerate(packet_group):
            insert_dict(target_bcg, "bcg_packets", {
                "epoch_id": epoch_id,
                "packet_index": packet_index,
                "timestamp": packet["timestamp"],
                "sensor_packet_id": packet["sensor_packet_id"],
                "status_code": packet["status_code"],
                "heart_rate": packet["heart_rate"],
                "respiration_rate": packet["respiration_rate"],
                "bcg_base64": packet["bcg_base64"],
                "raw_packet_base64": packet["raw_packet_base64"],
            })

    target_sessions.commit()
    target_bcg.commit()
    session_check = target_sessions.execute("PRAGMA integrity_check").fetchone()[0]
    bcg_check = target_bcg.execute("PRAGMA integrity_check").fetchone()[0]
    if session_check != "ok" or bcg_check != "ok":
        raise SystemExit(f"Integrity check failed: sessions={session_check}, bcg={bcg_check}")

    target_sessions.close()
    target_bcg.close()
    source_sessions.close()
    source_bcg.close()

    for suffix in ("-wal", "-shm"):
        Path(str(sessions_path) + suffix).unlink(missing_ok=True)
        Path(str(bcg_path) + suffix).unlink(missing_ok=True)
    os.replace(sessions_new_path, sessions_path)
    os.replace(bcg_new_path, bcg_path)

    profiles_path = data_dir / "profiles.json"
    try:
        profiles = json.loads(profiles_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        profiles = {}
    profile = dict(profiles.get(session["username_key"]) or {})
    profile.update({
        "username": session["user"],
        "username_key": session["username_key"],
        "gender": session.get("gender"),
        "sessions": 0,
        "last_session_utc": None,
    })
    atomic_json(profiles_path, {session["username_key"]: profile})
    atomic_json(data_dir / "baselines.json", {})

    for legacy in ("sessions.jsonl", "sessions.jsonl.bak"):
        (data_dir / legacy).unlink(missing_ok=True)
    (data_dir / "server.log").write_text("", encoding="utf-8")

    manifest = {
        "status": "reset_complete",
        "session_id": args.session_id,
        "username_key": session["username_key"],
        "new_start_utc": start_utc,
        "tx1": {
            "label": "tx1",
            "local_interval": f"{args.start_local}–{args.end_local} {args.timezone}",
            "packet_count": len(tx1_packets),
            "first_packet_utc": tx1_packets[0]["timestamp"],
            "last_packet_utc": tx1_packets[-1]["timestamp"],
        },
        "retained": {
            "sessions": 1,
            "timeline_rows": len(kept_timeline),
            "event_rows_plus_tx_marker": len(kept_events) + 1,
            "bcg_packets": len(kept_packets),
            "bcg_tx_windows": (len(kept_packets) + args.tx_packets - 1) // args.tx_packets,
            "bcg_partial_windows": 1 if len(kept_packets) % args.tx_packets else 0,
        },
        "cleared": "all other users, sessions, earlier rows, personal baselines, legacy JSONL and server.log",
    }
    atomic_json(data_dir / "dataset-reset-manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
