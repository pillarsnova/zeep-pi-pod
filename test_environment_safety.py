import unittest

from zeep_pod.sessions.environment_safety import (
    safety_limit_text,
    summarize_safety_excursions,
)


class EnvironmentSafetyTests(unittest.TestCase):
    def test_range_limits_are_exclusive_and_keep_both_boundaries(self):
        criterion = {"critical_below": 13.0, "critical_above": 32.0}
        summary = summarize_safety_excursions(
            [12.0, 13.0, 24.0, 32.0, 33.0],
            criterion,
        )

        self.assertEqual(summary["excursion_sample_count"], 2)
        self.assertEqual(summary["critical_below"], 13.0)
        self.assertEqual(summary["critical_above"], 32.0)
        self.assertEqual(
            safety_limit_text(summary, "°C"),
            "อยู่นอกช่วง 13–32°C",
        )

    def test_upper_inclusive_limit_remains_compatible_with_co2(self):
        summary = summarize_safety_excursions(
            [1299.0, 1300.0],
            {"critical_at_or_above": 1300.0},
        )

        self.assertEqual(summary["excursion_sample_count"], 1)
        self.assertEqual(summary["threshold"], 1300.0)
        self.assertEqual(
            safety_limit_text({"safety_threshold": 1300.0}, "ppm"),
            "แตะหรือเกิน 1300ppm",
        )


if __name__ == "__main__":
    unittest.main()
