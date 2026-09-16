"""Focused lifecycle tests for the Personal Baseline cache."""

from __future__ import annotations

import ast
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from personal import BaselineStore
from sleep_system_policy import (
    PERSONAL_BASELINE_LEARNING_START_UTC,
    PERSONAL_BEHAVIOUR_BASELINE_VERSION,
    PERSONAL_REST_WINDOW_BASELINE_VERSION,
    ZEEP_SLEEP_BASELINE_VERSION,
)


class _DatabaseStub:
    def read_sessions(self, _query, _params=()):
        return []


def _current_record() -> dict:
    return {
        "policy_version": ZEEP_SLEEP_BASELINE_VERSION,
        "behaviour_policy_version": PERSONAL_BEHAVIOUR_BASELINE_VERSION,
        "rest_window_policy_version": PERSONAL_REST_WINDOW_BASELINE_VERSION,
        "learning_cutoff": {"utc": PERSONAL_BASELINE_LEARNING_START_UTC},
        "status": "learning",
    }


class PersonalBaselineLifecycleTests(unittest.TestCase):
    def test_constructor_does_not_read_or_create_baseline_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary) / "not-created"
            with patch("personal.Path.open") as path_open:
                store = BaselineStore(_DatabaseStub(), data_dir)

            path_open.assert_not_called()
            self.assertFalse(data_dir.exists())
            self.assertFalse(store.initialized)

    def test_initialize_loads_normalized_data_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            record = _current_record()
            (data_dir / "baselines.json").write_text(
                json.dumps({"Person@Example.COM": record}),
                encoding="utf-8",
            )
            store = BaselineStore(_DatabaseStub(), data_dir)

            store.initialize()
            (data_dir / "baselines.json").write_text("{broken", encoding="utf-8")
            store.initialize()

            self.assertTrue(store.initialized)
            self.assertEqual(store.data, {"person@example.com": record})

    def test_corrupt_file_fails_soft_and_is_not_retried(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            (data_dir / "baselines.json").write_text("{broken", encoding="utf-8")
            store = BaselineStore(_DatabaseStub(), data_dir)
            output = StringIO()

            with redirect_stdout(output):
                store.initialize()
                store.initialize()

            self.assertTrue(store.initialized)
            self.assertEqual(store.data, {})
            self.assertIn("ignoring invalid baselines.json", output.getvalue())

    def test_public_read_lazily_initializes_for_direct_callers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            record = _current_record()
            (data_dir / "baselines.json").write_text(
                json.dumps({"person@example.com": record}),
                encoding="utf-8",
            )
            store = BaselineStore(_DatabaseStub(), data_dir)

            self.assertEqual(store.get("PERSON@example.com"), record)
            self.assertTrue(store.initialized)

    def test_app_initializes_baseline_before_identity_migration(self) -> None:
        source = (Path(__file__).resolve().parent / "app.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)
        lifespan = next(
            node
            for node in tree.body
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "lifespan"
        )
        initialize_line = next(
            node.lineno
            for node in ast.walk(lifespan)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "baselines"
            and node.func.attr == "initialize"
        )
        migration_line = next(
            node.lineno
            for node in ast.walk(lifespan)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_migrate_profiles_to_email_keys"
        )

        self.assertLess(initialize_line, migration_line)


if __name__ == "__main__":
    unittest.main()
