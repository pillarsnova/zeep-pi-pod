"""Shared value validation for Pod snapshot metadata."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from typing import Any

from .pod_snapshot_errors import PodDataSyncError


def validated_pod_id(value: object) -> str:
    pod_id = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", pod_id):
        raise PodDataSyncError("Snapshot Pod ID is invalid")
    return pod_id


def parse_timestamp(value: object) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError as exc:
        raise PodDataSyncError("Snapshot timestamp is invalid") from exc
    if parsed.tzinfo is None:
        raise PodDataSyncError("Snapshot timestamp must include a timezone")
    parsed = parsed.astimezone(UTC)
    now = datetime.now(UTC)
    if (parsed - now).total_seconds() > 600:
        raise PodDataSyncError("Snapshot timestamp is too far in the future")
    return parsed


def records_snapshot_id(
    records: list[dict[str, Any]], pod_id: object, git_commit: object
) -> str:
    """Bind content identity to its physical Pod and software provenance."""
    identity = f"pod_id={validated_pod_id(pod_id)}\ngit_commit={git_commit}\n"
    files = "\n".join(
        f"{item['path']}\0{item['size_bytes']}\0{item['sha256']}"
        for item in sorted(records, key=lambda item: item["path"])
    )
    return hashlib.sha256(f"{identity}{files}".encode()).hexdigest()
