"""Characterize restart orchestration without databases or hardware I/O."""

from __future__ import annotations

import unittest
from contextlib import ExitStack
from copy import deepcopy
from unittest.mock import Mock, patch

from sessions.restart_timeline import restore_timeline
from testing_support import configure_app_test_environment

configure_app_test_environment()

import app as pod_app  # noqa: E402


class SessionRestartTests(unittest.TestCase):
    def setUp(self) -> None:
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.row = {
            "session_id": "restart-case",
            "user": "person@example.test",
            "username_key": "person@example.test",
            "gender": "female",
            "identity_subject": "zeep:coded-person",
            "pod_id": "test-pod",
            "zeep_public_id": "coded-person",
            "rest_mode": "nap_recovery",
            "target_duration_s": 5400,
            "start_time": "2026-09-18T12:00:00+00:00",
            "created_at": "2026-09-18T11:59:00+00:00",
            "end_time": None,
            "end_reason": None,
        }
        self.profile = {"age": 38, "display_name": "Test Person", "sessions": 4}
        self.checkpoint = {
            "phase": "recording",
            "owner_auth_session_id": "browser-owner",
            "sleep_context": {"session_id": "restart-case"},
            "record": {
                "session_id": "restart-case",
                "username": self.row["user"],
                "username_key": self.row["username_key"],
                "identity_subject": self.row["identity_subject"],
                "pod_id": "test-pod",
                "rest_mode": "nap_recovery",
                "target_duration_s": 1800,
                "sample_interval_s": 5.0,
                "armed_at_utc": self.row["created_at"],
                "wellness_context": {"caffeine": "none"},
            },
        }
        self.timeline = [
            {
                "timestamp": self.row["start_time"],
                "temperature": 24.5,
                "humidity": 51,
                "sound": 42.1,
                "heart_rate": 63,
                "respiration_rate": 14,
                "bed_status": 0,
                "acoustic_label": "steady_mechanical",
                "acoustic_event_detected": 1,
                "acoustic_features_json": '{"centroid_hz": 120}',
            }
        ]
        self.calls = Mock()
        self.database = Mock(read_sessions=Mock(side_effect=self.read_sessions))
        self.database.flush.return_value = True
        self.calls.attach_mock(self.database.enqueue, "enqueue")
        self.calls.attach_mock(self.database.flush, "flush")
        self.replace("database", self.database)
        self.replace("_active_session", None)
        self.replace("_sleep_stage_path", {})
        self.replace(
            "_load_active_session_checkpoint", Mock(return_value=self.checkpoint)
        )
        self.replace("_clear_active_session_checkpoint", Mock())
        self.replace(
            "_load_profiles",
            Mock(return_value={self.row["username_key"]: self.profile}),
        )
        self.replace("_save_profiles", Mock())
        self.replace(
            "_restore_safety_checkpoint_context", Mock(return_value={"armed": True})
        )
        self.replace(
            "_current_safety_checkpoint_context", Mock(return_value={"armed": True})
        )
        self.replace("_reset_live_sleep_inference", Mock())
        self.replace("_reset_sleep_stage_path", Mock())
        self.replace("rest_window", Mock(return_value={"available": False}))
        self.replace("occupancy_client", Mock())
        self.replace(
            "session_vital_gate_now",
            Mock(return_value={"ready": False, "reason": "waiting_for_bcg"}),
        )
        self.replace(
            "restore_session_sleep_context",
            Mock(
                return_value={
                    "path": {
                        "stage": "n2",
                        "sleep_onset_at": 123,
                        "awake_hr_reference": 74,
                    },
                    "provenance": {"source": "checkpoint"},
                }
            ),
        )
        self.replace(
            "session_availability_by_account",
            Mock(
                return_value={
                    self.row["username_key"]: {
                        "lifetime_sessions": 3,
                        "last_data_session_utc": "previous",
                    }
                }
            ),
        )
        for name, alias in (
            ("_replace_session_projection_locked", "publish"),
            ("_save_active_session_checkpoint", "checkpoint"),
            ("log_event", "log"),
        ):
            mock = self.replace(name, Mock())
            self.calls.attach_mock(mock, alias)
        bcg = self.replace("bcg_storage", Mock())
        self.calls.attach_mock(bcg.start_session, "bcg")
        self.stack.enter_context(
            patch.object(pod_app.time, "time", return_value=1_789_739_000.0)
        )
        self.stack.enter_context(
            patch.object(pod_app.time, "monotonic", return_value=5000.0)
        )

    def replace(self, name, value):
        self.stack.enter_context(patch.object(pod_app, name, value))
        return value

    def read_sessions(self, query, params=()):
        if "FROM timeline" in query:
            return self.timeline
        if "FROM events" in query:
            return [{"type": "sleep_status", "n": 3}]
        if "end_time IS NULL" in query:
            return [self.row] if self.row and not self.row["end_time"] else []
        return [self.row] if self.row else []

    def test_recording_preserves_identity_intent_context_and_samples(self) -> None:
        self.assertEqual(pod_app._restore_interrupted_session(), "restart-case")
        active = pod_app._active_session
        record = active["record"]
        self.assertEqual(record["target_duration_s"], 1800)
        self.assertEqual(record["rest_mode"], "nap_recovery")
        self.assertEqual(record["wellness_context"], {"caffeine": "none"})
        self.assertEqual(record["started_at_utc"], self.row["start_time"])
        self.assertEqual(record["sample_interval_s"], pod_app.SESSION_SAMPLE_SECONDS)
        self.assertEqual(active["samples"][0]["sample_interval_s"], 5)
        self.assertEqual(
            active["samples"][0]["acoustic_features"], {"centroid_hz": 120}
        )
        self.assertEqual(active["samples"][0]["dba"], 42.1)
        self.assertIsNone(active["samples"][0]["sleep"])
        self.assertEqual(active["owner_auth_session_id"], "browser-owner")
        self.assertEqual(active["safety_context"], {"armed": True})
        self.assertEqual(active["counters"], {"sleep_status": 3})
        self.assertEqual(pod_app._sleep_stage_path["awake_hr_reference"], 74)
        self.assertEqual(pod_app._sleep_stage_path["stage"], "n2")
        public = pod_app._replace_session_projection_locked.call_args.args[0]
        self.assertTrue(public["recording"])
        self.assertEqual(public["vital_gate"]["reason"], "recording_resumed")
        self.assertEqual(public["samples"], 1)
        self.assertTrue(public["wellness_context_available"])
        pod_app._save_active_session_checkpoint.assert_called_once_with(active)
        self.assertEqual(
            [call[0] for call in self.calls.mock_calls],
            ["bcg", "publish", "enqueue", "log", "log", "checkpoint"],
        )

    def test_waiting_checkpoint_with_committed_row_resumes_recording(self) -> None:
        self.checkpoint["phase"] = "waiting_bed"
        pod_app._restore_interrupted_session()
        self.assertEqual(self.checkpoint["phase"], "recording")
        self.assertEqual(
            self.checkpoint["record"]["started_at_utc"], self.row["start_time"]
        )
        self.assertEqual(pod_app._active_session["phase"], "recording")

    def test_waiting_login_is_not_promoted_without_a_row(self) -> None:
        self.row = None
        self.checkpoint["phase"] = "waiting_bed"
        pod_app._restore_interrupted_session()
        active = pod_app._active_session
        self.assertEqual(active["phase"], "waiting_bed")
        self.assertIsNone(active["onbed_since"])
        self.assertIsNone(active["record"]["started_monotonic"])
        self.assertEqual(active["samples"], [])
        self.assertEqual(active["owner_auth_session_id"], "browser-owner")
        pod_app.bcg_storage.start_session.assert_not_called()
        self.database.enqueue.assert_not_called()

    def test_explicitly_ended_session_is_never_reopened(self) -> None:
        self.row.update(end_time="2026-09-18T13:00:00+00:00", end_reason="logout")
        self.assertIsNone(pod_app._restore_interrupted_session())
        self.assertIsNone(pod_app._active_session)
        pod_app._clear_active_session_checkpoint.assert_called_once()
        pod_app.bcg_storage.start_session.assert_not_called()

    def test_legacy_shutdown_flushes_before_bcg_and_reconciles_count(self) -> None:
        self.row.update(
            end_time="2026-09-18T13:00:00+00:00", end_reason="server_shutdown"
        )
        self.assertEqual(pod_app._restore_interrupted_session(), "restart-case")
        self.assertEqual(self.profile["sessions"], 3)
        self.assertEqual(self.profile["last_session_utc"], "previous")
        self.assertEqual(
            [call[0] for call in self.calls.mock_calls][:3], ["enqueue", "flush", "bcg"]
        )
        self.database.flush.assert_called_once_with(30)

    def test_failed_legacy_flush_does_not_start_bcg_or_publish(self) -> None:
        self.row.update(end_reason="server_shutdown")
        self.database.flush.return_value = False
        with self.assertRaisesRegex(RuntimeError, "flush session resume"):
            pod_app._restore_interrupted_session()
        pod_app.bcg_storage.start_session.assert_not_called()
        pod_app._replace_session_projection_locked.assert_not_called()

    def test_coordinator_failure_keeps_recording_with_degraded_lease(self) -> None:
        pod_app.occupancy_client.acquire.side_effect = pod_app.CoordinatorUnavailable(
            "offline"
        )
        self.assertEqual(pod_app._restore_interrupted_session(), "restart-case")
        self.assertIsNone(pod_app._active_session["occupancy_lease"])
        self.assertEqual(pod_app._active_session["occupancy_error"], "offline")
        self.assertEqual(pod_app._active_session["phase"], "recording")

    def test_checkpoint_refresh_failure_is_reported_without_eviction(self) -> None:
        pod_app._save_active_session_checkpoint.side_effect = OSError(
            "disk unavailable"
        )
        self.assertEqual(pod_app._restore_interrupted_session(), "restart-case")
        pod_app.log_event.assert_called_with(
            "session", "restart_checkpoint_refresh_failed", error="disk unavailable"
        )
        self.assertEqual(pod_app._active_session["phase"], "recording")

    def test_unresolved_intent_stays_auto_on_legacy_open_row(self) -> None:
        pod_app._load_active_session_checkpoint.return_value = None
        self.row.update(rest_mode=None, target_duration_s=None)
        self.assertEqual(pod_app._restore_interrupted_session(), "restart-case")
        self.assertEqual(pod_app._active_session["record"]["rest_mode"], "auto")
        self.assertIsNone(pod_app._active_session["record"]["target_duration_s"])

    def test_idle_restart_does_not_create_a_session(self) -> None:
        self.row = None
        pod_app._load_active_session_checkpoint.return_value = None
        self.assertIsNone(pod_app._restore_interrupted_session())
        self.assertIsNone(pod_app._active_session)
        self.assertEqual(self.calls.mock_calls, [])

    def test_waiting_restore_never_replaces_an_existing_owner(self) -> None:
        existing = {"record": {"session_id": "other-owner"}}
        pod_app._active_session = existing
        self.row = None
        self.checkpoint["phase"] = "waiting_bed"
        self.assertIsNone(pod_app._restore_interrupted_session())
        self.assertIs(pod_app._active_session, existing)
        pod_app._save_active_session_checkpoint.assert_not_called()
        pod_app._replace_session_projection_locked.assert_not_called()

    def test_recording_checkpoint_without_a_row_is_discarded(self) -> None:
        self.row = None
        self.assertIsNone(pod_app._restore_interrupted_session())
        pod_app._clear_active_session_checkpoint.assert_called_once()
        self.assertIsNone(pod_app._active_session)


