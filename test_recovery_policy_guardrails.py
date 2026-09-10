import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import tempfile
import unittest

from rescore_session_reports import rescore
from sleep_system_policy import (
    RECOVERY_SCORE_COMPONENT_MAX_POINTS,
    resolve_rest_target,
    summarize_environment_session_levels,
)


class RecoveryPolicyUnitTests(unittest.TestCase):
    def test_target_resolver_accepts_only_persisted_30_or_90_minutes(self):
        thirty = resolve_rest_target("nap_recovery", 30 * 60)
        ninety = resolve_rest_target("nap_recovery", 90 * 60)
        missing = resolve_rest_target("nap_recovery", None)
        invalid = resolve_rest_target("nap_recovery", 45 * 60)

        self.assertEqual(thirty["key"], "nap_30")
        self.assertEqual(ninety["key"], "nap_90")
        self.assertEqual(missing["source"], "legacy_missing")
        self.assertTrue(missing["review_required"])
        self.assertFalse(invalid["valid"])
        self.assertFalse(invalid["available"])

    def test_auto_mode_never_acquires_a_target(self):
        target = resolve_rest_target("auto", None, use_mode_default=True)

        self.assertFalse(target["available"])
        self.assertEqual(target["source"], "unresolved_mode")

    def test_recovery_v2_weights_total_one_hundred_without_coverage(self):
        self.assertEqual(RECOVERY_SCORE_COMPONENT_MAX_POINTS, {
            "goal_duration": 25.0,
            "physiological_response": 35.0,
            "rest_continuity": 30.0,
            "environment_support": 10.0,
        })
        self.assertEqual(sum(RECOVERY_SCORE_COMPONENT_MAX_POINTS.values()), 100)
        self.assertNotIn("data_coverage", RECOVERY_SCORE_COMPONENT_MAX_POINTS)

    def test_single_critical_sample_is_peak_context_not_session_level(self):
        summary = summarize_environment_session_levels(
            ["critical"] + ["excellent"] * 239
        )

        self.assertEqual(summary["status_key"], "excellent")
        self.assertEqual(summary["peak_status_key"], "critical")
        self.assertEqual(summary["critical_sample_pct"], 0.417)
        self.assertTrue(summary["transient_critical_observed"])


