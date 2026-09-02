"""Consistent, bounded daily backups for on-device ZEEP data.

Only date-named archives are managed by the retention policy. Deployment
snapshots, if an operator creates one manually, are deliberately left alone.
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from database import DatabaseManager


class DailyBackup:
    def __init__(
        self,
        database: DatabaseManager,
        backup_dir: Path,
        *,
        retention_count: int = 3,
        supplemental_paths: Iterable[Path] = (),
    ) -> None:
        self.database = database
        self.backup_dir = backup_dir
        self.retention_count = max(1, int(retention_count))
        self.supplemental_paths = tuple(Path(path) for path in supplemental_paths)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="daily-backup", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(2)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.create_if_needed()
            except Exception as exc:
                print(f"[BACKUP] failed: {exc}")
            self._stop.wait(300)

    def _managed_archives(self) -> list[Path]:
        """Return newest-first archives created by this service."""
        return sorted(
            self.backup_dir.glob("[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9].zip"),
            reverse=True,
        )

    def prune_archives(self) -> list[Path]:
        """Bound disk use without deleting manually named recovery bundles."""
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        removed: list[Path] = []
        for archive in self._managed_archives()[self.retention_count:]:
            archive.unlink(missing_ok=True)
            removed.append(archive)
        return removed

    def create_if_needed(self) -> Path:
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        destination = self.backup_dir / f"{datetime.now().strftime('%Y%m%d')}.zip"
        if destination.exists():
            self.prune_archives()
            return destination

        self.database.flush(30)
        with tempfile.TemporaryDirectory(prefix="zeep-backup-") as temp:
            temp_dir = Path(temp)
            copies: list[Path] = []
            for source_path in (self.database.sessions_path, self.database.bcg_path):
                copy_path = temp_dir / source_path.name
                source = sqlite3.connect(source_path)
                target = sqlite3.connect(copy_path)
                try:
                    source.backup(target)
                finally:
                    source.close()
                    target.close()
                copies.append(copy_path)

            manifest = {
                "format": "zeep-on-device-backup-v2",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "retention_count": self.retention_count,
                "files": [path.name for path in copies],
            }
            pending = destination.with_suffix(".zip.tmp")
            with zipfile.ZipFile(pending, "w", zipfile.ZIP_DEFLATED) as archive:
                for copy in copies:
                    archive.write(copy, copy.name)
                for source_path in self.supplemental_paths:
                    if source_path.is_file():
                        archive.write(source_path, source_path.name)
                        manifest["files"].append(source_path.name)
                archive.writestr(
                    "manifest.json",
                    json.dumps(manifest, ensure_ascii=False, indent=2),
                )
            pending.replace(destination)

        self.prune_archives()
        return destination
