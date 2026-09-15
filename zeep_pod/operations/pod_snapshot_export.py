"""Read-only snapshot exporter executed on a ZEEP Pod."""

from __future__ import annotations

import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, NamedTuple

from .pod_snapshot_errors import PodDataSyncError
from .pod_snapshot_validation import parse_timestamp, records_snapshot_id
from .secure_paths import sha256_file as _sha256
from .secure_paths import strict_json_loads

SNAPSHOT_SCHEMA = "zeep-pod-workstation-snapshot-v1"
REQUIRED_DATABASES = {
    "data/sessions.db": {"sessions", "timeline", "events"},
    "data/bcg.db": {"bcg_epochs", "bcg_packets"},
}
OPTIONAL_FILES = (
    "data/profiles.json",
    "data/baselines.json",
    "data/output_labels.json",
    "data/wellness-history-promotion-latest.json",
    "data/sleep-history-reclassification-latest.json",
    "calibration.json",
)
EXCLUDED_PRIVATE_STATE = (
    "data/auth.db",
    "data/local_admins.json",
    "data/occupancy.db",
    "data/active_session_checkpoint.json",
    "data/last_sensor_frame.json",
    "data/aircon_control_state.json",
)
MAX_MEMBER_BYTES = 3 * 1024**3
MAX_TOTAL_BYTES = 8 * 1024**3
MAX_ARCHIVE_BYTES = 4 * 1024**3
MAX_MANIFEST_BYTES = 1024**2
MAX_CAPTURE_WINDOW_SECONDS = 600
COPY_CHUNK_BYTES = 64 * 1024


class _ExportSource(NamedTuple):
    relative: str
    source: Path
    estimated_bytes: int
    expected_tables: frozenset[str] | None = None


class PodSnapshotExportError(RuntimeError):
    """Raised when the Pod cannot create a safe snapshot."""


def validate_capture_window(manifest: dict[str, Any]) -> None:
    """Validate the bounded, explicitly non-atomic cross-database capture."""
    created = parse_timestamp(manifest.get("created_at_utc"))
    window = manifest.get("capture_window")
    if not isinstance(window, dict) or window.get("cross_database_atomic") is not False:
        raise PodDataSyncError("Snapshot capture window is invalid")
    started = parse_timestamp(window.get("started_at_utc"))
    completed = parse_timestamp(window.get("completed_at_utc"))
    duration = (completed - started).total_seconds()
    if not 0 <= duration <= MAX_CAPTURE_WINDOW_SECONDS or completed > created:
        raise PodDataSyncError("Snapshot capture window is invalid")


def _safe_source(root: Path, relative: str) -> Path:
    parts = PurePosixPath(relative).parts
    candidate = root
    for part in parts:
        candidate /= part
        if candidate.is_symlink():
            raise PodSnapshotExportError(f"symlink source is not allowed: {relative}")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise PodSnapshotExportError(f"source escapes Pod root: {relative}") from exc
    if not resolved.is_file():
        raise PodSnapshotExportError(f"source is not a file: {relative}")
    return resolved


