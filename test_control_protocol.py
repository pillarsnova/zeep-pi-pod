"""Side-effect-free contracts for device command normalization."""

from __future__ import annotations

import unittest

from control_protocol import (
    apply_aircon_temperature_bias,
    normalize_aircon_command,
    normalize_bed_command,
)


class AirconProtocolTests(unittest.TestCase):
    def test_normalizes_fixed_and_temperature_commands(self) -> None:
        self.assertEqual(normalize_aircon_command("  SWING_ON  "), "swing_on")
        self.assertEqual(normalize_aircon_command("temp   18"), "temp 18")
        with self.assertRaises(ValueError):
            normalize_aircon_command("temp 33")

    def test_user_temperature_bias_is_explicit_and_bounded(self) -> None:
        self.assertEqual(
            apply_aircon_temperature_bias(
                "temp 20", desired_min_c=15, desired_max_c=25, bias_c=-5,
            ),
            ("temp 15", 20, 15),
        )
        self.assertEqual(
            apply_aircon_temperature_bias(
                "swing_on", desired_min_c=15, desired_max_c=25, bias_c=-5,
            ),
            ("swing_on", None, None),
        )
        with self.assertRaises(ValueError):
            apply_aircon_temperature_bias(
                "temp 14", desired_min_c=15, desired_max_c=25, bias_c=-5,
            )


class BedProtocolTests(unittest.TestCase):
    def test_only_bounded_one_shot_and_reference_commands_are_accepted(self) -> None:
        self.assertEqual(normalize_bed_command(" HEAD_UP "), "head_up")
        self.assertEqual(normalize_bed_command("bed_stop"), "bed_stop")
        with self.assertRaises(ValueError):
            normalize_bed_command("run_forever")


if __name__ == "__main__":
    unittest.main()
