import sqlite3
import stat
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from audit_sleep_history_shadow import (
    ShadowPath,
    apply_replay_statuses_to_report_rows,
    normalize_session_allowlist,
    private_write_bytes,
    replay_session,
    report_state_rows_with_annotations,
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
        self.assertTrue(metadata["provisional"])
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
            [True, True, False, False],
        )
        self.assertEqual(
            [metadata["score_eligible"] for _, metadata in results],
            [False, False, True, True],
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

    def test_initial_state_is_not_published_before_confirmation(self):
        path = ShadowPath()

        first, first_metadata = path.step("wake", 30.0, False)
        second, metadata = path.step("wake", 60.0, False)

        self.assertIsNone(first)
        self.assertEqual(
            first_metadata["decision_kind"], "initial_confirmation_wait"
        )
        self.assertEqual(second, "wake")
        self.assertEqual(metadata["decision"], "confirmed")

    def test_replay_confirms_initial_wake_at_sixty_seconds_like_live(self):
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

        self.assertEqual(
            [row["t"] for row in replay["status_rows"] if row["state"] == "wait"],
            [30.0],
        )
        self.assertEqual(
            [(row["t"], row["state"]) for row in replay["state_rows"]],
            [(60.0, "wake")],
        )

    def test_partial_final_epoch_is_explicit_unscored_no_data(self):
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

        tail = replay["status_rows"][-1]
        self.assertEqual(tail["t"], 65.0)
        self.assertEqual(tail["attribution_start"], 60.0)
        self.assertEqual(tail["sample_interval_s"], 5.0)
        self.assertEqual(tail["state"], "no_data")
        self.assertEqual(tail["data_status"], "incomplete_final_epoch")
        self.assertTrue(tail["excluded_from_score"])
        accounting = replay["classification_accounting"]
        self.assertEqual(accounting["no_data_s"], 5.0)
        self.assertEqual(accounting["accounted_s"], 65.0)
        self.assertTrue(accounting["arithmetic_invariant"]["holds"])

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
        tail = next(
            row for row in replay["status_rows"]
            if row["data_status"] == "incomplete_final_epoch"
        )
        self.assertEqual(tail["attribution_start"], 60.0)
        self.assertEqual(tail["sample_interval_s"], 25.0)
        self.assertTrue(
            replay["classification_accounting"]["arithmetic_invariant"][
                "holds"
            ]
        )

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
        self.assertEqual([row["t"] for row in off_bed], [90.0])
        self.assertFalse(any(
            row["t"] == 90.0 for row in replay["state_rows"]
        ))

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
            [False, False, True, True],
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

    def test_bcg_invalid_status_overrides_valid_timeline_vitals_in_report(self):
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

        apply_replay_statuses_to_report_rows(
            report_rows,
            status_rows,
            session_start=0.0,
        )

        counts = {"wake": 1, "n1": 1}
        night = {
            "estimated_sleep_s": 30.0,
            "sleep_efficiency": 0.5,
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

        self.assertEqual(report_rows[1]["sleep_operational_state"], "no_data")
        self.assertIsNone(report_rows[1]["sleep"])
        self.assertIsNone(report_rows[1]["sleep_pending_state"])
        self.assertFalse(report_rows[1]["acoustic_corroborated"])
        self.assertFalse(report_rows[1]["sleep_score_eligible"])
        self.assertEqual(accounting["no_data_s"], 30.0)
        self.assertEqual(accounting["score_eligible_s"], 60.0)
        self.assertEqual(report["sleep"]["actual_scored_s"], 60.0)
        self.assertTrue(accounting["display_stage_total_reconciles"])
        self.assertTrue(accounting["score_stage_total_reconciles"])
        self.assertTrue(accounting["arithmetic_invariant"]["holds"])


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
