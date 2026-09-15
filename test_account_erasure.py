from __future__ import annotations

import threading
import unittest

from zeep_pod.identity.account_erasure import (
    AccountErasureError,
    erase_local_user_account,
)


class DatabaseStub:
    def __init__(self, *, flush_results=None) -> None:
        self.flush_results = list(flush_results or [True, True])
        self.flush_calls = 0
        self.jobs = []

    def read_sessions(self, sql, params):
        self.read_query = (sql, params)
        return [{"session_id": "session-1"}]

    def enqueue(self, database, operation, payload):
        self.jobs.append((database, operation, payload))

    def flush(self, _timeout):
        index = min(self.flush_calls, len(self.flush_results) - 1)
        self.flush_calls += 1
        return self.flush_results[index]

    def health(self):
        return {"last_error": "writer failed"}


class BaselineStub:
    def __init__(self) -> None:
        self.deleted = []

    def delete_user(self, key):
        self.deleted.append(key)
        return True


class AuthStub:
    def __init__(self) -> None:
        self.revoked = []
        self.offline_clear_calls = 0

    def revoke_user_account(self, key):
        self.revoked.append(key)
        return 2

    def clear_offline_tickets(self):
        self.offline_clear_calls += 1
        return 1


class AccountErasureTests(unittest.TestCase):
    def dependencies(self, *, flush_results=None):
        profiles = {
            "person@example.com": {
                "username": "Person",
                "email": "person@example.com",
            }
        }
        database = DatabaseStub(flush_results=flush_results)
        baseline = BaselineStub()
        auth = AuthStub()
        cleared = []
        cleared_shares = []
        cleared_profiles = []

        def load_profiles():
            return dict(profiles)

        def save_profiles(value):
            profiles.clear()
            profiles.update(value)

        def clear_pending(session_id):
            cleared.append(session_id)
            return True

        def clear_shares(account_key):
            cleared_shares.append(account_key)
            return 1

        def clear_profiles(account_key):
            cleared_profiles.append(account_key)
            return 1

        return {
            "profiles": profiles,
            "database": database,
            "baseline": baseline,
            "auth": auth,
            "cleared": cleared,
            "cleared_shares": cleared_shares,
            "cleared_profiles": cleared_profiles,
            "kwargs": {
                "database": database,
                "baseline_store": baseline,
                "auth_sessions": auth,
                "profiles_lock": threading.Lock(),
                "load_profiles": load_profiles,
                "save_profiles": save_profiles,
                "clear_pending_ingest": clear_pending,
                "clear_report_shares": clear_shares,
                "clear_pending_profiles": clear_profiles,
                "clear_session_checkpoint": lambda keys: (
                    cleared.append(("checkpoint", set(keys))) or True
                ),
            },
        }

    def test_erases_every_active_local_account_store(self):
        deps = self.dependencies()

        result = erase_local_user_account(
            "PERSON@example.com",
            **deps["kwargs"],
        )

        self.assertEqual(result["sessions_removed"], 1)
        self.assertEqual(result["pending_uploads_removed"], 1)
        self.assertEqual(result["revoked_browser_sessions"], 2)
        self.assertEqual(result["report_shares_revoked"], 1)
        self.assertEqual(result["pending_profiles_revoked"], 1)
        self.assertEqual(result["offline_tickets_revoked"], 1)
        self.assertTrue(result["checkpoint_removed"])
        self.assertEqual(deps["cleared_shares"], ["person@example.com"])
        self.assertEqual(deps["cleared_profiles"], ["person@example.com"])
        self.assertNotIn("person@example.com", deps["profiles"])
        self.assertEqual(deps["baseline"].deleted, ["person@example.com"])
        self.assertEqual(deps["auth"].revoked, ["person@example.com"])
        self.assertEqual(deps["auth"].offline_clear_calls, 1)

    def test_erases_canonical_identity_and_all_declared_legacy_aliases(self):
        deps = self.dependencies()
        deps["profiles"]["person@example.com"]["legacy_account_keys"] = [
            "Old-Login",
        ]

        result = erase_local_user_account("old-login", **deps["kwargs"])

        self.assertEqual(result["account_key"], "person@example.com")
        self.assertEqual(
            result["account_aliases"],
            ["old-login", "person@example.com"],
        )
        query, params = deps["database"].read_query
        self.assertIn("lower(username_key) IN (?,?)", query)
        self.assertEqual(params, ("old-login", "person@example.com"))
        self.assertEqual(
            deps["auth"].revoked,
            ["old-login", "person@example.com"],
        )

    def test_distinct_canonical_profile_is_not_erased_as_legacy_alias(self):
        deps = self.dependencies()
        deps["profiles"]["person@example.com"].update(
            {
                "zeep_public_id": "public-person",
                "legacy_account_keys": ["other@example.com"],
            }
        )
        deps["profiles"]["other@example.com"] = {
            "username": "Other",
            "zeep_public_id": "public-other",
        }

        result = erase_local_user_account(
            "person@example.com",
            **deps["kwargs"],
        )

        self.assertEqual(result["account_aliases"], ["person@example.com"])
        self.assertEqual(
            result["skipped_alias_collisions"],
            ["other@example.com"],
        )
        self.assertIn("other@example.com", deps["profiles"])
        _query, params = deps["database"].read_query
        self.assertEqual(params, ("person@example.com",))

    def test_same_public_id_allows_redundant_canonical_alias_cleanup(self):
        deps = self.dependencies()
        deps["profiles"]["person@example.com"].update(
            {
                "zeep_public_id": "public-person",
                "legacy_account_keys": ["old-login"],
            }
        )
        deps["profiles"]["old-login"] = {
            "zeep_public_id": "public-person",
        }

        result = erase_local_user_account(
            "person@example.com",
            **deps["kwargs"],
        )

        self.assertEqual(
            result["account_aliases"],
            ["old-login", "person@example.com"],
        )
        self.assertEqual(result["skipped_alias_collisions"], [])
        self.assertNotIn("old-login", deps["profiles"])

    def test_ambiguous_legacy_alias_never_selects_an_account_to_erase(self):
        deps = self.dependencies()
        deps["profiles"]["person@example.com"].update({
            "zeep_public_id": "public-person",
            "legacy_account_keys": ["shared-login"],
        })
        deps["profiles"]["other@example.com"] = {
            "zeep_public_id": "public-other",
            "legacy_account_keys": ["shared-login"],
        }

        with self.assertRaises(AccountErasureError):
            erase_local_user_account(
                "shared-login",
                **deps["kwargs"],
            )

        self.assertFalse(hasattr(deps["database"], "read_query"))
        self.assertIn("person@example.com", deps["profiles"])
        self.assertIn("other@example.com", deps["profiles"])
        self.assertEqual(deps["baseline"].deleted, [])

    def test_failed_bcg_flush_keeps_session_rows_and_identity_for_retry(self):
        deps = self.dependencies(flush_results=[False])

        with self.assertRaises(AccountErasureError):
            erase_local_user_account(
                "person@example.com",
                **deps["kwargs"],
            )

        self.assertIn("person@example.com", deps["profiles"])
        self.assertEqual(deps["baseline"].deleted, [])
        self.assertEqual(deps["auth"].revoked, [])
        self.assertEqual(
            deps["database"].jobs,
            [("bcg", "delete_bcg_session", {"session_id": "session-1"})],
        )

    def test_failed_session_flush_keeps_identity_for_retry(self):
        deps = self.dependencies(flush_results=[True, False])

        with self.assertRaises(AccountErasureError):
            erase_local_user_account(
                "person@example.com",
                **deps["kwargs"],
            )

        self.assertIn("person@example.com", deps["profiles"])
        self.assertEqual(deps["baseline"].deleted, [])
        self.assertEqual(deps["auth"].revoked, [])

    def test_unverifiable_checkpoint_keeps_identity_for_retry(self):
        deps = self.dependencies()

        def fail_checkpoint(_keys):
            raise ValueError("damaged checkpoint")

        deps["kwargs"]["clear_session_checkpoint"] = fail_checkpoint
        with self.assertRaisesRegex(AccountErasureError, "checkpoint"):
            erase_local_user_account("person@example.com", **deps["kwargs"])

        self.assertIn("person@example.com", deps["profiles"])
        self.assertEqual(deps["baseline"].deleted, [])
        self.assertEqual(deps["auth"].revoked, [])


if __name__ == "__main__":
    unittest.main()
