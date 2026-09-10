import sqlite3
import stat
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from audit_sleep_history_shadow import (
    ShadowPath,
    normalize_session_allowlist,
    private_write_bytes,
    report_state_rows_with_annotations,
    select_session_rows,
)
from sleep_stage_annotations import build_annotation, load_annotations


class ShadowPathParityTests(unittest.TestCase):
    def test_pending_allowed_transition_holds_previous_confirmed_state(self):
        path = ShadowPath()
        path.last = "wake"
        path.stage_since = 0.0

        held, metadata = path.step("n1", 100.0, False)

        self.assertEqual(held, "wake")
        self.assertEqual(metadata["confirmed_state"], "wake")
        self.assertEqual(metadata["decision"], "confirming")

    def test_initial_state_is_not_published_before_confirmation(self):
        path = ShadowPath()

        first, _ = path.step("wake", 30.0, False)
        second, metadata = path.step("wake", 60.0, False)

        self.assertIsNone(first)
        self.assertEqual(second, "wake")
        self.assertEqual(metadata["decision"], "confirmed")

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
