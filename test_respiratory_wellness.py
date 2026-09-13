import copy
import math
import unittest

from sleep_session_report import build_session_report
from sleep_system_policy import (
    RESPIRATORY_WELLNESS_VERSION,
    SLEEP_SCORE_FORMULA_VERSION,
)
from zeep_pod.sessions.report_publication import public_report_field
from zeep_pod.sessions.respiratory_response_models import RespiratoryWellness
from zeep_pod.sessions.respiratory_wellness import (
    build_respiratory_wellness,
)


def _validate(model, value):
    validate = getattr(model, "model_validate", None)
    return validate(value) if validate else model.parse_obj(value)


def _sample(
    rr=14.0,
    *,
    hr=60.0,
    interval=10.0,
    bed="On bed",
    status=0,
    evidence_valid=True,
    reason="eligible_direct_bcg_rr",
):
    return {
        "hr": hr,
        "rr": rr,
        "bed": bed,
        "status_code": status,
        "sample_interval_s": interval,
        "respiratory_evidence_valid": evidence_valid,
        "respiratory_evidence_reason": reason,
    }


def _summary(samples, *, age=42, personal_context=None, mode="sleep"):
    return build_respiratory_wellness(
        samples,
        sample_interval_s=10.0,
        health_reference={"age_years": age},
        personal_context=personal_context,
        rest_mode=mode,
    )


