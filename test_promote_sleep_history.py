import unittest

from promote_sleep_history import (
    cohort_minimum_duration_seconds,
    session_is_in_reviewed_cohort,
)


class PromoteSleepHistoryCohortTests(unittest.TestCase):
    def test_operator_zero_minimum_allows_short_positive_session(self):
        artifact = {"cohort": {"minimum_minutes_exclusive": 0}}

        self.assertEqual(cohort_minimum_duration_seconds(artifact), 0.0)
        self.assertTrue(session_is_in_reviewed_cohort(
            start_time="2026-08-31T17:00:00+00:00",
            end_time="2026-08-31T17:09:00+00:00",
            duration=540,
            minimum_duration_seconds=0.0,
        ))

    def test_reviewed_minimum_remains_exclusive(self):
        self.assertFalse(session_is_in_reviewed_cohort(
            start_time="2026-08-31T17:00:00+00:00",
            end_time="2026-08-31T17:30:00+00:00",
            duration=1_500,
            minimum_duration_seconds=1_500,
        ))

    def test_open_or_pre_cutover_session_is_ineligible(self):
        common = {
            "duration": 1_800,
            "minimum_duration_seconds": 0.0,
        }
        self.assertFalse(session_is_in_reviewed_cohort(
            start_time="2026-08-31T17:00:00+00:00",
            end_time=None,
            **common,
        ))
        self.assertFalse(session_is_in_reviewed_cohort(
            start_time="2026-08-31T16:59:59+00:00",
            end_time="2026-08-31T17:30:00+00:00",
            **common,
        ))

    def test_negative_cohort_minimum_is_rejected(self):
        with self.assertRaises(ValueError):
            cohort_minimum_duration_seconds({
                "cohort": {"minimum_minutes_exclusive": -1},
            })


if __name__ == "__main__":
    unittest.main()
