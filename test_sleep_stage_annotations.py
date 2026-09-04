import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from rescore_session_reports import rescore
from sleep_stage_annotations import (
    apply_annotations,
    build_annotation,
    load_annotations,
)


class SleepStageAnnotationTests(unittest.TestCase):
    def setUp(self):
        self.annotation = build_annotation(
            state="wake",
            start_time="2026-08-26T02:06:28+00:00",
            end_time="2026-08-26T02:06:58+00:00",
            source="user_reported_ground_truth",
            reason="ผู้ใช้งานยืนยันว่าตื่นแล้ว",
            created_at_utc="2026-08-27T00:00:00+00:00",
        )
        self.annotations = load_annotations([{"value": json.dumps(self.annotation)}])

    def test_period_boundaries_match_six_five_second_rounds(self):
        timestamps = [
            "2026-08-26T02:06:28.650000+00:00",
            "2026-08-26T02:06:33.650000+00:00",
            "2026-08-26T02:06:38.650000+00:00",
            "2026-08-26T02:06:43.650000+00:00",
            "2026-08-26T02:06:48.650000+00:00",
            "2026-08-26T02:06:53.650000+00:00",
            "2026-08-26T02:06:58.650000+00:00",
        ]
        matched = []
        for timestamp in timestamps:
            _, annotation = apply_annotations(
                {"state": "n1"}, timestamp, self.annotations,
            )
            matched.append(annotation is not None)
        self.assertEqual(matched, [False, True, True, True, True, True, True])

    def test_overlay_keeps_original_decision_for_audit(self):
        updated, _ = apply_annotations(
            {"state": "n1", "probabilities": {"n1": 0.68}, "confidence": "low"},
            "2026-08-26T02:06:53.650000+00:00",
            self.annotations,
        )
        self.assertEqual(updated["state"], "wake")
        self.assertEqual(updated["probabilities"]["wake"], 1.0)
        self.assertEqual(updated["stage_annotation"]["original_state"], "n1")
        self.assertFalse(updated["stage_annotation"]["aasm_psg_equivalent"])
        self.assertNotIn("ยืนยันย้อนหลัง", updated["reason"])

    def test_superseded_annotation_is_not_applied(self):
        superseded = {**self.annotation, "status": "superseded"}
        annotations = load_annotations([{"value": json.dumps(superseded)}])
        updated, annotation = apply_annotations(
            {"state": "n1"},
            "2026-08-26T02:06:53.650000+00:00",
            annotations,
        )
        self.assertEqual(updated["state"], "n1")
        self.assertIsNone(annotation)

    def test_rescore_uses_annotation_without_rewriting_raw_stage(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            connection = sqlite3.connect(data_dir / "sessions.db")
            connection.executescript("""
                CREATE TABLE sessions (
                    session_id TEXT PRIMARY KEY, user TEXT, username_key TEXT,
                    start_time TEXT, end_time TEXT, duration REAL, gender TEXT
                );
                CREATE TABLE events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT,
                    timestamp TEXT, type TEXT, value TEXT
                );
                CREATE TABLE timeline (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT,
                    timestamp TEXT, temperature REAL, humidity REAL, co2 REAL,
                    lux REAL, sound REAL, heart_rate REAL,
                    respiration_rate REAL, bed_status TEXT,
                    pm2_5 REAL, voc_index REAL
                );
            """)
            connection.execute(
                "INSERT INTO sessions VALUES (?,?,?,?,?,?,?)",
                ("s1", "akkewach", "akkewach@example.com",
                 "2026-08-26T02:00:00+00:00", "2026-08-26T02:07:00+00:00", 420, None),
            )
            for timestamp in ("02:06:33", "02:06:38", "02:06:43",
                              "02:06:48", "02:06:53", "02:06:58"):
                connection.execute(
                    "INSERT INTO events(session_id,timestamp,type,value) VALUES (?,?,?,?)",
                    ("s1", f"2026-08-26T{timestamp}+00:00", "sleep_stage",
                     json.dumps({"state": "n1", "metrics": {}})),
                )
            connection.execute(
                "INSERT INTO events(session_id,timestamp,type,value) VALUES (?,?,?,?)",
                ("s1", "2026-08-26T02:07:00+00:00", "final_summary",
                 json.dumps({"sleep_state_counts": {"n1": 6}, "night_summary": {}})),
            )
            connection.execute(
                "INSERT INTO events(session_id,timestamp,type,value) VALUES (?,?,?,?)",
                ("s1", self.annotation["created_at_utc"], "sleep_stage_annotation",
                 json.dumps(self.annotation)),
            )
            connection.commit()
            before = connection.execute(
                "SELECT value FROM events WHERE type='sleep_stage' ORDER BY id"
            ).fetchall()
            connection.close()

            result = rescore(data_dir, ["s1"], requested_mode=None, apply=True)
            self.assertEqual(result["sessions"][0]["counts"]["wake"], 6)
            self.assertEqual(result["sessions"][0]["annotated_rounds"], 6)
            connection = sqlite3.connect(data_dir / "sessions.db")
            after = connection.execute(
                "SELECT value FROM events WHERE type='sleep_stage' ORDER BY id"
            ).fetchall()
            connection.close()
            self.assertEqual(before, after)

    def test_rescore_keeps_30_second_stage_cadence_separate_from_sensor_cadence(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            connection = sqlite3.connect(data_dir / "sessions.db")
            connection.executescript("""
                CREATE TABLE sessions (
                    session_id TEXT PRIMARY KEY, user TEXT, username_key TEXT,
                    start_time TEXT, end_time TEXT, duration REAL, gender TEXT
                );
                CREATE TABLE events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT,
                    timestamp TEXT, type TEXT, value TEXT
                );
                CREATE TABLE timeline (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT,
                    timestamp TEXT, temperature REAL, humidity REAL, co2 REAL,
                    lux REAL, sound REAL, heart_rate REAL,
                    respiration_rate REAL, bed_status TEXT,
                    pm2_5 REAL, voc_index REAL
                );
            """)
            connection.execute(
                "INSERT INTO sessions VALUES (?,?,?,?,?,?,?)",
                ("s30", "user", "user@example.com",
                 "2026-09-01T00:00:00+00:00", "2026-09-01T00:02:00+00:00",
                 120, None),
            )
            for second in (30, 60, 90, 120):
                connection.execute(
                    "INSERT INTO events(session_id,timestamp,type,value) VALUES (?,?,?,?)",
                    ("s30", f"2026-09-01T00:{second // 60:02d}:{second % 60:02d}+00:00",
                     "sleep_stage", json.dumps({
                         "state": "n2", "sample_interval_s": 30,
                         "estimator_version": "stable-30s-test", "metrics": {},
                     })),
                )
            connection.execute(
                "INSERT INTO events(session_id,timestamp,type,value) VALUES (?,?,?,?)",
                ("s30", "2026-09-01T00:02:00+00:00", "final_summary",
                 json.dumps({
                     "rest_mode": "auto", "sample_interval_s": 10,
                     "sensor_sample_interval_s": 10, "night_summary": {},
                 })),
            )
            for second in range(10, 121, 10):
                connection.execute(
                    "INSERT INTO timeline(session_id,timestamp,temperature,humidity,co2,"
                    "lux,sound,heart_rate,respiration_rate,bed_status,pm2_5,voc_index) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    ("s30", f"2026-09-01T00:{second // 60:02d}:{second % 60:02d}+00:00",
                     24, 50, 700, 1, 35, 60, 13, "On bed", 5, 100),
                )
            connection.commit()
            connection.close()

            result = rescore(data_dir, ["s30"], requested_mode=None, apply=True)
            self.assertEqual(result["sessions"][0]["rounds"], 4)
            self.assertEqual(result["sessions"][0]["rest_mode"]["group"], "nap_recovery")
            self.assertEqual(result["sessions"][0]["rest_mode"]["score_title"], "Recovery Score")
            connection = sqlite3.connect(data_dir / "sessions.db")
            final = json.loads(connection.execute(
                "SELECT value FROM events WHERE type='final_summary'"
            ).fetchone()[0])
            connection.close()
            self.assertEqual(final["sample_interval_s"], 30)
            self.assertEqual(final["sensor_sample_interval_s"], 10)
            self.assertEqual(final["night_summary"]["estimated_sleep_s"], 120)
            self.assertEqual(
                final["session_report"]["sleep"]["actual_scored_s"], 120,
            )


if __name__ == "__main__":
    unittest.main()
