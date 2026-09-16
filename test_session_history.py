import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from database import DatabaseManager
from sleep_system_policy import (
    PRE_RESTORE_SESSION_REPORT_VERSION,
    RECOVERY_SCORE_FORMULA_VERSION,
    SESSION_REPORT_VERSION,
    SLEEP_SCORE_FORMULA_VERSION,
)
from sessions.history import (
    apply_session_availability,
    session_availability_by_account,
    users_ordered_by_latest_session,
)
from sessions.history_service import (
    SessionHistoryService,
    resolve_history_window,
    safe_account_profile,
)
from sessions.score_summary import history_summary


class SessionAvailabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temporary.name)
        self.database = DatabaseManager(self.data_dir)
        self.database.initialize()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_recovery_average_never_mixes_nap_targets(self) -> None:
        def nap(session_id: str, target_s: int, score: int) -> dict:
            key = "nap_30" if target_s == 1_800 else "nap_90"
            return {
                "session_id": session_id,
                "account_key": "person@example.test",
                "ended_at_utc": "2026-09-05T06:30:00+00:00",
                "rest_mode": "nap_recovery",
                "target_duration_s": target_s,
                "sleep_quality": {
                    "available": True,
                    "score": score,
                    "quality_type": "rest_goal",
                    "score_title": "Recovery Score",
                    "formula_version": RECOVERY_SCORE_FORMULA_VERSION,
                    "duration_target": {"key": key, "seconds": target_s},
                },
            }

        same_target = history_summary(
            [
                nap("nap-a", 1_800, 80),
                nap("nap-b", 1_800, 90),
            ]
        )
        mixed_targets = history_summary(
            [
                nap("nap-a", 1_800, 80),
                nap("nap-c", 5_400, 70),
            ]
        )

        self.assertEqual(same_target["average_recovery_score"], 85.0)
        self.assertIsNone(mixed_targets["average_recovery_score"])

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
        self.assertEqual(result["current_sessions_without_data"], 1)
        self.assertEqual(result["completed_sessions"], 3)
        self.assertEqual(result["available_usage_sessions"], 2)
        self.assertEqual(
            result["last_available_session_utc"],
            "2026-09-01T10:00:00+00:00",
        )
        self.assertEqual(
            result["last_available_usage_session_utc"],
            "2026-09-02T10:00:00+00:00",
        )

        service = SessionHistoryService(
            self.database,
            history_start_utc="2026-09-01T00:00:00+00:00",
            report_version="report-v1",
            release_quality=lambda _summary, quality: quality or {},
            health_reference=lambda _profile: {},
        )
        completed = service.account_completed_sessions(
            account,
            {"email": account},
        )

        self.assertEqual(
            [item["session_id"] for item in completed],
            ["current-empty", "current-data"],
        )
        self.assertEqual(completed[0]["sample_count"], 0)
        self.assertEqual(completed[1]["sample_count"], 1)

        visible = service.account_history(
            account,
            {"email": account},
        )
        self.assertEqual(
            [item["session_id"] for item in visible["sessions"]],
            ["current-empty", "current-data"],
        )

    def test_account_history_includes_legacy_keys_but_publishes_canonical_key(
        self,
    ) -> None:
        canonical = "person@example.test"
        legacy = "old-display-name"
        self.insert_session(
            "legacy-session",
            legacy,
            "2026-09-02T10:00:00+00:00",
            with_timeline=True,
        )
        service = SessionHistoryService(
            self.database,
            history_start_utc="2026-09-01T00:00:00+00:00",
            report_version="report-v1",
            release_quality=lambda _summary, quality: quality or {},
            health_reference=lambda _profile: {},
        )
        profile = {
            "email": canonical,
            "display_name": "Person",
            "legacy_account_keys": [legacy],
        }

        profiles = {canonical: profile}
        safe_profile = safe_account_profile(canonical, profile, profiles)
        sessions = service.account_completed_sessions(canonical, safe_profile)
        detail = service.session_by_id(
            "legacy-session",
            profiles,
            account_key=canonical,
        )

        self.assertEqual([item["session_id"] for item in sessions], ["legacy-session"])
        self.assertEqual(sessions[0]["account_key"], canonical)
        self.assertIsNotNone(detail)
        self.assertEqual(detail["account_key"], canonical)

    def test_legacy_alias_collision_never_crosses_account_history(self) -> None:
        canonical = "person@example.test"
        collision = "other@example.test"
        self.insert_session(
            "other-session",
            collision,
            "2026-09-02T10:00:00+00:00",
            with_timeline=True,
        )
        service = SessionHistoryService(
            self.database,
            history_start_utc="2026-09-01T00:00:00+00:00",
            report_version="report-v1",
            release_quality=lambda _summary, quality: quality or {},
            health_reference=lambda _profile: {},
        )
        profile = {
            "email": canonical,
            "zeep_public_id": "public-person",
            "legacy_account_keys": [collision],
        }
        profiles = {
            canonical: profile,
            collision: {
                "email": collision,
                "zeep_public_id": "public-other",
            },
        }

        safe_profile = safe_account_profile(canonical, profile, profiles)
        sessions = service.account_completed_sessions(canonical, safe_profile)
        detail = service.session_by_id(
            "other-session",
            profiles,
            account_key=canonical,
        )

        self.assertEqual(safe_profile["verified_legacy_account_keys"], [])
        self.assertEqual(sessions, [])
        self.assertIsNone(detail)

    def test_duplicate_orphan_alias_claim_fails_closed(self) -> None:
        alias = "old-user"
        self.insert_session(
            "orphan-session",
            alias,
            "2026-09-02T10:00:00+00:00",
            with_timeline=True,
        )
        profiles = {
            "first@example.test": {
                "email": "first@example.test",
                "legacy_account_keys": [alias],
            },
            "second@example.test": {
                "email": "second@example.test",
                "legacy_account_keys": [alias],
            },
        }
        service = SessionHistoryService(
            self.database,
            history_start_utc="2026-09-01T00:00:00+00:00",
            report_version="report-v1",
            release_quality=lambda _summary, quality: quality or {},
            health_reference=lambda _profile: {},
        )

        for key, profile in profiles.items():
            safe_profile = safe_account_profile(key, profile, profiles)
            self.assertEqual(safe_profile["verified_legacy_account_keys"], [])
            self.assertEqual(
                service.account_completed_sessions(key, safe_profile),
                [],
            )

    def test_admin_all_users_canonicalizes_verified_legacy_rows(self) -> None:
        canonical = "person@example.test"
        legacy = "old-person"
        self.insert_session(
            "legacy-session",
            legacy,
            "2026-09-02T10:00:00+00:00",
            with_timeline=True,
        )
        profiles = {
            canonical: {
                "email": canonical,
                "display_name": "Person",
                "legacy_account_keys": [legacy],
            }
        }
        service = SessionHistoryService(
            self.database,
            history_start_utc="2026-09-01T00:00:00+00:00",
            report_version="report-v1",
            release_quality=lambda _summary, quality: quality or {},
            health_reference=lambda _profile: {},
        )

        result = service.admin_history(profiles, window=None, query="person")
        detail = service.session_by_id("legacy-session", profiles)

        self.assertEqual(result["total"], 1)
        self.assertEqual(result["sessions"][0]["account_key"], canonical)
        self.assertEqual(result["participants"][0]["account_key"], canonical)
        self.assertIsNotNone(detail)
        self.assertEqual(detail["account_key"], canonical)

    def test_profile_overlay_preserves_lifetime_context(self) -> None:
        profile = {"sessions": 9, "display_name": "Tester"}
        result = apply_session_availability(
            profile,
            {
                "available_sessions": 2,
                "lifetime_sessions": 4,
                "archived_sessions": 2,
                "sessions_without_data": 1,
                "current_sessions_without_data": 1,
                "completed_sessions": 5,
                "available_usage_sessions": 3,
                "last_available_session_utc": "2026-09-02T00:00:00+00:00",
                "last_available_usage_session_utc": "2026-09-03T00:00:00+00:00",
                "last_data_session_utc": "2026-09-02T00:00:00+00:00",
            },
        )

        self.assertEqual(result["sessions"], 2)
        self.assertEqual(result["available_sessions"], 2)
        self.assertEqual(result["lifetime_sessions"], 4)
        self.assertEqual(result["archived_sessions"], 2)
        self.assertEqual(result["completed_sessions"], 5)
        self.assertEqual(result["available_usage_sessions"], 3)
        self.assertEqual(profile["sessions"], 9)

    def test_user_selector_folds_verified_legacy_availability(self) -> None:
        canonical = "person@example.test"
        legacy = "old-person"
        profiles = {
            canonical: {
                "account_key": canonical,
                "email": canonical,
                "legacy_account_keys": [legacy],
            }
        }
        availability = {
            legacy: {
                "available_sessions": 1,
                "lifetime_sessions": 1,
                "sessions_without_data": 1,
                "current_sessions_without_data": 1,
                "last_available_usage_session_utc": ("2026-09-03T00:00:00+00:00"),
            }
        }

        users = users_ordered_by_latest_session(
            profiles,
            availability_by_account=availability,
        )

        self.assertEqual(users[0]["available_sessions"], 1)
        self.assertEqual(users[0]["available_usage_sessions"], 2)
        self.assertEqual(users[0]["completed_sessions"], 2)
        self.assertEqual(
            users[0]["history_order_utc"],
            "2026-09-03T00:00:00+00:00",
        )

    def test_mixed_case_session_key_remains_visible_and_is_normalized(self) -> None:
        canonical = "person@example.test"
        self.insert_session(
            "mixed-case-session",
            "Person@Example.Test",
            "2026-09-05T06:00:00+00:00",
            with_timeline=True,
        )
        profile = {"email": canonical, "account_key": canonical}
        profiles = {canonical: profile}
        service = SessionHistoryService(
            self.database,
            history_start_utc="2026-09-01T00:00:00+00:00",
            report_version="report-v1",
            release_quality=lambda _summary, quality: quality or {},
            health_reference=lambda _profile: {},
        )

        sessions = service.account_sessions(canonical, profile)
        detail = service.session_by_id(
            "mixed-case-session",
            profiles,
            account_key=canonical,
        )
        availability = session_availability_by_account(
            self.database.read_sessions,
            "2026-09-01T00:00:00+00:00",
        )

        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["account_key"], canonical)
        self.assertIsNotNone(detail)
        self.assertEqual(detail["account_key"], canonical)
        self.assertEqual(availability[canonical]["available_sessions"], 1)

        self.database.initialize()
        rows = self.database.read_sessions(
            "SELECT username_key FROM sessions WHERE session_id=?",
            ("mixed-case-session",),
        )
        self.assertEqual(rows[0]["username_key"], canonical)

    def test_user_selector_rejects_duplicate_legacy_alias_claim(self) -> None:
        alias = "old-user"
        profiles = {
            "first@example.test": {
                "account_key": "first@example.test",
                "legacy_account_keys": [alias],
            },
            "second@example.test": {
                "account_key": "second@example.test",
                "legacy_account_keys": [alias],
            },
        }
        availability = {
            alias: {
                "available_sessions": 1,
                "lifetime_sessions": 1,
            }
        }

        users = users_ordered_by_latest_session(
            profiles,
            availability_by_account=availability,
        )

        self.assertEqual(
            [user["available_usage_sessions"] for user in users],
            [0, 0],
        )

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
            "UPDATE sessions SET end_time=?,rest_mode=?,target_duration_s=? "
            "WHERE session_id=?",
            ("2026-09-05T00:30:00+00:00", "sleep", 25_200, "overnight"),
        )
        connection.execute(
            "UPDATE sessions SET end_time=?,rest_mode=?,target_duration_s=? "
            "WHERE session_id=?",
            ("2026-09-05T06:30:00+00:00", "nap_recovery", 1_800, "nap"),
        )
        for session_id, score, quality_type, title, formula in (
            (
                "overnight",
                88,
                "sleep",
                "Sleep Score",
                SLEEP_SCORE_FORMULA_VERSION,
            ),
            (
                "nap",
                81,
                "rest_goal",
                "Recovery Score",
                RECOVERY_SCORE_FORMULA_VERSION,
            ),
        ):
            final_summary = {
                "rest_mode": ("sleep" if quality_type == "sleep" else "nap_recovery"),
                "night_summary": {
                    "sleep_quality": {
                        "available": True,
                        "score": score,
                        "quality_type": quality_type,
                        "score_title": title,
                        "formula_version": formula,
                        "level": "ดีมาก",
                        **(
                            {
                                "duration_target": {
                                    "key": "nap_30",
                                    "seconds": 1_800,
                                }
                            }
                            if quality_type == "rest_goal"
                            else {
                                "duration_target": {
                                    "key": "overnight_7h",
                                    "seconds": 25_200,
                                }
                            }
                        ),
                    },
                },
                "session_report": {"version": "report-v1"},
            }
            connection.execute(
                "INSERT INTO events(session_id,timestamp,type,value) VALUES (?,?,?,?)",
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

    def test_history_never_counts_or_publishes_a_cross_mode_score(self) -> None:
        sessions = [
            {
                "session_id": "sleep-valid",
                "account_key": "first@example.test",
                "ended_at_utc": "2026-09-05T01:00:00+00:00",
                "rest_mode": "sleep",
                "target_duration_s": 25_200,
                "sleep_quality": {
                    "available": True,
                    "score": 88,
                    "quality_type": "sleep",
                    "score_title": "Sleep Score",
                    "formula_version": SLEEP_SCORE_FORMULA_VERSION,
                    "duration_target": {
                        "key": "overnight_7h",
                        "seconds": 25_200,
                    },
                },
            },
            {
                "session_id": "recovery-valid",
                "account_key": "second@example.test",
                "ended_at_utc": "2026-09-05T02:00:00+00:00",
                "rest_mode": "nap_recovery",
                "target_duration_s": 1_800,
                "sleep_quality": {
                    "available": True,
                    "score": 81,
                    "quality_type": "rest_goal",
                    "score_title": "Recovery Score",
                    "formula_version": RECOVERY_SCORE_FORMULA_VERSION,
                    "duration_target": {
                        "key": "nap_30",
                        "seconds": 1_800,
                    },
                },
            },
            {
                "session_id": "nap-with-sleep-score",
                "account_key": "third@example.test",
                "ended_at_utc": "2026-09-05T03:00:00+00:00",
                "rest_mode": "nap_recovery",
                "sleep_quality": {
                    "available": True,
                    "score": 91,
                    "quality_type": "sleep",
                    "score_title": "Sleep Score",
                    "formula_version": SLEEP_SCORE_FORMULA_VERSION,
                },
            },
        ]

        summary = SessionHistoryService._summary(sessions)
        participants = SessionHistoryService._participants(sessions)

        self.assertEqual(summary["sleep_score_count"], 1)
        self.assertEqual(summary["recovery_score_count"], 1)
        self.assertEqual(summary["awaiting_score_count"], 1)
        self.assertEqual(
            summary["sleep_score_count"]
            + summary["recovery_score_count"]
            + summary["awaiting_score_count"],
            summary["session_count"],
        )
        conflicting = next(
            score
            for participant in participants
            for score in participant["scores"]
            if score["session_id"] == "nap-with-sleep-score"
        )
        self.assertFalse(conflicting["available"])
        self.assertIsNone(conflicting["score"])
        self.assertEqual(conflicting["score_type"], "recovery_score")
        self.assertEqual(conflicting["score_title"], "Recovery Score")

    def test_history_average_is_hidden_when_score_formulas_differ(self) -> None:
        sessions = [
            {"account_key": "first@example.test"},
            {"account_key": "second@example.test"},
        ]
        canonical = [
            {
                "score": {
                    "available": True,
                    "type": "sleep_score",
                    "value": 84,
                    "formula_version": "sleep-formula-v2",
                }
            },
            {
                "score": {
                    "available": True,
                    "type": "sleep_score",
                    "value": 92,
                    "formula_version": "sleep-formula-v1",
                }
            },
        ]

        summary = SessionHistoryService._summary(
            sessions,
            canonical_results=canonical,
        )

        self.assertEqual(summary["sleep_score_count"], 2)
        self.assertIsNone(summary["average_sleep_score"])

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

    def test_session_lookup_filters_ownership_and_keeps_persisted_mode(self) -> None:
        account = "owner@example.test"
        self.insert_session(
            "owned-session",
            account,
            "2026-09-05T05:00:00+00:00",
            with_timeline=True,
        )
        connection = sqlite3.connect(self.data_dir / "sessions.db")
        connection.execute(
            "UPDATE sessions SET rest_mode=?,target_duration_s=? WHERE session_id=?",
            ("nap_recovery", 1800, "owned-session"),
        )
        connection.commit()
        connection.close()
        service = SessionHistoryService(
            self.database,
            history_start_utc="2026-09-01T00:00:00+00:00",
            report_version="report-v1",
            release_quality=lambda _summary, quality: quality or {},
            health_reference=lambda _profile: {},
        )

        owned = service.session_by_id(
            "owned-session",
            {account: {"email": account}},
            account_key=account,
        )
        forbidden = service.session_by_id(
            "owned-session",
            {account: {"email": account}},
            account_key="other@example.test",
        )

        self.assertEqual(owned["rest_mode"], "nap_recovery")
        self.assertEqual(owned["target_duration_s"], 1800)
        self.assertIsNone(forbidden)

    def test_canonical_session_metadata_wins_over_stale_final_summary(self) -> None:
        account = "corrected@example.test"
        self.insert_session(
            "corrected-session",
            account,
            "2026-09-05T05:00:00+00:00",
            with_timeline=True,
        )
        connection = sqlite3.connect(self.data_dir / "sessions.db")
        connection.execute(
            "UPDATE sessions SET rest_mode=?,target_duration_s=? WHERE session_id=?",
            ("nap_recovery", 5400, "corrected-session"),
        )
        connection.execute(
            "INSERT INTO events(session_id,timestamp,type,value) VALUES (?,?,?,?)",
            (
                "corrected-session",
                "2026-09-05T05:30:00+00:00",
                "final_summary",
                json.dumps(
                    {
                        "rest_mode": "sleep",
                        "target_duration_s": 1800,
                    }
                ),
            ),
        )
        connection.commit()
        connection.close()
        service = SessionHistoryService(
            self.database,
            history_start_utc="2026-09-01T00:00:00+00:00",
            report_version="report-v1",
            release_quality=lambda _summary, quality: quality or {},
            health_reference=lambda _profile: {},
        )

        result = service.session_by_id(
            "corrected-session",
            {account: {"email": account}},
            account_key=account,
        )

        self.assertEqual(result["rest_mode"], "nap_recovery")
        self.assertEqual(result["target_duration_s"], 5400)

    def test_history_keeps_approved_prior_report_and_drops_unknown_version(
        self,
    ) -> None:
        account = "compatible-report@example.test"
        self.insert_session(
            "compatible-report",
            account,
            "2026-09-05T05:00:00+00:00",
            with_timeline=True,
        )
        self.insert_session(
            "unknown-report",
            account,
            "2026-09-05T06:00:00+00:00",
            with_timeline=True,
        )
        connection = sqlite3.connect(self.data_dir / "sessions.db")
        for session_id, report_version in (
            ("compatible-report", PRE_RESTORE_SESSION_REPORT_VERSION),
            ("unknown-report", "zeep-session-report-v0-unknown"),
        ):
            final_summary = {
                "session_report": {
                    "version": report_version,
                    "headline": f"persisted {session_id}",
                },
            }
            connection.execute(
                "INSERT INTO events(session_id,timestamp,type,value) VALUES (?,?,?,?)",
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
            report_version=SESSION_REPORT_VERSION,
            release_quality=lambda _summary, quality: quality or {},
            health_reference=lambda _profile: {},
        )

        compatible = service.session_by_id(
            "compatible-report",
            {account: {"email": account}},
            account_key=account,
        )
        unknown = service.session_by_id(
            "unknown-report",
            {account: {"email": account}},
            account_key=account,
        )

        self.assertEqual(
            compatible["session_report"]["version"],
            PRE_RESTORE_SESSION_REPORT_VERSION,
        )
        self.assertEqual(
            compatible["session_report"]["headline"],
            "persisted compatible-report",
        )
        self.assertIsNone(unknown["session_report"])


if __name__ == "__main__":
    unittest.main()
