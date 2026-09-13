import sqlite3
import stat
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from audit_sleep_history_shadow import (
    ShadowPath,
    _duration_weighted_waso_seconds,
    normalize_session_allowlist,
    private_write_bytes,
    project_replay_decisions_to_report_rows,
    replay_session,
    report_state_rows_with_annotations,
    resolve_replay_mode_context,
    select_session_rows,
)
from sleep_session_report import build_session_report, build_sleep_quality
from sleep_stage_annotations import build_annotation, load_annotations


class ShadowPathParityTests(unittest.TestCase):
    @staticmethod
    def replay_bucket(timestamp, *, status=0):
        return {
            "t": float(timestamp),
            "hr": 72.0,
            "rr": 16.0,
            "valid": True,
            "status": status,
            "samples": [0] * 1000,
            "packet_count": 10,
            "paired_packets": 10,
            "paired_vital_coverage": 1.0,
            "waveform_sample_coverage": 1.0,
            "sound_leq_dba": None,
            "sound_large_step": False,
        }

    @staticmethod
    def replay_baseline():
        return {
            "wake": {"hr": (68.0, 82.0), "rr": (14.0, 20.0)},
            "n1": {"hr": (62.0, 76.0), "rr": (13.0, 19.0)},
            "n2": {"hr": (55.0, 70.0), "rr": (12.0, 18.0)},
            "n3": {"hr": (48.0, 64.0), "rr": (10.0, 16.0)},
            "rem": {"hr": (56.0, 76.0), "rr": (12.0, 20.0)},
        }

    def test_pending_allowed_transition_holds_previous_confirmed_state(self):
        path = ShadowPath()
        path.last = "wake"
        path.stage_since = 0.0

        held, metadata = path.step("n1", 100.0, False)

        self.assertEqual(held, "wake")
        self.assertEqual(metadata["confirmed_state"], "wake")
        self.assertEqual(metadata["decision"], "confirming")
        self.assertTrue(metadata["held_previous_state"])
        self.assertFalse(metadata["provisional"])
        self.assertTrue(metadata["score_eligible"])
        self.assertTrue(metadata["excluded_from_personal_baseline"])
        self.assertEqual(metadata["score_attribution_state"], "wake")
        self.assertFalse(metadata["challenger_counted_as_new_state"])

    def test_ambiguous_evidence_carries_previous_state_without_time_limit(self):
        path = ShadowPath()
        path.last = "n2"
        path.stage_since = 0.0

        results = [path.step(None, index * 30.0, False) for index in range(1, 5)]

        self.assertEqual([stage for stage, _ in results], ["n2"] * 4)
        self.assertEqual(
            [metadata["continuity_hold_epochs"] for _, metadata in results],
            [1, 2, 3, 4],
        )
        self.assertEqual(
            [metadata["provisional"] for _, metadata in results],
            [False, False, False, False],
        )
        self.assertEqual(
            [metadata["score_eligible"] for _, metadata in results],
            [True, True, True, True],
        )
        for _, metadata in results:
            self.assertEqual(metadata["confirmed_state"], "n2")
            self.assertEqual(metadata["score_attribution_state"], "n2")
            self.assertFalse(metadata["challenger_counted_as_new_state"])
            self.assertNotIn("unclassified", metadata)

    def test_blocked_transition_carries_previous_state_not_wait(self):
        path = ShadowPath()
        path.last = "wake"
        path.stage_since = 0.0

        held, metadata = path.step("n3", 30.0, False)

        self.assertEqual(held, "wake")
        self.assertEqual(metadata["decision"], "blocked_transition_hold")
        self.assertEqual(metadata["confirmed_state"], "wake")
        self.assertEqual(metadata["pending_state"], "n3")
        self.assertTrue(metadata["held_previous_state"])
        self.assertNotIn("unclassified", metadata)

    def test_initial_state_is_published_as_immediate_wake_anchor(self):
        path = ShadowPath()

        first, first_metadata = path.step("wake", 30.0, False)
        second, metadata = path.step("wake", 60.0, False)

        self.assertEqual(first, "wake")
        self.assertEqual(
            first_metadata["decision_kind"], "confirmed_state"
        )
        self.assertEqual(first_metadata["decision"], "initial_awake_anchor")
        self.assertTrue(first_metadata["score_eligible"])
        self.assertEqual(second, "wake")
        self.assertEqual(metadata["decision"], "hold_confirmed")

    def test_strong_wake_override_is_auditable_on_direct_n2_to_wake(self):
        path = ShadowPath()
        path.last = "n2"
        path.stage_since = 0.0
        path.cycle_has_n1 = True

        held, pending = path.step("wake", 120.0, True)
        confirmed, transition = path.step("wake", 150.0, True)

        self.assertEqual(held, "n2")
        self.assertEqual(pending["decision"], "confirming")
        self.assertEqual(confirmed, "wake")
        self.assertEqual(transition["decision"], "confirmed")
        self.assertTrue(transition["strong_wake_override"])

    def test_replay_anchors_initial_wake_at_first_epoch_like_live(self):
        buckets = [self.replay_bucket(index * 10) for index in range(1, 7)]

        with patch(
            "audit_sleep_history_shadow.make_buckets",
            return_value=buckets,
        ):
            replay = replay_session(
                [],
                0.0,
                60.0,
                baseline=self.replay_baseline(),
                rem_variability_weight=1.0,
            )

        self.assertFalse(replay["status_rows"])
        self.assertEqual(
            [(row["t"], row["state"]) for row in replay["state_rows"]],
            [(30.0, "wake"), (60.0, "wake")],
        )
        self.assertEqual(
            replay["classification_accounting"][
                "occupied_in_pod_state_gap_s"
            ],
            0.0,
        )

    def test_partial_final_epoch_carries_scoreable_state(self):
        buckets = [self.replay_bucket(index * 10) for index in range(1, 7)]

        with patch(
            "audit_sleep_history_shadow.make_buckets",
            return_value=buckets,
        ):
            replay = replay_session(
                [],
                0.0,
                65.0,
                baseline=self.replay_baseline(),
                rem_variability_weight=1.0,
            )

        tail = replay["state_rows"][-1]
        self.assertEqual(tail["t"], 65.0)
        self.assertEqual(tail["attribution_start"], 60.0)
        self.assertEqual(tail["sample_interval_s"], 5.0)
        self.assertEqual(tail["state"], "wake")
        self.assertFalse(tail["provisional"])
        self.assertTrue(tail["score_eligible"])
        self.assertTrue(tail["excluded_from_personal_baseline"])
        accounting = replay["classification_accounting"]
        self.assertEqual(accounting["no_data_s"], 0.0)
        self.assertEqual(accounting["actual_scored_s"], 65.0)
        self.assertEqual(accounting["occupied_in_pod_state_gap_s"], 0.0)
        self.assertTrue(accounting["occupied_state_invariant"]["holds"])
        self.assertEqual(accounting["accounted_s"], 65.0)
        self.assertTrue(accounting["arithmetic_invariant"]["holds"])
        self.assertEqual(
            replay["state_attribution_coverage_percent"], 100.0
        )
        self.assertEqual(
            replay["physiological_evidence_coverage_percent"], 46.2
        )

    def test_report_projection_preserves_exact_off_grid_boundaries(self):
        sensor_rows = [
            {"t": 30.0, "hr": 70.0, "rr": 15.0, "bed": "On bed"},
            {"t": 60.0, "hr": 65.0, "rr": 14.0, "bed": "On bed"},
            {"t": 85.0, "hr": None, "rr": None, "bed": None},
        ]
        states = [
            {
                "t": 30.0,
                "attribution_start": 0.0,
                "attribution_end": 30.0,
                "sample_interval_s": 30.0,
                "state": "wake",
                "score_eligible": True,
            },
            {
                "t": 75.0,
                "attribution_start": 30.0,
                "attribution_end": 75.0,
                "sample_interval_s": 45.0,
                "state": "n1",
                "score_eligible": True,
            },
        ]
        statuses = [{
            "t": 85.0,
            "attribution_start": 75.0,
            "attribution_end": 85.0,
            "sample_interval_s": 10.0,
            "state": "off_bed",
            "data_status": "confirmed_off_bed",
        }]

        rows, summary = project_replay_decisions_to_report_rows(
            sensor_rows,
            states,
            statuses,
            session_start=0.0,
            session_end=85.0,
        )

        self.assertEqual(
            [(row["sample_interval_s"], row.get("sleep")) for row in rows],
            [(30.0, "wake"), (30.0, "n1"), (15.0, "n1"), (10.0, None)],
        )
        self.assertEqual(rows[-1]["sleep_data_status"], "confirmed_off_bed")
        self.assertEqual(sum(row["sample_interval_s"] for row in rows), 85.0)
        self.assertEqual(summary["requested_seconds"], 85.0)

    def test_replay_never_pads_a_decision_beyond_session_end(self):
        replay = replay_session(
            [],
            0.0,
            85.0,
            baseline=self.replay_baseline(),
            rem_variability_weight=1.0,
        )

        decisions = [*replay["state_rows"], *replay["status_rows"]]
        self.assertTrue(decisions)
        self.assertLessEqual(max(row["t"] for row in decisions), 85.0)
        tail = replay["state_rows"][-1]
        self.assertEqual(tail["attribution_start"], 60.0)
        self.assertEqual(tail["sample_interval_s"], 25.0)
        self.assertTrue(tail["score_eligible"])
        self.assertTrue(
            replay["classification_accounting"]["arithmetic_invariant"][
                "holds"
            ]
        )
        self.assertEqual(
            replay["state_attribution_coverage_percent"], 100.0
        )
        self.assertEqual(
            replay["physiological_evidence_coverage_percent"], 0.0
        )

    def test_waso_uses_partial_tail_duration_instead_of_full_epoch(self):
        rows = [
            {"state": "n2", "sample_interval_s": 30.0},
            {"state": "wake", "sample_interval_s": 5.0},
        ]

        self.assertEqual(_duration_weighted_waso_seconds(rows), 5.0)

    def test_off_grid_three_bucket_exit_replaces_prior_stage_with_off_bed(self):
        buckets = [self.replay_bucket(index * 10) for index in range(1, 11)]
        for bucket in buckets[-3:]:
            bucket["status"] = 1

        with patch(
            "audit_sleep_history_shadow.make_buckets",
            return_value=buckets,
        ):
            replay = replay_session(
                [],
                0.0,
                100.0,
                baseline=self.replay_baseline(),
                rem_variability_weight=1.0,
            )

        off_bed = [
            row for row in replay["status_rows"]
            if row["state"] == "off_bed"
        ]
        self.assertEqual([row["t"] for row in off_bed], [90.0, 100.0])
        self.assertFalse(any(
            row["t"] == 90.0 for row in replay["state_rows"]
        ))

    def test_confirmed_off_bed_stays_latched_through_missing_buckets(self):
        buckets = [self.replay_bucket(index * 10) for index in range(1, 13)]
        for bucket in buckets[6:9]:
            bucket["status"] = 1
        for bucket in buckets[9:]:
            bucket.update({
                "status": None,
                "valid": False,
                "hr": None,
                "rr": None,
                "packet_count": 0,
                "paired_packets": 0,
            })

        with patch(
            "audit_sleep_history_shadow.make_buckets",
            return_value=buckets,
        ):
            replay = replay_session(
                [],
                0.0,
                120.0,
                baseline=self.replay_baseline(),
                rem_variability_weight=1.0,
            )

        self.assertEqual(
            [row["t"] for row in replay["status_rows"]],
            [90.0, 120.0],
        )
        self.assertFalse(any(
            row["t"] in {90.0, 120.0} for row in replay["state_rows"]
        ))
        self.assertEqual(
            replay["classification_accounting"]["off_bed_s"],
            60.0,
        )

    def test_return_within_epoch_does_not_backfill_wake_over_off_bed(self):
        buckets = [self.replay_bucket(index * 10) for index in range(1, 13)]
        for bucket in buckets[6:9]:
            bucket["status"] = 1
        buckets[9].update({
            "status": None,
            "valid": False,
            "hr": None,
            "rr": None,
            "packet_count": 0,
            "paired_packets": 0,
        })

        with patch(
            "audit_sleep_history_shadow.make_buckets",
            return_value=buckets,
        ):
            replay = replay_session(
                [],
                0.0,
                120.0,
                baseline=self.replay_baseline(),
                rem_variability_weight=1.0,
            )

        tail = replay["state_rows"][-1]
        self.assertEqual(tail["attribution_start"], 110.0)
        self.assertEqual(tail["attribution_end"], 120.0)
        self.assertEqual(tail["sample_interval_s"], 10.0)
        self.assertEqual(
            replay["classification_accounting"]["off_bed_s"],
            50.0,
        )
        self.assertEqual(
            replay["classification_accounting"]["actual_scored_s"],
            70.0,
        )
        self.assertTrue(
            replay["classification_accounting"]["arithmetic_invariant"][
                "holds"
            ]
        )

    def test_terminal_exit_with_valid_vitals_is_not_off_bed(self):
        buckets = [self.replay_bucket(index * 10) for index in range(1, 7)]
        tail_packet = {
            "timestamp": "1970-01-01T00:01:05+00:00",
            "status_code": 1,
            "heart_rate": 72.0,
            "respiration_rate": 16.0,
        }

        with patch(
            "audit_sleep_history_shadow.make_buckets",
            return_value=buckets,
        ):
            replay = replay_session(
                [tail_packet],
                0.0,
                65.0,
                baseline=self.replay_baseline(),
                rem_variability_weight=1.0,
            )

        self.assertFalse(replay["status_rows"])
        self.assertEqual(replay["state_rows"][-1]["t"], 65.0)
        self.assertEqual(replay["state_rows"][-1]["state"], "wake")

    def test_terminal_exit_without_returning_vitals_is_off_bed(self):
        buckets = [self.replay_bucket(index * 10) for index in range(1, 7)]
        tail_packet = {
            "timestamp": "1970-01-01T00:01:05+00:00",
            "status_code": 1,
            "heart_rate": None,
            "respiration_rate": None,
        }

        with patch(
            "audit_sleep_history_shadow.make_buckets",
            return_value=buckets,
        ):
            replay = replay_session(
                [tail_packet],
                0.0,
                65.0,
                baseline=self.replay_baseline(),
                rem_variability_weight=1.0,
            )

        self.assertEqual(replay["status_rows"][-1]["state"], "off_bed")
        self.assertEqual(replay["status_rows"][-1]["sample_interval_s"], 5.0)
        self.assertEqual(
            replay["classification_accounting"]["off_bed_s"],
            5.0,
        )

    def test_terminal_exit_preserves_occupied_prefix_of_partial_tail(self):
        buckets = [self.replay_bucket(index * 10) for index in range(1, 7)]
        tail_packets = [
            {
                "timestamp": "1970-01-01T00:01:05+00:00",
                "status_code": 0,
                "heart_rate": 72.0,
                "respiration_rate": 16.0,
            },
            {
                "timestamp": "1970-01-01T00:01:15+00:00",
                "status_code": 0,
                "heart_rate": 72.0,
                "respiration_rate": 16.0,
            },
            {
                "timestamp": "1970-01-01T00:01:25+00:00",
                "status_code": 1,
                "heart_rate": None,
                "respiration_rate": None,
            },
        ]

        with patch(
            "audit_sleep_history_shadow.make_buckets",
            return_value=buckets,
        ):
            replay = replay_session(
                tail_packets,
                0.0,
                85.0,
                baseline=self.replay_baseline(),
                rem_variability_weight=1.0,
            )

        tail_state = replay["state_rows"][-1]
        tail_off_bed = replay["status_rows"][-1]
        self.assertEqual(tail_state["attribution_start"], 60.0)
        self.assertEqual(tail_state["attribution_end"], 75.0)
        self.assertEqual(tail_state["sample_interval_s"], 15.0)
        self.assertEqual(tail_off_bed["attribution_start"], 75.0)
        self.assertEqual(tail_off_bed["attribution_end"], 85.0)
        self.assertEqual(tail_off_bed["sample_interval_s"], 10.0)
        accounting = replay["classification_accounting"]
        self.assertEqual(accounting["actual_scored_s"], 75.0)
        self.assertEqual(accounting["off_bed_s"], 10.0)
        self.assertTrue(accounting["arithmetic_invariant"]["holds"])

    def test_n2_challenger_needs_four_epochs_before_receiving_stage_time(self):
        path = ShadowPath()
        path.last = "n1"
        path.stage_since = 0.0
        path.cycle_has_n1 = True

        results = [
            path.step("n2", index * 30.0, False)
            for index in range(1, 5)
        ]

        self.assertEqual([stage for stage, _ in results], ["n1"] * 3 + ["n2"])
        for _, metadata in results[:3]:
            self.assertEqual(metadata["score_attribution_state"], "n1")
            self.assertFalse(metadata["challenger_counted_as_new_state"])
        self.assertEqual(
            [metadata["score_eligible"] for _, metadata in results],
            [True, True, True, True],
        )
        self.assertEqual(results[-1][1]["required"], 4)
        self.assertTrue(results[-1][1]["challenger_counted_as_new_state"])

    def test_signal_gap_preserves_confirmed_stage_and_first_onset(self):
        path = ShadowPath()
        path.last = "n2"
        path.stage_since = 150.0
        path.cycle_has_n1 = True
        path.sleep_onset_at = 30.0
        path.candidate = "rem"
        path.candidate_ticks = 1
        path.ema = {"rem": 0.8}

        path.observe_signal_gap()

        self.assertEqual(path.segment, 1)
        self.assertEqual(path.last, "n2")
        self.assertEqual(path.stage_since, 150.0)
        self.assertTrue(path.cycle_has_n1)
        self.assertEqual(path.sleep_onset_at, 30.0)
        self.assertIsNone(path.candidate)
        self.assertEqual(path.candidate_ticks, 0)
        self.assertIsNone(path.ema)

    def test_invalid_epoch_breaks_challenger_confirmation_like_live(self):
        path = ShadowPath()
        path.last = "n1"
        path.stage_since = 0.0
        path.cycle_has_n1 = True
        path.sleep_onset_at = 30.0
        path.candidate = "n2"
        path.candidate_ticks = 3
        path.continuity_hold_ticks = 3
        path.ema = {"n2": 0.8}

        path.interrupt_confirmation()

        self.assertEqual(path.last, "n1")
        self.assertEqual(path.stage_since, 0.0)
        self.assertTrue(path.cycle_has_n1)
        self.assertEqual(path.sleep_onset_at, 30.0)
        self.assertIsNone(path.candidate)
        self.assertEqual(path.candidate_ticks, 0)
        self.assertEqual(path.continuity_hold_ticks, 0)
        self.assertIsNone(path.ema)

    def test_confirmed_off_bed_starts_new_cycle_but_preserves_onset(self):
        path = ShadowPath()
        path.last = "n3"
        path.stage_since = 180.0
        path.cycle_has_n1 = True
        path.sleep_onset_at = 30.0
        path.candidate = "n2"
        path.candidate_ticks = 1

        path.observe_confirmed_off_bed(240.0)

        self.assertEqual(path.segment, 1)
        self.assertEqual(path.last, "wake")
        self.assertEqual(path.stage_since, 240.0)
        self.assertFalse(path.cycle_has_n1)
        self.assertEqual(path.sleep_onset_at, 30.0)
        self.assertFalse(path.allowed("n2", strong_wake=False))
        self.assertTrue(path.allowed("n1", strong_wake=False))
        self.assertIsNone(path.candidate)
        self.assertEqual(path.candidate_ticks, 0)
        self.assertTrue(path.off_bed_latched)

        path.observe_confirmed_return()

        self.assertFalse(path.off_bed_latched)

    def test_health_artifact_is_owner_only_even_when_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "replay.json"
            path.write_bytes(b"old")
            path.chmod(0o644)

            private_write_bytes(path, b"reviewed")

            self.assertEqual(path.read_bytes(), b"reviewed")
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_report_annotation_does_not_change_model_state_row(self):
        annotation = build_annotation(
            state="wake",
            start_time="2026-09-02T07:00:00+00:00",
            end_time="2026-09-02T07:01:00+00:00",
            source="participant_report",
            reason="confirmed awake",
        )
        annotations = load_annotations([{"value": annotation}])
        timestamp = datetime(
            2026, 9, 2, 7, 0, 30, tzinfo=timezone.utc
        ).timestamp()
        model_rows = [{"t": timestamp, "state": "n1", "metrics": {}}]
        evidence_rows = [{
            "t": timestamp,
            "probabilities": {"wake": 0.2, "n1": 0.8},
            "quality": {"winner_value": 0.8},
        }]

        report_rows, applied = report_state_rows_with_annotations(
            model_rows, evidence_rows, annotations
        )

        self.assertEqual(model_rows[0]["state"], "n1")
        self.assertEqual(report_rows[0]["model_state"], "n1")
        self.assertEqual(report_rows[0]["state"], "wake")
        self.assertEqual(report_rows[0]["confidence"], "high")
        self.assertEqual(applied, 1)

    def test_legacy_no_data_status_does_not_override_carried_state(self):
        report_rows = [
            {
                "_bucket_index": 0,
                "t": 30.0,
                "sleep": "wake",
                "sleep_score_eligible": True,
                "hr": 72.0,
                "rr": 16.0,
                "bed": "On bed",
            },
            {
                "_bucket_index": 1,
                "t": 60.0,
                "sleep": "n2",
                "sleep_score_eligible": True,
                "sleep_pending_state": "rem",
                "acoustic_corroborated": True,
                "hr": 70.0,
                "rr": 15.0,
                "bed": "On bed",
            },
            {
                "_bucket_index": 2,
                "t": 90.0,
                "sleep": "n1",
                "sleep_score_eligible": True,
                "hr": 68.0,
                "rr": 14.5,
                "bed": "On bed",
            },
        ]
        status_rows = [{
            "t": 60.0,
            "attribution_start": 30.0,
            "state": "no_data",
            "data_status": "invalid_or_missing_current_vitals_or_bcg",
            "reason": "Raw BCG coverage did not pass the current gate",
        }]

        states = [
            {
                "t": row["t"],
                "attribution_start": row["t"] - 30.0,
                "attribution_end": row["t"],
                "sample_interval_s": 30.0,
                "state": row["sleep"],
                "score_eligible": row["sleep_score_eligible"],
                "pending_state": row.get("sleep_pending_state"),
                "metrics": {
                    "auxiliary_evidence": {
                        "acoustic": {
                            "corroborated": row.get(
                                "acoustic_corroborated", False
                            )
                        }
                    }
                },
            }
            for row in report_rows
        ]
        report_rows, _ = project_replay_decisions_to_report_rows(
            report_rows,
            states,
            status_rows,
            session_start=0.0,
            session_end=90.0,
        )

        counts = {"wake": 1, "n1": 1, "n2": 1}
        night = {
            "estimated_sleep_s": 60.0,
            "sleep_efficiency": 2 / 3,
            "awakenings": 0,
            "waso_proxy_s": 0.0,
        }
        quality = build_sleep_quality(
            90.0,
            night,
            counts,
            completed=True,
            rest_mode="sleep",
            stage_sequence=report_rows,
            sensor_samples=report_rows,
            sample_interval_s=30.0,
            score_state_counts=counts,
        )
        report = build_session_report(
            90.0,
            report_rows,
            night,
            counts,
            quality,
            rest_mode="sleep",
            sample_interval_s=30.0,
            estimator_version="test",
            sleep_score_state_counts=counts,
        )
        accounting = report["sleep"]["classification_accounting"]

        self.assertNotIn("sleep_operational_state", report_rows[1])
        self.assertEqual(report_rows[1]["sleep"], "n2")
        self.assertEqual(report_rows[1]["sleep_pending_state"], "rem")
        self.assertTrue(report_rows[1]["acoustic_corroborated"])
        self.assertTrue(report_rows[1]["sleep_score_eligible"])
        self.assertEqual(accounting["no_data_s"], 0.0)
        self.assertEqual(accounting["score_eligible_s"], 90.0)
        self.assertEqual(report["sleep"]["actual_scored_s"], 90.0)
        self.assertTrue(accounting["display_stage_total_reconciles"])
        self.assertTrue(accounting["score_stage_total_reconciles"])
        self.assertTrue(accounting["arithmetic_invariant"]["holds"])


