"""Regression tests for Sleep physiology continuity across code updates."""

from __future__ import annotations

import unittest

from sleep_system_policy import sleep_policy_snapshot
from zeep_pod.sessions.sleep_context import (
    apply_sleep_decisions_to_samples,
    checkpoint_sleep_context,
    restore_session_sleep_context,
    restore_sleep_context,
)


class SleepRestartContextTests(unittest.TestCase):
    def test_legacy_provisional_stage_is_scoreable_for_whole_epoch(self) -> None:
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
            [True, True, True, True, True, True],
        )
        self.assertTrue(all(
            row["sleep_excluded_from_score"] is False for row in samples
        ))
        self.assertEqual(
            [row["sleep_excluded_from_personal_baseline"] for row in samples],
            [False, False, False, True, True, True],
        )

    def test_legacy_no_data_status_cannot_erase_durable_stage(self) -> None:
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

        self.assertTrue(all(row["sleep"] == "n2" for row in samples))
        self.assertTrue(all(
            row["sleep_data_status"] == "live"
            and row["sleep_score_eligible"] is True
            and row["sleep_excluded_from_score"] is False
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

    def test_no_decisions_anchor_wake_for_all_occupied_time(self) -> None:
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

        self.assertEqual(samples[0]["sleep_data_status"], "initial_awake_anchor")
        self.assertTrue(all(
            row["sleep_data_status"] == "continuity_hold"
            for row in samples[1:]
        ))
        self.assertTrue(all(row["sleep"] == "wake" for row in samples))
        self.assertTrue(all(row["sleep_score_eligible"] for row in samples))
        self.assertTrue(all(
            row["sleep_excluded_from_personal_baseline"] for row in samples
        ))

    def test_initial_anchor_does_not_depend_on_wall_clock_gap(self) -> None:
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
                "initial_awake_anchor",
                "continuity_hold",
                "continuity_hold",
            ],
        )
        self.assertEqual([row["sleep"] for row in samples], ["wake"] * 3)
        self.assertTrue(all(row["sleep_score_eligible"] for row in samples))

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
            row["sleep_score_eligible"] is True for row in samples[3:]
        ))
        self.assertTrue(all(
            row["sleep_data_status"] == "continuity_hold"
            for row in samples[3:]
        ))
        self.assertTrue(all(
            row["sleep_excluded_from_personal_baseline"] is True
            for row in samples[3:]
        ))

    def test_invalid_vitals_or_bcg_carry_durable_stage(self) -> None:
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

        self.assertEqual([row["sleep"] for row in samples], ["n2"] * 3)
        self.assertTrue(all(
            row["sleep_score_eligible"] for row in samples
        ))
        self.assertTrue(all(
            row["sleep_data_status"] == "continuity_hold"
            for row in samples[1:]
        ))

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
            row["sleep"] == "n2"
            and row["sleep_data_status"] == "continuity_hold"
            and row["sleep_score_eligible"] is True
            for row in samples[3:9]
        ))

    def test_confirmed_off_bed_latches_until_same_packet_fresh_return(self) -> None:
        samples = [
            {
                "t": 10.0,
                "bed": "On bed",
                "hr": 60.0,
                "rr": 14.0,
                "bcg_analysis_valid": True,
            },
            {
                "t": 20.0,
                "bed": "Get out of bed",
                "hr": None,
                "rr": None,
                "bcg_analysis_valid": False,
                "bed_exit_evidence": {
                    "confirmed": True,
                    "confirmed_by": "consecutive_buckets",
                },
            },
            {
                # Plausible values without a proven current BCG bucket cannot
                # release the durable latch after restart. The cached stage is
                # discarded before replay and is not authoritative either.
                "t": 30.0,
                "bed": "On bed",
                "hr": 60.0,
                "rr": 14.0,
                "sleep": "wake",
            },
            {
                "t": 40.0,
                "bed": "On bed",
                "hr": 60.0,
                "rr": None,
                "bcg_analysis_valid": True,
            },
            {
                "t": 50.0,
                "bed": "On bed",
                "hr": None,
                "rr": 14.0,
                "bcg_analysis_valid": True,
            },
            {
                "t": 60.0,
                "bed": "On bed",
                "hr": 60.0,
                "rr": 14.0,
                "bcg_analysis_valid": True,
            },
        ]
        stage_event = {
            "timestamp": "1970-01-01T00:00:10+00:00",
            "value": {
                "state": "n2",
                "attribution_start": "1970-01-01T00:00:00+00:00",
                "attribution_end": "1970-01-01T00:00:10+00:00",
                "score_eligible": True,
            },
        }

        apply_sleep_decisions_to_samples(
            samples,
            stage_events=[stage_event],
            fallback_interval_s=10.0,
        )

        self.assertEqual(
            [row.get("sleep") for row in samples],
            ["n2", None, None, None, None, "wake"],
        )
        self.assertTrue(all(
            row["sleep_data_status"] == "empty_bed"
            for row in samples[1:5]
        ))
        self.assertTrue(samples[5]["sleep_score_eligible"])

    def test_raw_bed_exit_label_does_not_create_off_bed_latch(self) -> None:
        samples = [
            {
                "t": 10.0,
                "bed": "On bed",
                "hr": 60.0,
                "rr": 14.0,
                "bcg_analysis_valid": True,
            },
            {
                "t": 20.0,
                "bed": "Get out of bed",
                "hr": None,
                "rr": None,
                "bcg_analysis_valid": False,
                "bed_exit_evidence": {"confirmed": False},
            },
            {
                "t": 30.0,
                "bed": "On bed",
                "hr": None,
                "rr": None,
                "bcg_analysis_valid": False,
            },
        ]
        stage_event = {
            "timestamp": "1970-01-01T00:00:10+00:00",
            "value": {
                "state": "n2",
                "attribution_start": "1970-01-01T00:00:00+00:00",
                "attribution_end": "1970-01-01T00:00:10+00:00",
            },
        }

        apply_sleep_decisions_to_samples(
            samples,
            stage_events=[stage_event],
            fallback_interval_s=10.0,
        )

        self.assertEqual([row["sleep"] for row in samples], ["n2"] * 3)
        self.assertNotIn(
            "empty_bed", [row["sleep_data_status"] for row in samples]
        )

    def test_unconfirmed_off_bed_status_state_cannot_override_stage(self) -> None:
        samples = [{"t": float(second)} for second in (10, 20, 30)]
        interval = {
            "attribution_start": "1970-01-01T00:00:00+00:00",
            "attribution_end": "1970-01-01T00:00:30+00:00",
        }

        apply_sleep_decisions_to_samples(
            samples,
            stage_events=[{
                "timestamp": "1970-01-01T00:00:30+00:00",
                "value": {"state": "n2", **interval},
            }],
            status_events=[{
                "timestamp": "1970-01-01T00:00:30+00:00",
                "value": {
                    "state": "off_bed",
                    "data_status": "missing_current_vitals",
                    **interval,
                },
            }],
            fallback_interval_s=30.0,
        )

        self.assertEqual([row["sleep"] for row in samples], ["n2"] * 3)

    def test_confirmed_evidence_normalizes_and_latches_legacy_status(self) -> None:
        samples = [{"t": 10.0}, {"t": 20.0}]

        apply_sleep_decisions_to_samples(
            samples,
            stage_events=[],
            status_events=[{
                "timestamp": "1970-01-01T00:00:10+00:00",
                "value": {
                    "state": "off_bed",
                    "data_status": "missing_current_vitals",
                    "bed_exit_evidence": {"confirmed": True},
                    "attribution_start": "1970-01-01T00:00:00+00:00",
                    "attribution_end": "1970-01-01T00:00:10+00:00",
                },
            }],
            fallback_interval_s=10.0,
        )

        self.assertEqual(
            [row["sleep_data_status"] for row in samples],
            ["confirmed_off_bed", "empty_bed"],
        )
        self.assertTrue(all(row["sleep"] is None for row in samples))

    def test_legacy_durable_off_bed_state_is_a_canonical_status(self) -> None:
        samples = [{"t": 10.0}, {"t": 20.0}]

        apply_sleep_decisions_to_samples(
            samples,
            stage_events=[],
            status_events=[{
                "timestamp": "1970-01-01T00:00:10+00:00",
                "value": {
                    "state": "off_bed",
                    "attribution_start": "1970-01-01T00:00:00+00:00",
                    "attribution_end": "1970-01-01T00:00:10+00:00",
                },
            }],
            fallback_interval_s=10.0,
        )

        self.assertEqual(
            [row["sleep_data_status"] for row in samples],
            ["confirmed_off_bed", "empty_bed"],
        )

    def test_stage_and_carry_preserve_all_version_provenance(self) -> None:
        provenance = {
            "estimator_version": "estimator-test",
            "evidence_version": "evidence-test",
            "baseline_version": "baseline-test",
            "transition_policy_version": "transition-test",
        }
        expected = {
            "sleep_estimator_version": "estimator-test",
            "sleep_evidence_version": "evidence-test",
            "sleep_baseline_version": "baseline-test",
            "sleep_transition_policy": "transition-test",
        }
        samples = [{"t": 10.0}, {"t": 20.0}]

        apply_sleep_decisions_to_samples(
            samples,
            stage_events=[{
                "timestamp": "1970-01-01T00:00:10+00:00",
                "value": {
                    "state": "n2",
                    "attribution_start": "1970-01-01T00:00:00+00:00",
                    "attribution_end": "1970-01-01T00:00:10+00:00",
                    "metrics": {
                        "auxiliary_evidence": {
                            "acoustic": {"corroborated": True}
                        }
                    },
                    **provenance,
                },
            }],
            fallback_interval_s=10.0,
        )

        for sample in samples:
            self.assertEqual(
                {field: sample.get(field) for field in expected}, expected
            )
        self.assertTrue(samples[0]["acoustic_corroborated"])
        self.assertFalse(samples[1]["acoustic_corroborated"])

    def test_durable_stage_event_releases_latch_without_timeline_bcg(self) -> None:
        samples = [{"t": 10.0}, {"t": 20.0}, {"t": 30.0}]
        status_event = {
            "timestamp": "1970-01-01T00:00:10+00:00",
            "value": {
                "state": "off_bed",
                "data_status": "confirmed_off_bed",
                "attribution_start": "1970-01-01T00:00:00+00:00",
                "attribution_end": "1970-01-01T00:00:10+00:00",
                "estimator_version": "off-bed-estimator",
            },
        }
        stage_event = {
            "timestamp": "1970-01-01T00:00:20+00:00",
            "value": {
                "state": "wake",
                "attribution_start": "1970-01-01T00:00:10+00:00",
                "attribution_end": "1970-01-01T00:00:20+00:00",
                "estimator_version": "return-estimator",
            },
        }

        apply_sleep_decisions_to_samples(
            samples,
            stage_events=[stage_event],
            status_events=[status_event],
            fallback_interval_s=10.0,
        )

        self.assertEqual(
            [sample.get("sleep") for sample in samples],
            [None, "wake", "wake"],
        )
        self.assertEqual(
            [sample["sleep_occupancy_provenance"] for sample in samples],
            [
                "canonical_off_bed_status",
                "durable_stage_event",
                "durable_stage_event",
            ],
        )
        self.assertEqual(
            [sample.get("sleep_estimator_version") for sample in samples],
            ["off-bed-estimator", "return-estimator", "return-estimator"],
        )

    def test_off_bed_latch_and_fresh_return_preserve_provenance(self) -> None:
        expected = {
            "sleep_estimator_version": "estimator-test",
            "sleep_evidence_version": "evidence-test",
            "sleep_baseline_version": "baseline-test",
            "sleep_transition_policy": "transition-test",
        }
        samples = [
            {"t": 10.0},
            {"t": 20.0},
            {
                "t": 30.0,
                "bed": "On bed",
                "hr": 60.0,
                "rr": 14.0,
                "bcg_analysis_valid": True,
            },
        ]
        status_event = {
            "timestamp": "1970-01-01T00:00:10+00:00",
            "value": {
                "state": "off_bed",
                "data_status": "confirmed_off_bed",
                "attribution_start": "1970-01-01T00:00:00+00:00",
                "attribution_end": "1970-01-01T00:00:10+00:00",
                "estimator_version": "estimator-test",
                "evidence_version": "evidence-test",
                "baseline_version": "baseline-test",
                "transition_policy_version": "transition-test",
            },
        }

        apply_sleep_decisions_to_samples(
            samples,
            stage_events=[],
            status_events=[status_event],
            fallback_interval_s=10.0,
        )

        self.assertEqual(
            [sample["sleep_data_status"] for sample in samples],
            ["confirmed_off_bed", "empty_bed", "initial_awake_anchor"],
        )
        for sample in samples:
            self.assertEqual(
                {field: sample.get(field) for field in expected}, expected
            )

    def test_sparse_status_provenance_does_not_erase_stage_versions(self) -> None:
        samples = [{"t": 10.0}, {"t": 20.0}]
        interval = {
            "attribution_start": "1970-01-01T00:00:00+00:00",
            "attribution_end": "1970-01-01T00:00:10+00:00",
        }

        apply_sleep_decisions_to_samples(
            samples,
            stage_events=[{
                "timestamp": "1970-01-01T00:00:10+00:00",
                "value": {
                    "state": "n2",
                    "estimator_version": "estimator-test",
                    "evidence_version": "stage-evidence-test",
                    "baseline_version": "baseline-test",
                    "transition_policy_version": "transition-test",
                    **interval,
                },
            }],
            status_events=[{
                "timestamp": "1970-01-01T00:00:10+00:00",
                "value": {
                    "state": "off_bed",
                    "data_status": "confirmed_off_bed",
                    "evidence_version": "exit-evidence-test",
                    **interval,
                },
            }],
            fallback_interval_s=10.0,
        )

        expected = {
            "sleep_estimator_version": "estimator-test",
            "sleep_evidence_version": "exit-evidence-test",
            "sleep_baseline_version": "baseline-test",
            "sleep_transition_policy": "transition-test",
        }
        for sample in samples:
            self.assertEqual(
                {field: sample.get(field) for field in expected}, expected
            )

    def test_durable_off_bed_status_keeps_its_provenance(self) -> None:
        samples = [{
            "t": 30.0,
            "bed": "Get out of bed",
            "hr": None,
            "rr": None,
            "bcg_analysis_valid": False,
        }]
        status_event = {
            "timestamp": "1970-01-01T00:00:30+00:00",
            "value": {
                "state": "off_bed",
                "data_status": "confirmed_off_bed",
                "attribution_start": "1970-01-01T00:00:00+00:00",
                "attribution_end": "1970-01-01T00:00:30+00:00",
                "evidence_version": "bed-exit-v-test",
            },
        }

        apply_sleep_decisions_to_samples(
            samples,
            stage_events=[],
            status_events=[status_event],
            fallback_interval_s=30.0,
        )

        self.assertEqual(samples[0]["sleep_data_status"], "confirmed_off_bed")
        self.assertEqual(
            samples[0]["sleep_evidence_version"], "bed-exit-v-test"
        )

    def test_dominant_off_bed_status_latches_across_following_gap(self) -> None:
        samples = [
            {"t": 30.0, "bed": None, "hr": None, "rr": None},
            {"t": 60.0, "bed": None, "hr": None, "rr": None},
        ]
        status_event = {
            "timestamp": "1970-01-01T00:00:30+00:00",
            "value": {
                "state": "off_bed",
                "data_status": "confirmed_or_dominant_off_bed",
                "attribution_start": "1970-01-01T00:00:00+00:00",
                "attribution_end": "1970-01-01T00:00:30+00:00",
            },
        }

        apply_sleep_decisions_to_samples(
            samples,
            stage_events=[],
            status_events=[status_event],
            fallback_interval_s=30.0,
        )

        self.assertEqual(
            [sample["sleep_data_status"] for sample in samples],
            ["confirmed_or_dominant_off_bed", "empty_bed"],
        )
        self.assertTrue(all(sample["sleep"] is None for sample in samples))

    def test_checkpoint_copies_only_restart_physiology(self) -> None:
        context = checkpoint_sleep_context(
            {
                "session_id": "session-1",
                "awake_vital_pairs": [(1_000.0, 76.0, 18.0)],
                "awake_hr_reference": 76.0,
                "awake_rr_reference": 18.0,
                "sleep_onset_at": 1_060.0,
                "last_valid_frame_t": 1_120.0,
                "off_bed_latched": True,
                "private_note": "not-persisted",
            },
            "session-1",
        )

        self.assertIsNotNone(context)
        self.assertNotIn("private_note", context)
        self.assertEqual(context["awake_hr_reference"], 76.0)
        self.assertIs(context["off_bed_latched"], True)

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

    def test_restore_latch_requires_proven_fresh_bcg_to_release(self) -> None:
        common = {
            "session_id": "session-1",
            "stage_events": [],
            "evidence_events": [],
            "checkpoint_context": {
                "session_id": "session-1",
                "off_bed_latched": True,
            },
            "heart_rate_range": (30.0, 220.0),
            "respiration_rate_range": (4.0, 50.0),
        }
        plausible_but_unproven = restore_sleep_context(
            samples=[{
                "t": 30.0,
                "sleep": "wake",
                "bed": "On bed",
                "hr": 60.0,
                "rr": 14.0,
            }],
            **common,
        )
        proven_same_bucket = restore_sleep_context(
            samples=[{
                "t": 30.0,
                "sleep": "wake",
                "bed": "On bed",
                "hr": 60.0,
                "rr": 14.0,
                "bcg_analysis_valid": True,
            }],
            **common,
        )

        self.assertIs(
            plausible_but_unproven["path"]["off_bed_latched"], True
        )
        self.assertIs(
            plausible_but_unproven["provenance"]["off_bed_latched"], True
        )
        self.assertIs(
            proven_same_bucket["path"]["off_bed_latched"], False
        )

    def test_session_restore_accepts_later_durable_stage_as_return(self) -> None:
        status_event = {
            "timestamp": "1970-01-01T00:00:10+00:00",
            "value": {
                "state": "off_bed",
                "data_status": "confirmed_off_bed",
                "attribution_start": "1970-01-01T00:00:00+00:00",
                "attribution_end": "1970-01-01T00:00:10+00:00",
            },
        }
        stage_event = {
            "timestamp": "1970-01-01T00:00:20+00:00",
            "value": {
                "state": "wake",
                "attribution_start": "1970-01-01T00:00:10+00:00",
                "attribution_end": "1970-01-01T00:00:20+00:00",
            },
        }

        def read_sessions(query, _parameters):
            if "type='sleep_stage_status'" in query:
                return [status_event]
            if "type='sleep_stage'" in query:
                return [stage_event]
            return []

        samples = [{"t": 10.0}, {"t": 20.0}, {"t": 30.0}]
        restored = restore_session_sleep_context(
            read_sessions,
            "session-1",
            samples=samples,
            checkpoint_context={
                "session_id": "session-1",
                "off_bed_latched": True,
            },
            heart_rate_range=(30.0, 220.0),
            respiration_rate_range=(4.0, 50.0),
            fallback_interval_s=10.0,
        )

        self.assertEqual([sample.get("sleep") for sample in samples], [
            None, "wake", "wake",
        ])
        self.assertIs(restored["path"]["off_bed_latched"], False)

    def test_policy_declares_confirmed_latch_and_same_packet_return(self) -> None:
        snapshot = sleep_policy_snapshot()
        gate = snapshot["classification_gate"]
        movement = snapshot["movement_guard"]

        self.assertTrue(gate["off_bed_return_requires_same_packet_hr_rr_bcg"])
        self.assertTrue(gate["durable_stage_event_confirms_occupied_return"])
        self.assertFalse(movement["raw_bed_label_can_latch_off_bed"])
        self.assertEqual(
            movement["off_bed_latch_sources"],
            [
                "confirmed_bed_exit_evidence",
                "canonical_off_bed_status_event",
            ],
        )
        self.assertTrue(
            movement["off_bed_return_requires_affirmative_on_bed_status"]
        )
        self.assertTrue(
            movement["off_bed_return_requires_same_packet_hr_rr_bcg"]
        )
        self.assertTrue(
            movement["durable_stage_event_confirms_occupied_return"]
        )

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

        self.assertEqual(samples[0]["sleep"], "wake")
        self.assertEqual(
            samples[0]["sleep_data_status"],
            "initial_awake_anchor",
        )
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
