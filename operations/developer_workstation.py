"""Explicit owner-approved, machine-bound exception for a development Mac.

This is a user-owned exception, not OS-admin approval or proof of encryption.
The marker stays in ignored private-data and is never distributed via Git.
"""

from __future__ import annotations

import os
import platform
import socket
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from . import workstation_approval as approval
from .pod_snapshot_errors import PodDataSyncError
from .secure_paths import atomic_json, read_private_json

EXCEPTION_SCHEMA = "zeep-owner-approved-development-mac-v1"
EXCEPTION_MARKER = (
    Path(__file__).resolve().parents[1] / "private-data/developer-mac-approval.json"
)


def approve_development_mac(
    approved_by: str,
    destination: Path,
    *,
    marker: Path = EXCEPTION_MARKER,
) -> dict[str, Any]:
    """Record the owner's explicit exception for this Mac and destination."""
    if platform.system() != "Darwin" or not approved_by.strip():
        raise approval.WorkstationApprovalError("ข้อยกเว้นนี้ใช้เฉพาะ Mac ที่เจ้าของอนุมัติ")
    now = datetime.now(UTC)
    payload = {
        "schema": EXCEPTION_SCHEMA,
        "approval_kind": "owner_approved_development_exception",
        "hostname": socket.gethostname(),
        "machine_id": approval._machine_identity(),
        "owner_uid": os.getuid(),
        "approved_by": approved_by.strip(),
        "approved_at_utc": now.isoformat(),
        "expires_at_utc": (now + timedelta(days=365)).isoformat(),
        "destination": str(destination.expanduser().resolve()),
        "encryption_requirement_waived": True,
        "disk_encryption": approval.disk_encryption_status(destination),
        "risk_acknowledgement": "Owner accepts unencrypted local Wellness snapshots on this development Mac only",
        "os_admin_approval": False,
    }
    if marker.is_symlink() or marker.parent.is_symlink():
        raise approval.WorkstationApprovalError("ห้ามใช้ symlink สำหรับทะเบียนข้อยกเว้น")
    marker.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    atomic_json(marker, payload, mode=0o600)
    return payload


def require_development_mac(
    destination: Path,
    *,
    marker: Path = EXCEPTION_MARKER,
) -> dict[str, Any]:
    """Accept only this OS user, machine, destination tree and valid record."""
    if platform.system() != "Darwin":
        raise approval.WorkstationApprovalError("ข้อยกเว้นนี้ไม่ใช้กับเครื่องทีมอื่นหรือ Pi")
    try:
        payload, metadata = read_private_json(marker)
    except PodDataSyncError as exc:
        raise approval.WorkstationApprovalError("อ่านทะเบียนข้อยกเว้นไม่สำเร็จ") from exc
    valid = (
        isinstance(payload, dict)
        and payload.get("schema") == EXCEPTION_SCHEMA
        and payload.get("approval_kind") == "owner_approved_development_exception"
        and metadata.st_uid == os.getuid() == payload.get("owner_uid")
        and stat.S_IMODE(metadata.st_mode) == 0o600
        and payload.get("hostname") == socket.gethostname()
        and payload.get("machine_id") == approval._machine_identity()
        and payload.get("encryption_requirement_waived") is True
        and bool(str(payload.get("approved_by") or "").strip())
    )
    if not valid:
        raise approval.WorkstationApprovalError("ทะเบียนข้อยกเว้นไม่ตรงกับเครื่องหรือผู้ใช้ปัจจุบัน")
    try:
        root = Path(payload["destination"])
        if not root.is_absolute():
            raise ValueError("relative destination")
        destination.expanduser().resolve().relative_to(root.resolve())
    except (KeyError, ValueError) as exc:
        raise approval.WorkstationApprovalError(
            "ปลายทางอยู่นอกขอบเขตที่เจ้าของอนุมัติ"
        ) from exc
    start = approval._marker_time(payload, "approved_at_utc")
    end = approval._marker_time(payload, "expires_at_utc")
    now = datetime.now(UTC)
    if not start <= now < end or end - start > timedelta(days=365, minutes=1):
        raise approval.WorkstationApprovalError("ทะเบียนข้อยกเว้นหมดอายุหรือวันที่ไม่ถูกต้อง")
    payload["disk_encryption_current"] = approval.disk_encryption_status(destination)
    return payload
