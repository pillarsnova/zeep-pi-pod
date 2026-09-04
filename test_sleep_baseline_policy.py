"""Regression tests for the versioned ZEEP sleep-state baseline policy."""

import copy
import time
import unittest

from testing_support import configure_app_test_environment

configure_app_test_environment()
import app as zeep


class SleepClassificationGateTests(unittest.TestCase):
    """A machine/empty Pod must never be assigned a human Sleep Stage."""

    def setUp(self):
        with zeep.state_lock:
            self.previous_session = copy.deepcopy(zeep.state["session"])
        with zeep.history_lock:
            self.previous_features = list(zeep.sleep_feature_history)
            zeep.sleep_feature_history.clear()
        with zeep.sleep_path_lock:
            self.previous_path = copy.deepcopy(zeep._sleep_stage_path)
            zeep._reset_sleep_stage_path("gate-test")
            for stage in ("wake", "n1", "n2", "n3"):
                zeep._apply_stage_to_path(stage)

    def tearDown(self):
        with zeep.state_lock:
            zeep.state["session"].clear()
            zeep.state["session"].update(self.previous_session)
        with zeep.history_lock:
            zeep.sleep_feature_history.clear()
            zeep.sleep_feature_history.extend(self.previous_features)
        with zeep.sleep_path_lock:
            zeep._sleep_stage_path.clear()
            zeep._sleep_stage_path.update(self.previous_path)

    def set_session(self, *, active, recording):
        with zeep.state_lock:
            zeep.state["session"].update({
                "active": active,
                "recording": recording,
                "session_id": "gate-test" if active else None,
                "started_at": time.time() - 120 if recording else None,
                "account_key": None,
            })

    def add_frame(self, *, hr, rr, status=0, confirmed_status=0,
                  bcg_valid=True, exit_confirmed=False):
        now = time.time()
        with zeep.history_lock:
            zeep.sleep_feature_history.append({
                "t": now,
                "bcg_latest_t": now,
                "status": status,
                "confirmed_status": confirmed_status,
                "bed_exit_evidence": {"confirmed": exit_confirmed},
                "bcg_valid": bcg_valid,
                "hr": hr,
                "rr": rr,
                "bcg_samples": [],
                "clip_ratio": 0.0,
                "esp_fresh": False,
                "sensor_status": {},
            })

    def assert_inactive(self, result, expected_state):
        self.assertEqual(result["state"], expected_state)
        self.assertFalse(result["classification_active"])
        self.assertFalse(result["held_previous_state"])
        self.assertEqual(set(result["probabilities"]), {"wake", "n1", "n2", "n3", "rem"})
        self.assertTrue(all(value == 0.0 for value in result["probabilities"].values()))

    def test_no_session_does_not_hold_previous_n3(self):
        self.set_session(active=False, recording=False)
        result = zeep.estimate_sleep_state()
        self.assert_inactive(result, "off_bed")
        self.assertEqual(result["data_status"], "no_session")
        self.assertEqual(result["last_valid_state"], "n3")

    def test_waiting_session_does_not_classify_before_recording(self):
        self.set_session(active=True, recording=False)
        self.add_frame(hr=61.0, rr=14.0)
        result = zeep.estimate_sleep_state()
        self.assert_inactive(result, "no_data")
        self.assertEqual(result["data_status"], "waiting_for_vitals")

    def test_current_frame_requires_both_hr_and_rr(self):
        self.set_session(active=True, recording=True)
        self.add_frame(hr=None, rr=None, bcg_valid=False)
        result = zeep.estimate_sleep_state()
        self.assert_inactive(result, "no_data")
        self.assertEqual(result["data_status"], "invalid_or_missing_current_vitals")

    def test_confirmed_empty_bed_is_not_wake_or_sleep(self):
        self.set_session(active=True, recording=True)
        self.add_frame(
            hr=61.0, rr=14.0, status=1, confirmed_status=1,
            exit_confirmed=True,
        )
        result = zeep.estimate_sleep_state()
        self.assert_inactive(result, "off_bed")
        self.assertEqual(result["data_status"], "empty_bed")

    def test_startup_vital_drop_is_held_at_wake_not_n1(self):
        self.set_session(active=True, recording=True)
        with zeep.state_lock:
            zeep.state["session"]["started_at"] = time.time() - 90.0
        with zeep.sleep_path_lock:
            zeep._reset_sleep_stage_path("gate-test")
        hrs = (83.75, 76.3, 76.7, 79.7, 80.0, 80.6)
        rrs = (20.2, 16.68, 16.05, 15.51, 15.8, 17.59)
        for hr, rr in zip(hrs, rrs):
            self.add_frame(hr=hr, rr=rr)

        result = zeep.estimate_sleep_state()

        self.assertEqual(result["raw_candidate"], "wake")
        self.assertNotEqual(result["confirmed_state"], "n1")
        self.assertFalse(result["sleep_evidence"]["sleep_onset_gate"]["passed"])
        self.assertFalse(
            result["sleep_evidence"]["sleep_onset_gate"]["observation_complete"]
        )

    def test_pending_transition_result_uses_defined_candidate(self):
        """A held 60-second transition must return telemetry, not NameError."""
        self.set_session(active=True, recording=True)
        started = time.time() - 10 * 60.0
        with zeep.state_lock:
            zeep.state["session"]["started_at"] = started
        with zeep.sleep_path_lock:
            zeep._reset_sleep_stage_path("gate-test")
            zeep._sleep_stage_path["last"] = "wake"
            zeep._sleep_stage_path["stage_since"] = started
            zeep._sleep_stage_path["awake_vital_pairs"] = [
                (started + index * 10.0, 76.0, 18.0) for index in range(6)
            ]
            zeep._sleep_stage_path["awake_hr_reference"] = 76.0
            zeep._sleep_stage_path["awake_rr_reference"] = 18.0
        for _ in range(6):
            self.add_frame(hr=62.0, rr=15.0)

        result = zeep.estimate_sleep_state()

        self.assertIn(result["raw_candidate"], {"wake", "n1"})
        self.assertIn("pending_state", result["confirmation"])
        self.assertNotEqual(result["data_status"], "error")