class HistoricalRecoveryGuardrailTests(unittest.TestCase):
    @staticmethod
    def _database(
        root: Path,
        *,
        duration_s: float,
        target_duration_s=None,
        sound_spike: bool = False,
    ) -> tuple[dict, int, int]:
        connection = sqlite3.connect(root / "sessions.db")
        connection.executescript("""
            CREATE TABLE sessions (
                session_id TEXT PRIMARY KEY,
                user TEXT,
                username_key TEXT,
                start_time TEXT,
                end_time TEXT,
                duration REAL,
                gender TEXT,
                rest_mode TEXT,
                target_duration_s REAL
            );
            CREATE TABLE events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                timestamp TEXT,
                type TEXT,
                value TEXT
            );
            CREATE TABLE timeline (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                timestamp TEXT,
                temperature REAL,
                humidity REAL,
                co2 REAL,
                lux REAL,
                sound REAL,
                heart_rate REAL,
                respiration_rate REAL,
                bed_status TEXT,
                pm2_5 REAL,
                voc_index REAL
            );
        """)
        start = datetime(2026, 9, 10, 0, 0, tzinfo=timezone.utc)
        end = start + timedelta(seconds=duration_s)
        connection.execute(
            "INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?)",
            (
                "nap-1",
                "Tester",
                "tester@example.com",
                start.isoformat(),
                end.isoformat(),
                duration_s,
                None,
                "nap_recovery",
                target_duration_s,
            ),
        )
        quality = {
            "available": True,
            "score": 71,
            "score_title": "Recovery Score",
            "estimated_sleep_s": 0,
            "actual_scored_s": duration_s,
            "version": "legacy-recovery-score",
            "rest_mode": {
                "requested": "nap_recovery",
                "resolved": "nap_recovery",
                "group": "nap_recovery",
                "label": "Nap & Refresh",
            },
        }
        old_report = {
            "version": "legacy-report",
            "quality": quality,
            "rest_mode": quality["rest_mode"],
            "sleep": {"recording_s": duration_s},
            "findings": [{"key": "sound", "severity": "critical"}],
        }
        final_summary = {
            "rest_mode": "nap_recovery",
            "target_duration_s": target_duration_s,
            "sample_interval_s": 30,
            "sensor_sample_interval_s": 5,
            "timeline_schema_version": 4,
            "night_summary": {
                "sleep_quality": quality,
                "wellness_score": 71,
            },
            "session_report": old_report,
        }
        connection.execute(
            "INSERT INTO events(session_id,timestamp,type,value) VALUES (?,?,?,?)",
            ("nap-1", end.isoformat(), "final_summary", json.dumps(final_summary)),
        )
        stage_count = max(1, int(duration_s // 30))
        for index in range(stage_count):
            timestamp = start + timedelta(seconds=(index + 1) * 30)
            connection.execute(
                "INSERT INTO events(session_id,timestamp,type,value) "
                "VALUES (?,?,?,?)",
                (
                    "nap-1",
                    min(timestamp, end).isoformat(),
                    "sleep_stage",
                    json.dumps({
                        "state": "wake",
                        "sample_interval_s": 30,
                        "metrics": {},
                    }),
                ),
            )
        timeline_count = max(6, int(duration_s // 5))
        for index in range(timeline_count):
            timestamp = start + timedelta(seconds=(index + 1) * 5)
            sound = 80.0 if sound_spike and index < 6 else 38.0
            connection.execute(
                "INSERT INTO timeline VALUES "
                "(NULL,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    "nap-1",
                    min(timestamp, end).isoformat(),
                    24.0,
                    50.0,
                    750.0,
                    1.0,
                    sound,
                    64.0,
                    14.0,
                    "On bed",
                    8.0,
                    100.0,
                ),
            )
        connection.commit()
        before_stage_count = connection.execute(
            "SELECT COUNT(*) FROM events WHERE type='sleep_stage'"
        ).fetchone()[0]
        before_timeline_count = connection.execute(
            "SELECT COUNT(*) FROM timeline"
        ).fetchone()[0]
        connection.close()
        return quality, before_stage_count, before_timeline_count

    def test_missing_legacy_target_is_skipped_and_preserves_score(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            original, _, _ = self._database(data_dir, duration_s=60 * 60)

            result = rescore(
                data_dir,
                ["nap-1"],
                requested_mode=None,
                apply=True,
            )

            item = result["sessions"][0]
            self.assertEqual(item["status"], "skipped_review_required")
            self.assertEqual(item["reason_code"], "missing_recovery_target")
            connection = sqlite3.connect(data_dir / "sessions.db")
            final = json.loads(connection.execute(
                "SELECT value FROM events WHERE type='final_summary'"
            ).fetchone()[0])
            connection.close()
            self.assertEqual(final["night_summary"]["sleep_quality"], original)

    def test_hard_short_session_withholds_score_even_without_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            self._database(data_dir, duration_s=9 * 60)

            result = rescore(
                data_dir,
                ["nap-1"],
                requested_mode=None,
                apply=True,
            )

            item = result["sessions"][0]
            self.assertEqual(item["status"], "rescored")
            self.assertIsNone(item["new_score"])
            self.assertEqual(
                item["quality"]["rest_mode"]["protocol_status"]["status"],
                "insufficient",
            )

    def test_target_30_session_over_45_minutes_is_review_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            original, _, _ = self._database(
                data_dir,
                duration_s=46 * 60,
                target_duration_s=30 * 60,
            )

            result = rescore(
                data_dir,
                ["nap-1"],
                requested_mode=None,
                apply=True,
            )

            item = result["sessions"][0]
            self.assertEqual(item["status"], "skipped_review_required")
            self.assertEqual(item["reason_code"], "recovery_timing_review")
            connection = sqlite3.connect(data_dir / "sessions.db")
            final = json.loads(connection.execute(
                "SELECT value FROM events WHERE type='final_summary'"
            ).fetchone()[0])
            connection.close()
            self.assertEqual(final["night_summary"]["sleep_quality"], original)

    def test_report_only_refreshes_environment_and_preserves_quality(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            original, stage_count, timeline_count = self._database(
                data_dir,
                duration_s=20 * 60,
                sound_spike=True,
            )

            result = rescore(
                data_dir,
                ["nap-1"],
                requested_mode=None,
                apply=True,
                report_only=True,
            )

            self.assertEqual(result["refreshed_count"], 1)
            self.assertEqual(result["rescored_count"], 0)
            connection = sqlite3.connect(data_dir / "sessions.db")
            final = json.loads(connection.execute(
                "SELECT value FROM events WHERE type='final_summary'"
            ).fetchone()[0])
            report = final["session_report"]
            sound = next(
                item for item in report["findings"] if item["key"] == "sound"
            )
            self.assertEqual(final["night_summary"]["sleep_quality"], original)
            self.assertEqual(sound["severity"], "excellent")
            self.assertTrue(sound["transient_critical_observed"])
            self.assertEqual(
                report["rest_mode"]["protocol_status"]["display_status"],
                "TARGET_UNKNOWN",
            )
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM events WHERE type='sleep_stage'"
            ).fetchone()[0], stage_count)
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM timeline"
            ).fetchone()[0], timeline_count)
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM events "
                "WHERE type='session_report_refreshed'"
            ).fetchone()[0], 1)
            connection.close()

    def test_report_only_refuses_all_sessions(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "requires one or more"):
                rescore(
                    Path(temporary),
                    None,
                    requested_mode=None,
                    apply=False,
                    report_only=True,
                )


if __name__ == "__main__":
    unittest.main()
