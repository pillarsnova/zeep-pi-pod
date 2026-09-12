import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from trim_session import trim_session
from rescore_session_reports import rescore


class TrimSessionTests(unittest.TestCase):
    def _data_dir(self, root: Path) -> Path:
        sessions = sqlite3.connect(root / "sessions.db")
        sessions.executescript("""
            CREATE TABLE sessions (
              id INTEGER PRIMARY KEY, session_id TEXT UNIQUE, user TEXT,
              username_key TEXT, start_time TEXT, end_time TEXT, duration REAL,
              end_reason TEXT, note TEXT
            );
            CREATE TABLE timeline (
              id INTEGER PRIMARY KEY, session_id TEXT, timestamp TEXT,
              temperature REAL, humidity REAL, co2 REAL, lux REAL, sound REAL,
              heart_rate REAL, respiration_rate REAL, bed_status TEXT
            );
            CREATE TABLE events (
              id INTEGER PRIMARY KEY, session_id TEXT, timestamp TEXT,
              type TEXT, value TEXT
            );
        """)
        sessions.execute(
            "INSERT INTO sessions VALUES (1,?,?,?,?,?,?,?,?)",
            ("session-1", "user", "user", "2026-08-26T00:00:00+00:00",
             "2026-08-26T00:20:00+00:00", 1200, "logout", None))
        for index, minute in enumerate((5, 10, 15), 1):
            sessions.execute(
                "INSERT INTO timeline VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (index, "session-1", f"2026-08-26T00:{minute:02d}:00+00:00",
                 25, 50, 750, 1, 35, 60, 13, "On bed"))
        sessions.execute(
            "INSERT INTO events VALUES (1,?,?,?,?)",
            ("session-1", "2026-08-26T00:05:00+00:00", "sleep_stage",
             json.dumps({"state": "n2", "confidence": "high",
                         "estimator_version": "test-estimator"})))
        sessions.execute(
            "INSERT INTO events VALUES (2,?,?,?,?)",
            ("session-1", "2026-08-26T00:10:00+00:00", "sleep_stage",
             json.dumps({"state": "wake", "confidence": "high"})))
        sessions.execute(
            "INSERT INTO events VALUES (3,?,?,?,?)",
            ("session-1", "2026-08-26T00:20:00+00:00", "final_summary",
             json.dumps({"sleep_estimator": "test-estimator", "bed_start_s": 20})))
        sessions.commit()
        sessions.close()

        bcg = sqlite3.connect(root / "bcg.db")
        bcg.executescript("""
            CREATE TABLE bcg_epochs (
              epoch_id INTEGER PRIMARY KEY, session_id TEXT, epoch_index INTEGER,
              tx_label TEXT, start_time TEXT, end_time TEXT, packet_count INTEGER,
              sample_count INTEGER, average_hr REAL, average_rr REAL
            );
            CREATE TABLE bcg_packets (
              id INTEGER PRIMARY KEY, epoch_id INTEGER, packet_index INTEGER,
              timestamp TEXT, sensor_packet_id INTEGER, status_code INTEGER,
              heart_rate REAL, respiration_rate REAL, bcg_base64 TEXT,
              raw_packet_base64 TEXT
            );
        """)
        bcg.execute(
            "INSERT INTO bcg_epochs VALUES (1,'session-1',1,'tx1',?,?,?,?,?,?)",
            ("2026-08-26T00:04:00+00:00", "2026-08-26T00:10:00+00:00",
             3, 75, 61, 13))
        bcg.execute(
            "INSERT INTO bcg_epochs VALUES (2,'session-1',2,'tx2',?,?,?,?,?,?)",
            ("2026-08-26T00:15:00+00:00", "2026-08-26T00:15:00+00:00",
             1, 25, 70, 16))
        for row in (
            (1, 1, 1, "2026-08-26T00:05:00+00:00"),
            (2, 1, 2, "2026-08-26T00:09:00+00:00"),
            (3, 1, 3, "2026-08-26T00:10:00+00:00"),
            (4, 2, 1, "2026-08-26T00:15:00+00:00"),
        ):
            bcg.execute(
                "INSERT INTO bcg_packets VALUES (?,?,?,?,1,0,60,13,'x','y')", row)
        bcg.commit()
        bcg.close()
        return root

    def test_dry_run_then_apply_trims_and_rebuilds_summary(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = self._data_dir(Path(temporary))
            cutoff = datetime(2026, 8, 26, 0, 10, tzinfo=timezone.utc)
            dry = trim_session(data_dir, "session-1", cutoff, "battery", apply=False)
            self.assertFalse(dry["applied"])
            self.assertEqual(dry["before"]["timeline_after_cutoff"], 2)
            self.assertEqual(dry["before"]["bcg_packets_after_cutoff"], 2)

            result = trim_session(data_dir, "session-1", cutoff, "battery", apply=True)
            self.assertTrue(result["applied"])
            self.assertEqual(result["after"]["timeline_after_cutoff"], 0)
            self.assertEqual(result["after"]["bcg_packets_after_cutoff"], 0)
            self.assertEqual(result["duration_s"], 600)
            self.assertEqual(result["sleep_state_counts"]["n2"], 66)

            sessions = sqlite3.connect(data_dir / "sessions.db")
            sessions.row_factory = sqlite3.Row
            session = sessions.execute("SELECT * FROM sessions").fetchone()
            self.assertEqual(session["end_time"], "2026-08-26T00:10:00+00:00")
            final = json.loads(sessions.execute(
                "SELECT value FROM events WHERE type='final_summary'").fetchone()[0])
            self.assertEqual(final["manual_trim"]["reason"], "battery")
            self.assertIn("session_report", final)
            self.assertEqual(final["rest_mode"], "auto")
            self.assertIn("waso_proxy_s", final["night_summary"])
            self.assertEqual(
                final["night_summary"]["sleep_onset_proxy_s"],
                270,
            )
            self.assertTrue(
                final["report_sample_grid"]["classification_complete"]
            )
            self.assertEqual(
                final["report_sample_grid"]["five_state_seconds"],
                600,
            )
            accounting = final["session_report"]["sleep"][
                "classification_accounting"
            ]
            self.assertEqual(accounting["score_eligible_s"], 600)
            self.assertEqual(accounting["no_data_s"], 0)
            sessions.close()

            bcg = sqlite3.connect(data_dir / "bcg.db")
            epochs = bcg.execute(
                "SELECT tx_label,packet_count,sample_count,end_time FROM bcg_epochs").fetchall()
            self.assertEqual(epochs, [
                ("tx1_partial", 2, 50, "2026-08-26T00:09:00+00:00")])
            bcg.close()

            check = sqlite3.connect(data_dir / "sessions.db")
            before_stage_count = check.execute(
                "SELECT COUNT(*) FROM events WHERE type='sleep_stage'").fetchone()[0]
            check.close()
            dry_score = rescore(
                data_dir,
                ["session-1"],
                requested_mode="short_nap",
                requested_target_minutes=30,
                apply=False,
            )
            self.assertFalse(dry_score["applied"])
            self.assertEqual(dry_score["sessions"][0]["rest_mode"]["resolved"], "short_nap")

            applied_score = rescore(
                data_dir,
                ["session-1"],
                requested_mode="short_nap",
                requested_target_minutes=30,
                apply=True,
            )
            self.assertTrue(applied_score["applied"])
            sessions = sqlite3.connect(data_dir / "sessions.db")
            self.assertEqual(sessions.execute(
                "SELECT COUNT(*) FROM events WHERE type='sleep_stage'").fetchone()[0],
                before_stage_count)
            self.assertEqual(sessions.execute(
                "SELECT COUNT(*) FROM events WHERE type='session_report_rescored'"
            ).fetchone()[0], 1)
            final = json.loads(sessions.execute(
                "SELECT value FROM events WHERE type='final_summary'").fetchone()[0])
            self.assertEqual(final["rest_mode"], "short_nap")
            sessions.close()

    def test_trim_scores_legacy_provisional_as_continuity_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = self._data_dir(Path(temporary))
            sessions = sqlite3.connect(data_dir / "sessions.db")
            sessions.execute(
                "DELETE FROM events WHERE type='sleep_stage'"
            )
            sessions.execute("DELETE FROM timeline")
            stage_rows = (
                ("2026-08-26T00:05:00+00:00", True, False),
                ("2026-08-26T00:05:30+00:00", True, False),
                ("2026-08-26T00:06:00+00:00", False, True),
            )
            for index, (timestamp, provisional, eligible) in enumerate(
                stage_rows,
                10,
            ):
                value = {
                    "state": "n2",
                    "sample_interval_s": 30,
                    "estimator_version": "continuity-test",
                    "decision_kind": "continuity_hold",
                    "held_previous_state": True,
                    "provisional": provisional,
                    "pending_state": "n3",
                    "score_attribution_state": "n2",
                    "challenger_counted_as_new_state": False,
                    "score_eligible": eligible,
                    "excluded_from_score": not eligible,
                    "excluded_from_personal_baseline": True,
                }
                sessions.execute(
                    "INSERT INTO events VALUES (?,?,?,?,?)",
                    (
                        index,
                        "session-1",
                        timestamp,
                        "sleep_stage",
                        json.dumps(value),
                    ),
                )
                sessions.execute(
                    "INSERT INTO timeline VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        index,
                        "session-1",
                        timestamp,
                        25,
                        50,
                        750,
                        1,
                        35,
                        60,
                        13,
                        "On bed",
                    ),
                )
            final = {
                "sleep_estimator": "continuity-test",
                "rest_mode": "overnight",
                "sample_interval_s": 30,
                "timeline_schema_version": 4,
            }
            sessions.execute(
                "UPDATE events SET value=? WHERE type='final_summary'",
                (json.dumps(final),),
            )
            sessions.commit()
            sessions.close()

            result = trim_session(
                data_dir,
                "session-1",
                datetime(2026, 8, 26, 0, 10, tzinfo=timezone.utc),
                "continuity-regression",
                apply=True,
            )

            self.assertEqual(result["sleep_state_counts"]["n2"], 11)
            self.assertEqual(result["sleep_score_state_counts"]["n2"], 11)
            sessions = sqlite3.connect(data_dir / "sessions.db")
            persisted = json.loads(sessions.execute(
                "SELECT value FROM events WHERE type='final_summary'"
            ).fetchone()[0])
            sessions.close()
            self.assertEqual(persisted["sleep_state_counts"]["n2"], 11)
            self.assertEqual(
                persisted["sleep_score_state_counts"]["n2"],
                11,
            )
            self.assertEqual(
                persisted["night_summary"]["estimated_sleep_s"],
                330,
            )
            self.assertEqual(
                persisted["night_summary"]["sleep_quality"][
                    "actual_scored_s"
                ],
                600,
            )
            sleep = persisted["session_report"]["sleep"]
            self.assertEqual(sleep["continuity_carried_forward_s"], 570)
            self.assertEqual(sleep["provisional_hold_s"], 60)
            self.assertEqual(sleep["actual_scored_s"], 600)
            self.assertEqual(sleep["excluded_from_score_s"], 0)
            self.assertTrue(
                sleep["classification_accounting"][
                    "score_stage_total_reconciles"
                ]
            )

    def test_trim_ignores_legacy_no_data_but_preserves_off_bed(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = self._data_dir(Path(temporary))
            sessions = sqlite3.connect(data_dir / "sessions.db")
            sessions.execute(
                "DELETE FROM events WHERE type IN "
                "('sleep_stage','sleep_stage_status')"
            )
            sessions.execute("DELETE FROM timeline")

            events = (
                (
                    10,
                    "2026-08-26T00:02:00+00:00",
                    "sleep_stage",
                    {
                        "state": "n2",
                        "attribution_start": (
                            "2026-08-26T00:01:30+00:00"
                        ),
                        "attribution_end": (
                            "2026-08-26T00:02:00+00:00"
                        ),
                        "score_eligible": False,
                        "excluded_from_score": True,
                    },
                ),
                (
                    11,
                    "2026-08-26T00:04:00+00:00",
                    "sleep_stage_status",
                    {
                        "state": "no_data",
                        "data_status": "missing_current_vitals",
                        "attribution_start": (
                            "2026-08-26T00:03:30+00:00"
                        ),
                        "attribution_end": (
                            "2026-08-26T00:04:00+00:00"
                        ),
                    },
                ),
                (
                    12,
                    "2026-08-26T00:06:00+00:00",
                    "sleep_stage_status",
                    {
                        "state": "off_bed",
                        "data_status": "confirmed_off_bed",
                        "attribution_start": (
                            "2026-08-26T00:05:00+00:00"
                        ),
                        "attribution_end": (
                            "2026-08-26T00:06:00+00:00"
                        ),
                    },
                ),
                (
                    13,
                    "2026-08-26T00:08:00+00:00",
                    "sleep_stage",
                    {
                        "state": "n2",
                        "attribution_start": (
                            "2026-08-26T00:07:30+00:00"
                        ),
                        "attribution_end": (
                            "2026-08-26T00:08:00+00:00"
                        ),
                    },
                ),
            )
            for event_id, timestamp, event_type, value in events:
                sessions.execute(
                    "INSERT INTO events VALUES (?,?,?,?,?)",
                    (
                        event_id,
                        "session-1",
                        timestamp,
                        event_type,
                        json.dumps(value),
                    ),
                )
            sessions.execute(
                "UPDATE events SET value=? WHERE type='final_summary'",
                (json.dumps({
                    "sleep_estimator": "continuity-test",
                    "rest_mode": "overnight",
                    "sample_interval_s": 30,
                    "sensor_sample_interval_s": 30,
                    "timeline_schema_version": 4,
                }),),
            )
            sessions.commit()
            sessions.close()

            trim_session(
                data_dir,
                "session-1",
                datetime(2026, 8, 26, 0, 10, tzinfo=timezone.utc),
                "off-bed-regression",
                apply=True,
            )

            sessions = sqlite3.connect(data_dir / "sessions.db")
            persisted = json.loads(sessions.execute(
                "SELECT value FROM events WHERE type='final_summary'"
            ).fetchone()[0])
            sessions.close()
            grid = persisted["report_sample_grid"]
            self.assertTrue(grid["classification_complete"])
            self.assertEqual(grid["five_state_seconds"], 450)
            self.assertEqual(grid["off_bed_seconds"], 150)
            self.assertEqual(grid["unattributed_seconds"], 0)
            self.assertEqual(persisted["sleep_state_counts"]["wake"], 3)
            self.assertEqual(persisted["sleep_state_counts"]["n2"], 12)
            self.assertEqual(
                persisted["sleep_state_counts"],
                persisted["sleep_score_state_counts"],
            )
            accounting = persisted["session_report"]["sleep"][
                "classification_accounting"
            ]
            self.assertEqual(accounting["score_eligible_s"], 450)
            self.assertEqual(accounting["off_bed_s"], 150)
            self.assertEqual(accounting["no_data_s"], 0)
            self.assertTrue(accounting["arithmetic_invariant"]["holds"])


if __name__ == "__main__":
    unittest.main()
