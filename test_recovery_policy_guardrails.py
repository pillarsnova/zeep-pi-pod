import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

import rescore_session_reports
from api_models import AuthLoginCommand
from rescore_session_reports import rescore
from sleep_session_report import build_sleep_quality
from sleep_system_policy import (
    PREVIOUS_SESSION_REPORT_VERSION,
    PREVIOUS_SLEEP_QUALITY_VERSION,
    RECOVERY_SCORE_COMPONENT_MAX_POINTS,
    SESSION_REPORT_VERSION,
    SLEEP_QUALITY_VERSION,
    resolve_rest_target,
    summarize_environment_session_levels,
)
from zeep_pod.sessions.history_quality import released_historical_quality


class RecoveryPolicyUnitTests(unittest.TestCase):
    def test_two_mode_docs_match_recovery_v2_contract(self):
        root = Path(__file__).resolve().parent
        evidence = (root / "research/evidence-library/TWO_MODE_SCORE_EVIDENCE.md").read_text(
            encoding="utf-8"
        )
        protocol = (root / "docs/zeep-pilot-two-mode-protocol.md").read_text(
            encoding="utf-8"
        )
        for document in (evidence, protocol):
            self.assertIn("30 หรือ 90 นาที", document)
            self.assertIn("เวลาพักตามเป้าหมาย 25", document)
            self.assertIn("การตอบสนอง HR/RR 35", document)
            self.assertIn("ความต่อเนื่อง", document)
            self.assertIn("30", document)
            self.assertIn("สิ่งแวดล้อม", document)
            self.assertIn("10", document)
            self.assertIn("Coverage", document)

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

    def test_public_login_accepts_only_the_two_pilot_modes(self):
        with self.assertRaises(ValidationError):
            AuthLoginCommand(
                identifier="tester",
                password="secret",
                rest_mode="overnight",
            )

    def test_explicit_unknown_legacy_never_becomes_recovery(self):
        quality = build_sleep_quality(
            30 * 60,
            {},
            {"wake": 360},
            rest_mode="unknown_legacy",
            sensor_samples=[{
                "hr": 65.0,
                "rr": 14.0,
                "bed": "On bed",
            }] * 360,
        )

        self.assertFalse(quality["available"])
        self.assertIsNone(quality["rest_mode"]["group"])
        self.assertEqual(
            quality["validation_status"], "legacy_mode_unresolved"
        )

    def test_untouched_previous_overnight_score_remains_visible(self):
        quality = {
            "available": True,
            "score": 88,
            "quality_type": "sleep",
            "version": PREVIOUS_SLEEP_QUALITY_VERSION,
        }
        final_summary = {
            "rest_mode": "sleep",
            "session_report": {
                "version": PREVIOUS_SESSION_REPORT_VERSION,
                "rest_mode": {"group": "sleep"},
                "sleep": {"recording_s": 7 * 3600},
            },
        }

        released = released_historical_quality(final_summary, quality)

        self.assertTrue(released["available"])
        self.assertEqual(released["score"], 88)
        self.assertTrue(released["compatible_untouched_sleep_result"])

    def test_unresolved_auto_history_is_not_labelled_recovery(self):
        quality = {
            "available": True,
            "score": 71,
            "version": PREVIOUS_SLEEP_QUALITY_VERSION,
        }
        final_summary = {
            "rest_mode": "auto",
            "session_report": {
                "version": PREVIOUS_SESSION_REPORT_VERSION,
                "rest_mode": {"requested": "auto", "group": None},
                "sleep": {"recording_s": 60 * 60},
            },
        }

        released = released_historical_quality(final_summary, quality)

        self.assertFalse(released["available"])
        self.assertIsNone(released["score"])
        self.assertTrue(released["rest_mode_unresolved"])
        self.assertNotEqual(released["score_title"], "Recovery Score")

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

    def test_missing_optional_sound_reduces_coverage_not_environment_result(self):
        samples = [{
            "bed": "On bed", "hr": 62.0, "rr": 14.0,
            "temp": 24.0, "hum": 50.0, "co2": 750.0,
            "lux": 1.0, "pm2_5": 8.0, "voc": 100.0,
        } for _ in range(240)]
        quality = build_sleep_quality(
            20 * 60,
            {},
            {"wake": 240},
            rest_mode="nap_recovery",
            sensor_samples=samples,
            target_duration_s=30 * 60,
        )

        environment = quality["environment_support"]
        self.assertTrue(environment["meets_expected"])
        self.assertEqual(environment["assessment_quality"], "degraded_optional")
        self.assertEqual(environment["blocking_unavailable_count"], 0)
        self.assertEqual(environment["optional_unavailable_count"], 1)
        self.assertEqual(environment["available_factors"], 6)
        self.assertEqual(environment["expected_factors"], 7)
        self.assertEqual(environment["coverage_pct"], 85.7)


