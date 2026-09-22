"""Contracts of the extracted N3 policy, coercion and presentation modules."""

import unittest

from common.numbers import as_finite_number, coerce_finite_number
from presentation.sleep_candidate import sleep_candidate_reason
from sessions.sleep_n3_policy import SLEEP_N3_MIN_AXIS_BASELINE_FIT, n3_policy_snapshot
from sleep_system_policy import sleep_policy_snapshot


class N3ModuleContractsTests(unittest.TestCase):
    def test_legacy_coercion_is_explicit_and_strict_numbers_do_not_change(self):
        for value, expected in (("2.5", 2.5), (True, 1.0), (False, 0.0)):
            with self.subTest(value=value):
                self.assertEqual(coerce_finite_number(value), expected)
                self.assertIsNone(as_finite_number(value))

    def test_invalid_coercion_uses_the_requested_default(self):
        for value in (None, "bad", float("nan"), float("inf"), 10**1000):
            with self.subTest(value=value):
                self.assertEqual(coerce_finite_number(value, 0.025), 0.025)

    def test_manifest_matches_policy_and_returns_detached_metadata(self):
        expected = n3_policy_snapshot()
        self.assertEqual(expected["minimum_axis_fit"], SLEEP_N3_MIN_AXIS_BASELINE_FIT)
        self.assertEqual(sleep_policy_snapshot()["n3_baseline_support"], expected)
        expected["minimum_axis_fit"] = 1
        self.assertEqual(n3_policy_snapshot()["minimum_axis_fit"], 0.25)

    def test_candidate_reason_exists_for_every_supported_state(self):
        for state in ("wake", "n1", "n2", "n3", "rem"):
            with self.subTest(state=state):
                self.assertTrue(sleep_candidate_reason(state))
        self.assertEqual(
            sleep_candidate_reason("n3"),
            "ชีพจรและการหายใจสอดคล้องกับช่วงอ้างอิง N3 "
            "พร้อมหลักฐานความนิ่งและการหายใจสม่ำเสมอ",
        )

    def test_unknown_or_missing_candidate_makes_no_stage_claim(self):
        for value in (None, "", "unknown", "off_bed"):
            with self.subTest(value=value):
                self.assertIsNone(sleep_candidate_reason(value))


if __name__ == "__main__":
    unittest.main()
