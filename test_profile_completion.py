"""Regression tests for the profile gate that runs before a Session starts.

An account registered on the phone can reach the pod with no gender, date of
birth, height or weight.  These tests pin the two halves of the contract: the
pod refuses to claim an occupant until the ZEEP account carries those four, and
the answer is written back to ZEEP rather than kept on the appliance.
"""

from __future__ import annotations

import unittest
import unittest.mock
from datetime import date

from fastapi import HTTPException
from fastapi.testclient import TestClient

from profile_completion import (
    PendingProfileRegistry,
    build_zeep_patch,
    missing_required_fields,
)
from testing_support import configure_app_test_environment
from identity.profile_fields import normalise_blood_group

_test_root = configure_app_test_environment()

import app as pod_app  # noqa: E402  (environment must be set before import)


COMPLETE_ME = {
    "gender": "male",
    "dateOfBirth": "1995-08-21",
    "heightCm": 175,
    "weightKg": 68.5,
    "bloodGroup": "O",
}

LOGIN_ID = "9a5a4f9e-0d0b-4c1f-9a9a-0f2f6d1c77aa"
POLL_SECRET = "q" * 64


def blank_me(**overrides):
    """A freshly registered account: identity only, no health facts."""
    me = {
        "publicId": "public-fresh",
        "username": "fresh-user",
        "email": "fresh.user@example.test",
        "displayName": "Fresh User",
        "gender": None,
        "dateOfBirth": None,
        "heightCm": None,
        "weightKg": None,
        "bloodGroup": None,
    }
    me.update(overrides)
    return me


def form(**overrides):
    body = {
        "gender": "male",
        "date_of_birth": "1995-08-21",
        "height_cm": 175,
        "weight_kg": 68.5,
        "blood_group": "O",
    }
    body.update(overrides)
    return body


class BloodGroupMappingTests(unittest.TestCase):
    """The account API offers ABO on its own; the pod must not drop it."""

    def test_abo_without_rh_is_a_real_answer(self) -> None:
        for raw, expected in (("A", "A"), ("B", "B"), ("AB", "AB"), ("O", "O")):
            with self.subTest(raw=raw):
                self.assertEqual(normalise_blood_group(raw), expected)

    def test_lowercase_and_padding_still_map(self) -> None:
        self.assertEqual(normalise_blood_group(" o "), "O")
        self.assertEqual(normalise_blood_group("ab"), "AB")

    def test_rh_notation_keeps_working(self) -> None:
        self.assertEqual(normalise_blood_group("O+"), "O+")
        self.assertEqual(normalise_blood_group("AB negative"), "AB-")

    def test_unknown_stays_unknown(self) -> None:
        self.assertIsNone(normalise_blood_group(None))
        self.assertIsNone(normalise_blood_group("ไม่ทราบ"))
        self.assertIsNone(normalise_blood_group("C+"))


class MissingFieldTests(unittest.TestCase):
    def test_a_fresh_account_is_missing_all_four(self) -> None:
        self.assertEqual(
            missing_required_fields(blank_me()),
            ("gender", "date_of_birth", "height_cm", "weight_kg"),
        )

    def test_a_complete_account_needs_nothing(self) -> None:
        self.assertEqual(missing_required_fields(COMPLETE_ME), ())

    def test_blood_group_never_gates_a_session(self) -> None:
        self.assertEqual(missing_required_fields({**COMPLETE_ME, "bloodGroup": None}), ())

    def test_gender_prefer_not_to_say_counts_as_answered(self) -> None:
        """An account that chose not to say has answered; do not ask again."""
        self.assertEqual(
            missing_required_fields({**COMPLETE_ME, "gender": "prefer_not_to_say"}),
            (),
        )

    def test_unusable_values_count_as_missing(self) -> None:
        self.assertIn("date_of_birth", missing_required_fields({**COMPLETE_ME, "dateOfBirth": "not-a-date"}))
        self.assertIn("height_cm", missing_required_fields({**COMPLETE_ME, "heightCm": 3}))
        self.assertIn("weight_kg", missing_required_fields({**COMPLETE_ME, "weightKg": 0}))


