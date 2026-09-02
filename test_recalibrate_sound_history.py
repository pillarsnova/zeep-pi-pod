import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from recalibrate_sound_history import recalibrate_sound_history


def _database(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE schema_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        INSERT INTO schema_meta(key,value) VALUES('schema_version','3');
        CREATE TABLE timeline(
          id INTEGER PRIMARY KEY,session_id TEXT,timestamp TEXT,sound REAL
        );
        CREATE TABLE events(
          id INTEGER PRIMARY KEY,session_id TEXT,timestamp TEXT,type TEXT,value TEXT
        );
        """
    )
    connection.executemany(
        "INSERT INTO timeline(session_id,timestamp,sound) VALUES(?,?,?)",
        [
            ("s1", "2026-08-27T05:00:00+07:00", 50.0),
            ("s1", "2026-08-27T05:00:05+07:00", 5.0),
            ("s1", "2026-08-27T06:00:00+07:00", 30.0),
        ],
    )
    payload = {
        "reason": "เสียงเฉลี่ย 50.0 dBA",
        "metrics": {"auxiliary_evidence": {"acoustic": {
            "mean_leq_dba": 50.0, "max_leq_dba": 52.0,
        }}},
    }
    connection.execute(
        "INSERT INTO events(session_id,timestamp,type,value) VALUES(?,?,?,?)",
        ("s1", "2026-08-27T05:00:00+07:00", "sleep_stage",
         json.dumps(payload, ensure_ascii=False)),
    )
    connection.commit()
    connection.close()


class RecalibrateSoundHistoryTests(unittest.TestCase):
    def test_preview_does_not_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "sessions.db"
            _database(database)
            result = recalibrate_sound_history(
                database, session_id="s1", before="2026-08-27T05:51:53+07:00",
                delta_db=-10, apply=False,
            )
            self.assertEqual(result["timeline_rows"], 2)
            self.assertEqual(result["held_invalid_rows"], 1)
            connection = sqlite3.connect(database)
            try:
                rows = connection.execute(
                    "SELECT sound FROM timeline ORDER BY id"
                ).fetchall()
            finally:
                connection.close()
            self.assertEqual(rows, [(50.0,), (5.0,), (30.0,)])

    def test_apply_updates_timeline_and_acoustic_evidence_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "sessions.db"
            _database(database)
            result = recalibrate_sound_history(
                database, session_id="s1", before="2026-08-27T05:51:53+07:00",
                delta_db=-10, apply=True,
            )
            self.assertEqual(result["timeline_rows"], 2)
            connection = sqlite3.connect(database)
            try:
                rows = connection.execute(
                    "SELECT sound FROM timeline ORDER BY id"
                ).fetchall()
                payload = json.loads(connection.execute(
                    "SELECT value FROM events WHERE type='sleep_stage'"
                ).fetchone()[0])
            finally:
                connection.close()
            self.assertEqual(rows, [(40.0,), (40.0,), (30.0,)])
            self.assertEqual(payload["reason"], "เสียงเฉลี่ย 40.0 dBA")
            acoustic = payload["metrics"]["auxiliary_evidence"]["acoustic"]
            self.assertEqual(acoustic["mean_leq_dba"], 40.0)
            self.assertEqual(acoustic["max_leq_dba"], 42.0)
            with self.assertRaisesRegex(RuntimeError, "already applied"):
                recalibrate_sound_history(
                    database, session_id="s1", before="2026-08-27T05:51:53+07:00",
                    delta_db=-10, apply=True,
                )


if __name__ == "__main__":
    unittest.main()
