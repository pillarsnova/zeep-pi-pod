"""Keep the deployed single-file UI synchronized with Control partials."""

from pathlib import Path
import re
import unittest

import ui_composer


class UiComposerTests(unittest.TestCase):
    def test_generated_index_matches_template_and_partials(self):
        self.assertEqual(
            ui_composer.INDEX.read_text(encoding="utf-8"),
            ui_composer.render(),
        )

    def test_each_control_section_has_one_partial_and_one_runtime_instance(self):
        runtime = ui_composer.INDEX.read_text(encoding="utf-8")
        template = ui_composer.TEMPLATE.read_text(encoding="utf-8")
        for class_token, filename in ui_composer.PARTIALS.items():
            with self.subTest(section=class_token):
                self.assertTrue((ui_composer.PARTIAL_DIR / filename).is_file())
                matches = re.findall(
                    rf'<section\b[^>]*class="[^"]*\b{re.escape(class_token)}\b[^"]*"',
                    runtime,
                )
                self.assertEqual(len(matches), 1)
                self.assertEqual(
                    template.count(ui_composer.MARKER.format(name=filename)), 1
                )

    def test_sound_engineering_ui_handles_untrusted_and_missing_raw_values(self):
        template = ui_composer.TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("function escapeMarkup(value='')", template)
        self.assertIn(".filter(Boolean).map(escapeMarkup).join(' · ')", template)
        self.assertIn(
            "item.value===null||item.value===undefined||item.value===''",
            template,
        )
        self.assertIn("item.healthy?'pass':'fail'", template)
        self.assertNotIn("item.value?'pass'", template)

    def test_sound_preview_is_three_packet_display_only_fallback(self):
        template = ui_composer.TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("environment.sound_dba_firmware_est", template)
        self.assertIn("evidenceCount>=3", template)
        self.assertIn("digits:2", template)
        self.assertIn("SPH0645LM4H-B · ESP32 โดยตรง", template)
        self.assertIn("แสดงผลเท่านั้น ไม่ใช้ประเมินภาพรวมหรือคะแนน", template)
        self.assertIn("ชั่วคราว · ไม่ใช้คะแนน", template)
        self.assertNotIn(
            "detail:`${fmt(soundMetric.value,1)} dBA est. · "
            "แสดงผลเท่านั้น`,level:'warn'",
            template,
        )
        self.assertIn("typeof windowRaw==='boolean'?NaN", template)
        self.assertIn(
            "const t=e.temperature_c,h=e.humidity_rh,l=e.lux,"
            "s=e.sound_dba_est",
            template,
        )


if __name__ == "__main__":
    unittest.main()
