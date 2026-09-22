"""Regression coverage for independent N3 HR/RR reference support."""

from __future__ import annotations

import unittest

from sessions.sleep_baseline_support import n3_baseline_support
from sessions.sleep_runtime_evidence import baseline_interval_proximity
from sleep_stage_scoring import score_sleep_evidence
from sleep_system_policy import (
    AGE_SLEEP_BASELINES,
    SLEEP_N3_MIN_AXIS_BASELINE_FIT,
    sleep_policy_snapshot,
)


class N3BaselineSupportTests(unittest.TestCase):
    def support(self, hr_fit=0.95, rr_fit=0.95, **measurements):
        return n3_baseline_support(
            {"n3": hr_fit}, {"n3": rr_fit},
            **{"mean_hr": 58, "mean_rr": 13, **measurements},
        )

    def test_each_axis_must_pass_without_weighted_compensation(self):
        for hr, rr, axis in ((1, 0.01, "rr"), (0.01, 1, "hr")):
            with self.subTest(axis=axis):
                result = self.support(hr, rr)
                self.assertFalse(result["passed"])
                self.assertIn(
                    f"{axis}_outside_n3_reference_support",
                    result["reason_codes"],
                )

    def test_floor_is_inclusive_and_not_a_stage_probability(self):
        floor = SLEEP_N3_MIN_AXIS_BASELINE_FIT
        self.assertTrue(self.support(floor, floor)["passed"])
        self.assertFalse(self.support(floor - 1e-7, 1)["passed"])
        self.assertEqual(
            self.support()["role"],
            "candidate_compatibility_not_stage_probability",
        )

    def test_invalid_or_missing_axis_cannot_pass(self):
        for invalid in (None, float("nan"), float("inf"), -1, True, "bad"):
            with self.subTest(value=invalid):
                self.assertFalse(self.support(rr_fit=invalid)["passed"])
                self.assertFalse(self.support(mean_rr=invalid)["passed"])
        self.assertFalse(self.support(rr_fit=1.1)["passed"])
        self.assertFalse(n3_baseline_support(
            {}, {"n3": 1}, mean_hr=58, mean_rr=13
        )["passed"])

    def test_policy_exposes_the_effective_threshold(self):
        policy = sleep_policy_snapshot()["n3_baseline_support"]
        self.assertEqual(policy["minimum_axis_fit"], 0.25)
        self.assertTrue(policy["both_hr_and_rr_required"])
        self.assertFalse(policy["rr_rate_drop_required"])
        self.assertFalse(policy["nap_n3_prohibited"])


class N3ScoringIntegrationTests(unittest.TestCase):
    def score(self, hr=58.0, rr=13.0, age_group="unspecified", **overrides):
        baseline = AGE_SLEEP_BASELINES[age_group]
        hr_fits = {
            stage: baseline_interval_proximity(hr, band["hr"])[0]
            for stage, band in baseline.items()
        }
        rr_fits = {
            stage: baseline_interval_proximity(rr, band["rr"])[0]
            for stage, band in baseline.items()
        }
        return score_sleep_evidence(
            base_scores={
                stage: (hr_fits[stage] + rr_fits[stage]) / 2
                for stage in baseline
            },
            hr_fits=hr_fits,
            rr_fits=rr_fits,
            metrics={
                "mean_hr": hr,
                "mean_rr": rr,
                "awake_hr_reference": 72.0,
                "awake_rr_reference": 17.0,
                "current_stage": "n2",
                "sleep_onset_established": True,
                "sleep_elapsed_min": 14,
                "waveform_available": True,
                "movement_ratio": 0.0,
                "hr_cv": 0.015,
                "rr_cv": 0.025,
                "resp_regularity": 0.75,
                "bcg_amplitude_shift_ratio": 0.05,
                **overrides,
            },
            elapsed_min=25,
            rem_variability_weight=1.0,
            n3_rr_conflict_penalty=1.2,
            n2_rr_conflict_support=0.3,
            move_wake_ratio=0.15,
            move_deep_ratio=0.05,
        )

    def test_synthetic_conflict_cannot_enter_n3_on_hr_and_stability_alone(self):
        for age_group in AGE_SLEEP_BASELINES:
            with self.subTest(age=age_group):
                scores, evidence = self.score(
                    hr=60.0, rr=21.0, age_group=age_group,
                    awake_hr_reference=65.0, awake_rr_reference=19.0,
                    hr_cv=0.01, rr_cv=0.01, resp_regularity=0.70,
                )
                self.assertFalse(evidence["n3_gate"])
                self.assertEqual(scores["n3"], 0)
                self.assertIn(
                    "rr_outside_n3_reference_support",
                    evidence["n3_baseline_support"]["reason_codes"],
                )

    def test_compatible_constant_rr_can_still_support_n3_during_nap(self):
        for mode in ("nap_recovery", "sleep"):
            with self.subTest(mode=mode):
                scores, evidence = self.score(
                    awake_rr_reference=13.0, rest_mode=mode
                )
                self.assertEqual(evidence["rr_drop_support"], 0)
                self.assertTrue(evidence["n3_gate"])
                self.assertGreater(scores["n3"], 0)

    def test_nearest_fit_alone_cannot_bypass_other_gates(self):
        for override in (
            {"waveform_available": False},
            {"current_stage": "wake"},
            {"current_stage": "n1"},
            {"movement_ratio": 0.3},
            {"resp_regularity": 0.4},
            {"bcg_baseline_drift_flag": True},
        ):
            with self.subTest(override=override):
                _, evidence = self.score(**override)
                self.assertTrue(evidence["n3_baseline_support"]["passed"])
                self.assertFalse(evidence["n3_gate"])


if __name__ == "__main__":
    unittest.main()
