"""Guard the incremental move away from the legacy composition root."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PACKAGE = ROOT / "zeep_pod"
MAX_PACKAGE_FILE_LINES = 500
MAX_FUNCTION_LINES = 90
MAX_APP_LINES = 8_800


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
        app_lines = len(
            (ROOT / "app.py").read_text(encoding="utf-8").splitlines()
        )
        self.assertLessEqual(app_lines, MAX_APP_LINES)

    def test_hardware_classes_live_in_hardware_package(self) -> None:
        tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
        local_classes = {
            node.name for node in tree.body if isinstance(node, ast.ClassDef)
        }
        self.assertNotIn("GPIOManager", local_classes)
        self.assertNotIn("AudioPlayer", local_classes)


if __name__ == "__main__":
    unittest.main()
