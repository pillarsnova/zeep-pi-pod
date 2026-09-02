import base64
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


BASE = Path(__file__).resolve().parent


class ResetSleepDatasetTests(unittest.TestCase):
    def test_reset_keeps_selected_run_and_builds_tx1(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            sessions = sqlite3.connect(data / "sessions.db")
            sessions.executescript((BASE / "schema.sql").read_text(encoding="utf-8"))
            sessions.execute(
                """INSERT INTO sessions
                   (session_id,user,username_key,identity_subject,pod_id,zeep_public_id,
                    gender,start_time,created_at,schema_version)
                   VALUES (?,?,?,?,?,?,?,?,?,3)""",
                ("active", "Current", "current", "zeep:1", "pod-1", "1", "male",
                 "2026-08-25T20:00:00+00:00", "2026-08-25T20:00:00+00:00"),
            )
            sessions.execute(
                """INSERT INTO sessions
                   (session_id,user,username_key,gender,start_time,created_at,schema_version)
                   VALUES (?,?,?,?,?,?,3)""",
                ("old", "Old", "old", "female", "2026-08-24T20:00:00+00:00",
                 "2026-08-24T20:00:00+00:00"),
            )
            sessions.execute(
                "INSERT INTO timeline(session_id,timestamp,heart_rate) VALUES (?,?,?)",
                ("active", "2026-08-25T21:00:00+00:00", 70),
            )
            sessions.execute(
                "INSERT INTO timeline(session_id,timestamp,heart_rate) VALUES (?,?,?)",
                ("active", "2026-08-25T21:29:11+00:00", 58),
            )
            sessions.execute(
                "INSERT INTO timeline(session_id,timestamp,heart_rate) VALUES (?,?,?)",
                ("old", "2026-08-24T21:00:00+00:00", 65),
            )
            sessions.execute(
                "INSERT INTO events(session_id,timestamp,type,value) VALUES (?,?,?,?)",
                ("active", "2026-08-25T21:29:15+00:00", "sleep_stage", "{}"),
            )
            sessions.commit()
            sessions.close()

            bcg = sqlite3.connect(data / "bcg.db")
            bcg.executescript((BASE / "bcg_schema.sql").read_text(encoding="utf-8"))
            start = datetime(2026, 8, 25, 21, 29, 10, tzinfo=timezone.utc)
            epoch_id = bcg.execute(
                """INSERT INTO bcg_epochs
                   (session_id,epoch_index,tx_label,start_time,end_time,packet_count,
                    sample_count,average_hr,average_rr) VALUES (?,?,?,?,?,?,?,?,?)""",
                ("active", 1, "legacy", start.isoformat(),
                 (start + timedelta(seconds=119)).isoformat(), 120, 3000, 58, 15),
            ).lastrowid
            encoded = base64.b64encode(b"x" * 50).decode("ascii")
            raw = base64.b64encode(b"x" * 66).decode("ascii")
            for index in range(121):
                timestamp = (start + timedelta(seconds=index)).isoformat()
                bcg.execute(
                    """INSERT INTO bcg_packets
                       (epoch_id,packet_index,timestamp,sensor_packet_id,status_code,
                        heart_rate,respiration_rate,bcg_base64,raw_packet_base64)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (epoch_id, index, timestamp, index, 0, 58, 15, encoded, raw),
                )
            bcg.commit()
            bcg.close()

            (data / "profiles.json").write_text(json.dumps({
                "current": {"username": "Current", "sessions": 9},
                "old": {"username": "Old", "sessions": 4},
            }), encoding="utf-8")
            (data / "baselines.json").write_text('{"old": {"nights": 3}}', encoding="utf-8")
            (data / "sessions.jsonl.bak").write_text("legacy", encoding="utf-8")
            (data / "server.log").write_text("private log", encoding="utf-8")

            subprocess.run([
                sys.executable, str(BASE / "reset_sleep_dataset.py"),
                "--data-dir", str(data), "--session-id", "active",
                "--start-local", "2026-08-26T04:29:10",
                "--end-local", "2026-08-26T04:30:10",
                "--timezone", "Asia/Bangkok", "--tx-packets", "60",
                "--confirm", "DELETE-ALL-SLEEP-DATA",
            ], check=True, capture_output=True, text=True)

            sessions = sqlite3.connect(data / "sessions.db")
            self.assertEqual(sessions.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 1)
            self.assertEqual(sessions.execute("SELECT COUNT(*) FROM timeline").fetchone()[0], 1)
            self.assertEqual(
                sessions.execute("SELECT COUNT(*) FROM events WHERE type='tx_interval'").fetchone()[0],
                1,
            )
            self.assertEqual(
                sessions.execute("SELECT start_time FROM sessions").fetchone()[0],
                "2026-08-25T21:29:10+00:00",
            )
            sessions.close()

            bcg = sqlite3.connect(data / "bcg.db")
            self.assertEqual(
                bcg.execute("SELECT tx_label,packet_count FROM bcg_epochs ORDER BY epoch_index").fetchall(),
                [("tx1", 60), ("tx2", 60), ("tx3_partial", 1)],
            )
            self.assertEqual(bcg.execute("SELECT COUNT(*) FROM bcg_packets").fetchone()[0], 121)
            bcg.close()
            self.assertEqual(set(json.loads((data / "profiles.json").read_text())), {"current"})
            self.assertEqual(json.loads((data / "baselines.json").read_text()), {})
            self.assertFalse((data / "sessions.jsonl.bak").exists())
            self.assertEqual((data / "server.log").read_text(), "")


if __name__ == "__main__":
    unittest.main()
