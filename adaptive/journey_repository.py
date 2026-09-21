"""Bounded SQLite adapter, reusing session event persistence and erasure."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from database import DatabaseManager

MAX_SAMPLES = 20000


class JourneyRepository:
    """Read raw rows without mutation; append only explicit user decisions."""

    def __init__(self, database: DatabaseManager) -> None:
        self.database = database

    def session(self, session_id: str) -> dict[str, Any] | None:
        rows = self.database.read_sessions(
            "SELECT * FROM sessions WHERE session_id=?",
            (session_id,),
        )
        return rows[0] if rows else None

    def samples(self, session_id: str) -> tuple[list[dict[str, Any]], bool]:
        rows = self.database.read_sessions(
            "SELECT * FROM timeline WHERE session_id=? ORDER BY timestamp DESC LIMIT ?",
            (session_id, MAX_SAMPLES + 1),
        )
        return list(reversed(rows[:MAX_SAMPLES])), len(rows) > MAX_SAMPLES

    def events(self, session_id: str) -> list[dict[str, Any]]:
        return self.database.read_sessions(
            "SELECT * FROM events WHERE session_id=? AND type IN "
            "('aircon_command','bed_command','output','pulse','door','music',"
            "'adaptive_comfort','adaptive_decision') ORDER BY timestamp,id",
            (session_id,),
        )

    def prior_feedback(self, session: dict[str, Any]) -> list[dict[str, Any]]:
        if not str(session.get("username_key") or "").strip():
            return []
        return self.database.read_sessions(
            "SELECT e.*,s.end_time FROM events e JOIN sessions s "
            "ON e.session_id=s.session_id WHERE s.username_key=? "
            "AND s.end_time<? AND e.timestamp<? AND e.type='adaptive_comfort' "
            "ORDER BY e.timestamp,e.id LIMIT 2000",
            (session["username_key"], session["start_time"], session["start_time"]),
        )

    def append(
        self,
        session_id: str,
        kind: str,
        value: dict[str, Any],
        *,
        now: float,
    ) -> None:
        """Persist through the existing writer; never claim success on failure."""
        self.database.enqueue(
            "sessions",
            "event",
            {
                "session_id": session_id,
                "timestamp": datetime.fromtimestamp(now, UTC).isoformat(),
                "type": kind,
                "value": value,
            },
        )
        if not self.database.flush(timeout=5):
            raise RuntimeError("adaptive event persistence not confirmed")
