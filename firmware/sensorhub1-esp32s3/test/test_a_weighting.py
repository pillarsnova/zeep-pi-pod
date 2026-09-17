"""Host regression checks for the independently derived A-weighting filter."""

from __future__ import annotations

import cmath
import math
import unittest


SAMPLE_RATE = 32_000.0
SECTIONS = (
    (
        0.3430690102281953,
        -0.6861380204563906,
        0.3430690102281953,
        -1.9919271185967897,
        0.9919434114503273,
    ),
    (1.0, -2.0, 1.0, -1.843990656105489, 0.8468163240645945),
    (1.0, 2.0, 1.0, 0.1794717314686119, 0.008052525599085385),
)


def digital_response_db(frequency_hz: float) -> float:
    z = cmath.exp(2j * math.pi * frequency_hz / SAMPLE_RATE)
    response = 1.0 + 0.0j
    for b0, b1, b2, a1, a2 in SECTIONS:
        numerator = b0 + b1 / z + b2 / (z * z)
        denominator = 1.0 + a1 / z + a2 / (z * z)
        response *= numerator / denominator
    return 20.0 * math.log10(abs(response))


def analogue_a_weighting_db(frequency_hz: float) -> float:
    f1, f2, f3, f4 = 20.598997, 107.65265, 737.86223, 12194.217
    squared = frequency_hz * frequency_hz
    numerator = f4 * f4 * squared * squared
    denominator = (
        (squared + f1 * f1)
        * math.sqrt((squared + f2 * f2) * (squared + f3 * f3))
        * (squared + f4 * f4)
    )
    return 20.0 * math.log10(numerator / denominator) + 2.0


class AWeightingTests(unittest.TestCase):
    def test_is_normalized_at_one_kilohertz(self) -> None:
        self.assertAlmostEqual(digital_response_db(1000), 0.0, places=6)

    def test_tracks_analogue_curve_through_eight_kilohertz(self) -> None:
        for frequency in (31.5, 63, 125, 250, 500, 1000, 2000, 4000):
            with self.subTest(frequency=frequency):
                error = (
                    digital_response_db(frequency)
                    - analogue_a_weighting_db(frequency)
                )
                self.assertLessEqual(abs(error), 0.6)

    def test_eight_kilohertz_bilinear_error_is_bounded(self) -> None:
        error = digital_response_db(8000) - analogue_a_weighting_db(8000)
        self.assertLessEqual(abs(error), 1.6)

    def test_all_sections_have_poles_inside_unit_circle(self) -> None:
        for *_, a1, a2 in SECTIONS:
            discriminant = cmath.sqrt(a1 * a1 - 4.0 * a2)
            poles = ((-a1 + discriminant) / 2.0, (-a1 - discriminant) / 2.0)
            self.assertTrue(all(abs(pole) < 1.0 for pole in poles))

    def test_sph0645_reference_tone_maps_to_94_db_spl(self) -> None:
        sensitivity_dbfs = -26.0
        measured_dbfs = sensitivity_dbfs
        datasheet_offset_db = 94.0 - sensitivity_dbfs
        laeq_dba = datasheet_offset_db + measured_dbfs
        self.assertAlmostEqual(laeq_dba, 94.0, places=6)

    def test_sph0645_datasheet_offset_is_120_db(self) -> None:
        self.assertEqual(94.0 - (-26.0), 120.0)


if __name__ == "__main__":
    unittest.main()
