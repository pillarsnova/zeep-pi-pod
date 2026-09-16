"""Cross-platform exclusive lock for one snapshot destination."""

from __future__ import annotations

import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .pod_snapshot_errors import PodDataSyncError


def _open_lock(path: Path):
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise PodDataSyncError("Snapshot lock must be a real local file") from exc
    opened = os.fstat(descriptor)
    try:
        linked = path.lstat()
    except OSError:
        os.close(descriptor)
        raise PodDataSyncError("Snapshot lock could not be verified") from None
    if (
        not stat.S_ISREG(opened.st_mode)
        or stat.S_ISLNK(linked.st_mode)
        or (opened.st_dev, opened.st_ino) != (linked.st_dev, linked.st_ino)
    ):
        os.close(descriptor)
        raise PodDataSyncError("Snapshot lock must be a real local file")
    os.fchmod(descriptor, 0o600)
    return os.fdopen(descriptor, "r+b")


@contextmanager
def sync_lock(destination: Path) -> Iterator[None]:
    """Prevent concurrent sync jobs from racing latest/retention updates."""
    lock_path = destination / ".sync.lock"
    with _open_lock(lock_path) as handle:
        if os.name == "nt":
            import msvcrt

            if not lock_path.stat().st_size:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
