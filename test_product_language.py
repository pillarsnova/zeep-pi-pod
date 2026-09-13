import unittest

from zeep_pod.product_language import (
    USER_ENVIRONMENT_LEVELS,
    USER_WELLNESS_DISCLAIMER,
    user_confidence_level,
    user_environment_finding_copy,
    user_environment_level,
    user_respiratory_age_context,
    user_score_level,
)
from zeep_pod.sessions.quality_publication import (
    public_environment_metric,
    public_quality_payload,
)
from zeep_pod.sessions.report_publication import public_report_field
from zeep_pod.sessions.result_context import canonical_subjective_outcome


class ProductLanguageTests(unittest.TestCase):
    def test_score_copy_keeps_low_result_supportive(self):
        self.assertEqual(
            user_score_level("low", "ควรปรับปรุง"),
            "ให้เวลากับการพักเพิ่ม",
        )
        self.assertEqual(user_score_level("good"), "ดี")

    def test_wellness_levels_do_not_reuse_emergency_judgement(self):
        self.assertEqual(user_environment_level("poor"), "ควรปรับ")
        self.assertEqual(
            user_environment_level("critical"),
            "แนะนำให้ปรับตอนนี้",
        )
        self.assertNotIn("แย่", USER_ENVIRONMENT_LEVELS.values())
        self.assertNotIn("วิกฤต", USER_ENVIRONMENT_LEVELS.values())

    def test_unknown_copy_is_calm_and_honest(self):
        self.assertEqual(
            user_environment_level("unknown"),
            "กำลังรวบรวมข้อมูล",
        )
        self.assertEqual(
            user_score_level("custom", "ควรปรับปรุง"),
            "ผลการพักครั้งนี้",
        )
        self.assertEqual(
            user_environment_level("future", "แย่"),
            "กำลังรวบรวมข้อมูล",
        )
        self.assertEqual(
            user_confidence_level("future", "ข้อมูลไม่พอ"),
            "กำลังเตรียมผลสรุป",
        )
        self.assertEqual(user_confidence_level("low"), "กำลังรวบรวมข้อมูลเพิ่ม")

    def test_safety_review_stays_direct_without_engineering_jargon(self):
        title, detail, action, safety_review = user_environment_finding_copy(
            "CO₂ · พบ Safety excursion",
            "critical",
            "safety_review",
            "co2",
        )

        self.assertEqual(title, "CO₂ · ควรให้ทีมตรวจสอบ")
        self.assertIn("เกณฑ์ความปลอดภัย", detail)
        self.assertNotIn("excursion", detail.casefold())
        self.assertEqual(action, "กรุณาแจ้งทีมงาน")
        self.assertTrue(safety_review)

    def test_missing_optional_context_invites_the_next_step(self):
        band, label, guidance = user_respiratory_age_context(None)

        self.assertIsNone(band)
        self.assertEqual(label, "บริบทตามช่วงวัย")
        self.assertIn("ให้คำแนะนำเหมาะกับช่วงวัย", guidance)

        outcome = canonical_subjective_outcome(None)
        self.assertEqual(outcome["status"], "not_measured")
        self.assertEqual(outcome["label"], "ยังไม่ได้บันทึกความรู้สึกหลังพัก")

    def test_public_api_rewrites_legacy_harsh_environment_copy(self):
        metric = public_environment_metric({"status_key": "critical", "status": "วิกฤต"})
        assessment = public_report_field(
            "environment_assessment",
            {
                "mode": "sleep",
                "mode_label": "BCG Overnight Gate",
                "acceptable_min_level": "fair",
                "acceptable_min_label": "firmware threshold",
                "overall_level": "poor",
                "overall_label": "แย่",
            },
        )

        self.assertEqual(metric["status"], "แนะนำให้ปรับตอนนี้")
        self.assertEqual(assessment["mode_label"], "Overnight Recovery")
        self.assertEqual(assessment["acceptable_min_label"], "พอใช้")
        self.assertEqual(assessment["overall_label"], "ควรปรับ")

        finding = public_report_field(
            "findings",
            [
                {
                    "key": "temperature",
                    "severity": "poor",
                    "decision": "required",
                    "title": "Timeline Gate SHT3x-DIS · แย่",
                    "detail": "ตรวจ firmware freshness",
                    "action": "debug sensor",
                }
            ],
        )[0]
        self.assertEqual(finding["title"], "อุณหภูมิ · ควรปรับ")
        self.assertNotIn("Timeline", str(finding))
        self.assertNotIn("SHT3x", str(finding))

    def test_public_finding_copy_covers_acoustic_unknown_and_safety(self):
        findings = public_report_field(
            "findings",
            [
                {
                    "key": "acoustic_corroborated",
                    "severity": "fair",
                    "decision": "investigate",
                    "title": "SPH0645 / BCG / Bed Status",
                    "detail": "Timeline Gate matched 4 Epochs",
                    "action": "debug firmware",
                },
                {
                    "key": "future_backend_finding",
                    "severity": "poor",
                    "decision": "investigate",
                    "title": "แย่มาก",
                    "detail": "UNKNOWN GATE FAILED",
                    "action": "inspect raw payload",
                },
                {
                    "key": "future_safety_finding",
                    "severity": "critical",
                    "decision": "safety_review",
                    "title": "EMERGENCY SENSOR BUS FAILURE",
                    "detail": "GPIO timeout",
                    "action": "reboot ESP32",
                    "critical_above": 32.0,
                    "maximum": 34.0,
                },
            ],
        )

        self.assertEqual(
            findings[0]["title"],
            "เสียงและการขยับบนเตียง · ลองสังเกตเพิ่มเติม",
        )
        self.assertIn("ช่วงเวลาใกล้กัน", findings[0]["detail"])
        self.assertEqual(findings[1]["title"], "ข้อมูลประกอบ · ลองสังเกตเพิ่มเติม")
        self.assertEqual(
            findings[2]["title"],
            "ข้อมูลด้านความปลอดภัย · ควรให้ทีมตรวจสอบ",
        )
        self.assertEqual(findings[2]["action"], "กรุณาแจ้งทีมงาน")
        self.assertEqual(findings[2]["critical_above"], 32.0)
        self.assertEqual(findings[2]["maximum"], 34.0)
        rendered = str(findings)
        for internal_copy in (
            "SPH0645",
            "BCG",
            "Timeline",
            "Gate",
            "Epoch",
            "firmware",
            "UNKNOWN",
            "GPIO",
            "ESP32",
            "แย่มาก",
        ):
            self.assertNotIn(internal_copy, rendered)

    def test_unknown_assessment_labels_fail_closed(self):
        assessment = public_report_field(
            "environment_assessment",
            {
                "mode": "future_mode",
                "mode_label": "Internal Mode Gate",
                "acceptable_min_label": "Critical firmware threshold",
            },
        )

        self.assertEqual(assessment["mode_label"], "รูปแบบการพักครั้งนี้")
        self.assertEqual(assessment["acceptable_min_label"], "กำลังรวบรวมข้อมูล")
        self.assertNotIn("Gate", str(assessment))
        self.assertNotIn("firmware", str(assessment))

    def test_public_disclaimers_and_component_labels_are_canonical(self):
        quality = public_quality_payload(
            {
                "component_labels": {
                    "sleep_opportunity": "Sleep onset Gate",
                    "restorative_architecture": "N2/N3/REM architecture",
                    "data_coverage": "BCG paired coverage",
                    "secret_component": "raw backend wording",
                },
                "disclaimer": "BCG Sensor result using AASM PSG proxy",
            }
        )

        self.assertEqual(
            quality["component_labels"],
            {
                "sleep_opportunity": "เวลาและการเข้าสู่การพัก",
                "restorative_architecture": "รูปแบบการพัก",
                "data_coverage": "ความครบถ้วนของข้อมูล",
            },
        )
        self.assertEqual(quality["disclaimer"], USER_WELLNESS_DISCLAIMER)
        self.assertEqual(
            public_report_field("disclaimer", "BCG/AASM/PSG internal note"),
            USER_WELLNESS_DISCLAIMER,
        )
        rendered = str(quality)
        for internal_copy in ("Gate", "N2", "BCG", "AASM", "PSG", "backend"):
            self.assertNotIn(internal_copy, rendered)


if __name__ == "__main__":
    unittest.main()
