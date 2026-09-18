"""Guard the incremental move away from the legacy composition root."""

from __future__ import annotations

import ast
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DOMAIN_PACKAGE_NAMES = (
    "acoustics",
    "adaptive",
    "api",
    "common",
    "hardware",
    "identity",
    "operations",
    "presentation",
    "safety",
    "sensors",
    "sessions",
)
DOMAIN_PACKAGES = tuple(ROOT / name for name in DOMAIN_PACKAGE_NAMES)
MAX_PACKAGE_FILE_LINES = 500
MAX_FUNCTION_LINES = 90
MAX_APP_LINES = 6_839
MAX_SNAPSHOT_FUNCTION_LINES = 118
MAX_BCG_READER_FACADE_LINES = 31
MAX_SENSOR_FRAME_SAMPLER_FACADE_LINES = 27
MAX_FINALIZATION_COMMIT_FACADE_LINES = 19
ROOT_COMPATIBILITY_FACADE_LINE_CAPS = {
    "api_history.py": 8,
    "api_models.py": 12,
    "api_v1.py": 18,
    "sensor_calibration.py": 8,
    "sensor_contracts.py": 8,
    "sensor_runtime.py": 8,
    "sound_observability.py": 8,
    "api_state_projection.py": 24,
}
COMMON_VALUE_MIGRATED_MODULES = (
    "sessions/presentation_metrics.py",
    "sessions/protocol_publication.py",
    "sessions/result_context.py",
    "sessions/result_contract.py",
    "sessions/result_restore_contract.py",
    "sessions/restore_summary.py",
    "sessions/restore_summary_baseline.py",
    "sessions/score_summary.py",
    "sessions/target_provenance.py",
    "sessions/usage_development.py",
    "sessions/usage_presentation.py",
    "sessions/usage_publication.py",
    "sessions/user_learning_profile.py",
    "sessions/user_score_history.py",
)
COMMON_FINITE_NUMBER_MIGRATED_MODULES = {
    "sleep_session_report.py": "_number",
    "adaptive/features.py": "finite_number",
    "sessions/environment_safety.py": "_finite_number",
    "sessions/user_baseline_context.py": "_number",
}
LEGACY_PACKAGE_FACADES = {
    "api_history",
    "api_models",
    "api_v1",
    "sensor_calibration",
    "sensor_contracts",
    "sensor_runtime",
    "sound_observability",
    "api_state_projection",
}
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
LEGACY_PACKAGE_FILE_LINE_CAPS = {
    # Behavior-preserving first migration; subsequent estimator refactors must
    # split this module and may never increase the temporary ceiling.
    "sessions/live_sleep_estimator.py": 1_171,
}
LEGACY_FUNCTION_LINE_CAPS = {
    "reclassify_sleep_history.py:main": 291,
    "reclassify_sleep_history.py:rescore_event": 239,
    "sessions/live_sleep_estimator.py:estimate_sleep_state": 1_156,
    "sessions/live_sleep_estimator.py:carry_occupied_epoch": 134,
    "app.py:_finalize_active_session": 349,
    "sleep_session_report.py:_build_awake_rest_quality": 447,
    "sleep_session_report.py:build_session_report": 588,
    "sleep_stage_scoring.py:score_sleep_evidence": 421,
    "sleep_system_policy.py:sleep_policy_snapshot": 406,
}


def _is_state_session_subscript(node: ast.AST) -> bool:
    return bool(
        isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Name)
        and node.value.id == "state"
        and isinstance(node.slice, ast.Constant)
        and node.slice.value == "session"
    )


def _targets_session_state(node: ast.AST) -> bool:
    if _is_state_session_subscript(node):
        return True
    if isinstance(node, ast.Subscript):
        return _targets_session_state(node.value)
    if isinstance(node, (ast.Tuple, ast.List)):
        return any(_targets_session_state(item) for item in node.elts)
    return False


def _is_session_mutator_call(node: ast.Call) -> bool:
    function = node.func
    return bool(
        isinstance(function, ast.Attribute)
        and function.attr in {"clear", "pop", "setdefault", "update"}
        and _is_state_session_subscript(function.value)
    )


