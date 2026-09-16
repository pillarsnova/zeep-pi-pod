"""Read-only storage and end-to-end guards for historical replay."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import reclassify_sleep_history as replay
from zeep_pod.sessions.historical_replay_storage import (
    ReplayStorageError,
    load_bcg_packets,
    load_session_sleep_events,
)


class HistoricalReplayStorageTests(unittest.TestCase):
    def test_missing_database_is_not_created(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "missing"
            paths = (directory / "sessions.db", directory / "bcg.db")

            for path, loader in (
                (paths[0], load_session_sleep_events),
                (paths[1], load_bcg_packets),
            ):
                with (
                    self.subTest(path=path.name),
                    self.assertRaisesRegex(FileNotFoundError, "Replay database"),
                ):
                    loader(path, "session-1")

            self.assertFalse(directory.exists())

    def test_non_empty_dry_run_does_not_mutate_source_databases(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            self._create_history(data_dir)
            before = self._snapshot(data_dir)
            output = io.StringIO()
            arguments = argparse.Namespace(
                data_dir=data_dir,
                session_id="session-1",
                apply=False,
                force=True,
            )

            with (
                patch.object(replay, "parse_args", return_value=arguments),
                redirect_stdout(output),
            ):
                replay.main()

            result = json.loads(output.getvalue())
            self.assertEqual(result["status"], "dry_run")
            self.assertEqual(result["session_id"], "session-1")
            self.assertEqual(result["rounds_considered"], 1)
            self.assertEqual(result["raw_bcg_reconstruction"]["rounds"], 1)
            self.assertEqual(self._snapshot(data_dir), before)

    def test_storage_loaders_return_detached_mappings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            self._create_history(data_dir)

            session, events = load_session_sleep_events(
                data_dir / "sessions.db",
                "session-1",
            )
            packets = load_bcg_packets(data_dir / "bcg.db", "session-1")

            self.assertEqual(session["username_key"], "person@example.com")
            self.assertEqual(len(events), 1)
            self.assertEqual(len(packets), 1)
            self.assertIsInstance(events[0], dict)
            self.assertIsInstance(packets[0], dict)
            events[0]["value"] = "changed"
            packets[0]["heart_rate"] = -1

            _, reloaded_events = load_session_sleep_events(
                data_dir / "sessions.db",
                "session-1",
            )
            reloaded_packets = load_bcg_packets(data_dir / "bcg.db", "session-1")
            self.assertNotEqual(reloaded_events[0]["value"], "changed")
            self.assertEqual(reloaded_packets[0]["heart_rate"], 62.0)

    def test_wrong_schema_has_actionable_path_context(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "wrong-schema.db"
            with closing(sqlite3.connect(path)) as connection:
                connection.execute("CREATE TABLE unrelated (id INTEGER)")

            for loader in (
                lambda: load_session_sleep_events(path, "session-1"),
                lambda: load_bcg_packets(path, "session-1"),
            ):
                with self.assertRaisesRegex(
                    ReplayStorageError,
                    rf"Replay database schema/query failed: {path.resolve()}",
                ):
                    loader()

    @staticmethod
    def _digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @classmethod
    def _snapshot(cls, directory: Path) -> dict[str, str]:
        return {
            path.relative_to(directory).as_posix(): cls._digest(path)
            for path in sorted(directory.rglob("*"))
            if path.is_file()
        }

    @staticmethod
    def _create_history(data_dir: Path) -> None:
        with closing(sqlite3.connect(data_dir / "sessions.db")) as connection:
            connection.executescript(
                """
                CREATE TABLE sessions (
                    session_id TEXT,
                    start_time TEXT,
                    end_time TEXT,
                    username_key TEXT,
                    gender TEXT
                );
                CREATE TABLE events (
                    id INTEGER,
                    session_id TEXT,
                    timestamp TEXT,
                    type TEXT,
                    value TEXT
                );
                INSERT INTO sessions VALUES (
                    'session-1',
                    '2026-09-16T00:00:00+00:00',
                    '2026-09-16T01:00:00+00:00',
                    'person@example.com',
                    'unspecified'
                );
                """
            )
            value = {
                "state": "wake",
                "estimator_version": "legacy-estimator",
                "window_start": "2026-09-16T00:00:00+00:00",
                "window_end": "2026-09-16T00:00:30+00:00",
                "sample_interval_s": 30,
                "sample_count": 1,
                "metrics": {
                    "mean_hr": 62.0,
                    "mean_rr": 15.0,
                    "movement_ratio": 0.0,
                    "bed_status": "On bed",
                },
            }
            connection.execute(
                "INSERT INTO events VALUES (?,?,?,?,?)",
                (
                    1,
                    "session-1",
                    "2026-09-16T00:00:30+00:00",
                    "sleep_stage",
                    json.dumps(value),
                ),
            )
            connection.commit()

        with closing(sqlite3.connect(data_dir / "bcg.db")) as connection:
            connection.executescript(
                """
                CREATE TABLE bcg_epochs (
                    epoch_id INTEGER PRIMARY KEY,
                    session_id TEXT,
                    epoch_index INTEGER
                );
                CREATE TABLE bcg_packets (
                    id INTEGER PRIMARY KEY,
                    epoch_id INTEGER,
                    timestamp TEXT,
                    status_code INTEGER,
                    heart_rate REAL,
                    respiration_rate REAL,
                    bcg_base64 TEXT
                );
                INSERT INTO bcg_epochs VALUES (1, 'session-1', 1);
                INSERT INTO bcg_packets VALUES (
                    1, 1, '2026-09-16T00:00:15+00:00', 0, 62.0, 15.0, NULL
                );
                """
            )
            connection.commit()


if __name__ == "__main__":
    unittest.main()