class SleepTransitionPolicyTests(unittest.TestCase):
    def setUp(self):
        with zeep.sleep_path_lock:
            self.previous = dict(zeep._sleep_stage_path)
            self.previous["seen"] = list(zeep._sleep_stage_path["seen"])
            zeep._reset_sleep_stage_path("test-session")

    def tearDown(self):
        with zeep.sleep_path_lock:
            zeep._sleep_stage_path.update(self.previous)

    def apply(self, *stages):
        with zeep.sleep_path_lock:
            for stage in stages:
                zeep._apply_stage_to_path(stage)

    def assert_allowed(self, allowed, blocked):
        for stage in allowed:
            self.assertTrue(zeep._transition_allowed(stage)[0], stage)
        for stage in blocked:
            self.assertFalse(zeep._transition_allowed(stage)[0], stage)

    def test_new_cycle_must_publish_wake_first(self):
        self.assert_allowed({"wake"}, {"n1", "n2", "n3", "rem"})

    def test_wake_only_enters_sleep_through_n1(self):
        self.apply("wake")
        self.assert_allowed({"wake", "n1"}, {"n2", "n3", "rem"})
        for blocked in ("n2", "n3", "rem"):
            self.assertEqual(
                zeep._transition_fallback_state(blocked, "wake"), "wake")

    def test_n1_can_enter_guarded_rem_but_not_n3(self):
        self.apply("wake", "n1")
        self.assert_allowed({"wake", "n1", "n2", "rem"}, {"n3"})
        self.assertEqual(zeep._transition_fallback_state("n3", "n1"), "n1")

    def test_n2_can_enter_n3_or_rem(self):
        self.apply("wake", "n1", "n2")
        self.assert_allowed({"n1", "n2", "n3", "rem"}, {"wake"})
        self.assertEqual(zeep._transition_fallback_state("wake", "n2"), "n2")
        self.assertTrue(zeep._transition_allowed("wake", strong_wake=True)[0])

    def test_n3_can_enter_rem_and_rem_can_wake_naturally(self):
        self.apply("wake", "n1", "n2", "n3")
        self.assert_allowed({"n3", "n2", "rem"}, {"wake", "n1"})
        self.assertEqual(zeep._transition_fallback_state("wake", "n3"), "n3")
        self.assertTrue(zeep._transition_allowed("wake", strong_wake=True)[0])

        with zeep.sleep_path_lock:
            zeep._reset_sleep_stage_path("test-session")
        self.apply("wake", "n1", "n2", "rem")
        self.assert_allowed({"rem", "n2", "n1", "wake"}, {"n3"})
        self.assertTrue(zeep._transition_allowed("wake", strong_wake=True)[0])

    def test_n3_to_rem_requires_normal_dwell_and_two_evidence_epochs(self):
        with zeep.sleep_path_lock:
            zeep._reset_sleep_stage_path("test-session")
            for index, stage in enumerate(("wake", "n1", "n2", "n3")):
                zeep._apply_stage_to_path(stage, now=index * 60.0)
        for index, now in enumerate((240.0, 270.0), start=1):
            stage, meta = zeep._stabilize_sleep_stage("rem", now=now)
            self.assertEqual(meta["required_ticks"], 2)
            self.assertEqual(meta["candidate_ticks"], index)
            self.assertEqual(meta["confirmation_seconds"], 60.0)
            self.assertEqual(stage, "rem" if index == 2 else "n3")

    def test_wake_resets_n1_gate_for_the_next_cycle(self):
        self.apply("wake", "n1", "n3", "wake")
        self.assert_allowed({"wake", "n1"}, {"n2", "n3", "rem"})
        self.assertEqual(zeep._transition_fallback_state("n3", "wake"), "wake")

    def test_n1_gate_persists_for_the_whole_cycle_not_only_recent_history(self):
        self.apply("wake", "n1", "n2", "rem", "n2", "rem", "n2", "rem", "n2", "n3")
        with zeep.sleep_path_lock:
            self.assertNotIn("n1", zeep._sleep_stage_path["seen"])
            self.assertTrue(zeep._sleep_stage_path["cycle_has_n1"])
        self.assertTrue(zeep._transition_allowed("n2")[0])
        self.assertEqual(zeep._transition_fallback_state("n1", "n3"), "n3")

    def test_transition_requires_two_thirty_second_evidence_epochs(self):
        with zeep.sleep_path_lock:
            zeep._apply_stage_to_path("wake", now=0.0)
        stage, meta = zeep._stabilize_sleep_stage("n1", now=30.0)
        self.assertEqual(stage, "wake")
        self.assertTrue(meta["held"])
        stage, meta = zeep._stabilize_sleep_stage("n1", now=60.0)
        self.assertEqual(stage, "n1")
        self.assertFalse(meta["held"])
        self.assertEqual(meta["confirmation_seconds"], 60.0)

    def test_n2_transition_requires_four_evidence_epochs_and_reports_120_seconds(self):
        with zeep.sleep_path_lock:
            zeep._apply_stage_to_path("n1", now=0.0)
        for index, now in enumerate((30.0, 60.0, 90.0, 120.0), start=1):
            stage, meta = zeep._stabilize_sleep_stage("n2", now=now)
            self.assertEqual(meta["required_ticks"], 4)
            self.assertEqual(meta["confirmation_seconds"], 120.0)
            self.assertEqual(stage, "n2" if index == 4 else "n1")


