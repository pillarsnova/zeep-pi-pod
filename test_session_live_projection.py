"""Contract tests for the pure live Session projection."""

from __future__ import annotations

import unittest
from dataclasses import replace

from sessions.live_projection import (
    SessionPublicIdentity,
    active_session_projection,
    inactive_session_projection,
    recording_vital_gate,
)

PUBLIC_KEYS = {
    "active",
    "username",
    "account_key",
    "email",
    "display_name",
    "auth_source",
    "gender",
    "age",
    "age_group",
    "health_reference",
    "wellness_context_available",
    "rest_mode",
    "target_duration_s",
    "personal_rest_baseline",
    "session_id",
    "started_at",
    "samples",
    "recording",
    "bed_wait_s",
    "vital_gate",
}


class SessionLiveProjectionTests(unittest.TestCase):
    @staticmethod
    def identity() -> SessionPublicIdentity:
        return SessionPublicIdentity(
            username="person@example.test",
            account_key="person@example.test",
            email="person@example.test",
            display_name="Person",
            auth_source="zeep",
            gender="female",
            age=36,
            age_group="30-44",
            health_reference={"schema_version": 1},
        )

    @staticmethod
    def vital_gate() -> dict[str, object]:
        return {
            "ready": False,
            "heart_rate_valid": True,
            "respiration_rate_valid": True,
            "confirmed_packets": 2,
            "required_packets": 3,
            "packets_since_login": 2,
            "bcg_fresh": True,
            "on_bed": True,
            "reason": "confirming_hr_rr",
        }

    def test_inactive_projection_has_complete_private_context_reset(self) -> None:
        projection = inactive_session_projection(
            required_packets=3,
            reason="no_session",
        )

        self.assertEqual(set(projection), PUBLIC_KEYS)
        self.assertFalse(projection["active"])
        self.assertFalse(projection["wellness_context_available"])
        self.assertIsNone(projection["personal_rest_baseline"])
        self.assertEqual(projection["vital_gate"]["reason"], "no_session")

    def test_active_projection_has_same_complete_outer_contract(self) -> None:
        projection = active_session_projection(
            self.identity(),
            session_id="session-1",
            rest_mode="nap_recovery",
            target_duration_s=1_800,
            started_at=1_000.0,
            samples=0,
            recording=False,
            vital_gate=self.vital_gate(),
            wellness_context_available=True,
            personal_rest_baseline={"status": "learning"},
        )

        self.assertEqual(set(projection), PUBLIC_KEYS)
        self.assertTrue(projection["active"])
        self.assertTrue(projection["wellness_context_available"])
        self.assertEqual(
            projection["personal_rest_baseline"],
            {"status": "learning"},
        )

    def test_active_projection_detaches_nested_mappings(self) -> None:
        health = {"schema_version": 1}
        baseline = {
            "status": "ready",
            "environment": {"temperature_c": 22.0},
        }
        gate = self.vital_gate()
        identity = replace(self.identity(), health_reference=health)

        projection = active_session_projection(
            identity,
            session_id="session-1",
            rest_mode="sleep",
            target_duration_s=25_200,
            started_at=1_000.0,
            samples=12,
            recording=True,
            vital_gate=gate,
            personal_rest_baseline=baseline,
        )
        health["schema_version"] = 2
        baseline["status"] = "changed"
        baseline["environment"]["temperature_c"] = 30.0
        gate["reason"] = "changed"

        self.assertEqual(projection["health_reference"]["schema_version"], 1)
        self.assertEqual(projection["personal_rest_baseline"]["status"], "ready")
        self.assertEqual(
            projection["personal_rest_baseline"]["environment"]["temperature_c"],
            22.0,
        )
        self.assertEqual(
            projection["vital_gate"]["reason"],
            "confirming_hr_rr",
        )

    def test_gate_diagnostics_survive_recording_transition(self) -> None:
        source = {**self.vital_gate(), "internal_secret": "must-not-publish"}
        projection = recording_vital_gate(source)

        self.assertTrue(projection["ready"])
        self.assertEqual(projection["reason"], "recording")
        self.assertEqual(projection["packets_since_login"], 2)
        self.assertTrue(projection["bcg_fresh"])
        self.assertTrue(projection["on_bed"])
        self.assertNotIn("internal_secret", projection)

    def test_active_projection_allowlists_vital_gate(self) -> None:
        gate = {**self.vital_gate(), "internal_secret": "must-not-publish"}
        projection = active_session_projection(
            self.identity(),
            session_id="session-1",
            rest_mode="sleep",
            target_duration_s=25_200,
            started_at=1_000.0,
            samples=0,
            recording=False,
            vital_gate=gate,
        )

        self.assertNotIn("internal_secret", projection["vital_gate"])

    def test_zero_bed_wait_preserves_wire_number_shape(self) -> None:
        projection = inactive_session_projection(
            required_packets=3,
            reason="no_session",
        )

        self.assertIs(type(projection["bed_wait_s"]), int)

    def test_calls_do_not_share_mutable_gate_state(self) -> None:
        first = inactive_session_projection(
            required_packets=3,
            reason="waiting_for_bcg",
        )
        second = inactive_session_projection(
            required_packets=3,
            reason="waiting_for_bcg",
        )

        first["vital_gate"]["reason"] = "changed"
        self.assertEqual(second["vital_gate"]["reason"], "waiting_for_bcg")


if __name__ == "__main__":
    unittest.main()
