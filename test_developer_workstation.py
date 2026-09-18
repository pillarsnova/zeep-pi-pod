"""Owner exceptions never silently authorise another device or destination."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from operations import developer_workstation as dev
from operations import workstation_approval as policy


class DeveloperWorkstationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.marker = self.root / "approval.json"
        self.destination = self.root / "snapshots"
        for target, value in (
            ("platform.system", "Darwin"),
            ("socket.gethostname", "developer-mac"),
            ("approval._machine_identity", "macos:unit-test-device"),
            ("approval.disk_encryption_status", {"enabled": False}),
        ):
            patcher = patch("operations.developer_workstation." + target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def approve(self):
        return dev.approve_development_mac("Project owner", self.destination, marker=self.marker)

    def check(self, destination=None):
        return dev.require_development_mac(destination or self.destination, marker=self.marker)

    def test_exception_records_true_encryption_state(self):
        self.approve()
        result = self.check(self.destination / "pod-1")
        self.assertFalse(result["disk_encryption_current"]["enabled"])
        self.assertTrue(result["encryption_requirement_waived"])
        self.assertFalse(result["os_admin_approval"])

    def test_other_machine_rejected(self):
        self.approve()
        with patch.object(policy, "_machine_identity", return_value="macos:other"):
            with self.assertRaises(policy.WorkstationApprovalError):
                self.check()

    def test_other_destination_rejected(self):
        self.approve()
        with self.assertRaises(policy.WorkstationApprovalError):
            self.check(self.root / "other")

    def test_other_platform_rejected(self):
        self.approve()
        with patch.object(dev.platform, "system", return_value="Linux"):
            with self.assertRaises(policy.WorkstationApprovalError):
                self.check()

    def test_world_readable_marker_rejected(self):
        self.approve()
        os.chmod(self.marker, 0o644)
        with self.assertRaises(policy.WorkstationApprovalError):
            self.check()

    def test_symlink_marker_rejected(self):
        self.approve()
        link = self.root / "link.json"
        link.symlink_to(self.marker)
        with self.assertRaises(policy.WorkstationApprovalError):
            dev.require_development_mac(self.destination, marker=link)

    def test_expired_marker_rejected(self):
        payload = self.approve()
        payload["expires_at_utc"] = payload["approved_at_utc"]
        dev.atomic_json(self.marker, payload)
        with self.assertRaises(policy.WorkstationApprovalError):
            self.check()

    def test_no_approval_by_default(self):
        with self.assertRaises(policy.WorkstationApprovalError):
            self.check()


if __name__ == "__main__":
    unittest.main()