class SleepContextGapTests(unittest.TestCase):
    """A transient observation gap must not manufacture a Wake cycle."""

    def setUp(self):
        with zeep.sleep_path_lock:
            self.previous = copy.deepcopy(zeep._sleep_stage_path)
            zeep._reset_sleep_stage_path("gap-continuity-test")

    def tearDown(self):
        with zeep.sleep_path_lock:
            zeep._sleep_stage_path.clear()
            zeep._sleep_stage_path.update(self.previous)

    @staticmethod
    def valid_frame(timestamp, hr=60.0, rr=15.0):
        return {
            "t": timestamp,
            "bcg_valid": True,
            "hr": hr,
            "rr": rr,
        }

    def test_transient_gap_preserves_confirmed_sleep_and_onset(self):
        with zeep.sleep_path_lock:
            zeep._apply_stage_to_path("wake", now=0.0)
            zeep._apply_stage_to_path("n1", now=30.0)
            zeep._apply_stage_to_path("n2", now=150.0)
            zeep._sleep_stage_path["sleep_onset_at"] = 30.0
            zeep._sleep_stage_path["last_valid_frame_t"] = 180.0
            zeep._sleep_stage_path["candidate"] = "rem"
            zeep._sleep_stage_path["candidate_ticks"] = 1
            zeep._sleep_stage_path["probability_ema"] = {"rem": 1.0}

        context = zeep._update_sleep_session_context(
            [self.valid_frame(300.0)], now=300.0, session_started=0.0,
        )

        self.assertTrue(context["gap_detected"])
        self.assertFalse(context["gap_reset"])
        self.assertTrue(context["context_preserved_after_gap"])
        self.assertTrue(context["sleep_onset_established"])
        with zeep.sleep_path_lock:
            self.assertEqual(zeep._sleep_stage_path["last"], "n2")
            self.assertTrue(zeep._sleep_stage_path["cycle_has_n1"])
            self.assertEqual(zeep._sleep_stage_path["sleep_onset_at"], 30.0)
            self.assertIsNone(zeep._sleep_stage_path["candidate"])
            self.assertEqual(zeep._sleep_stage_path["candidate_ticks"], 0)
            self.assertIsNone(zeep._sleep_stage_path["probability_ema"])

    def test_new_session_still_requires_wake_first(self):
        self.assertFalse(zeep._transition_allowed("n1")[0])
        self.assertTrue(zeep._transition_allowed("wake")[0])


