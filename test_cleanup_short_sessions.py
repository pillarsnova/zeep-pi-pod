import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from cleanup_short_sessions import CLEANUP_ID, apply_cleanup, inspect_candidates


class CleanupShortSessionsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.data = self.root / "data"
        self.data.mkdir()
        base = Path(__file__).resolve().parent
        sessions = sqlite3.connect(self.data / "sessions.db")
        sessions.execute("PRAGMA foreign_keys=ON")
        sessions.executescript((base / "schema.sql").read_text(encoding="utf-8"))
        bcg = sqlite3.connect(self.data / "bcg.db")
        bcg.execute("PRAGMA foreign_keys=ON")
        bcg.executescript((base / "bcg_schema.sql").read_text(encoding="utf-8"))
        for session_id, username, duration, end_time in (
            ("short", "user@example.test", 7199.0, "2026-08-27T02:00:00+00:00"),
            ("exact", "user@example.test", 7200.0, "2026-08-27T04:00:00+00:00"),
            ("active", "user@example.test", None, None),
        ):
            sessions.execute(
                """INSERT INTO sessions
                   (session_id,user,username_key,start_time,end_time,duration,created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (session_id, username, username, "2026-08-27T00:00:00+00:00",
                 end_time, duration, "2026-08-27T00:00:00+00:00"),
            )
            sessions.execute(
                "INSERT INTO timeline(session_id,timestamp) VALUES (?,?)",
                (session_id, "2026-08-27T00:00:05+00:00"),
            )
            sessions.execute(
                "INSERT INTO events(session_id,timestamp,type) VALUES (?,?,?)",
                (session_id, "2026-08-27T00:00:05+00:00", "sleep_stage"),
            )
            cursor = bcg.execute(
                """INSERT INTO bcg_epochs
                   (session_id,epoch_index,tx_label,start_time,end_time,packet_count,sample_count)
                   VALUES (?,?,?,?,?,?,?)""",
                (session_id, 1, "tx1", "2026-08-27T00:00:00+00:00",
                 "2026-08-27T00:01:00+00:00", 1, 25),
            )
            bcg.execute(
                """INSERT INTO bcg_packets
                   (epoch_id,packet_index,timestamp,status_code,bcg_base64,raw_packet_base64)
                   VALUES (?,?,?,?,?,?)""",
                (cursor.lastrowid, 0, "2026-08-27T00:00:01+00:00", 0, "AA==", "AA=="),
            )
        sessions.commit()
        bcg.commit()
        sessions.close()
        bcg.close()
        (self.data / "profiles.json").write_text(json.dumps({
            "user@example.test": {
                "username": "User", "sessions": 2,
                "last_session_utc": "2026-08-27T04:00:00+00:00",
            },
        }), encoding="utf-8")
        (self.data / "baselines.json").write_text("{}", encoding="utf-8")
        (self.data / "active_session_checkpoint.json").write_text(
            json.dumps({"phase": "recording", "record": {"session_id": "active"}}),
            encoding="utf-8",
        )

    def tearDown(self):
        self.temporary.cleanup()

    def test_dry_run_is_strict_and_excludes_active(self):
        plan = inspect_candidates(self.data, 7200)
        self.assertEqual(plan["candidate_session_ids"], ["short"])
        self.assertEqual(plan["delete_counts"], {
            "sessions": 1, "timeline": 1, "events": 1,
            "bcg_epochs": 1, "bcg_packets": 1,
        })

    def test_apply_cascades_rebuilds_metadata_and_cannot_repeat(self):
        marker = self.data / f"{CLEANUP_ID}.done.json"
        result = apply_cleanup(self.data, self.root / "backup", marker, 7200)
        self.assertEqual(result["status"], "applied")
        sessions = sqlite3.connect(self.data / "sessions.db")
        bcg = sqlite3.connect(self.data / "bcg.db")
        self.assertEqual(
            [row[0] for row in sessions.execute("SELECT session_id FROM sessions ORDER BY session_id")],
            ["active", "exact"],
        )
        self.assertEqual(
            [row[0] for row in bcg.execute("SELECT session_id FROM bcg_epochs ORDER BY session_id")],
            ["active", "exact"],
        )
        sessions.close()
        bcg.close()
        profile = json.loads((self.data / "profiles.json").read_text(encoding="utf-8"))
        self.assertEqual(profile["user@example.test"]["sessions"], 1)
        self.assertEqual(
            profile["user@example.test"]["last_session_utc"],
            "2026-08-27T04:00:00+00:00",
        )
        self.assertTrue(marker.exists())
        repeated = apply_cleanup(self.data, self.root / "backup", marker, 7200)
        self.assertEqual(repeated["status"], "already_applied")


if __name__ == "__main__":
    unittest.main()
