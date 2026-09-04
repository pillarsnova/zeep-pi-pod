import unittest

from reclassify_sleep_history import (
    HistoricalStagePath,
    RawBcgWindow,
    adjusted_probabilities,
    audit_replayed_sequence,
)


class RawBcgWindowTests(unittest.TestCase):
    def test_rebuilds_variability_and_movement_from_five_second_buckets(self):
        packets = [
            {"timestamp": "2026-08-25T21:29:11+00:00", "heart_rate": 50.0,
             "respiration_rate": 14.0, "status_code": 0},
            {"timestamp": "2026-08-25T21:29:14+00:00", "heart_rate": 52.0,
             "respiration_rate": 16.0, "status_code": 0},
            {"timestamp": "2026-08-25T21:29:16+00:00", "heart_rate": 60.0,
             "respiration_rate": 18.0, "status_code": 2},
            {"timestamp": "2026-08-25T21:29:19+00:00", "heart_rate": 62.0,
             "respiration_rate": 20.0, "status_code": 0},
        ]
        result = RawBcgWindow(packets).reconstruct({
            "window_start": "2026-08-25T21:29:10+00:00",
            "window_end": "2026-08-25T21:29:20+00:00",
            "sample_count": 2,
        })

        self.assertEqual(result["mean_hr"], 56.0)
        self.assertEqual(result["mean_rr"], 17.0)
        self.assertGreater(result["hr_cv"], 0.08)
        self.assertGreater(result["rr_cv"], 0.1)
        self.assertEqual(result["movement_ratio"], 0.5)
        self.assertEqual(result["max_moving_run_frames"], 1)
        self.assertEqual(result["movement_burst_count"], 1)
        self.assertEqual(result["bed_status"], "Moving")

    def test_isolated_final_exit_packet_is_not_replayed_as_empty_bed(self):
        packets = [
            {"timestamp": "2026-08-25T21:29:11+00:00", "heart_rate": 60.0,
             "respiration_rate": 14.0, "status_code": 0},
            {"timestamp": "2026-08-25T21:29:16+00:00", "heart_rate": 60.0,
             "respiration_rate": 14.0, "status_code": 0},
            {"timestamp": "2026-08-25T21:29:18+00:00", "heart_rate": 60.0,
             "respiration_rate": 14.0, "status_code": 0},
            {"timestamp": "2026-08-25T21:29:19+00:00", "heart_rate": None,
             "respiration_rate": None, "status_code": 1},
        ]
        result = RawBcgWindow(packets).reconstruct({
            "window_start": "2026-08-25T21:29:10+00:00",
            "window_end": "2026-08-25T21:29:20+00:00",
            "sample_count": 2,
        })
        self.assertEqual(result["bed_status"], "On bed")
        self.assertTrue(result["bed_exit_evidence"]["transient_rejected"])

    def test_raw_packet_burst_does_not_confirm_exit_by_itself(self):
        packets = [
            {"timestamp": "2026-08-25T21:29:11+00:00", "heart_rate": 60.0,
             "respiration_rate": 14.0, "status_code": 0},
            {"timestamp": "2026-08-25T21:29:16+00:00", "heart_rate": None,
             "respiration_rate": None, "status_code": 1},
            {"timestamp": "2026-08-25T21:29:17+00:00", "heart_rate": None,
             "respiration_rate": None, "status_code": 1},
            {"timestamp": "2026-08-25T21:29:18+00:00", "heart_rate": None,
             "respiration_rate": None, "status_code": 1},
            {"timestamp": "2026-08-25T21:29:19+00:00", "heart_rate": None,
             "respiration_rate": None, "status_code": 1},
            {"timestamp": "2026-08-25T21:29:20+00:00", "heart_rate": None,
             "respiration_rate": None, "status_code": 1},
        ]
        result = RawBcgWindow(packets).reconstruct({
            "window_start": "2026-08-25T21:29:10+00:00",
            "window_end": "2026-08-25T21:29:20+00:00",
            "sample_count": 2,
        })
        self.assertEqual(result["bed_status"], "On bed")
        self.assertTrue(result["bed_exit_evidence"]["transient_rejected"])
        self.assertFalse(
            result["bed_exit_evidence"]["raw_packet_confirmation_enabled"])

    def test_completed_session_preserves_single_terminal_exit_packet(self):
        packets = [
            {"timestamp": "2026-08-25T21:29:11+00:00", "heart_rate": 60.0,
             "respiration_rate": 14.0, "status_code": 0},
            {"timestamp": "2026-08-25T21:29:16+00:00", "heart_rate": 60.0,
             "respiration_rate": 14.0, "status_code": 0},
            {"timestamp": "2026-08-25T21:29:19+00:00", "heart_rate": None,
             "respiration_rate": None, "status_code": 1},
        ]
        result = RawBcgWindow(packets).reconstruct({
            "window_start": "2026-08-25T21:29:10+00:00",
            "window_end": "2026-08-25T21:29:20+00:00",
            "sample_count": 2,
        }, terminal_session_boundary=True)
        self.assertEqual(result["bed_status"], "Get out of bed")
        self.assertEqual(
            result["bed_exit_evidence"]["confirmed_by"],
            "terminal_session_boundary",
        )


