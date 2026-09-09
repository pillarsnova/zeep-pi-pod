from __future__ import annotations

import importlib.util
import pathlib
import unittest


SCRIPT = pathlib.Path(__file__).parents[1] / "tools" / "cem_calibrate.py"
SPEC = importlib.util.spec_from_file_location("cem_calibrate", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class CemCalibrationTests(unittest.TestCase):
    def test_cli_workflow_is_retired(self) -> None:
        with self.assertRaisesRegex(SystemExit, "archived firmware calibration"):
            MODULE.main()

    def test_consistent_offset_passes(self) -> None:
        pairs = []
        for reference in (35.0, 45.0, 55.0, 65.0):
            for jitter in (-0.2, 0.0, 0.2):
                pairs.append({
                    "cem_dba": reference,
                    "firmware_dba": reference - 2.0 + jitter,
                })
        result = MODULE.evaluate(pairs, "abc")
        self.assertEqual(result["decision"], "PASS")
        self.assertAlmostEqual(result["recommended_offset_db"], 2.0)

    def test_nonlinear_sensor_fails(self) -> None:
        pairs = [
            {"cem_dba": value, "firmware_dba": measured}
            for value, measured in (
                (35.0, 35.0),
                (35.0, 35.2),
                (35.0, 34.8),
                (45.0, 39.0),
                (45.0, 39.2),
                (45.0, 38.8),
                (55.0, 46.0),
                (55.0, 46.2),
                (55.0, 45.8),
                (65.0, 51.0),
                (65.0, 51.2),
                (65.0, 50.8),
            )
        ]
        self.assertEqual(MODULE.evaluate(pairs, "abc")["decision"], "FAIL")


if __name__ == "__main__":
    unittest.main()
