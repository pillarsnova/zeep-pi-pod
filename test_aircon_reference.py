"""Regression tests for import-safe Aircon fan-reference persistence."""

from __future__ import annotations

import ast
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from hardware.aircon_reference import AirconFanReferenceStore

ROOT = Path(__file__).resolve().parent
FIXED_NOW = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)


class AirconFanReferenceStoreTests(unittest.TestCase):
    def store(
        self,
        path: Path,
        *,
        on_invalid=None,
    ) -> AirconFanReferenceStore:
        return AirconFanReferenceStore(
            path,
            1,
            clock=lambda: FIXED_NOW,
            on_invalid=on_invalid,
        )

    def test_constructor_has_no_file_system_side_effect(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "aircon.json"

            self.store(path)

            self.assertFalse(path.exists())
            self.assertFalse(path.parent.exists())

    def test_initialize_creates_default_only_at_lifecycle_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "aircon.json"

            result = self.store(path).initialize()

            self.assertEqual(result["fan_level"], 1)
            self.assertEqual(result["source"], "pod_default_reference")
            self.assertEqual(json.loads(path.read_text())["fan_level"], 1)

    def test_saved_reference_survives_restart_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "aircon.json"
            first = self.store(path)
            first.save(4, "admin_declared_reference", operator="test-admin")

            result = self.store(path).initialize()

            self.assertEqual(result["fan_level"], 4)
            self.assertEqual(result["source"], "admin_declared_reference")
            self.assertEqual(result["operator"], "test-admin")

    def test_legacy_level_only_reference_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "aircon.json"
            path.write_text('{"fan_level": 5}', encoding="utf-8")

            result = self.store(path).initialize()

            self.assertEqual(result["fan_level"], 5)
            self.assertEqual(result["source"], "persisted_reference")
            self.assertIsNone(result["updated_at"])
            self.assertEqual(json.loads(path.read_text())["fan_level"], 5)

    def test_blank_source_keeps_legacy_unknown_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "aircon.json"

            result = self.store(path).save(2, "")

            self.assertEqual(result["source"], "unknown")

    def test_corrupt_reference_is_reported_and_recovered(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "aircon.json"
            path.write_text("not-json", encoding="utf-8")
            invalid: list[Exception] = []

            result = self.store(path, on_invalid=invalid.append).initialize()

            self.assertEqual(result["fan_level"], 1)
            self.assertEqual(result["source"], "recovered_default_reference")
            self.assertEqual(len(invalid), 1)
            self.assertEqual(json.loads(path.read_text())["fan_level"], 1)

    def test_concurrent_saves_leave_one_valid_atomic_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "aircon.json"
            store = self.store(path)

            with ThreadPoolExecutor(max_workers=5) as executor:
                list(
                    executor.map(
                        lambda level: store.save(level, "concurrency_test"),
                        [1, 2, 3, 4, 5] * 4,
                    )
                )

            result = store.load()
            self.assertIn(result["fan_level"], range(1, 6))
            self.assertEqual(result["source"], "concurrency_test")
            self.assertFalse(path.with_suffix(".json.tmp").exists())

    def test_rejects_boolean_and_out_of_range_levels(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self.store(Path(directory) / "aircon.json")
            for value in (True, 0, 6):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    store.save(value, "invalid")


class AirconReferenceCompositionTests(unittest.TestCase):
    def test_app_initializes_repository_inside_lifespan(self) -> None:
        tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
        lifespan = next(
            node
            for node in tree.body
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "lifespan"
        )
        calls = {
            node.func.id
            for node in ast.walk(lifespan)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }

        self.assertIn("_initialize_aircon_fan_reference", calls)
        aircon_line = next(
            node.lineno
            for node in ast.walk(lifespan)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_initialize_aircon_fan_reference"
        )
        gpio_line = next(
            node.lineno
            for node in ast.walk(lifespan)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "initialize"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "gpio"
        )
        self.assertLess(aircon_line, gpio_line)

    def test_app_has_no_module_scope_reference_load(self) -> None:
        tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
        module_calls = {
            node.func.id
            for statement in tree.body
            if not isinstance(
                statement,
                (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
            )
            for node in ast.walk(statement)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }

        self.assertNotIn("_load_aircon_fan_level_reference", module_calls)
        self.assertNotIn("_initialize_aircon_fan_reference", module_calls)


if __name__ == "__main__":
    unittest.main()
