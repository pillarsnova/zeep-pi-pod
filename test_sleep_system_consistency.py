"""Cross-layer regression tests for the canonical ZEEP sleep policy.

These tests intentionally span Live, historical replay, Session scoring, Admin
inspection, UI copy, and documentation.  A policy edit is incomplete until all
of those layers agree with :mod:`sleep_system_policy`.
"""

from pathlib import Path
import unittest

from testing_support import configure_app_test_environment

configure_app_test_environment()
import app as zeep
import personal
import reclassify_sleep_history as replay
import sleep_session_report as report
import sleep_system_policy as policy


PI5_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PI5_ROOT.parent
DOCS_ROOT = (
    PROJECT_ROOT / "docs"
    if (PROJECT_ROOT / "docs" / "zeep-sleep-system-current.md").exists()
    else PI5_ROOT / "docs"
)


class SleepSystemPolicyConsistencyTests(unittest.TestCase):
    def test_live_runtime_imports_canonical_versions_and_graph(self):
        self.assertEqual(zeep.SLEEP_ESTIMATOR_VERSION, policy.SLEEP_ESTIMATOR_VERSION)
        self.assertEqual(
            zeep.ZEEP_SLEEP_TRANSITION_POLICY_VERSION,
            policy.ZEEP_SLEEP_TRANSITION_POLICY_VERSION,
        )
        self.assertEqual(zeep.SLEEP_STAGE_CONFIRM_TICKS, policy.SLEEP_STAGE_CONFIRM_TICKS)
        self.assertEqual(
            zeep.SLEEP_STAGE_MIN_DWELL_SECONDS,
            policy.SLEEP_STAGE_MIN_DWELL_SECONDS,
        )
        self.assertEqual(
            zeep.SLEEP_PROBABILITY_EMA_ALPHA,
            policy.SLEEP_PROBABILITY_EMA_ALPHA,
        )
        self.assertIn("rem", policy.SLEEP_ALLOWED_TRANSITIONS["n3"])
        self.assertIn("rem", policy.SLEEP_ALLOWED_TRANSITIONS["n1"])
        self.assertIn("wake", policy.SLEEP_ALLOWED_TRANSITIONS["rem"])
        self.assertEqual(zeep._sleep_decision_provenance(), {
            "estimator_version": policy.SLEEP_ESTIMATOR_VERSION,
            "evidence_version": policy.SLEEP_EVIDENCE_VERSION,
            "baseline_version": policy.ZEEP_SLEEP_BASELINE_VERSION,
            "transition_policy_version": policy.ZEEP_SLEEP_TRANSITION_POLICY_VERSION,
            "g2_ontology_version": policy.SLEEP_G2_ONTOLOGY_VERSION,
        })

    def test_historical_replay_uses_the_same_policy_objects(self):
        self.assertEqual(replay.BACKFILL_VERSION, policy.SLEEP_HISTORY_BACKFILL_VERSION)
        self.assertEqual(replay.STAGES, policy.ZEEP_SLEEP_STATES)
        self.assertEqual(
            replay.HistoricalStagePath.confirm_ticks,
            policy.SLEEP_STAGE_CONFIRM_TICKS,
        )
        self.assertEqual(
            replay.HistoricalStagePath.minimum_dwell,
            policy.SLEEP_STAGE_MIN_DWELL_SECONDS,
        )
        self.assertNotIn(("n3", "rem"), replay.PROHIBITED_TRANSITIONS)
        self.assertNotIn(("n1", "rem"), replay.PROHIBITED_TRANSITIONS)
        self.assertNotIn(("rem", "wake"), replay.PROHIBITED_TRANSITIONS)

    def test_live_and_historical_transition_guards_emit_the_same_path(self):
        with zeep.sleep_path_lock:
            previous = dict(zeep._sleep_stage_path)
            previous["seen"] = list(zeep._sleep_stage_path["seen"])
            zeep._reset_sleep_stage_path("cross-layer-transition-test")
        historical = replay.HistoricalStagePath()
        sequence = [
            ("n3", 0.0, False),
            ("n3", 15.0, False), ("n3", 20.0, False), ("n3", 25.0, False),
            ("n3", 60.0, False), ("n3", 65.0, False), ("n3", 70.0, False),
            ("n3", 140.0, False), ("n3", 145.0, False),
            ("n3", 150.0, False), ("n3", 155.0, False), ("n3", 160.0, False),
            ("rem", 240.0, False), ("rem", 245.0, False),
            ("rem", 250.0, False), ("rem", 255.0, False), ("rem", 260.0, False),
            ("wake", 300.0, False),
        ]
        try:
            for candidate, now, strong_wake in sequence:
                live_stage, live_meta = zeep._stabilize_sleep_stage(
                    candidate, now=now, strong_wake=strong_wake,
                )
                replay_stage, replay_meta = historical.stabilize(
                    candidate, now=now, strong_wake=strong_wake,
                )
                self.assertEqual(live_stage, replay_stage)
                self.assertEqual(live_meta["bridge_state"], replay_meta["bridge_state"])
                self.assertEqual(live_meta["held"], replay_meta["held"])
                with zeep.sleep_path_lock:
                    zeep._apply_stage_to_path(live_stage, now=now)
                historical.commit(replay_stage, now)
        finally:
            with zeep.sleep_path_lock:
                zeep._sleep_stage_path.clear()
                zeep._sleep_stage_path.update(previous)

    def test_personal_baseline_uses_canonical_health_eligibility(self):
        self.assertEqual(
            personal.MIN_SESSION_SECONDS,
            policy.PERSONAL_BASELINE_MIN_SESSION_SECONDS,
        )
        self.assertEqual(
            personal.MIN_DETECTED_SLEEP_SECONDS,
            policy.PERSONAL_BASELINE_MIN_DETECTED_SLEEP_SECONDS,
        )
        manifest = policy.sleep_policy_snapshot()["personal_baseline_learning"]
        self.assertTrue(manifest["awake_rest_sessions_excluded"])
        self.assertEqual(manifest["quality_type_required"], "sleep")

    def test_report_uses_current_versions_and_aasm_seven_hour_target(self):
        self.assertEqual(report.SLEEP_QUALITY_VERSION, policy.SLEEP_QUALITY_VERSION)
        self.assertEqual(report.SESSION_REPORT_VERSION, policy.SESSION_REPORT_VERSION)
        quality = report.build_sleep_quality(
            25_200,
            {"sleep_onset_proxy_s": 600},
            {"n2": 2520, "n3": 1512, "rem": 1008},
            rest_mode="overnight",
        )
        self.assertEqual(quality["duration_target"]["seconds"], 25_200)
        self.assertEqual(quality["architecture"]["points"]["n3"], 12.0)
        self.assertEqual(quality["component_max_points"], {
            key: value for key, value in policy.SLEEP_QUALITY_COMPONENT_MAX_POINTS.items()
        })

    def test_admin_policy_snapshot_exposes_exact_runtime_policy(self):
        snapshot = zeep.sleep_policy_admin()
        self.assertEqual(snapshot["versions"], policy.sleep_policy_snapshot()["versions"])
        self.assertEqual(snapshot["stage_presentation"], policy.SLEEP_STAGE_PRESENTATION)
        self.assertEqual(snapshot["runtime"]["analysis_interval_seconds"], 10.0)
        self.assertEqual(snapshot["runtime"]["sensor_sample_seconds"], 10.0)
        self.assertEqual(snapshot["runtime"]["evidence_epoch_seconds"], 30.0)
        self.assertEqual(snapshot["runtime"]["evidence_sensor_frames"], 3)
        self.assertEqual(snapshot["runtime"]["confirmation_seconds"], 60.0)
        self.assertEqual(snapshot["runtime"]["confirmation_epochs"], 2)
        self.assertTrue(snapshot["runtime"]["evidence_and_confirmed_state_separate"])
        self.assertEqual(snapshot["runtime"]["rolling_window_frames"], 6)
        self.assertEqual(
            snapshot["runtime"]["bed_exit_confirmation"], {
                "consecutive_analysis_buckets": 3,
                "raw_packet_minimum": 5,
                "raw_packet_ratio": 0.8,
                "raw_packet_can_confirm": False,
                "isolated_mid_session_code": "transient_rejected",
                "raw_status_retained_for_admin": True,
            },
        )
        self.assertFalse(snapshot["claim_boundary"]["aasm_psg_equivalent"])
        self.assertFalse(snapshot["claim_boundary"]["actuator_trigger"])
        self.assertEqual(snapshot["probability_filter"], {
            "method": "ema_after_60s_rolling_features",
            "alpha": 0.20,
            "candidate_switch_margin": 0.05,
            "display_winner_margin": 0.01,
            "instant_strong_wake_bypass": False,
            "strong_wake_still_requires_confirmation": True,
        })
        self.assertEqual(snapshot["classification_gate"], {
            "active_session_required": True,
            "recording_phase_required": True,
            "confirmed_occupied_bed_required": True,
            "fresh_current_hr_required": True,
            "fresh_current_rr_required": True,
            "inactive_probabilities_zero": True,
            "inactive_stage_persistence": False,
            "hold_last_stage_when_inactive": False,
            "evidence_event_type": "sleep_stage_evidence",
            "confirmed_state_event_type": "sleep_stage",
        })
        self.assertEqual(snapshot["cadence"], {
            "sensor_sample_seconds": 10.0,
            "sensor_frames_per_evidence_epoch": 3,
            "evidence_epoch_seconds": 30.0,
            "confirmation_epochs": 2,
            "confirmation_seconds": 60.0,
            "evidence_and_confirmed_state_separate": True,
            "safety_supervisor_seconds": 1.0,
        })

    def test_sleep_stage_meanings_are_consistent_across_policy_and_ui(self):
        expected = {
            "wake": ("W", "ตื่น", "ช่วงที่ระบบประเมินว่ายังตื่นหรือกลับเข้าสู่สถานะตื่น"),
            "n1": ("N1", "หลับตื้น / เคลิ้มหลับ", "เริ่มเข้าสู่การนอน ร่างกายผ่อนคลาย และปลุกให้ตื่นได้ง่าย"),
            "n2": ("N2", "หลับสนิทขึ้น / หลับตื้นต่อเนื่อง", "หัวใจและการหายใจช้าลง ร่างกายเข้าสู่การนอนที่ต่อเนื่องขึ้น"),
            "n3": ("N3", "หลับลึก / ร่างกายซ่อมแซมส่วนที่สึกหรอ", "ระยะที่หลับลึกที่สุดและสัมพันธ์กับกระบวนการฟื้นฟูร่างกาย"),
            "rem": ("REM", "หลับฝัน / สมองจัดระเบียบความจำ", "สมองทำงานมากขึ้น มักเกิดความฝัน และเกี่ยวข้องกับความจำและอารมณ์"),
        }
        ui = (PI5_ROOT / "static" / "index.html").read_text(encoding="utf-8")
        snapshot = policy.sleep_policy_snapshot()
        for state, (code, title, meaning) in expected.items():
            self.assertEqual(snapshot["stage_presentation"][state], {
                "code": code, "title": title, "meaning": meaning,
            })
            self.assertIn(f"code:'{code}'", ui)
            self.assertIn(f"title:'{title}'", ui)
            self.assertIn(f"meaning:'{meaning}'", ui)
        self.assertIn("sleepMeta.meaning", ui)
        self.assertNotIn("rem:        {code:'REM',  label:'ฝัน'", ui)

    def test_environment_context_uses_fair_floor_and_two_pilot_profiles(self):
        manifest = policy.sleep_policy_snapshot()["environment_context"]
        self.assertEqual(
            manifest["version"], policy.ENVIRONMENT_CONTEXT_POLICY_VERSION)
        self.assertEqual(manifest["acceptable_min_level"], "fair")
        self.assertFalse(manifest["direct_stage_influence"])
        self.assertFalse(manifest["changes_life_safety_thresholds"])
        for mode in policy.REST_SESSION_GROUPS:
            view = policy.environment_policy_snapshot(mode)
            self.assertEqual(view["mode"], mode)
            self.assertEqual(len(view["criteria"]), 7)
        sleep_sound = policy.environment_criterion("sound", "sleep")
        nap_sound = policy.environment_criterion(
            "sound", "recovery_readiness")
        self.assertEqual(
            nap_sound["mode"], "nap_recovery")
        ui = (PI5_ROOT / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn("พอใช้ขึ้นไปถือว่าผ่านขั้นต่ำ", ui)
        self.assertIn("metric.score<2", ui)
        self.assertNotIn("metric.score<4", ui)
        self.assertIn("environment.assessment||assessDashboardAtmosphere", ui)

    def test_policy_and_ui_expose_exactly_two_canonical_pilot_modes(self):
        self.assertEqual(set(policy.REST_SESSION_GROUPS), {
            "sleep", "nap_recovery",
        })
        self.assertEqual(set(policy.REST_MODE_PROTOCOLS), set(policy.REST_SESSION_GROUPS))
        self.assertEqual(
            policy.REST_MODE_PROTOCOLS["sleep"]["minimum_seconds"], 5 * 3600)
        self.assertEqual(
            policy.REST_MODE_PROTOCOLS["nap_recovery"]["recommended_range_seconds"],
            [25 * 60, 35 * 60],
        )
        ui = (PI5_ROOT / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn("Nap &amp; Refresh · ประมาณ 30 นาที", ui)
        self.assertIn("Overnight Recovery · พักค้างคืน", ui)
        self.assertNotIn('option value="auto"', ui)
        self.assertNotIn('option value="recovery_readiness"', ui)
        self.assertNotIn('option value="relax_meditation"', ui)
        self.assertNotIn('option value="performance_prep"', ui)
        self.assertNotIn('option value="physical_comfort"', ui)

    def test_user_and_admin_ui_describe_guarded_rem_transitions(self):
        ui = (PI5_ROOT / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn("หลักฐาน 30 วิแยกจากสถานะยืนยัน 60 วิ", ui)
        self.assertIn("REM ชนะต่อเนื่อง 2 epoch/60 วินาที", ui)
        self.assertIn("N1 → REM", ui)
        self.assertIn("REM → Wake", ui)
        self.assertNotIn("REM ต่อเนื่อง 5 รอบ", ui)

    def test_ui_and_document_do_not_render_a_stage_when_gate_is_inactive(self):
        ui = (PI5_ROOT / "static" / "index.html").read_text(encoding="utf-8")
        doc = (DOCS_ROOT / "zeep-sleep-system-current.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("sl.classification_active===true", ui)
        self.assertIn("ยังไม่จัดประเภทการนอน", ui)
        self.assertIn("probability ทั้ง 5 เป็นศูนย์", doc)

    def test_dashboard_uses_server_emitted_state_and_documents_smoothing(self):
        ui = (PI5_ROOT / "static" / "index.html").read_text(encoding="utf-8")
        doc = (DOCS_ROOT / "zeep-sleep-system-current.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("stage.key===sleep.state", ui)
        self.assertNotIn("winner.value>0", ui)
        self.assertIn("Stability EMA", ui)
        self.assertIn("EMA `alpha=0.20`", doc)

    def test_user_history_is_bound_to_authenticated_account_without_chooser(self):
        ui = (PI5_ROOT / "static" / "index.html").read_text(encoding="utf-8")
        css = (PI5_ROOT / "static" / "theme-modern.css").read_text(encoding="utf-8")
        self.assertIn("currentPrincipal?.role==='user'", ui)
        self.assertIn("currentPrincipal.account_key||currentPrincipal.email", ui)
        self.assertIn("history-self-context", ui)
        self.assertIn(
            'body[data-view="sessions"][data-role="user"] #historyToolbar',
            css,
        )
        self.assertIn("display: none !important", css)

    def test_admin_history_users_are_ordered_by_latest_session(self):
        profiles = {
            "old@example.test": {
                "account_key": "old@example.test", "display_name": "Old",
                "last_session_utc": "2026-08-20T10:00:00+00:00",
            },
            "new@example.test": {
                "account_key": "new@example.test", "display_name": "Newest completed",
                "last_session_utc": "2026-08-28T10:00:00+00:00",
            },
            "active@example.test": {
                "account_key": "active@example.test", "display_name": "Active",
                "last_session_utc": "2026-08-18T10:00:00+00:00",
            },
        }
        users = zeep._users_ordered_by_latest_session(profiles, {
            "username_key": "active@example.test",
            "started_at_utc": "2026-08-28T11:00:00+00:00",
        })
        self.assertEqual(
            [user["account_key"] for user in users],
            ["active@example.test", "new@example.test", "old@example.test"],
        )
        self.assertTrue(users[0]["has_active_session"])
        self.assertEqual(users[1]["history_order_utc"], "2026-08-28T10:00:00+00:00")

        ui = (PI5_ROOT / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn("sortHistoryUsersNewestFirst(d.users)", ui)
        self.assertIn("sessionState.account_key||sessionState.email", ui)

    def test_canonical_document_tracks_all_current_policy_versions(self):
        doc = (DOCS_ROOT / "zeep-sleep-system-current.md").read_text(encoding="utf-8")
        for version in policy.sleep_policy_snapshot()["versions"].values():
            self.assertIn(version, doc)
        self.assertIn("N3 → REM", doc)
        self.assertIn("20 + 30 + 30 + 15 + 5", doc)
        self.assertIn("25200", doc)


if __name__ == "__main__":
    unittest.main()
