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

    def test_inline_partials_are_complete_ordered_and_deterministic(self):
        template = ui_composer.TEMPLATE.read_text(encoding="utf-8")
        marker_positions = []
        for name in ui_composer.INLINE_PARTIALS:
            with self.subTest(partial=name):
                path = ui_composer.STATIC / "partials" / name
                self.assertTrue(path.is_file())
                self.assertTrue(path.read_text(encoding="utf-8").endswith("\n"))
                marker = ui_composer.INLINE_MARKER.format(name=name)
                self.assertEqual(template.count(marker), 1)
                marker_positions.append(template.index(marker))
        self.assertEqual(marker_positions, sorted(marker_positions))
        self.assertEqual(ui_composer.render(), ui_composer.render())

    def test_composed_dom_ids_are_unique_and_literal_references_exist(self):
        runtime = ui_composer.render()
        element_ids = re.findall(r'\bid="([^"]+)"', runtime)
        self.assertEqual(len(element_ids), len(set(element_ids)))
        referenced_ids = set(
            re.findall(r"getElementById\(['\"]([^'\"]+)['\"]\)", runtime)
        )
        self.assertEqual(referenced_ids - set(element_ids), set())

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
                self.assertEqual(template.count(ui_composer.MARKER.format(name=filename)), 1)

    def test_calibration_ui_handles_untrusted_and_missing_raw_values(self):
        template = ui_composer.render()
        self.assertIn("function escapeMarkup(value='')", template)
        self.assertIn("function calibrationNumber(value,step=0.1)", template)
        self.assertIn(
            "if(value===null||value===undefined||value==='')return '--';",
            template,
        )
        self.assertIn("if(!Number.isFinite(number))return '--';", template)
        self.assertNotIn("channel.engineering", template)

    def test_sound_ui_uses_direct_canonical_esp32_value(self):
        template = ui_composer.render()
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

    def test_respiratory_wellness_ui_is_age_aware_without_medical_claims(self):
        template = ui_composer.render()
        css = (ui_composer.STATIC / "theme-modern.css").read_text(encoding="utf-8")

        self.assertIn("function renderRespiratoryWellness", template)
        self.assertIn("การหายใจระหว่างพัก", template)
        self.assertIn("ข้อมูลนี้ช่วยดูแนวโน้มระหว่างพัก", template)
        self.assertIn("ไม่ใช่การตรวจสมรรถภาพปอด", template)
        self.assertIn("ออกซิเจนในเลือด หรือการวินิจฉัยโรค", template)
        self.assertIn(
            "ไม่เปลี่ยน Sleep/Recovery Score",
            template,
        )
        self.assertIn("respiratory_wellness", template)
        self.assertIn(".respiratory-wellness-card", css)

        for unsafe_claim in (
            "ปอดแข็งแรงมาก",
            "ปอดแข็งแรงดี",
            "วินิจฉัยภาวะหยุดหายใจ",
            "ตรวจพบภาวะหยุดหายใจ",
            "วัดออกซิเจนในเลือด",
        ):
            with self.subTest(unsafe_claim=unsafe_claim):
                self.assertNotIn(unsafe_claim, template)

    def test_user_vitals_summary_groups_heart_and_breathing_without_fitness_claims(self):
        template = ui_composer.render()
        start = template.index("function renderRespiratoryWellness")
        end = template.index("function renderSessionOverview", start)
        renderer = template[start:end]

        self.assertIn("if(!adminView){", renderer)
        self.assertIn("ชีพจรและการหายใจ", renderer)
        self.assertIn("vital.heart_rate_bpm", renderer)
        self.assertIn("vital.respiration_rate_brpm", renderer)
        self.assertIn("ชีพจรโดยประมาณ", renderer)
        self.assertIn("หายใจโดยประมาณ", renderer)
        self.assertIn("value!==null&&value!==undefined&&value!==''", renderer)
        self.assertIn("<b>สรุป</b>", renderer)
        self.assertIn("<b>คำแนะนำ</b>", renderer)
        self.assertIn("ไม่ใช่การวินิจฉัย", renderer)
        self.assertNotIn("quality.physiology?.heart_rate_average", renderer)
        self.assertNotIn("summary.interpretation", renderer.split("if(!adminView){", 1)[1].split("return `<section", 1)[0])
        self.assertIn(
            "!adminView||q.physiology?.heart_rate_average==null",
            template,
        )
        self.assertIn("adminView||!hasCompactVitals?statBlock", template)
        for prohibited in ("ร่างกายแข็งแรง", "ปอดแข็งแรง", "ความฟิต", "ฟิตมาก"):
            with self.subTest(prohibited=prohibited):
                self.assertNotIn(prohibited, renderer)

    def test_audio_controls_default_to_visible_repeat_at_sixty_percent(self):
        partial = (ui_composer.PARTIAL_DIR / "audio.html").read_text(encoding="utf-8")
        template = ui_composer.render()
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
        template = ui_composer.render()
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
        self.assertNotIn("unconfirmed:{label:'ยังยืนยันไม่ได้", template)
        self.assertIn(
            "ทุกช่วงที่อยู่บนเตียงถูกนำมาประเมินอย่างต่อเนื่อง",
            template,
        )
        self.assertIn(
            "'Nap & Refresh นับคุณค่าของการพักทั้งขณะตื่นและหลับ'",
            template,
        )
        self.assertIn("NREM คือ N1 + N2 + N3", template)
        self.assertIn("function recoveryProtocolBadge(report,adminView=false)", template)
        self.assertIn("status==='target_unknown'", template)
        self.assertIn("`เป้าหมาย ${Math.round(targetMinutes)} นาที`", template)
        self.assertIn("'Legacy target ไม่ถูกบันทึก'", template)
        self.assertIn("'ตรวจ Mode/ระยะเวลา'", template)
        self.assertIn("'ระยะเวลาต่างจากรูปแบบที่เลือก'", template)
        self.assertNotIn("stageCoverage>=80", template)
        self.assertNotIn("ต้องมี Sleep State coverage อย่างน้อย 80%", template)
        self.assertIn(".session-report-overview.mode-recovery", css)
        self.assertIn(".recovery-profile-summary", css)
        self.assertIn(".report-protocol-badge.legacy", css)

    def test_usage_history_copy_keeps_legacy_routes_and_filter_ids(self):
        template = ui_composer.render()
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
        template = ui_composer.render()
        css = (ui_composer.STATIC / "theme-modern.css").read_text(encoding="utf-8")

        self.assertIn("function restoreSummarySource(source)", template)
        self.assertIn(
            "payload.restore_summary||report.restore_summary",
            template,
        )
        self.assertIn("if(!summary||typeof summary!=='object')return null;", template)
        self.assertNotIn("summary.available===false)return null", template)
        self.assertIn("['message','observation','name']", template)
        self.assertIn("สิ่งที่ทำได้ดี", template)
        self.assertIn("ไม่ยืนยันเหตุ–ผล", template)
        self.assertIn("ไม่ใช่ความพร้อมตลอดทั้งวัน", template)
        self.assertIn("กำลังรวบรวมข้อมูลเพื่ออธิบายผลการพักครั้งนี้", template)
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
        template = ui_composer.render()
        css = (ui_composer.STATIC / "theme-modern.css").read_text(encoding="utf-8")

        self.assertIn("const adminView=currentPrincipal?.role==='admin';", template)
        self.assertIn("const technicalNote=currentPrincipal?.role==='admin'", template)
        self.assertNotIn("function normalizeUsageDetail(payload)", template)
        self.assertIn("const legacyPath=`/api/history/", template)
        self.assertIn("renderReport(await r.json())", template)
        self.assertNotIn("sleep_timeline:[]", template)
        self.assertIn('class="sleep-period user-sleep-period"', template)
        self.assertIn("ประเมินจากแนวโน้มระหว่างการพัก", template)
        self.assertIn("แสดงต่อเนื่องจากช่วงก่อนหน้า", template)
        self.assertIn("@media (max-width: 520px)", css)
        self.assertIn("grid-template-columns: repeat(6, minmax(0, 1fr));", css)
        self.assertIn("min-height: 44px;", css)
        self.assertIn(
            'body[data-view="sessions"][data-role="admin"] .history-admin-filter',
            css,
        )

    def test_sleep_state_ui_discloses_continuity_hold_without_unclassified(self):
        template = ui_composer.render()

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
        self.assertNotIn("stage.score_eligible_duration_s", template)
        self.assertIn("State ที่เข้าคะแนน", template)
        self.assertIn("Recovery Score ไม่บังคับให้หลับ", template)
        self.assertIn("State (ข้อมูลประกอบ)", template)
        self.assertIn("provisional · คง State ก่อนหน้า", template)
        self.assertIn("ยังไม่นับเป็น State ใหม่", template)
        self.assertIn("แสดงต่อเนื่องจากช่วงก่อนหน้า", template)
        self.assertRegex(template, r"no_data:\s+\{code:'NO DATA'")
        self.assertIn("confirming_initial_state", template)
        self.assertIn("WAIT · กำลังยืนยันสถานะ", template)
        self.assertNotIn("period.decision_kind==='classification_gap'", template)
        self.assertNotIn("provisional เป็นส่วนหนึ่งของเวลาที่คง State", template)
        self.assertIn("OFF BED เท่านั้นที่ไม่เข้า Sleep Score", template)
        self.assertNotIn("WAIT · ไม่มีข้อมูลสถานะ", template)
        self.assertNotIn("Unclassified", template)

    def test_user_copy_is_friendly_while_safety_language_stays_direct(self):
        template = ui_composer.render()

        self.assertIn("const USER_PRODUCT_COPY=Object.freeze", template)
        self.assertIn("กำลังเชื่อมต่อข้อมูลล่าสุด", template)
        self.assertIn("กำลังยืนยันการเปลี่ยนแปลง", template)
        self.assertIn("ช่วงนี้แยกจากเวลาพัก", template)
        self.assertIn("ระยะเวลาใช้งาน", template)
        self.assertIn("data-admin-panel", template)
        self.assertIn("ระบบเข้าสู่โหมดปลอดภัย", template)
        self.assertIn("CO₂ ≥1,300 ppm", template)
        self.assertIn("function userReportFinding", template)
        self.assertIn("function userScoreMeaning", template)
        self.assertIn("แนะนำให้ปรับตอนนี้", template)
        self.assertIn("กรุณาแจ้งทีมงาน", template)
        self.assertIn("unknown:'ผลการพักครั้งนี้'", template)
        self.assertIn(
            "ดูภาพรวมการพักครั้งนี้ร่วมกับรายละเอียดด้านล่าง",
            template,
        )
        self.assertIn("ยังไม่ได้ยืนยันการเข้าสู่ระบบจากโทรศัพท์", template)
        self.assertIn("กรุณาเข้าสู่ระบบอีกครั้งเพื่อดูประวัติของคุณ", template)
        self.assertIn("ยังไม่ตอบสนอง · ลองอีกครั้ง", template)
        self.assertIn("QR สำหรับผลครั้งนี้ยังไม่พร้อม", template)
        self.assertIn("กำลังเตรียม ZEEP", template)
        self.assertIn("กรอกอีเมลหรือชื่อผู้ใช้และรหัสผ่านให้ครบ", template)
        self.assertIn("การพักครั้งนี้สิ้นสุดแล้ว", template)
        self.assertIn("เริ่มการพักแบบออฟไลน์เรียบร้อยแล้ว", template)
        self.assertNotIn("มือถือปฏิเสธการเข้าสู่ระบบนี้", template)
        self.assertNotIn("กรอก Username/Email", template)
        self.assertNotIn("Session สิ้นสุดแล้ว", template)
        self.assertNotIn("Session นี้ไม่ได้ผูกกับบัญชี ZEEP", template)

    def test_user_surfaces_project_stable_copy_instead_of_raw_api_details(self):
        template = ui_composer.render()

        post_start = template.index("async function post(url, body)")
        post_end = template.index("/* ---- Admin Control Debug", post_start)
        qr_start = template.index("function qrErrorFrom")
        qr_end = template.index("async function startQrSession", qr_start)
        login_start = template.index("async function doZeepLogin")
        login_end = template.index("async function doLocalLogin", login_start)
        history_start = template.index("async function refreshHistory")
        history_end = template.index("function historyLocalToday", history_start)
        restore_start = template.index("function renderRestoreSummary")
        restore_end = template.index("function historyScoreMarkup", restore_start)

        self.assertIn("if(adminView)", template[post_start:post_end])
        self.assertIn("ทำรายการไม่สำเร็จ กรุณาลองอีกครั้ง", template[post_start:post_end])
        self.assertNotIn("detail.message", template[qr_start:qr_end])
        self.assertIn("userLoginFailure(code,r.status)", template[login_start:login_end])
        self.assertNotIn("detail.message", template[login_start:login_end])
        self.assertIn("กำลังเตรียมรายการย้อนหลังของคุณ", template[history_start:history_end])
        self.assertIn("userRestoreMeaning", template[restore_start:restore_end])
        self.assertIn("userRestoreDriverText", template[restore_start:restore_end])

        dashboard_start = template.index("function setDashboardSensor")
        dashboard_end = template.index("const dashboardAtmosphereLevels", dashboard_start)
        unified_start = template.index("function setUnifiedSensor")
        unified_end = template.index("const unifiedComfortProfiles", unified_start)
        self.assertIn("currentPrincipal?.role==='admin'", template[dashboard_start:dashboard_end])
        self.assertIn("currentPrincipal?.role==='admin'", template[unified_start:unified_end])

    def test_required_safety_sensor_loss_never_invites_user_to_continue(self):
        template = ui_composer.render()
        start = template.index("const safetyFaults=Array.isArray")
        end = template.index("if (sessionChanged && se.active)", start)
        message_policy = template[start:end]

        self.assertIn("se.active&&userSafetyFaults.length", message_policy)
        self.assertIn("กรุณาหยุดการพัก", message_policy)
        self.assertIn("เปิดประตูออกจาก ZEEP", message_policy)
        self.assertIn("ระบบกำลังตรวจความพร้อม", message_policy)

    def test_safety_banner_is_visible_and_actionable_on_every_view(self):
        template = ui_composer.render()
        start = template.index("const safetyFaults=Array.isArray")
        end = template.index("if (sessionChanged && se.active)", start)
        message_policy = template[start:end]

        self.assertIn('id="safetyUserAlert"', template)
        self.assertIn('role="alert" aria-live="assertive"', template)
        self.assertIn("function setSafetyUserAlert", template)
        self.assertIn("setSafetyUserAlert(true,title,detail,se.active)", message_policy)
        self.assertIn("กรุณาหยุดการพัก เปิดประตูออกจาก ZEEP", message_policy)
        self.assertIn('href="/control"', template)

        login_start = template.index("function renderLoginSafety")
        login_end = template.index("async function safetyAction", login_start)
        login_renderer = template[login_start:login_end]
        self.assertIn("sf.level==='emergency'", login_renderer)
        self.assertIn("เปิดประตู ออกจาก ZEEP", login_renderer)
        emergency_copy = login_renderer.split("el.className='login-safety danger';", 1)[1]
        self.assertNotIn("el.textContent=''", emergency_copy)

    def test_safety_emergency_alert_is_not_limited_to_monitor_route(self):
        template = ui_composer.render()
        alert_start = template.index("function setMonitorAlert")
        alert_end = template.index("function evaluateMonitorAlerts", alert_start)
        render_start = template.index("function renderSafety")
        render_end = template.index("function renderLoginSafety", render_start)

        self.assertIn("announceNewEmergency", template[alert_start:alert_end])
        self.assertIn("key==='safety_emergency'", template[alert_start:alert_end])
        self.assertIn("currentPrincipal?.role==='admin'", template[render_start:render_end])
        self.assertNotIn(
            "document.body.dataset.view==='monitor'",
            template[render_start:render_end],
        )

    def test_shared_report_image_uses_the_same_user_copy_projector(self):
        template = ui_composer.render()
        score_start = template.index("function drawReportScore")
        score_end = template.index("function drawReportMetrics", score_start)
        finding_start = template.index("function drawReportFindings")
        finding_end = template.index("async function drawSessionReportPng", finding_start)
        png_start = finding_end
        png_end = template.index("async function doLogout", png_start)

        self.assertIn("userScoreMeaning(quality)", template[score_start:score_end])
        self.assertNotIn("quality.insight", template[score_start:score_end])
        self.assertIn("userReportFinding(item)", template[finding_start:finding_end])
        self.assertNotIn("item.detail", template[finding_start:finding_end])
        self.assertNotIn("Coverage:", template[png_start:png_end])
        self.assertIn("เป็นข้อมูลเพื่อดูแลการพัก", template[png_start:png_end])

    def test_shared_report_image_prioritises_safety_review_before_truncation(self):
        template = ui_composer.render()
        start = template.index("function drawReportFindings")
        end = template.index("async function drawSessionReportPng", start)
        renderer = template[start:end]

        self.assertIn("item?.decision==='safety_review'?0", renderer)
        self.assertLess(renderer.index(".sort("), renderer.index(".slice(0,5)"))

    def test_user_result_copy_does_not_trust_legacy_engineering_text(self):
        template = ui_composer.render()
        finding_start = template.index("function userReportFinding")
        finding_end = template.index("function userEnvironmentPresentation", finding_start)
        finding_renderer = template[finding_start:finding_end]
        baseline_start = template.index("function renderRestoreSummary")
        baseline_end = template.index("function historyScoreMarkup", baseline_start)
        baseline_renderer = template[baseline_start:baseline_end]

        self.assertIn("environmentMetrics[metricKey]", finding_renderer)
        self.assertNotIn("item.title", finding_renderer)
        self.assertIn("จากการพัก ${Math.round(sessionsUsed)} ครั้ง", baseline_renderer)
        self.assertNotIn("${Math.round(sessionsUsed)} Session", baseline_renderer)
        self.assertIn("ช่วงที่มีการรบกวน", template)
        self.assertIn("ยังไม่มีปัจจัยที่ต้องดูแลเป็นพิเศษ", template)

    def test_user_sleep_and_profile_copy_hides_model_implementation(self):
        template = ui_composer.render()

        guide_start = template.index('<details class="stage-guide">')
        guide_end = template.index("</details>", guide_start)
        guide = template[guide_start:guide_end]
        login_start = template.index("function renderLoginBaseline")
        login_end = template.index("const SLEEP_TH", login_start)
        login_copy = template[login_start:login_end]
        profile_start = template.index("function renderHealthReference")
        profile_end = template.index("function healthReferenceInline", profile_start)
        profile_copy = template[profile_start:profile_end]

        self.assertIn("Sleep Stage เป็นค่าประเมินแนวโน้ม", guide)
        self.assertIn("ระยะ REM / หลับฝัน", guide)
        self.assertIn("ไม่ได้วัดการฟื้นตัวของร่างกาย ความฝัน หรือความจำโดยตรง", guide)
        for technical_term in ("BCG", "HR/RR", "PSG"):
            with self.subTest(technical_term=technical_term):
                self.assertNotIn(technical_term, guide)
        self.assertIn("เตรียมค่าเริ่มต้นที่เหมาะกับคุณ", login_copy)
        self.assertIn("เรียนรู้รูปแบบของคุณ", login_copy)
        self.assertNotIn("base-row", login_copy)
        self.assertNotIn("Gender Baseline", login_copy)
        self.assertIn("const adminView=currentPrincipal?.role==='admin';", profile_copy)
        self.assertIn("ข้อมูลจากบัญชีช่วยให้คำแนะนำเหมาะกับคุณมากขึ้น", profile_copy)

    def test_user_control_copy_hides_controller_topology(self):
        template = ui_composer.render()
        control_start = template.index("function renderUnifiedControl")
        control_end = template.index("/* ---- Red ambient", control_start)
        renderer = template[control_start:control_end]
        partials = "\n".join((ui_composer.PARTIAL_DIR / filename).read_text(encoding="utf-8") for filename in ui_composer.PARTIALS.values())

        self.assertIn("const adminView=currentPrincipal?.role==='admin';", renderer)
        self.assertIn("'กำลังเชื่อมต่อแอร์'", renderer)
        self.assertIn("'ระดับเสียง · dBA'", renderer)
        self.assertIn("USER_BED_STATUS_TH", renderer)
        for visible_implementation_copy in (
            ">Aircon · Offline<",
            ">ESP32 Bed · --<",
            ">GPIO · --<",
            ">Audio · --<",
            ">ค่าจาก ESP32 · dBA<",
            ">PI5 · Pulse<",
            ">Pulse Output · 1 วินาที<",
        ):
            with self.subTest(copy=visible_implementation_copy):
                self.assertNotIn(visible_implementation_copy, partials)

    def test_wellness_card_does_not_own_emergency_alarm(self):
        template = ui_composer.render()
        start = template.index("function renderDashboardAtmosphere")
        end = template.index("const ADMIN_EXPLANATION_CONTEXT", start)
        atmosphere_renderer = template[start:end]

        self.assertNotIn("playMonitorTone", atmosphere_renderer)
        self.assertNotIn("toast(", atmosphere_renderer)
        self.assertIn("card.setAttribute('aria-live','polite')", atmosphere_renderer)
        self.assertIn("function renderSafety", template)
        self.assertIn("'safety_emergency'", template)


if __name__ == "__main__":
    unittest.main()
