"""Keep the deployed single-file UI synchronized with Control partials."""

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

    def test_calibration_ui_handles_untrusted_and_missing_raw_values(self):
        template = ui_composer.TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("function escapeMarkup(value='')", template)
        self.assertIn("function calibrationNumber(value,step=0.1)", template)
        self.assertIn(
            "if(value===null||value===undefined||value==='')return '--';",
            template,
        )
        self.assertIn("if(!Number.isFinite(number))return '--';", template)
        self.assertNotIn("channel.engineering", template)

    def test_sound_ui_uses_direct_canonical_esp32_value(self):
        template = ui_composer.TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("const raw=environment.sound_dba_est;", template)
        self.assertIn(
            "typeof raw==='number'&&Number.isFinite(raw)&&raw>=30&&raw<=130",
            template,
        )
        self.assertIn(
            "return {value:raw,unit:'dBA',digits:1,source:'esp32'};",
            template,
        )
        self.assertIn("รับ sound_dba จาก ESP32 โดยตรง", template)
        self.assertIn("SPH0645LM4H-B · ESP32 direct", template)
        self.assertIn("<span>ESP32 DIRECT</span>", template)
        self.assertIn(
            "const t=e.temperature_c,h=e.humidity_rh,l=e.lux,s=e.sound_dba_est",
            template,
        )
        for obsolete in (
            "environment.sound_dba_firmware_est",
            "sound_preview_evidence_count",
            "evidenceCount>=3",
            "ชั่วคราว · ไม่ใช้คะแนน",
            "แสดงผลเท่านั้น ไม่ใช้ประเมินภาพรวมหรือคะแนน",
            "A-weighted LAeq",
        ):
            with self.subTest(obsolete=obsolete):
                self.assertNotIn(obsolete, template)

    def test_audio_controls_default_to_visible_repeat_at_sixty_percent(self):
        partial = (ui_composer.PARTIAL_DIR / "audio.html").read_text(encoding="utf-8")
        template = ui_composer.TEMPLATE.read_text(encoding="utf-8")
        css = (ui_composer.STATIC / "theme-modern.css").read_text(encoding="utf-8")

        self.assertEqual(partial.count('id="unifiedAudioModeToggle"'), 1)
        self.assertIn('class="stream-control stream-loop', partial)
        self.assertIn('data-mode="repeat_one"', partial)
        self.assertIn('aria-pressed="true"', partial)
        self.assertIn('id="unifiedAudioModeLabel">เล่นซ้ำ', partial)
        self.assertNotIn('class="stream-mode-row"', partial)
        self.assertIn('id="unifiedVolume"', partial)
        self.assertIn('value="60"', partial)
        self.assertIn('id="unifiedVolumeText">60%</b>', partial)
        self.assertIn("let unifiedAudioMode = 'repeat_one';", template)
        self.assertIn("music.volume??60", template)
        self.assertIn(
            "grid-template-columns: repeat(4, minmax(0, 1fr));",
            css,
        )
        self.assertIn(".audio-zone .stream-loop.on", css)

    def test_history_reports_use_mode_appropriate_result_language(self):
        template = ui_composer.TEMPLATE.read_text(encoding="utf-8")
        css = (ui_composer.STATIC / "theme-modern.css").read_text(
            encoding="utf-8"
        )

        self.assertIn("function reportPresentationMode(source)", template)
        self.assertIn("'NAP & REFRESH SUMMARY'", template)
        self.assertIn("'OVERNIGHT SLEEP SUMMARY'", template)
        self.assertIn("'รูปแบบการพักที่ตรวจพบ'", template)
        self.assertIn("awake_rest:{label:'พักขณะตื่น'", template)
        self.assertIn("drowsy:{label:'เคลิ้ม · N1'", template)
        self.assertIn("short_sleep:{label:'พบช่วงหลับ · N2/N3/REM'", template)
        self.assertIn("unconfirmed:{label:'ยังยืนยันไม่ได้", template)
        self.assertIn("NO DATA/OFF BED", template)
        self.assertIn("'ไม่บังคับให้หลับ · Sleep State เป็นข้อมูลประกอบ'", template)
        self.assertIn("NREM เป็นผลรวม N1 + N2 + N3", template)
        self.assertIn("function recoveryProtocolBadge(report)", template)
        self.assertIn("status==='target_unknown'", template)
        self.assertIn("`เป้าหมาย ${Math.round(targetMinutes)} นาที`", template)
        self.assertIn("'Legacy target ไม่ถูกบันทึก'", template)
        self.assertIn("'ตรวจ Mode/ระยะเวลา'", template)
        self.assertNotIn("stageCoverage>=80", template)
        self.assertNotIn("ต้องมี Sleep State coverage อย่างน้อย 80%", template)
        self.assertIn(".session-report-overview.mode-recovery", css)
        self.assertIn(".recovery-profile-summary", css)
        self.assertIn(".report-protocol-badge.legacy", css)


if __name__ == "__main__":
    unittest.main()
