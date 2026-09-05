import unittest
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from audit_sleep_history_shadow import (
    ShadowPath,
    private_write_bytes,
    report_state_rows_with_annotations,
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
        self.assertEqual(applied, 1)


if __name__ == "__main__":
    unittest.main()