class HistoricalRecoveryGuardrailTests(unittest.TestCase):
    @staticmethod
    def _database(
        root: Path,
        *,
        duration_s: float,
        target_duration_s=None,
        sound_spike: bool = False,
        quality_version: str = "legacy-recovery-score",
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
            "version": quality_version,
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

    def test_canonical_session_intent_overrides_stale_final_summary(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            self._database(
                data_dir,
                duration_s=20 * 60,
                target_duration_s=30 * 60,
            )
            connection = sqlite3.connect(data_dir / "sessions.db")
            final_id, final_value = connection.execute(
                "SELECT id,value FROM events WHERE type='final_summary'"
            ).fetchone()
            stale_final = json.loads(final_value)
            stale_final["rest_mode"] = "sleep"
            stale_final["target_duration_s"] = 90 * 60
            connection.execute(
                "UPDATE events SET value=? WHERE id=?",
                (json.dumps(stale_final), final_id),
            )
            connection.commit()
            connection.close()

            result = rescore(
                data_dir,
                ["nap-1"],
                requested_mode=None,
                apply=True,
            )

            item = result["sessions"][0]
            self.assertEqual(item["rest_mode"]["group"], "nap_recovery")
            self.assertEqual(
                item["quality"]["rest_mode"]["target"]["seconds"],
                30 * 60,
            )
            connection = sqlite3.connect(data_dir / "sessions.db")
            persisted = json.loads(connection.execute(
                "SELECT value FROM events WHERE type='final_summary'"
            ).fetchone()[0])
            connection.close()
            self.assertEqual(persisted["rest_mode"], "nap_recovery")
            self.assertEqual(persisted["target_duration_s"], 30 * 60)

    def test_nested_legacy_target_is_reused_without_duration_inference(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            self._database(data_dir, duration_s=20 * 60)
            connection = sqlite3.connect(data_dir / "sessions.db")
            final_id, final_value = connection.execute(
                "SELECT id,value FROM events WHERE type='final_summary'"
            ).fetchone()
            final = json.loads(final_value)
            final["target_duration_s"] = None
            final["session_report"]["quality"]["duration_target"] = {
                "seconds": 30 * 60,
            }
            connection.execute(
                "UPDATE events SET value=? WHERE id=?",
                (json.dumps(final), final_id),
            )
            connection.commit()
            connection.close()

            result = rescore(
                data_dir,
                ["nap-1"],
                requested_mode=None,
                apply=False,
            )

            item = result["sessions"][0]
            self.assertEqual(item["status"], "rescored")
            self.assertEqual(
                item["quality"]["rest_mode"]["target"]["seconds"],
                30 * 60,
            )

    def test_apply_rolls_back_every_session_when_later_rebuild_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            self._database(
                data_dir,
                duration_s=20 * 60,
                target_duration_s=30 * 60,
            )
            connection = sqlite3.connect(data_dir / "sessions.db")
            first_final = connection.execute(
                "SELECT value FROM events WHERE session_id='nap-1' "
                "AND type='final_summary'"
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO sessions "
                "SELECT 'nap-2',user,username_key,datetime(start_time, '+1 day'),"
                "datetime(end_time, '+1 day'),duration,gender,rest_mode,"
                "target_duration_s FROM sessions WHERE session_id='nap-1'"
            )
            connection.commit()
            connection.close()

            original_rebuild = rescore_session_reports._rebuild
            rebuilt_sessions = []

            def fail_second(connection, session, *args, **kwargs):
                rebuilt_sessions.append(session["session_id"])
                if session["session_id"] == "nap-2":
                    raise RuntimeError("forced second Session failure")
                return original_rebuild(connection, session, *args, **kwargs)

            with patch.object(
                rescore_session_reports,
                "_rebuild",
                side_effect=fail_second,
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "forced second Session failure",
                ):
                    rescore(
                        data_dir,
                        ["nap-1", "nap-2"],
                        requested_mode=None,
                        apply=True,
                    )

            self.assertEqual(rebuilt_sessions, ["nap-1", "nap-2"])
            connection = sqlite3.connect(data_dir / "sessions.db")
            after_final = connection.execute(
                "SELECT value FROM events WHERE session_id='nap-1' "
                "AND type='final_summary'"
            ).fetchone()[0]
            audit_count = connection.execute(
                "SELECT COUNT(*) FROM events "
                "WHERE type='session_report_rescored'"
            ).fetchone()[0]
            connection.close()
            self.assertEqual(after_final, first_final)
            self.assertEqual(audit_count, 0)

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
                quality_version=SLEEP_QUALITY_VERSION,
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
            self.assertEqual(report["version"], SESSION_REPORT_VERSION)
            self.assertEqual(
                report["quality"]["version"], SLEEP_QUALITY_VERSION
            )
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
            audit = json.loads(connection.execute(
                "SELECT value FROM events "
                "WHERE type='session_report_refreshed'"
            ).fetchone()[0])
            self.assertEqual(
                audit["report_refresh_scope"],
                "full_derived_session_report",
            )
            self.assertIn("previous_report", audit)
            self.assertNotEqual(
                audit["previous_report_sha256"],
                audit["new_report_sha256"],
            )
            connection.close()

    def test_report_only_rejects_stale_quality_without_writing(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            original, stage_count, _ = self._database(
                data_dir,
                duration_s=20 * 60,
                sound_spike=True,
            )

            with self.assertRaisesRegex(
                ValueError,
                "current report contract with a stale sleep_quality",
            ):
                rescore(
                    data_dir,
                    ["nap-1"],
                    requested_mode=None,
                    apply=True,
                    report_only=True,
                )

            connection = sqlite3.connect(data_dir / "sessions.db")
            final = json.loads(connection.execute(
                "SELECT value FROM events WHERE type='final_summary'"
            ).fetchone()[0])
            self.assertEqual(final["night_summary"]["sleep_quality"], original)
            self.assertEqual(final["session_report"]["version"], "legacy-report")
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM events WHERE type='sleep_stage'"
            ).fetchone()[0], stage_count)
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM events "
                "WHERE type='session_report_refreshed'"
            ).fetchone()[0], 0)
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