class RestartTimelineTests(unittest.TestCase):
    def test_cadence_migration_preserves_input_and_old_sample_values(self) -> None:
        start = "2026-09-18T12:00:00+00:00"
        resumed = "2026-09-18T12:01:00+00:00"
        rows = [{"timestamp": start, "heart_rate": 65, "respiration_rate": 14}]
        record = {"sample_interval_s": 5}
        original = deepcopy((rows, record))
        result = restore_timeline(
            rows, record, start_at_utc=start, resumed_at_utc=resumed, live_interval_s=10
        )
        self.assertEqual((rows, record), original)
        self.assertTrue(result.upgraded)
        self.assertEqual(result.previous_interval_s, 5)
        self.assertEqual(result.samples[0]["sample_interval_s"], 5)
        self.assertEqual(result.samples[0]["hr"], 65)
        self.assertEqual(result.samples[0]["rr"], 14)
        self.assertEqual(
            result.cadence_segments[-1],
            {
                "start_at_utc": resumed,
                "sample_interval_s": 10,
            },
        )

    def test_current_cadence_does_not_append_duplicate_segment(self) -> None:
        start = "2026-09-18T12:00:00+00:00"
        result = restore_timeline(
            [],
            {"sample_interval_s": 10},
            start_at_utc=start,
            resumed_at_utc="2026-09-18T12:01:00+00:00",
            live_interval_s=10,
        )
        self.assertFalse(result.upgraded)
        self.assertEqual(len(result.cadence_segments), 1)
        self.assertEqual(result.samples, [])


if __name__ == "__main__":
    unittest.main()
