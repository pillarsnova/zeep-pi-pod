"""HTTP contract tests for the Admin account-erasure boundary."""

from __future__ import annotations

import threading
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from zeep_pod.identity.account_erasure_api import (
    create_account_erasure_router,
)


class DatabaseStub:
    def __init__(self) -> None:
        self.read_count = 0

    def read_sessions(self, _sql, _params):
        self.read_count += 1
        return []

    def enqueue(self, _database, _operation, _payload):
        raise AssertionError("empty account must not enqueue a database job")

    def flush(self, _timeout):
        return True

    def health(self):
        return {"last_error": None}


class EmptyBaseline:
    @staticmethod
    def delete_user(_key):
        return False


class EmptyAuth:
    @staticmethod
    def revoke_user_account(_key):
        return 0

    @staticmethod
    def clear_offline_tickets():
        return 0


class AccountErasureApiTests(unittest.TestCase):
    def client(self, *, active_key=None, profiles=None):
        database = DatabaseStub()
        profiles = profiles or {}
        app = FastAPI()
        app.include_router(
            create_account_erasure_router(
                require_admin=lambda: None,
                lifecycle_lock=threading.RLock(),
                normalize_account_key=lambda value: value.strip().casefold(),
                active_account_key=lambda: active_key,
                database=database,
                baseline_store=EmptyBaseline(),
                auth_sessions=EmptyAuth(),
                profiles_lock=threading.Lock(),
                load_profiles=lambda: dict(profiles),
                save_profiles=lambda _profiles: None,
                clear_pending_ingest=lambda _session_id: False,
                clear_report_shares=lambda _account_key: 0,
                clear_pending_profiles=lambda _account_key: 0,
                clear_session_checkpoint=lambda _account_keys: False,
                log_event=lambda *_args, **_kwargs: None,
                backup_retention_count=lambda: 3,
            )
        )
        return TestClient(app), database

    def test_delete_is_idempotent_and_reports_backup_boundary(self) -> None:
        client, database = self.client()

        response = client.delete("/api/users/ABSENT%40example.com")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["already_absent"])
        self.assertEqual(
            response.json()["deletion_scope"],
            {
                "local_active_store_deleted": True,
                "remote_uploaded_objects_deleted": False,
                "daily_backup_archives_deleted": False,
                "daily_backup_archives_retained": 3,
            },
        )
        self.assertEqual(database.read_count, 1)

    def test_openapi_publishes_strict_local_erasure_scope(self) -> None:
        client, _database = self.client()

        document = client.app.openapi()
        operation = document["paths"]["/api/users/{username}"]["delete"]
        schema = operation["responses"]["200"]["content"][
            "application/json"
        ]["schema"]

        self.assertEqual(schema["$ref"], "#/components/schemas/AccountErasureResponse")
        properties = document["components"]["schemas"][
            "AccountErasureScope"
        ]["properties"]
        self.assertIn("local_active_store_deleted", properties)
        self.assertIn("remote_uploaded_objects_deleted", properties)
        self.assertIn("daily_backup_archives_deleted", properties)

    def test_active_account_is_never_deleted(self) -> None:
        client, database = self.client(active_key="person@example.com")

        response = client.delete("/api/users/person%40example.com")

        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(database.read_count, 0)

    def test_active_legacy_alias_blocks_canonical_account_erasure(self) -> None:
        client, database = self.client(
            active_key="old-login",
            profiles={
                "person@example.com": {
                    "legacy_account_keys": ["old-login"],
                }
            },
        )

        response = client.delete("/api/users/person%40example.com")

        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(database.read_count, 0)


if __name__ == "__main__":
    unittest.main()