class HistoricalStagePathTests(unittest.TestCase):
    def test_new_cycle_is_anchored_at_wake_without_fabricated_bridge(self):
        path = HistoricalStagePath()
        selected, _ = path.stabilize("n3", now=0.0, strong_wake=False)
        self.assertEqual(selected, "wake")
        path.commit(selected, 0.0)

        # A direct N3 candidate is rejected until independent N1/N2 evidence
        # arrives; the transition prior must not manufacture either label.
        selected, metadata = path.stabilize("n3", now=15.0, strong_wake=False)
        self.assertEqual(selected, "wake")
        self.assertIsNone(metadata["bridge_state"])
        self.assertEqual(metadata["decision"], "blocked_transition_abstain")
        path.commit(selected, 15.0)
        selected, metadata = path.stabilize("n3", now=45.0, strong_wake=False)
        self.assertEqual(selected, "wake")
        self.assertEqual(metadata["required_ticks"], 0)

    def test_emitted_stage_remains_probability_winner(self):
        result = adjusted_probabilities(
            {"wake": 0.05, "n1": 0.1, "n2": 0.2, "n3": 0.6, "rem": 0.05},
            "n2",
        )
        self.assertEqual(max(result, key=result.get), "n2")
        self.assertAlmostEqual(sum(result.values()), 1.0, places=4)

    def test_n1_cycle_gate_survives_recent_history_eviction(self):
        path = HistoricalStagePath()
        for index, stage in enumerate(
            ("wake", "n1", "n2", "rem", "n2", "rem", "n2", "rem", "n2", "n3")
        ):
            path.commit(stage, index * 60.0)
        self.assertNotIn("n1", path.seen)
        self.assertTrue(path.cycle_has_n1)
        self.assertTrue(path._allowed("n2", False))
        self.assertEqual(path._fallback("n1"), "n3")

    def test_historical_path_allows_sustained_n3_to_rem(self):
        path = HistoricalStagePath()
        for index, stage in enumerate(("wake", "n1", "n2", "n3")):
            path.commit(stage, index * 60.0)
        self.assertTrue(path._allowed("rem", False))
        selected = "n3"
        for now in (240.0, 270.0):
            selected, metadata = path.stabilize("rem", now=now, strong_wake=False)
        self.assertEqual(selected, "rem")
        self.assertEqual(metadata["required_ticks"], 2)
        self.assertEqual(metadata["confirmation_seconds"], 60.0)

    def test_historical_n2_to_wake_requires_strong_proxy_without_bridge(self):
        path = HistoricalStagePath()
        for index, stage in enumerate(("wake", "n1", "n2")):
            path.commit(stage, index * 60.0)
        self.assertFalse(path._allowed("wake", False))
        self.assertEqual(path._fallback("wake"), "n2")
        self.assertTrue(path._allowed("wake", True))


class ReplayAuditTests(unittest.TestCase):
    @staticmethod
    def value(state, *, movement=0.0, shift=0.0, hr=60.0, rr=16.0):
        return {
            "state": state,
            "metrics": {
                "mean_hr": hr,
                "mean_rr": rr,
                "movement_ratio": movement,
                "bcg_amplitude_shift_ratio": shift,
                "waveform_available": True,
            },
        }

    def test_valid_sequence_passes_with_corroborated_motion_wake_proxy(self):
        sequence = [
            ("t0", self.value("wake")),
            ("t1", self.value("n1")),
            ("t2", self.value("n2")),
            ("t3", {
                "state": "wake",
                "metrics": {
                    "mean_hr": 65.0,
                    "mean_rr": 18.0,
                    "movement_ratio": 0.5,
                    "max_moving_run_frames": 4,
                    "hr_slope_bpm_per_min": 2.5,
                    "bcg_amplitude_shift_ratio": 0.2,
                    "bed_status": "Moving",
                },
            }),
        ]
        audit = audit_replayed_sequence(sequence)
        self.assertTrue(audit["apply_gate"]["passed"])
        self.assertEqual(audit["arousal_proxy_validation"]["sleep_to_wake_count"], 1)
        self.assertEqual(audit["arousal_proxy_validation"]["amplitude_shift_aligned"], 1)
        self.assertEqual(audit["arousal_proxy_validation"]["any_same_window_proxy"], 1)

    def test_prohibited_transition_and_ping_pong_block_apply(self):
        prohibited = audit_replayed_sequence([
            ("t0", self.value("wake")),
            ("t1", self.value("n3")),
        ])
        self.assertFalse(prohibited["apply_gate"]["passed"])
        self.assertEqual(prohibited["transition_verification"]["wake_to_n3"], 1)

        ping_pong = audit_replayed_sequence([
            ("t0", self.value("wake")),
            ("t1", self.value("n1")),
            ("t2", self.value("n2")),
            ("t3", self.value("rem")),
            ("t4", self.value("n2")),
        ])
        self.assertFalse(ping_pong["apply_gate"]["passed"])
        self.assertEqual(
            ping_pong["boundary_packet_smoothness"]["n2_rem_one_epoch_ping_pong"], 1)

    def test_sustained_n3_to_rem_is_not_a_prohibited_transition(self):
        audit = audit_replayed_sequence([
            ("t0", self.value("wake")),
            ("t1", self.value("n1")),
            ("t2", self.value("n2")),
            ("t3", self.value("n3")),
            ("t4", self.value("rem")),
            ("t5", self.value("rem")),
        ])
        self.assertTrue(audit["apply_gate"]["passed"])
        self.assertEqual(audit["transition_verification"]["n3_to_rem"], 1)
        self.assertEqual(audit["transition_verification"]["prohibited_count"], 0)

    def test_sleep_to_wake_without_any_same_window_proxy_blocks_apply(self):
        audit = audit_replayed_sequence([
            ("t0", self.value("wake")),
            ("t1", self.value("n1")),
            ("t2", self.value("n2")),
            ("t3", self.value("wake")),
        ])
        self.assertFalse(audit["apply_gate"]["passed"])
        self.assertEqual(audit["arousal_proxy_validation"]["missing_proxy_count"], 1)


if __name__ == "__main__":
    unittest.main()
