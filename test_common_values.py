"""Regression tests for shared dependency-free value helpers."""

from __future__ import annotations

import math
import unittest

from common.mappings import as_mapping
from common.numbers import (
    as_finite_number,
    as_number,
    number_in_range,
)


class CommonNumberTests(unittest.TestCase):
    def test_mapping_helper_returns_a_detached_dictionary(self) -> None:
        source = {"score": 80}
        projected = as_mapping(source)
        projected["score"] = 90
        self.assertEqual(source["score"], 80)
        self.assertEqual(as_mapping(None), {})

    def test_as_number_accepts_only_json_number_types(self) -> None:
        self.assertEqual(as_number(3), 3.0)
        self.assertEqual(as_number(2.5), 2.5)
        self.assertIsNone(as_number(True))
        self.assertIsNone(as_number("3"))

    def test_finite_helper_rejects_nan_and_infinity(self) -> None:
        self.assertIsNone(as_finite_number(math.nan))
        self.assertIsNone(as_finite_number(math.inf))
        self.assertEqual(as_finite_number(-1.5), -1.5)

    def test_range_is_inclusive_and_finite_by_default(self) -> None:
        self.assertEqual(number_in_range(30, 30, 130), 30.0)
        self.assertEqual(number_in_range(130, 30, 130), 130.0)
        self.assertIsNone(number_in_range(29.9, 30, 130))
        self.assertIsNone(number_in_range(math.inf, 30, 130))


if __name__ == "__main__":
    unittest.main()