class ReplayModeContextTests(unittest.TestCase):
    @staticmethod
    def legacy_summary(*, mode="sleep", group="sleep", target=25_200):
        return {
            "target_duration_s": target,
            "session_report": {
                "rest_mode": {"resolved": mode, "group": group},
                "quality": {"score": 81},
            },
        }

    def test_canonical_mode_and_target_override_conflicting_legacy_summary(self):
        context = resolve_replay_mode_context(
            {"rest_mode": "nap_recovery", "target_duration_s": 1_800},
            self.legacy_summary(),
        )

        self.assertEqual(context["resolved"], "nap_recovery")
        self.assertEqual(context["group"], "nap_recovery")
        self.assertEqual(context["scoring_mode"], "nap_recovery")
        self.assertEqual(context["mode_source"], "sessions.rest_mode")
        self.assertEqual(context["target_duration_s"], 1_800)
        self.assertEqual(
            context["target_duration_source"],
            "sessions.target_duration_s",
        )
        self.assertEqual(context["old_score"], 81)

    def test_missing_canonical_values_use_auditable_legacy_fallback(self):
        context = resolve_replay_mode_context(
            {"rest_mode": None, "target_duration_s": None},
            self.legacy_summary(
                mode="short_nap", group="nap_recovery", target=5_400,
            ),
        )

        self.assertEqual(context["resolved"], "short_nap")
        self.assertEqual(context["group"], "nap_recovery")
        self.assertEqual(context["mode_source"], "legacy_final_summary")
        self.assertEqual(context["target_duration_s"], 5_400)
        self.assertEqual(
            context["target_duration_source"],
            "legacy_final_summary_duration_target",
        )

    def test_legacy_nested_duration_target_is_not_replaced_by_a_guess(self):
        summary = self.legacy_summary(
            mode="short_nap", group="nap_recovery", target=None,
        )
        summary["session_report"]["quality"]["duration_target"] = {
            "seconds": 5_400,
        }

        context = resolve_replay_mode_context(
            {"rest_mode": None, "target_duration_s": None},
            summary,
        )

        self.assertEqual(context["target_duration_s"], 5_400)
        self.assertEqual(
            context["target_duration_source"],
            "legacy_final_summary_duration_target",
        )

    def test_invalid_explicit_mode_stays_unresolved_instead_of_falling_back(self):
        context = resolve_replay_mode_context(
            {"rest_mode": "not-a-mode", "target_duration_s": 0},
            self.legacy_summary(),
        )

        self.assertEqual(context["resolved"], "not-a-mode")
        self.assertEqual(context["group"], "unresolved")
        self.assertEqual(context["scoring_mode"], "auto")
        self.assertEqual(context["mode_source"], "sessions.rest_mode")
        self.assertEqual(context["target_duration_s"], 0)
        self.assertEqual(
            context["target_duration_source"],
            "sessions.target_duration_s",
        )