class ModularArchitectureTests(unittest.TestCase):
    """Keep new domain modules small and independent from ``app.py``."""

    def package_modules(self) -> list[Path]:
        return sorted(
            path for package in DOMAIN_PACKAGES for path in package.rglob("*.py")
        )

    def test_legacy_namespace_is_removed(self) -> None:
        self.assertFalse((ROOT / "zeep_pod").exists())

    def test_domain_packages_resolve_from_this_project(self) -> None:
        origins: dict[str, str] = {}
        for name in DOMAIN_PACKAGE_NAMES:
            spec = importlib.util.find_spec(name)
            if spec is None or spec.origin is None:
                origins[name] = "missing"
                continue
            origin = Path(spec.origin).resolve()
            try:
                origin.relative_to(ROOT)
            except ValueError:
                origins[name] = str(origin)
        self.assertEqual(origins, {})

    def test_package_modules_are_bounded(self) -> None:
        oversized = {
            path.relative_to(ROOT).as_posix(): len(
                path.read_text(encoding="utf-8").splitlines()
            )
            for path in self.package_modules()
            if len(path.read_text(encoding="utf-8").splitlines())
            > LEGACY_PACKAGE_FILE_LINE_CAPS.get(
                path.relative_to(ROOT).as_posix(), MAX_PACKAGE_FILE_LINES
            )
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
                key = f"{path.relative_to(ROOT)}:{node.name}"
                if key in LEGACY_FUNCTION_LINE_CAPS:
                    continue
                if length > MAX_FUNCTION_LINES:
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

    def test_live_session_state_writes_use_the_app_facade(self) -> None:
        tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
        allowed = {
            "_patch_session_projection_locked",
            "_replace_session_projection_locked",
        }
        offenders: list[str] = []
        functions = (
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        )
        for function in functions:
            for node in ast.walk(function):
                if isinstance(node, ast.Call) and _is_session_mutator_call(node):
                    if function.name not in allowed:
                        offenders.append(f"{function.name}:{node.lineno}")
                if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                    targets = (
                        node.targets
                        if isinstance(node, ast.Assign)
                        else [node.target]
                    )
                    if any(_targets_session_state(target) for target in targets):
                        if function.name not in allowed:
                            offenders.append(f"{function.name}:{node.lineno}")
                    if (
                        isinstance(node, ast.Assign)
                        and _is_state_session_subscript(node.value)
                        and function.name != "_replace_session_projection_locked"
                    ):
                        offenders.append(f"{function.name}:{node.lineno}:alias")
        self.assertEqual(offenders, [])

    def test_root_compatibility_facades_remain_thin(self) -> None:
        oversized = {
            relative_path: lines
            for relative_path, maximum in ROOT_COMPATIBILITY_FACADE_LINE_CAPS.items()
            if (
                lines := len(
                    (ROOT / relative_path).read_text(encoding="utf-8").splitlines()
                )
            )
            > maximum
        }
        self.assertEqual(oversized, {})

    def test_migrated_modules_use_common_value_library(self) -> None:
        duplicates: dict[str, list[str]] = {}
        for relative_path in COMMON_VALUE_MIGRATED_MODULES:
            tree = ast.parse((ROOT / relative_path).read_text(encoding="utf-8"))
            names = [
                node.name
                for node in tree.body
                if isinstance(node, ast.FunctionDef)
                and node.name in {"_mapping", "_number"}
            ]
            if names:
                duplicates[relative_path] = names
        self.assertEqual(duplicates, {})

    def test_finite_number_migrations_stay_in_common_library(self) -> None:
        duplicates: dict[str, str] = {}
        for relative_path, helper_name in COMMON_FINITE_NUMBER_MIGRATED_MODULES.items():
            tree = ast.parse((ROOT / relative_path).read_text(encoding="utf-8"))
            if any(
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == helper_name
                for node in tree.body
            ):
                duplicates[relative_path] = helper_name
        self.assertEqual(duplicates, {})

    def test_api_and_sensor_packages_avoid_legacy_facades(self) -> None:
        offenders: dict[str, list[str]] = {}
        paths = [
            *sorted((ROOT / "api").glob("*.py")),
            *sorted((ROOT / "sensors").glob("*.py")),
        ]
        for path in paths:
            imported: list[str] = []
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.extend(
                        alias.name
                        for alias in node.names
                        if alias.name in LEGACY_PACKAGE_FACADES
                    )
                elif (
                    isinstance(node, ast.ImportFrom)
                    and node.module in LEGACY_PACKAGE_FACADES
                ):
                    imported.append(str(node.module))
            if imported:
                offenders[path.relative_to(ROOT).as_posix()] = imported
        self.assertEqual(offenders, {})

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
