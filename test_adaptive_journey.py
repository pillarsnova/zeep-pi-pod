"""Synthetic regression for four-step advisory; never uses Pod data/hardware."""

from __future__ import annotations

import copy
import json
import math
import tempfile
import threading
import unittest
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

from adaptive.coach import one_recommendation
from adaptive.comfort import build_comfort_reference, cohort
from adaptive.journey import build_journey, normalize_samples
from adaptive.journey_repository import JourneyRepository
from adaptive.outcomes import comfort_direction, compare_commands, window_summary
from api.adaptive_journey import create_adaptive_journey_router
from database import DatabaseManager
from sessions.activity import record_session_activity

NOW = 1800000000.0


def stamp(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, UTC).isoformat()


def rows(start: float = NOW - 600, count: int = 60) -> list[dict]:
    return [
        {
            "timestamp": stamp(start + i * 10),
            "temperature": 24.0,
            "humidity": 50.0,
            "sound": 40.0,
            "lux": 1.0,
            "co2": 800.0,
            "heart_rate": 60.0,
            "respiration_rate": 15.0,
            "bed_status": "on_bed",
        }
        for i in range(count)
    ]


def snapshot() -> dict:
    return {
        "session": {"recording": True, "session_id": "s1"},
        "sensor_frame": {"data_age_s": 1, "stale": False},
        "safety": {"ready": True, "latched": False},
        "sensor": {"environment": {"devices": {"sht3x_dis": {"status": "live"}}}},
    }


