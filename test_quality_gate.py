"""Keep focused validation aligned with extracted module ownership."""

from __future__ import annotations

import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import quality_gate


class QualityGateSelectionTests(unittest.TestCase):
    def plan_for(self, path: str) -> list[str]:
        return quality_gate.test_plan(quality_gate.classify(path))

    def test_extracted_live_estimator_runs_sleep_and_session_regressions(self):
        plan = self.plan_for("sessions/live_sleep_estimator.py")
        self.assertIn("test_sleep_system_consistency.py", plan)
        self.assertIn("test_sleep_restart_context.py", plan)
        self.assertIn("test_session_lifecycle.py", plan)

    def test_ai_context_keeps_privacy_and_learning_tests(self):
        plan = self.plan_for("sessions/user_ai_context.py")
        self.assertIn("test_user_ai_context.py", plan)
        self.assertIn("test_user_learning_profile.py", plan)

    def test_extracted_adaptive_features_run_advisory_tests(self):
        plan = self.plan_for("adaptive/features.py")
        self.assertIn("test_adaptive_learning.py", plan)

    def test_bed_motion_runs_physical_control_failsafe_tests(self):
        plan = self.plan_for("hardware/bed_motion.py")
        self.assertIn("test_control_failsafe.py", plan)

    def test_extracted_bcg_reader_keeps_sensor_regressions(self):
        plan = self.plan_for("hardware/bcg.py")
        self.assertIn("test_bcg_reader.py", plan)
        self.assertIn("test_sensor_contract.py", plan)

    def test_matching_test_is_not_hidden_by_broader_domain(self):
        plan = self.plan_for("sessions/personal_behaviour.py")
        self.assertIn("test_personal_behaviour.py", plan)

    def test_changed_files_includes_deleted_paths_in_both_git_diffs(self):
        def git_results(*args):
            if args[0] == "diff" and "--diff-filter=ACDMR" in args:
                return ["adaptive/removed.py"]
            return []

        with patch.object(quality_gate, "git_lines", side_effect=git_results) as git:
            self.assertEqual(
                quality_gate.changed_files("origin/develop"),
                ["adaptive/removed.py"],
            )

        diffs = [call.args for call in git.call_args_list if call.args[0] == "diff"]
        self.assertEqual(len(diffs), 2)
        self.assertTrue(all("--diff-filter=ACDMR" in args for args in diffs))

    def test_removed_test_triggers_full_instead_of_importing_missing_module(self):
        with tempfile.TemporaryDirectory() as root:
            with patch.object(quality_gate, "ROOT", Path(root)):
                self.assertEqual(quality_gate.classify("test_removed.py"), {"full"})

    def test_test_plan_deduplicates_overlapping_profiles(self):
        plan = quality_gate.test_plan(
            {"core", "session", "test:test_session_lifecycle.py"}
        )
        self.assertEqual(plan.count("test_session_lifecycle.py"), 1)

    def test_start_characterization_is_in_session_gate(self):
        self.assertIn("test_session_start.py", quality_gate.PROFILE_TESTS["session"])

    def test_every_focused_profile_references_existing_tests(self):
        for profile, tests in quality_gate.PROFILE_TESTS.items():
            for filename in tests:
                with self.subTest(profile=profile, filename=filename):
                    self.assertTrue((quality_gate.ROOT / filename).is_file())

    def test_focused_style_targets_match_full_package_boundary(self):
        self.assertEqual(
            quality_gate.package_style_targets(
                [
                    "app.py",
                    "test_session_start.py",
                    "sessions/live_projection.py",
                    "hardware/bed_motion.py",
                    "docs/architecture.md",
                ]
            ),
            ["sessions/live_projection.py", "hardware/bed_motion.py"],
        )

    def test_changed_roots_compile_without_expanding_legacy_lint_scope(self):
        paths = [
            "app.py",
            "sessions/live_projection.py",
            "test_session_live_projection.py",
        ]
        args = SimpleNamespace(
            scopes=["changed"],
            base="origin/develop",
            dry_run=True,
            list_profiles=False,
        )
        with (
            patch.object(quality_gate, "parse_args", return_value=args),
            patch.object(quality_gate, "changed_files", return_value=paths),
            patch.object(quality_gate, "run") as run,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(quality_gate.main(), 0)

        commands = [call.args[0] for call in run.call_args_list]
        style = [command for command in commands if command[1:3] == ["-m", "ruff"]]
        self.assertEqual(
            [command[3:] for command in style],
            [
                ["check", "sessions/live_projection.py"],
                ["format", "--check", "sessions/live_projection.py"],
            ],
        )
        compile_command = next(
            command for command in commands if command[1:3] == ["-m", "py_compile"]
        )
        self.assertEqual(compile_command[3:], paths)


if __name__ == "__main__":
    unittest.main()
