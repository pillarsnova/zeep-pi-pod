import sqlite3
import tempfile
import unittest
from pathlib import Path

from database import DatabaseManager
from zeep_pod.sessions.history import (
    apply_session_availability,
    session_availability_by_account,
)


class SessionAvailabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temporary.name)
        self.database = DatabaseManager(self.data_dir)
        self.database.initialize()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def insert_session(
        self,
        session_id: str,
        account: str,
        start_time: str,
        *,
        with_timeline: bool,
        completed: bool = True,
    ) -> None:
        connection = sqlite3.connect(self.data_dir / "sessions.db")
        connection.execute(
            """
            INSERT INTO sessions (
                session_id,user,username_key,start_time,end_time,duration,
                created_at,schema_version
            ) VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                session_id,
                account,
                account,
                start_time,
                start_time if completed else None,
                1800 if completed else None,
                start_time,
                4,
            ),
        )
        if with_timeline:
            connection.execute(
                """
                INSERT INTO timeline (
                    session_id,timestamp,temperature,heart_rate,
                    respiration_rate,bed_status
                ) VALUES (?,?,?,?,?,?)
                """,
                (session_id, start_time, 23.0, 60.0, 14.0, "On bed"),
            )
        connection.commit()
        connection.close()

    def test_counts_only_completed_data_backed_current_history(self) -> None:
        account = "current@example.test"
        self.insert_session(
            "old-data",
            account,
            "2026-08-31T10:00:00+00:00",
            with_timeline=True,
        )
        self.insert_session(
            "current-data",
            account,
            "2026-09-01T10:00:00+00:00",
            with_timeline=True,
        )
        self.insert_session(
            "current-empty",
            account,
            "2026-09-02T10:00:00+00:00",
            with_timeline=False,
        )
        self.insert_session(
            "current-active",
            account,
            "2026-09-03T10:00:00+00:00",
            with_timeline=True,
            completed=False,
        )

        result = session_availability_by_account(
            self.database.read_sessions,
            "2026-09-01T00:00:00+00:00",
        )[account]

        self.assertEqual(result["available_sessions"], 1)
        self.assertEqual(result["lifetime_sessions"], 2)
        self.assertEqual(result["archived_sessions"], 1)
        self.assertEqual(result["sessions_without_data"], 1)
        self.assertEqual(
            result["last_available_session_utc"],
            "2026-09-01T10:00:00+00:00",
        )

    def test_profile_overlay_preserves_lifetime_context(self) -> None:
        profile = {"sessions": 9, "display_name": "Tester"}
        result = apply_session_availability(
            profile,
            {
                "available_sessions": 2,
                "lifetime_sessions": 4,
                "archived_sessions": 2,
                "sessions_without_data": 1,
                "last_available_session_utc": "2026-09-02T00:00:00+00:00",
                "last_data_session_utc": "2026-09-02T00:00:00+00:00",
            },
        )

        self.assertEqual(result["sessions"], 2)
        self.assertEqual(result["available_sessions"], 2)
        self.assertEqual(result["lifetime_sessions"], 4)
        self.assertEqual(result["archived_sessions"], 2)
        self.assertEqual(profile["sessions"], 9)


if __name__ == "__main__":
    unittest.main()