class PatchBuilderTests(unittest.TestCase):
    def test_shapes_the_payload_the_account_api_expects(self) -> None:
        self.assertEqual(
            build_zeep_patch(
                gender="male",
                date_of_birth="1995-08-21",
                height_cm=175,
                weight_kg=68.5,
                blood_group="O",
            ),
            {
                "gender": "male",
                "dateOfBirth": "1995-08-21",
                "heightCm": 175.0,
                "weightKg": 68.5,
                "bloodGroup": "O",
            },
        )

    def test_unknown_blood_group_is_sent_as_null_not_omitted(self) -> None:
        """The account API updates only the keys it receives."""
        patch = build_zeep_patch(**form(blood_group=""))
        self.assertIn("bloodGroup", patch)
        self.assertIsNone(patch["bloodGroup"])

    def test_gender_accepts_only_what_the_account_api_stores(self) -> None:
        for gender in ("male", "female", "other"):
            with self.subTest(gender=gender):
                self.assertEqual(build_zeep_patch(**form(gender=gender))["gender"], gender)
        with self.assertRaises(HTTPException):
            build_zeep_patch(**form(gender="unspecified"))

    def test_a_date_that_never_existed_is_refused(self) -> None:
        """The form cannot offer 31 February, but the server must not rely on it."""
        for bad in ("1995-02-31", "1995-04-31", "1999-02-29", "1995-13-01"):
            with self.subTest(date_of_birth=bad):
                with self.assertRaises(HTTPException):
                    build_zeep_patch(**form(date_of_birth=bad))

    def test_bounds_match_the_session_guards(self) -> None:
        """Reject here rather than update the account and fail the Session."""
        today = date(2026, 9, 15)
        for field, value in (
            ("date_of_birth", "2015-01-01"),  # under 18
            ("date_of_birth", "1900-01-01"),  # over 100
            ("height_cm", 40),
            ("weight_kg", 500),
        ):
            with self.subTest(field=field, value=value):
                with self.assertRaises(HTTPException):
                    build_zeep_patch(**form(**{field: value}), today=today)


class PendingRegistryTests(unittest.TestCase):
    def test_a_ticket_reclaims_the_parked_login_exactly_once(self) -> None:
        registry = PendingProfileRegistry()
        ticket = registry.remember({"username": "u"}, {"gender": None}, ("gender",))
        pending = registry.consume(ticket)
        self.assertIsNotNone(pending)
        self.assertEqual(pending.auth["username"], "u")
        self.assertIsNone(registry.consume(ticket))

    def test_an_abandoned_form_stops_holding_tokens(self) -> None:
        now = [0.0]
        registry = PendingProfileRegistry(clock=lambda: now[0], ttl_seconds=60.0)
        ticket = registry.remember({"username": "u"}, {}, ())
        now[0] = 61.0
        self.assertIsNone(registry.consume(ticket))

    def test_an_unknown_ticket_is_refused(self) -> None:
        self.assertIsNone(PendingProfileRegistry().consume("never-issued"))

    def test_account_erasure_discards_only_matching_pending_login(self) -> None:
        registry = PendingProfileRegistry()
        removed_ticket = registry.remember(
            {"username": "one", "email": "one@example.test"},
            {},
            (),
        )
        kept_ticket = registry.remember(
            {"username": "two", "email": "two@example.test"},
            {},
            (),
        )

        self.assertEqual(registry.discard_account("ONE@example.test"), 1)
        self.assertIsNone(registry.consume(removed_ticket))
        self.assertIsNotNone(registry.consume(kept_ticket))