class BaselineProximityTests(unittest.TestCase):
    def test_midpoint_breaks_overlapping_range_ties(self):
        center, detail = zeep._baseline_interval_proximity(60.0, (50.0, 70.0))
        edge, _ = zeep._baseline_interval_proximity(50.0, (50.0, 70.0))
        outside, outside_detail = zeep._baseline_interval_proximity(40.0, (50.0, 70.0))
        self.assertGreater(center, edge)
        self.assertGreater(edge, outside)
        self.assertEqual(detail["distance_to_range"], 0.0)
        self.assertEqual(outside_detail["distance_to_range"], 10.0)


class SleepProbabilityStabilityTests(unittest.TestCase):
    def test_onset_guard_holds_wake_when_n1_wins_too_early(self):
        candidate, metadata = zeep.candidate_from_stage_evidence(
            {"wake": 0.11, "n1": 0.81, "n2": 0.06, "n3": 0.01, "rem": 0.01},
            {"wake": 0.11, "n1": 0.81, "n2": 0.06, "n3": 0.01, "rem": 0.01},
            "wake",
            switch_margin=zeep.SLEEP_PROBABILITY_SWITCH_MARGIN,
            n3_gate=False,
            sleep_onset_gate_passed=False,
        )
        self.assertEqual(candidate, "wake")
        self.assertTrue(metadata["sleep_onset_guard_held"])
        self.assertEqual(metadata["candidate_source"], "sleep_onset_guard")

    def test_ema_damps_one_thirty_second_probability_jump(self):
        previous = {"wake": 0.05, "n1": 0.05, "n2": 0.15, "n3": 0.05, "rem": 0.70}
        current = {"wake": 0.05, "n1": 0.05, "n2": 0.65, "n3": 0.05, "rem": 0.20}
        smoothed = zeep.smooth_stage_probabilities(
            previous, current, alpha=zeep.SLEEP_PROBABILITY_EMA_ALPHA)
        self.assertEqual(max(smoothed, key=smoothed.get), "rem")
        self.assertAlmostEqual(smoothed["rem"], 0.60)
        self.assertAlmostEqual(smoothed["n2"], 0.25)
        self.assertAlmostEqual(sum(smoothed.values()), 1.0)

    def test_close_challenger_does_not_start_a_transition(self):
        candidate, metadata = zeep.stable_probability_candidate(
            {"wake": 0.05, "n1": 0.08, "n2": 0.40, "n3": 0.04, "rem": 0.43},
            "n2",
            switch_margin=zeep.SLEEP_PROBABILITY_SWITCH_MARGIN,
        )
        self.assertEqual(candidate, "n2")
        self.assertTrue(metadata["margin_held"])

    def test_current_gated_n3_evidence_is_not_blocked_by_display_ema(self):
        """Regression for two nights where valid N3 never escaped N2.

        The rolling evidence has already changed decisively to N3, while the
        separately published EMA still trails N2. State confirmation must
        consume the former and leave the latter as display telemetry.
        """
        current_evidence = {
            "wake": 0.034, "n1": 0.064, "n2": 0.338,
            "n3": 0.540, "rem": 0.024,
        }
        display_ema = {
            "wake": 0.0466, "n1": 0.0829, "n2": 0.4369,
            "n3": 0.4117, "rem": 0.0219,
        }

        evidence_candidate, evidence_meta = zeep.candidate_from_stage_evidence(
            current_evidence,
            display_ema,
            "n2",
            switch_margin=zeep.SLEEP_PROBABILITY_SWITCH_MARGIN,
            n3_gate=True,
        )
        display_candidate, display_meta = zeep.stable_probability_candidate(
            display_ema,
            "n2",
            switch_margin=zeep.SLEEP_PROBABILITY_SWITCH_MARGIN,
        )

        self.assertEqual(evidence_candidate, "n3")
        self.assertEqual(
            evidence_meta["candidate_source"],
            "gated_n3_current_30s_evidence_before_ema",
        )
        self.assertTrue(evidence_meta["gated_n3_current_evidence_override"])
        self.assertEqual(display_candidate, "n2")
        self.assertEqual(display_meta["filtered_winner"], "n2")
        self.assertFalse(display_meta["margin_held"])

    def test_current_n3_winner_cannot_bypass_ema_without_n3_gate(self):
        candidate, metadata = zeep.candidate_from_stage_evidence(
            {"wake": 0.034, "n1": 0.064, "n2": 0.338,
             "n3": 0.540, "rem": 0.024},
            {"wake": 0.0466, "n1": 0.0829, "n2": 0.4369,
             "n3": 0.4117, "rem": 0.0219},
            "n2",
            switch_margin=zeep.SLEEP_PROBABILITY_SWITCH_MARGIN,
            n3_gate=False,
        )
        self.assertEqual(candidate, "n2")
        self.assertFalse(metadata["gated_n3_current_evidence_override"])
        self.assertEqual(metadata["candidate_source"], "ema_probability")

    def test_ema_cannot_start_transition_when_current_gate_is_closed(self):
        candidate, metadata = zeep.candidate_from_stage_evidence(
            {"wake": 0.10, "n1": 0.10, "n2": 0.60, "n3": 0.10, "rem": 0.10},
            {"wake": 0.10, "n1": 0.10, "n2": 0.55, "n3": 0.10, "rem": 0.15},
            "n1",
            switch_margin=zeep.SLEEP_PROBABILITY_SWITCH_MARGIN,
            n3_gate=False,
            sleep_onset_gate_passed=True,
            eligible_states={
                "wake": True, "n1": True, "n2": False,
                "n3": False, "rem": False,
            },
        )
        self.assertEqual(candidate, "n1")
        self.assertTrue(metadata["closed_gate_transition_prevented"])

    def test_n3_evidence_still_needs_two_confirmation_epochs(self):
        with zeep.sleep_path_lock:
            zeep._reset_sleep_stage_path("n3-confirmation-test")
            zeep._apply_stage_to_path("wake", now=-120.0)
            zeep._apply_stage_to_path("n1", now=-90.0)
            zeep._apply_stage_to_path("n2", now=0.0)
        stage, first = zeep._stabilize_sleep_stage("n3", now=60.0)
        self.assertEqual(stage, "n2")
        self.assertTrue(first["held"])
        stage, second = zeep._stabilize_sleep_stage("n3", now=90.0)
        self.assertEqual(stage, "n3")
        self.assertFalse(second["held"])

    def test_emitted_stage_is_winner_without_zeroing_challenger(self):
        visible = zeep.align_probabilities_to_emitted_stage(
            {"wake": 0.05, "n1": 0.08, "n2": 0.30, "n3": 0.07, "rem": 0.50},
            "n2",
            winner_margin=zeep.SLEEP_DISPLAY_WINNER_MARGIN,
        )
        self.assertEqual(max(visible, key=visible.get), "n2")
        self.assertGreater(visible["rem"], 0.0)
        self.assertAlmostEqual(sum(visible.values()), 1.0)

    def test_new_session_clears_probability_memory(self):
        with zeep.sleep_path_lock:
            previous = copy.deepcopy(zeep._sleep_stage_path)
            try:
                zeep._sleep_stage_path["probability_ema"] = {"rem": 1.0}
                zeep._reset_sleep_stage_path("new-session")
                self.assertIsNone(zeep._sleep_stage_path["probability_ema"])
            finally:
                zeep._sleep_stage_path.clear()
                zeep._sleep_stage_path.update(previous)


