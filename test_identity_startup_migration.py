from __future__ import annotations

import unittest
from unittest.mock import Mock

from identity.startup_migration import migrate_identity_stores


class IdentityStartupMigrationTests(unittest.TestCase):
    def test_store_failure_does_not_prevent_remaining_migrations(self) -> None:
        sessions = Mock(return_value=2)
        baselines = Mock(side_effect=OSError("baseline disk unavailable"))
        auth = Mock(return_value=1)
        mapping = {"old-login": "person@example.com"}

        result = migrate_identity_stores(
            mapping,
            session_migration=sessions,
            baseline_migration=baselines,
            auth_migration=auth,
        )

        sessions.assert_called_once_with(mapping)
        baselines.assert_called_once_with(mapping)
        auth.assert_called_once_with(mapping)
        self.assertEqual(result["sessions"]["status"], "ok")
        self.assertEqual(result["baselines"]["status"], "error")
        self.assertEqual(result["browser_sessions"]["result"], 1)
