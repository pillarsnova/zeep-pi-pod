"""Regression tests for the non-scoring ZEEP Restore Summary layer."""

import json
import tempfile
import unittest
from pathlib import Path

from personal import BaselineStore
from sleep_session_report import build_session_report, build_sleep_quality
from sleep_system_policy import (
    APPROVED_SLEEP_RESULT_VERSION_PAIRS,
    PRE_CONTINUITY_SESSION_REPORT_VERSION,
    PRE_CONTINUITY_SLEEP_QUALITY_VERSION,
    PRE_RESPIRATORY_SESSION_REPORT_VERSION,
    PRE_RESTORE_SESSION_REPORT_VERSION,
    RECOVERY_SCORE_FORMULA_VERSION,
    RESTORE_SUMMARY_VERSION,
    SESSION_REPORT_VERSION,
    SLEEP_QUALITY_VERSION,
    SLEEP_SCORE_FORMULA_VERSION,
)
from zeep_pod.sessions.history_quality import released_historical_quality
from zeep_pod.sessions.restore_summary import build_restore_summary


def _sleep_quality(score=82):
    return {
        "available": True,
        "score": score,
        "quality_type": "sleep",
        "rest_mode": {"group": "sleep", "requested": "sleep"},
        "component_points": {
            "sleep_opportunity": 17.0,
            "sleep_stability": 24.0,
            "restorative_architecture": 24.0,
            "cycle_expression": 12.0,
            "data_coverage": 5.0,
        },
        "component_max_points": {
            "sleep_opportunity": 20.0,
            "sleep_stability": 30.0,
            "restorative_architecture": 30.0,
            "cycle_expression": 15.0,
            "data_coverage": 5.0,
        },
        "score_confidence": {
            "level": "high",
            "label": "หลักฐานสูง",
            "session_coverage_pct": 98.0,
            "paired_hr_rr_coverage_pct": 96.0,
        },
        "formula_version": SLEEP_SCORE_FORMULA_VERSION,
    }


class _BehaviourDatabase:
    def __init__(self):
        self.summaries = {}
        self.sessions = []
        for index in range(1, 9):
            session_id = f"nap-{index}"
            self.sessions.insert(
                0,
                {
                    "session_id": session_id,
                    "duration": 30 * 60,
                    "start_time": f"2026-09-{index:02d}T06:00:00+00:00",
                },
            )
            self.summaries[session_id] = {
                "night_summary": {
                    "estimated_sleep_s": 0,
                    "sleep_quality": {
                        "available": True,
                        "score": 70 + index,
                        "quality_type": "rest_goal",
                        "version": SLEEP_QUALITY_VERSION,
                    },
                },
                "session_report": {
                    "version": SESSION_REPORT_VERSION,
                    "rest_mode": {
                        "group": "nap_recovery",
                        "requested": "nap_recovery",
                        "resolved": "nap_recovery",
                    },
                },
            }

    def read_sessions(self, sql, params=()):
        if "FROM sessions" in sql:
            return list(self.sessions)
        if "type='final_summary'" in sql:
            summary = self.summaries.get(params[0])
            return [{"value": json.dumps(summary)}] if summary else []
        if "FROM timeline" in sql:
            return [
                {
                    "timestamp": "2026-09-01T06:00:00+00:00",
                    "temperature": 24.0,
                    "humidity": 50.0,
                    "co2": 750.0,
                    "lux": 2.0,
                    "sound": 35.0,
                    "heart_rate": 64.0,
                    "respiration_rate": 14.0,
                    "bed_status": "On bed",
                }
            ]
        return []


