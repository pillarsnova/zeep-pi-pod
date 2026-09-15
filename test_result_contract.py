from __future__ import annotations

import unittest

from sleep_system_policy import (
    PERSONAL_BEHAVIOUR_BASELINE_VERSION,
    RECOVERY_SCORE_FORMULA_VERSION,
    RESTORE_SUMMARY_VERSION,
    SLEEP_SCORE_FORMULA_VERSION,
)
from zeep_pod.sessions.result_contract import build_result_contract


class SessionResultContractTests(unittest.TestCase):
    def test_overnight_coverage_points_are_disclosed(self) -> None:
        quality = {
            "available": True,
            "score": 81,
            "quality_type": "sleep",
            "score_title": "Sleep Score",
            "formula_version": SLEEP_SCORE_FORMULA_VERSION,
            "version": "sleep-quality-test",
            "data_coverage": {"pct": 80, "points": 4, "max_points": 5},
            "score_confidence": {"level": "low", "label": "หลักฐานจำกัด"},
            "rest_mode": {"group": "sleep", "label": "Overnight Recovery"},
        }
        result = build_result_contract(
            {
                "ended_at_utc": "2026-09-11T00:00:00+00:00",
                "rest_mode": "sleep",
                "sleep_quality": quality,
                "session_report": {
                    "data_quality": {
                        "level": "low",
                        "label": "ความครอบคลุมจำกัด",
                    }
                },
            }
        )

        self.assertEqual(result["score"]["type"], "sleep_score")
        self.assertTrue(result["data_quality"]["coverage_contributes_points"])
        self.assertEqual(result["data_quality"]["coverage_points"], 4)
        self.assertFalse(result["data_quality"]["coverage_can_hide_score"])
        self.assertEqual(
            result["data_quality"]["label"],
            "กำลังรวบรวมข้อมูลเพิ่ม",
        )
        self.assertEqual(
            result["data_quality"]["confidence"]["label"],
            "กำลังรวบรวมข้อมูลเพิ่ม",
        )
        self.assertEqual(
            result["score_revision_policy"],
            "versioned_recalculation_with_audit",
        )

    def test_nap_coverage_is_qa_context_not_score_component(self) -> None:
        quality = {
            "available": True,
            "score": 76,
            "quality_type": "rest_goal",
            "score_title": "Recovery Score",
            "formula_version": RECOVERY_SCORE_FORMULA_VERSION,
            "version": "sleep-quality-test",
            "data_coverage": {"pct": 60, "score_component": False},
            "rest_mode": {
                "group": "nap_recovery",
                "label": "Nap & Refresh",
            },
        }
        result = build_result_contract(
            {
                "ended_at_utc": "2026-09-11T00:00:00+00:00",
                "rest_mode": "nap_recovery",
                "sleep_quality": quality,
            }
        )

        self.assertEqual(result["score"]["type"], "recovery_score")
        self.assertFalse(result["data_quality"]["coverage_contributes_points"])

    def test_nap_protocol_review_is_preserved_in_canonical_result(self) -> None:
        quality = {
            "available": True,
            "score": 91,
            "quality_type": "rest_goal",
            "score_title": "Recovery Score",
            "formula_version": RECOVERY_SCORE_FORMULA_VERSION,
            "version": "sleep-quality-test",
            "review_required": True,
            "duration_target": {
                "key": "nap_90",
                "label": "Nap & Refresh · 90 นาที",
                "seconds": 5400,
            },
            "rest_mode": {
                "group": "nap_recovery",
                "label": "Nap & Refresh",
                "protocol_status": {
                    "available": True,
                    "canonical_mode": "nap_recovery",
                    "observed_seconds": 7260,
                    "status": "implausible_outlier",
                    "review_required": True,
                    "score_releasable": True,
                    "timing_review_threshold_seconds": 7200,
                    "legacy_hard_max_seconds": 7200,
                },
            },
        }

        result = build_result_contract(
            {
                "ended_at_utc": "2026-09-11T00:00:00+00:00",
                "rest_mode": "nap_recovery",
                "target_duration_s": 5400,
                "sleep_quality": quality,
            }
        )

        self.assertTrue(result["score"]["available"])
        self.assertTrue(result["score"]["review_required"])
        self.assertTrue(result["mode"]["review_required"])
        self.assertTrue(result["mode"]["protocol_review_required"])
        self.assertEqual(
            result["mode"]["target"]["protocol_status"][
                "timing_review_threshold_seconds"
            ],
            7200,
        )
        self.assertEqual(
            result["mode"]["validation_status"],
            "mode_confirmed",
        )

    def test_unknown_legacy_mode_is_not_inferred_as_nap(self) -> None:
        result = build_result_contract(
            {
                "ended_at_utc": "2026-09-11T00:00:00+00:00",
                "rest_mode": "auto",
                "sleep_quality": {"available": False, "score": None},
            }
        )

        self.assertEqual(result["mode"]["key"], "unknown")
        self.assertEqual(result["score"]["type"], "unresolved_score")
        self.assertFalse(result["score"]["available"])
        self.assertEqual(
            result["restore_summary"]["session_scope"]["mode"],
            "unknown",
        )

    def test_unavailable_copy_distinguishes_completed_from_open_session(self) -> None:
        base = {
            "rest_mode": "sleep",
            "sleep_quality": {
                "available": False,
                "score": None,
                "quality_type": "sleep",
            },
        }
        completed = build_result_contract(
            {
                **base,
                "ended_at_utc": "2026-09-11T00:00:00+00:00",
            }
        )
        active = build_result_contract(base)

        self.assertEqual(
            completed["score"]["reason"],
            "ครั้งนี้ยังไม่มีคะแนน เพราะข้อมูลสำคัญสำหรับสรุปผลยังไม่ครบ",
        )
        self.assertEqual(
            completed["restore_summary"]["status"]["label"],
            "ครั้งนี้ยังไม่มีคะแนน",
        )
        self.assertIn("กำลังรวบรวมข้อมูล", active["score"]["reason"])
        self.assertEqual(
            active["restore_summary"]["status"]["label"],
            "กำลังเตรียมผลสรุป",
        )

    def test_safety_review_stays_visible_without_hiding_released_score(self) -> None:
        for source in ("quality", "environment"):
            with self.subTest(source=source):
                quality = {
                    "available": True,
                    "score": 94,
                    "quality_type": "sleep",
                    "score_title": "Sleep Score",
                    "formula_version": SLEEP_SCORE_FORMULA_VERSION,
                    "duration_target": {
                        "key": "overnight_7h",
                        "seconds": 25_200,
                    },
                    "level_key": "very_good",
                    "level": "ดีมาก",
                }
                report = {"rest_mode": {"group": "sleep"}}
                if source == "quality":
                    quality["safety_review_required"] = True
                else:
                    report["environment_assessment"] = {
                        "safety_review_required": True,
                    }
                result = build_result_contract(
                    {
                        "ended_at_utc": "2026-09-11T00:00:00+00:00",
                        "rest_mode": "sleep",
                        "target_duration_s": 25_200,
                        "sleep_quality": quality,
                        "session_report": report,
                    }
                )

                self.assertTrue(result["score"]["available"])
                self.assertEqual(result["score"]["value"], 94)
                self.assertEqual(
                    result["score"]["level"],
                    "ควรให้ทีมตรวจสอบ",
                )
                self.assertTrue(result["score"]["review_required"])
                self.assertEqual(
                    result["restore_summary"]["status"]["key"],
                    "safety_review",
                )

    def test_persisted_restore_summary_is_preferred_without_rescoring(self) -> None:
        persisted = {
            "version": RESTORE_SUMMARY_VERSION,
            "creates_independent_score": False,
            "source_score": {
                "type": "sleep_score",
                "value": 90,
                "formula_version": SLEEP_SCORE_FORMULA_VERSION,
                "samples": ["must-not-leak"],
            },
            "status": {"key": "sleep_restore_very_good"},
            "session_scope": {"mode": "sleep"},
            "personal_baseline": {
                "comparison": {"available": False},
                "xApiKey": "must-not-leak",
                "privateKey": "must-not-leak",
            },
            "unexpected_raw_payload": {"samples": ["must-not-leak"]},
        }
        result = build_result_contract(
            {
                "ended_at_utc": "2026-09-11T00:00:00+00:00",
                "rest_mode": "sleep",
                "target_duration_s": 25_200,
                "sleep_quality": {
                    "available": True,
                    "score": 90,
                    "quality_type": "sleep",
                    "formula_version": SLEEP_SCORE_FORMULA_VERSION,
                    "duration_target": {
                        "key": "overnight_7h",
                        "seconds": 25_200,
                    },
                },
                "session_report": {"restore_summary": persisted},
            }
        )

        self.assertEqual(result["restore_summary"]["version"], RESTORE_SUMMARY_VERSION)
        self.assertEqual(result["restore_summary"]["source_score"]["value"], 90)
        self.assertFalse(result["provenance"]["score_recalculated_by_adapter"])
        self.assertNotIn("unexpected_raw_payload", result["restore_summary"])
        self.assertNotIn("samples", result["restore_summary"]["source_score"])
        baseline = result["restore_summary"]["personal_baseline"]
        self.assertFalse(baseline["comparison"]["available"])
        self.assertNotIn("xApiKey", baseline)

    def test_persisted_summary_cannot_override_released_invariants(self) -> None:
        persisted = {
            "version": "restore-test",
            "available": True,
            "creates_independent_score": True,
            "source_score": {
                "type": "recovery_score",
                "title": "Invented Restore Score",
                "value": 999,
                "available": True,
            },
            "status": {
                "key": "persisted-presentation",
                "label": "ข้อความที่บันทึกไว้",
            },
            "session_scope": {
                "mode": "nap_recovery",
                "whole_day_readiness": True,
                "clinical_readiness": True,
                "updates_during_day": True,
            },
            "claim_boundary": {
                "whole_day_readiness": True,
                "training_load_included": True,
            },
            "whole_day_readiness_available": True,
            "confidence": {
                "label": "ข้อมูลเดิมที่ปลอดภัย",
                "accessToken": "must-not-leak",
                "rawSamples": [1, 2, 3],
                "clientSecret": "must-not-leak",
                "apiKey": "must-not-leak",
            },
        }
        result = build_result_contract(
            {
                "ended_at_utc": "2026-09-11T00:00:00+00:00",
                "rest_mode": "sleep",
                "target_duration_s": 25_200,
                "sleep_quality": {
                    "available": True,
                    "score": 81,
                    "quality_type": "sleep",
                    "score_title": "Sleep Score",
                    "formula_version": SLEEP_SCORE_FORMULA_VERSION,
                    "duration_target": {
                        "key": "overnight_7h",
                        "seconds": 25_200,
                    },
                },
                "session_report": {
                    "rest_mode": {
                        "group": "sleep",
                        "label": "Overnight Recovery",
                    },
                    "restore_summary": persisted,
                },
            }
        )

        summary = result["restore_summary"]
        self.assertFalse(summary["creates_independent_score"])
        self.assertFalse(summary["whole_day_readiness_available"])
        self.assertEqual(summary["source_score"]["type"], "sleep_score")
        self.assertEqual(summary["source_score"]["title"], "Sleep Score")
        self.assertEqual(summary["source_score"]["value"], 81.0)
        self.assertTrue(summary["source_score"]["available"])
        self.assertEqual(
            summary["source_score"]["formula_version"],
            SLEEP_SCORE_FORMULA_VERSION,
        )
        self.assertEqual(summary["session_scope"]["mode"], "sleep")
        self.assertFalse(summary["session_scope"]["whole_day_readiness"])
        self.assertFalse(summary["session_scope"]["clinical_readiness"])
        self.assertFalse(summary["session_scope"]["updates_during_day"])
        self.assertFalse(summary["claim_boundary"]["whole_day_readiness"])
        self.assertFalse(summary["claim_boundary"]["training_load_included"])
        self.assertEqual(summary["status"]["label"], "ภาพรวมการนอนคืนนี้ดี")
        self.assertNotEqual(summary["status"]["label"], "ข้อความที่บันทึกไว้")
        self.assertNotEqual(summary["confidence"], {"label": "ข้อมูลเดิมที่ปลอดภัย"})
        self.assertFalse(summary["provenance"]["persisted_source_score_matched"])

    def test_report_mode_mismatch_blocks_score_in_both_directions(self) -> None:
        cases = (
            ("sleep", "sleep", "nap_recovery", "sleep", "sleep_score"),
            (
                "nap_recovery",
                "rest_goal",
                "sleep",
                "nap_recovery",
                "recovery_score",
            ),
        )
        for session_mode, quality_type, report_mode, expected, score_type in cases:
            with self.subTest(session_mode=session_mode):
                result = build_result_contract(
                    {
                        "ended_at_utc": "2026-09-11T00:00:00+00:00",
                        "rest_mode": session_mode,
                        "sleep_quality": {
                            "available": True,
                            "score": 91,
                            "quality_type": quality_type,
                            "rest_mode": {"group": session_mode},
                        },
                        "session_report": {
                            "rest_mode": {"group": report_mode},
                        },
                    }
                )

                self.assertEqual(result["mode"]["key"], expected)
                self.assertTrue(result["mode"]["review_required"])
                self.assertEqual(
                    result["mode"]["validation_status"],
                    "mode_metadata_conflict",
                )
                self.assertEqual(result["score"]["type"], score_type)
                self.assertFalse(result["score"]["available"])
                self.assertIsNone(result["score"]["value"])

    def test_released_quality_mode_conflict_is_unavailable(self) -> None:
        result = build_result_contract(
            {
                "ended_at_utc": "2026-09-11T00:00:00+00:00",
                "rest_mode": "sleep",
                "sleep_quality": {
                    "available": True,
                    "score": 91,
                    "quality_type": "rest_goal",
                },
                "session_report": {"rest_mode": {"group": "sleep"}},
            }
        )

        self.assertEqual(result["mode"]["key"], "sleep")
        self.assertFalse(result["score"]["available"])
        self.assertTrue(result["score"]["review_required"])

    def test_canonical_session_target_wins_over_stale_quality_target(self) -> None:
        result = build_result_contract(
            {
                "ended_at_utc": "2026-09-11T00:00:00+00:00",
                "rest_mode": "nap_recovery",
                "target_duration_s": 5400,
                "sleep_quality": {
                    "available": True,
                    "score": 80,
                    "quality_type": "rest_goal",
                    "rest_mode": {"group": "nap_recovery"},
                    "duration_target": {
                        "key": "nap_30",
                        "seconds": 1800,
                    },
                },
                "session_report": {
                    "rest_mode": {"group": "nap_recovery"},
                },
            }
        )

        self.assertEqual(result["mode"]["target"]["seconds"], 5400)
        self.assertEqual(result["mode"]["target"]["minutes"], 90)
        self.assertEqual(result["mode"]["target"]["key"], "nap_90")
        self.assertNotEqual(result["mode"]["target"]["key"], "nap_30")
        self.assertFalse(result["score"]["available"])
        self.assertEqual(
            result["score"]["validation_status"],
            "target_metadata_conflict",
        )

    def test_session_target_seconds_canonicalize_a_wrong_equal_seconds_key(
        self,
    ) -> None:
        result = build_result_contract(
            {
                "ended_at_utc": "2026-09-11T00:00:00+00:00",
                "rest_mode": "nap_recovery",
                "target_duration_s": 5400,
                "sleep_quality": {
                    "available": True,
                    "score": 80,
                    "quality_type": "rest_goal",
                    "rest_mode": {"group": "nap_recovery"},
                    "duration_target": {
                        "key": "nap_30",
                        "seconds": 5400,
                    },
                },
                "session_report": {
                    "rest_mode": {"group": "nap_recovery"},
                },
            }
        )

        self.assertEqual(result["mode"]["target"]["key"], "nap_90")
        self.assertEqual(result["mode"]["target"]["seconds"], 5400)
        self.assertEqual(result["mode"]["target"]["minutes"], 90)
        self.assertFalse(result["score"]["available"])

    def test_current_nap_without_score_target_fails_closed(self) -> None:
        result = build_result_contract(
            {
                "ended_at_utc": "2026-09-11T00:00:00+00:00",
                "rest_mode": "nap_recovery",
                "target_duration_s": 1_800,
                "sleep_quality": {
                    "available": True,
                    "score": 80,
                    "quality_type": "rest_goal",
                    "score_title": "Recovery Score",
                    "formula_version": RECOVERY_SCORE_FORMULA_VERSION,
                    "rest_mode": {"group": "nap_recovery"},
                },
            }
        )

        self.assertEqual(result["mode"]["target"]["key"], "nap_30")
        self.assertFalse(result["score"]["available"])
        self.assertTrue(result["score"]["review_required"])
        self.assertEqual(
            result["score"]["validation_status"],
            "target_metadata_conflict",
        )

    def test_legacy_nap_without_session_target_stays_readable_but_unscoped(
        self,
    ) -> None:
        result = build_result_contract(
            {
                "ended_at_utc": "2026-09-11T00:00:00+00:00",
                "rest_mode": "nap_recovery",
                "sleep_quality": {
                    "available": True,
                    "score": 80,
                    "quality_type": "rest_goal",
                    "score_title": "Recovery Score",
                    "formula_version": RECOVERY_SCORE_FORMULA_VERSION,
                    "duration_target": {
                        "key": "nap_30m",
                        "seconds": 1_800,
                    },
                },
            }
        )

        self.assertTrue(result["score"]["available"])
        self.assertTrue(result["score"]["review_required"])
        self.assertIsNone(result["mode"]["target"])

    def test_invalid_session_target_is_reviewed_and_never_published_as_valid(self):
        nap = build_result_contract(
            {
                "ended_at_utc": "2026-09-11T00:00:00+00:00",
                "rest_mode": "nap_recovery",
                "target_duration_s": 1234,
                "sleep_quality": {
                    "available": True,
                    "score": 80,
                    "quality_type": "rest_goal",
                    "rest_mode": {"group": "nap_recovery"},
                    "duration_target": {"key": "nap_30", "seconds": 1234},
                },
            }
        )
        sleep = build_result_contract(
            {
                "ended_at_utc": "2026-09-11T00:00:00+00:00",
                "rest_mode": "sleep",
                "target_duration_s": 3600,
                "sleep_quality": {
                    "available": True,
                    "score": 80,
                    "quality_type": "sleep",
                    "rest_mode": {"group": "sleep"},
                },
            }
        )

        self.assertTrue(nap["mode"]["protocol_review_required"])
        self.assertTrue(nap["mode"]["review_required"])
        self.assertIsNone(nap["mode"]["target"]["key"])
        self.assertIsNone(nap["mode"]["target"]["seconds"])
        self.assertTrue(sleep["mode"]["protocol_review_required"])
        self.assertEqual(sleep["mode"]["target"]["key"], "overnight_7h")
        self.assertEqual(sleep["mode"]["target"]["seconds"], 7 * 3600)
        self.assertFalse(sleep["score"]["available"])

    def test_current_sleep_target_mismatch_fails_closed(self) -> None:
        for quality_target in (None, {"seconds": 27_000, "key": "overnight"}):
            with self.subTest(quality_target=quality_target):
                quality = {
                    "available": True,
                    "score": 88,
                    "quality_type": "sleep",
                    "score_title": "Sleep Score",
                    "formula_version": SLEEP_SCORE_FORMULA_VERSION,
                    "rest_mode": {"group": "sleep"},
                }
                if quality_target is not None:
                    quality["duration_target"] = quality_target
                result = build_result_contract(
                    {
                        "ended_at_utc": "2026-09-11T00:00:00+00:00",
                        "rest_mode": "sleep",
                        "target_duration_s": 25_200,
                        "sleep_quality": quality,
                    }
                )

                self.assertEqual(
                    result["mode"]["target"]["seconds"],
                    25_200,
                )
                self.assertFalse(result["score"]["available"])
                self.assertEqual(
                    result["score"]["validation_status"],
                    "target_metadata_conflict",
                )
                self.assertIn(
                    "รูปแบบการพัก",
                    result["score"]["reason"],
                )

    def test_current_sleep_without_any_target_metadata_fails_closed(self) -> None:
        result = build_result_contract(
            {
                "ended_at_utc": "2026-09-11T00:00:00+00:00",
                "rest_mode": "sleep",
                "sleep_quality": {
                    "available": True,
                    "score": 88,
                    "quality_type": "sleep",
                    "score_title": "Sleep Score",
                    "formula_version": SLEEP_SCORE_FORMULA_VERSION,
                    "rest_mode": {"group": "sleep"},
                },
            }
        )

        self.assertFalse(result["score"]["available"])
        self.assertIsNone(result["score"]["value"])
        self.assertTrue(result["score"]["review_required"])
        self.assertEqual(
            result["score"]["validation_status"],
            "target_metadata_conflict",
        )

    def test_persisted_context_is_canonical_and_subjective_needs_provenance(
        self,
    ) -> None:
        persisted = {
            "version": RESTORE_SUMMARY_VERSION,
            "source_score": {
                "type": "sleep_score",
                "value": 80,
                "formula_version": SLEEP_SCORE_FORMULA_VERSION,
            },
            "session_scope": {"mode": "sleep"},
            "personal_baseline": {
                "mode": "sleep",
                "baseline_policy_version": PERSONAL_BEHAVIOUR_BASELINE_VERSION,
                "score_formula_version": SLEEP_SCORE_FORMULA_VERSION,
                "target_specific": True,
                "target_key": "overnight_7h",
                "maturity": {"sessions_used": 8},
                "comparison": {
                    "available": True,
                    "baseline_median": 75,
                    "typical_range": [70, 80],
                    "whole_day_readiness": True,
                },
                "training_load": 99,
            },
            "trend": {
                "available": True,
                "baseline_policy_version": PERSONAL_BEHAVIOUR_BASELINE_VERSION,
                "score_formula_version": SLEEP_SCORE_FORMULA_VERSION,
                "target_specific": True,
                "target_key": "overnight_7h",
                "windows": {
                    "7": {
                        "session_count": 7,
                        "average": 76,
                        "latest": 80,
                        "training_load": 99,
                    }
                },
                "whole_day_readiness_trend": True,
            },
            "subjective_outcome": {
                "status": "measured",
                "freshness_delta": 2,
                "activity_readiness": 9,
                "source": "sensor_inference",
                "sensor_inferred": True,
                "whole_day_readiness": True,
            },
        }
        result = build_result_contract(
            {
                "ended_at_utc": "2026-09-11T00:00:00+00:00",
                "rest_mode": "sleep",
                "target_duration_s": 25_200,
                "sleep_quality": {
                    "available": True,
                    "score": 80,
                    "quality_type": "sleep",
                    "formula_version": SLEEP_SCORE_FORMULA_VERSION,
                    "rest_mode": {"group": "sleep"},
                    "duration_target": {
                        "key": "overnight_7h",
                        "seconds": 25_200,
                    },
                },
                "session_report": {
                    "rest_mode": {"group": "sleep"},
                    "restore_summary": persisted,
                },
            }
        )

        summary = result["restore_summary"]
        self.assertTrue(summary["personal_baseline"]["comparison"]["available"])
        self.assertNotIn("training_load", str(summary["personal_baseline"]))
        self.assertFalse(summary["trend"]["whole_day_readiness_trend"])
        self.assertNotIn("training_load", str(summary["trend"]))
        self.assertEqual(summary["subjective_outcome"]["status"], "not_measured")
        self.assertIsNone(summary["subjective_outcome"]["freshness_delta"])

        persisted["subjective_outcome"] = {
            "status": "measured",
            "freshness_delta": 2,
            "activity_readiness": 9,
            "source": "session_questionnaire",
            "sensor_inferred": False,
        }
        measured = build_result_contract(
            {
                "ended_at_utc": "2026-09-11T00:00:00+00:00",
                "rest_mode": "sleep",
                "target_duration_s": 25_200,
                "sleep_quality": {
                    "available": True,
                    "score": 80,
                    "quality_type": "sleep",
                    "formula_version": SLEEP_SCORE_FORMULA_VERSION,
                    "rest_mode": {"group": "sleep"},
                    "duration_target": {
                        "key": "overnight_7h",
                        "seconds": 25_200,
                    },
                },
                "session_report": {
                    "rest_mode": {"group": "sleep"},
                    "restore_summary": persisted,
                },
            }
        )["restore_summary"]["subjective_outcome"]
        self.assertEqual(measured["status"], "measured")
        self.assertEqual(measured["freshness_delta"], 2.0)

    def test_persisted_available_cannot_release_unavailable_score(self) -> None:
        result = build_result_contract(
            {
                "ended_at_utc": "2026-09-11T00:00:00+00:00",
                "rest_mode": "nap_recovery",
                "sleep_quality": {
                    "available": False,
                    "score": 88,
                    "quality_type": "rest_goal",
                },
                "restore_summary": {
                    "available": True,
                    "creates_independent_score": True,
                    "source_score": {
                        "type": "sleep_score",
                        "value": 999,
                        "available": True,
                    },
                    "session_scope": {"mode": "sleep"},
                },
            }
        )

        summary = result["restore_summary"]
        self.assertFalse(summary["available"])
        self.assertFalse(summary["source_score"]["available"])
        self.assertIsNone(summary["source_score"]["value"])
        self.assertEqual(summary["source_score"]["type"], "recovery_score")
        self.assertEqual(summary["session_scope"]["mode"], "nap_recovery")

    def test_out_of_range_released_score_is_not_exposed(self) -> None:
        result = build_result_contract(
            {
                "ended_at_utc": "2026-09-11T00:00:00+00:00",
                "rest_mode": "sleep",
                "sleep_quality": {
                    "available": True,
                    "score": 999,
                    "quality_type": "sleep",
                },
                "restore_summary": {
                    "available": True,
                    "source_score": {"type": "sleep_score", "value": 999},
                },
            }
        )

        self.assertFalse(result["score"]["available"])
        self.assertIsNone(result["score"]["value"])
        self.assertFalse(result["restore_summary"]["available"])
        self.assertIsNone(result["restore_summary"]["source_score"]["value"])

    def test_released_session_quality_wins_over_unapproved_report_copy(self) -> None:
        result = build_result_contract(
            {
                "ended_at_utc": "2026-09-11T00:00:00+00:00",
                "rest_mode": "sleep",
                "sleep_quality": {
                    "available": False,
                    "score": None,
                    "quality_type": "sleep",
                    "reason": "version pair not approved",
                },
                "session_report": {
                    "rest_mode": {"group": "sleep"},
                    "quality": {
                        "available": True,
                        "score": 87,
                        "quality_type": "sleep",
                    },
                },
            }
        )

        self.assertFalse(result["score"]["available"])
        self.assertIsNone(result["score"]["value"])
        self.assertFalse(result["restore_summary"]["available"])

    def test_string_false_never_releases_score_or_clinical_claim(self) -> None:
        result = build_result_contract(
            {
                "ended_at_utc": "2026-09-11T00:00:00+00:00",
                "rest_mode": "sleep",
                "sleep_quality": {
                    "available": "false",
                    "score": 88,
                    "quality_type": "sleep",
                    "clinical_validated": "false",
                },
            }
        )

        self.assertFalse(result["score"]["available"])
        self.assertIsNone(result["score"]["value"])
        self.assertFalse(result["score"]["clinical_validated"])

    def test_score_identity_provenance_never_relabels_between_modes(self) -> None:
        cases = (
            (
                "nap_recovery",
                {
                    "score_title": "Sleep Score",
                    "formula_version": SLEEP_SCORE_FORMULA_VERSION,
                },
                "recovery_score",
                "Recovery Score",
            ),
            (
                "sleep",
                {
                    "quality_type": "sleep",
                    "score_title": "Recovery Score",
                    "formula_version": SLEEP_SCORE_FORMULA_VERSION,
                },
                "sleep_score",
                "Sleep Score",
            ),
            (
                "nap_recovery",
                {
                    "quality_type": "rest_goal",
                    "score_title": "Recovery Score",
                    "formula_version": SLEEP_SCORE_FORMULA_VERSION,
                },
                "recovery_score",
                "Recovery Score",
            ),
            (
                "sleep",
                {
                    "quality_type": "sleep",
                    "score_title": "Sleep Score",
                    "formula_version": RECOVERY_SCORE_FORMULA_VERSION,
                },
                "sleep_score",
                "Sleep Score",
            ),
            (
                "sleep",
                {
                    "quality_type": "sleep",
                    "score_title": "Sleep Score",
                },
                "sleep_score",
                "Sleep Score",
            ),
        )
        for mode, identity, expected_type, expected_title in cases:
            with self.subTest(mode=mode, identity=identity):
                result = build_result_contract(
                    {
                        "ended_at_utc": "2026-09-11T00:00:00+00:00",
                        "rest_mode": mode,
                        "sleep_quality": {
                            "available": True,
                            "score": 91,
                            **identity,
                        },
                    }
                )

                self.assertEqual(result["score"]["type"], expected_type)
                self.assertEqual(result["score"]["title"], expected_title)
                self.assertFalse(result["score"]["available"])
                self.assertIsNone(result["score"]["value"])
                self.assertTrue(result["score"]["review_required"])
                self.assertTrue(result["score"]["validation_status"])

    def test_approved_historical_formula_family_remains_releasable(self) -> None:
        cases = (
            (
                "sleep",
                "sleep",
                "Sleep Score",
                "zeep-sleep-score-v1.0-reviewed",
                "sleep_score",
            ),
            (
                "nap_recovery",
                "rest_goal",
                "Recovery Score",
                "zeep-recovery-score-v2.0-reviewed",
                "recovery_score",
            ),
        )
        for mode, quality_type, title, formula, expected_type in cases:
            with self.subTest(mode=mode):
                result = build_result_contract(
                    {
                        "ended_at_utc": "2026-09-11T00:00:00+00:00",
                        "rest_mode": mode,
                        "sleep_quality": {
                            "available": True,
                            "score": 79,
                            "quality_type": quality_type,
                            "score_title": title,
                            "formula_version": formula,
                        },
                    }
                )

                self.assertTrue(result["score"]["available"])
                self.assertEqual(result["score"]["type"], expected_type)
                self.assertEqual(result["score"]["value"], 79.0)


if __name__ == "__main__":
    unittest.main()
