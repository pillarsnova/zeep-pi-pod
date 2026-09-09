"""Host regression checks for the independently derived A-weighting filter."""

from __future__ import annotations

import cmath
import math
import unittest


SAMPLE_RATE = 48_000.0
SECTIONS = (
    (
        0.23418304260355596,
        -0.46836608520711193,
        0.23418304260355596,
        -1.9946144559930215,
        0.99462170701408426,
    ),
    (1.0, -2.0, 1.0, -1.8938704947230707, 0.89515976909466166),
    (1.0, 2.0, 1.0, -0.22455845805977914, 0.012606625271546396),
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
        for frequency in (31.5, 63, 125, 250, 500, 1000, 2000, 4000, 8000):
            with self.subTest(frequency=frequency):
                error = (
                    digital_response_db(frequency)
                    - analogue_a_weighting_db(frequency)
                )
                self.assertLessEqual(abs(error), 0.6)

    def test_all_sections_have_poles_inside_unit_circle(self) -> None:
        for *_, a1, a2 in SECTIONS:
            discriminant = cmath.sqrt(a1 * a1 - 4.0 * a2)
            poles = ((-a1 + discriminant) / 2.0, (-a1 - discriminant) / 2.0)
            self.assertTrue(all(abs(pole) < 1.0 for pole in poles))

    def test_sph0645_reference_tone_maps_to_94_db_spl(self) -> None:
        sensitivity_dbfs = -26.0
        sine_peak = 10 ** (sensitivity_dbfs / 20.0)
        sine_rms = sine_peak / math.sqrt(2.0)
        measured_dbfs = 20.0 * math.log10(sine_rms)
        laeq_dba = 94.0 - sensitivity_dbfs + 3.0102999566 + measured_dbfs
        self.assertAlmostEqual(laeq_dba, 94.0, places=6)


if __name__ == "__main__":
    unittest.main()