class FakeZeep:
    """Stand in for the account API, recording what the pod wrote."""

    def __init__(self, me, *, offline_on=()):
        self.me = dict(me)
        self.offline_on = set(offline_on)
        self.calls: list[tuple[str, str]] = []
        self.patches: list[dict] = []

    def __call__(self, method, path, *, json_body=None, token=None, **_kw):
        self.calls.append((method, path))
        if (method, path) in self.offline_on:
            raise pod_app.ZeepApiOffline("test offline")
        if path == "/v1/users/me" and method == "PATCH":
            assert token == "access-token", "the pod must write as the occupant"
            self.patches.append(dict(json_body))
            self.me.update(json_body)
            return {"status": "success", "data": dict(self.me)}
        if path == "/v1/users/me":
            return {"status": "success", "data": dict(self.me)}
        if path == "/v1/auth/logout":
            return {"status": "success", "data": {}}
        if path == "/v1/auth/qr/session":
            return {"status": "success", "data": {
                "loginId": LOGIN_ID,
                "pollSecret": POLL_SECRET,
                "qrCode": "data:image/png;base64,iVBORw0KGgo=",
                "expiresIn": 180,
            }}
        if path == "/v1/auth/qr/poll":
            return {"status": "success", "data": {
                "state": "approved",
                "tokens": {"accessToken": "access-token", "refreshToken": "refresh-token"},
                "user": {
                    "publicId": "public-fresh",
                    "username": "fresh-user",
                    "email": "fresh.user@example.test",
                    "displayName": "Fresh User",
                    "role": "user",
                    "plan": "test",
                },
            }}
        raise AssertionError(f"unexpected ZEEP call: {method} {path}")


