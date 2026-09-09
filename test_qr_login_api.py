"""API-level regression tests for QR login.

The ZEEP API is faked at the ``_zeep_request`` boundary: these tests assert the
pod's half of the contract — that ``pollSecret`` never leaves the Pi and that an
approved QR lands in exactly the same pod session as a password login.
"""
from __future__ import annotations

import unittest
import unittest.mock

from fastapi.testclient import TestClient

from testing_support import configure_app_test_environment

_test_root = configure_app_test_environment()

import app as pod_app  # noqa: E402  (environment must be set before import)


POLL_SECRET = "s" * 64
LOGIN_ID = "bef864d1-a4fe-4eab-b9df-5d48bca889a1"

APPROVED_USER = {
    "publicId": "public-qr-user",
    "username": "qr-user",
    "email": "qr.user@example.test",
    "displayName": "QR User",
    "role": "user",
    "plan": "test",
}


class FakeZeep:
    """Stand in for the ZEEP API, one scripted poll state at a time."""

    def __init__(self, poll_states, profile=None):
        self.poll_states = list(poll_states)
        self.profile = {"gender": "male", "dateOfBirth": "1990-01-01"}
        if profile is not None:
            self.profile = profile
        self.calls: list[tuple[str, str]] = []

    def __call__(self, method, path, *, json_body=None, token=None, **_kw):
        self.calls.append((method, path))
        if path == "/v1/auth/qr/session":
            return {"status": "success", "data": {
                "loginId": LOGIN_ID,
                "pollSecret": POLL_SECRET,
                "qrPayload": '{"t":"zeep-qr-login","v":1,"loginId":"%s"}' % LOGIN_ID,
                "qrCode": "data:image/png;base64,iVBORw0KGgo=",
                "expiresAt": "2026-09-09T12:00:00.000Z",
                "expiresIn": 180,
            }}
        if path == "/v1/auth/qr/poll":
            assert json_body["pollSecret"] == POLL_SECRET, "Pi sent the wrong secret"
            assert json_body["loginId"] == LOGIN_ID
            return {"status": "success", "data": self.poll_states.pop(0)}
        if path == "/v1/users/me":
            return {"status": "success", "data": self.profile}
        raise AssertionError(f"unexpected ZEEP call: {method} {path}")


def approved_payload():
    return {
        "state": "approved",
        "tokens": {"accessToken": "access-token", "refreshToken": "refresh-token"},
        "user": dict(APPROVED_USER),
    }


class QrLoginApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        pod_app.database.initialize()
        pod_app.database.start()

    @classmethod
    def tearDownClass(cls) -> None:
        if pod_app._active_session is not None:
            pod_app._finalize_active_session("test_cleanup")
        pod_app.database.stop()

    def setUp(self) -> None:
        self.original = pod_app._zeep_request
        self.client = TestClient(pod_app.app)

    def tearDown(self) -> None:
        pod_app._zeep_request = self.original
        pod_app.qr_logins.forget(LOGIN_ID)
        if pod_app._active_session is not None:
            pod_app._finalize_active_session("qr_test_cleanup")

    def install(self, *poll_states, profile=None) -> FakeZeep:
        fake = FakeZeep(poll_states, profile=profile)
        pod_app._zeep_request = fake
        return fake

    # ---- session ---------------------------------------------------------
    def test_session_hands_the_browser_the_qr_but_never_the_secret(self) -> None:
        self.install()
        r = self.client.post("/api/auth/qr/session")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["login_id"], LOGIN_ID)
        self.assertTrue(body["qr_code"].startswith("data:image/png;base64,"))
        self.assertEqual(body["expires_in"], 180)
        self.assertNotIn(POLL_SECRET, r.text)
        self.assertNotIn("poll_secret", body)
        self.assertNotIn("pollSecret", body)

    def test_session_keeps_the_secret_for_the_pod_to_poll_with(self) -> None:
        self.install()
        self.client.post("/api/auth/qr/session")
        self.assertEqual(pod_app.qr_logins.secret_for(LOGIN_ID), POLL_SECRET)

    def test_session_refused_while_the_pod_is_occupied(self) -> None:
        """Refuse before spending a rate-limited QR nobody could complete."""
        fake = self.install()
        with unittest.mock.patch.object(pod_app, "_active_session", {"id": "busy"}):
            r = self.client.post("/api/auth/qr/session")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["detail"]["code"], "pod_already_occupied")
        self.assertEqual(fake.calls, [], "must not reach ZEEP when occupied")

    def test_session_reports_zeep_offline_as_503(self) -> None:
        def offline(*_a, **_kw):
            raise pod_app.ZeepApiOffline("no route to host")

        pod_app._zeep_request = offline
        r = self.client.post("/api/auth/qr/session")
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json()["detail"]["code"], "offline")

    # ---- poll ------------------------------------------------------------
    def test_poll_of_an_unknown_login_id_never_reaches_zeep(self) -> None:
        """A photographed QR carries only loginId, and this pod holds no secret."""
        fake = self.install()
        r = self.client.post("/api/auth/qr/poll", json={"login_id": LOGIN_ID})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"state": "expired"})
        self.assertEqual(fake.calls, [])

    def test_poll_relays_pending_and_scanned(self) -> None:
        fake = self.install(
            {"state": "pending", "expiresAt": "2026-09-09T12:00:00.000Z"},
            {"state": "scanned", "scannedBy": {"displayName": "QR User"},
             "expiresAt": "2026-09-09T12:00:00.000Z"},
        )
        self.client.post("/api/auth/qr/session")
        pending = self.client.post("/api/auth/qr/poll", json={"login_id": LOGIN_ID})
        self.assertEqual(pending.json()["state"], "pending")

        scanned = self.client.post("/api/auth/qr/poll", json={"login_id": LOGIN_ID}).json()
        self.assertEqual(scanned["state"], "scanned")
        # The screen must name the scanner so a stolen QR is visible to the
        # person standing at the pod.
        self.assertEqual(scanned["scanned_by"]["display_name"], "QR User")
        self.assertIn(("POST", "/v1/auth/qr/poll"), fake.calls)

    def test_rejected_and_expired_release_the_ticket(self) -> None:
        for state in ("rejected", "expired"):
            with self.subTest(state=state):
                self.install({"state": state})
                self.client.post("/api/auth/qr/session")
                r = self.client.post("/api/auth/qr/poll", json={"login_id": LOGIN_ID})
                self.assertEqual(r.json()["state"], state)
                self.assertIsNone(pod_app.qr_logins.secret_for(LOGIN_ID))

    def test_approved_starts_the_same_pod_session_as_a_password_login(self) -> None:
        self.install(approved_payload())
        self.client.post("/api/auth/qr/session")
        r = self.client.post(
            "/api/auth/qr/poll",
            json={"login_id": LOGIN_ID, "rest_mode": "sleep"},
        )
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["state"], "approved")
        self.assertEqual(body["user"]["username"], "qr-user")
        self.assertEqual(body["user"]["email"], "qr.user@example.test")
        self.assertEqual(body["principal"]["role"], "user")
        self.assertEqual(body["session"]["rest_mode"], "sleep")
        # Same browser session contract as password login: cookie + CSRF.
        self.assertTrue(self.client.cookies.get(pod_app.COOKIE_NAME))
        self.assertTrue(self.client.cookies.get(pod_app.CSRF_COOKIE_NAME))
        self.assertEqual(self.client.get("/api/auth/me").status_code, 200)
        # Tokens are for binding the account only; they must not be echoed.
        self.assertNotIn("access-token", r.text)
        self.assertNotIn("refresh-token", r.text)

    def test_approved_is_single_use_on_this_pod_too(self) -> None:
        """ZEEP consumed the ticket, so a replayed poll must not re-enter login."""
        self.install(approved_payload())
        self.client.post("/api/auth/qr/session")
        self.assertEqual(
            self.client.post("/api/auth/qr/poll", json={"login_id": LOGIN_ID}).status_code,
            200,
        )
        self.assertIsNone(pod_app.qr_logins.secret_for(LOGIN_ID))
        replay = self.client.post("/api/auth/qr/poll", json={"login_id": LOGIN_ID})
        self.assertEqual(replay.json(), {"state": "expired"})

    def test_account_without_birthdate_asks_for_an_age_group(self) -> None:
        """The QR pane reveals the age selector on this code and offers a new QR."""
        self.install(approved_payload(), profile={"gender": "male"})
        self.client.post("/api/auth/qr/session")
        r = self.client.post("/api/auth/qr/poll", json={"login_id": LOGIN_ID})
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.json()["detail"]["code"], "age_group_required")

    def test_age_group_from_the_qr_pane_completes_login(self) -> None:
        self.install(approved_payload(), profile={"gender": "male"})
        self.client.post("/api/auth/qr/session")
        r = self.client.post(
            "/api/auth/qr/poll",
            json={"login_id": LOGIN_ID, "age_group": "30-44"},
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["session"]["age_group"], "30-44")


if __name__ == "__main__":
    import unittest.mock  # noqa: F401
    unittest.main()
