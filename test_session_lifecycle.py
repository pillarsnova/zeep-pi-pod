"""Unit tests for Session lifecycle rules outside the composition root."""

from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from zeep_pod.sessions.lifecycle import (
    SessionCheckpointStore,
    bed_is_occupied,
    evaluate_vital_start_gate,
)


class SessionCheckpointStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.path = Path(self.temporary_directory.name) / "checkpoint.json"

    @staticmethod
    def active_session() -> dict[str, object]:
        return {
            "phase": "waiting_bed",
            "owner_auth_session_id": "browser-session",
            "onbed_since": time.monotonic() - 5,
            "auth": {
                "access_token": "must-not-be-persisted",
                "password": "also-secret",
            },
            "record": {
                "session_id": "session-1",
                "username": "person@example.test",
                "username_key": "person@example.test",
                "identity_subject": "zeep:person-1",
                "pod_id": "pod-1",
                "rest_mode": "overnight",
                "private_field": "must-not-be-persisted",
            },
            "sleep_context": {
                "session_id": "session-1",
                "awake_vital_pairs": [
                    [1_000.0 + index * 10.0, 76.0 - index, 18.0 - index / 10]
                    for index in range(6)
                ],
                "awake_hr_reference": 74.0,
                "awake_rr_reference": 17.8,
                "sleep_onset_at": 1_060.0,
                "last_valid_frame_t": 1_120.0,
                "private_note": "must-not-be-persisted",
            },
        }

    def test_round_trip_persists_only_allowlisted_fields(self) -> None:
        store = SessionCheckpointStore(self.path, bed_start_seconds=20)
        payload = store.save(self.active_session())

        serialized = self.path.read_text(encoding="utf-8")
        self.assertNotIn("must-not-be-persisted", serialized)
        self.assertNotIn("also-secret", serialized)
        self.assertNotIn("private_note", serialized)
        self.assertEqual(payload, store.load())
        self.assertLessEqual(payload["onbed_elapsed_s"], 20)
        self.assertEqual(
            payload["sleep_context"]["awake_hr_reference"], 74.0
        )
        self.assertEqual(
            len(payload["sleep_context"]["awake_vital_pairs"]), 6
        )

    def test_sleep_context_must_belong_to_the_same_session(self) -> None:
        store = SessionCheckpointStore(self.path, bed_start_seconds=20)
        active = self.active_session()
        active["sleep_context"]["session_id"] = "another-session"

        with self.assertRaisesRegex(ValueError, "belongs to another session"):
            store.save(active)

    def test_invalid_checkpoint_is_rejected_and_reported(self) -> None:
        errors: list[str] = []
        self.path.write_text(json.dumps({"schema_version": 99}), encoding="utf-8")
        store = SessionCheckpointStore(
            self.path,
            bed_start_seconds=20,
            on_invalid=lambda exc: errors.append(str(exc)),
        )

        self.assertIsNone(store.load())
        self.assertEqual(errors, ["unsupported checkpoint version"])


class SessionVitalGateTests(unittest.TestCase):
    @staticmethod
    def valid_bcg(now_epoch_s: float) -> dict[str, object]:
        return {
            "connected": True,
            "last_update": now_epoch_s,
            "status_code": 0,
            "heart_rate_current_valid": True,
            "respiration_current_valid": True,
            "heart_rate_held": False,
            "respiration_held": False,
            "packets": 103,
            "vital_valid_streak": 3,
        }

    def test_gate_requires_new_valid_packets_after_login(self) -> None:
        now_epoch_s = 1_000.0
        result = evaluate_vital_start_gate(
            self.valid_bcg(now_epoch_s),
            {"vital_gate_start_packet_count": 100},
            now_epoch_s=now_epoch_s,
            stale_seconds=5,
            on_bed_codes={0},
            required_packets=3,
        )

        self.assertTrue(result["ready"])
        self.assertEqual(result["confirmed_packets"], 3)
        self.assertEqual(result["reason"], "ready")

    def test_held_or_stale_vitals_never_start_recording(self) -> None:
        now_epoch_s = 1_000.0
        held = self.valid_bcg(now_epoch_s)
        held["heart_rate_held"] = True
        held_result = evaluate_vital_start_gate(
            held,
            {"vital_gate_start_packet_count": 100},
            now_epoch_s=now_epoch_s,
            stale_seconds=5,
            on_bed_codes={0},
            required_packets=3,
        )
        stale = self.valid_bcg(now_epoch_s - 10)
        stale_result = evaluate_vital_start_gate(
            stale,
            {"vital_gate_start_packet_count": 100},
            now_epoch_s=now_epoch_s,
            stale_seconds=5,
            on_bed_codes={0},
            required_packets=3,
        )

        self.assertFalse(held_result["ready"])
        self.assertEqual(held_result["reason"], "waiting_for_hr")
        self.assertFalse(stale_result["ready"])
        self.assertEqual(stale_result["reason"], "waiting_for_bcg")

    def test_bed_occupancy_requires_a_fresh_packet(self) -> None:
        now_epoch_s = 1_000.0
        self.assertTrue(
            bed_is_occupied(
                self.valid_bcg(now_epoch_s),
                now_epoch_s=now_epoch_s,
                stale_seconds=5,
                on_bed_codes={0},
            )
        )
        self.assertFalse(
            bed_is_occupied(
                self.valid_bcg(now_epoch_s - 6),
                now_epoch_s=now_epoch_s,
                stale_seconds=5,
                on_bed_codes={0},
            )
        )


if __name__ == "__main__":
    unittest.main()