class TargetedSessionSelectionTests(unittest.TestCase):
    CUTOFF_UTC = "2026-08-31T17:00:00+00:00"

    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.execute(
            "CREATE TABLE sessions ("
            "session_id TEXT PRIMARY KEY, start_time TEXT, end_time TEXT, "
            "duration REAL)"
        )
        rows = [
            (
                "eligible-later", "2026-09-01T02:00:00+00:00",
                "2026-09-01T02:31:00+00:00", 1_860,
            ),
            (
                "eligible-earlier", "2026-09-01T01:00:00+00:00",
                "2026-09-01T01:30:00+00:00", 1_800,
            ),
            (
                "too-short", "2026-09-01T03:00:00+00:00",
                "2026-09-01T03:25:00+00:00", 1_500,
            ),
            (
                "active", "2026-09-01T04:00:00+00:00", None, 1_800,
            ),
            (
                "before-cutover", "2026-08-31T16:59:59+00:00",
                "2026-08-31T17:30:00+00:00", 1_800,
            ),
        ]
        self.connection.executemany(
            "INSERT INTO sessions VALUES (?,?,?,?)", rows
        )

    def tearDown(self):
        self.connection.close()

    def test_omitted_allowlist_preserves_full_eligible_cohort_query(self):
        rows, provenance = select_session_rows(
            self.connection,
            session_ids=None,
            cutoff_utc=self.CUTOFF_UTC,
            minimum_minutes=25,
        )

        self.assertEqual(
            [row["session_id"] for row in rows],
            ["eligible-earlier", "eligible-later"],
        )
        self.assertEqual(provenance["mode"], "eligible_cohort_query")
        self.assertFalse(provenance["operator_supplied"])
        self.assertNotIn("requested_session_ids", provenance)

    def test_explicit_allowlist_selects_only_requested_eligible_sessions(self):
        rows, provenance = select_session_rows(
            self.connection,
            session_ids=["eligible-later", "eligible-earlier"],
            cutoff_utc=self.CUTOFF_UTC,
            minimum_minutes=25,
        )

        self.assertEqual(
            [row["session_id"] for row in rows],
            ["eligible-earlier", "eligible-later"],
        )
        self.assertEqual(provenance["mode"], "explicit_session_allowlist")
        self.assertEqual(
            provenance["requested_session_ids"],
            ["eligible-later", "eligible-earlier"],
        )
        self.assertEqual(
            provenance["selected_session_ids"],
            ["eligible-earlier", "eligible-later"],
        )
        self.assertEqual(len(provenance["allowlist_sha256"]), 64)

    def test_explicit_allowlist_rejects_every_ineligible_reason_atomically(self):
        with self.assertRaisesRegex(
            ValueError,
            "missing=session_not_found.*active=session_not_completed.*"
            "too-short=session_duration_not_above_minimum.*"
            "before-cutover=session_before_cutover",
        ):
            select_session_rows(
                self.connection,
                session_ids=[
                    "missing", "active", "too-short", "before-cutover",
                ],
                cutoff_utc=self.CUTOFF_UTC,
                minimum_minutes=25,
            )

    def test_allowlist_normalization_deduplicates_but_rejects_blank(self):
        self.assertEqual(
            normalize_session_allowlist([" session-a ", "session-a"]),
            ["session-a"],
        )
        with self.assertRaisesRegex(ValueError, "cannot be blank"):
            normalize_session_allowlist([" "])


if __name__ == "__main__":
    unittest.main()
