from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from operations import workstation_approval


def _status(enabled: bool) -> dict[str, object]:
    return {
        "platform": "macOS",
        "technology": "FileVault",
        "enabled": enabled,
        "evidence": f"FileVault is {'On' if enabled else 'Off'}.",
    }


class WorkstationApprovalTest(unittest.TestCase):
    def test_approval_requires_encryption_and_is_bound_to_host(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            marker = root / "approval.json"
            destination = root / "snapshots"
            with (
                patch.object(
                    workstation_approval,
                    "disk_encryption_status",
                    return_value=_status(True),
                ),
                patch.object(
                    workstation_approval.socket,
                    "gethostname",
                    return_value="team-mac",
                ),
                patch.object(
                    workstation_approval,
                    "_approval_owner_uid",
                    return_value=os.getuid(),
                ),
                patch.object(
                    workstation_approval,
                    "_machine_identity",
                    return_value="macos:test-machine-id",
                ),
            ):
                approved = workstation_approval.approve_workstation(
                    "Owner", marker=marker, destination=destination
                )
                checked = workstation_approval.require_workstation_approval(
                    destination=destination, marker=marker
                )
            self.assertEqual(approved["hostname"], "team-mac")
            self.assertEqual(checked["approved_by"], "Owner")
            self.assertEqual(checked["machine_id"], "macos:test-machine-id")
            self.assertTrue(checked["disk_encryption_current"]["enabled"])
            self.assertEqual(marker.stat().st_mode & 0o777, 0o644)

    def test_unencrypted_workstation_cannot_be_approved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            marker = Path(temporary) / "approval.json"
            with (
                patch.object(
                    workstation_approval,
                    "disk_encryption_status",
                    return_value=_status(False),
                ),
                patch.object(
                    workstation_approval,
                    "_approval_owner_uid",
                    return_value=os.getuid(),
                ),
                patch.object(
                    workstation_approval,
                    "_machine_identity",
                    return_value="macos:test-machine-id",
                ),
            ):
                with self.assertRaisesRegex(
                    workstation_approval.WorkstationApprovalError,
                    "ยังไม่เปิดใช้งาน",
                ):
                    workstation_approval.approve_workstation("Owner", marker=marker)
            self.assertFalse(marker.exists())

    def test_diskutil_parser_requires_yes_on_encryption_line(self) -> None:
        misleading = "FileVault: No\nEncrypted: No\nSolid State: Yes\n"
        self.assertFalse(workstation_approval._macos_diskutil_encrypted(misleading))
        self.assertTrue(
            workstation_approval._macos_diskutil_encrypted("FileVault: Yes\n")
        )
        self.assertTrue(
            workstation_approval._macos_diskutil_encrypted("Encrypted: Yes\n")
        )

    def test_filevault_parser_accepts_only_exact_enabled_status(self) -> None:
        self.assertTrue(
            workstation_approval._macos_filevault_enabled("FileVault is On.\n")
        )
        self.assertFalse(
            workstation_approval._macos_filevault_enabled(
                "FileVault is Off.\nEncryption is On for another volume.\n"
            )
        )
        self.assertFalse(
            workstation_approval._macos_filevault_enabled(
                "FileVault is Off.\nFileVault is On.\n"
            )
        )

    def test_encryption_tools_are_absolute_and_run_with_minimal_env(self) -> None:
        for tools in workstation_approval.TRUSTED_TOOLS.values():
            for executable in tools.values():
                self.assertTrue(Path(executable).is_absolute())

        result = SimpleNamespace(returncode=0, stdout="FileVault is On.\n", stderr="")
        with patch.object(
            workstation_approval.subprocess,
            "run",
            return_value=result,
        ) as run:
            output = workstation_approval._command_output(
                ["/usr/bin/fdesetup", "status"]
            )

        self.assertEqual(output, "FileVault is On.")
        (command,) = run.call_args.args
        self.assertEqual(command[0], "/usr/bin/fdesetup")
        self.assertEqual(
            run.call_args.kwargs["env"],
            {
                "LANG": "C",
                "LC_ALL": "C",
                "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            },
        )

    def test_copied_marker_is_rejected_on_another_host(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            marker = Path(temporary) / "approval.json"
            marker.write_text(
                json.dumps(
                    {
                        "schema": workstation_approval.APPROVAL_SCHEMA,
                        "hostname": "different-host",
                        "approved_by": "Owner",
                        "expires_at_utc": (
                            datetime.now(UTC) + timedelta(days=1)
                        ).isoformat(),
                    }
                ),
                encoding="utf-8",
            )
            marker.chmod(0o644)
            with (
                patch.object(
                    workstation_approval,
                    "_approval_owner_uid",
                    return_value=os.getuid(),
                ),
                patch.object(
                    workstation_approval.socket,
                    "gethostname",
                    return_value="team-mac",
                ),
            ):
                with self.assertRaisesRegex(
                    workstation_approval.WorkstationApprovalError,
                    "เครื่องอื่น",
                ):
                    workstation_approval.require_workstation_approval(marker=marker)

    def test_marker_symlink_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target.json"
            marker = root / "approval.json"
            target.write_text("{}", encoding="utf-8")
            target.chmod(0o600)
            marker.symlink_to(target)
            with self.assertRaisesRegex(
                workstation_approval.WorkstationApprovalError,
                "ยังไม่ได้รับอนุมัติ",
            ):
                workstation_approval.require_workstation_approval(marker=marker)

    def test_predictable_temp_symlink_is_not_followed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            marker = root / "approval.json"
            victim = root / "victim"
            victim.write_text("keep", encoding="utf-8")
            victim.chmod(0o644)
            marker.with_suffix(".json.tmp").symlink_to(victim)
            with (
                patch.object(
                    workstation_approval,
                    "disk_encryption_status",
                    return_value=_status(True),
                ),
                patch.object(
                    workstation_approval,
                    "_approval_owner_uid",
                    return_value=os.getuid(),
                ),
                patch.object(
                    workstation_approval,
                    "_machine_identity",
                    return_value="macos:test-machine-id",
                ),
            ):
                workstation_approval.approve_workstation("Owner", marker=marker)
            self.assertEqual(victim.read_text(encoding="utf-8"), "keep")
            self.assertEqual(victim.stat().st_mode & 0o777, 0o644)

    def test_handcrafted_incomplete_marker_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            marker = Path(temporary) / "approval.json"
            marker.write_text(
                json.dumps(
                    {
                        "schema": workstation_approval.APPROVAL_SCHEMA,
                        "hostname": workstation_approval.socket.gethostname(),
                        "machine_id": "macos:test-machine-id",
                        "approved_by": "Owner",
                        "expires_at_utc": (
                            datetime.now(UTC) + timedelta(days=5000)
                        ).isoformat(),
                    }
                ),
                encoding="utf-8",
            )
            marker.chmod(0o644)
            with (
                patch.object(
                    workstation_approval,
                    "_approval_owner_uid",
                    return_value=os.getuid(),
                ),
                patch.object(
                    workstation_approval,
                    "_machine_identity",
                    return_value="macos:test-machine-id",
                ),
                self.assertRaisesRegex(
                    workstation_approval.WorkstationApprovalError, "วันเวลา"
                ),
            ):
                workstation_approval.require_workstation_approval(marker=marker)

    def test_unprivileged_user_cannot_issue_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            marker = Path(temporary) / "approval.json"
            with (
                patch.object(workstation_approval.os, "geteuid", return_value=501),
                self.assertRaisesRegex(
                    workstation_approval.WorkstationApprovalError,
                    "OS administrator",
                ),
            ):
                workstation_approval.approve_workstation("Self", marker=marker)
            self.assertFalse(marker.exists())

    def test_self_issued_user_owned_marker_is_rejected(self) -> None:
        now = datetime.now(UTC)
        payload = {
            "schema": workstation_approval.APPROVAL_SCHEMA,
            "hostname": "team-mac",
            "machine_id": "macos:test-machine-id",
            "approved_by": "Self",
            "approved_at_utc": now.isoformat(),
            "expires_at_utc": (now + timedelta(days=1)).isoformat(),
            "disk_encryption": _status(True),
        }
        user_owned = SimpleNamespace(st_mode=0o100644, st_uid=501)
        with (
            patch.object(
                workstation_approval,
                "read_private_json",
                return_value=(payload, user_owned),
            ),
            self.assertRaisesRegex(
                workstation_approval.WorkstationApprovalError,
                "OS administrator",
            ),
        ):
            workstation_approval.require_workstation_approval(
                marker=Path("/tmp/self-issued-approval.json")
            )

    def test_marker_is_bound_to_stable_machine_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            marker = Path(temporary) / "approval.json"
            destination = Path(temporary) / "snapshots"
            with (
                patch.object(
                    workstation_approval,
                    "disk_encryption_status",
                    return_value=_status(True),
                ),
                patch.object(
                    workstation_approval,
                    "_approval_owner_uid",
                    return_value=os.getuid(),
                ),
                patch.object(
                    workstation_approval,
                    "_machine_identity",
                    return_value="macos:machine-a",
                ),
            ):
                workstation_approval.approve_workstation(
                    "Owner", marker=marker, destination=destination
                )
            with (
                patch.object(
                    workstation_approval,
                    "_approval_owner_uid",
                    return_value=os.getuid(),
                ),
                patch.object(
                    workstation_approval,
                    "_machine_identity",
                    return_value="macos:machine-b",
                ),
                self.assertRaisesRegex(
                    workstation_approval.WorkstationApprovalError,
                    "machine ID",
                ),
            ):
                workstation_approval.require_workstation_approval(
                    destination=destination,
                    marker=marker,
                )

    def test_windows_fails_closed_until_acl_transport_is_supported(self) -> None:
        with self.assertRaisesRegex(
            workstation_approval.WorkstationApprovalError, "Windows"
        ):
            workstation_approval.disk_encryption_status(system="Windows")


if __name__ == "__main__":
    unittest.main()
