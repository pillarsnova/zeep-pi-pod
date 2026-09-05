import sqlite3
import tempfile
import unittest
import json
from pathlib import Path

from database import DatabaseManager
from zeep_pod.sessions.history import (
    apply_session_availability,
    session_availability_by_account,
)
from zeep_pod.sessions.history_service import (
    SessionHistoryService,
    resolve_history_window,
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

    def test_local_day_window_is_converted_to_bangkok_utc(self) -> None:
        window = resolve_history_window(
            "2026-09-05",
            "2026-09-05",
            "00:00",
            "23:59",
        )

        self.assertEqual(window.start_utc, "2026-09-04T17:00:00+00:00")
        self.assertEqual(window.end_utc, "2026-09-05T17:00:00+00:00")
        self.assertEqual(
            window.public_snapshot()["day_assignment"],
            "session_end_local_date",
        )

    def test_daily_history_counts_people_and_mode_specific_scores(self) -> None:
        first = "first@example.test"
        second = "second@example.test"
        self.insert_session(
            "overnight",
            first,
            "2026-09-04T18:00:00+00:00",
            with_timeline=True,
        )
        self.insert_session(
            "nap",
            second,
            "2026-09-05T06:00:00+00:00",
            with_timeline=True,
        )
        connection = sqlite3.connect(self.data_dir / "sessions.db")
        connection.execute(
            "UPDATE sessions SET end_time=? WHERE session_id=?",
            ("2026-09-05T00:30:00+00:00", "overnight"),
        )
        connection.execute(
            "UPDATE sessions SET end_time=? WHERE session_id=?",
            ("2026-09-05T06:30:00+00:00", "nap"),
        )
        for session_id, score, quality_type, title in (
            ("overnight", 88, "sleep", "Sleep Score"),
            ("nap", 81, "rest_goal", "Recovery Score"),
        ):
            final_summary = {
                "night_summary": {
                    "sleep_quality": {
                        "available": True,
                        "score": score,
                        "quality_type": quality_type,
                        "score_title": title,
                        "level": "ดีมาก",
                    },
                },
                "session_report": {"version": "report-v1"},
            }
            connection.execute(
                "INSERT INTO events(session_id,timestamp,type,value) "
                "VALUES (?,?,?,?)",
                (
                    session_id,
                    "2026-09-05T06:31:00+00:00",
                    "final_summary",
                    json.dumps(final_summary),
                ),
            )
        connection.commit()
        connection.close()

        service = SessionHistoryService(
            self.database,
            history_start_utc="2026-09-01T00:00:00+00:00",
            report_version="report-v1",
            release_quality=lambda _summary, quality: quality,
            health_reference=lambda _profile: {},
        )
        result = service.admin_history(
            {
                first: {"email": first, "display_name": "First"},
                second: {"email": second, "display_name": "Second"},
            },
            window=resolve_history_window(
                "2026-09-05",
                "2026-09-05",
            ),
        )

        self.assertEqual(result["summary"]["people_count"], 2)
        self.assertEqual(result["summary"]["session_count"], 2)
        self.assertEqual(result["summary"]["sleep_score_count"], 1)
        self.assertEqual(result["summary"]["recovery_score_count"], 1)
        self.assertEqual(result["summary"]["average_sleep_score"], 88.0)
        self.assertEqual(result["summary"]["average_recovery_score"], 81.0)
        self.assertEqual(len(result["participants"]), 2)

    def test_name_filter_is_admin_presentation_only(self) -> None:
        account = "search@example.test"
        self.insert_session(
            "searchable",
            account,
            "2026-09-05T05:00:00+00:00",
            with_timeline=True,
        )
        service = SessionHistoryService(
            self.database,
            history_start_utc="2026-09-01T00:00:00+00:00",
            report_version="report-v1",
            release_quality=lambda _summary, quality: quality or {},
            health_reference=lambda _profile: {},
        )
        window = resolve_history_window("2026-09-05", "2026-09-05")

        found = service.admin_history(
            {account: {"display_name": "Somchai Tester"}},
            window=window,
            query="somchai",
        )
        missing = service.admin_history(
            {account: {"display_name": "Somchai Tester"}},
            window=window,
            query="not-this-person",
        )

        self.assertEqual(found["summary"]["people_count"], 1)
        self.assertEqual(missing["summary"]["people_count"], 0)


if __name__ == "__main__":
    unittest.main()
