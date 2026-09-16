"""Approve only encrypted team workstations for Pod data snapshots."""

from __future__ import annotations

import os
import platform
import re
import socket
import stat
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .pod_snapshot_errors import PodDataSyncError
from .secure_paths import atomic_json, read_private_json

APPROVAL_SCHEMA = "zeep-data-workstation-approval-v2"
DEFAULT_MARKER = (
    Path("/Library/Application Support/ZEEP/team-workstation-approval.json")
    if platform.system() == "Darwin"
    else Path("/etc/zeep/team-workstation-approval.json")
)
DEFAULT_DATA_DESTINATION = Path("private-data/pod-sync")
APPROVAL_VALID_DAYS = 365
TRUSTED_TOOLS = {
    "Darwin": {
        "diskutil": "/usr/sbin/diskutil",
        "fdesetup": "/usr/bin/fdesetup",
        "ioreg": "/usr/sbin/ioreg",
    },
    "Linux": {
        "findmnt": "/usr/bin/findmnt",
        "lsblk": "/usr/bin/lsblk",
    },
}


class WorkstationApprovalError(RuntimeError):
    """Raised when a workstation is not approved for personal Wellness data."""


def _approval_owner_uid() -> int:
    """The local OS administrator owns the authoritative approval marker."""
    return 0


def _require_approval_authority() -> None:
    if not hasattr(os, "geteuid") or os.geteuid() != _approval_owner_uid():
        raise WorkstationApprovalError("ต้องให้ OS administrator เป็นผู้อนุมัติเครื่องทีม")


def _command_output(command: list[str]) -> str:
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
            env={
                "LANG": "C",
                "LC_ALL": "C",
                "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            },
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise WorkstationApprovalError(
            f"ตรวจ disk encryption ไม่สำเร็จ: {command[0]}"
        ) from exc
    output = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part)
    if result.returncode:
        raise WorkstationApprovalError(
            f"ตรวจ disk encryption ไม่สำเร็จ: {output or command[0]}"
        )
    return output


def _existing_parent(path: Path) -> Path:
    candidate = path.expanduser().resolve()
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    if not candidate.exists():
        raise WorkstationApprovalError("ไม่พบ volume ปลายทางสำหรับตรวจ encryption")
    return candidate


def _macos_diskutil_encrypted(output: str) -> bool:
    return bool(
        re.search(
            r"^\s*(?:FileVault|Encrypted):\s*Yes\s*$",
            output,
            flags=re.IGNORECASE | re.MULTILINE,
        )
    )


def _macos_filevault_enabled(output: str) -> bool:
    """Accept only the single canonical status line from ``fdesetup``."""
    status_lines = [
        line.strip().casefold()
        for line in output.splitlines()
        if line.strip().casefold().startswith("filevault is")
    ]
    return status_lines == ["filevault is on."]


def _trusted_tool(system: str, name: str) -> str:
    try:
        return TRUSTED_TOOLS[system][name]
    except KeyError as exc:
        raise WorkstationApprovalError(
            f"ไม่พบเครื่องมือตรวจสอบระบบที่เชื่อถือได้: {name}"
        ) from exc


def _machine_identity(system: str | None = None) -> str:
    operating_system = system or platform.system()
    if operating_system == "Darwin":
        output = _command_output(
            [
                _trusted_tool("Darwin", "ioreg"),
                "-rd1",
                "-c",
                "IOPlatformExpertDevice",
            ]
        )
        match = re.search(r'"IOPlatformUUID"\s*=\s*"([0-9A-Fa-f-]{36})"', output)
        if not match:
            raise WorkstationApprovalError("ไม่พบ machine ID ของ macOS")
        return f"macos:{match.group(1).lower()}"
    if operating_system == "Linux":
        try:
            machine_id = Path("/etc/machine-id").read_text(encoding="ascii").strip()
        except OSError as exc:
            raise WorkstationApprovalError("ไม่พบ machine ID ของ Linux") from exc
        if not re.fullmatch(r"[0-9a-fA-F]{32}", machine_id):
            raise WorkstationApprovalError("machine ID ของ Linux ไม่ถูกต้อง")
        return f"linux:{machine_id.lower()}"
    raise WorkstationApprovalError(f"ยังไม่รองรับการอนุมัติเครื่องสำหรับ {operating_system}")


def _macos_encryption_status(destination: Path) -> dict[str, Any]:
    existing = _existing_parent(destination)
    if existing.stat().st_dev == Path("/").stat().st_dev:
        output = _command_output([_trusted_tool("Darwin", "fdesetup"), "status"])
        enabled = _macos_filevault_enabled(output)
        technology = "FileVault"
    else:
        output = _command_output(
            [_trusted_tool("Darwin", "diskutil"), "info", str(existing)]
        )
        enabled = _macos_diskutil_encrypted(output)
        technology = "Encrypted macOS volume"
    return {
        "platform": "macOS",
        "technology": technology,
        "enabled": enabled,
        "evidence": output,
        "destination": str(destination.expanduser().resolve()),
    }


def _linux_encryption_status(destination: Path) -> dict[str, Any]:
    existing = _existing_parent(destination)
    source = _command_output(
        [
            _trusted_tool("Linux", "findmnt"),
            "-n",
            "-o",
            "SOURCE",
            "-T",
            str(existing),
        ]
    ).splitlines()[0]
    types = _command_output(
        [_trusted_tool("Linux", "lsblk"), "-s", "-n", "-o", "TYPE", source]
    )
    enabled = "crypt" in {line.strip().lower() for line in types.splitlines()}
    return {
        "platform": "Linux",
        "technology": "LUKS/dm-crypt",
        "enabled": enabled,
        "evidence": f"source={source}; block_types={','.join(types.split())}",
        "destination": str(destination.expanduser().resolve()),
    }


