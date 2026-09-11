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
        css = (ui_composer.STATIC / "theme-modern.css").read_text(encoding="utf-8")

        self.assertIn("function reportPresentationMode(source)", template)
        self.assertIn("if(unresolved)return 'unknown';", template)
        self.assertIn("'รูปแบบยังไม่ยืนยัน'", template)
        self.assertIn("'ผล Session · รอยืนยันรูปแบบ'", template)
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

    def test_usage_history_copy_keeps_legacy_routes_and_filter_ids(self):
        template = ui_composer.TEMPLATE.read_text(encoding="utf-8")
        shell = (ui_composer.STATIC / "app-shell.js").read_text(encoding="utf-8")

        self.assertIn("title: 'ประวัติการใช้งาน'", shell)
        self.assertIn("ดูผล Overnight Recovery และ Nap & Refresh", shell)
        self.assertNotIn("ประวัติการนอน", shell)
        self.assertIn("<h3>ประวัติการใช้งาน</h3>", template)
        self.assertIn("USAGE HISTORY", template)
        self.assertNotIn("<h3>ประวัติการนอน</h3>", template)

        for legacy_contract in (
            'id="historyCard"',
            'id="historyUser"',
            "function refreshHistory(btn)",
            "/api/history/${encodeURIComponent(user)}",
        ):
            with self.subTest(legacy_contract=legacy_contract):
                self.assertIn(legacy_contract, template)

        for filter_id in (
            "historyDateFrom",
            "historyDateTo",
            "historyTimeFrom",
            "historyTimeTo",
            "historyNameFilter",
            "historyUser",
        ):
            with self.subTest(filter_id=filter_id):
                self.assertIn(f'id="{filter_id}"', template)

    def test_restore_summary_is_short_claim_safe_and_backward_compatible(self):
        template = ui_composer.TEMPLATE.read_text(encoding="utf-8")
        css = (ui_composer.STATIC / "theme-modern.css").read_text(encoding="utf-8")

        self.assertIn("function restoreSummarySource(source)", template)
        self.assertIn(
            "payload.restore_summary||report.restore_summary",
            template,
        )
        self.assertIn("if(!summary||typeof summary!=='object')return null;", template)
        self.assertNotIn("summary.available===false)return null", template)
        self.assertIn("['message','observation','name']", template)
        self.assertIn("ข้อมูลที่สัมพันธ์กับผล", template)
        self.assertIn("ไม่ยืนยันเหตุ–ผล", template)
        self.assertIn("ไม่ใช่ความพร้อมตลอดทั้งวัน", template)
        self.assertIn("หลักฐานยังไม่พอสำหรับสรุปปัจจัย", template)
        self.assertIn("sleep_restore_very_good", template)
        self.assertIn("pace_morning", template)
        self.assertIn("prioritise_rest", template)
        self.assertIn("rest_goal_full", template)
        self.assertIn("rest_partial", template)
        self.assertIn("rest_more", template)
        self.assertIn("renderRestoreSummary(payload,presentation)", template)
        self.assertIn("renderRestoreSummary(rec,presentation)", template)
        self.assertIn(".restore-summary-card", css)
        self.assertIn(".restore-summary-grid", css)
        self.assertNotIn("whole_day_readiness", template)
        self.assertNotIn("freshness_delta", template)

    def test_user_report_hides_raw_diagnostics_and_mobile_filters_fit(self):
        template = ui_composer.TEMPLATE.read_text(encoding="utf-8")
        css = (ui_composer.STATIC / "theme-modern.css").read_text(encoding="utf-8")

        self.assertIn("const adminView=currentPrincipal?.role==='admin';", template)
        self.assertIn("const technicalNote=currentPrincipal?.role==='admin'", template)
        self.assertNotIn("function normalizeUsageDetail(payload)", template)
        self.assertIn("const legacyPath=`/api/history/", template)
        self.assertIn("renderReport(await r.json())", template)
        self.assertNotIn("sleep_timeline:[]", template)
        self.assertIn('class="sleep-period user-sleep-period"', template)
        self.assertIn("สถานะที่ระบบยืนยันจากแนวโน้มภายใน Session", template)
        self.assertIn("@media (max-width: 520px)", css)
        self.assertIn("grid-template-columns: repeat(6, minmax(0, 1fr));", css)
        self.assertIn("min-height: 44px;", css)
        self.assertIn(
            'body[data-view="sessions"][data-role="admin"] .history-admin-filter',
            css,
        )

    def test_sleep_state_ui_discloses_continuity_hold_without_unclassified(self):
        template = ui_composer.TEMPLATE.read_text(encoding="utf-8")

        self.assertIn(
            "function classificationAccountingMarkup(report,adminView,presentation)",
            template,
        )
        self.assertIn("TIME ACCOUNTING", template)
        self.assertIn("เวลาของ Session ถูกจัดหมวดครบ", template)
        self.assertIn("ใช้คิดคะแนน", template)
        self.assertIn("ไม่นับคะแนน", template)
        self.assertIn("accounting.provisional_hold_s", template)
        self.assertIn("accounting.initial_wait_s", template)
        self.assertIn("accounting.no_data_s", template)
        self.assertIn("accounting.off_bed_s", template)
        self.assertIn("stage.score_eligible_duration_s", template)
        self.assertIn("ใช้เฉพาะเวลาที่เข้าคะแนน", template)
        self.assertIn("Recovery Score ไม่บังคับให้หลับ", template)
        self.assertIn("State (ข้อมูลประกอบ)", template)
        self.assertIn("provisional · คง State ก่อนหน้า", template)
        self.assertIn("ยังไม่นับเป็น State ใหม่", template)
        self.assertIn("คงสถานะก่อนหน้า", template)
        self.assertRegex(template, r"no_data:\s+\{code:'NO DATA'")
        self.assertIn("confirming_initial_state", template)
        self.assertIn("WAIT · กำลังยืนยันสถานะ", template)
        self.assertIn("NO DATA · ไม่มีข้อมูลสถานะ", template)
        self.assertNotIn("WAIT · ไม่มีข้อมูลสถานะ", template)
        self.assertNotIn("Unclassified", template)


if __name__ == "__main__":
    unittest.main()