class ProfileGateApiTests(unittest.TestCase):
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
        self.original_request = pod_app._zeep_request
        self.original_auth = pod_app._authenticate_zeep_account
        self.client = TestClient(pod_app.app)

    def tearDown(self) -> None:
        pod_app.qr_logins.forget(LOGIN_ID)
        if pod_app._active_session is not None:
            pod_app._finalize_active_session("profile_gate_test_cleanup")
        pod_app._zeep_request = self.original_request
        pod_app._authenticate_zeep_account = self.original_auth

    def install(self, me, **kwargs) -> FakeZeep:
        fake = FakeZeep(me, **kwargs)
        pod_app._zeep_request = fake
        pod_app._authenticate_zeep_account = lambda *_a, **_kw: (
            {
                "public_id": "public-fresh",
                "username": "fresh-user",
                "email": "fresh.user@example.test",
                "display_name": "Fresh User",
                "role": "user",
                "plan": "test",
                "access_token": "access-token",
                "refresh_token": "refresh-token",
                "profile_refreshed": True,
            },
            dict(fake.me),
        )
        return fake

    def login(self, password="valid"):
        return self.client.post(
            "/api/auth/login",
            json={"identifier": "fresh-user", "password": password},
        )

    # ---- the gate --------------------------------------------------------
    def test_an_incomplete_account_is_asked_before_the_pod_is_claimed(self) -> None:
        self.install(blank_me())
        r = self.login()
        self.assertEqual(r.status_code, 422, r.text)
        detail = r.json()["detail"]
        self.assertEqual(detail["code"], "profile_incomplete")
        self.assertEqual(
            detail["missing"], ["gender", "date_of_birth", "height_cm", "weight_kg"]
        )
        self.assertTrue(detail["profile_ticket"])
        # No Session, no lease and no cookie: an abandoned form must leave the
        # pod free for the next person.
        self.assertIsNone(pod_app._active_session)
        self.assertNotIn(pod_app.COOKIE_NAME, self.client.cookies)

    def test_only_the_missing_fields_are_named(self) -> None:
        self.install(blank_me(gender="female", dateOfBirth="1995-08-21"))
        detail = self.login().json()["detail"]
        self.assertEqual(detail["missing"], ["height_cm", "weight_kg"])

    def test_a_complete_account_starts_a_session_untouched(self) -> None:
        fake = self.install(dict(COMPLETE_ME))
        r = self.login()
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(fake.patches, [], "a complete account must not be rewritten")

    def test_password_login_preserves_the_selected_90_minute_nap_target(self) -> None:
        self.install(dict(COMPLETE_ME))
        response = self.client.post(
            "/api/auth/login",
            json={
                "identifier": "fresh-user",
                "password": "valid",
                "rest_mode": "nap_recovery",
                "target_duration_minutes": 90,
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["session"]["target_duration_s"], 90 * 60)

    def test_local_login_preserves_the_selected_90_minute_nap_target(self) -> None:
        identifier = "local-nap-90@example.test"
        ticket = pod_app.auth_sessions.issue_offline_ticket(identifier)
        response = self.client.post(
            "/api/session/login",
            json={
                "username": "local-nap-90",
                "gender": "female",
                "age_group": "30-44",
                "offline_ticket": ticket,
                "offline_identifier": identifier,
                "rest_mode": "nap_recovery",
                "target_duration_minutes": 90,
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["session"]["target_duration_s"], 90 * 60)

    def test_blood_group_alone_never_triggers_the_form(self) -> None:
        self.install({**COMPLETE_ME, "bloodGroup": None})
        self.assertEqual(self.login().status_code, 200)

    # ---- answering it ----------------------------------------------------
    def test_the_answer_is_written_to_zeep_and_then_starts_the_session(self) -> None:
        fake = self.install(blank_me())
        ticket = self.login().json()["detail"]["profile_ticket"]

        r = self.client.post(
            "/api/auth/profile/complete",
            json={"profile_ticket": ticket, **form()},
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(
            fake.patches,
            [{
                "gender": "male",
                "dateOfBirth": "1995-08-21",
                "heightCm": 175.0,
                "weightKg": 68.5,
                "bloodGroup": "O",
            }],
        )
        # The Session must be bound to what ZEEP confirmed, re-read after the
        # write, not to the values typed at the tablet.
        self.assertIn(("GET", "/v1/users/me"), fake.calls[fake.calls.index(("PATCH", "/v1/users/me")):])
        health = r.json()["session"]["health_reference"]
        self.assertEqual(health["gender"], "male")
        self.assertEqual(health["height_cm"], 175.0)
        self.assertEqual(health["weight_kg"], 68.5)
        self.assertEqual(health["blood_group"], "O")
        self.assertEqual(health["age_group"], "30-44")
        self.assertIsNotNone(pod_app._active_session)

    def test_profile_completion_preserves_the_selected_90_minute_nap_target(
        self,
    ) -> None:
        self.install(blank_me())
        ticket = self.login().json()["detail"]["profile_ticket"]
        response = self.client.post(
            "/api/auth/profile/complete",
            json={
                "profile_ticket": ticket,
                "rest_mode": "nap_recovery",
                "target_duration_minutes": 90,
                **form(),
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["session"]["target_duration_s"], 90 * 60)

    def test_an_unknown_blood_group_still_completes_the_login(self) -> None:
        fake = self.install(blank_me())
        ticket = self.login().json()["detail"]["profile_ticket"]
        r = self.client.post(
            "/api/auth/profile/complete",
            json={"profile_ticket": ticket, **form(blood_group="")},
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIsNone(fake.patches[0]["bloodGroup"])
        self.assertIsNone(r.json()["session"]["health_reference"]["blood_group"])

    def test_a_ticket_cannot_be_replayed(self) -> None:
        self.install(blank_me())
        ticket = self.login().json()["detail"]["profile_ticket"]
        self.assertEqual(
            self.client.post(
                "/api/auth/profile/complete", json={"profile_ticket": ticket, **form()}
            ).status_code,
            200,
        )
        pod_app._finalize_active_session("replay_test")
        replay = self.client.post(
            "/api/auth/profile/complete", json={"profile_ticket": ticket, **form()}
        )
        self.assertEqual(replay.status_code, 422)
        self.assertEqual(replay.json()["detail"]["code"], "profile_ticket_invalid")

    def test_an_unknown_ticket_is_refused(self) -> None:
        self.install(blank_me())
        r = self.client.post(
            "/api/auth/profile/complete", json={"profile_ticket": "made-up", **form()}
        )
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.json()["detail"]["code"], "profile_ticket_invalid")

    def test_a_rejected_form_can_be_retried_without_logging_in_again(self) -> None:
        """A QR login cannot re-authenticate — hand back a usable ticket."""
        fake = self.install(blank_me())
        ticket = self.login().json()["detail"]["profile_ticket"]

        bad = self.client.post(
            "/api/auth/profile/complete",
            json={"profile_ticket": ticket, **form(height_cm=12)},
        )
        self.assertEqual(bad.status_code, 422, bad.text)
        self.assertEqual(bad.json()["detail"]["code"], "profile_invalid")
        self.assertEqual(fake.patches, [], "an invalid form must not reach ZEEP")

        retry = bad.json()["detail"]["profile_ticket"]
        self.assertNotEqual(retry, ticket)
        self.assertEqual(
            self.client.post(
                "/api/auth/profile/complete", json={"profile_ticket": retry, **form()}
            ).status_code,
            200,
        )

    def test_zeep_offline_blocks_instead_of_starting_a_session(self) -> None:
        """These facts live in the account; there is nothing to fall back to."""
        self.install(blank_me(), offline_on={("PATCH", "/v1/users/me")})
        ticket = self.login().json()["detail"]["profile_ticket"]
        r = self.client.post(
            "/api/auth/profile/complete", json={"profile_ticket": ticket, **form()}
        )
        self.assertEqual(r.status_code, 503, r.text)
        detail = r.json()["detail"]
        self.assertEqual(detail["code"], "profile_update_offline")
        self.assertNotIn("offline_ticket", detail, "no local fallback for profile data")
        self.assertTrue(detail["profile_ticket"], "the user may retry the same form")
        self.assertIsNone(pod_app._active_session)

    def test_the_form_is_refused_once_someone_else_took_the_pod(self) -> None:
        self.install(blank_me())
        ticket = self.login().json()["detail"]["profile_ticket"]
        with unittest.mock.patch.object(pod_app, "_active_session", {"id": "busy"}):
            r = self.client.post(
                "/api/auth/profile/complete", json={"profile_ticket": ticket, **form()}
            )
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["detail"]["code"], "pod_already_occupied")

    # ---- QR login --------------------------------------------------------
    def test_qr_login_reaches_the_same_gate(self) -> None:
        """An approved QR releases its tokens once, so the ticket must carry them."""
        fake = self.install(blank_me())
        self.client.post("/api/auth/qr/session")
        poll = self.client.post("/api/auth/qr/poll", json={"login_id": LOGIN_ID})
        self.assertEqual(poll.status_code, 422, poll.text)
        detail = poll.json()["detail"]
        self.assertEqual(detail["code"], "profile_incomplete")

        r = self.client.post(
            "/api/auth/profile/complete",
            json={"profile_ticket": detail["profile_ticket"], **form()},
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(len(fake.patches), 1)
        self.assertEqual(r.json()["session"]["health_reference"]["gender"], "male")

    def test_an_unreachable_profile_is_not_called_incomplete(self) -> None:
        """A failed /users/me says nothing about the account; keep the cache."""
        self.install(dict(COMPLETE_ME))
        self.assertEqual(self.login().status_code, 200)
        pod_app._finalize_active_session("cached_test")

        fake = self.install({})
        pod_app._authenticate_zeep_account = lambda *_a, **_kw: (
            {
                "public_id": "public-fresh",
                "username": "fresh-user",
                "email": "fresh.user@example.test",
                "display_name": "Fresh User",
                "role": "user",
                "plan": "test",
                "access_token": "access-token",
                "refresh_token": "refresh-token",
                "profile_refreshed": False,
            },
            {},
        )
        r = self.login()
        self.assertEqual(r.status_code, 200, r.text)
        health = r.json()["session"]["health_reference"]
        self.assertEqual(health["refresh_status"], "cached")
        self.assertEqual(health["height_cm"], 175.0)
        self.assertEqual(fake.patches, [])

    # ---- an account the pod already knows --------------------------------
    def test_a_returning_occupant_is_asked_again_while_zeep_stays_empty(self) -> None:
        """A local age-group guess must not stand in for the account's own facts."""
        self.install(dict(COMPLETE_ME))
        self.assertEqual(self.login().status_code, 200)
        pod_app._finalize_active_session("returning_test")

        self.install(blank_me())
        r = self.login()
        self.assertEqual(r.status_code, 422, r.text)
        self.assertEqual(r.json()["detail"]["code"], "profile_incomplete")


if __name__ == "__main__":
    unittest.main()
