"""Hard-limit regression tests for the Pod-side snapshot exporter."""

from __future__ import annotations

import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from operations import pod_snapshot_export


def _database(path: Path, tables: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        for table in sorted(tables):
            connection.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)")
        connection.execute(f"INSERT INTO {sorted(tables)[0]} (id) VALUES (1)")
        connection.commit()
    finally:
        connection.close()


def _pod_root(root: Path) -> None:
    for relative, tables in pod_snapshot_export.REQUIRED_DATABASES.items():
        _database(root / relative, tables)


class PodSnapshotExportLimitTests(unittest.TestCase):
    def test_sqlite_page_preflight_rejects_before_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = (Path(temporary) / "pod").resolve()
            work = (Path(temporary) / "work").resolve()
            work.mkdir()
            _pod_root(root)
            relative, tables = next(
                iter(pod_snapshot_export.REQUIRED_DATABASES.items())
            )
            source = root / relative
            footprint = pod_snapshot_export._database_footprint(source, tables)
            connection = sqlite3.connect(source)
            try:
                page_size, page_count = pod_snapshot_export._database_layout(connection)
            finally:
                connection.close()
            self.assertGreaterEqual(footprint, page_size * page_count)

            with (
                patch.object(pod_snapshot_export, "MAX_MEMBER_BYTES", footprint - 1),
                patch.object(pod_snapshot_export, "MAX_TOTAL_BYTES", footprint * 10),
                patch.object(pod_snapshot_export, "MAX_ARCHIVE_BYTES", footprint * 10),
                patch.object(pod_snapshot_export, "_backup_database") as backup,
            ):
                with self.assertRaisesRegex(
                    pod_snapshot_export.PodSnapshotExportError,
                    "source exceeds",
                ):
                    pod_snapshot_export._build_archive(root, "pod.test", work)

            backup.assert_not_called()
            self.assertEqual(list(work.rglob("*")), [])

    def test_json_metadata_preflight_rejects_before_any_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = (Path(temporary) / "pod").resolve()
            work = (Path(temporary) / "work").resolve()
            work.mkdir()
            _pod_root(root)
            largest_db = max(
                pod_snapshot_export._database_footprint(root / relative, tables)
                for relative, tables in pod_snapshot_export.REQUIRED_DATABASES.items()
            )
            profile = root / "data/profiles.json"
            profile.write_text(
                json.dumps({"payload": "x" * (largest_db + 4096)}),
                encoding="utf-8",
            )
            member_cap = largest_db + 1024

            with (
                patch.object(pod_snapshot_export, "MAX_MEMBER_BYTES", member_cap),
                patch.object(pod_snapshot_export, "MAX_TOTAL_BYTES", member_cap * 10),
                patch.object(pod_snapshot_export, "MAX_ARCHIVE_BYTES", member_cap * 10),
                patch.object(pod_snapshot_export, "_backup_database") as backup,
                patch.object(pod_snapshot_export, "_copy_json") as copy_json,
            ):
                with self.assertRaisesRegex(
                    pod_snapshot_export.PodSnapshotExportError,
                    "source exceeds",
                ):
                    pod_snapshot_export._build_archive(root, "pod.test", work)

            backup.assert_not_called()
            copy_json.assert_not_called()
            self.assertEqual(list(work.rglob("*")), [])

    def test_growing_stream_never_writes_past_json_cap(self) -> None:
        source = io.BytesIO(b"x" * 24)
        destination = io.BytesIO()
        with (
            patch.object(pod_snapshot_export, "COPY_CHUNK_BYTES", 8),
            self.assertRaisesRegex(
                pod_snapshot_export.PodSnapshotExportError,
                "grew beyond",
            ),
        ):
            pod_snapshot_export._copy_stream_bounded(source, destination, 20)
        self.assertLessEqual(len(destination.getvalue()), 20)

    def test_archive_writer_and_export_output_stop_at_cap(self) -> None:
        original_writer = pod_snapshot_export._BoundedArchiveWriter
        writers: list[pod_snapshot_export._BoundedArchiveWriter] = []

        class TrackingWriter(original_writer):
            def __init__(self, path: Path, max_bytes: int) -> None:
                super().__init__(path, max_bytes)
                writers.append(self)

        with tempfile.TemporaryDirectory() as temporary:
            root = (Path(temporary) / "pod").resolve()
            _pod_root(root)
            output = io.BytesIO()
            archive_cap = 512
            with (
                patch.object(pod_snapshot_export, "MAX_ARCHIVE_BYTES", archive_cap),
                patch.object(
                    pod_snapshot_export,
                    "_BoundedArchiveWriter",
                    TrackingWriter,
                ),
                self.assertRaisesRegex(
                    pod_snapshot_export.PodSnapshotExportError,
                    "archive exceeds",
                ),
            ):
                pod_snapshot_export.export_snapshot(root, "pod.test", output)

        self.assertTrue(writers)
        self.assertLessEqual(writers[0].maximum_size, archive_cap)
        self.assertEqual(output.getvalue(), b"")

    def test_free_space_preflight_runs_before_staging(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = (Path(temporary) / "pod").resolve()
            work = (Path(temporary) / "work").resolve()
            work.mkdir()
            _pod_root(root)
            with (
                patch.object(
                    pod_snapshot_export.shutil,
                    "disk_usage",
                    return_value=Mock(free=0),
                ),
                patch.object(pod_snapshot_export, "_backup_database") as backup,
                self.assertRaisesRegex(
                    pod_snapshot_export.PodSnapshotExportError,
                    "temporary space",
                ),
            ):
                pod_snapshot_export._build_archive(root, "pod.test", work)
            backup.assert_not_called()


if __name__ == "__main__":
    unittest.main()
