import json
import unittest

from promote_sleep_history import (
    _event_values,
    cohort_minimum_duration_seconds,
    reviewed_mode_group,
    session_is_in_reviewed_cohort,
    validate_promotion_reconciliation,
)


class PromoteSleepHistoryCohortTests(unittest.TestCase):
    def test_explicit_unresolved_mode_is_not_replaced_by_shadow_guess(self):
        item = {
            "previous_mode": {"resolved": "auto", "group": "unresolved"},
            "mode": {"resolved": "nap_30", "group": "nap_recovery"},
        }

        self.assertEqual(reviewed_mode_group(item), "unresolved")

    def test_explicit_sleep_or_nap_mode_remains_scoreable(self):
        for group in ("sleep", "nap_recovery"):
            with self.subTest(group=group):
                self.assertEqual(
                    reviewed_mode_group({"previous_mode": {"group": group}}),
                    group,
                )

    def test_promoted_stage_persists_its_thirty_second_attribution(self):
        events = _event_values({
            "state_rows": [{
                "t": 60.0,
                "state": "wake",
                "metrics": {},
                "score_eligible": True,
            }],
        })

        _timestamp, event_type, raw_value = events[0]
        value = json.loads(raw_value)
        self.assertEqual(event_type, "sleep_stage")
        self.assertEqual(
            value["attribution_start"], "1970-01-01T00:00:30+00:00"
        )
        self.assertEqual(
            value["attribution_end"], "1970-01-01T00:01:00+00:00"
        )

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


class PromoteSleepHistoryReconciliationTests(unittest.TestCase):
    @staticmethod
    def _report(**accounting_overrides):
        accounting = {
            "display_stage_total_reconciles": True,
            "score_stage_total_reconciles": True,
            "arithmetic_invariant": {"holds": True},
        }
        accounting.update(accounting_overrides)
        return {
            "sleep": {
                "actual_scored_s": 1_800.0,
                "classification_accounting": accounting,
            }
        }

    def test_accepts_fully_reconciled_report_and_quality(self):
        result = validate_promotion_reconciliation(
            self._report(), {"actual_scored_s": 1_800.0}
        )

        self.assertEqual(result["actual_scored_delta_s"], 0.0)

    def test_rejects_display_or_score_total_mismatch(self):
        for key in (
            "display_stage_total_reconciles",
            "score_stage_total_reconciles",
        ):
            with self.subTest(key=key):
                with self.assertRaisesRegex(RuntimeError, key):
                    validate_promotion_reconciliation(
                        self._report(**{key: False}),
                        {"actual_scored_s": 1_800.0},
                    )

    def test_rejects_arithmetic_invariant_failure(self):
        with self.assertRaisesRegex(RuntimeError, "arithmetic invariant"):
            validate_promotion_reconciliation(
                self._report(arithmetic_invariant={"holds": False}),
                {"actual_scored_s": 1_800.0},
            )

    def test_rejects_report_quality_actual_scored_mismatch(self):
        with self.assertRaisesRegex(RuntimeError, "actual_scored_s mismatch"):
            validate_promotion_reconciliation(
                self._report(), {"actual_scored_s": 1_770.0}
            )

    def test_rejects_missing_or_non_finite_actual_scored(self):
        for value in (None, True, float("nan"), -1.0):
            with self.subTest(value=value):
                with self.assertRaisesRegex(
                    RuntimeError, "quality actual_scored_s"
                ):
                    validate_promotion_reconciliation(
                        self._report(), {"actual_scored_s": value}
                    )


if __name__ == "__main__":
    unittest.main()
