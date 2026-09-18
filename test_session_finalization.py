"""Characterize finalization order and failure recovery without hardware I/O."""

from __future__ import annotations

import unittest
from contextlib import ExitStack
from datetime import datetime
from unittest.mock import Mock, patch

from testing_support import configure_app_test_environment

configure_app_test_environment()

import app as pod_app  # noqa: E402


class SessionFinalizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.calls = Mock()
        self.record = {
            "session_id": "finalize-test",
            "username": "person@example.test",
            "username_key": "person@example.test",
            "identity_subject": "zeep:coded",
            "rest_mode": "nap_recovery",
            "target_duration_s": 1800,
            "started_monotonic": 1000.0,
            "sample_interval_s": 10.0,
            "started_at_utc": "2026-09-19T00:00:00+00:00",
            "armed_at_utc": "2026-09-18T23:59:00+00:00",
            "health_reference": {"schema_version": 1, "age_years": 38},
        }
        epoch = datetime.fromisoformat(self.record["started_at_utc"]).timestamp()
        self.samples = [
            {
                "t": epoch + (i + 1) * 10,
                "sleep": "wake",
                "bed": "On bed",
                "sample_interval_s": 10,
                "temp": 24,
                "hum": 50,
                "dba": 40,
                "lux": 0,
                "co2": 800,
                "pm2_5": 10,
                "voc": 90,
                "hr": 65,
                "rr": 14,
                "sleep_estimator_version": "test-estimator",
                "sleep_score_eligible": True,
            }
            for i in range(180)
        ]
        self.active = {
            "record": self.record,
            "samples": self.samples,
            "counters": {"door": 1},
            "auth": {"refresh_token": "fake-refresh", "access_token": "fake-access"},
            "occupancy_lease": {"id": "test-lease"},
            "phase": "recording",
        }
        self.replace("_active_session", self.active)
        self.database = self.replace("database", Mock())
        self.database.flush.return_value = True
        self.database.read_sessions.return_value = []
        self.database.health.return_value = {"last_error": None}
        self.track(self.database.flush, "flush")
        self.track(self.database.enqueue, "enqueue")
        self.track(self.database.read_sessions, "read")
        self.replace("bcg_storage", Mock())
        self.track(pod_app.bcg_storage.end_session, "bcg_end")
        self.track(pod_app.bcg_storage.start_session, "bcg_start")
        self.replace("report_shares", Mock())
        for name in ("reserve", "discard", "fulfil"):
            self.track(getattr(pod_app.report_shares, name), name)
        self.replace("occupancy_client", Mock())
        self.track(pod_app.occupancy_client.release, "lease_release")
        self.replace("baselines", Mock())
        pod_app.baselines.behaviour_context.return_value = {"available": False}
        pod_app.baselines.update_user.return_value = {
            "status": "learning",
            "nights_used": 1,
        }
        self.track(pod_app.baselines.behaviour_context, "baseline_context")
        self.track(pod_app.baselines.update_user, "baseline_update")
        self.profile = {"sessions": 3}
        self.replace(
            "_load_profiles",
            Mock(return_value={self.record["username_key"]: self.profile}),
        )
        self.replace(
            "session_availability_by_account",
            Mock(
                return_value={
                    self.record["username_key"]: {
                        "lifetime_sessions": 4,
                        "last_data_session_utc": "latest",
                    }
                }
            ),
        )
        self.replace(
            "session_vital_gate_now",
            Mock(return_value={"ready": False, "reason": "waiting_for_bcg"}),
        )
        for name, alias in (
            ("_clear_active_session_checkpoint", "clear_checkpoint"),
            ("_enqueue_session_ingest", "ingest"),
            ("_zeep_request", "logout"),
            ("_replace_session_projection_locked", "publish_idle"),
            ("_reset_live_sleep_inference", "reset_inference"),
            ("_save_profiles", "save_profile"),
            ("log_event", "log"),
        ):
            self.track(self.replace(name, Mock()), alias)
        self.projection = {
            "samples": self.samples,
            "report_samples": self.samples,
            "report_interval_s": 10.0,
            "cadence_summary": {},
            "grid_summary": {"classification_complete": True},
            "bed_status_counts": {"On bed": 180},
            "sleep_state_counts": {"wake": 180},
            "sleep_score_state_counts": {"wake": 180},
        }
        project = self.stack.enter_context(
            patch.object(
                pod_app.report_projection,
                "project_report_samples",
                return_value=self.projection,
            )
        )
        self.track(project, "project")
        self.stack.enter_context(
            patch.object(pod_app.time, "monotonic", return_value=2800.0)
        )
        self.stack.enter_context(
            patch.object(pod_app.time, "time", return_value=epoch + 1800)
        )

    def replace(self, name, value):
        self.stack.enter_context(patch.object(pod_app, name, value))
        return value

    def track(self, mock, name):
        self.calls.attach_mock(mock, name)

    def call_names(self):
        return [call[0] for call in self.calls.mock_calls]

    def test_recorded_session_commits_before_logout_upload_and_learning(self) -> None:
        result = pod_app._finalize_active_session()
        self.assertIs(result, self.record)
        self.assertIsNone(pod_app._active_session)
        self.assertNotIn("started_monotonic", result)
        self.assertEqual(result["duration_s"], 1800)
        self.assertEqual(result["rest_mode"], "nap_recovery")
        self.assertTrue(result["session_report"]["available"])
        self.assertEqual(self.profile["sessions"], 4)
        names = self.call_names()
        ordered = [
            "reserve",
            "flush",
            "project",
            "bcg_end",
            "baseline_context",
            "enqueue",
            "clear_checkpoint",
            "lease_release",
            "logout",
            "ingest",
            "fulfil",
            "baseline_update",
            "save_profile",
            "publish_idle",
            "reset_inference",
        ]
        self.assertEqual(
            [name for name in names if name in ordered and name != "flush"],
            [name for name in ordered if name != "flush"],
        )
        self.assertEqual(self.database.flush.call_count, 3)
        self.assertEqual(
            self.database.enqueue.call_args.args[:2], ("sessions", "session_finalize")
        )

    def test_idle_does_not_reserve_or_write(self) -> None:
        pod_app._active_session = None
        self.assertIsNone(pod_app._finalize_active_session())
        self.assertEqual(self.calls.mock_calls, [])

    def test_prior_baseline_is_used_and_persisted_before_learning(self) -> None:
        prior = {"prior_sessions": 3, "reference": {"heart_rate_bpm": 62.0}}
        pod_app.baselines.behaviour_context.return_value = prior
        with patch.object(
            pod_app, "build_session_report", wraps=pod_app.build_session_report
        ) as build:
            pod_app._finalize_active_session()
        self.assertIs(build.call_args.kwargs["personal_context"], prior)
        self.assertIs(build.call_args.kwargs["trend_context"], prior)
        summary = self.database.enqueue.call_args.args[2]["final_summary"]
        self.assertEqual(summary["restore_context"], prior)
        self.assertLess(
            self.call_names().index("baseline_context"),
            self.call_names().index("baseline_update"),
        )

    def test_waiting_login_closes_without_report_or_baseline(self) -> None:
        self.record["started_monotonic"] = None
        self.active["phase"] = "waiting_bed"
        result = pod_app._finalize_active_session()
        self.assertFalse(result["recording_started"])
        self.assertEqual(result["end_reason"], "not_recorded")
        self.assertEqual(result["samples"], [])
        self.assertNotIn("session_report", result)
        self.database.enqueue.assert_not_called()
        pod_app.baselines.update_user.assert_not_called()
        pod_app._enqueue_session_ingest.assert_not_called()
        self.assertEqual(self.call_names()[-1], "discard")

    def test_projection_flush_failure_keeps_live_owner_and_checkpoint(self) -> None:
        self.database.flush.return_value = False
        with self.assertRaisesRegex(
            RuntimeError, "before Sleep attribution projection"
        ):
            pod_app._finalize_active_session()
        self.assertIs(pod_app._active_session, self.active)
        self.assertEqual(self.record["started_monotonic"], 1000)
        pod_app._clear_active_session_checkpoint.assert_not_called()
        pod_app.occupancy_client.release.assert_not_called()
        pod_app.report_shares.discard.assert_called_once_with("zeep:coded")

    def test_incomplete_projection_is_not_committed(self) -> None:
        self.projection["grid_summary"]["classification_complete"] = False
        with self.assertRaisesRegex(RuntimeError, "continuity invariant"):
            pod_app._finalize_active_session()
        self.assertIs(pod_app._active_session, self.active)
        self.database.enqueue.assert_not_called()
        pod_app.bcg_storage.end_session.assert_not_called()

    def test_final_bcg_flush_failure_restores_same_session(self) -> None:
        self.database.flush.side_effect = [True, False]
        with self.assertRaisesRegex(RuntimeError, "final BCG epoch"):
            pod_app._finalize_active_session()
        self.assertIs(pod_app._active_session, self.active)
        pod_app.bcg_storage.start_session.assert_called_once_with("finalize-test")
        pod_app._clear_active_session_checkpoint.assert_not_called()
        pod_app._enqueue_session_ingest.assert_not_called()

    def test_commit_failure_restores_session_without_upload(self) -> None:
        self.database.flush.side_effect = [True, True, False]
        with self.assertRaisesRegex(RuntimeError, "before Session finalization"):
            pod_app._finalize_active_session()
        self.assertIs(pod_app._active_session, self.active)
        self.assertIn("started_monotonic", self.record)
        pod_app.bcg_storage.start_session.assert_called_once_with("finalize-test")
        pod_app._clear_active_session_checkpoint.assert_not_called()
        pod_app._enqueue_session_ingest.assert_not_called()

    def test_best_effort_remote_failures_do_not_lose_completed_report(self) -> None:
        pod_app.occupancy_client.release.side_effect = pod_app.CoordinatorUnavailable(
            "offline"
        )
        pod_app._zeep_request.side_effect = pod_app.HTTPException(503, "offline")
        pod_app.baselines.update_user.side_effect = RuntimeError("learning unavailable")
        result = pod_app._finalize_active_session()
        self.assertTrue(result["session_report"]["available"])
        self.assertIsNone(pod_app._active_session)
        self.assertEqual(self.call_names()[-2:], ["publish_idle", "reset_inference"])
        pod_app._enqueue_session_ingest.assert_called_once()


if __name__ == "__main__":
    unittest.main()
