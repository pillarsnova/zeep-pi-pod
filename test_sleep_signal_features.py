import base64
import json
import math
import sqlite3
import struct
import unittest

from sleep_signal_features import (
    HR_SANITY_RANGE_BPM,
    RR_SANITY_RANGE_PER_MIN,
    arousal_proxy_evidence,
    bed_exit_event_summary,
    bed_exit_window_evidence,
    coefficient_of_variation,
    decode_bcg_samples,
    debounced_bed_status_labels,
    filter_vital_values,
    linear_slope_per_minute,
    movement_window_metrics,
    sleep_classification_gap_controls,
    sleep_classification_gap_timeline,
    sleep_movement_evidence,
    summary_features,
    terminal_occupancy_timeline,
    terminal_wake_transition,
    waveform_features,
)
from sleep_stage_scoring import (
    evidence_candidate_with_abstention,
    score_sleep_evidence,
)


class SignalFeatureTests(unittest.TestCase):
    def test_decodes_one_raw_packet(self):
        samples = list(range(-12, 13))
        encoded = base64.b64encode(struct.pack("<25h", *samples)).decode("ascii")
        self.assertEqual(decode_bcg_samples(encoded), samples)
        self.assertEqual(decode_bcg_samples("broken"), [])

    def test_linear_trend_reports_units_per_minute(self):
        # -0.5 per five seconds = -6 units per minute.
        self.assertAlmostEqual(linear_slope_per_minute([60, 59.5, 59, 58.5]), -6.0)
        features = summary_features([60, 59.5, 59, 58.5], [18, 17.8, 17.6, 17.4])
        self.assertLess(features["hr_slope_bpm_per_min"], 0)
        self.assertLess(features["rr_slope_per_min"], 0)

    def test_malformed_and_out_of_range_vitals_are_removed_before_scoring(self):
        self.assertEqual(
            filter_vital_values([None, "bad", float("nan"), -1, 24, 25, 80, 221],
                                HR_SANITY_RANGE_BPM),
            [25.0, 80.0],
        )
        self.assertEqual(
            filter_vital_values([0, 1, 2, 18, 60, 61], RR_SANITY_RANGE_PER_MIN),
            [2.0, 18.0, 60.0],
        )
        self.assertIsNone(coefficient_of_variation([None, "bad", float("inf")]))

    def test_brief_on_bed_motion_is_not_an_arousal_or_wake_by_itself(self):
        proxy = arousal_proxy_evidence({
            "bcg_amplitude_shift_ratio": 0.0,
            "movement_ratio": 0.167,
            "max_moving_run_frames": 2,
            "movement_burst_count": 1,
            "bed_status": "Moving",
        })
        self.assertFalse(proxy["present"])
        self.assertTrue(proxy["movement"]["sleep_compatible"])
        self.assertEqual(
            proxy["movement"]["category"],
            "position_change_or_blanket_adjustment_candidate",
        )
        self.assertFalse(proxy["validated_cortical_arousal"])

    def test_sustained_motion_needs_vital_and_waveform_corroboration_for_wake(self):
        motion_only = sleep_movement_evidence({
            "movement_ratio": 0.5,
            "max_moving_run_frames": 4,
            "hr_slope_bpm_per_min": 0.2,
            "rr_slope_per_min": 0.1,
            "bcg_amplitude_shift_ratio": 0.2,
            "bed_status": "Moving",
        })
        corroborated = sleep_movement_evidence({
            "movement_ratio": 0.5,
            "max_moving_run_frames": 4,
            "hr_slope_bpm_per_min": 2.5,
            "rr_slope_per_min": 0.1,
            "bcg_amplitude_shift_ratio": 0.2,
            "bed_status": "Moving",
        })
        self.assertFalse(motion_only["strong_wake"])
        self.assertTrue(motion_only["sleep_compatible"])
        self.assertTrue(corroborated["strong_wake"])
        self.assertFalse(corroborated["anatomy_determined"])
        self.assertFalse(corroborated["blanket_motion_determined"])

    def test_movement_window_preserves_burst_shape(self):
        window = movement_window_metrics([0, 2, 2, 0, 2, 0])
        self.assertEqual(window["moving_frames"], 3)
        self.assertEqual(window["max_moving_run_frames"], 2)
        self.assertEqual(window["movement_burst_count"], 2)

    def test_bed_exit_remains_direct_wake_evidence(self):
        movement = sleep_movement_evidence({
            "movement_ratio": 0.0,
            "bed_status": "Get out of bed",
        })
        self.assertTrue(movement["strong_wake"])
        self.assertEqual(movement["category"], "bed_exit")

    def test_single_bed_exit_packet_is_rejected_as_transient(self):
        evidence = bed_exit_window_evidence(
            [0, 1], latest_raw_exit_frames=1, latest_raw_total_frames=5)
        self.assertFalse(evidence["confirmed"])
        self.assertTrue(evidence["transient_rejected"])

    def test_bed_exit_confirms_by_three_analysis_buckets(self):
        by_time = bed_exit_window_evidence(
            [0, 1, 1, 1], latest_raw_exit_frames=1, latest_raw_total_frames=5)
        self.assertEqual(by_time["confirmed_by"], "consecutive_buckets")

    def test_raw_packet_confirmation_is_disabled_by_default(self):
        by_packets = bed_exit_window_evidence(
            [0, 1], latest_raw_exit_frames=5, latest_raw_total_frames=5)
        self.assertFalse(by_packets["confirmed"])
        self.assertFalse(by_packets["raw_packet_confirmation_enabled"])

        by_packets = bed_exit_window_evidence(
            [0, 1],
            latest_raw_exit_frames=5,
            latest_raw_total_frames=5,
            raw_packet_confirmation_enabled=True,
        )
        self.assertEqual(by_packets["confirmed_by"], "raw_packet_majority")

    def test_three_second_false_exit_pattern_is_rejected(self):
        evidence = bed_exit_window_evidence(
            [0, 1], latest_raw_exit_frames=3, latest_raw_total_frames=5)
        self.assertFalse(evidence["confirmed"])
        self.assertTrue(evidence["transient_rejected"])

    def test_terminal_session_boundary_preserves_single_final_exit(self):
        evidence = bed_exit_window_evidence(
            [0, 1],
            latest_raw_exit_frames=1,
            latest_raw_total_frames=5,
            terminal_session_boundary=True,
        )
        self.assertTrue(evidence["confirmed"])
        self.assertEqual(evidence["confirmed_by"], "terminal_session_boundary")

    def test_report_counts_terminal_exit_but_ignores_isolated_mid_session_code(self):
        summary = bed_exit_event_summary([
            "On bed", "Get out of bed", "On bed", "Get out of bed",
        ])
        self.assertEqual(summary["event_count"], 1)
        self.assertEqual(summary["confirmed_samples"], 1)
        self.assertEqual(summary["transient_samples"], 1)
        self.assertEqual(debounced_bed_status_labels([
            "On bed", "Get out of bed", "On bed", "Get out of bed",
        ]), ["On bed", "On bed", "On bed", "Get out of bed"])

    def test_report_rejects_two_bucket_mid_session_exit_pulse(self):
        labels = [
            "On bed", "Get out of bed", "Get out of bed", "On bed",
        ]
        summary = bed_exit_event_summary(labels)
        self.assertEqual(summary["event_count"], 0)
        self.assertEqual(summary["transient_samples"], 2)
        self.assertEqual(
            debounced_bed_status_labels(labels),
            ["On bed", "On bed", "On bed", "On bed"],
        )

    def test_terminal_exit_is_separate_from_sleep_stage(self):
        rows = [
            {"t": 100, "hr": 72, "rr": 14, "bed": "On bed"},
            {"t": 105, "hr": None, "rr": None, "bed": "Moving"},
            {"t": 110, "hr": None, "rr": None, "bed": "On bed"},
            {"t": 115, "hr": None, "rr": None, "bed": "Get out of bed"},
            {"t": 120, "hr": None, "rr": None, "bed": "Get out of bed"},
            {"t": 125, "hr": None, "rr": None, "bed": "Get out of bed"},
            # A bag or blanket can make the unloaded Sensor change label after
            # the exit; no returning HR/RR keeps the terminal exit latched.
            {"t": 130, "hr": None, "rr": None, "bed": "Heavy object on bed"},
        ]
        periods = terminal_occupancy_timeline(
            rows, session_end=140, sample_interval_s=5,
        )
        self.assertEqual(
            [period["state"] for period in periods],
            ["no_user_on_bed", "exited_zeep"],
        )
        self.assertEqual(periods[0]["start_time"], "1970-01-01T00:01:40+00:00")
        self.assertEqual(periods[0]["end_time"], "1970-01-01T00:01:50+00:00")
        self.assertEqual(periods[1]["start_time"], "1970-01-01T00:01:50+00:00")
        self.assertEqual(periods[1]["end_time"], "1970-01-01T00:02:20+00:00")
        self.assertTrue(all(not period["sleep_stage"] for period in periods))

    def test_missing_vitals_without_confirmed_exit_is_not_occupancy_truth(self):
        rows = [
            {"t": 100, "hr": 72, "rr": 14, "bed": "On bed"},
            {"t": 105, "hr": None, "rr": None, "bed": "Moving"},
            {"t": 110, "hr": None, "rr": None, "bed": "On bed"},
        ]
        self.assertEqual(
            terminal_occupancy_timeline(rows, session_end=115),
            [],
        )

    def test_vitals_return_after_exit_pulse_rejects_terminal_latch(self):
        rows = [
            {"t": 100, "hr": 72, "rr": 14, "bed": "On bed"},
            {"t": 105, "hr": None, "rr": None, "bed": "Get out of bed"},
            {"t": 110, "hr": None, "rr": None, "bed": "Get out of bed"},
            {"t": 115, "hr": None, "rr": None, "bed": "Get out of bed"},
            {"t": 120, "hr": 74, "rr": 15, "bed": "On bed"},
        ]
        self.assertEqual(
            terminal_occupancy_timeline(rows, session_end=125),
            [],
        )

    def test_terminal_exit_accepts_sqlite_rows_without_alias_columns(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        connection.execute(
            "CREATE TABLE timeline(timestamp REAL,heart_rate REAL,"
            "respiration_rate REAL,bed_status TEXT)"
        )
        connection.executemany(
            "INSERT INTO timeline VALUES(?,?,?,?)",
            [
                (100, 72, 14, "On bed"),
                (105, None, None, "Get out of bed"),
                (110, None, None, "Get out of bed"),
                (115, None, None, "Get out of bed"),
            ],
        )
        try:
            rows = connection.execute("SELECT * FROM timeline ORDER BY timestamp")
            periods = terminal_occupancy_timeline(rows, session_end=120)
        finally:
            connection.close()
        self.assertEqual([item["state"] for item in periods], ["exited_zeep"])

    def test_terminal_wake_closes_sleep_sequence_before_bed_exit(self):
        occupancy = [{
            "state": "exited_zeep",
            "start_time": "2026-08-29T02:00:00+00:00",
        }]
        marker = terminal_wake_transition(
            [{"state": "n2"}, {"state": "rem"}],
            terminal_occupancy=occupancy,
            session_end="2026-08-29T02:01:00+00:00",
            end_reason="logout",
        )
        self.assertIsNotNone(marker)
        self.assertEqual(marker["state"], "wake")
        self.assertEqual(marker["previous_state"], "rem")
        self.assertEqual(marker["start_time"], occupancy[0]["start_time"])
        self.assertEqual(marker["duration_s"], 0.0)
        self.assertEqual(marker["decision_kind"], "terminal_wake_boundary")
        self.assertTrue(marker["excluded_from_stage_statistics"])
        self.assertFalse(marker["aasm_psg_equivalent"])

    def test_terminal_wake_uses_explicit_end_without_bed_exit(self):
        marker = terminal_wake_transition(
            [{"state": "n3"}],
            session_end=120,
            end_reason="admin_end_session",
        )
        self.assertIsNotNone(marker)
        self.assertEqual(marker["start_time"], "1970-01-01T00:02:00+00:00")
        self.assertEqual(marker["confirmed_by"], "explicit_session_end")

    def test_terminal_wake_does_not_duplicate_real_wake_or_invent_stage(self):
        self.assertIsNone(terminal_wake_transition(
            [{"state": "n2"}, {"state": "wake"}],
            session_end=120,
        ))
        self.assertIsNone(terminal_wake_transition(
            [{"state": None}, {"state": "off_bed"}],
            session_end=120,
        ))

    def test_report_exposes_off_bed_gap_without_creating_sleep_stage(self):
        periods = [
            {"state": "n2", "start_time": 100, "end_time": 110},
            {"state": "n1", "start_time": 150, "end_time": 160},
        ]
        samples = [
            {"t": t, "hr": None, "rr": None, "bed": "Get out of bed"}
            for t in (110, 120, 130, 140)
        ]
        gaps = sleep_classification_gap_timeline(
            periods,
            samples,
            session_start=100,
            classification_end=160,
            sensor_sample_interval_s=10,
        )
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0]["state"], "off_bed")
        self.assertEqual(gaps[0]["duration_s"], 40.0)
        self.assertEqual(gaps[0]["decision_kind"], "classification_gap")
        self.assertEqual(gaps[0]["coverage"]["off_bed_rows"], 4)
        self.assertFalse(gaps[0]["sleep_stage"])
        self.assertTrue(gaps[0]["excluded_from_score"])

    def test_report_labels_vital_or_sensor_gap_instead_of_hiding_time(self):
        periods = [{"state": "wake", "start_time": 120, "end_time": 130}]
        missing_vitals = sleep_classification_gap_timeline(
            periods,
            [
                {"t": 100, "hr": None, "rr": None, "bed": "On bed"},
                {"t": 110, "hr": None, "rr": None, "bed": "Moving"},
            ],
            session_start=100,
            classification_end=130,
            sensor_sample_interval_s=10,
        )
        self.assertEqual(missing_vitals[0]["state"], "no_data")
        self.assertEqual(
            missing_vitals[0]["data_status"], "missing_current_vitals")

        sensor_gap = sleep_classification_gap_timeline(
            periods,
            [],
            session_start=90,
            classification_end=130,
            sensor_sample_interval_s=10,
        )
        self.assertEqual(sensor_gap[0]["state"], "sensor_gap")
        self.assertEqual(sensor_gap[0]["coverage"]["sensor_rows"], 0)

    def test_report_does_not_add_noise_for_short_decision_gap(self):
        gaps = sleep_classification_gap_timeline(
            [
                {"state": "n2", "start_time": 100, "end_time": 120},
                {"state": "n3", "start_time": 130, "end_time": 150},
            ],
            [],
            session_start=100,
            classification_end=150,
            sensor_sample_interval_s=10,
        )
        self.assertEqual(gaps, [])

    def test_report_holds_previous_stage_across_service_restart_for_display(self):
        gaps = sleep_classification_gap_timeline(
            [
                {"state": "n2", "start_time": 100, "end_time": 120},
                {"state": "n1", "start_time": 160, "end_time": 180},
            ],
            [],
            session_start=100,
            classification_end=180,
            sensor_sample_interval_s=10,
            service_pause_times=[121],
            service_resume_times=[158],
        )
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0]["state"], "restart_hold")
        self.assertEqual(gaps[0]["held_state"], "n2")
        self.assertTrue(gaps[0]["held_previous_state"])
        self.assertEqual(
            gaps[0]["data_status"], "service_restart_hold")
        self.assertFalse(gaps[0]["sleep_stage"])
        self.assertTrue(gaps[0]["excluded_from_score"])

    def test_report_keeps_first_wait_even_if_restart_marker_exists(self):
        gaps = sleep_classification_gap_timeline(
            [{"state": "wake", "start_time": 140, "end_time": 160}],
            [],
            session_start=100,
            classification_end=160,
            sensor_sample_interval_s=10,
            service_pause_times=[110],
            service_resume_times=[130],
        )
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0]["state"], "sensor_gap")
        self.assertFalse(gaps[0]["held_previous_state"])

    def test_operational_annotation_holds_later_gaps_with_audit(self):
        controls = sleep_classification_gap_controls([{
            "type": "classification_gap_annotation",
            "timestamp": "2026-09-05T00:00:00+00:00",
            "value": json.dumps({
                "policy": "hold_previous_confirmed_state",
                "scope": "after_initial_wait",
                "display_only": True,
            }),
        }])
        gaps = sleep_classification_gap_timeline(
            [
                {"state": "wake", "start_time": 130, "end_time": 150},
                {"state": "n1", "start_time": 180, "end_time": 200},
            ],
            [],
            session_start=100,
            classification_end=200,
            sensor_sample_interval_s=10,
            **controls,
        )
        self.assertEqual([gap["state"] for gap in gaps], [
            "sensor_gap", "restart_hold",
        ])
        self.assertEqual(gaps[1]["held_state"], "wake")
        self.assertEqual(
            gaps[1]["operational_hold_source"],
            "session_operational_annotation",
        )

    def test_tiny_bcg_shift_is_not_arousal_proxy_evidence(self):
        proxy = arousal_proxy_evidence({
            "bcg_amplitude_shift_ratio": 0.01,
            "movement_ratio": 0.0,
            "bed_status": "On bed",
        })
        self.assertFalse(proxy["present"])
        self.assertEqual(proxy["thresholds"]["bcg_amplitude_shift_ratio"], 0.12)

    def test_regular_sine_is_more_ordered_than_multi_frequency_signal(self):
        sample_rate = 25
        seconds = 60
        regular = [int(1500 * math.sin(2 * math.pi * 0.25 * i / sample_rate))
                   for i in range(sample_rate * seconds)]
        mixed = [int(
            900 * math.sin(2 * math.pi * 0.17 * i / sample_rate)
            + 900 * math.sin(2 * math.pi * 0.31 * i / sample_rate)
            + 600 * math.sin(2 * math.pi * 0.43 * i / sample_rate)
        ) for i in range(sample_rate * seconds)]
        regular_features = waveform_features(regular)
        mixed_features = waveform_features(mixed)
        self.assertTrue(regular_features["waveform_available"])
        self.assertGreater(regular_features["resp_regularity"], mixed_features["resp_regularity"])
        self.assertLess(regular_features["resp_spectral_entropy"], mixed_features["resp_spectral_entropy"])
        self.assertIn("bcg_baseline_drift_ratio", regular_features)