class SleepStageWeightingTests(unittest.TestCase):
    def test_rr_baseline_weight_is_raised_without_overtaking_hr(self):
        self.assertEqual(zeep.SLEEP_BASELINE_HR_WEIGHT, 0.50)
        self.assertEqual(zeep.SLEEP_BASELINE_RR_WEIGHT, 0.40)
        self.assertEqual(zeep._physiological_baseline_fit(1.0, 1.0), 0.90)

    def test_n2_like_rr_resists_false_n3(self):
        baseline = zeep.AGE_SLEEP_BASELINES["18-29"]
        rr_n2, _ = zeep._baseline_interval_proximity(17.1, baseline["n2"]["rr"])
        rr_n3, _ = zeep._baseline_interval_proximity(17.1, baseline["n3"]["rr"])
        guard = zeep._rr_n3_conflict_adjustment({"n2": rr_n2, "n3": rr_n3})
        self.assertGreater(guard["conflict"], 0.0)
        self.assertGreater(guard["n3_penalty"], guard["n2_support"])

    def test_rr_centered_on_n3_adds_no_conflict_penalty(self):
        baseline = zeep.AGE_SLEEP_BASELINES["18-29"]
        rr_n2, _ = zeep._baseline_interval_proximity(13.0, baseline["n2"]["rr"])
        rr_n3, _ = zeep._baseline_interval_proximity(13.0, baseline["n3"]["rr"])
        guard = zeep._rr_n3_conflict_adjustment({"n2": rr_n2, "n3": rr_n3})
        self.assertEqual(guard["conflict"], 0.0)
        self.assertEqual(guard["n3_penalty"], 0.0)


