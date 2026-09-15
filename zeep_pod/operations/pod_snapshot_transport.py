"""Pinned SSH transport for downloading a Pod snapshot."""

from __future__ import annotations

import ipaddress
import os
import re
import selectors
import shlex
import subprocess
import time
from pathlib import Path

from .pod_snapshot_errors import PodDataSyncError

MAX_ARCHIVE_BYTES = 4 * 1024**3
READ_CHUNK_BYTES = 64 * 1024
MAX_ERROR_BYTES = 16 * 1024
SSH_EXECUTABLE = "/usr/bin/ssh"


def validated_host(value: str) -> str:
    """Return one SSH destination without option-like or malformed labels."""
    candidate = value.strip()
    user = r"[A-Za-z0-9][A-Za-z0-9._-]*"
    match = re.fullmatch(rf"(?:(?P<user>{user})@)?(?P<host>[^@]+)", candidate)
    if not match:
        raise PodDataSyncError("Pod host is invalid")
    hostname = match.group("host")
    if hostname.startswith("[") and hostname.endswith("]"):
        if not re.fullmatch(r"\[[0-9A-Fa-f:]+\]", hostname):
            raise PodDataSyncError("Pod host is invalid")
        try:
            ipaddress.IPv6Address(hostname[1:-1])
        except ValueError as exc:
            raise PodDataSyncError("Pod host is invalid") from exc
    else:
        labels = hostname.split(".")
        valid_label = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
        if len(hostname) > 253 or any(
            not re.fullmatch(valid_label, label) for label in labels
        ):
            raise PodDataSyncError("Pod host is invalid")
    return candidate


def validated_remote_root(value: str) -> str:
    """Return one canonical absolute POSIX project path."""
    from pathlib import PurePosixPath

    path = PurePosixPath(value)
    if (
        value.startswith("//")
        or not re.fullmatch(r"/[A-Za-z0-9._/-]+", value)
        or ".." in path.parts
        or "." in path.parts
        or str(path) != value
    ):
        raise PodDataSyncError("Remote project root is invalid")
    return value


def _run_bounded_command(
    command: list[str],
    archive_path: Path,
    *,
    timeout_seconds: int,
    max_bytes: int = MAX_ARCHIVE_BYTES,
) -> tuple[int, bytes]:
    """Stream stdout with a hard byte cap while draining bounded stderr."""
    if os.name == "nt":
        raise PodDataSyncError("Workstation snapshot transport is not supported here")
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdout is not None and process.stderr is not None
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    deadline = time.monotonic() + max(1, timeout_seconds)
    total = 0
    errors = bytearray()
    try:
        with archive_path.open("xb") as output:
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(command, timeout_seconds)
                events = selector.select(min(1.0, remaining))
                if not events and process.poll() is not None:
                    continue
                for key, _ in events:
                    chunk = key.fileobj.read1(READ_CHUNK_BYTES)
                    if not chunk:
                        selector.unregister(key.fileobj)
                    elif key.data == "stdout":
                        if total + len(chunk) > max_bytes:
                            raise PodDataSyncError(
                                "Snapshot archive exceeds the allowed limit"
                            )
                        output.write(chunk)
                        total += len(chunk)
                    else:
                        errors.extend(chunk)
                        del errors[:-MAX_ERROR_BYTES]
        return process.wait(timeout=max(1, deadline - time.monotonic())), bytes(errors)
    except Exception:
        process.kill()
        process.wait()
        archive_path.unlink(missing_ok=True)
        raise
    finally:
        selector.close()
        process.stdout.close()
        process.stderr.close()


def download_snapshot(
    host: str,
    remote_root: str,
    archive_path: Path,
    *,
    connect_timeout_seconds: int,
    command_timeout_seconds: int,
) -> None:
    """Run only the reviewed exporter module and capture its ZIP output."""
    host = validated_host(host)
    remote_root = validated_remote_root(remote_root)
    known_hosts = Path.home() / ".ssh" / "known_hosts"
    remote_command = shlex.join(
        [
            "/usr/bin/env",
            "LC_ALL=C",
            f"PYTHONPATH={remote_root}",
            "/usr/bin/python3",
            "-m",
            "zeep_pod.operations.pod_snapshot_export",
            remote_root,
            host,
        ]
    )
    command = [
        SSH_EXECUTABLE,
        "-o",
        "BatchMode=yes",
        "-o",
        "ClearAllForwardings=yes",
        "-o",
        "ForwardAgent=no",
        "-o",
        "PermitLocalCommand=no",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        f"UserKnownHostsFile={known_hosts}",
        "-o",
        f"ConnectTimeout={max(1, connect_timeout_seconds)}",
        "--",
        host,
        remote_command,
    ]
    try:
        returncode, errors = _run_bounded_command(
            command,
            archive_path,
            timeout_seconds=command_timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise PodDataSyncError(f"Pod snapshot timed out: {host}") from exc
    if returncode:
        archive_path.unlink(missing_ok=True)
        detail = errors.decode("utf-8", errors="replace").strip()[-400:]
        raise PodDataSyncError(
            f"Pod snapshot failed: {host}" + (f" · {detail}" if detail else "")
        )
    if not archive_path.is_file() or not archive_path.stat().st_size:
        raise PodDataSyncError(f"Pod returned an empty snapshot: {host}")
    if archive_path.stat().st_size > MAX_ARCHIVE_BYTES:
        archive_path.unlink(missing_ok=True)
        raise PodDataSyncError("Snapshot archive exceeds the allowed limit")
