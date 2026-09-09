"""Registry rules for the ZEEP QR login handshake."""

import unittest

from qr_login import DEFAULT_TTL_SECONDS, QrLoginRegistry


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class QrLoginRegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FakeClock()
        self.registry = QrLoginRegistry(clock=self.clock, grace_seconds=60.0)

    def test_remembers_secret_for_issued_login_id(self):
        self.registry.remember("login-1", "secret-1", 180)
        self.assertEqual(self.registry.secret_for("login-1"), "secret-1")

    def test_unknown_login_id_has_no_secret(self):
        """A photographed QR carries only loginId, which yields no secret."""
        self.registry.remember("login-1", "secret-1", 180)
        self.assertIsNone(self.registry.secret_for("login-2"))
        self.assertIsNone(self.registry.secret_for(""))

    def test_secret_survives_qr_ttl_so_approval_window_still_polls(self):
        """ZEEP keeps a 60 s token window open after the 180 s QR expires."""
        self.registry.remember("login-1", "secret-1", 180)
        self.clock.advance(181)
        self.assertEqual(self.registry.secret_for("login-1"), "secret-1")

    def test_secret_drops_after_ttl_plus_grace(self):
        self.registry.remember("login-1", "secret-1", 180)
        self.clock.advance(241)
        self.assertIsNone(self.registry.secret_for("login-1"))

    def test_forget_drops_ticket_immediately(self):
        self.registry.remember("login-1", "secret-1", 180)
        self.registry.forget("login-1")
        self.assertIsNone(self.registry.secret_for("login-1"))
        self.registry.forget("login-1")  # terminal states may arrive twice

    def test_expired_tickets_do_not_accumulate(self):
        for index in range(5):
            self.registry.remember(f"login-{index}", f"secret-{index}", 180)
        self.assertEqual(len(self.registry), 5)
        self.clock.advance(241)
        self.assertEqual(len(self.registry), 0)

    def test_missing_or_invalid_expiry_falls_back_to_contract_ttl(self):
        for expires_in in (None, 0, -5, "not-a-number"):
            with self.subTest(expires_in=expires_in):
                registry = QrLoginRegistry(clock=self.clock, grace_seconds=0.0)
                registry.remember("login-1", "secret-1", expires_in)
                self.clock.advance(DEFAULT_TTL_SECONDS - 1)
                self.assertEqual(registry.secret_for("login-1"), "secret-1")
                self.clock.advance(2)
                self.assertIsNone(registry.secret_for("login-1"))

    def test_rejects_incomplete_ticket(self):
        with self.assertRaises(ValueError):
            self.registry.remember("", "secret-1", 180)
        with self.assertRaises(ValueError):
            self.registry.remember("login-1", "", 180)


if __name__ == "__main__":
    unittest.main()