class AnalysisFrameTests(unittest.TestCase):
    def test_three_sensor_frames_publish_one_thirty_second_sleep_epoch(self):
        original_estimator = zeep.estimate_sleep_state
        with zeep.analysis_frame_lock:
            original_frame = zeep._analysis_frame
            original_cache = dict(zeep._sleep_cache)
        with zeep.state_lock:
            original_session = copy.deepcopy(zeep.state["session"])
            zeep.state["session"].update({
                "session_id": "frame-test", "active": True, "recording": True,
            })
        with zeep.sleep_path_lock:
            original_path = copy.deepcopy(zeep._sleep_stage_path)
            zeep._reset_sleep_stage_path("frame-test")
        zeep.estimate_sleep_state = lambda: {"state": "n2", "probabilities": {"n2": 1.0}}
        try:
            for timestamp in (100.0, 110.0, 120.0):
                zeep._publish_analysis_frame(
                    {
                        "t": timestamp, "status": 3, "hr": 61.0, "rr": 14.0,
                        "bcg_frames": 2, "bcg_valid": True,
                        "bcg_latest_t": timestamp - 0.5,
                    },
                    {"temperature_c": 23.5, "humidity_rh": 52.0},
                    {"connected": True},
                )
            frame = zeep.analysis_frame_cached()
            self.assertEqual(frame["refresh_s"], 10.0)
            self.assertEqual(frame["evidence_refresh_s"], 30.0)
            self.assertEqual(frame["confirmation_s"], 60.0)
            self.assertEqual(frame["sequence"], 12)
            self.assertEqual(frame["session_id"], "frame-test")
            self.assertEqual(frame["environment"]["temperature_c"], 23.5)
            self.assertEqual(frame["bcg"]["heart_rate_bpm"], 61.0)
            self.assertEqual(frame["sleep"]["state"], "n2")
            self.assertTrue(frame["sleep"]["evidence_epoch_due"])
        finally:
            zeep.estimate_sleep_state = original_estimator
            with zeep.state_lock:
                zeep.state["session"].clear()
                zeep.state["session"].update(original_session)
            with zeep.sleep_path_lock:
                zeep._sleep_stage_path.clear()
                zeep._sleep_stage_path.update(original_path)
            with zeep.analysis_frame_lock:
                zeep._analysis_frame = original_frame
                zeep._sleep_cache.clear()
                zeep._sleep_cache.update(original_cache)