class RestoreSummaryTests(unittest.TestCase):
    def test_finalization_freezes_prior_context_for_historical_display(self):
        source = Path("app.py").read_text(encoding="utf-8")

        self.assertIn("restore_context = baselines.behaviour_context(", source)
        self.assertIn('"restore_context": restore_context', source)
        self.assertIn("personal_context=restore_context", source)
        self.assertIn("trend_context=restore_context", source)

    def test_overnight_wraps_sleep_score_without_third_score(self):
        summary = build_restore_summary(_sleep_quality())

        self.assertEqual(summary["version"], RESTORE_SUMMARY_VERSION)
        self.assertFalse(summary["creates_independent_score"])
        self.assertNotIn("restore_score", summary)
        self.assertEqual(summary["source_score"]["type"], "sleep_score")
        self.assertEqual(summary["source_score"]["value"], 82)
        self.assertEqual(
            summary["source_score"]["formula_version"],
            SLEEP_SCORE_FORMULA_VERSION,
        )
        self.assertEqual(summary["status"]["label"], "ภาพรวมการนอนคืนนี้ดี")
        self.assertNotIn(
            "data_coverage",
            {item["key"] for item in summary["drivers"]["positive"]},
        )
        self.assertFalse(summary["session_scope"]["whole_day_readiness"])
        self.assertFalse(summary["claim_boundary"]["medical_diagnosis"])

    def test_nap_uses_recovery_score_and_does_not_require_sleep(self):
        quality = {
            "available": True,
            "score": 74,
            "quality_type": "rest_goal",
            "rest_mode": {
                "group": "nap_recovery",
                "requested": "nap_recovery",
            },
            "component_points": {
                "goal_duration": 20.0,
                "physiological_response": 27.0,
                "rest_continuity": 22.0,
                "environment_support": 5.0,
            },
            "component_max_points": {
                "goal_duration": 25.0,
                "physiological_response": 35.0,
                "rest_continuity": 30.0,
                "environment_support": 10.0,
            },
            "formula_version": RECOVERY_SCORE_FORMULA_VERSION,
            "sleep_detected": False,
        }

        summary = build_restore_summary(quality)

        self.assertEqual(summary["source_score"]["type"], "recovery_score")
        self.assertEqual(summary["source_score"]["value"], 74)
        self.assertEqual(summary["status"]["label"], "ช่วงพักนี้เป็นไปได้ดี")
        self.assertEqual(summary["session_scope"]["mode"], "nap_recovery")
        self.assertEqual(summary["subjective_outcome"]["status"], "not_measured")
        self.assertIsNone(summary["subjective_outcome"]["activity_readiness"])

    def test_unknown_legacy_mode_is_not_silently_treated_as_nap(self):
        summary = build_restore_summary(
            {
                "available": True,
                "score": 75,
                "rest_mode": {"group": None, "requested": "auto"},
            }
        )

        self.assertFalse(summary["available"])
        self.assertEqual(summary["source_score"]["type"], "unresolved_score")
        self.assertIsNone(summary["source_score"]["formula_version"])
        self.assertEqual(summary["session_scope"]["mode"], "unknown")

    def test_legacy_string_mode_is_normalised_without_crashing(self):
        quality = _sleep_quality()
        quality.pop("quality_type")
        quality["rest_mode"] = "overnight"

        summary = build_restore_summary(quality)

        self.assertTrue(summary["available"])
        self.assertEqual(summary["source_score"]["type"], "sleep_score")

    def test_missing_sensor_is_attention_never_a_positive_driver(self):
        summary = build_restore_summary(
            _sleep_quality(),
            findings=[
                {
                    "key": "sound",
                    "severity": "unavailable",
                    "decision": "advisory",
                    "title": "เสียง · ไม่มีข้อมูล",
                    "detail": "ยังไม่มีข้อมูล SPH0645",
                    "action": "ตรวจ SPH0645",
                }
            ],
        )

        positive_keys = {item["key"] for item in summary["drivers"]["positive"]}
        attention_keys = {item["key"] for item in summary["drivers"]["attention"]}
        self.assertNotIn("environment_sound", positive_keys)
        self.assertIn("environment_sound", attention_keys)
        driver = next(item for item in summary["drivers"]["attention"] if item["key"] == "environment_sound")
        self.assertFalse(driver["affects_source_score"])
        self.assertEqual(driver["label"], "เสียง · กำลังรวบรวมข้อมูล")
        self.assertEqual(driver["message"], "ZEEP กำลังรวบรวมข้อมูลส่วนนี้")
        self.assertNotIn("SPH0645", driver["message"])

    def test_safety_review_is_first_attention_driver(self):
        quality = _sleep_quality()
        quality["component_points"]["sleep_stability"] = 5.0
        summary = build_restore_summary(
            quality,
            findings=[
                {
                    "key": "sound",
                    "severity": "poor",
                    "decision": "required",
                    "title": "เสียง · ต้องแก้ไข",
                },
                {
                    "key": "co2_safety_excursion",
                    "metric_key": "co2",
                    "severity": "critical",
                    "decision": "safety_review",
                    "title": "CO₂ · พบ Safety excursion",
                    "threshold": 1300.0,
                    "minimum": 850.0,
                    "maximum": 1400.0,
                    "sample_count": 2,
                    "sample_pct": 10.0,
                },
            ],
        )

        attention = summary["drivers"]["attention"]
        self.assertEqual(attention[0]["key"], "environment_co2_safety_excursion")
        self.assertEqual(attention[0]["label"], "CO₂ · ควรให้ทีมตรวจสอบ")
        self.assertEqual(attention[0]["action"], "กรุณาแจ้งทีมงาน")
        self.assertEqual(attention[0]["decision"], "safety_review")
        self.assertEqual(attention[0]["threshold"], 1300.0)
        self.assertEqual(attention[0]["maximum"], 1400.0)
        self.assertEqual(attention[0]["sample_count"], 2)

    def test_explicit_not_measured_subjective_payload_stays_unmeasured(self):
        summary = build_restore_summary(
            _sleep_quality(),
            subjective_outcome={
                "status": "not_measured",
                "freshness_delta": 2,
            },
        )

        self.assertEqual(summary["subjective_outcome"]["status"], "not_measured")
        self.assertIsNone(summary["subjective_outcome"]["freshness_delta"])

    def test_baseline_compares_only_after_seven_same_mode_sessions(self):
        early = build_restore_summary(
            _sleep_quality(),
            personal_context={
                "sessions_used": 6,
                "score_median": 75,
                "score_typical_range": [72, 79],
            },
        )
        active = build_restore_summary(
            _sleep_quality(),
            personal_context={
                "sessions_used": 8,
                "score_median": 75,
                "score_typical_range": [72, 79],
            },
            trend_context={"scores": [70, 72, 75, 77, 82]},
        )

        self.assertEqual(early["personal_baseline"]["maturity"]["key"], "early")
        self.assertFalse(early["personal_baseline"]["comparison"]["available"])
        comparison = active["personal_baseline"]["comparison"]
        self.assertTrue(comparison["available"])
        self.assertEqual(comparison["key"], "above_typical")
        self.assertEqual(comparison["delta_points"], 7.0)
        self.assertTrue(active["trend"]["available"])
        self.assertFalse(active["trend"]["whole_day_readiness_trend"])

    def test_session_report_separates_recovery_environment_from_admin_qa(self):
        samples = [
            {
                "bed": "On bed",
                "hr": 64.0,
                "rr": 14.0,
                "temp": 24.0,
                "hum": 50.0,
                "co2": 750.0,
                "dba": 35.0,
                "lux": 2.0,
                "pm2_5": 8.0,
                "voc": 100.0,
            }
            for _ in range(20)
        ]
        quality = build_sleep_quality(
            10 * 60,
            {},
            {"wake": 20},
            rest_mode="nap_recovery",
            sensor_samples=samples,
            sample_interval_s=30,
            target_duration_s=30 * 60,
        )
        report = build_session_report(
            10 * 60,
            samples,
            {},
            {"wake": 20},
            quality,
            rest_mode="nap_recovery",
            sample_interval_s=30,
            target_duration_s=30 * 60,
        )

        self.assertEqual(
            report["restore_summary"]["source_score"]["value"],
            quality["score"],
        )
        environment = report["environment_assessment"]
        self.assertTrue(environment["context_only"])
        self.assertTrue(environment["sleep_stage_context_only"])
        self.assertFalse(environment["contributes_to_primary_score"])
        self.assertEqual(environment["max_score_points"], 0.0)
        recovery_environment = quality["environment_support"]
        self.assertTrue(recovery_environment["contributes_to_primary_score"])
        self.assertEqual(recovery_environment["max_points"], 10.0)
        self.assertTrue(all(finding["contributes_to_primary_score"] is False for finding in report["findings"]))

    def test_missing_nap_sensor_is_qa_not_a_score_penalty(self):
        samples = [
            {
                "bed": "On bed",
                "hr": 64.0,
                "rr": 14.0,
                "temp": 24.0,
                "hum": 50.0,
                "co2": 750.0,
                "dba": None,
                "lux": 2.0,
                "pm2_5": 8.0,
                "voc": 100.0,
            }
            for _ in range(20)
        ]
        quality = build_sleep_quality(
            10 * 60,
            {},
            {"wake": 20},
            rest_mode="nap_recovery",
            sensor_samples=samples,
            sample_interval_s=30,
            target_duration_s=30 * 60,
        )
        report = build_session_report(
            10 * 60,
            samples,
            {},
            {"wake": 20},
            quality,
            rest_mode="nap_recovery",
            sample_interval_s=30,
            target_duration_s=30 * 60,
        )

        sound = next(finding for finding in report["findings"] if finding["key"] == "sound")
        self.assertEqual(sound["severity"], "unavailable")
        self.assertFalse(sound["contributes_to_primary_score"])
        driver = next(item for item in report["restore_summary"]["drivers"]["attention"] if item["key"] == "environment_sound")
        self.assertFalse(driver["affects_source_score"])

    def test_report_version_bump_preserves_previous_approved_pair(self):
        self.assertEqual(
            SESSION_REPORT_VERSION,
            "zeep-session-report-v10.8-respiratory-wellness",
        )
        self.assertIn(
            (SESSION_REPORT_VERSION, SLEEP_QUALITY_VERSION),
            APPROVED_SLEEP_RESULT_VERSION_PAIRS,
        )
        self.assertIn(
            (PRE_RESPIRATORY_SESSION_REPORT_VERSION, SLEEP_QUALITY_VERSION),
            APPROVED_SLEEP_RESULT_VERSION_PAIRS,
        )
        self.assertIn(
            (
                PRE_CONTINUITY_SESSION_REPORT_VERSION,
                PRE_CONTINUITY_SLEEP_QUALITY_VERSION,
            ),
            APPROVED_SLEEP_RESULT_VERSION_PAIRS,
        )
        self.assertIn(
            (
                PRE_RESTORE_SESSION_REPORT_VERSION,
                PRE_CONTINUITY_SLEEP_QUALITY_VERSION,
            ),
            APPROVED_SLEEP_RESULT_VERSION_PAIRS,
        )

    def test_pre_restore_nap_score_remains_display_compatible(self):
        quality = {
            "available": True,
            "score": 74,
            "quality_type": "rest_goal",
            "version": PRE_CONTINUITY_SLEEP_QUALITY_VERSION,
        }
        final_summary = {
            "rest_mode": "nap_recovery",
            "session_report": {
                "version": PRE_RESTORE_SESSION_REPORT_VERSION,
                "rest_mode": {"group": "nap_recovery"},
            },
        }

        released = released_historical_quality(final_summary, quality)

        self.assertEqual(released["score"], 74)
        self.assertTrue(released["compatible_pre_restore_result"])

    def test_pre_continuity_nap_score_remains_display_compatible(self):
        quality = {
            "available": True,
            "score": 76,
            "quality_type": "rest_goal",
            "version": PRE_CONTINUITY_SLEEP_QUALITY_VERSION,
        }
        final_summary = {
            "rest_mode": "nap_recovery",
            "session_report": {
                "version": PRE_CONTINUITY_SESSION_REPORT_VERSION,
                "rest_mode": {"group": "nap_recovery"},
            },
        }

        released = released_historical_quality(final_summary, quality)

        self.assertEqual(released["score"], 76)
        self.assertTrue(released["compatible_pre_continuity_result"])

    def test_baseline_store_keeps_same_mode_score_reference_and_trend(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        store = BaselineStore(
            _BehaviourDatabase(),
            Path(temporary.name),
        )

        record = store.update_user("person@example.com")
        context = record["behaviour_by_mode"]["nap_recovery"]

        self.assertEqual(context["sessions_used"], 8)
        self.assertEqual(context["scores"], list(range(71, 79)))
        self.assertEqual(context["score_median"], 74.5)
        self.assertEqual(
            context["score_reference"]["method"],
            "median_and_interquartile_range",
        )
        self.assertEqual(
            context["score_formula_versions"],
            [RECOVERY_SCORE_FORMULA_VERSION],
        )


if __name__ == "__main__":
    unittest.main()
