"""Read-only SQLite access for the legacy Sleep History replay command."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any


class ReplayStorageError(RuntimeError):
    """Identify an unreadable or incompatible historical replay database."""


def load_session_sleep_events(
    database_path: Path,
    session_id: str | None,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Load one Session and its Sleep events without creating or mutating DBs."""
    try:
        with closing(_connect_readonly(database_path)) as connection:
            if session_id:
                session = connection.execute(
                    "SELECT * FROM sessions WHERE session_id=?",
                    (session_id,),
                ).fetchone()
            else:
                session = connection.execute(
                    "SELECT * FROM sessions "
                    "ORDER BY (end_time IS NULL) DESC,start_time DESC LIMIT 1"
                ).fetchone()
            if session is None:
                return None, []
            events = connection.execute(
                "SELECT id,timestamp,value FROM events "
                "WHERE session_id=? AND type='sleep_stage' ORDER BY timestamp,id",
                (session["session_id"],),
            ).fetchall()
    except sqlite3.DatabaseError as exc:
        raise _storage_error(database_path, exc) from exc
    return dict(session), [dict(row) for row in events]


def load_bcg_packets(
    database_path: Path,
    session_id: str,
) -> list[dict[str, Any]]:
    """Load raw BCG packet rows through a query-only connection."""
    try:
        with closing(_connect_readonly(database_path)) as connection:
            rows = connection.execute(
                """SELECT p.timestamp,p.status_code,p.heart_rate,p.respiration_rate
                   ,p.bcg_base64
                   FROM bcg_packets p JOIN bcg_epochs e ON e.epoch_id=p.epoch_id
                   WHERE e.session_id=? ORDER BY p.timestamp,p.id""",
                (session_id,),
            ).fetchall()
    except sqlite3.DatabaseError as exc:
        raise _storage_error(database_path, exc) from exc
    return [dict(row) for row in rows]


def _storage_error(path: Path, error: sqlite3.DatabaseError) -> ReplayStorageError:
    resolved = path.resolve()
    return ReplayStorageError(
        f"Replay database schema/query failed: {resolved}: {error}"
    )


def _connect_readonly(path: Path) -> sqlite3.Connection:
    """Open an existing SQLite file in enforced read-only/query-only mode."""
    resolved = path.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"Replay database not found: {resolved}")
    connection = sqlite3.connect(
        f"{resolved.as_uri()}?mode=ro",
        uri=True,
        timeout=15,
    )
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA busy_timeout=15000")
    except Exception:
        connection.close()
        raise
    return connection