class ScoringGuardTests(unittest.TestCase):
    @staticmethod
    def score(metrics, elapsed=100):
        fits = {
            "wake": 0.4, "n1": 0.6, "n2": 0.9, "n3": 0.95, "rem": 0.8,
        }
        scores, evidence = score_sleep_evidence(
            base_scores=fits,
            hr_fits=fits,
            rr_fits=fits,
            metrics={
                "mean_hr": 58.0,
                "mean_rr": 13.0,
                "awake_hr_reference": 72.0,
                "awake_rr_reference": 17.0,
                "current_stage": "n2",
                "sleep_onset_established": True,
                "sleep_elapsed_min": elapsed,
                "waveform_available": True,
                "bcg_amplitude_shift_ratio": 0.05,
                **metrics,
            },
            elapsed_min=elapsed,
            rem_variability_weight=1.0,
            n3_rr_conflict_penalty=1.2,
            n2_rr_conflict_support=0.3,
            move_wake_ratio=0.15,
            move_deep_ratio=0.05,
        )
        return scores, evidence

    def test_rem_needs_quiet_irregular_respiration_after_45_minutes(self):
        _, blocked = self.score({
            "hr_cv": 0.02, "rr_cv": 0.03, "movement_ratio": 0.0,
            "resp_spectral_entropy": 0.6,
        })
        _, allowed = self.score({
            "hr_cv": 0.03, "rr_cv": 0.06, "movement_ratio": 0.0,
            "resp_spectral_entropy": 0.6,
        })
        self.assertFalse(blocked["rem_gate"])
        self.assertTrue(allowed["rem_gate"])
        self.assertFalse(allowed["ibi_hrv_available"])

    def test_n3_needs_regular_respiration_and_low_variability(self):
        _, rejected = self.score({
            "hr_cv": 0.02, "rr_cv": 0.03, "movement_ratio": 0.0,
            "resp_regularity": 0.45, "waveform_available": True,
        })
        _, accepted = self.score({
            "hr_cv": 0.015, "rr_cv": 0.025, "movement_ratio": 0.0,
            "resp_regularity": 0.75, "waveform_available": True,
        })
        self.assertFalse(rejected["n3_gate"])
        self.assertTrue(accepted["n3_gate"])

    def test_acoustic_support_is_bounded_and_only_changes_wake(self):
        common = {
            "hr_cv": 0.03, "rr_cv": 0.04, "movement_ratio": 0.0,
            "resp_regularity": 0.6, "waveform_available": True,
        }
        baseline, _ = self.score(common)
        supported, evidence = self.score({
            **common,
            "corroborated_acoustic_wake_support": 999.0,
        })
        self.assertGreater(supported["wake"], baseline["wake"])
        self.assertLessEqual(supported["wake"] - baseline["wake"], 0.05)
        for stage in ("n1", "n2", "n3", "rem"):
            self.assertAlmostEqual(supported[stage], baseline[stage])
        self.assertEqual(evidence["corroborated_acoustic_wake_support"], 0.35)
        self.assertFalse(evidence["environment_direct_stage_influence"])

    def test_brief_motion_does_not_add_wake_score(self):
        common = {
            "hr_cv": 0.03, "rr_cv": 0.04,
            "resp_regularity": 0.6, "waveform_available": True,
            "bed_status": "Moving",
        }
        quiet, _ = self.score({**common, "movement_ratio": 0.0})
        brief, evidence = self.score({
            **common,
            "movement_ratio": 0.167,
            "max_moving_run_frames": 2,
            "movement_burst_count": 1,
        })
        self.assertAlmostEqual(brief["wake"], quiet["wake"])
        self.assertTrue(evidence["movement"]["sleep_compatible"])

    def test_initial_acquisition_drop_cannot_create_n1(self):
        scores, evidence = self.score({
            "current_stage": "wake",
            "sleep_onset_established": False,
            "hr_cv": 0.0434,
            "rr_cv": 0.1035,
            "movement_ratio": 0.0,
            "hr_slope_bpm_per_min": -21.15,
            "rr_slope_per_min": -12.45,
            "bcg_amplitude_shift_ratio": 0.0345,
            "waveform_available": True,
        }, elapsed=0.35)
        self.assertFalse(evidence["sleep_onset_gate"]["passed"])
        self.assertFalse(evidence["sleep_onset_gate"]["observation_complete"])
        self.assertEqual(evidence["n1_transition_support"], 0.0)
        self.assertGreater(scores["wake"], scores["n1"])

    def test_onset_needs_quiet_downward_evidence_after_observation(self):
        common = {
            "hr_cv": 0.03,
            "rr_cv": 0.035,
            "hr_slope_bpm_per_min": -2.0,
            "rr_slope_per_min": -0.5,
            "resp_regularity": 0.60,
            "waveform_available": True,
        }
        _, quiet = self.score({**common, "movement_ratio": 0.0}, elapsed=6.0)
        _, moving = self.score({
            **common,
            "movement_ratio": 0.5,
            "max_moving_run_frames": 3,
        }, elapsed=6.0)
        self.assertTrue(quiet["sleep_onset_gate"]["passed"])
        self.assertFalse(moving["sleep_onset_gate"]["passed"])
        self.assertFalse(moving["sleep_onset_gate"]["quiet_bed"])

        _, flat_after_drop = self.score({
            **common,
            "movement_ratio": 0.0,
            "hr_slope_bpm_per_min": 0.0,
            "rr_slope_per_min": 0.0,
            "awake_hr_reference": 72.0,
            "mean_hr": 66.0,
        }, elapsed=20.0)
        self.assertTrue(flat_after_drop["sleep_onset_gate"]["passed"])
        self.assertTrue(
            flat_after_drop["sleep_onset_gate"]["level_shift_onset_passed"]
        )
        self.assertEqual(
            flat_after_drop["sleep_onset_gate"]["accepted_path"],
            "sustained_relative_drop",
        )

        _, hr_only_drop = self.score({
            **common,
            "mean_hr": 66.0,
            "mean_rr": 18.0,
            "movement_ratio": 0.0,
            "hr_slope_bpm_per_min": 0.0,
            "rr_slope_per_min": 0.0,
        }, elapsed=20.0)
        self.assertTrue(hr_only_drop["sleep_onset_gate"]["passed"])
        self.assertGreater(
            hr_only_drop["sleep_onset_gate"]["relative_sleep_support_weighted"],
            hr_only_drop["sleep_onset_gate"]["minimum_relative_sleep_support"],
        )
        self.assertEqual(
            hr_only_drop["sleep_onset_gate"]["relative_sleep_support_concordant"],
            0.0,
        )
        self.assertFalse(hr_only_drop["sleep_onset_gate"]["rr_rate_drop_required"])

        _, flat_quiet_wake = self.score({
            **common,
            "mean_hr": 72.0,
            "mean_rr": 17.0,
            "movement_ratio": 0.0,
            "hr_slope_bpm_per_min": 0.0,
            "rr_slope_per_min": 0.0,
        }, elapsed=20.0)
        self.assertFalse(flat_quiet_wake["sleep_onset_gate"]["passed"])
        self.assertLess(
            flat_quiet_wake["sleep_onset_gate"]["downward_transition"],
            flat_quiet_wake["sleep_onset_gate"]["minimum_downward_transition"],
        )
        self.assertLess(
            flat_quiet_wake["sleep_onset_gate"]["relative_sleep_support"],
            flat_quiet_wake["sleep_onset_gate"]["minimum_relative_sleep_support"],
        )

    def test_gated_n3_has_specific_boundary_but_ambiguous_n2_still_abstains(self):
        distribution = {
            "wake": 0.05, "n1": 0.14, "n2": 0.35, "n3": 0.46, "rem": 0.0,
        }
        ordinary, ordinary_meta = evidence_candidate_with_abstention(
            distribution, minimum_winner=0.50, minimum_margin=0.10,
        )
        gated, gated_meta = evidence_candidate_with_abstention(
            distribution,
            minimum_winner=0.50,
            minimum_margin=0.10,
            gated_stage_thresholds={"n3": (0.40, 0.05)},
        )
        self.assertIsNone(ordinary)
        self.assertFalse(ordinary_meta["passed"])
        self.assertEqual(gated, "n3")
        self.assertEqual(gated_meta["threshold_source"], "n3_independent_gate")

        n2_distribution = {
            "wake": 0.05, "n1": 0.14, "n2": 0.46, "n3": 0.35, "rem": 0.0,
        }
        n2_candidate, n2_meta = evidence_candidate_with_abstention(
            n2_distribution,
            minimum_winner=0.50,
            minimum_margin=0.10,
            gated_stage_thresholds={"n3": (0.40, 0.05)},
        )
        self.assertIsNone(n2_candidate)
        self.assertEqual(n2_meta["threshold_source"], "general")


if __name__ == "__main__":
    unittest.main()
