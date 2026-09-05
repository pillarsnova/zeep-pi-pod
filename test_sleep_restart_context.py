"""Regression tests for Sleep physiology continuity across code updates."""

from __future__ import annotations

import unittest

from zeep_pod.sessions.sleep_context import (
    checkpoint_sleep_context,
    restore_sleep_context,
)


class SleepRestartContextTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
