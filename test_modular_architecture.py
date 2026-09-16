"""Guard the incremental move away from the legacy composition root."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PACKAGE = ROOT / "zeep_pod"
MAX_PACKAGE_FILE_LINES = 500
MAX_FUNCTION_LINES = 90
MAX_APP_LINES = 8_025
MAX_SNAPSHOT_FUNCTION_LINES = 118
MAX_BCG_READER_FACADE_LINES = 31
MAX_SENSOR_FRAME_SAMPLER_FACADE_LINES = 27
MAX_FINALIZATION_COMMIT_FACADE_LINES = 19
LEGACY_FILE_LINE_CAPS = {
    "access_control.py": 508,
    "pod_occupancy.py": 387,
    "reclassify_sleep_history.py": 1_109,
    "sleep_session_report.py": 3_584,
    "sleep_stage_scoring.py": 977,
    "sleep_system_policy.py": 1_885,
    "sleep_signal_features.py": 830,
    "personal.py": 1_117,
}
LEGACY_FUNCTION_LINE_CAPS = {
    "reclassify_sleep_history.py:main": 291,
    "reclassify_sleep_history.py:rescore_event": 239,
    "app.py:estimate_sleep_state": 940,
    "app.py:_finalize_active_session": 464,
    "sleep_session_report.py:_build_awake_rest_quality": 447,
    "sleep_session_report.py:build_session_report": 588,
    "sleep_stage_scoring.py:score_sleep_evidence": 421,
    "sleep_system_policy.py:sleep_policy_snapshot": 406,
}


class ModularArchitectureTests(unittest.TestCase):
    """Keep new domain modules small and independent from ``app.py``."""

    def package_modules(self) -> list[Path]:
        return sorted(PACKAGE.rglob("*.py"))

    def test_package_modules_are_bounded(self) -> None:
        oversized = {
            path.relative_to(ROOT).as_posix(): len(
                path.read_text(encoding="utf-8").splitlines()
            )
            for path in self.package_modules()
            if len(path.read_text(encoding="utf-8").splitlines())
            > MAX_PACKAGE_FILE_LINES
        }
        self.assertEqual(oversized, {})

    def test_package_functions_are_bounded(self) -> None:
        oversized: dict[str, int] = {}
        for path in self.package_modules():
            source = path.read_text(encoding="utf-8")
            for node in ast.walk(ast.parse(source)):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                length = int(node.end_lineno or node.lineno) - node.lineno + 1
                if length > MAX_FUNCTION_LINES:
                    key = f"{path.relative_to(ROOT)}:{node.name}"
                    oversized[key] = length
        self.assertEqual(oversized, {})

    def test_package_never_imports_composition_root(self) -> None:
        offenders: list[str] = []
        for path in self.package_modules():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    if any(alias.name == "app" for alias in node.names):
                        offenders.append(path.relative_to(ROOT).as_posix())
                if isinstance(node, ast.ImportFrom) and node.module == "app":
                    offenders.append(path.relative_to(ROOT).as_posix())
        self.assertEqual(offenders, [])

    def test_composition_root_cannot_grow(self) -> None:
        app_lines = len((ROOT / "app.py").read_text(encoding="utf-8").splitlines())
        self.assertLessEqual(app_lines, MAX_APP_LINES)

    def test_legacy_domain_files_cannot_grow(self) -> None:
        oversized = {
            relative_path: lines
            for relative_path, maximum in LEGACY_FILE_LINE_CAPS.items()
            if (
                lines := len(
                    (ROOT / relative_path).read_text(encoding="utf-8").splitlines()
                )
            )
            > maximum
        }
        self.assertEqual(oversized, {})

    def test_legacy_function_hotspots_cannot_grow(self) -> None:
        oversized: dict[str, int] = {}
        found: set[str] = set()
        grouped: dict[str, dict[str, int]] = {}
        for key, maximum in LEGACY_FUNCTION_LINE_CAPS.items():
            relative_path, function_name = key.split(":", 1)
            grouped.setdefault(relative_path, {})[function_name] = maximum
        for relative_path, limits in grouped.items():
            tree = ast.parse((ROOT / relative_path).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if node.name not in limits:
                    continue
                key = f"{relative_path}:{node.name}"
                found.add(key)
                length = int(node.end_lineno or node.lineno) - node.lineno + 1
                if length > limits[node.name]:
                    oversized[key] = length
        self.assertEqual(oversized, {})
        self.assertEqual(set(LEGACY_FUNCTION_LINE_CAPS) - found, set())

    def test_live_snapshot_composition_cannot_regrow(self) -> None:
        tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
        snapshot = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "snapshot"
        )
        length = int(snapshot.end_lineno or snapshot.lineno) - snapshot.lineno + 1
        self.assertLessEqual(length, MAX_SNAPSHOT_FUNCTION_LINES)

    def test_bcg_reader_remains_a_thin_compatibility_facade(self) -> None:
        tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
        reader = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "bcg_reader"
        )
        length = int(reader.end_lineno or reader.lineno) - reader.lineno + 1
        self.assertLessEqual(length, MAX_BCG_READER_FACADE_LINES)

    def test_sensor_sampler_remains_a_thin_compatibility_facade(self) -> None:
        tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
        sampler = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "sensor_frame_sampler"
        )
        length = int(sampler.end_lineno or sampler.lineno) - sampler.lineno + 1
        self.assertLessEqual(length, MAX_SENSOR_FRAME_SAMPLER_FACADE_LINES)

    def test_finalization_commit_remains_a_thin_facade(self) -> None:
        tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
        finalizer = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_commit_live_session_finalization"
        )
        length = int(finalizer.end_lineno or finalizer.lineno) - finalizer.lineno + 1
        self.assertLessEqual(length, MAX_FINALIZATION_COMMIT_FACADE_LINES)

    def test_hardware_classes_live_in_hardware_package(self) -> None:
        tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
        local_classes = {
            node.name for node in tree.body if isinstance(node, ast.ClassDef)
        }
        self.assertNotIn("GPIOManager", local_classes)
        self.assertNotIn("AudioPlayer", local_classes)
        self.assertNotIn("ControlHub2BedMQTT", local_classes)


if __name__ == "__main__":
    unittest.main()
