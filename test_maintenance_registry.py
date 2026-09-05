"""Regression checks for supported offline maintenance/data-correction tools."""

from pathlib import Path
import unittest

import maintenance_registry as registry


ROOT = Path(__file__).resolve().parent


class MaintenanceRegistryTests(unittest.TestCase):
    def test_registry_covers_every_supported_tool_and_file_exists(self):
        expected = {
            "reclassify_sleep_history.py",
            "audit_sleep_history_shadow.py",
            "promote_sleep_history.py",
            "compare_sleep_history_replay.py",
            "rescore_session_reports.py",
            "recalibrate_sound_history.py",
            "cleanup_short_sessions.py",
            "trim_session.py",
            "reset_sleep_dataset.py",
            "annotate_sleep_stage.py",
        }
        self.assertEqual(set(registry.MAINTENANCE_TOOLS), expected)
        for filename in expected:
            self.assertTrue((ROOT / filename).is_file(), filename)
            source = (ROOT / filename).read_text(encoding="utf-8")
            self.assertIn(f'MAINTENANCE_TOOL_NAME = "{filename}"', source)

    def test_every_tool_declares_write_boundary_and_guard(self):
        for filename, spec in registry.MAINTENANCE_TOOLS.items():
            with self.subTest(tool=filename):
                self.assertTrue(spec["group"])
                self.assertTrue(spec["purpose"])
                self.assertIsInstance(spec["writes"], list)
                self.assertTrue(spec["preserves"])
                self.assertTrue(spec["guard"])
                self.assertIn(
                    spec["default_mode"],
                    {
                        "audit_only", "dry_run", "read_only",
                        "refuse_without_confirmation",
                    },
                )

    def test_no_browser_execution_is_exposed(self):
        snapshot = registry.maintenance_contract_snapshot()
        self.assertFalse(snapshot["browser_execution_enabled"])
        self.assertEqual(snapshot["tools"], registry.MAINTENANCE_TOOLS)


if __name__ == "__main__":
    unittest.main()
