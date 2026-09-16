"""Characterization tests for the dependency-free historical replay runtime."""

from __future__ import annotations

import argparse
import ast
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import reclassify_sleep_history as replay
import sleep_system_policy as policy
from zeep_pod.sessions.historical_replay_runtime import HistoricalReplayRuntime


class HistoricalReplayRuntimeTests(unittest.TestCase):
    def test_replay_source_has_no_application_import(self):
        source_path = Path(replay.__file__)
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        imported_modules = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported_modules.update(
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        )

        self.assertNotIn("app", imported_modules)

    def test_defaults_are_the_canonical_estimator_defaults(self):
        runtime = HistoricalReplayRuntime.from_environment({})

        self.assertEqual(
            runtime.baseline_hr_weight,
            policy.SLEEP_DEFAULT_BASELINE_HR_WEIGHT,
        )
        self.assertEqual(
            runtime.baseline_rr_weight,
            policy.SLEEP_DEFAULT_BASELINE_RR_WEIGHT,
        )
        self.assertEqual(
            runtime.n3_rr_conflict_penalty,
            policy.SLEEP_DEFAULT_N3_RR_CONFLICT_PENALTY,
        )
        self.assertEqual(
            runtime.n2_rr_conflict_support,
            policy.SLEEP_DEFAULT_N2_RR_CONFLICT_SUPPORT,
        )
        self.assertEqual(
            runtime.move_wake_ratio,
            policy.SLEEP_DEFAULT_MOVE_WAKE_RATIO,
        )
        self.assertEqual(
            runtime.move_deep_ratio,
            policy.SLEEP_DEFAULT_MOVE_DEEP_RATIO,
        )

    def test_environment_overrides_and_weighting_match_live_contract(self):
        runtime = HistoricalReplayRuntime.from_environment(
            {
                "SLEEP_BASELINE_HR_WEIGHT": "0.25",
                "SLEEP_BASELINE_RR_WEIGHT": "0.75",
                "SLEEP_N3_RR_CONFLICT_PENALTY": "0.11",
                "SLEEP_N2_RR_CONFLICT_SUPPORT": "0.12",
                "SLEEP_MOVE_WAKE_RATIO": "0.2",
                "SLEEP_MOVE_DEEP_RATIO": "0.13",
                "SLEEP_HR_CV_DEEP": "0.03",
                "SLEEP_HR_CV_REM": "0.14",
            }
        )

        self.assertEqual(runtime.baseline_hr_weight, 0.25)
        self.assertEqual(runtime.baseline_rr_weight, 0.75)
        self.assertEqual(runtime.n3_rr_conflict_penalty, 0.11)
        self.assertEqual(runtime.n2_rr_conflict_support, 0.12)
        self.assertEqual(runtime.move_wake_ratio, 0.2)
        self.assertEqual(runtime.move_deep_ratio, 0.13)
        self.assertEqual(runtime.hr_cv_deep, 0.03)
        self.assertEqual(runtime.hr_cv_rem, 0.14)
        self.assertAlmostEqual(
            runtime.physiological_baseline_fit(0.8, 0.4),
            0.5,
        )

    def test_invalid_effective_weights_fail_with_live_startup_guard(self):
        cases = (
            (
                {"SLEEP_BASELINE_HR_WEIGHT": "-0.1"},
                "Sleep baseline weights must not be negative",
            ),
            (
                {"SLEEP_BASELINE_RR_WEIGHT": "-0.1"},
                "Sleep baseline weights must not be negative",
            ),
            (
                {
                    "SLEEP_BASELINE_HR_WEIGHT": "0",
                    "SLEEP_BASELINE_RR_WEIGHT": "0",
                },
                "At least one sleep baseline weight must be positive",
            ),
            (
                {"SLEEP_N3_RR_CONFLICT_PENALTY": "-0.1"},
                "Sleep RR conflict weights must not be negative",
            ),
            (
                {"SLEEP_N2_RR_CONFLICT_SUPPORT": "-0.1"},
                "Sleep RR conflict weights must not be negative",
            ),
        )
        for environment, message in cases:
            with (
                self.subTest(environment=environment),
                self.assertRaisesRegex(RuntimeError, message),
            ):
                HistoricalReplayRuntime.from_environment(environment)

    def test_provenance_uses_canonical_policy_versions(self):
        self.assertEqual(
            HistoricalReplayRuntime.decision_provenance(),
            {
                "estimator_version": policy.SLEEP_ESTIMATOR_VERSION,
                "evidence_version": policy.SLEEP_EVIDENCE_VERSION,
                "baseline_version": policy.ZEEP_SLEEP_BASELINE_VERSION,
                "transition_policy_version": (
                    policy.ZEEP_SLEEP_TRANSITION_POLICY_VERSION
                ),
                "g2_ontology_version": policy.SLEEP_G2_ONTOLOGY_VERSION,
            },
        )

    def test_dry_run_does_not_import_application_composition_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            self._create_empty_history(data_dir)
            arguments = argparse.Namespace(
                data_dir=data_dir,
                session_id="session-1",
                apply=False,
                force=False,
            )
            output = io.StringIO()

            with (
                patch.object(replay, "parse_args", return_value=arguments),
                patch.dict(os.environ, {}, clear=True),
                patch.dict(sys.modules, {"app": None}),
                redirect_stdout(output),
            ):
                replay.main()

            self.assertEqual(
                json.loads(output.getvalue()),
                {
                    "status": "nothing_to_reclassify",
                    "session_id": "session-1",
                },
            )

    @staticmethod
    def _create_empty_history(data_dir: Path) -> None:
        connection = sqlite3.connect(data_dir / "sessions.db")
        try:
            connection.executescript(
                """
                CREATE TABLE sessions (
                    session_id TEXT,
                    start_time TEXT,
                    end_time TEXT,
                    username_key TEXT,
                    gender TEXT
                );
                CREATE TABLE events (
                    id INTEGER,
                    session_id TEXT,
                    timestamp TEXT,
                    type TEXT,
                    value TEXT
                );
                INSERT INTO sessions VALUES (
                    'session-1',
                    '2026-09-16T00:00:00+00:00',
                    '2026-09-16T01:00:00+00:00',
                    'person@example.com',
                    'unspecified'
                );
                """
            )
            connection.commit()
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
