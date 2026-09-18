"""Download and verify a read-only ZEEP Pod data snapshot."""

from __future__ import annotations

import re
import secrets
import shutil
import tempfile
import zipfile
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .pod_snapshot_errors import PodDataSyncError
from .pod_snapshot_export import (
    EXCLUDED_PRIVATE_STATE,
    OPTIONAL_FILES,
    REQUIRED_DATABASES,
    SNAPSHOT_SCHEMA,
    validate_capture_window,
)
from .pod_snapshot_lock import sync_lock as _sync_lock
from .pod_snapshot_transport import download_snapshot as _download_snapshot
from .pod_snapshot_transport import validated_host as _validated_host
from .pod_snapshot_transport import validated_remote_root as _validated_remote_root
from .pod_snapshot_validation import parse_timestamp as _parse_timestamp
from .pod_snapshot_validation import records_snapshot_id as _records_snapshot_id
from .pod_snapshot_validation import validated_pod_id as _validated_pod_id
from .secure_paths import atomic_json as _write_json_atomic
from .secure_paths import (
    cleanup_sensitive_artifacts,
    enforce_snapshot_retention,
    extract_private_zip,
    read_private_json,
    real_child_directory,
    require_private_path,
    require_private_tree,
    safe_archive_path,
    sqlite_database_is_valid,
    strict_json_loads,
    validated_nonnegative_hours,
    validated_snapshot_destination,
)
from .secure_paths import sha256_file as _sha256
from .workstation_approval import require_workstation_approval

DEFAULT_HOSTS = ("pod1@pod1.starling-altered.ts.net", "pod1@192.168.1.100")
DEFAULT_REMOTE_ROOT = "/home/pod1/pi5"
DEFAULT_DESTINATION = Path("private-data/pod-sync")
DEFAULT_POD_ID = "zeep-pod-01"
DEFAULT_RETENTION = 3
DEFAULT_MAX_AGE_HOURS = 72
MAX_ARCHIVE_BYTES = 4 * 1024**3
MAX_MEMBER_BYTES = 3 * 1024**3
MAX_TOTAL_BYTES = 8 * 1024**3
MAX_MANIFEST_BYTES = 1024**2
ALLOWED_SNAPSHOT_FILES = frozenset((*REQUIRED_DATABASES, *OPTIONAL_FILES))
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _validated_destination(value: Path) -> Path:
    return validated_snapshot_destination(
        value,
        project_root=PROJECT_ROOT,
        project_destination=DEFAULT_DESTINATION,
    )


