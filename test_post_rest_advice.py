"""After-rest tips must be traceable without inventing measured recovery."""

import copy
import unittest

from sessions.post_rest_advice import build_post_rest_advice
from sessions.restore_summary import build_restore_summary
from test_restore_summary import _sleep_quality


class PostRestAdviceTests(unittest.TestCase):
    def advice(self, group="nap_recovery", **kwargs):
        return build_post_rest_advice(group, 80, {"attention": []}, **kwargs)

    def test_awake_rest_does_not_prescribe_deep_sleep(self):
        tip = self.advice(quality={"estimated_sleep_s": 0})
        self.assertEqual(tip["tip_id"], "quiet_awake_break")
        self.assertNotIn("หลับลึก", tip["primary"])
        self.assertFalse(tip["whole_day_readiness_claim"])

    def test_missing_sleep_is_not_zero(self):
        self.assertNotEqual(self.advice()["tip_id"], "quiet_awake_break")

    def test_sleep_mode_uses_sleep_habit(self):
        self.assertEqual(self.advice("sleep")["tip_id"], "regular_sleep_routine")

    def test_limited_data_does_not_claim_a_good_outcome(self):
        tip = self.advice(limited_evidence=True)
        self.assertEqual(tip["basis"], "limited_data")

    def test_missing_score_still_has_practical_advice(self):
        tip = build_post_rest_advice("nap_recovery", None, {})
        self.assertTrue(tip["primary"])
        self.assertEqual(tip["tip_id"], "check_feeling")

    def test_valid_self_report_changes_action(self):
        tip = self.advice(
            subjective={
                "status": "measured",
                "freshness_delta": -2,
                "source": "session_questionnaire",
                "sensor_inferred": False,
            }
        )
        self.assertEqual(tip["basis"], "self_report")
        self.assertIn("ขับรถ", tip["primary"])

    def test_unverified_self_report_does_not_personalise(self):
        tip = self.advice(subjective={"status": "measured", "freshness_delta": -2})
        self.assertNotEqual(tip["basis"], "self_report")

    def test_no_baseline_claim_without_valid_comparison(self):
        tip = self.advice("sleep", baseline={"comparison": {"available": False}})
        self.assertEqual(tip["basis"], "session_sensor")

    def test_valid_prior_baseline_is_explained(self):
        tip = self.advice(
            "sleep",
            baseline={
                "comparison": {
                    "available": True,
                    "label": "ใกล้รูปแบบเดิม",
                }
            },
        )
        self.assertEqual(tip["basis"], "personal_baseline")
        self.assertIn("รูปแบบและเป้าหมายเดียวกัน", tip["reason"])

    def test_safety_precedes_general_tips(self):
        tip = build_post_rest_advice(
            "sleep",
            90,
            {
                "attention": [
                    {
                        "key": "environment_co2",
                        "priority": "safety_review",
                        "action": "กรุณาแจ้งทีมงาน",
                    }
                ]
            },
            limited_evidence=True,
        )
        self.assertEqual(tip["basis"], "safety")
        self.assertEqual(tip["primary"], "กรุณาแจ้งทีมงาน")

    def test_different_observations_select_different_actions(self):
        tips = [
            build_post_rest_advice(
                "sleep",
                80,
                {
                    "attention": [
                        {
                            "key": "environment_" + metric,
                            "category": "environment",
                            "label": metric,
                        }
                    ]
                },
            )
            for metric in ("sound", "lux", "co2")
        ]
        self.assertEqual(len({tip["primary"] for tip in tips}), 3)
        self.assertTrue(all("ยังไม่ยืนยันว่าเป็นสาเหตุ" in tip["reason"] for tip in tips))

    def test_plain_language_keeps_the_action_and_evidence_separate(self):
        tip = self.advice(quality={"estimated_sleep_s": 0})
        self.assertEqual(tip["title"], "พักสายตาระหว่างวัน")
        self.assertIn("ไม่ต้องฝืนให้หลับ", tip["primary"])
        self.assertIn("ยังไม่พบช่วงหลับชัดเจน", tip["reason"])
        self.assertNotIn("Sensor", tip["primary"] + tip["reason"])
        self.assertFalse(tip["automatic_actuation"])

    def test_short_session_tip_is_conditional_not_a_claim_of_drowsiness(self):
        tip = build_post_rest_advice("nap_recovery", None, {})
        self.assertIn("หากยังรู้สึกง่วง", tip["primary"])
        self.assertEqual(tip["basis"], "limited_data")
        self.assertFalse(tip["whole_day_readiness_claim"])

    def test_score_and_input_are_not_changed(self):
        quality = _sleep_quality(82)
        original = copy.deepcopy(quality)
        summary = build_restore_summary(quality)
        self.assertEqual(quality, original)
        self.assertEqual(summary["source_score"]["value"], 82)
        self.assertTrue(summary["recommendation"]["reason"])

    def test_report_metric_aliases_select_specific_actions(self):
        for metric, expected in (
            ("voc", "environment_voc_index"),
            ("pm25", "environment_pm2_5"),
        ):
            tip = build_post_rest_advice(
                "sleep",
                80,
                {
                    "attention": [
                        {
                            "key": "environment_" + metric,
                            "category": "environment",
                        }
                    ]
                },
            )
            self.assertEqual(tip["tip_id"], expected)

    def test_invalid_questionnaire_is_not_promoted_to_measured(self):
        summary = build_restore_summary(
            _sleep_quality(),
            subjective_outcome={
                "status": "measured",
                "freshness_delta": 2,
            },
        )
        self.assertEqual(summary["subjective_outcome"]["status"], "not_measured")


if __name__ == "__main__":
    unittest.main()