class JourneyTests(unittest.TestCase):
    def test_comfort_direction_does_not_assume_lower_is_better(self):
        band = {"low": 22, "high": 24}
        self.assertEqual(comfort_direction(26, 24, band), "toward_reference")
        self.assertEqual(comfort_direction(22, 19, band), "away_from_reference")
        self.assertEqual(comfort_direction(22, 23, band), "within_reference")
        self.assertEqual(comfort_direction(None, 23, band), "not_compared")

    def test_activity_adapter_preserves_waiting_and_recording_semantics(self):
        database = Mock()
        active = None
        args = {
            "lock": threading.Lock(),
            "active_session": lambda: active,
            "database": database,
        }
        record_session_activity("music", {"action": "play"}, **args)
        database.enqueue.assert_not_called()
        active = {"counters": {}, "phase": "waiting", "record": {"session_id": "s1"}}
        record_session_activity("music", {"action": "play"}, **args)
        self.assertEqual(active["counters"]["music"], 1)
        database.enqueue.assert_not_called()
        active["phase"] = "recording"
        record_session_activity("music", {"action": "play"}, **args)
        self.assertEqual(active["counters"]["music"], 2)
        call = database.enqueue.call_args.args
        self.assertEqual(call[:2], ("sessions", "event"))
        self.assertEqual(call[2]["session_id"], "s1")
        self.assertEqual(call[2]["value"], {"action": "play"})

    def test_merge_is_read_only_chronological_and_includes_control(self):
        samples = rows()
        samples[2]["lux"] = 30
        events = [
            {
                "id": 1,
                "timestamp": stamp(NOW - 590),
                "type": "door",
                "value": '{"action":"open","token":"secret"}',
            }
        ]
        before = copy.deepcopy((samples, events))
        output = build_journey(samples, events)
        self.assertEqual((samples, events), before)
        self.assertEqual(len(output["channels"]), 9)
        self.assertEqual(output["events"][0]["kind"], "command")
        self.assertNotIn("secret", json.dumps(output))
        times = [event["t"] for event in output["events"]]
        self.assertEqual(times, sorted(times))
        self.assertFalse(output["events"][0]["physical_confirmation"])

    def test_missing_and_invalid_are_not_zero_or_false_events(self):
        samples = rows(count=3)
        samples[1]["sound"] = math.nan
        samples[2]["timestamp"] = stamp(NOW)
        output = build_journey(samples, [])
        self.assertIsNone(output["points"][1]["sound"])
        self.assertEqual([event["kind"] for event in output["events"]], ["gap"])

    def test_duplicate_samples_do_not_inflate_coverage(self):
        sample = {"t": NOW - 10, "sound": 40.0}
        result = window_summary([sample] * 30, "sound", NOW - 300, NOW)
        self.assertEqual(result["samples"], 1)
        self.assertLess(result["coverage"], 0.04)

    def test_sound_uses_energy_average(self):
        result = window_summary(
            [{"t": 0, "sound": 40}, {"t": 10, "sound": 60}], "sound", 0, 20
        )
        self.assertAlmostEqual(result["value"], 57.03, places=2)

    def test_outcomes_wait_for_full_window_and_flag_other_commands(self):
        commands = [
            {"id": "c1", "t": NOW, "label": "คำสั่งแอร์"},
            {"id": "c2", "t": NOW + 10, "label": "คำสั่งเสียง"},
        ]
        samples = normalize_samples(rows(NOW - 300, 67))
        pending = compare_commands(samples, commands, now=NOW + 30)
        self.assertEqual(pending[0]["status"], "waiting")
        self.assertIsNone(pending[0]["metrics"][0]["delta"])
        finished = compare_commands(samples, commands, now=NOW + 400)
        self.assertEqual(finished[0]["status"], "confounded")
        self.assertFalse(finished[0]["causal_claim"])
        self.assertFalse(finished[0]["metrics"][0]["benefit_confirmed"])

    def test_modes_do_not_fallback_auto_to_nap(self):
        self.assertEqual(cohort({"rest_mode": "auto"}), "unknown")
        self.assertNotEqual(
            cohort({"rest_mode": "nap_recovery", "target_duration_s": 1800}),
            cohort({"rest_mode": "nap_recovery", "target_duration_s": 5400}),
        )

    def test_reference_requires_prior_completed_self_report_same_mode(self):
        current = {"start_time": stamp(NOW), "rest_mode": "sleep"}
        evidence = {
            "source": "self_report",
            "use_for_personalization": True,
            "cohort": "overnight",
            "response": "comfortable",
            "metrics": {"temperature": {"value": 22, "coverage": 1}},
        }
        previous = {
            "session_id": "old",
            "end_time": stamp(NOW - 1000),
            "value": evidence,
        }
        result = build_comfort_reference(current, [previous])
        self.assertEqual(result["ranges"]["temperature"]["typical"], 22)
        for change in (
            {"source": "staff_observation"},
            {"cohort": "nap_30"},
            {"response": "too_cold"},
            {"use_for_personalization": False},
        ):
            altered = {**previous, "value": {**evidence, **change}}
            self.assertEqual(build_comfort_reference(current, [altered])["ranges"], {})
        current_row = {**previous, "end_time": stamp(NOW + 1)}
        self.assertEqual(build_comfort_reference(current, [current_row])["ranges"], {})

    def test_one_advisory_no_actuation_and_stale_safety_cooldown(self):
        reference = {
            "status": "learning",
            "ranges": {"temperature": {"typical": 22, "sessions": 1}},
        }
        samples = normalize_samples(rows())
        live = snapshot()
        result = one_recommendation("s1", live, reference, samples, [], now=NOW)
        self.assertIsNotNone(result["item"])
        self.assertFalse(result["automatic_actuation"])
        self.assertEqual(result["item"]["execution"], "manual_control_only")
        for field, value in (
            ("sensor_frame", {"stale": True}),
            ("safety", {"ready": True, "latched": True}),
            ("session", {"recording": True, "session_id": "s2"}),
        ):
            self.assertIsNone(
                one_recommendation(
                    "s1",
                    {**live, field: value},
                    reference,
                    samples,
                    [],
                    now=NOW,
                )["item"]
            )
        self.assertIsNone(
            one_recommendation(
                "s1",
                live,
                reference,
                samples,
                [{"t": NOW - 60}],
                now=NOW,
            )["item"]
        )


class JourneyApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = DatabaseManager(Path(self.temp.name))
        self.database.initialize()
        self.database.start()
        self.database.enqueue(
            "sessions",
            "session_start",
            {
                "session_id": "s1",
                "user": "coded",
                "username_key": "owner",
                "rest_mode": "sleep",
                "start_time": stamp(NOW - 600),
                "created_at": stamp(NOW - 600),
            },
        )
        self.assertTrue(self.database.flush())
        self.principal = SimpleNamespace(
            account_key="owner", role="user", is_admin=False, auth_source="browser"
        )

        def require_user(x_csrf_token: str | None = Header(None)):
            if x_csrf_token != "test-csrf":
                raise HTTPException(403, "csrf")
            return self.principal

        application = FastAPI()
        application.include_router(
            create_adaptive_journey_router(
                database=self.database,
                require_user=require_user,
                snapshot_for=lambda _: snapshot(),
                clock=lambda: NOW,
            ),
            prefix="/api/v1",
        )
        self.client = TestClient(application)
        self.headers = {"X-CSRF-Token": "test-csrf"}
        self.url = "/api/v1/adaptive/sessions/s1"

    def tearDown(self):
        self.database.stop()
        self.temp.cleanup()

    def test_owner_scope_and_no_store(self):
        result = self.client.get(self.url, headers=self.headers)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.headers["cache-control"], "private, no-store")
        self.principal.account_key = "another"
        self.assertEqual(
            self.client.get(self.url, headers=self.headers).status_code, 404
        )
        self.principal.account_key = ""
        with closing(self.database._connect(self.database.sessions_path)) as connection:
            connection.execute(
                "UPDATE sessions SET username_key='' WHERE session_id='s1'"
            )
            connection.commit()
        self.assertEqual(
            self.client.get(self.url, headers=self.headers).status_code, 404
        )
        self.assertEqual(JourneyRepository(self.database).prior_feedback({}), [])
        self.principal.is_admin = True
        self.assertEqual(
            self.client.get(self.url, headers=self.headers).status_code, 200
        )
        self.principal.auth_source = "api_token"
        self.assertEqual(
            self.client.get(self.url, headers=self.headers).status_code, 403
        )

    def test_consent_csrf_idempotency_and_raw_unchanged(self):
        body = {
            "response": "comfortable",
            "use_for_personalization": True,
            "request_id": str(uuid4()),
        }
        self.assertEqual(
            self.client.post(self.url + "/comfort", json=body).status_code, 403
        )
        missing = {
            key: value
            for key, value in body.items()
            if key != "use_for_personalization"
        }
        self.assertEqual(
            self.client.post(
                self.url + "/comfort", json=missing, headers=self.headers
            ).status_code,
            422,
        )
        for _ in range(2):
            response = self.client.post(
                self.url + "/comfort", json=body, headers=self.headers
            )
            self.assertEqual(response.status_code, 200)
        repository = JourneyRepository(self.database)
        self.assertEqual(len(repository.events("s1")), 1)
        self.assertEqual(repository.samples("s1")[0], [])
        self.assertIsNone(repository.session("s1")["end_time"])

    def test_forged_or_expired_decision_does_not_execute(self):
        response = self.client.post(
            self.url + "/decisions",
            headers=self.headers,
            json={
                "recommendation_id": "forged",
                "decision": "accept",
                "request_id": str(uuid4()),
            },
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(JourneyRepository(self.database).events("s1"), [])

    def test_confirmed_advice_is_idempotent_and_never_a_command(self):
        evidence = {
            "source": "self_report",
            "use_for_personalization": True,
            "cohort": "overnight",
            "response": "comfortable",
            "metrics": {"temperature": {"value": 22, "coverage": 1}},
        }
        with closing(self.database._connect(self.database.sessions_path)) as connection:
            connection.execute(
                "INSERT INTO sessions(session_id,user,username_key,start_time,"
                "end_time,created_at,rest_mode) VALUES (?,?,?,?,?,?,?)",
                (
                    "old",
                    "coded",
                    "owner",
                    stamp(NOW - 3000),
                    stamp(NOW - 2000),
                    stamp(NOW - 3000),
                    "sleep",
                ),
            )
            connection.execute(
                "INSERT INTO events(session_id,timestamp,type,value) VALUES (?,?,?,?)",
                ("old", stamp(NOW - 2000), "adaptive_comfort", json.dumps(evidence)),
            )
            connection.executemany(
                "INSERT INTO timeline(session_id,timestamp,temperature) VALUES (?,?,?)",
                [("s1", row["timestamp"], row["temperature"]) for row in rows()],
            )
            connection.commit()
        before = JourneyRepository(self.database).samples("s1")
        data = self.client.get(self.url, headers=self.headers).json()["data"]
        item = data["recommendation"]["item"]
        self.assertIsNotNone(item)
        body = {
            "recommendation_id": item["id"],
            "decision": "accept",
            "request_id": str(uuid4()),
        }
        for _ in range(2):
            response = self.client.post(
                self.url + "/decisions", json=body, headers=self.headers
            )
            self.assertEqual(response.status_code, 200)
            self.assertFalse(response.json()["data"]["command_executed"])
        events = JourneyRepository(self.database).events("s1")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "adaptive_decision")
        self.assertEqual(JourneyRepository(self.database).samples("s1"), before)
        self.assertIsNone(
            self.client.get(self.url, headers=self.headers).json()["data"][
                "recommendation"
            ]["item"]
        )


if __name__ == "__main__":
    unittest.main()
