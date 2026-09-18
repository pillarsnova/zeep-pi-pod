"""Small filesystem helpers for privacy-sensitive local snapshots."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import secrets
import shutil
import sqlite3
import stat
import tempfile
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any

from .pod_snapshot_errors import PodDataSyncError

PRIVATE_FILE_MODE = 0o600
PRIVATE_DIRECTORY_MODE = 0o700
SENSITIVE_ARTIFACT_TTL = timedelta(hours=24)
SENSITIVE_ARTIFACT_MAX_COUNT = 3
MANAGED_SNAPSHOT_NAME = re.compile(r"\d{8}T\d{6}Z-[0-9a-f]{12}")


def strict_json_loads(content: str | bytes) -> Any:
    """Parse standards-compliant JSON and reject NaN/Infinity extensions."""

    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON number is not allowed: {value}")

    return json.loads(content, parse_constant=reject_constant)


def safe_archive_path(name: str) -> bool:
    """Return whether a ZIP member is a non-traversing relative path."""
    path = PurePosixPath(name)
    return bool(name) and not path.is_absolute() and ".." not in path.parts


def sha256_file(path: Path) -> str:
    """Return a streaming SHA-256 digest for one local file."""
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def validated_snapshot_destination(
    value: Path,
    *,
    project_root: Path,
    project_destination: Path,
) -> Path:
    """Keep in-repository snapshots inside the ignored private-data tree."""
    destination = value.expanduser().resolve()
    allowed = (project_root / project_destination).resolve()
    try:
        destination.relative_to(project_root)
    except ValueError:
        return destination
    try:
        destination.relative_to(allowed)
    except ValueError as exc:
        raise PodDataSyncError(
            "Snapshot destination inside the project must use private-data/pod-sync"
        ) from exc
    return destination


def real_child_directory(parent: Path, name: str) -> Path:
    """Create or validate one real directory directly below ``parent``."""
    parent = parent.resolve(strict=True)
    candidate = parent / name
    try:
        current = candidate.lstat()
    except FileNotFoundError:
        try:
            candidate.mkdir(mode=0o700)
        except FileExistsError:
            current = candidate.lstat()
        else:
            current = candidate.lstat()
    if stat.S_ISLNK(current.st_mode) or not stat.S_ISDIR(current.st_mode):
        raise PodDataSyncError("Snapshot directory must be a real directory")
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(parent)
    except ValueError as exc:
        raise PodDataSyncError("Snapshot directory escapes its destination") from exc
    os.chmod(resolved, 0o700)
    return resolved


def atomic_json(path: Path, payload: dict[str, Any], *, mode: int = 0o600) -> None:
    """Replace a JSON file without following a predictable temporary symlink."""
    parent = path.parent.resolve(strict=True)
    target = parent / path.name
    descriptor, pending_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=parent,
    )
    pending = Path(pending_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fchmod(handle.fileno(), mode)
            os.fsync(handle.fileno())
        pending.replace(target)
        if hasattr(os, "O_DIRECTORY"):
            directory = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    except Exception:
        pending.unlink(missing_ok=True)
        raise


def read_private_json(
    path: Path, *, max_bytes: int = 64 * 1024
) -> tuple[Any, os.stat_result]:
    """Read one owner-only JSON file through the same verified descriptor."""
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise PodDataSyncError("Private JSON file could not be opened safely") from exc
    try:
        opened = os.fstat(descriptor)
        linked = path.lstat()
        if (
            not stat.S_ISREG(opened.st_mode)
            or stat.S_ISLNK(linked.st_mode)
            or (opened.st_dev, opened.st_ino) != (linked.st_dev, linked.st_ino)
        ):
            raise PodDataSyncError("Private JSON file must be a real local file")
        with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
            descriptor = -1
            content = handle.read(max_bytes + 1)
        if len(content.encode("utf-8")) > max_bytes:
            raise PodDataSyncError("Private JSON file is too large")
        return strict_json_loads(content), opened
    except (OSError, ValueError) as exc:
        raise PodDataSyncError("Private JSON file is invalid") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def require_regular_file(path: Path, message: str) -> os.stat_result:
    """Return ``lstat`` for a non-symlink regular file or fail closed."""
    try:
        result = path.lstat()
    except OSError as exc:
        raise PodDataSyncError(message) from exc
    if stat.S_ISLNK(result.st_mode) or not stat.S_ISREG(result.st_mode):
        raise PodDataSyncError(message)
    return result


def require_private_path(path: Path) -> None:
    """Require one file or directory to be owned by this user and owner-only."""
    owner_uid = os.geteuid() if hasattr(os, "geteuid") else os.getuid()
    try:
        result = path.lstat()
    except OSError as exc:
        raise PodDataSyncError("Snapshot permissions could not be verified") from exc
    is_directory = stat.S_ISDIR(result.st_mode)
    if (
        stat.S_ISLNK(result.st_mode)
        or not (is_directory or stat.S_ISREG(result.st_mode))
        or result.st_uid != owner_uid
        or result.st_mode & 0o077
    ):
        raise PodDataSyncError("Snapshot must be owner-only on an approved machine")


def require_private_tree(root: Path) -> None:
    """Require a snapshot tree to be owned by this user and owner-only."""
    for path in (root, *root.rglob("*")):
        require_private_path(path)


def cleanup_sensitive_artifacts(
    parent: Path,
    prefixes: tuple[str, ...],
    *,
    now: datetime | None = None,
    ttl: timedelta = SENSITIVE_ARTIFACT_TTL,
    max_count: int = SENSITIVE_ARTIFACT_MAX_COUNT,
) -> list[str]:
    """Bound crash/quarantine copies without following attacker-controlled links."""
    current = now or datetime.now(UTC)
    candidates: list[tuple[datetime, Path]] = []
    for candidate in parent.iterdir():
        if not candidate.name.startswith(prefixes):
            continue
        try:
            metadata = candidate.lstat()
        except OSError:
            continue
        if stat.S_ISLNK(metadata.st_mode):
            continue
        modified = datetime.fromtimestamp(metadata.st_mtime, UTC)
        candidates.append((modified, candidate))
    candidates.sort(key=lambda item: (item[0], item[1].name), reverse=True)
    removed: list[str] = []
    for index, (modified, candidate) in enumerate(candidates):
        if index < max(0, max_count) and current - modified <= ttl:
            continue
        try:
            if candidate.is_dir():
                shutil.rmtree(candidate)
            else:
                candidate.unlink()
        except OSError:
            continue
        removed.append(candidate.name)
    return removed


def sqlite_database_is_valid(path: Path, expected_tables: set[str]) -> bool:
    """Validate a standalone frozen backup without creating WAL/SHM files."""
    try:
        connection = sqlite3.connect(
            f"{path.resolve().as_uri()}?mode=ro&immutable=1", uri=True
        )
        try:
            check = connection.execute("PRAGMA quick_check").fetchone()
            rows = connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        finally:
            connection.close()
    except sqlite3.Error:
        return False
    tables = {str(row[0]) for row in rows}
    return bool(check and check[0] == "ok" and expected_tables <= tables)


def extract_private_zip(archive_path: Path, destination: Path) -> None:
    """Extract a pre-validated ZIP into owner-only files and directories."""
    root = destination.resolve(strict=True)
    root.chmod(PRIVATE_DIRECTORY_MODE)
    try:
        with zipfile.ZipFile(archive_path) as archive:
            for item in archive.infolist():
                target = destination / item.filename
                target.resolve().relative_to(root)
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                target.parent.chmod(0o700)
                with archive.open(item) as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output)
                target.chmod(0o600)
    except PodDataSyncError:
        raise
    except Exception as exc:
        raise PodDataSyncError(f"Snapshot extraction is invalid: {exc}") from exc


def validated_nonnegative_hours(value: object) -> float:
    """Return a finite non-negative hour value."""
    try:
        hours = float(value)
    except (TypeError, ValueError) as exc:
        raise PodDataSyncError("Snapshot maximum age is invalid") from exc
    if not math.isfinite(hours) or hours < 0:
        raise PodDataSyncError("Snapshot maximum age is invalid")
    return hours


def prune_snapshot_directories(
    managed: list[tuple[datetime, Path]], retention_count: int, protected: Path
) -> list[str]:
    """Remove old verified snapshot directories while preserving the active one."""
    keep = {protected.resolve()}
    for _, candidate in managed:
        if len(keep) >= max(1, retention_count):
            break
        keep.add(candidate.resolve())
    removed: list[str] = []
    for _, candidate in managed:
        if candidate.resolve() in keep:
            continue
        try:
            shutil.rmtree(candidate)
        except OSError:
            continue
        removed.append(candidate.name)
    return removed


def enforce_snapshot_retention(
    parent: Path,
    managed: list[tuple[datetime, Path]],
    retention_count: int,
    protected: Path,
) -> tuple[list[str], list[str]]:
    """Quarantine invalid managed-looking copies, then prune verified copies."""
    verified = {candidate.resolve() for _, candidate in managed}
    quarantined: list[str] = []
    for candidate in parent.iterdir():
        if not MANAGED_SNAPSHOT_NAME.fullmatch(candidate.name):
            continue
        try:
            metadata = candidate.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                candidate.unlink()
                quarantined.append(candidate.name)
                continue
            if candidate.resolve() in verified:
                continue
            rejected = parent / (f".rejected-{candidate.name}-{secrets.token_hex(6)}")
            candidate.replace(rejected)
            quarantined.append(candidate.name)
        except OSError:
            continue
    removed = prune_snapshot_directories(managed, retention_count, protected)
    return removed, quarantined