def disk_encryption_status(
    destination: Path = DEFAULT_DATA_DESTINATION,
    system: str | None = None,
) -> dict[str, Any]:
    """Return fail-closed encryption status for the destination volume."""
    operating_system = system or platform.system()
    if operating_system == "Darwin":
        return _macos_encryption_status(destination)
    if operating_system == "Linux":
        return _linux_encryption_status(destination)
    raise WorkstationApprovalError(
        f"ยังไม่มีวิธีตรวจ disk encryption สำหรับ {operating_system}"
    )


def _require_encryption(destination: Path) -> dict[str, Any]:
    status = disk_encryption_status(destination)
    if not status.get("enabled"):
        technology = status.get("technology") or "disk encryption"
        raise WorkstationApprovalError(f"{technology} ยังไม่เปิดใช้งาน")
    return status


def _write_marker(marker: Path, payload: dict[str, Any]) -> None:
    marker = marker.expanduser().absolute()
    marker.parent.mkdir(parents=True, exist_ok=True)
    if marker.is_symlink():
        raise WorkstationApprovalError("ไฟล์อนุมัติต้องไม่เป็น symlink")
    try:
        atomic_json(marker, payload, mode=0o644)
    except PodDataSyncError as exc:
        raise WorkstationApprovalError(str(exc)) from exc


def approve_workstation(
    approved_by: str,
    marker: Path = DEFAULT_MARKER,
    destination: Path = DEFAULT_DATA_DESTINATION,
) -> dict[str, Any]:
    """Record an approval only after live volume-encryption verification."""
    _require_approval_authority()
    approver = approved_by.strip()
    if not approver:
        raise WorkstationApprovalError("ต้องระบุผู้อนุมัติเครื่อง")
    now = datetime.now(UTC)
    payload = {
        "schema": APPROVAL_SCHEMA,
        "hostname": socket.gethostname(),
        "machine_id": _machine_identity(),
        "approved_by": approver,
        "approved_at_utc": now.isoformat(),
        "expires_at_utc": (now + timedelta(days=APPROVAL_VALID_DAYS)).isoformat(),
        "disk_encryption": _require_encryption(destination),
    }
    _write_marker(marker, payload)
    return payload


def _marker_time(payload: dict[str, Any], field: str) -> datetime:
    try:
        value = datetime.fromisoformat(
            str(payload.get(field) or "").replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise WorkstationApprovalError("วันเวลาการอนุมัติไม่ถูกต้อง") from exc
    if value.tzinfo is None:
        raise WorkstationApprovalError("วันเวลาการอนุมัติไม่มี timezone")
    return value.astimezone(UTC)


def require_workstation_approval(
    destination: Path = DEFAULT_DATA_DESTINATION,
    marker: Path = DEFAULT_MARKER,
) -> dict[str, Any]:
    """Validate local approval and re-check encryption before every sync."""
    marker = marker.expanduser().absolute()
    try:
        payload, marker_stat = read_private_json(marker)
    except PodDataSyncError as exc:
        raise WorkstationApprovalError("เครื่องนี้ยังไม่ได้รับอนุมัติให้เก็บข้อมูล Wellness") from exc
    if not isinstance(payload, dict) or payload.get("schema") != APPROVAL_SCHEMA:
        raise WorkstationApprovalError("รูปแบบการอนุมัติเครื่องไม่ถูกต้อง")
    if stat.S_IMODE(marker_stat.st_mode) & 0o022:
        raise WorkstationApprovalError("ไฟล์อนุมัติต้องห้ามผู้ใช้ทั่วไปแก้ไข")
    if hasattr(os, "getuid") and marker_stat.st_uid != _approval_owner_uid():
        raise WorkstationApprovalError("ไฟล์อนุมัติไม่ได้เป็นของ OS administrator")
    if payload.get("hostname") != socket.gethostname():
        raise WorkstationApprovalError("การอนุมัตินี้เป็นของเครื่องอื่น")
    if payload.get("machine_id") != _machine_identity():
        raise WorkstationApprovalError("machine ID ไม่ตรงกับเครื่องที่อนุมัติ")
    if not str(payload.get("approved_by") or "").strip():
        raise WorkstationApprovalError("ไม่พบผู้อนุมัติเครื่อง")
    approved_at = _marker_time(payload, "approved_at_utc")
    expires_at = _marker_time(payload, "expires_at_utc")
    now = datetime.now(UTC)
    if approved_at > now + timedelta(minutes=10):
        raise WorkstationApprovalError("วันอนุมัติอยู่ในอนาคต")
    if expires_at - approved_at > timedelta(days=APPROVAL_VALID_DAYS, minutes=1):
        raise WorkstationApprovalError("ระยะเวลาการอนุมัติเกินนโยบาย")
    if expires_at <= now:
        raise WorkstationApprovalError("การอนุมัติเครื่องหมดอายุแล้ว")
    original_encryption = payload.get("disk_encryption")
    if not isinstance(original_encryption, dict) or not original_encryption.get(
        "enabled"
    ):
        raise WorkstationApprovalError("ไม่พบหลักฐาน encryption ตอนอนุมัติเครื่อง")
    payload["disk_encryption_current"] = _require_encryption(destination)
    return payload
