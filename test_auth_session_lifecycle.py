"""Focused lifecycle regression tests for browser authentication storage."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from access_control import AuthSessionManager


class AuthSessionLifecycleTests(unittest.TestCase):
    def test_constructor_does_not_touch_filesystem(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "not-created"

            manager = AuthSessionManager(data_dir)

            self.assertEqual(manager.path, data_dir / "auth.db")
            self.assertFalse(data_dir.exists())
            self.assertFalse(manager.initialized)

    def test_initialize_is_idempotent_and_preserves_session_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = AuthSessionManager(Path(tmp))

            manager.initialize()
            manager.initialize()

            self.assertTrue(manager.initialized)

            with closing(sqlite3.connect(manager.path)) as connection:
                columns = {
                    row[1]
                    for row in connection.execute("PRAGMA table_info(auth_sessions)")
                }
                indexes = {
                    row[1]
                    for row in connection.execute("PRAGMA index_list(auth_sessions)")
                }
            self.assertEqual(
                columns,
                {
                    "token_hash",
                    "session_id",
                    "subject",
                    "username",
                    "display_name",
                    "account_key",
                    "email",
                    "role",
                    "auth_source",
                    "csrf_token",
                    "created_at",
                    "expires_at",
                },
            )
            self.assertIn("idx_auth_subject", indexes)
            self.assertIn("idx_auth_account_key", indexes)

    def test_initialized_manager_keeps_public_session_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = AuthSessionManager(Path(tmp))
            manager.initialize()

            cookie, principal = manager.create(
                subject="zeep:user-1",
                username="tester",
                display_name="Tester",
                account_key="tester@example.com",
                email="tester@example.com",
                role="user",
                auth_source="zeep",
            )

            self.assertEqual(manager.resolve(cookie), principal)
            self.assertEqual(
                principal.public_dict(),
                {
                    "subject": "zeep:user-1",
                    "username": "tester",
                    "display_name": "Tester",
                    "account_key": "tester@example.com",
                    "email": "tester@example.com",
                    "role": "user",
                    "auth_source": "zeep",
                    "expires_at": principal.expires_at,
                },
            )

    def test_public_operation_keeps_non_lifespan_callers_compatible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = AuthSessionManager(Path(tmp))

            cookie, principal = manager.create(
                subject="admin:operator",
                username="operator",
                display_name="Operator",
                account_key="operator",
                email=None,
                role="admin",
                auth_source="local_admin",
            )

            self.assertTrue(manager.path.exists())
            self.assertEqual(manager.resolve(cookie), principal)

    def test_failed_configuration_load_can_be_retried(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            accounts = data_dir / "local_admins.json"
            accounts.write_text("{broken", encoding="utf-8")
            with patch.dict(
                os.environ,
                {"LOCAL_ADMIN_ACCOUNTS_FILE": str(accounts)},
            ):
                manager = AuthSessionManager(data_dir)

                with self.assertRaisesRegex(ValueError, "cannot read"):
                    manager.initialize()
                self.assertFalse(manager.initialized)
                self.assertFalse(manager.path.exists())

                accounts.write_text(
                    json.dumps({"version": 1, "accounts": []}),
                    encoding="utf-8",
                )
                manager.initialize()

                self.assertTrue(manager.initialized)
                self.assertTrue(manager.path.exists())


if __name__ == "__main__":
    unittest.main()
