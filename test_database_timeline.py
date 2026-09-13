"""Persistence regressions for versioned Session timeline evidence."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from database import DatabaseManager


def _session_start_payload(session_id: str) -> dict[str, object]:
    return {
        "session_id": session_id,
        "user": "Atomic Test",
        "username_key": "atomic@example.test",
        "gender": "unspecified",
        "rest_mode": "sleep",
        "target_duration_s": 28_800,
        "start_time": "2026-09-13T00:00:00+00:00",
        "created_at": "2026-09-13T00:00:00+00:00",
    }


class SessionFinalizationTransactionTests(unittest.TestCase):
    def test_session_row_summary_and_terminal_wake_commit_together(self):
        with tempfile.TemporaryDirectory() as root:
            manager = DatabaseManager(Path(root))
            manager.initialize()
            manager.start()
            try:
                manager.enqueue(
                    "sessions",
                    "session_start",
                    _session_start_payload("atomic-success"),
                )
                self.assertTrue(manager.flush())
                payload = {
                    "session_id": "atomic-success",
                    "end_time": "2026-09-13T08:00:00+00:00",
                    "duration": 28_800.0,
                    "note": None,
                    "end_reason": "logout",
                    "terminal_wake": {
                        "timestamp": "2026-09-13T07:59:30+00:00",
                        "value": {"state": "wake"},
                    },
                    "final_summary": {"score": 91, "rest_mode": "sleep"},
                }
                manager.enqueue("sessions", "session_finalize", payload)
                self.assertTrue(manager.flush())
                # Retrying after an ambiguous timeout replaces, rather than
                # duplicates, the two generated final events.
                manager.enqueue("sessions", "session_finalize", payload)
                self.assertTrue(manager.flush())
            finally:
                manager.stop()

            inspect = sqlite3.connect(manager.sessions_path)
            row = inspect.execute(
                "SELECT end_time,duration,end_reason FROM sessions WHERE session_id=?",
                ("atomic-success",),
            ).fetchone()
            events = inspect.execute(
                "SELECT type,value FROM events WHERE session_id=? ORDER BY timestamp",
                ("atomic-success",),
            ).fetchall()
            inspect.close()

            self.assertEqual(
                row,
                ("2026-09-13T08:00:00+00:00", 28_800.0, "logout"),
            )
            self.assertEqual(
                [event[0] for event in events],
                ["session_terminal_wake", "final_summary"],
            )
            self.assertEqual(json.loads(events[1][1])["score"], 91)

    def test_writer_error_rolls_back_whole_finalize_and_flush_reports_failure(self):
        with tempfile.TemporaryDirectory() as root:
            manager = DatabaseManager(Path(root))
            manager.initialize()
            manager.start()
            try:
                manager.enqueue(
                    "sessions",
                    "session_start",
                    _session_start_payload("atomic-failure"),
                )
                manager.enqueue(
                    "sessions",
                    "event",
                    {
                        "session_id": "atomic-failure",
                        "timestamp": "2026-09-13T00:30:00+00:00",
                        "type": "final_summary",
                        "value": {"version": "previous"},
                    },
                )
                self.assertTrue(manager.flush())

                manager.enqueue(
                    "sessions",
                    "session_finalize",
                    {
                        "session_id": "atomic-failure",
                        "end_time": "2026-09-13T08:00:00+00:00",
                        "duration": 28_800.0,
                        "end_reason": "logout",
                        # json.dumps fails after the row update and summary
                        # delete, proving both mutations are rolled back.
                        "final_summary": {"unsupported": object()},
                    },
                )
                self.assertFalse(manager.flush())
                self.assertIn("TypeError", manager.health()["last_error"])

                row = manager.read_sessions(
                    "SELECT end_time,duration,end_reason FROM sessions WHERE session_id=?",
                    ("atomic-failure",),
                )[0]
                events = manager.read_sessions(
                    "SELECT value FROM events WHERE session_id=? AND type='final_summary'",
                    ("atomic-failure",),
                )
                self.assertIsNone(row["end_time"])
                self.assertIsNone(row["duration"])
                self.assertIsNone(row["end_reason"])
                self.assertEqual(json.loads(events[0]["value"])["version"], "previous")
            finally:
                manager.stop()


class RespiratoryEvidenceTimelineTests(unittest.TestCase):
    def test_v6_migration_adds_and_round_trips_rr_evidence(self):
        with tempfile.TemporaryDirectory() as root:
            data_dir = Path(root)
            legacy = sqlite3.connect(data_dir / "sessions.db")
            legacy.execute("""
                CREATE TABLE timeline (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    temperature REAL, humidity REAL, co2 REAL, lux REAL,
                    sound REAL, heart_rate REAL, respiration_rate REAL,
                    bed_status TEXT
                )
            """)
            legacy.commit()
            legacy.close()

            manager = DatabaseManager(data_dir)
            manager.initialize()
            inspect = sqlite3.connect(data_dir / "sessions.db")
            columns = {
                row[1] for row in inspect.execute("PRAGMA table_info(timeline)")
            }
            inspect.close()
            self.assertIn("respiratory_evidence_valid", columns)
            self.assertIn("respiratory_evidence_reason", columns)

            manager.start()
            manager.enqueue("sessions", "timeline", {
                "session_id": "session-respiratory-1",
                "timestamp": "2026-09-13T00:00:00+00:00",
                "respiration_rate": 14.2,
                "bed_status": "On bed",
                "respiratory_evidence_valid": True,
                "respiratory_evidence_reason": "direct_current_rr",
            })
            self.assertTrue(manager.flush())
            manager.stop()

            verify = sqlite3.connect(data_dir / "sessions.db")
            stored = verify.execute(
                "SELECT respiration_rate,respiratory_evidence_valid,"
                "respiratory_evidence_reason FROM timeline"
            ).fetchone()
            verify.close()
            self.assertEqual(stored, (14.2, 1, "direct_current_rr"))


if __name__ == "__main__":
    unittest.main()
