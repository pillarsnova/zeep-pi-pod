from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
import zipfile
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from operations import (
    pod_data_sync,
    pod_snapshot_export,
    pod_snapshot_lock,
    pod_snapshot_transport,
    secure_paths,
)
from operations.workstation_approval import WorkstationApprovalError


def _database(path: Path, tables: set[str], value: int = 0) -> None:
    connection = sqlite3.connect(path)
    try:
        for table in sorted(tables):
            connection.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)")
        first = sorted(tables)[0]
        connection.execute(f"INSERT INTO {first} (id) VALUES (?)", (value + 1,))
        connection.commit()
    finally:
        connection.close()


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _archive(
    path: Path,
    *,
    host: str = "pod1@example.test",
    pod_id: str = "pod-one",
    value: int = 0,
    created_at: datetime | None = None,
) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        files: dict[str, bytes] = {}
        for relative, tables in pod_data_sync.REQUIRED_DATABASES.items():
            database = root / Path(relative).name
            _database(database, tables, value)
            files[relative] = database.read_bytes()
        files["data/profiles.json"] = json.dumps({"revision": value}).encode()
        records = [
            {
                "path": name,
                "size_bytes": len(payload),
                "sha256": _digest(payload),
            }
            for name, payload in sorted(files.items())
        ]
        created = created_at or datetime.now(UTC).replace(microsecond=0)
        manifest = {
            "schema": pod_data_sync.SNAPSHOT_SCHEMA,
            "snapshot_id": pod_data_sync._records_snapshot_id(
                records, pod_id, "abc123"
            ),
            "created_at_utc": created.isoformat(),
            "source": {
                "host": host,
                "pod_id": pod_id,
                "remote_root": "/home/pod1/pi5",
                "git_commit": "abc123",
            },
            "files": records,
            "capture_window": {
                "started_at_utc": (created - timedelta(seconds=1)).isoformat(),
                "completed_at_utc": created.isoformat(),
                "cross_database_atomic": False,
            },
            "excluded_private_state": list(pod_data_sync.EXCLUDED_PRIVATE_STATE),
            "contains_personal_wellness_data": True,
        }
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest))
            for name, payload in files.items():
                archive.writestr(name, payload)


def _rewrite_manifest(
    source: Path,
    target: Path,
    update: Callable[[dict[str, object]], None],
) -> None:
    with zipfile.ZipFile(source) as current, zipfile.ZipFile(target, "w") as changed:
        for item in current.infolist():
            payload = current.read(item.filename)
            if item.filename == "manifest.json":
                manifest = json.loads(payload)
                update(manifest)
                payload = json.dumps(manifest).encode()
            changed.writestr(item, payload)