def _normalised_records(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    records = manifest.get("files")
    if not isinstance(records, list):
        raise PodDataSyncError("Snapshot file register is invalid")
    normalised: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            raise PodDataSyncError("Snapshot file record is invalid")
        relative = str(record.get("path") or "")
        checksum = str(record.get("sha256") or "")
        size = record.get("size_bytes")
        if isinstance(size, bool) or not isinstance(size, int):
            raise PodDataSyncError("Snapshot file size is invalid")
        if relative not in ALLOWED_SNAPSHOT_FILES or not safe_archive_path(relative):
            raise PodDataSyncError("Snapshot contains a file outside the allowlist")
        if size < 0 or size > MAX_MEMBER_BYTES:
            raise PodDataSyncError("Snapshot file size exceeds the allowed limit")
        if not re.fullmatch(r"[0-9a-f]{64}", checksum):
            raise PodDataSyncError("Snapshot checksum is invalid")
        normalised.append({"path": relative, "size_bytes": size, "sha256": checksum})
    paths = [record["path"] for record in normalised]
    if len(paths) != len(set(paths)):
        raise PodDataSyncError("Snapshot file register contains duplicates")
    if sum(record["size_bytes"] for record in normalised) > MAX_TOTAL_BYTES:
        raise PodDataSyncError("Snapshot content exceeds the allowed limit")
    return normalised


def _validate_manifest(manifest: object) -> dict[str, Any]:
    if not isinstance(manifest, dict) or manifest.get("schema") != SNAPSHOT_SCHEMA:
        raise PodDataSyncError("Snapshot schema is not supported")
    records = _normalised_records(manifest)
    source = manifest.get("source")
    if not isinstance(source, dict):
        raise PodDataSyncError("Snapshot source is invalid")
    snapshot_id = str(manifest.get("snapshot_id") or "")
    if snapshot_id != _records_snapshot_id(
        records, source.get("pod_id"), source.get("git_commit")
    ):
        raise PodDataSyncError("Snapshot ID does not match its file register")
    _validated_pod_id(source.get("pod_id"))
    validate_capture_window(manifest)
    return manifest


def _read_manifest(archive_path: Path) -> dict[str, Any]:
    try:
        if archive_path.stat().st_size > MAX_ARCHIVE_BYTES:
            raise PodDataSyncError("Snapshot archive exceeds the allowed limit")
        with zipfile.ZipFile(archive_path) as archive:
            infos = archive.infolist()
            names = [item.filename for item in infos]
            if len(names) != len(set(names)) or names.count("manifest.json") != 1:
                raise PodDataSyncError("Snapshot members are missing or duplicated")
            if any(not safe_archive_path(name) for name in names):
                raise PodDataSyncError("Snapshot contains an unsafe path")
            if sum(item.file_size for item in infos) > MAX_TOTAL_BYTES:
                raise PodDataSyncError(
                    "Snapshot archive expands beyond the allowed limit"
                )
            for item in infos:
                file_type = (item.external_attr >> 16) & 0o170000
                if item.file_size > MAX_MEMBER_BYTES or file_type == 0o120000:
                    raise PodDataSyncError("Snapshot contains an unsafe member")
            manifest_info = archive.getinfo("manifest.json")
            if manifest_info.file_size > MAX_MANIFEST_BYTES:
                raise PodDataSyncError("Snapshot manifest is too large")
            manifest = _validate_manifest(
                strict_json_loads(archive.read(manifest_info))
            )
    except PodDataSyncError:
        raise
    except Exception as exc:
        raise PodDataSyncError(f"Snapshot archive is invalid: {exc}") from exc
    registered = {record["path"] for record in _normalised_records(manifest)}
    if set(names) != {"manifest.json", *registered}:
        raise PodDataSyncError("Snapshot archive and file register do not match")
    return manifest


def _verify_extracted_snapshot(path: Path, manifest: dict[str, Any]) -> None:
    require_private_tree(path)
    manifest = _validate_manifest(manifest)
    records = _normalised_records(manifest)
    expected = {"manifest.json", *(record["path"] for record in records)}
    actual = {
        item.relative_to(path).as_posix()
        for item in path.rglob("*")
        if item.is_file() and not item.is_symlink()
    }
    if actual != expected or any(item.is_symlink() for item in path.rglob("*")):
        raise PodDataSyncError("Snapshot directory contains unexpected content")
    for record in records:
        candidate = path / record["path"]
        try:
            candidate.resolve(strict=True).relative_to(path.resolve(strict=True))
        except (OSError, ValueError) as exc:
            raise PodDataSyncError("Snapshot file escapes its directory") from exc
        if candidate.stat().st_size != record["size_bytes"]:
            raise PodDataSyncError(f"Snapshot size mismatch: {record['path']}")
        if _sha256(candidate) != record["sha256"]:
            raise PodDataSyncError(f"Snapshot checksum mismatch: {record['path']}")
        if candidate.suffix == ".json":
            try:
                strict_json_loads(candidate.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise PodDataSyncError(
                    f"Snapshot JSON is invalid: {record['path']}"
                ) from exc
    missing = set(REQUIRED_DATABASES) - {record["path"] for record in records}
    if missing:
        raise PodDataSyncError("Snapshot is missing required databases")
    for relative, tables in REQUIRED_DATABASES.items():
        if not sqlite_database_is_valid(path / relative, tables):
            raise PodDataSyncError(f"SQLite validation failed: {relative}")


def _download_from_first_host(
    hosts: Iterable[str],
    remote_root: str,
    archive_path: Path,
    *,
    expected_pod_id: str,
    connect_timeout_seconds: int,
    command_timeout_seconds: int,
) -> tuple[str, dict[str, Any]]:
    failures = []
    for host in hosts:
        try:
            _download_snapshot(
                host,
                remote_root,
                archive_path,
                connect_timeout_seconds=connect_timeout_seconds,
                command_timeout_seconds=command_timeout_seconds,
            )
            manifest = _read_manifest(archive_path)
            source = manifest["source"]
            if str(source.get("host") or "") != host:
                raise PodDataSyncError(
                    "Snapshot source does not match the selected Pod"
                )
            if _validated_pod_id(source.get("pod_id")) != expected_pod_id:
                raise PodDataSyncError(
                    "Snapshot Pod ID does not match the requested Pod"
                )
            with tempfile.TemporaryDirectory(
                prefix="verify-", dir=archive_path.parent
            ) as temporary:
                verification = Path(temporary)
                extract_private_zip(archive_path, verification)
                _verify_extracted_snapshot(verification, manifest)
        except (OSError, PodDataSyncError, zipfile.BadZipFile) as exc:
            failures.append(str(exc))
            archive_path.unlink(missing_ok=True)
            continue
        return host, manifest
    raise PodDataSyncError("; ".join(failures))


def _read_local_manifest(snapshot: Path) -> dict[str, Any]:
    manifest_path = snapshot / "manifest.json"
    if snapshot.is_symlink() or not snapshot.is_dir():
        raise PodDataSyncError("Stored snapshot directory is invalid")
    try:
        require_private_tree(snapshot)
        payload, _ = read_private_json(manifest_path, max_bytes=MAX_MANIFEST_BYTES)
        return _validate_manifest(payload)
    except (OSError, ValueError, PodDataSyncError) as exc:
        raise PodDataSyncError(f"Stored manifest is invalid: {exc}") from exc


def _existing_snapshot(pod_directory: Path, snapshot_id: str) -> Path | None:
    for candidate in pod_directory.iterdir():
        if (
            not candidate.is_dir()
            or candidate.is_symlink()
            or candidate.name.startswith(".")
        ):
            continue
        try:
            manifest = _read_local_manifest(candidate)
            if manifest.get("snapshot_id") == snapshot_id:
                _verify_extracted_snapshot(candidate, manifest)
                return candidate
        except (OSError, PodDataSyncError):
            continue
    return None


def _install_verified_snapshot(
    archive_path: Path,
    manifest: dict[str, Any],
    destination: Path,
) -> tuple[Path, Path, bool]:
    pod_id = _validated_pod_id((manifest.get("source") or {}).get("pod_id"))
    pod_directory = real_child_directory(destination, pod_id)
    existing = _existing_snapshot(pod_directory, str(manifest["snapshot_id"]))
    if existing:
        return pod_directory, existing, True
    timestamp = _parse_timestamp(manifest["created_at_utc"]).strftime("%Y%m%dT%H%M%SZ")
    final_path = pod_directory / f"{timestamp}-{str(manifest['snapshot_id'])[:12]}"
    pending_path = Path(tempfile.mkdtemp(prefix=".partial-", dir=pod_directory))
    try:
        extract_private_zip(archive_path, pending_path)
        _verify_extracted_snapshot(pending_path, manifest)
        if final_path.exists() or final_path.is_symlink():
            rejected = pod_directory / (
                f".rejected-{final_path.name}-{secrets.token_hex(6)}"
            )
            final_path.replace(rejected)
        pending_path.replace(final_path)
    except Exception:
        shutil.rmtree(pending_path, ignore_errors=True)
        raise
    return pod_directory, final_path, False


def _managed_snapshots(pod_directory: Path) -> list[tuple[datetime, Path]]:
    managed = []
    for candidate in pod_directory.iterdir():
        if (
            not candidate.is_dir()
            or candidate.is_symlink()
            or candidate.name.startswith(".")
        ):
            continue
        try:
            manifest = _read_local_manifest(candidate)
            pod_id = _validated_pod_id((manifest.get("source") or {}).get("pod_id"))
            if pod_id != pod_directory.name:
                continue
            _verify_extracted_snapshot(candidate, manifest)
            managed.append((_parse_timestamp(manifest["created_at_utc"]), candidate))
        except (OSError, PodDataSyncError):
            continue
    return sorted(managed, key=lambda item: (item[0], item[1].name), reverse=True)


def _latest_payload(
    selected_host: str,
    manifest: dict[str, Any],
    final_path: Path,
) -> dict[str, Any]:
    source = manifest["source"]
    return {
        "schema": SNAPSHOT_SCHEMA,
        "source_host": selected_host,
        "pod_id": _validated_pod_id(source.get("pod_id")),
        "git_commit": str(source.get("git_commit") or "unknown"),
        "snapshot_id": manifest["snapshot_id"],
        "snapshot": final_path.name,
        "path": str(final_path),
        "created_at_utc": manifest["created_at_utc"],
        "verified_at_utc": datetime.now(UTC).isoformat(),
        "contains_personal_wellness_data": True,
        "selection_provenance": {
            "source": "network_sync",
            "fallback": False,
            "freshness_basis": "verified_at_utc",
        },
    }


def _verified_latest_file(latest_path: Path, max_age_hours: float) -> dict[str, Any]:
    require_private_tree(latest_path)
    try:
        payload, _ = read_private_json(latest_path, max_bytes=MAX_MANIFEST_BYTES)
    except (OSError, ValueError, PodDataSyncError) as exc:
        raise PodDataSyncError("Latest snapshot pointer is invalid") from exc
    if not isinstance(payload, dict) or payload.get("schema") != SNAPSHOT_SCHEMA:
        raise PodDataSyncError("Latest snapshot pointer schema is invalid")
    pod_directory = latest_path.parent.resolve(strict=True)
    snapshot_name = str(payload.get("snapshot") or "")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", snapshot_name):
        raise PodDataSyncError("Latest snapshot path is invalid")
    snapshot = (pod_directory / snapshot_name).resolve(strict=True)
    try:
        snapshot.relative_to(pod_directory)
    except ValueError as exc:
        raise PodDataSyncError("Latest snapshot escapes its Pod directory") from exc
    manifest = _read_local_manifest(snapshot)
    if manifest.get("snapshot_id") != payload.get("snapshot_id"):
        raise PodDataSyncError("Latest snapshot ID does not match")
    if str(payload.get("path") or "") != str(snapshot):
        raise PodDataSyncError("Latest snapshot absolute path does not match")
    source = manifest["source"]
    if payload.get("pod_id") != source.get("pod_id"):
        raise PodDataSyncError("Latest snapshot Pod ID does not match")
    if payload.get("git_commit") != source.get("git_commit"):
        raise PodDataSyncError("Latest snapshot commit does not match")
    if payload.get("created_at_utc") != manifest.get("created_at_utc"):
        raise PodDataSyncError("Latest snapshot timestamp does not match")
    _verify_extracted_snapshot(snapshot, manifest)
    age_hours = (
        datetime.now(UTC) - _parse_timestamp(payload.get("verified_at_utc"))
    ).total_seconds() / 3600
    if age_hours > max(0, max_age_hours):
        raise PodDataSyncError("Latest verified snapshot is stale")
    return {
        **payload,
        "path": str(snapshot),
        "age_hours": round(max(0, age_hours), 2),
        "selection_provenance": {
            "source": "latest_pointer",
            "fallback": False,
            "freshness_basis": "verified_at_utc",
        },
    }


def latest_verified_snapshot(
    destination: Path = DEFAULT_DESTINATION,
    expected_pod_id: str = DEFAULT_POD_ID,
    *,
    max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
) -> dict[str, Any]:
    """Return the freshest fully verified local snapshot without network access."""
    destination = _validated_destination(destination).resolve(strict=True)
    require_workstation_approval(destination)
    require_private_path(destination)
    expected_pod_id = _validated_pod_id(expected_pod_id)
    age_limit = validated_nonnegative_hours(max_age_hours)
    for pod_directory in destination.iterdir():
        if pod_directory.is_symlink() or not pod_directory.is_dir():
            continue
        if pod_directory.name != expected_pod_id:
            continue
        require_workstation_approval(pod_directory)
        require_private_path(pod_directory)
        latest_path = pod_directory / "latest.json"
        fallback_reason = "latest_pointer_missing"
        try:
            return _verified_latest_file(latest_path, age_limit)
        except (OSError, PodDataSyncError):
            if latest_path.exists() or latest_path.is_symlink():
                fallback_reason = "latest_pointer_invalid"
        for created, snapshot in _managed_snapshots(pod_directory):
            age_hours = max(0, (datetime.now(UTC) - created).total_seconds() / 3600)
            if age_hours > age_limit:
                continue
            manifest = _read_local_manifest(snapshot)
            payload = _latest_payload(
                str(manifest["source"]["host"]), manifest, snapshot
            )
            return {
                **payload,
                "age_hours": round(age_hours, 2),
                "selection_provenance": {
                    "source": "retained_snapshot_scan",
                    "fallback": True,
                    "reason": fallback_reason,
                    "freshness_basis": "created_at_utc",
                },
            }
    raise PodDataSyncError("No fresh verified Pod snapshot is available")


def sync_pod_data(
    hosts: Iterable[str] = DEFAULT_HOSTS,
    *,
    remote_root: str = DEFAULT_REMOTE_ROOT,
    destination: Path = DEFAULT_DESTINATION,
    expected_pod_id: str = DEFAULT_POD_ID,
    retention_count: int = DEFAULT_RETENTION,
    connect_timeout_seconds: int = 8,
    command_timeout_seconds: int = 300,
) -> dict[str, Any]:
    """Synchronise one verified Pod snapshot and return its local location."""
    destination = _validated_destination(destination)
    require_workstation_approval(destination)
    expected_pod_id = _validated_pod_id(expected_pod_id)
    host_candidates = tuple(
        dict.fromkeys(_validated_host(host) for host in hosts if host.strip())
    )
    if not host_candidates:
        raise PodDataSyncError("At least one Pod host is required")
    remote_root = _validated_remote_root(remote_root)
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination.chmod(0o700)
    pod_directory = real_child_directory(destination, expected_pod_id)
    require_workstation_approval(pod_directory)
    with _sync_lock(destination):
        cleaned = cleanup_sensitive_artifacts(destination, ("zeep-pod-sync-",))
        cleaned.extend(
            f"{pod_directory.name}/{name}"
            for name in cleanup_sensitive_artifacts(
                pod_directory, (".partial-", ".rejected-", ".latest.json.")
            )
        )
        with tempfile.TemporaryDirectory(
            prefix="zeep-pod-sync-", dir=destination
        ) as temporary:
            archive_path = Path(temporary) / "snapshot.zip"
            selected_host, manifest = _download_from_first_host(
                host_candidates,
                remote_root,
                archive_path,
                expected_pod_id=expected_pod_id,
                connect_timeout_seconds=connect_timeout_seconds,
                command_timeout_seconds=command_timeout_seconds,
            )
            pod_directory, final_path, up_to_date = _install_verified_snapshot(
                archive_path, manifest, destination
            )
        stored_manifest = _read_local_manifest(final_path)
        latest = _latest_payload(selected_host, stored_manifest, final_path)
        _write_json_atomic(pod_directory / "latest.json", latest)
        removed, quarantined = enforce_snapshot_retention(
            pod_directory,
            _managed_snapshots(pod_directory),
            max(1, retention_count),
            final_path,
        )
        if not final_path.is_dir():
            raise PodDataSyncError("New snapshot failed verification during retention")
        cleaned.extend(
            f"{pod_directory.name}/{name}"
            for name in cleanup_sensitive_artifacts(
                pod_directory, (".partial-", ".rejected-", ".latest.json.")
            )
        )
    return {
        **latest,
        "up_to_date": up_to_date,
        "retention_count": max(1, retention_count),
        "pruned_snapshots": removed,
        "quarantined_invalid_snapshots": quarantined,
        "cleaned_sensitive_artifacts": sorted(set(cleaned)),
        "excluded_private_state": list(EXCLUDED_PRIVATE_STATE),
    }
