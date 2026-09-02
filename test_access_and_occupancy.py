"""Unit tests for authentication and cross-pod occupancy invariants."""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from access_control import AuthSessionManager, hash_password, verify_password
from pod_occupancy import OccupancyConflict, OccupancyStore, create_occupancy_router


class AuthSessionTests(unittest.TestCase):
    def test_cookie_is_opaque_and_resolves_to_role(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = AuthSessionManager(Path(tmp))
            cookie, principal = manager.create(
                subject="zeep:user-1",
                username="tester",
                display_name="Tester",
                account_key="user@example.com",
                email="user@example.com",
                role="user",
                auth_source="zeep",
            )
            self.assertNotIn("tester", cookie)
            self.assertEqual(manager.resolve(cookie), principal)
            manager.revoke(cookie)
            self.assertIsNone(manager.resolve(cookie))

    def test_offline_ticket_is_one_time_and_identity_bound(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = AuthSessionManager(Path(tmp))
            ticket = manager.issue_offline_ticket("user@example.com")
            self.assertFalse(manager.consume_offline_ticket(ticket, "someone-else"))
            self.assertFalse(manager.consume_offline_ticket(ticket, "user@example.com"))
            ticket = manager.issue_offline_ticket("user@example.com")
            self.assertTrue(manager.consume_offline_ticket(ticket, "USER@example.com"))
            self.assertFalse(manager.consume_offline_ticket(ticket, "user@example.com"))

    def test_scrypt_password_hash(self) -> None:
        encoded = hash_password("correct horse battery staple")
        self.assertTrue(verify_password("correct horse battery staple", encoded))
        self.assertFalse(verify_password("wrong", encoded))


class OccupancyTests(unittest.TestCase):
    def test_same_account_cannot_hold_two_pods(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = OccupancyStore(Path(tmp), ttl_seconds=15)
            store.acquire(
                subject="zeep:user-1", pod_id="pod-01",
                pod_session_id="session-1", username="tester",
            )
            with self.assertRaises(OccupancyConflict) as caught:
                store.acquire(
                    subject="zeep:user-1", pod_id="pod-02",
                    pod_session_id="session-2", username="tester",
                )
            self.assertEqual(caught.exception.reason, "account_already_in_use")

    def test_same_pod_cannot_hold_two_accounts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = OccupancyStore(Path(tmp), ttl_seconds=15)
            store.acquire(
                subject="zeep:user-1", pod_id="pod-01",
                pod_session_id="session-1", username="first",
            )
            with self.assertRaises(OccupancyConflict) as caught:
                store.acquire(
                    subject="zeep:user-2", pod_id="pod-01",
                    pod_session_id="session-2", username="second",
                )
            self.assertEqual(caught.exception.reason, "pod_already_occupied")

    def test_exact_session_acquire_is_idempotent_and_release_frees_pod(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = OccupancyStore(Path(tmp), ttl_seconds=15)
            first = store.acquire(
                subject="zeep:user-1", pod_id="pod-01",
                pod_session_id="session-1", username="tester",
            )
            renewed = store.acquire(
                subject="zeep:user-1", pod_id="pod-01",
                pod_session_id="session-1", username="tester",
            )
            self.assertEqual(first.lease_id, renewed.lease_id)
            self.assertGreaterEqual(renewed.expires_at, first.expires_at)
            store.release(renewed)
            self.assertEqual(store.list_active(), [])

    def test_internal_coordinator_requires_shared_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = OccupancyStore(Path(tmp), ttl_seconds=15)
            api = FastAPI()
            api.include_router(create_occupancy_router(store, "coordinator-secret"))
            client = TestClient(api)
            body = {
                "subject": "zeep:user-1", "pod_id": "pod-01",
                "pod_session_id": "session-1", "username": "tester",
            }
            self.assertEqual(
                client.post("/api/internal/occupancy/acquire", json=body).status_code,
                401,
            )
            response = client.post(
                "/api/internal/occupancy/acquire",
                json=body,
                headers={"X-Pod-Coordinator-Token": "coordinator-secret"},
            )
            self.assertEqual(response.status_code, 200, response.text)


if __name__ == "__main__":
    unittest.main()
