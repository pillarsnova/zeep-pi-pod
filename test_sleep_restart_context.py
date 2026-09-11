"""Regression tests for Sleep physiology continuity across code updates."""

from __future__ import annotations

import unittest

from zeep_pod.sessions.sleep_context import (
    apply_sleep_decisions_to_samples,
    checkpoint_sleep_context,
    restore_session_sleep_context,
    restore_sleep_context,
)


class SleepRestartContextTests(unittest.TestCase):
    def test_epoch_projection_applies_provisional_to_all_three_sensor_rows(self) -> None:
        samples = [
            {
                "t": float(second),
                "analysis_epoch_s": float(second),
                "hr": 65.0,
                "rr": 15.0,
                # Simulate the old forward-shifted Dashboard snapshot.
                "sleep": "wake" if second >= 30 else None,
                "sleep_score_eligible": second < 60,
            }
            for second in (10, 20, 30, 40, 50, 60)
        ]
        stage_events = [
            {
                "timestamp": "1970-01-01T00:00:30+00:00",
                "value": {
                    "state": "wake",
                    "attribution_start": "1970-01-01T00:00:00+00:00",
                    "attribution_end": "1970-01-01T00:00:30+00:00",
                    "sample_interval_s": 30.0,
                    "score_eligible": True,
                },
            },
            {
                "timestamp": "1970-01-01T00:01:00+00:00",
                "value": {
                    "state": "wake",
                    "attribution_start": "1970-01-01T00:00:30+00:00",
                    "attribution_end": "1970-01-01T00:01:00+00:00",
                    "sample_interval_s": 30.0,
                    "held_previous_state": True,
                    "provisional": True,
                    "score_eligible": False,
                    "excluded_from_score": True,
                    "confirmation": {
                        "pending_state": "n1",
                        "provisional": True,
                    },
                },
            },
        ]

        apply_sleep_decisions_to_samples(
            samples,
            stage_events=stage_events,
            fallback_interval_s=30.0,
        )

        self.assertEqual([row["sleep"] for row in samples], ["wake"] * 6)
        self.assertEqual(
            [row["sleep_provisional"] for row in samples],
            [False, False, False, True, True, True],
        )
        self.assertEqual(
            [row["sleep_score_eligible"] for row in samples],
            [True, True, True, False, False, False],
        )

    def test_operational_status_overrides_stale_stage_snapshot(self) -> None:
        samples = [
            {"t": float(second), "sleep": "n2", "hr": 60.0, "rr": 14.0}
            for second in (10, 20, 30)
        ]
        stage_event = {
            "timestamp": "1970-01-01T00:00:30+00:00",
            "value": {
                "state": "n2",
                "attribution_start": "1970-01-01T00:00:00+00:00",
                "attribution_end": "1970-01-01T00:00:30+00:00",
                "score_eligible": True,
            },
        }
        status_event = {
            "timestamp": "1970-01-01T00:00:30+00:00",
            "value": {
                "state": "no_data",
                "data_status": "missing_current_vitals",
                "attribution_start": "1970-01-01T00:00:00+00:00",
                "attribution_end": "1970-01-01T00:00:30+00:00",
                "excluded_from_score": True,
            },
        }

        apply_sleep_decisions_to_samples(
            samples,
            stage_events=[stage_event],
            status_events=[status_event],
            fallback_interval_s=30.0,
        )

        self.assertTrue(all(row["sleep"] is None for row in samples))
        self.assertTrue(all(
            row["sleep_data_status"] == "missing_current_vitals"
            and row["sleep_score_eligible"] is False
            and row["sleep_excluded_from_score"] is True
            for row in samples
        ))

    def test_projection_uses_session_clock_when_analysis_frame_is_lagged(self) -> None:
        # The sampler starts immediately and is not phase-locked to analysis;
        # analysis_epoch_s may therefore be None once and duplicated later.
        samples = [
            {"t": 3.0, "analysis_epoch_s": None, "hr": 65.0, "rr": 15.0},
            {"t": 13.0, "analysis_epoch_s": 10.0, "hr": 65.0, "rr": 15.0},
            {"t": 23.0, "analysis_epoch_s": 20.0, "hr": 65.0, "rr": 15.0},
            {"t": 33.0, "analysis_epoch_s": 20.0, "hr": 64.0, "rr": 14.5},
            {"t": 43.0, "analysis_epoch_s": 30.0, "hr": 64.0, "rr": 14.5},
            {"t": 53.0, "analysis_epoch_s": 40.0, "hr": 64.0, "rr": 14.5},
        ]
        events = [
            {
                "timestamp": "1970-01-01T00:00:30+00:00",
                "value": {
                    "state": "wake",
                    "attribution_start": "1970-01-01T00:00:00+00:00",
                    "attribution_end": "1970-01-01T00:00:30+00:00",
                    "score_eligible": True,
                },
            },
            {
                "timestamp": "1970-01-01T00:01:00+00:00",
                "value": {
                    "state": "n1",
                    "attribution_start": "1970-01-01T00:00:30+00:00",
                    "attribution_end": "1970-01-01T00:01:00+00:00",
                    "score_eligible": True,
                },
            },
        ]

        apply_sleep_decisions_to_samples(
            samples,
            stage_events=events,
            fallback_interval_s=30.0,
        )

        self.assertEqual(
            [sample["sleep"] for sample in samples],
            ["wake", "wake", "wake", "n1", "n1", "n1"],
        )

    def test_no_decisions_caps_initial_wait_at_two_minutes(self) -> None:
        samples = [
            {
                "t": float(second),
                "sample_interval_s": 10.0,
                "hr": 65.0,
                "rr": 15.0,
                "bed": "On bed",
                "bcg_analysis_valid": True,
            }
            for second in range(10, 3610, 10)
        ]

        apply_sleep_decisions_to_samples(
            samples,
            stage_events=[],
            fallback_interval_s=30.0,
        )

        self.assertTrue(all(
            row["sleep_data_status"] == "confirming_initial_state"
            for row in samples[:12]
        ))
        self.assertTrue(all(
            row["sleep_data_status"] == "initial_confirmation_timeout"
            for row in samples[12:]
        ))
        self.assertTrue(all(row["sleep"] is None for row in samples))

    def test_initial_wait_uses_wall_clock_not_only_valid_row_count(self) -> None:
        samples = [
            {
                "t": float(second),
                "sample_interval_s": 10.0,
                "hr": 65.0,
                "rr": 15.0,
                "bed": "On bed",
                "bcg_analysis_valid": True,
            }
            for second in (10, 20, 600)
        ]

        apply_sleep_decisions_to_samples(
            samples,
            stage_events=[],
            fallback_interval_s=30.0,
        )

        self.assertEqual(
            [row["sleep_data_status"] for row in samples],
            [
                "confirming_initial_state",
                "confirming_initial_state",
                "initial_confirmation_timeout",
            ],
        )

    def test_only_a_valid_unfinished_tail_carries_previous_state(self) -> None:
        samples = [
            {
                "t": float(second),
                "sample_interval_s": 10.0,
                "hr": 62.0,
                "rr": 14.0,
                "bed": "On bed",
                "bcg_analysis_valid": True,
            }
            for second in (10, 20, 30, 40, 50)
        ]
        event = {
            "timestamp": "1970-01-01T00:00:30+00:00",
            "value": {
                "state": "n2",
                "attribution_start": "1970-01-01T00:00:00+00:00",
                "attribution_end": "1970-01-01T00:00:30+00:00",
                "score_eligible": True,
            },
        }

        apply_sleep_decisions_to_samples(
            samples,
            stage_events=[event],
            fallback_interval_s=30.0,
        )

        self.assertEqual([row["sleep"] for row in samples], ["n2"] * 5)
        self.assertTrue(all(
            row["sleep_score_eligible"] is False for row in samples[3:]
        ))
        self.assertTrue(all(
            row["sleep_data_status"] == "provisional_hold"
            for row in samples[3:]
        ))

    def test_invalid_vitals_or_bcg_cannot_create_tail_hold(self) -> None:
        samples = [
            {
                "t": 30.0,
                "hr": 62.0,
                "rr": 14.0,
                "bed": "On bed",
                "bcg_analysis_valid": True,
            },
            {
                "t": 40.0,
                "hr": 500.0,
                "rr": 14.0,
                "bed": "On bed",
                "bcg_analysis_valid": True,
            },
            {
                "t": 50.0,
                "hr": 62.0,
                "rr": 14.0,
                "bed": "On bed",
                "bcg_analysis_valid": False,
            },
        ]
        event = {
            "timestamp": "1970-01-01T00:00:30+00:00",
            "value": {
                "state": "n2",
                "attribution_start": "1970-01-01T00:00:00+00:00",
                "attribution_end": "1970-01-01T00:00:30+00:00",
            },
        }

        apply_sleep_decisions_to_samples(
            samples,
            stage_events=[event],
            fallback_interval_s=30.0,
        )

        self.assertIsNone(samples[1]["sleep"])
        self.assertEqual(
            samples[1]["sleep_data_status"],
            "invalid_or_missing_current_vitals",
        )
        self.assertIsNone(samples[2]["sleep"])
        self.assertEqual(samples[2]["sleep_data_status"], "invalid_current_bcg")

    def test_long_interior_gap_never_uses_partial_tail_fallback(self) -> None:
        samples = [
            {
                "t": float(second),
                "hr": 62.0,
                "rr": 14.0,
                "bed": "On bed",
                "bcg_analysis_valid": True,
            }
            for second in range(10, 121, 10)
        ]
        events = [
            {
                "timestamp": "1970-01-01T00:00:30+00:00",
                "value": {
                    "state": "n2",
                    "attribution_start": "1970-01-01T00:00:00+00:00",
                    "attribution_end": "1970-01-01T00:00:30+00:00",
                },
            },
            {
                "timestamp": "1970-01-01T00:02:00+00:00",
                "value": {
                    "state": "n2",
                    "attribution_start": "1970-01-01T00:01:30+00:00",
                    "attribution_end": "1970-01-01T00:02:00+00:00",
                },
            },
        ]

        apply_sleep_decisions_to_samples(
            samples,
            stage_events=events,
            fallback_interval_s=30.0,
        )

        self.assertTrue(all(
            row["sleep"] is None
            and row["sleep_data_status"] == "missing_durable_sleep_decision"
            for row in samples[3:9]
        ))

    def test_checkpoint_copies_only_restart_physiology(self) -> None:
        context = checkpoint_sleep_context(
            {
                "session_id": "session-1",
                "awake_vital_pairs": [(1_000.0, 76.0, 18.0)],
                "awake_hr_reference": 76.0,
                "awake_rr_reference": 18.0,
                "sleep_onset_at": 1_060.0,
                "last_valid_frame_t": 1_120.0,
                "private_note": "not-persisted",
            },
            "session-1",
        )

        self.assertIsNotNone(context)
        self.assertNotIn("private_note", context)
        self.assertEqual(context["awake_hr_reference"], 76.0)

    def test_checkpoint_restores_awake_reference_and_original_onset(self) -> None:
        pairs = [
            [1_000.0 + index * 10.0, 78.0 - index, 18.0 - index / 10]
            for index in range(6)
        ]
        restored = restore_sleep_context(
            "session-1",
            stage_events=[
                {
                    "timestamp": "2026-09-05T15:00:00+00:00",
                    "value": {"state": "n1"},
                },
                {
                    "timestamp": "2026-09-05T15:01:00+00:00",
                    "value": {"state": "n2"},
                },
            ],
            evidence_events=[],
            samples=[],
            checkpoint_context={
                "session_id": "session-1",
                "awake_vital_pairs": pairs,
                "awake_hr_reference": 76.0,
                "awake_rr_reference": 17.8,
                "sleep_onset_at": 1_060.0,
                "last_valid_frame_t": 1_120.0,
            },
            heart_rate_range=(30.0, 220.0),
            respiration_rate_range=(4.0, 50.0),
        )

        self.assertEqual(restored["provenance"]["source"], "checkpoint")
        self.assertEqual(restored["path"]["sleep_onset_at"], 1_060.0)
        self.assertEqual(restored["path"]["last"], "n2")
        self.assertIsNotNone(restored["path"]["awake_hr_reference"])
        self.assertIsNotNone(restored["path"]["awake_rr_reference"])

    def test_legacy_checkpoint_recovers_reference_from_timeline(self) -> None:
        samples = [
            {
                "t": 1_000.0 + index * 10.0,
                "hr": 78.0 - index,
                "rr": 18.0 - index / 10,
            }
            for index in range(6)
        ]
        restored = restore_sleep_context(
            "session-1",
            stage_events=[
                {
                    "timestamp": "1970-01-01T00:18:20+00:00",
                    "value": {"state": "n1"},
                }
            ],
            evidence_events=[],
            samples=samples,
            checkpoint_context=None,
            heart_rate_range=(30.0, 220.0),
            respiration_rate_range=(4.0, 50.0),
        )

        provenance = restored["provenance"]
        self.assertEqual(provenance["source"], "pre_onset_timeline")
        self.assertEqual(provenance["awake_reference_pairs"], 6)
        self.assertEqual(provenance["last_confirmed_state"], "n1")

    def test_session_restore_maps_durable_stage_back_to_timeline(self) -> None:
        stage_event = {
            "timestamp": "1970-01-01T00:18:20+00:00",
            "value": {
                "state": "n2",
                "window_start": "1970-01-01T00:17:50+00:00",
                "window_end": "1970-01-01T00:18:20+00:00",
                "confidence": "high",
                "probabilities": {"n2": 0.8},
            },
        }

        def read_sessions(query, _parameters):
            return [stage_event] if "type='sleep_stage'" in query else []

        samples = [
            {"t": 1_050.0, "hr": 65.0, "rr": 15.0, "sleep": None},
            {"t": 1_090.0, "hr": 65.0, "rr": 15.0, "sleep": None},
        ]
        restored = restore_session_sleep_context(
            read_sessions,
            "session-1",
            samples=samples,
            checkpoint_context=None,
            heart_rate_range=(30.0, 220.0),
            respiration_rate_range=(4.0, 50.0),
            fallback_interval_s=30.0,
        )

        self.assertIsNone(samples[0]["sleep"])
        self.assertEqual(samples[1]["sleep"], "n2")
        self.assertEqual(samples[1]["sleep_confidence"], "high")
        self.assertEqual(restored["path"]["last"], "n2")

    def test_replayed_path_uses_attribution_start_for_onset_and_dwell(self) -> None:
        restored = restore_sleep_context(
            "session-1",
            stage_events=[{
                "timestamp": "1970-01-01T00:18:20+00:00",
                "value": {
                    "state": "n1",
                    "attribution_start": "1970-01-01T00:17:50+00:00",
                    "attribution_end": "1970-01-01T00:18:20+00:00",
                },
            }],
            evidence_events=[],
            samples=[],
            checkpoint_context=None,
            heart_rate_range=(30.0, 220.0),
            respiration_rate_range=(4.0, 50.0),
        )

        self.assertEqual(restored["path"]["sleep_onset_at"], 1_070.0)
        self.assertEqual(restored["path"]["stage_since"], 1_070.0)


if __name__ == "__main__":
    unittest.main()
