"""Regression coverage for the bounded live initial WAIT contract."""

from __future__ import annotations

import copy
import time
import unittest

import app
from zeep_pod.sessions.sleep_runtime_evidence import (
    INITIAL_WAIT_HARD_CAP_SECONDS,
    enforce_initial_wait_hard_cap,
    sleep_status_event,
)


def waiting_result() -> dict[str, object]:
    return {
        "state": "no_data",
        "confirmed_state": None,
        "classification_active": False,
        "data_status": "confirming_initial_state",
        "score_eligible": False,
        "provisional": True,
    }


class InitialWaitHardCapTests(unittest.TestCase):
    def test_wait_remains_available_before_120_seconds(self) -> None:
        result = enforce_initial_wait_hard_cap(
            waiting_result(),
            elapsed_seconds=119.9,
            maximum_seconds=INITIAL_WAIT_HARD_CAP_SECONDS,
            sleep_states=("wake", "n1", "n2", "n3", "rem"),
        )
        self.assertEqual(result["data_status"], "confirming_initial_state")

    def test_wait_becomes_unscored_no_data_at_120_seconds(self) -> None:
        result = enforce_initial_wait_hard_cap(
            waiting_result(),
            elapsed_seconds=120.0,
            maximum_seconds=INITIAL_WAIT_HARD_CAP_SECONDS,
            sleep_states=("wake", "n1", "n2", "n3", "rem"),
        )
        self.assertEqual(result["state"], "no_data")
        self.assertEqual(result["data_status"], "initial_confirmation_timeout")
        self.assertFalse(result["classification_active"])
        self.assertFalse(result["score_eligible"])

        event = sleep_status_event(
            result,
            session_id="wait-cap",
            epoch_s=1_000.0,
            evidence_epoch_s=30.0,
            provenance={},
        )
        self.assertEqual(event["value"]["state"], "no_data")
        self.assertNotIn("WAIT", event["value"]["label"])

    def test_confirmed_state_is_never_replaced_by_timeout(self) -> None:
        confirmed = {
            "state": "n2",
            "confirmed_state": "n2",
            "classification_active": True,
            "data_status": "live",
            "score_eligible": True,
        }
        result = enforce_initial_wait_hard_cap(
            confirmed,
            elapsed_seconds=900.0,
            maximum_seconds=INITIAL_WAIT_HARD_CAP_SECONDS,
            sleep_states=("wake", "n1", "n2", "n3", "rem"),
        )
        self.assertEqual(result, confirmed)

    def test_between_epoch_path_uses_recording_wall_clock(self) -> None:
        now = time.time()
        with app.state_lock:
            original_session = copy.deepcopy(app.state["session"])
            app.state["session"].update({
                "active": True,
                "recording": True,
                "session_id": "wait-cap",
                "started_at": now - 121.0,
            })
        with app.sleep_path_lock:
            original_path = copy.deepcopy(app._sleep_stage_path)
            app._reset_sleep_stage_path("wait-cap")
        try:
            result = app._sleep_value_between_evidence_epochs(
                {
                    "t": now,
                    "bcg_valid": True,
                    "status": 0,
                    "confirmed_status": 0,
                    "bed_exit_evidence": {"confirmed": False},
                },
                "wait-cap",
                {"next_evidence_s": 20.0},
            )
            self.assertEqual(
                result["data_status"],
                "initial_confirmation_timeout",
            )
            self.assertFalse(result["score_eligible"])
        finally:
            with app.sleep_path_lock:
                app._sleep_stage_path.clear()
                app._sleep_stage_path.update(original_path)
            with app.state_lock:
                app.state["session"] = original_session


if __name__ == "__main__":
    unittest.main()
