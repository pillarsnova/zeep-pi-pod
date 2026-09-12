"""Regression coverage for the no-gap initial Recording contract."""

from __future__ import annotations

import copy
import time
import unittest
from unittest.mock import patch

from testing_support import configure_app_test_environment

configure_app_test_environment()
import app


class InitialRecordingContinuityTests(unittest.TestCase):
    def setUp(self) -> None:
        with app.state_lock:
            self.original_session = copy.deepcopy(app.state["session"])
        with app.sleep_path_lock:
            self.original_path = copy.deepcopy(app._sleep_stage_path)
        with app.analysis_frame_lock:
            self.original_frame = copy.deepcopy(app._analysis_frame)
        self.original_cache = copy.deepcopy(app._sleep_cache)
        with app.session_lock:
            self.original_active = app._active_session

    def tearDown(self) -> None:
        with app.sleep_path_lock:
            app._sleep_stage_path.clear()
            app._sleep_stage_path.update(self.original_path)
        with app.state_lock:
            app.state["session"] = self.original_session
        with app.analysis_frame_lock:
            app._analysis_frame = self.original_frame
        app._sleep_cache.clear()
        app._sleep_cache.update(self.original_cache)
        with app.session_lock:
            app._active_session = self.original_active

    def evaluate(self, *, recording: bool, elapsed_s: float) -> dict:
        now = time.time()
        with app.state_lock:
            app.state["session"].update({
                "active": True,
                "recording": recording,
                "session_id": "initial-continuity",
                "started_at": now - elapsed_s,
            })
        with app.sleep_path_lock:
            app._reset_sleep_stage_path("initial-continuity")
        return app._sleep_value_between_evidence_epochs(
            {
                "t": now,
                "bcg_valid": True,
                "status": 0,
                "confirmed_status": 0,
                "bed_exit_evidence": {"confirmed": False},
            },
            "initial-continuity",
            {"next_evidence_s": 20.0},
        )

    def test_recording_starts_with_scoreable_wake(self) -> None:
        result = self.evaluate(recording=True, elapsed_s=1.0)

        self.assertEqual(result["state"], "wake")
        self.assertEqual(result["confirmed_state"], "wake")
        self.assertEqual(result["data_status"], "initial_awake_anchor")
        self.assertTrue(result["classification_active"])
        self.assertTrue(result["score_eligible"])
        self.assertFalse(result["provisional"])

    def test_elapsed_wall_clock_cannot_create_wait_or_no_data(self) -> None:
        result = self.evaluate(recording=True, elapsed_s=3_600.0)

        self.assertEqual(result["state"], "wake")
        self.assertNotIn(
            result["data_status"],
            {"confirming_initial_state", "initial_confirmation_timeout"},
        )
        self.assertTrue(result["score_eligible"])

    def test_waiting_for_vitals_exists_only_before_recording(self) -> None:
        result = self.evaluate(recording=False, elapsed_s=3_600.0)

        self.assertEqual(result["state"], "no_data")
        self.assertEqual(result["data_status"], "waiting_for_vitals")
        self.assertFalse(result["classification_active"])
        self.assertFalse(result["score_eligible"])

    def test_live_cache_starts_recording_at_scoreable_wake(self) -> None:
        with app.state_lock:
            app.state["session"].update({
                "active": True,
                "recording": True,
                "session_id": "cache-start",
            })
        with app.analysis_frame_lock:
            app._analysis_frame = None
        app._sleep_cache.update({
            "t": 0.0,
            "value": None,
            "session_id": "cache-start",
            "sequence": None,
        })

        result = app.sleep_state_cached()

        self.assertEqual(result["state"], "wake")
        self.assertEqual(result["data_status"], "initial_awake_anchor")
        self.assertTrue(result["classification_active"])
        self.assertTrue(result["score_eligible"])

    def test_data_gap_status_cannot_be_persisted_during_recording(self) -> None:
        with app.state_lock:
            app.state["session"].update({
                "active": True,
                "recording": True,
                "session_id": "status-guard",
            })
        with app.session_lock:
            app._active_session = {
                "phase": "recording",
                "record": {"session_id": "status-guard"},
            }
        with patch.object(app.database, "enqueue") as enqueue:
            app._persist_sleep_stage_status(
                {
                    "state": "no_data",
                    "data_status": "waiting_for_sensor_frame",
                },
                epoch_s=time.time(),
            )

        enqueue.assert_not_called()


if __name__ == "__main__":
    unittest.main()
