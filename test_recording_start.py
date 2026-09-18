"""Recording must not become visible before its Session row is durable."""

from __future__ import annotations

import threading
import unittest
from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import Mock

from sessions.recording_start import RecordingStartPorts, begin_recording


class RecordingStartTests(unittest.TestCase):
    def setUp(self) -> None:
        self.active = {
            "phase": "waiting_bed",
            "record": {
                "session_id": "test-session",
                "username": "coded-tester",
                "username_key": "coded-tester",
                "gender": "unspecified",
                "armed_at_utc": "2026-09-19T00:00:00+00:00",
                "sample_interval_s": 10.0,
            },
        }
        self.events = []

        def event(name):
            def capture(*args, **kwargs):
                self.events.append(name)
                return True
            return capture

        self.ports = RecordingStartPorts(
            session_lock=threading.RLock(),
            state_lock=threading.RLock(),
            get_active=lambda: self.active,
            vital_gate=lambda active: {"ready": True, "reason": "ready"},
            enqueue=event("enqueue"),
            flush=event("flush"),
            reset_inference=event("reset_inference"),
            start_bcg=event("start_bcg"),
            patch_projection=event("publish"),
            save_checkpoint=event("checkpoint"),
            log_event=event("log"),
            clock=lambda: 100.0,
            monotonic=lambda: 25.0,
            utc_now=lambda: datetime(2026, 9, 19, tzinfo=UTC),
        )

    def start(self, ports=None):
        begin_recording(
            self.active,
            ports=ports or self.ports,
            default_interval_s=10.0,
            bed_start_seconds=20.0,
            required_packets=3,
        )

    def test_durable_start_preserves_side_effect_order(self):
        self.start()
        self.assertEqual(self.events, [
            "enqueue", "flush", "reset_inference", "start_bcg",
            "publish", "checkpoint", "log",
        ])
        self.assertEqual(self.active["phase"], "recording")
        self.assertEqual(self.active["last_sample"], float("-inf"))
        self.assertEqual(self.active["record"]["started_monotonic"], 25.0)

    def test_lost_vitals_do_not_create_recording_or_storage_writes(self):
        ports = replace(self.ports, vital_gate=lambda active: {
            "ready": False, "reason": "missing_rr",
        })
        with self.assertRaisesRegex(RuntimeError, "missing_rr"):
            self.start(ports)
        self.assertEqual(self.events, [])
        self.assertEqual(self.active["phase"], "waiting_bed")

    def test_failed_flush_does_not_start_bcg_or_publish_recording(self):
        ports = replace(self.ports, flush=Mock(return_value=False))
        with self.assertRaisesRegex(RuntimeError, "did not flush"):
            self.start(ports)
        self.assertEqual(self.events, ["enqueue"])
        self.assertEqual(self.active["phase"], "waiting_bed")

    def test_replaced_session_does_not_publish_or_checkpoint_old_occupant(self):
        ports = replace(self.ports, get_active=lambda: None)
        with self.assertRaisesRegex(RuntimeError, "active Session changed"):
            self.start(ports)
        self.assertNotIn("publish", self.events)
        self.assertNotIn("checkpoint", self.events)
        self.assertEqual(self.active["phase"], "waiting_bed")


if __name__ == "__main__":
    unittest.main()