class PodDataSyncTest(unittest.TestCase):
    def _sync(self, archive: Path, destination: Path) -> dict[str, object]:
        def download(_host, _root, target, **_kwargs):
            shutil.copyfile(archive, target)

        with (
            patch.object(pod_data_sync, "require_workstation_approval"),
            patch.object(pod_data_sync, "_download_snapshot", download),
        ):
            return pod_data_sync.sync_pod_data(
                ["pod1@example.test"],
                destination=destination,
                expected_pod_id="pod-one",
            )

    def test_sync_installs_verified_snapshot_and_latest_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "source.zip"
            destination = root / "snapshots"
            _archive(archive)

            result = self._sync(archive, destination)

            snapshot = Path(str(result["path"]))
            self.assertTrue((snapshot / "data/sessions.db").is_file())
            self.assertTrue((snapshot / "data/bcg.db").is_file())
            latest = json.loads(
                (snapshot.parent / "latest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(latest["path"], str(snapshot))
            self.assertFalse((snapshot / "data/auth.db").exists())
            self.assertFalse(result["up_to_date"])
            self.assertEqual(snapshot.stat().st_mode & 0o777, 0o700)
            self.assertEqual(
                (snapshot / "data/sessions.db").stat().st_mode & 0o777, 0o600
            )
            self.assertEqual(
                (snapshot.parent / "latest.json").stat().st_mode & 0o777, 0o600
            )

    def test_same_content_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "source.zip"
            destination = root / "snapshots"
            _archive(archive)

            first = self._sync(archive, destination)
            second = self._sync(archive, destination)

            self.assertEqual(first["path"], second["path"])
            self.assertTrue(second["up_to_date"])

    def test_same_old_content_refreshes_verified_freshness(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old_archive = root / "old.zip"
            refreshed_archive = root / "refreshed.zip"
            destination = root / "snapshots"
            _archive(
                old_archive,
                created_at=datetime.now(UTC) - timedelta(days=4),
            )
            with (
                zipfile.ZipFile(old_archive) as source,
                zipfile.ZipFile(
                    refreshed_archive, "w", zipfile.ZIP_DEFLATED
                ) as refreshed,
            ):
                for item in source.infolist():
                    payload = source.read(item.filename)
                    if item.filename == "manifest.json":
                        manifest = json.loads(payload)
                        manifest["created_at_utc"] = datetime.now(UTC).isoformat()
                        payload = json.dumps(manifest).encode()
                    refreshed.writestr(item.filename, payload)

            first = self._sync(old_archive, destination)
            second = self._sync(refreshed_archive, destination)
            with patch.object(pod_data_sync, "require_workstation_approval"):
                latest = pod_data_sync.latest_verified_snapshot(
                    destination,
                    expected_pod_id="pod-one",
                    max_age_hours=72,
                )

            self.assertEqual(first["path"], second["path"])
            self.assertTrue(second["up_to_date"])
            self.assertLess(latest["age_hours"], 1)

    def test_latest_snapshot_is_scoped_to_requested_pod_and_real_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "source.zip"
            destination = root / "snapshots"
            _archive(archive)
            result = self._sync(archive, destination)
            with patch.object(pod_data_sync, "require_workstation_approval"):
                with self.assertRaisesRegex(pod_data_sync.PodDataSyncError, "No fresh"):
                    pod_data_sync.latest_verified_snapshot(
                        destination, expected_pod_id="another-pod"
                    )

            latest = Path(str(result["path"])).parent / "latest.json"
            victim = root / "victim.json"
            victim.write_text(latest.read_text(encoding="utf-8"), encoding="utf-8")
            latest.unlink()
            latest.symlink_to(victim)
            with patch.object(pod_data_sync, "require_workstation_approval"):
                fallback = pod_data_sync.latest_verified_snapshot(
                    destination, expected_pod_id="pod-one"
                )
            self.assertEqual(fallback["path"], result["path"])
            self.assertTrue(fallback["selection_provenance"]["fallback"])
            self.assertEqual(
                fallback["selection_provenance"]["reason"],
                "latest_pointer_invalid",
            )

    def test_corrupt_existing_snapshot_is_quarantined_and_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "source.zip"
            destination = root / "snapshots"
            _archive(archive)
            first = self._sync(archive, destination)
            Path(str(first["path"]), "data/profiles.json").write_text(
                "corrupt", encoding="utf-8"
            )

            second = self._sync(archive, destination)

            snapshot = Path(str(second["path"]))
            self.assertFalse(second["up_to_date"])
            self.assertEqual(
                json.loads((snapshot / "data/profiles.json").read_text())["revision"],
                0,
            )
            self.assertTrue(
                any(p.name.startswith(".rejected-") for p in snapshot.parent.iterdir())
            )

    def test_invalid_old_snapshot_cannot_escape_retention(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            destination = root / "snapshots"
            old_archive = root / "old.zip"
            current_archive = root / "current.zip"
            _archive(
                old_archive,
                value=1,
                created_at=datetime.now(UTC) - timedelta(minutes=2),
            )
            _archive(current_archive, value=2)
            old = self._sync(old_archive, destination)
            old_path = Path(str(old["path"]))
            manual = old_path.parent / "manual-review"
            manual.mkdir()
            (old_path / "data/profiles.json").write_text(
                "corrupt",
                encoding="utf-8",
            )

            current = self._sync(current_archive, destination)

            self.assertIn(
                old_path.name,
                current["quarantined_invalid_snapshots"],
            )
            self.assertFalse(old_path.exists())
            self.assertTrue(manual.is_dir())
            self.assertTrue(
                any(
                    path.name.startswith(f".rejected-{old_path.name}-")
                    for path in old_path.parent.iterdir()
                )
            )

    def test_checksum_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive_path = root / "snapshot.zip"
            extract = root / "extract"
            _archive(archive_path)
            extract.mkdir()
            manifest = pod_data_sync._read_manifest(archive_path)
            secure_paths.extract_private_zip(archive_path, extract)
            (extract / "data/profiles.json").write_text(
                '{"changed": true}', encoding="utf-8"
            )
            with self.assertRaisesRegex(pod_data_sync.PodDataSyncError, "mismatch"):
                pod_data_sync._verify_extracted_snapshot(extract, manifest)

    def test_nonfinite_manifest_error_falls_back_to_next_host(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            valid = root / "valid.zip"
            malformed = root / "malformed.zip"
            destination = root / "snapshots"
            _archive(valid, host="pod1@second.example.test")

            def inject_infinity(manifest: dict[str, object]) -> None:
                records = manifest["files"]
                assert isinstance(records, list)
                records[0]["size_bytes"] = float("inf")

            _rewrite_manifest(valid, malformed, inject_infinity)

            def download(host, _root, target, **_kwargs):
                source = malformed if "first" in host else valid
                shutil.copyfile(source, target)

            with (
                patch.object(pod_data_sync, "require_workstation_approval"),
                patch.object(pod_data_sync, "_download_snapshot", download),
            ):
                result = pod_data_sync.sync_pod_data(
                    ["pod1@first.example.test", "pod1@second.example.test"],
                    destination=destination,
                    expected_pod_id="pod-one",
                )
            self.assertEqual(result["source_host"], "pod1@second.example.test")

    def test_capture_window_contract_is_required_and_ordered(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.zip"
            invalid = root / "invalid.zip"
            _archive(source)

            def reverse_window(manifest: dict[str, object]) -> None:
                window = manifest["capture_window"]
                assert isinstance(window, dict)
                window["started_at_utc"] = (
                    datetime.now(UTC) + timedelta(minutes=2)
                ).isoformat()

            _rewrite_manifest(source, invalid, reverse_window)
            with self.assertRaisesRegex(
                pod_data_sync.PodDataSyncError, "capture window"
            ):
                pod_data_sync._read_manifest(invalid)

    def test_offline_snapshot_rejects_non_private_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "source.zip"
            destination = root / "snapshots"
            _archive(archive)
            result = self._sync(archive, destination)
            Path(str(result["path"]), "data/sessions.db").chmod(0o644)

            with patch.object(pod_data_sync, "require_workstation_approval"):
                with self.assertRaisesRegex(pod_data_sync.PodDataSyncError, "No fresh"):
                    pod_data_sync.latest_verified_snapshot(
                        destination, expected_pod_id="pod-one"
                    )

    def test_offline_lookup_falls_back_to_older_verified_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            destination = root / "snapshots"
            first_archive = root / "first.zip"
            second_archive = root / "second.zip"
            _archive(
                first_archive,
                value=1,
                created_at=datetime.now(UTC) - timedelta(minutes=2),
            )
            _archive(second_archive, value=2)
            first = self._sync(first_archive, destination)
            second = self._sync(second_archive, destination)
            Path(str(second["path"]), "data/profiles.json").write_text(
                "corrupt", encoding="utf-8"
            )

            with patch.object(pod_data_sync, "require_workstation_approval"):
                fallback = pod_data_sync.latest_verified_snapshot(
                    destination, expected_pod_id="pod-one"
                )
            self.assertEqual(fallback["path"], first["path"])
            self.assertEqual(
                fallback["selection_provenance"],
                {
                    "source": "retained_snapshot_scan",
                    "fallback": True,
                    "reason": "latest_pointer_invalid",
                    "freshness_basis": "created_at_utc",
                },
            )

    def test_sensitive_artifact_cleanup_is_bounded_by_age_and_count(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            current = datetime.now(UTC)
            for index in range(5):
                candidate = root / f".rejected-{index}"
                candidate.mkdir()
                timestamp = (current - timedelta(minutes=index)).timestamp()
                os.utime(candidate, (timestamp, timestamp))
            expired = root / ".partial-expired"
            expired.mkdir()
            old = (current - timedelta(days=2)).timestamp()
            os.utime(expired, (old, old))

            removed = secure_paths.cleanup_sensitive_artifacts(
                root, (".partial-", ".rejected-"), now=current
            )

            remaining = [path for path in root.iterdir() if path.is_dir()]
            self.assertEqual(len(remaining), 3)
            self.assertIn(".partial-expired", removed)
            self.assertEqual(len(removed), 3)

    def test_interrupted_download_directory_uses_real_cleanup_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            interrupted = root / "zeep-pod-sync-interrupted"
            interrupted.mkdir()
            archive = interrupted / "snapshot.zip"
            archive.write_bytes(b"personal wellness data")
            expired = datetime.now(UTC) - timedelta(days=2)
            os.utime(interrupted, (expired.timestamp(), expired.timestamp()))

            removed = secure_paths.cleanup_sensitive_artifacts(
                root,
                ("zeep-pod-sync-",),
            )

            self.assertEqual(removed, [interrupted.name])
            self.assertFalse(interrupted.exists())

    def test_offline_maximum_age_must_be_finite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "snapshots"
            destination.mkdir(mode=0o700)
            with patch.object(pod_data_sync, "require_workstation_approval"):
                with self.assertRaisesRegex(
                    pod_data_sync.PodDataSyncError, "maximum age"
                ):
                    pod_data_sync.latest_verified_snapshot(
                        destination,
                        expected_pod_id="pod-one",
                        max_age_hours=float("inf"),
                    )

    def test_unsafe_or_unregistered_archive_member_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            unsafe = root / "unsafe.zip"
            with zipfile.ZipFile(unsafe, "w") as archive:
                archive.writestr("manifest.json", "{}")
                archive.writestr("../escape", "bad")
            with self.assertRaisesRegex(pod_data_sync.PodDataSyncError, "unsafe"):
                pod_data_sync._read_manifest(unsafe)

            source = root / "source.zip"
            rewritten = root / "rewritten.zip"
            _archive(source)
            with (
                zipfile.ZipFile(source) as current,
                zipfile.ZipFile(rewritten, "w") as changed,
            ):
                for item in current.infolist():
                    changed.writestr(item, current.read(item.filename))
                changed.writestr("data/auth.db", b"private")
            with self.assertRaisesRegex(pod_data_sync.PodDataSyncError, "do not match"):
                pod_data_sync._read_manifest(rewritten)

    def test_invalid_remote_arguments_are_rejected_before_network(self) -> None:
        invalid = (
            ("-Ftmp", "/home/pod1/pi5"),
            ("--help", "/home/pod1/pi5"),
            ("pod1@example..test", "/home/pod1/pi5"),
            ("pod1@example.test", "/home/pod1/pi5/../../tmp"),
            ("pod1@example.test", "//home/pod1/pi5"),
        )
        with tempfile.TemporaryDirectory() as temporary:
            download = Mock()
            with (
                patch.object(pod_data_sync, "require_workstation_approval"),
                patch.object(pod_data_sync, "_download_snapshot", download),
            ):
                for host, remote_root in invalid:
                    with self.subTest(host=host, remote_root=remote_root):
                        with self.assertRaisesRegex(
                            pod_data_sync.PodDataSyncError, "invalid"
                        ):
                            pod_data_sync.sync_pod_data(
                                [host],
                                remote_root=remote_root,
                                destination=Path(temporary) / "snapshots",
                            )
            download.assert_not_called()

    def test_project_code_directory_is_rejected_as_snapshot_destination(self) -> None:
        download = Mock()
        approval = Mock()
        with (
            patch.object(pod_data_sync, "require_workstation_approval", approval),
            patch.object(pod_data_sync, "_download_snapshot", download),
        ):
            with self.assertRaisesRegex(
                pod_data_sync.PodDataSyncError, "private-data/pod-sync"
            ):
                pod_data_sync.sync_pod_data(
                    ["pod1@example.test"],
                    destination=pod_data_sync.PROJECT_ROOT / "data",
                )
        approval.assert_not_called()
        download.assert_not_called()

    def test_nested_snapshot_volume_must_also_pass_encryption_check(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "snapshots"
            download = Mock()

            def approval(path):
                if Path(path).name == "pod-one":
                    raise WorkstationApprovalError("volume not encrypted")

            with (
                patch.object(
                    pod_data_sync,
                    "require_workstation_approval",
                    side_effect=approval,
                ),
                patch.object(pod_data_sync, "_download_snapshot", download),
            ):
                with self.assertRaisesRegex(WorkstationApprovalError, "not encrypted"):
                    pod_data_sync.sync_pod_data(
                        ["pod1@example.test"],
                        destination=destination,
                        expected_pod_id="pod-one",
                    )
            download.assert_not_called()

    def test_pod_directory_symlink_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            destination = root / "snapshots"
            outside = root / "outside"
            archive = root / "source.zip"
            destination.mkdir()
            outside.mkdir()
            (destination / "pod-one").symlink_to(outside, target_is_directory=True)
            _archive(archive)

            with self.assertRaisesRegex(
                pod_data_sync.PodDataSyncError, "real directory"
            ):
                self._sync(archive, destination)
            self.assertEqual(list(outside.iterdir()), [])

    def test_lock_symlink_does_not_touch_its_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            victim = root / "victim"
            destination = root / "snapshots"
            destination.mkdir()
            victim.write_text("keep", encoding="utf-8")
            victim.chmod(0o644)
            (destination / ".sync.lock").symlink_to(victim)

            with self.assertRaisesRegex(pod_data_sync.PodDataSyncError, "lock"):
                with pod_snapshot_lock.sync_lock(destination):
                    pass
            self.assertEqual(victim.read_text(encoding="utf-8"), "keep")
            self.assertEqual(victim.stat().st_mode & 0o777, 0o644)

    def test_retention_removes_only_old_managed_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            destination = root / "snapshots"
            destination.mkdir()
            installed = []
            start = datetime.now(UTC).replace(microsecond=0) - timedelta(days=4)
            for index in range(4):
                archive = root / f"source-{index}.zip"
                _archive(archive, value=index, created_at=start + timedelta(days=index))
                manifest = pod_data_sync._read_manifest(archive)
                _, snapshot, _ = pod_data_sync._install_verified_snapshot(
                    archive, manifest, destination
                )
                installed.append(snapshot)
            manual = installed[-1].parent / "manual-review"
            manual.mkdir()

            removed = secure_paths.prune_snapshot_directories(
                pod_data_sync._managed_snapshots(installed[-1].parent),
                3,
                installed[-1],
            )

            self.assertEqual(removed, [installed[0].name])
            self.assertTrue(manual.is_dir())
            self.assertTrue(installed[-1].is_dir())

    def test_first_corrupt_host_falls_back_and_pod_id_must_match(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            destination = root / "snapshots"
            valid = root / "valid.zip"
            _archive(valid, host="pod1@second.example.test")

            def download(host, _remote_root, target, **_kwargs):
                if host == "pod1@first.example.test":
                    target.write_bytes(b"not-a-zip")
                else:
                    shutil.copyfile(valid, target)

            with (
                patch.object(pod_data_sync, "require_workstation_approval"),
                patch.object(pod_data_sync, "_download_snapshot", download),
            ):
                result = pod_data_sync.sync_pod_data(
                    ["pod1@first.example.test", "pod1@second.example.test"],
                    destination=destination,
                    expected_pod_id="pod-one",
                )
            self.assertEqual(result["source_host"], "pod1@second.example.test")

            mismatch = root / "mismatch.zip"
            _archive(mismatch, pod_id="another-pod")
            with self.assertRaisesRegex(pod_data_sync.PodDataSyncError, "Pod ID"):
                self._sync(mismatch, root / "mismatch-destination")

    def test_unapproved_workstation_stops_before_network(self) -> None:
        download = Mock()
        with (
            patch.object(
                pod_data_sync,
                "require_workstation_approval",
                side_effect=WorkstationApprovalError("not approved"),
            ),
            patch.object(pod_data_sync, "_download_snapshot", download),
        ):
            with self.assertRaisesRegex(WorkstationApprovalError, "not approved"):
                pod_data_sync.sync_pod_data(["pod1@example.test"])
        download.assert_not_called()


class PodSnapshotBoundaryTest(unittest.TestCase):
    def test_transport_uses_fixed_exporter_and_strict_host_key(self) -> None:
        captured: list[str] = []
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "snapshot.zip"

            def run(command, target, **_kwargs):
                captured.extend(command)
                target.write_bytes(b"snapshot")
                return 0, b""

            with patch.object(pod_snapshot_transport, "_run_bounded_command", run):
                pod_snapshot_transport.download_snapshot(
                    "pod1@example.test",
                    "/home/pod1/pi5",
                    archive,
                    connect_timeout_seconds=8,
                    command_timeout_seconds=30,
                )
        self.assertIn("StrictHostKeyChecking=yes", captured)
        self.assertEqual(captured[0], pod_snapshot_transport.SSH_EXECUTABLE)
        self.assertIn("ClearAllForwardings=yes", captured)
        self.assertIn("ForwardAgent=no", captured)
        self.assertIn("PermitLocalCommand=no", captured)
        remote_command = captured[-1]
        self.assertIn("PYTHONPATH=/home/pod1/pi5", remote_command)
        self.assertIn("operations.pod_snapshot_export", remote_command)
        self.assertNotIn("sh", captured)

    def test_transport_stops_before_writing_beyond_cap(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "snapshot.zip"
            command = [
                sys.executable,
                "-c",
                "import sys; sys.stdout.buffer.write(b'x' * 2048)",
            ]
            with self.assertRaisesRegex(
                pod_snapshot_transport.PodDataSyncError, "allowed limit"
            ):
                pod_snapshot_transport._run_bounded_command(
                    command,
                    archive,
                    timeout_seconds=5,
                    max_bytes=128,
                )
            self.assertFalse(archive.exists())

    def test_exporter_emits_valid_archive_and_rejects_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for relative, tables in pod_snapshot_export.REQUIRED_DATABASES.items():
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                _database(target, tables)
            (root / ".env").write_text("POD_ID=ZEEP_POD_01\n", encoding="utf-8")
            output = io.BytesIO()
            with patch.dict(os.environ, {}, clear=True):
                pod_snapshot_export.export_snapshot(root, "pod1@example.test", output)
            with zipfile.ZipFile(io.BytesIO(output.getvalue())) as archive:
                self.assertIn("manifest.json", archive.namelist())
                manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual(manifest["source"]["pod_id"], "zeep_pod_01")
            self.assertEqual(
                manifest["capture_window"]["completed_at_utc"],
                manifest["created_at_utc"],
            )
            self.assertFalse(manifest["capture_window"]["cross_database_atomic"])

            victim = root / "profile-source.json"
            victim.write_text("{}", encoding="utf-8")
            profile = root / "data/profiles.json"
            profile.symlink_to(victim)
            with self.assertRaisesRegex(
                pod_snapshot_export.PodSnapshotExportError, "symlink"
            ):
                pod_snapshot_export.export_snapshot(
                    root, "pod1@example.test", io.BytesIO()
                )


if __name__ == "__main__":
    unittest.main()