class EnvironmentContextTests(unittest.TestCase):
    def test_all_factors_inside_target_give_full_support(self):
        context = zeep._sleep_environment_context({
            "temperature_c": 24.0,
            "humidity_rh": 50.0,
            "co2_ppm": 700.0,
            "lux": 1.0,
            "sound_dba": 35.0,
            "pm2_5_ug_m3": 8.0,
            "voc_index": 100.0,
        })
        self.assertEqual(context["available_factors"], 7)
        self.assertEqual(context["coverage_percent"], 100.0)
        self.assertEqual(context["sleep_support_score"], 100)
        self.assertEqual(context["wake_prior"], 0.0)

    def test_environment_disruption_never_changes_a_stage_score(self):
        context = zeep._sleep_environment_context({
            "temperature_c": 32.0,
            "humidity_rh": 80.0,
            "co2_ppm": 1600.0,
            "lux": 100.0,
            "sound_dba": 60.0,
            "pm2_5_ug_m3": 50.0,
            "voc_index": 300.0,
        })
        self.assertGreater(context["disruption_index"], 0.7)
        self.assertLess(context["sleep_support_score"], 30)
        self.assertGreater(context["required_count"], 0)
        self.assertFalse(context["direct_stage_influence"])
        self.assertEqual(context["wake_prior"], 0.0)

    def test_missing_sensors_reduce_coverage_without_fabricating_values(self):
        context = zeep._sleep_environment_context({})
        self.assertEqual(context["available_factors"], 0)
        self.assertEqual(context["coverage_percent"], 0.0)
        self.assertIsNone(context["disruption_index"])
        self.assertIsNone(context["sleep_support_score"])
        self.assertEqual(context["wake_prior"], 0.0)

    def test_light_and_sound_context_changes_by_mode_but_never_sleep_state(self):
        values = {
            "temperature_c": 24.0, "humidity_rh": 50.0,
            "co2_ppm": 700.0, "lux": 200.0, "sound_dba": 48.0,
            "pm2_5_ug_m3": 8.0, "voc_index": 100.0,
        }
        sleep = zeep._sleep_environment_context(values, "sleep")
        readiness = zeep._sleep_environment_context(values, "recovery_readiness")
        self.assertGreater(readiness["sleep_support_score"], sleep["sleep_support_score"])
        self.assertEqual(sleep["wake_prior"], 0.0)
        self.assertEqual(readiness["wake_prior"], 0.0)
        self.assertFalse(sleep["direct_stage_influence"])
        self.assertFalse(readiness["direct_stage_influence"])


class AuxiliaryEvidenceTests(unittest.TestCase):
    @staticmethod
    def frame(sound=60.0, *, dynamic=False, statuses=(0,)):
        return {
            "sound_leq_dba": sound,
            "sound_large_step": dynamic,
            "status_codes_seen": list(statuses),
        }

    def test_loud_sound_alone_cannot_support_wake(self):
        evidence = zeep._sleep_auxiliary_evidence(
            [self.frame() for _ in range(6)],
            [0] * 6,
            0.0,
            {"bcg_amplitude_shift_ratio": 0.02},
        )
        self.assertTrue(evidence["acoustic"]["disturbance_detected"])
        self.assertFalse(evidence["acoustic"]["bcg_or_motion_corroborated"])
        self.assertEqual(evidence["corroborated_acoustic_wake_support"], 0.0)

    def test_sound_plus_bcg_shift_is_bounded_wake_corroboration(self):
        evidence = zeep._sleep_auxiliary_evidence(
            [self.frame() for _ in range(6)],
            [0] * 6,
            0.0,
            {"bcg_amplitude_shift_ratio": 0.15},
        )
        self.assertTrue(evidence["acoustic"]["bcg_or_motion_corroborated"])
        self.assertEqual(
            evidence["corroborated_acoustic_wake_support"],
            zeep.SLEEP_ACOUSTIC_WAKE_SUPPORT_MAX,
        )

    def test_vendor_respiratory_flags_are_context_not_stage_evidence(self):
        frames = [self.frame(sound=40.0) for _ in range(4)]
        frames += [self.frame(sound=40.0, statuses=(0, 3)),
                   self.frame(sound=40.0, statuses=(0, 5))]
        evidence = zeep._sleep_auxiliary_evidence(
            frames, [0] * 6, 0.0, {"bcg_amplitude_shift_ratio": 0.0})
        self.assertEqual(evidence["bed_status"]["weak_breathing_frames"], 1)
        self.assertEqual(evidence["bed_status"]["snoring_frames"], 1)
        self.assertFalse(evidence["bed_status"]["weak_breathing_is_diagnostic"])
        self.assertFalse(evidence["bed_status"]["snoring_is_stage_evidence"])


if __name__ == "__main__":
    unittest.main()
