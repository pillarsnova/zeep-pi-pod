"""Characterize Login-to-waiting Session creation with synthetic dependencies."""

from __future__ import annotations

import unittest
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

from testing_support import configure_app_test_environment

configure_app_test_environment()

import app as pod_app  # noqa: E402


class SessionStartTests(unittest.TestCase):
    def setUp(self) -> None:
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.calls = Mock()
        self.owner = SimpleNamespace(
            account_key="person@example.test",
            email="person@example.test",
            subject="zeep:coded-person",
            session_id="browser-owner",
        )
        self.auth = {
            "public_id": "coded-person",
            "email": "person@example.test",
            "display_name": "Test Person",
            "profile_refreshed": True,
            "access_token": "fake-access",
            "refresh_token": "fake-refresh",
        }
        self.health = {"age_years": 38, "height_cm": 170, "weight_kg": 65}
        self.profiles = {}
        self.lease = SimpleNamespace(expires_at=1234567)
        self.replace("_active_session", None)
        self.replace("_load_profiles", Mock(return_value=self.profiles))
        self.replace("_save_profiles", Mock(), "save_profiles")
        self.replace("baselines", Mock())
        self.replace("rest_window", Mock(return_value={"available": False}), "baseline")
        self.replace("occupancy_client", Mock(mode="local"))
        pod_app.occupancy_client.acquire.return_value = self.lease
        self.calls.attach_mock(pod_app.occupancy_client.acquire, "acquire")
        self.calls.attach_mock(pod_app.occupancy_client.release, "release")
        self.replace(
            "_current_safety_checkpoint_context", Mock(return_value={"armed": True})
        )
        self.replace("_save_active_session_checkpoint", Mock(), "checkpoint")
        self.replace("_reset_live_sleep_inference", Mock(), "reset")
        self.replace(
            "session_vital_gate_now",
            Mock(return_value={"ready": False, "reason": "waiting_for_bcg"}),
            "gate",
        )
        self.replace("_replace_session_projection_locked", Mock(), "publish")
        self.replace(
            "snapshot",
            Mock(return_value={"session": {"active": True, "recording": False}}),
        )
        self.replace("log_event", Mock(), "log")
        self.stack.enter_context(
            patch.object(pod_app.time, "time", return_value=1000.0)
        )
        self.stack.enter_context(
            patch.object(pod_app.time, "monotonic", return_value=100.0)
        )

    def replace(self, name, value, alias=None):
        self.stack.enter_context(patch.object(pod_app, name, value))
        if alias:
            self.calls.attach_mock(value, alias)
        return value

    def start(self, **overrides):
        arguments = {
            "username": "test-person",
            "gender": "female",
            "age": 38,
            "age_group": "30-44",
            "owner": self.owner,
            "auth": self.auth,
            "health_reference": self.health,
            "rest_mode": "nap_recovery",
            "target_duration_minutes": 30,
        }
        arguments.update(overrides)
        return pod_app._start_pod_session(**arguments)

    def test_success_persists_before_publishing_without_recording(self) -> None:
        result = self.start()
        active = pod_app._active_session
        self.assertTrue(result["ok"])
        self.assertEqual(active["phase"], "waiting_bed")
        self.assertIsNone(active["record"]["started_monotonic"])
        self.assertEqual(active["record"]["username_key"], self.owner.email)
        self.assertEqual(active["record"]["target_duration_s"], 1800)
        self.assertEqual(active["owner_auth_session_id"], self.owner.session_id)
        self.assertEqual(active["safety_context"], {"armed": True})
        self.assertIs(active["auth"], self.auth)
        self.assertNotIn("fake-access", str(active["record"]))
        self.assertNotIn("fake-refresh", str(result))
        self.assertEqual(
            [c[0] for c in self.calls.mock_calls],
            [
                "save_profiles",
                "baseline",
                "acquire",
                "checkpoint",
                "reset",
                "log",
                "gate",
                "publish",
            ],
        )

    def test_invalid_target_fails_before_profile_and_lease(self) -> None:
        with self.assertRaises(pod_app.HTTPException) as caught:
            self.start(target_duration_minutes=45)
        self.assertEqual(caught.exception.status_code, 422)
        self.assertEqual(self.calls.mock_calls, [])

    def test_occupied_pod_is_not_replaced(self) -> None:
        existing = {"record": {"session_id": "existing"}}
        pod_app._active_session = existing
        with self.assertRaises(pod_app.HTTPException) as caught:
            self.start()
        self.assertEqual(caught.exception.status_code, 409)
        self.assertIs(pod_app._active_session, existing)
        self.assertEqual(self.calls.mock_calls, [])

    def test_email_mismatch_is_rejected_without_side_effects(self) -> None:
        self.owner.account_key = "other@example.test"
        with self.assertRaises(pod_app.HTTPException) as caught:
            self.start()
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(self.calls.mock_calls, [])

    def test_checkpoint_failure_rolls_back_local_owner_and_lease(self) -> None:
        pod_app._save_active_session_checkpoint.side_effect = OSError(
            "disk unavailable"
        )
        with self.assertRaises(pod_app.HTTPException) as caught:
            self.start()
        self.assertEqual(caught.exception.status_code, 500)
        self.assertIsNone(pod_app._active_session)
        pod_app.occupancy_client.release.assert_called_once_with(self.lease)
        pod_app._reset_live_sleep_inference.assert_not_called()
        pod_app._replace_session_projection_locked.assert_not_called()

    def test_coordinator_outage_blocks_new_occupancy(self) -> None:
        pod_app.occupancy_client.acquire.side_effect = pod_app.CoordinatorUnavailable(
            "offline"
        )
        with self.assertRaises(pod_app.HTTPException) as caught:
            self.start()
        self.assertEqual(caught.exception.status_code, 503)
        self.assertEqual(
            caught.exception.detail["code"], "occupancy_coordinator_unavailable"
        )
        self.assertIsNone(pod_app._active_session)
        pod_app._save_active_session_checkpoint.assert_not_called()

    def test_failed_profile_refresh_preserves_verified_health_fields(self) -> None:
        self.profiles[self.owner.account_key] = {
            "gender": "female",
            "age": 40,
            "age_group": "30-44",
            "height_cm": 169,
            "weight_kg": 66,
            "blood_group": "O+",
        }
        self.auth["profile_refreshed"] = False
        self.start(health_reference={}, gender="male", age=30)
        profile = self.profiles[self.owner.account_key]
        self.assertEqual(profile["gender"], "female")
        self.assertEqual(profile["age"], 40)
        self.assertEqual(profile["height_cm"], 169)
        self.assertEqual(profile["blood_group"], "O+")
        self.assertEqual(profile["health_reference_refresh_status"], "cached")

    def test_successful_refresh_clears_removed_optional_health_fields(self) -> None:
        self.profiles[self.owner.account_key] = {
            "gender": "female",
            "age": 40,
            "age_group": "30-44",
            "height_cm": 169,
            "weight_kg": 66,
            "blood_group": "O+",
        }
        self.start(health_reference={})
        profile = self.profiles[self.owner.account_key]
        self.assertIsNone(profile["height_cm"])
        self.assertIsNone(profile["blood_group"])
        self.assertEqual(profile["health_reference_refresh_status"], "live_login")

    def test_local_fallback_keeps_local_key_and_does_not_need_auth_tokens(self) -> None:
        self.owner.account_key = "local-person"
        self.owner.email = None
        self.owner.subject = "local:test-pod:local-person"
        result = self.start(username="local-person", auth=None)
        active = pod_app._active_session
        self.assertTrue(result["ok"])
        self.assertIsNone(active["auth"])
        self.assertEqual(active["record"]["username_key"], "local-person")
        self.assertEqual(active["record"]["auth_source"], "local")
        profile = self.profiles["local-person"]
        self.assertIsNone(profile["email"])
        self.assertEqual(profile["health_reference_refresh_status"], "local_login")

    def test_acquire_conflict_preserves_response_shape_and_saved_profile(self) -> None:
        pod_app.occupancy_client.acquire.side_effect = pod_app.OccupancyConflict(
            "account_already_in_use", "other-pod"
        )
        with self.assertRaises(pod_app.HTTPException) as caught:
            self.start()
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(
            caught.exception.detail,
            {
                "code": "account_already_in_use",
                "message": "บัญชีนี้กำลังใช้งานตู้อื่นอยู่",
                "pod_id": "other-pod",
            },
        )
        self.assertEqual(
            [call[0] for call in self.calls.mock_calls],
            ["save_profiles", "baseline", "acquire"],
        )

    def test_second_owner_race_releases_new_lease_without_replacing_owner(self) -> None:
        existing = {"record": {"session_id": "other-session"}}

        def acquire_with_race(**kwargs):
            pod_app._active_session = existing
            return self.lease

        pod_app.occupancy_client.acquire.side_effect = acquire_with_race
        with self.assertRaises(pod_app.HTTPException) as caught:
            self.start()
        self.assertEqual(caught.exception.status_code, 409)
        self.assertIs(pod_app._active_session, existing)
        pod_app.occupancy_client.release.assert_called_once_with(self.lease)
        pod_app._save_active_session_checkpoint.assert_not_called()
        pod_app._replace_session_projection_locked.assert_not_called()

    def test_safety_snapshot_does_not_become_an_additional_login_gate(self) -> None:
        self.replace(
            "state",
            {"safety": {"level": "LATCHED"}, "sensor": {"bcg": {"packets": 42}}},
        )
        result = self.start()
        self.assertTrue(result["ok"])
        self.assertFalse(result["monitor_only"])
        self.assertIsNone(result["warning"])
        self.assertEqual(pod_app._active_session["vital_gate_start_packet_count"], 42)
        self.assertEqual(pod_app.log_event.call_args.kwargs["safety_level"], "LATCHED")

    def test_distinct_clock_points_and_session_suffix_are_preserved(self) -> None:
        origin = datetime(2026, 9, 19, tzinfo=UTC)
        moments = [origin + timedelta(seconds=i) for i in range(4)]
        clock = self.replace("datetime", Mock())
        clock.now.side_effect = moments
        self.stack.enter_context(
            patch.object(
                pod_app.uuid, "uuid4", return_value=SimpleNamespace(hex="abcdef")
            )
        )
        self.start()
        profile = self.profiles[self.owner.account_key]
        record = pod_app._active_session["record"]
        self.assertEqual(clock.now.call_count, 4)
        self.assertEqual(
            profile["health_reference_updated_at_utc"], moments[0].isoformat()
        )
        self.assertEqual(profile["created_at_utc"], moments[1].isoformat())
        self.assertEqual(record["session_id"], "s-20260919T000002Z-abcdef")
        self.assertEqual(record["armed_at_utc"], moments[3].isoformat())


if __name__ == "__main__":
    unittest.main()