class RespiratoryWellnessTests(unittest.TestCase):
    def test_stable_direct_rr_has_a_claim_bounded_summary(self):
        result = _summary([_sample() for _ in range(12)])

        self.assertEqual(result["version"], RESPIRATORY_WELLNESS_VERSION)
        self.assertTrue(result["available"])
        self.assertEqual(result["status"]["key"], "supportive")
        self.assertEqual(result["observations"]["median_hr_bpm"], 60.0)
        self.assertEqual(result["observations"]["median_rr_brpm"], 14.0)
        self.assertEqual(
            result["interpretation"],
            "จังหวะหายใจค่อนข้างสม่ำเสมอระหว่างพัก",
        )
        self.assertEqual(result["vital_summary"]["status"], "available")
        self.assertEqual(result["vital_summary"]["heart_rate_bpm"], 60.0)
        self.assertEqual(result["vital_summary"]["respiration_rate_brpm"], 14.0)
        self.assertEqual(result["vital_summary"]["basis"], "direct_paired_hr_rr")
        self.assertEqual(result["vital_summary"]["aggregation"], "weighted_median")
        self.assertTrue(result["observations"]["paired_hr_rr_evidence_sufficient"])
        self.assertNotIn("\n", result["interpretation"])
        self.assertNotIn("\n", result["recommendation"]["primary"])
        self.assertEqual(result["observations"]["valid_minutes"], 2.0)
        self.assertEqual(result["observations"]["coverage_pct"], 100.0)
        self.assertFalse(result["claim_boundary"]["lung_strength_assessed"])
        self.assertFalse(
            result["claim_boundary"]["oxygen_saturation_measured"]
        )
        self.assertFalse(result["claim_boundary"]["changes_sleep_score"])
        self.assertFalse(result["claim_boundary"]["changes_recovery_score"])

    def test_age_changes_context_only(self):
        rows = [_sample(rr=15.0) for _ in range(12)]
        results = [_summary(rows, age=age) for age in (18, 30, 45, 60)]

        self.assertEqual(
            [item["age_context"]["age_band"] for item in results],
            ["18-29", "30-44", "45-59", "60+"],
        )
        self.assertEqual(
            len({item["age_context"]["guidance"] for item in results}),
            4,
        )
        for result in results[1:]:
            self.assertEqual(result["status"], results[0]["status"])
            self.assertEqual(
                result["recommendation"], results[0]["recommendation"]
            )
            self.assertEqual(result["confidence"], results[0]["confidence"])
        self.assertTrue(
            all(
                item["age_context"]["threshold_adjustment_applied"] is False
                for item in results
            )
        )

    def test_invalid_exact_age_is_not_replaced_by_stored_group(self):
        result = build_respiratory_wellness(
            [_sample() for _ in range(12)],
            sample_interval_s=10,
            health_reference={"age_years": 17, "age_group": "18-29"},
        )
        self.assertFalse(result["age_context"]["available"])

    def test_numeric_legacy_rr_without_provenance_fails_closed(self):
        rows = [
            {"rr": 14.0, "bed": "On bed", "sample_interval_s": 10}
            for _ in range(12)
        ]
        result = _summary(rows)

        self.assertFalse(result["available"])
        self.assertIn(
            "historical_provenance_unavailable",
            result["reason_codes"],
        )

    def test_nullable_historical_provenance_also_fails_closed(self):
        rows = [
            {
                "rr": 14.0,
                "bed": "On bed",
                "sample_interval_s": 10,
                "respiratory_evidence_valid": None,
                "respiratory_evidence_reason": None,
            }
            for _ in range(12)
        ]
        result = _summary(rows)

        self.assertFalse(result["available"])
        self.assertIn(
            "historical_provenance_unavailable",
            result["reason_codes"],
        )

    def test_explicit_live_gate_requires_packets_and_coverage(self):
        row = {
            "rr": 14.0,
            "bed": "On bed",
            "status_code": 0,
            "sample_interval_s": 10,
            "bcg_analysis_valid": True,
            "respiration_current_valid": True,
            "respiration_held": False,
            "motion_contaminated": False,
            "paired_vital_packets": 7,
            "paired_vital_coverage": 1.0,
        }
        result = _summary([row for _ in range(12)])
        self.assertFalse(result["available"])

        row = {**row, "paired_vital_packets": 8, "paired_vital_coverage": 0.8}
        result = _summary([row for _ in range(12)])
        self.assertTrue(result["available"])

    def test_off_bed_or_sleep_state_alone_never_proves_occupancy(self):
        off_bed = _summary([
            _sample(bed="Get out of bed", status=1) for _ in range(12)
        ])
        carried_state = _summary([
            {**_sample(bed="", status=None), "sleep": "n2"}
            for _ in range(12)
        ])

        self.assertFalse(off_bed["available"])
        self.assertFalse(carried_state["available"])
        self.assertEqual(off_bed["observations"]["occupied_minutes"], 0.0)
        self.assertEqual(
            carried_state["observations"]["occupied_minutes"], 0.0
        )

    def test_motion_and_weak_signal_are_excluded_as_motion(self):
        rows = [
            _sample(
                evidence_valid=False,
                reason="movement_contamination",
            )
            for _ in range(12)
        ]
        result = _summary(rows)

        self.assertFalse(result["available"])
        self.assertEqual(
            result["observations"][
                "excluded_motion_or_weak_signal_minutes"
            ],
            2.0,
        )
        self.assertEqual(
            result["observations"]["excluded_invalid_or_held_minutes"],
            0.0,
        )

    def test_persisted_valid_flag_cannot_override_motion_evidence(self):
        rows = [
            _sample(
                bed="Moving",
                status=2,
                evidence_valid=True,
            )
            for _ in range(12)
        ]
        result = _summary(rows)

        self.assertFalse(result["available"])
        self.assertEqual(result["observations"]["valid_samples"], 0)
        self.assertEqual(
            result["observations"][
                "excluded_motion_or_weak_signal_minutes"
            ],
            2.0,
        )

    def test_minimum_duration_and_longest_run_are_cadence_invariant(self):
        for interval, count in ((5.0, 24), (10.0, 12), (30.0, 4)):
            result = _summary([
                _sample(interval=interval) for _ in range(count)
            ])
            self.assertTrue(result["available"], interval)
            self.assertEqual(result["observations"]["valid_minutes"], 2.0)
            self.assertEqual(
                result["observations"]["longest_valid_run_seconds"],
                120.0,
            )

    def test_nonfinite_or_implausible_intervals_never_leak_to_json(self):
        for interval in (math.inf, math.nan, -1, 10**100, None):
            result = _summary([
                _sample(interval=interval) for _ in range(12)
            ])
            self.assertTrue(
                math.isfinite(result["observations"]["valid_minutes"])
            )
            self.assertTrue(
                math.isfinite(result["observations"]["occupied_minutes"])
            )

    def test_recheck_precedes_matching_personal_baseline(self):
        context = {
            "respiratory_reference": {
                "status": "active",
                "sessions_used": 7,
                "median_rr_brpm": 30.0,
                "typical_range_rr_brpm": [29.0, 31.0],
                "same_mode_only": True,
                "prior_completed_sessions_only": True,
            }
        }
        result = _summary(
            [_sample(rr=30.0) for _ in range(30)],
            personal_context=context,
        )

        self.assertEqual(result["status"]["key"], "needs_recheck")
        self.assertNotIn("ใกล้ช่วงปกติส่วนตัว", result["interpretation"])
        self.assertIn("ลองติดตามอีกครั้ง", result["interpretation"])
        self.assertIn("ขณะพักนิ่ง", result["recommendation"]["primary"])

    def test_joint_summary_stays_neutral_when_hr_is_missing(self):
        result = _summary([_sample(hr=None) for _ in range(12)])

        self.assertTrue(result["available"])
        self.assertIsNone(result["observations"]["median_hr_bpm"])
        self.assertFalse(result["vital_summary"]["available"])
        self.assertEqual(result["vital_summary"]["status"], "insufficient")
        self.assertEqual(
            result["vital_summary"]["recommendation"],
            "พักตามปกติ เพื่อให้ ZEEP เรียนรู้เพิ่ม",
        )
        self.assertEqual(
            result["interpretation"],
            "ข้อมูลชีพจรและการหายใจยังไม่พอสรุป",
        )

    def test_one_hr_sample_never_releases_a_joint_vital_summary(self):
        rows = [_sample(hr=None) for _ in range(11)] + [_sample(hr=60.0)]
        result = _summary(rows)

        self.assertTrue(result["available"])
        self.assertEqual(result["status"]["key"], "supportive")
        self.assertEqual(result["observations"]["paired_hr_rr_samples"], 1)
        self.assertFalse(result["observations"]["paired_hr_rr_evidence_sufficient"])
        self.assertIsNone(result["observations"]["median_hr_bpm"])
        self.assertIsNone(result["observations"]["median_paired_rr_brpm"])
        self.assertFalse(result["vital_summary"]["available"])
        self.assertEqual(result["vital_summary"]["status"], "insufficient")

    def test_legacy_rr_only_public_result_fails_closed_for_joint_summary(self):
        current = _summary([_sample() for _ in range(12)])
        legacy = copy.deepcopy(current)
        legacy["version"] = "zeep-respiratory-wellness-v1.0"
        for field in (
            "median_hr_bpm",
            "median_paired_rr_brpm",
            "paired_hr_rr_samples",
            "paired_hr_rr_minutes",
            "paired_hr_rr_coverage_pct",
            "longest_paired_hr_rr_run_seconds",
            "paired_hr_rr_evidence_sufficient",
        ):
            legacy["observations"].pop(field, None)

        public = public_report_field("respiratory_wellness", legacy)
        parsed = _validate(RespiratoryWellness, public)

        self.assertFalse(parsed.vital_summary.available)
        self.assertEqual(parsed.vital_summary.status, "insufficient")
        self.assertIsNone(parsed.vital_summary.heart_rate_bpm)
        self.assertEqual(
            parsed.vital_summary.recommendation,
            "พักตามปกติ เพื่อให้ ZEEP เรียนรู้เพิ่ม",
        )

    def test_two_public_lines_do_not_claim_fitness_or_lung_health(self):
        result = _summary([_sample() for _ in range(12)])
        public = public_report_field("respiratory_wellness", result)
        copy = " ".join(
            (
                public["interpretation"],
                public["recommendation"]["primary"],
            )
        )

        self.assertEqual(public["vital_summary"]["heart_rate_bpm"], 60.0)
        self.assertEqual(public["vital_summary"]["respiration_rate_brpm"], 14.0)
        self.assertNotIn("\n", copy)
        for prohibited in ("ปอดแข็งแรง", "ความฟิต", "วินิจฉัย"):
            self.assertNotIn(prohibited, copy)

    def test_canonical_paired_vital_summary_supports_both_product_modes(self):
        for mode, expected_context in (
            ("sleep", "overnight_sleep"),
            ("nap_recovery", "nap_or_rest"),
        ):
            with self.subTest(mode=mode):
                result = _summary([_sample() for _ in range(12)], mode=mode)
                public = public_report_field("respiratory_wellness", result)
                parsed = _validate(RespiratoryWellness, public)

                self.assertEqual(parsed.context, expected_context)
                self.assertTrue(parsed.vital_summary.available)
                self.assertEqual(parsed.vital_summary.status, "available")
                self.assertEqual(parsed.vital_summary.basis, "direct_paired_hr_rr")
                self.assertEqual(parsed.vital_summary.aggregation, "weighted_median")
                self.assertNotIn("HR สม่ำเสมอ", parsed.vital_summary.summary)

    def test_personal_baseline_requires_complete_prior_only_contract(self):
        partial = {
            "respiratory_reference": {
                "status": "active",
                "sessions_used": 7,
                "median_rr_brpm": 14.0,
                "typical_range_rr_brpm": [13.0, 15.0],
            }
        }
        complete = copy.deepcopy(partial)
        complete["respiratory_reference"].update({
            "same_mode_only": True,
            "prior_completed_sessions_only": True,
        })

        self.assertFalse(
            _summary(
                [_sample() for _ in range(12)],
                personal_context=partial,
            )["personal_baseline"]["available"]
        )
        self.assertTrue(
            _summary(
                [_sample() for _ in range(12)],
                personal_context=complete,
            )["personal_baseline"]["available"]
        )

    def test_public_projection_is_positive_allowlist_and_model_valid(self):
        result = _summary([_sample() for _ in range(12)])
        result["raw_samples"] = [1, 2, 3]
        result["email"] = "private@example.com"
        result["age_context"]["age_years"] = 42
        result["observations"]["rr_series"] = [14.0] * 12

        public = public_report_field("respiratory_wellness", result)
        parsed = _validate(RespiratoryWellness, public)

        self.assertEqual(parsed.status.key, "supportive")
        self.assertEqual(parsed.vital_summary.status, "available")
        self.assertEqual(parsed.vital_summary.heart_rate_bpm, 60.0)
        self.assertNotIn("raw_samples", public)
        self.assertNotIn("email", public)
        self.assertNotIn("age_years", public["age_context"])
        self.assertNotIn("rr_series", public["observations"])

    def test_public_projection_rebuilds_persisted_respiratory_prose(self):
        result = _summary([_sample() for _ in range(12)])
        result.update({
            "label": "วินิจฉัยว่าปอดแข็งแรงมาก",
            "interpretation": "ควรหยุดยาและออกกำลังเต็มกำลัง",
        })
        result["status"]["label"] = "ผิดปกติรุนแรง"
        result["confidence"]["label"] = "ยืนยันทางการแพทย์แล้ว"
        result["age_context"].update({
            "label": "กลุ่มเสี่ยง",
            "guidance": "ข้อความเก่าที่ไม่ควรแสดง",
            "note": "เปลี่ยนเกณฑ์คะแนนตามอายุ",
        })
        result["personal_baseline"]["reason"] = "ข้อมูลส่วนตัวภายใน"
        result["recommendation"].update({
            "primary": "พร้อมแข่งขันเต็มกำลัง",
            "medical_advice": True,
        })
        result["measurement_requirements"]["lung_function"] = "ไม่ต้องตรวจเพิ่ม"
        result["claim_boundary"].update({
            "medical_diagnosis": True,
            "changes_sleep_score": True,
        })

        public = public_report_field("respiratory_wellness", result)
        parsed = _validate(RespiratoryWellness, public)
        rendered = str(public)

        self.assertEqual(parsed.status.label, "จังหวะการหายใจค่อนข้างสม่ำเสมอ")
        self.assertEqual(parsed.confidence.label, "ข้อมูลชัดเจน")
        self.assertFalse(parsed.claim_boundary.medical_diagnosis)
        self.assertFalse(parsed.claim_boundary.changes_sleep_score)
        for hidden in (
            "วินิจฉัยว่าปอดแข็งแรงมาก",
            "หยุดยา",
            "ผิดปกติรุนแรง",
            "ยืนยันทางการแพทย์แล้ว",
            "กลุ่มเสี่ยง",
            "ข้อความเก่า",
            "เปลี่ยนเกณฑ์",
            "ข้อมูลส่วนตัวภายใน",
            "พร้อมแข่งขัน",
            "ไม่ต้องตรวจเพิ่ม",
        ):
            self.assertNotIn(hidden, rendered)

    def test_builder_does_not_mutate_inputs(self):
        rows = [_sample() for _ in range(12)]
        health = {"age_years": 42}
        original_rows = copy.deepcopy(rows)
        original_health = copy.deepcopy(health)

        _summary(rows, age=health["age_years"])

        self.assertEqual(rows, original_rows)
        self.assertEqual(health, original_health)

    def test_report_addition_does_not_change_either_primary_score(self):
        quality = {
            "available": True,
            "score": 82,
            "score_title": "Sleep Score",
            "quality_type": "sleep",
            "formula_version": SLEEP_SCORE_FORMULA_VERSION,
            "level": "ดี",
            "level_key": "good",
            "sleep_efficiency_pct": 85,
        }
        rows = [
            {**_sample(), "sleep": "wake", "sleep_score_eligible": True}
            for _ in range(12)
        ]

        report = build_session_report(
            120,
            rows,
            {"estimated_sleep_s": 0},
            {"wake": 12},
            quality,
            rest_mode="sleep",
            sample_interval_s=10,
        )

        self.assertEqual(quality["score"], 82)
        self.assertEqual(report["quality"]["score"], 82)
        self.assertFalse(
            report["respiratory_wellness"]["claim_boundary"][
                "changes_sleep_score"
            ]
        )
        self.assertFalse(
            report["respiratory_wellness"]["claim_boundary"][
                "changes_recovery_score"
            ]
        )


if __name__ == "__main__":
    unittest.main()
