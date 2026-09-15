"""Adversarial regressions for the two ZEEP Wellness score formulas."""

from __future__ import annotations

import math
import unittest

from sleep_session_report import build_sleep_quality
from sleep_system_policy import (
    RECOVERY_SCORE_FORMULA_VERSION,
    SLEEP_SCORE_FORMULA_VERSION,
)
from zeep_pod.sessions.quality_publication import public_quality_payload
from zeep_pod.sessions.restore_summary import build_restore_summary
from zeep_pod.sessions.score_identity import assess_score_identity
from zeep_pod.sessions.usage_response_models import PublicQuality


def _row(**overrides):
    row = {
        "hr": 60.0,
        "rr": 14.0,
        "bed": "On bed",
        "sleep": "wake",
        "temp": 24.0,
        "hum": 50.0,
        "co2": 750.0,
        "dba": 35.0,
        "lux": 2.0,
        "pm2_5": 8.0,
        "voc": 100.0,
    }
    row.update(overrides)
    return row


def _nap(rows, *, duration_s=1800, counts=None, target_s=1800):
    return build_sleep_quality(
        duration_s,
        {},
        counts or {"wake": duration_s // 5},
        rest_mode="nap_recovery",
        sensor_samples=rows,
        sample_interval_s=5,
        target_duration_s=target_s,
    )


class WellnessScoreBalanceTests(unittest.TestCase):
    def test_overnight_short_recording_never_releases_sleep_score(self):
        rows = [_row(sleep="n2") for _ in range(6)]

        quality = build_sleep_quality(
            30,
            {"sleep_onset_proxy_s": 0},
            {"n2": 6},
            rest_mode="overnight",
            sensor_samples=rows,
            sample_interval_s=5,
        )

        self.assertFalse(quality["available"])
        self.assertIsNone(quality["score"])
        self.assertEqual(quality["level_key"], "unavailable")
        self.assertEqual(quality["level"], "ข้อมูลยังไม่พอ")
        self.assertEqual(quality["insight"], quality["reason"])
        self.assertEqual(
            quality["rest_mode"]["protocol_status"]["status"],
            "too_short",
        )
        self.assertFalse(
            quality["release_requirements"]["timing_releasable"]
        )

    def test_missing_nap_target_is_unavailable_even_with_no_components(self):
        quality = _nap(
            [],
            duration_s=3600,
            counts={"wake": 120},
            target_s=None,
        )

        self.assertFalse(quality["available"])
        self.assertIsNone(quality["score"])
        self.assertEqual(quality["level_key"], "unavailable")
        self.assertEqual(quality["level"], "ข้อมูลยังไม่พอ")
        self.assertEqual(quality["insight"], quality["reason"])
        self.assertEqual(
            quality["rest_mode"]["protocol_status"]["status"],
            "target_unknown",
        )
        self.assertEqual(quality["scored_max_points"], 100.0)
        self.assertEqual(
            set(quality["imputed_component_points"]),
            {
                "goal_duration",
                "physiological_response",
                "rest_continuity",
                "environment_support",
            },
        )

    def test_six_raw_vital_rows_do_not_create_a_near_max_shadow_score(self):
        rows = [_row() for _ in range(6)]

        quality = _nap(rows, counts={"wake": 360})

        self.assertFalse(quality["available"])
        self.assertLess(quality["engineering_shadow_score"], 80)
        self.assertEqual(quality["score_confidence"]["level"], "low")
        self.assertAlmostEqual(
            quality["physiology"]["usable_evidence_coverage_ratio"],
            0.017,
            places=3,
        )

    def test_missing_optional_components_are_neutral_not_score_inflating(self):
        complete = _nap([_row() for _ in range(360)])
        missing = _nap([
            {"hr": 60.0, "rr": 14.0, "sleep": "wake"}
            for _ in range(360)
        ])

        self.assertTrue(missing["available"])
        self.assertLess(missing["score"], complete["score"])
        self.assertEqual(missing["score_confidence"]["level"], "low")
        self.assertEqual(
            missing["imputed_component_points"],
            {"rest_continuity": 22.5, "environment_support": 7.5},
        )
        self.assertFalse(
            missing["score_normalized_for_available_components"]
        )

    def test_recovery_continuity_counts_confirmed_off_bed_time(self):
        occupied = [_row() for _ in range(120)]
        off_bed = [
            _row(
                hr=None,
                rr=None,
                bed="Get out of bed",
                sleep=None,
                sleep_data_status="confirmed_off_bed",
                bed_exit_evidence={"confirmed": True},
            )
            for _ in range(240)
        ]

        quality = _nap(occupied + off_bed, counts={"wake": 120})

        self.assertTrue(quality["available"])
        self.assertLess(quality["score"], 70)
        self.assertEqual(
            quality["duration_target"]["eligible_rest_seconds"],
            600.0,
        )
        self.assertEqual(
            quality["body_response"]["confirmed_off_bed_seconds"],
            1200.0,
        )
        self.assertEqual(
            quality["component_points"]["rest_continuity"],
            9.2,
        )

    def test_sleep_efficiency_includes_confirmed_post_onset_off_bed(self):
        occupied = [_row(sleep="n2") for _ in range(3600)]
        off_bed = [
            _row(
                hr=None,
                rr=None,
                bed="Get out of bed",
                sleep=None,
                sleep_data_status="confirmed_off_bed",
                bed_exit_evidence={"confirmed": True},
            )
            for _ in range(1440)
        ]
        interrupted = build_sleep_quality(
            7 * 3600,
            {"sleep_onset_proxy_s": 600},
            {"n2": 3600},
            rest_mode="overnight",
            sensor_samples=occupied + off_bed,
            sample_interval_s=5,
        )
        uninterrupted = build_sleep_quality(
            7 * 3600,
            {"sleep_onset_proxy_s": 600},
            {"n2": 5040},
            rest_mode="overnight",
            sensor_samples=[_row(sleep="n2") for _ in range(5040)],
            sample_interval_s=5,
        )

        self.assertTrue(interrupted["available"])
        self.assertEqual(interrupted["sleep_efficiency_pct"], 71)
        self.assertEqual(
            interrupted["confirmed_post_onset_off_bed_s"],
            7200.0,
        )
        self.assertLess(interrupted["score"], uninterrupted["score"])

    def test_physiology_extremes_are_reviewed_or_withheld(self):
        normal = _nap([_row() for _ in range(360)])
        for heart_rate, respiration in ((35.0, 6.0), (160.0, 40.0)):
            with self.subTest(heart_rate=heart_rate, respiration=respiration):
                edge = _nap([
                    _row(hr=heart_rate, rr=respiration)
                    for _ in range(360)
                ])
                self.assertTrue(edge["available"])
                self.assertTrue(edge["review_required"])
                self.assertTrue(
                    edge["physiology"]["edge_context_review_required"]
                )
                self.assertEqual(
                    edge["physiology"]["wellness_factor"],
                    0.6,
                )
                self.assertLess(edge["score"], normal["score"])

        outside = _nap([_row(hr=200.0, rr=50.0) for _ in range(360)])
        self.assertFalse(outside["available"])
        self.assertIsNone(outside["score"])
        self.assertFalse(outside["physiology"]["available"])

    def test_half_implausible_vitals_reduce_lift_and_confidence(self):
        normal = _nap([_row() for _ in range(360)])
        mixed = _nap(
            [_row() for _ in range(180)]
            + [_row(hr=180.0, rr=50.0) for _ in range(180)]
        )

        self.assertTrue(mixed["available"])
        self.assertLess(mixed["score"], normal["score"])
        self.assertEqual(mixed["score_confidence"]["level"], "medium")
        self.assertEqual(
            mixed["physiology"]["usable_evidence_coverage_ratio"],
            0.5,
        )

    def test_nonfinite_vitals_are_invalid_instead_of_crashing(self):
        quality = _nap([
            _row(hr=math.nan, rr=math.inf) for _ in range(360)
        ])

        self.assertFalse(quality["available"])
        self.assertIsNone(quality["score"])
        self.assertEqual(
            quality["physiology"]["plausible_paired_samples"],
            0,
        )

    def test_sparse_environment_frames_lower_confidence_not_score(self):
        rows = [
            _row(sample_interval_s=300.0)
            for _ in range(6)
        ]

        quality = _nap(rows, counts={"wake": 6})

        self.assertTrue(quality["available"])
        self.assertEqual(
            quality["environment_support"]["temporal_coverage_pct"],
            10.0,
        )
        self.assertEqual(quality["score_confidence"]["level"], "low")

    def test_safety_excursion_overrides_positive_headline(self):
        rows = [_row() for _ in range(239)]
        rows.append(_row(co2=1300.0))

        quality = _nap(rows, duration_s=1200, counts={"wake": 240})
        summary = build_restore_summary(quality)

        self.assertTrue(quality["available"])
        self.assertEqual(quality["level_key"], "safety_review")
        self.assertTrue(quality["safety_review_required"])
        self.assertTrue(
            quality["environment_support"]["safety_score_cap_applied"]
        )
        self.assertEqual(summary["status"]["key"], "safety_review")

    def test_high_recovery_score_does_not_claim_partial_timing_met_target(self):
        quality = _nap(
            [_row() for _ in range(120)],
            duration_s=600,
            counts={"wake": 120},
            target_s=1800,
        )
        summary = build_restore_summary(quality)

        self.assertGreaterEqual(quality["score"], 85)
        self.assertEqual(
            quality["rest_mode"]["protocol_status"]["status"],
            "partial",
        )
        self.assertIn("สั้นกว่าเป้าหมาย", quality["insight"])
        self.assertNotIn("เป้าหมาย", summary["status"]["label"])
        self.assertNotIn("เป้าหมาย", summary["status"]["meaning"])

    def test_out_of_protocol_recovery_copy_keeps_timing_distinct_from_score(self):
        quality = _nap(
            [_row() for _ in range(1440)],
            duration_s=7200,
            counts={"wake": 1440},
            target_s=1800,
        )

        self.assertTrue(quality["available"])
        self.assertTrue(quality["review_required"])
        self.assertEqual(
            quality["rest_mode"]["protocol_status"]["status"],
            "out_of_protocol",
        )
        self.assertIn("ระยะเวลาต่าง", quality["insight"])
        self.assertNotIn("สอดคล้องกับเป้าหมาย", quality["insight"])

    def test_formula_identity_requires_an_explicit_approved_version(self):
        result = assess_score_identity(
            {
                "quality_type": "sleep",
                "score_title": "Sleep Score",
                "formula_version": SLEEP_SCORE_FORMULA_VERSION + "-shadow",
            },
            "sleep",
        )

        self.assertFalse(result["valid"])
        self.assertEqual(result["validation_status"], "score_formula_mismatch")

    def test_public_contract_exposes_formula_inputs_without_raw_values(self):
        quality = _nap([
            {"hr": 60.0, "rr": 14.0, "sleep": "wake"}
            for _ in range(360)
        ])

        public = public_quality_payload(quality)
        parsed = PublicQuality.model_validate(public)

        self.assertEqual(parsed.formula_version, RECOVERY_SCORE_FORMULA_VERSION)
        self.assertEqual(parsed.duration_target.score_factor, 1.0)
        self.assertEqual(parsed.duration_target.score_curve_exponent, 0.5)
        self.assertEqual(
            parsed.imputed_component_points.rest_continuity,
            22.5,
        )
        self.assertEqual(parsed.scored_max_points, 100.0)
        self.assertFalse(parsed.score_normalized_for_available_components)

    def test_public_sleep_architecture_includes_identified_pattern_points(self):
        quality = build_sleep_quality(
            5 * 3600,
            {"sleep_onset_proxy_s": 600},
            {"n2": 3600},
            rest_mode="overnight",
            sensor_samples=[_row(sleep="n2") for _ in range(3600)],
            sample_interval_s=5,
        )

        public = public_quality_payload(quality)
        parsed = PublicQuality.model_validate(public)

        self.assertEqual(parsed.formula_version, SLEEP_SCORE_FORMULA_VERSION)
        self.assertEqual(
            parsed.architecture.points.identified_sleep_pattern,
            10.0,
        )


if __name__ == "__main__":
    unittest.main()
