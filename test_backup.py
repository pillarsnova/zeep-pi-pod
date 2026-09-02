from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path

from backup import DailyBackup


class _DatabaseStub:
    def __init__(self, root: Path) -> None:
        self.sessions_path = root / "sessions.db"
        self.bcg_path = root / "bcg.db"
        for path in (self.sessions_path, self.bcg_path):
            connection = sqlite3.connect(path)
            connection.execute("CREATE TABLE sample(value TEXT)")
            connection.execute("INSERT INTO sample(value) VALUES('kept')")
            connection.commit()
            connection.close()
        self.flush_calls: list[int] = []

    def flush(self, timeout: int) -> None:
        self.flush_calls.append(timeout)


class DailyBackupTests(unittest.TestCase):
    def test_archive_contains_consistent_databases_profile_files_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database = _DatabaseStub(root)
            profile = root / "profiles.json"
            baseline = root / "baselines.json"
            profile.write_text('{"user@example.com": {}}', encoding="utf-8")
            baseline.write_text('{"user@example.com": {}}', encoding="utf-8")
            manager = DailyBackup(
                database, root / "backup", retention_count=3,
                supplemental_paths=(profile, baseline),
            )

            archive_path = manager.create_if_needed()

            self.assertEqual(database.flush_calls, [30])
            with zipfile.ZipFile(archive_path) as archive:
                self.assertEqual(set(archive.namelist()), {
                    "sessions.db", "bcg.db", "profiles.json",
                    "baselines.json", "manifest.json",
                })
                manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual(manifest["format"], "zeep-on-device-backup-v2")
            self.assertEqual(manifest["retention_count"], 3)

    def test_prune_archives_keeps_only_newest_date_named_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            backup_dir = root / "backup"
            backup_dir.mkdir()
            for name in ("20260824.zip", "20260825.zip", "20260826.zip", "20260827.zip"):
                (backup_dir / name).write_bytes(b"archive")
            (backup_dir / "deployment-snapshot.zip").write_bytes(b"code")
            manager = DailyBackup(_DatabaseStub(root), backup_dir, retention_count=2)

            removed = manager.prune_archives()

            self.assertEqual([path.name for path in removed], ["20260825.zip", "20260824.zip"])
            self.assertEqual(
                sorted(path.name for path in backup_dir.iterdir()),
                ["20260826.zip", "20260827.zip", "deployment-snapshot.zip"],
            )


if __name__ == "__main__":
    unittest.main()