def _table_names(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    return {str(row[0]) for row in rows}


def _database_layout(connection: sqlite3.Connection) -> tuple[int, int]:
    page_size = int(connection.execute("PRAGMA page_size").fetchone()[0])
    page_count = int(connection.execute("PRAGMA page_count").fetchone()[0])
    if page_size <= 0 or page_count < 0:
        raise PodSnapshotExportError("SQLite page metadata is invalid")
    return page_size, page_count


def _database_footprint(source: Path, tables: set[str]) -> int:
    before = source.lstat()
    connection = sqlite3.connect(f"file:{source}?mode=ro", uri=True, timeout=30)
    try:
        missing = tables - _table_names(connection)
        if missing:
            raise PodSnapshotExportError(
                f"SQLite schema missing {','.join(sorted(missing))}: {source.name}"
            )
        page_size, page_count = _database_layout(connection)
    finally:
        connection.close()
    after = source.lstat()
    if source.is_symlink() or (before.st_dev, before.st_ino) != (
        after.st_dev,
        after.st_ino,
    ):
        raise PodSnapshotExportError(f"SQLite source changed: {source.name}")
    return max(before.st_size, page_size * page_count)


def _backup_database(
    source: Path,
    destination: Path,
    tables: set[str],
    max_bytes: int,
) -> int:
    before = source.lstat()
    source_db = sqlite3.connect(f"file:{source}?mode=ro", uri=True, timeout=30)
    target_db = sqlite3.connect(destination)
    try:
        opened = source.lstat()
        if source.is_symlink() or (before.st_dev, before.st_ino) != (
            opened.st_dev,
            opened.st_ino,
        ):
            raise PodSnapshotExportError(f"SQLite source changed: {source.name}")
        page_size, page_count = _database_layout(source_db)
        projected_bytes = max(opened.st_size, page_size * page_count)
        if projected_bytes > max_bytes:
            raise PodSnapshotExportError(
                f"SQLite source exceeds the allowed limit: {source.name}"
            )
        max_pages = max_bytes // page_size
        if max_pages < page_count:
            raise PodSnapshotExportError(
                f"SQLite source exceeds the allowed limit: {source.name}"
            )
        target_db.execute(f"PRAGMA page_size={page_size}")
        target_db.execute(f"PRAGMA max_page_count={max_pages}")

        def stop_growth(_status: int, _remaining: int, total: int) -> None:
            if total * page_size > max_bytes:
                raise PodSnapshotExportError(
                    f"SQLite source grew beyond the allowed limit: {source.name}"
                )

        source_db.backup(target_db, pages=16, progress=stop_growth)
        check = target_db.execute("PRAGMA quick_check").fetchone()
        missing = tables - _table_names(target_db)
        if not check or check[0] != "ok":
            raise PodSnapshotExportError(f"SQLite quick_check failed: {source.name}")
        if missing:
            raise PodSnapshotExportError(
                f"SQLite schema missing {','.join(sorted(missing))}: {source.name}"
            )
        finished = source.lstat()
        if source.is_symlink() or (before.st_dev, before.st_ino) != (
            finished.st_dev,
            finished.st_ino,
        ):
            raise PodSnapshotExportError(f"SQLite source changed: {source.name}")
    finally:
        source_db.close()
        target_db.close()
    copied_bytes = destination.stat().st_size
    if copied_bytes > max_bytes:
        destination.unlink(missing_ok=True)
        raise PodSnapshotExportError(
            f"SQLite snapshot exceeds the allowed limit: {source.name}"
        )
    return copied_bytes


def _git_commit(root: Path) -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _file_records(work: Path, included: list[str]) -> list[dict[str, object]]:
    return [
        {
            "path": relative,
            "size_bytes": (work / relative).stat().st_size,
            "sha256": _sha256(work / relative),
        }
        for relative in sorted(included)
    ]


def _copy_stream_bounded(
    source: BinaryIO, destination: BinaryIO, max_bytes: int
) -> int:
    """Copy a stream without ever writing beyond ``max_bytes``."""
    copied = 0
    while True:
        remaining = max_bytes - copied
        chunk = source.read(min(COPY_CHUNK_BYTES, remaining + 1))
        if not chunk:
            return copied
        if len(chunk) > remaining:
            raise PodSnapshotExportError("source grew beyond the allowed limit")
        destination.write(chunk)
        copied += len(chunk)


def _copy_json(source: Path, destination: Path, max_bytes: int) -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(source, flags)
    try:
        opened = os.fstat(descriptor)
        linked = source.lstat()
        if source.is_symlink() or (opened.st_dev, opened.st_ino) != (
            linked.st_dev,
            linked.st_ino,
        ):
            raise PodSnapshotExportError(f"JSON source changed: {source.name}")
        if opened.st_size > max_bytes:
            raise PodSnapshotExportError(
                f"JSON source exceeds the allowed limit: {source.name}"
            )
        with os.fdopen(descriptor, "rb") as input_file:
            descriptor = -1
            with destination.open("xb") as output_file:
                copied_bytes = _copy_stream_bounded(
                    input_file,
                    output_file,
                    max_bytes,
                )
            finished = os.fstat(input_file.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    linked = source.lstat()
    if (
        source.is_symlink()
        or (opened.st_dev, opened.st_ino)
        != (
            finished.st_dev,
            finished.st_ino,
        )
        or (opened.st_dev, opened.st_ino) != (linked.st_dev, linked.st_ino)
    ):
        destination.unlink(missing_ok=True)
        raise PodSnapshotExportError(f"JSON source changed: {source.name}")
    try:
        strict_json_loads(destination.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, ValueError):
        destination.unlink(missing_ok=True)
        raise
    return copied_bytes


def _app_pod_id(value: str) -> str:
    """Mirror the application POD_ID normalisation without importing app code."""
    raw = value.strip().lower()
    clean = "".join(char if char.isalnum() or char in "-_" else "-" for char in raw)
    return clean.strip("-") or "pod-unknown"


def _pod_id_from_root(root: Path) -> str:
    """Resolve POD_ID as the service does, including its local .env configuration."""
    configured = os.getenv("POD_ID", "").strip()
    dotenv = root / ".env"
    if not configured and dotenv.exists():
        source = _safe_source(root, ".env")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(source, flags)
        try:
            with os.fdopen(descriptor, encoding="utf-8") as handle:
                descriptor = -1
                for line in handle:
                    key, separator, value = line.partition("=")
                    if separator and key.strip() == "POD_ID":
                        configured = value.strip().strip("\"'")
                        break
        finally:
            if descriptor >= 0:
                os.close(descriptor)
    return _app_pod_id(configured or socket.gethostname())


def _manifest_reserve(source_count: int) -> int:
    expected = max(4096, (source_count + 1) * 2048)
    return min(MAX_MANIFEST_BYTES, expected)


def _collect_sources(root: Path) -> list[_ExportSource]:
    plans: list[_ExportSource] = []
    for relative, expected_tables in REQUIRED_DATABASES.items():
        source = _safe_source(root, relative)
        plans.append(
            _ExportSource(
                relative=relative,
                source=source,
                estimated_bytes=_database_footprint(source, expected_tables),
                expected_tables=frozenset(expected_tables),
            )
        )
    for relative in OPTIONAL_FILES:
        unresolved = root / relative
        if unresolved.is_symlink():
            raise PodSnapshotExportError(f"symlink source is not allowed: {relative}")
        if unresolved.exists():
            source = _safe_source(root, relative)
            plans.append(
                _ExportSource(
                    relative=relative,
                    source=source,
                    estimated_bytes=source.stat().st_size,
                )
            )
    return plans


def _validate_source_plan(plans: list[_ExportSource]) -> int:
    if min(MAX_MEMBER_BYTES, MAX_TOTAL_BYTES, MAX_ARCHIVE_BYTES) <= 0:
        raise PodSnapshotExportError("snapshot size limits are invalid")
    reserve = _manifest_reserve(len(plans))
    if reserve >= MAX_TOTAL_BYTES:
        raise PodSnapshotExportError("snapshot manifest exceeds the allowed limit")
    for plan in plans:
        if plan.estimated_bytes < 0 or plan.estimated_bytes > MAX_MEMBER_BYTES:
            raise PodSnapshotExportError(
                f"snapshot source exceeds the allowed limit: {plan.relative}"
            )
    total = sum(plan.estimated_bytes for plan in plans)
    if total > MAX_TOTAL_BYTES - reserve:
        raise PodSnapshotExportError("snapshot content exceeds the allowed limit")
    return total


def _ensure_temp_space(work: Path, estimated_sources: int, source_count: int) -> None:
    reserve = _manifest_reserve(source_count)
    staged = estimated_sources + reserve
    zip_overhead = 64 * 1024 + source_count * 1024
    expected_archive = min(MAX_ARCHIVE_BYTES, staged + zip_overhead)
    if shutil.disk_usage(work).free < staged + expected_archive:
        raise PodSnapshotExportError("insufficient temporary space for snapshot")


def _stage_sources(work: Path, plans: list[_ExportSource]) -> list[str]:
    included: list[str] = []
    copied_total = 0
    reserve = _manifest_reserve(len(plans))
    for plan in plans:
        remaining = MAX_TOTAL_BYTES - reserve - copied_total
        max_bytes = min(MAX_MEMBER_BYTES, remaining)
        if max_bytes <= 0 or plan.estimated_bytes > max_bytes:
            raise PodSnapshotExportError("snapshot content exceeds the allowed limit")
        destination = work / plan.relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if plan.expected_tables is not None:
            copied = _backup_database(
                plan.source,
                destination,
                set(plan.expected_tables),
                max_bytes,
            )
        else:
            copied = _copy_json(plan.source, destination, max_bytes)
        copied_total += copied
        included.append(plan.relative)
    return included


class _BoundedArchiveWriter:
    """Seekable binary file that refuses growth beyond a hard byte cap."""

    def __init__(self, path: Path, max_bytes: int) -> None:
        self._handle = path.open("x+b")
        self._max_bytes = max_bytes
        self.maximum_size = 0

    def write(self, data: bytes) -> int:
        end = self._handle.tell() + len(data)
        if end > self._max_bytes:
            raise PodSnapshotExportError("snapshot archive exceeds the allowed limit")
        written = self._handle.write(data)
        self.maximum_size = max(self.maximum_size, self._handle.tell())
        return written

    def __getattr__(self, name: str) -> Any:
        return getattr(self._handle, name)


def _write_archive(work: Path, manifest_path: Path, included: list[str]) -> Path:
    archive_path = work / "snapshot.zip"
    output = _BoundedArchiveWriter(archive_path, MAX_ARCHIVE_BYTES)
    try:
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(manifest_path, "manifest.json")
            for relative in included:
                archive.write(work / relative, relative)
    except Exception:
        archive_path.unlink(missing_ok=True)
        raise
    finally:
        output.close()
    return archive_path


def _write_manifest(work: Path, manifest: dict[str, Any], content_bytes: int) -> Path:
    encoded = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode()
    limit = min(MAX_MANIFEST_BYTES, MAX_MEMBER_BYTES)
    if len(encoded) > limit or content_bytes + len(encoded) > MAX_TOTAL_BYTES:
        raise PodSnapshotExportError("snapshot manifest exceeds the allowed limit")
    path = work / "manifest.json"
    with path.open("xb") as handle:
        handle.write(encoded)
    return path


def _build_archive(root: Path, source_label: str, work: Path) -> Path:
    started_at = datetime.now(UTC)
    plans = _collect_sources(root)
    estimated_sources = _validate_source_plan(plans)
    _ensure_temp_space(work, estimated_sources, len(plans))
    included = _stage_sources(work, plans)

    records = _file_records(work, included)
    content_bytes = sum(int(record["size_bytes"]) for record in records)
    pod_id = _pod_id_from_root(root)
    git_commit = _git_commit(root)
    completed_at = datetime.now(UTC)
    manifest = {
        "schema": SNAPSHOT_SCHEMA,
        "snapshot_id": records_snapshot_id(records, pod_id, git_commit),
        "created_at_utc": completed_at.isoformat(),
        "source": {
            "host": source_label,
            "pod_id": pod_id,
            "remote_root": str(root),
            "git_commit": git_commit,
        },
        "capture_window": {
            "started_at_utc": started_at.isoformat(),
            "completed_at_utc": completed_at.isoformat(),
            "cross_database_atomic": False,
        },
        "files": records,
        "excluded_private_state": list(EXCLUDED_PRIVATE_STATE),
        "contains_personal_wellness_data": True,
    }
    manifest_path = _write_manifest(work, manifest, content_bytes)
    return _write_archive(work, manifest_path, included)


def export_snapshot(root: Path, source_label: str, output: BinaryIO) -> None:
    """Write one validated ZIP snapshot to a binary stream."""
    resolved_root = root.expanduser().resolve(strict=True)
    if not resolved_root.is_dir():
        raise PodSnapshotExportError("Pod project root is unavailable")
    with tempfile.TemporaryDirectory(prefix="zeep-workstation-export-") as temporary:
        archive_path = _build_archive(resolved_root, source_label, Path(temporary))
        with archive_path.open("rb") as source:
            _copy_stream_bounded(source, output, MAX_ARCHIVE_BYTES)


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: pod_snapshot_export ROOT SOURCE_LABEL", file=sys.stderr)
        return 2
    try:
        export_snapshot(Path(sys.argv[1]), sys.argv[2], sys.stdout.buffer)
    except (OSError, ValueError, sqlite3.Error, PodSnapshotExportError) as exc:
        print(f"snapshot export failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
