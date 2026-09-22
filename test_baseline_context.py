"""Demographic grouping must not invent physiology or revise past facts."""

from __future__ import annotations

import unittest
from copy import deepcopy

from identity.baseline_context import build_baseline_context, project_health_reference
from identity.profile_fields import health_reference_from_profile
from sessions.result_privacy import public_result_value
from sleep_system_policy import age_group, gender_adjusted_baseline


class BaselineContextTests(unittest.TestCase):
    def context(self, **overrides):
        return build_baseline_context({
            "gender": "female", "age_years": 36, "age_group": "30-44",
            "height_cm": 175, "weight_kg": 70, **overrides,
        })

    def test_profile_axes_and_bmi_formula(self):
        female, male = self.context(), self.context(gender="male")
        self.assertEqual(female["bmi"]["value"], 22.86)
        self.assertEqual(female["cohort_key"], "female|30-44|18_5_to_25")
        self.assertEqual(male["cohort_key"], "male|30-44|18_5_to_25")
        self.assertEqual(female["bmi"], male["bmi"])
        self.assertFalse(female["matched_cohort_reference_available"])
        self.assertFalse(female["bmi_direct_stage_influence"])
        self.assertFalse(female["bmi_score_adjustment"])

    def test_age_boundaries_and_exact_age_take_precedence(self):
        for age, expected in (
            (18, "18-29"), (29, "18-29"), (30, "30-44"),
            (44, "30-44"), (45, "45-59"), (59, "45-59"), (60, "60+"),
        ):
            with self.subTest(age=age):
                self.assertEqual(self.context(age_years=age)["age_group"], expected)
        grouped = self.context(age_years=None, age_group="45-59")
        self.assertIsNone(grouped["age_years"])
        self.assertEqual(grouped["age_group"], "45-59")

    def test_bmi_boundaries_use_unrounded_measurement(self):
        for bmi, expected in (
            (18.49, "below_18_5"), (18.5, "18_5_to_25"),
            (24.999, "18_5_to_25"), (25, "25_to_30"),
            (29.999, "25_to_30"), (30, "30_and_above"),
        ):
            with self.subTest(bmi=bmi):
                result = self.context(height_cm=200, weight_kg=bmi * 4)
                self.assertEqual(result["bmi"]["band"], expected)

    def test_missing_or_invalid_values_are_not_average_imputations(self):
        for invalid in (None, 0, -1, True, float("nan"), float("inf"), "bad"):
            with self.subTest(value=invalid):
                result = self.context(weight_kg=invalid)
                self.assertIsNone(result["bmi"]["value"])
                self.assertIsNone(result["cohort_key"])
                self.assertIn("weight_kg", result["missing_fields"])
        self.assertIsNone(self.context(height_cm=0)["bmi"]["value"])
        self.assertIsNone(self.context(gender=None)["cohort_key"])

    def test_adult_bmi_band_is_not_applied_to_minors_or_unknown_age(self):
        for age, group in ((17, "18-29"), (None, None), (True, "30-44")):
            with self.subTest(age=age, group=group):
                result = self.context(age_years=age, age_group=group)
                self.assertIsNotNone(result["bmi"]["value"])
                self.assertIsNone(result["bmi"]["band"])
                self.assertIsNone(result["cohort_key"])
                self.assertFalse(result["adult_reference_applicable"])

    def test_profile_refresh_normalizes_units_then_builds_context(self):
        reference = health_reference_from_profile({
            "gender": "male", "age": 36, "age_is_estimated": False,
            "age_group": "30-44", "height_cm": 1.75, "weight_kg": 70,
        }, age_group_for=age_group)
        self.assertEqual(reference["baseline_context"]["bmi"]["value"], 22.86)

    def test_existing_snapshot_is_detached_not_replaced_with_current_profile(self):
        original = {
            "gender": "female", "age_years": 36,
            "height_cm": 175, "weight_kg": 70,
            "baseline_context": {"version": "old"},
        }
        before = deepcopy(original)
        projected = project_health_reference(original)
        self.assertEqual(original, before)
        self.assertEqual(projected["baseline_context"]["bmi"]["value"], 22.86)
        original["weight_kg"] = 90
        self.assertEqual(projected["weight_kg"], 70)
        self.assertIsNone(project_health_reference(None))

    def test_public_report_still_strips_the_entire_health_reference(self):
        result = public_result_value({
            "health_reference": {"baseline_context": self.context()},
            "score": 80,
        })
        self.assertEqual(result, {"score": 80})

    def test_bmi_grouping_does_not_modify_existing_stage_ranges(self):
        before = gender_adjusted_baseline("30-44", "female")
        for weight in (45, 70, 110):
            self.context(weight_kg=weight)
            self.assertEqual(before, gender_adjusted_baseline("30-44", "female"))


if __name__ == "__main__":
    unittest.main()
