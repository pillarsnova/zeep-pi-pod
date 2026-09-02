#!/usr/bin/env python3
"""One-time cleanup for completed ZEEP Sessions shorter than two hours.

The command is dry-run by default.  ``--apply`` creates an online SQLite
backup plus copies of profile/baseline JSON, removes only completed Sessions
whose recorded duration is strictly below the threshold, cascades their
Timeline/Event/BCG rows, rebuilds profile counters and personal baselines, and
writes a marker that prevents this cleanup version from running twice.

An active/open Session is always excluded, including the Session referenced by
``active_session_checkpoint.json``.  Stop ``zeep-pod.service`` before apply so
the application writer cannot race this maintenance transaction.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import shutil
import sqlite3
from typing import Any

from database import DatabaseManager
from personal import BaselineStore


MAINTENANCE_TOOL_NAME = "cleanup_short_sessions.py"
CLEANUP_ID = "cleanup-short-sessions-under-2h-v1"
DEFAULT_THRESHOLD_SECONDS = 2 * 3600


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".cleanup-new")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def connect(path: Path, *, readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=20)
    else:
        connection = sqlite3.connect(path, timeout=20)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=20000")
    return connection


def duration_seconds(row: sqlite3.Row) -> float | None:
    try:
        value = float(row["duration"])
        if math.isfinite(value) and value >= 0:
            return value
    except (TypeError, ValueError, OverflowError):
        pass
    try:
        start = datetime.fromisoformat(str(row["start_time"]).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(row["end_time"]).replace("Z", "+00:00"))
        return max(0.0, (end - start).total_seconds())
    except (TypeError, ValueError):
        return None


def checkpoint_session_id(data_dir: Path) -> str | None:
    try:
        payload = json.loads(
            (data_dir / "active_session_checkpoint.json").read_text(encoding="utf-8")
        )
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    value = payload.get("session_id") if isinstance(payload, dict) else None
    if not value and isinstance(payload, dict) and isinstance(payload.get("record"), dict):
        value = payload["record"].get("session_id")
    return str(value) if value else None


def inspect_candidates(data_dir: Path, threshold_seconds: float) -> dict[str, Any]:
    sessions_path = data_dir / "sessions.db"
    bcg_path = data_dir / "bcg.db"
    active_id = checkpoint_session_id(data_dir)
    sessions = connect(sessions_path, readonly=True)
    bcg = connect(bcg_path, readonly=True)
    try:
        completed = sessions.execute(
            """SELECT session_id,username_key,start_time,end_time,duration
               FROM sessions WHERE end_time IS NOT NULL ORDER BY start_time"""
        ).fetchall()
        candidates = []
        for row in completed:
            duration = duration_seconds(row)
            if (duration is not None and duration < threshold_seconds
                    and row["session_id"] != active_id):
                candidates.append({
                    "session_id": row["session_id"],
                    "username_key": row["username_key"],
                    "duration_seconds": round(duration, 3),
                })
        ids = [item["session_id"] for item in candidates]
        counts = {
            "sessions": len(ids),
            "timeline": 0,
            "events": 0,
            "bcg_epochs": 0,
            "bcg_packets": 0,
        }
        if ids:
            placeholders = ",".join("?" for _ in ids)
            counts["timeline"] = sessions.execute(
                f"SELECT COUNT(*) FROM timeline WHERE session_id IN ({placeholders})", ids
            ).fetchone()[0]
            counts["events"] = sessions.execute(
                f"SELECT COUNT(*) FROM events WHERE session_id IN ({placeholders})", ids
            ).fetchone()[0]
            counts["bcg_epochs"] = bcg.execute(
                f"SELECT COUNT(*) FROM bcg_epochs WHERE session_id IN ({placeholders})", ids
            ).fetchone()[0]
            counts["bcg_packets"] = bcg.execute(
                f"""SELECT COUNT(*) FROM bcg_packets p
                    JOIN bcg_epochs e ON e.epoch_id=p.epoch_id
                    WHERE e.session_id IN ({placeholders})""",
                ids,
            ).fetchone()[0]
        return {
            "cleanup_id": CLEANUP_ID,
            "threshold_seconds": threshold_seconds,
            "strictly_less_than_threshold": True,
            "active_checkpoint_session_excluded": bool(active_id),
            "candidate_session_ids": ids,
            "affected_username_keys": sorted({item["username_key"] for item in candidates}),
            "candidate_durations_seconds": [item["duration_seconds"] for item in candidates],
            "delete_counts": counts,
        }
    finally:
        sessions.close()
        bcg.close()


def backup_database(source_path: Path, destination_path: Path) -> None:
    source = connect(source_path, readonly=True)
    destination = sqlite3.connect(destination_path)
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()


def create_backup(data_dir: Path, backup_root: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = backup_root / f"{CLEANUP_ID}-{stamp}"
    destination.mkdir(parents=True, exist_ok=False)
    backup_database(data_dir / "sessions.db", destination / "sessions.db")
    backup_database(data_dir / "bcg.db", destination / "bcg.db")
    for name in ("profiles.json", "baselines.json", "active_session_checkpoint.json"):
        source = data_dir / name
        if source.exists():
            shutil.copy2(source, destination / name)
    return destination


def rebuild_profiles(data_dir: Path) -> None:
    path = data_dir / "profiles.json"
    try:
        profiles = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        profiles = {}
    if not isinstance(profiles, dict):
        profiles = {}
    sessions = connect(data_dir / "sessions.db", readonly=True)
    try:
        rows = sessions.execute(
            """SELECT username_key,COUNT(*) AS session_count,MAX(end_time) AS last_session
               FROM sessions WHERE end_time IS NOT NULL GROUP BY username_key"""
        ).fetchall()
    finally:
        sessions.close()
    summary = {
        str(row["username_key"]): (int(row["session_count"]), row["last_session"])
        for row in rows
    }
    for key, profile in list(profiles.items()):
        if not isinstance(profile, dict):
            profile = {}
            profiles[key] = profile
        count, last_session = summary.get(str(key), (0, None))
        profile["sessions"] = count
        profile["last_session_utc"] = last_session
    atomic_json(path, profiles)


def rebuild_baselines(data_dir: Path, username_keys: list[str]) -> None:
    database = DatabaseManager(data_dir)
    store = BaselineStore(database, data_dir)
    for username_key in username_keys:
        store.update_user(username_key)


def integrity(connection: sqlite3.Connection) -> str:
    return str(connection.execute("PRAGMA integrity_check").fetchone()[0])


def apply_cleanup(
    data_dir: Path,
    backup_root: Path,
    marker_path: Path,
    threshold_seconds: float,
) -> dict[str, Any]:
    if marker_path.exists():
        return {
            "status": "already_applied",
            "cleanup_id": CLEANUP_ID,
            "marker": str(marker_path),
        }
    plan = inspect_candidates(data_dir, threshold_seconds)
    backup_dir = create_backup(data_dir, backup_root)
    ids = list(plan["candidate_session_ids"])
    sessions = connect(data_dir / "sessions.db")
    bcg = connect(data_dir / "bcg.db")
    try:
        if ids:
            placeholders = ",".join("?" for _ in ids)
            with sessions:
                sessions.execute(
                    f"DELETE FROM sessions WHERE session_id IN ({placeholders})", ids
                )
            with bcg:
                bcg.execute(
                    f"DELETE FROM bcg_epochs WHERE session_id IN ({placeholders})", ids
                )
        session_integrity = integrity(sessions)
        bcg_integrity = integrity(bcg)
        session_orphans = sessions.execute(
            """SELECT
                 (SELECT COUNT(*) FROM timeline t LEFT JOIN sessions s USING(session_id)
                  WHERE s.session_id IS NULL) +
                 (SELECT COUNT(*) FROM events e LEFT JOIN sessions s USING(session_id)
                  WHERE s.session_id IS NULL)"""
        ).fetchone()[0]
        bcg_orphans = bcg.execute(
            """SELECT COUNT(*) FROM bcg_packets p
               LEFT JOIN bcg_epochs e ON e.epoch_id=p.epoch_id
               WHERE e.epoch_id IS NULL"""
        ).fetchone()[0]
        if session_integrity != "ok" or bcg_integrity != "ok" or session_orphans or bcg_orphans:
            raise RuntimeError(
                "post-cleanup integrity failed: "
                f"sessions={session_integrity}, bcg={bcg_integrity}, "
                f"session_orphans={session_orphans}, bcg_orphans={bcg_orphans}"
            )
    finally:
        sessions.close()
        bcg.close()

    rebuild_profiles(data_dir)
    rebuild_baselines(data_dir, list(plan["affected_username_keys"]))
    completed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    result = {
        **plan,
        "status": "applied",
        "completed_at_utc": completed_at,
        "backup_dir": str(backup_dir),
        "marker": str(marker_path),
        "integrity": {"sessions": "ok", "bcg": "ok", "orphans": 0},
    }
    atomic_json(marker_path, result)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument("--marker", type=Path)
    parser.add_argument("--threshold-seconds", type=float, default=DEFAULT_THRESHOLD_SECONDS)
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.threshold_seconds <= 0:
        raise SystemExit("--threshold-seconds must be positive")
    data_dir = args.data_dir.resolve()
    backup_root = (args.backup_dir or data_dir.parent / "backup").resolve()
    marker_path = (args.marker or data_dir / f"{CLEANUP_ID}.done.json").resolve()
    if args.apply:
        result = apply_cleanup(data_dir, backup_root, marker_path, args.threshold_seconds)
    else:
        result = inspect_candidates(data_dir, args.threshold_seconds)
        result["status"] = "dry_run"
        result["marker_exists"] = marker_path.exists()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
