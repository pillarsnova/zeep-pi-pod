"""Run synthetic frontend behaviors using the optional development Node runtime."""

from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NODE = shutil.which("node")


@unittest.skipUnless(NODE, "Node is required for frontend behavior tests")
class FrontendRuntimeTests(unittest.TestCase):
    def test_frontend_behaviors(self):
        suites = sorted((ROOT / "tests" / "frontend").glob("*.test.cjs"))
        self.assertTrue(suites, "Frontend behavior suites must exist")
        result = subprocess.run(
            [NODE, "--test", *(str(suite) for suite in suites)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
