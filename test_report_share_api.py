"""API-level regression tests for the post-Session QR share.

The feature is a kill-switchable addition to a flow that already works, so
these tests pin both halves: with the switch off the pod must behave exactly
as it did before, and with it on the share must never be able to break ending
a Session.  The ZEEP upload is faked at ``_zeep_request``, the same seam
``test_session_ingest`` and ``test_qr_login_api`` use.
"""
from __future__ import annotations

import base64
import threading
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from testing_support import configure_app_test_environment

_test_root = configure_app_test_environment()

import app as pod_app  # noqa: E402  (environment must be set before import)

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"canvas-pixels").decode()
UPLOADED = {
    "status": "success",
    "data": {
        "blobName": "sleep-reports/night.png",
        "url": "https://blob.example/private/night.png",
        "signedUrl": "https://blob.example/private/night.png?sig=abc",
    },
}


def csrf(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies.get("zeep_csrf") or ""}


def fake_zeep_account(_identifier: str, _password: str):
    return (
        {
            "public_id": "public-share-user",
            "username": "share-user",
            "email": "share.user@example.test",
            "display_name": "Share User",
            "role": "user",
            "plan": "test",
            "access_token": "occupant-access-token",
            "refresh_token": None,
            "profile_refreshed": True,
        },
        {"gender": "male", "dateOfBirth": "1990-01-01"},
    )


def finished_record() -> dict:
    """A finished record shaped as finalization leaves it, report included."""
    return {
        "session_id": "share-session-1",
        "identity_subject": "zeep:share-user",
        "username": "share.user@example.test",
        "display_name": "Share User",
        "duration_s": 20_000.0,
        "ended_at_utc": "2026-09-10T00:30:00+00:00",
        "recording_started": True,
        "sleep_quality": {"available": True, "score": 74, "level": "ดี"},
        "session_report": {"available": True, "sleep": {"estimated_sleep_s": 18_000}},
    }


class ReportShareApiTests(unittest.TestCase):
    """Drive the routes through a real login so the wiring is covered too."""

    @classmethod
    def setUpClass(cls) -> None:
        pod_app.database.initialize()
        pod_app.database.start()

    @classmethod
    def tearDownClass(cls) -> None:
        if pod_app._active_session is not None:
            pod_app._finalize_active_session("report_share_test_cleanup")
        pod_app.database.stop()

    def setUp(self) -> None:
        self._authenticate = pod_app._authenticate_zeep_account
        pod_app._authenticate_zeep_account = fake_zeep_account
        self.addCleanup(setattr, pod_app, "_authenticate_zeep_account", self._authenticate)
        self.addCleanup(self._close_session)
        self.registry = pod_app.report_shares
        self.addCleanup(setattr, self.registry, "enabled", self.registry.enabled)
        # The registry is a process singleton; drop what a sibling test left.
        self.registry.discard(finished_record()["identity_subject"])
        self.addCleanup(self.registry.discard, finished_record()["identity_subject"])

    def _close_session(self) -> None:
        if pod_app._active_session is not None:
            pod_app._finalize_active_session("report_share_test_cleanup")

    def login(self) -> TestClient:
        client = TestClient(pod_app.app)
        response = client.post(
            "/api/auth/login",
            json={"identifier": "share-user", "password": "valid"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return client

    def drop_active_session(self) -> None:
        """Clear ownership the way finalization's first lines do."""
        with pod_app.session_lock:
            active = pod_app._active_session
            pod_app._active_session = None
        lease = (active or {}).get("occupancy_lease")
        if lease is not None:
            pod_app.occupancy_client.release(lease)

    def issue_ticket(self) -> str:
        record = finished_record()
        self.registry.reserve(record["identity_subject"])
        self.registry.fulfil(record, access_token="occupant-access-token")
        share = self.registry.share_for(record["identity_subject"])
        self.assertIsNotNone(share)
        return share["ticket"]

    # ---- switch off: today's behaviour, byte for byte ----

    def test_the_switch_is_off_by_default(self) -> None:
        self.assertFalse(
            pod_app.ReportShareRegistry().enabled,
            "a new pod must not start sending reports off-device",
        )

    def test_disabled_pod_offers_no_ticket_and_no_route(self) -> None:
        self.registry.enabled = False
        client = self.login()
        state = client.get("/api/state")
        self.assertEqual(state.status_code, 200, state.text)
        self.assertIs(state.json()["features"]["session_report_share"], False)

        ended = client.post("/api/session/logout", headers=csrf(client))
        self.assertEqual(ended.status_code, 200, ended.text)
        self.assertIsNone(ended.json()["report_share"])

        refused = client.post(
            "/api/session/report-share",
            json={"ticket": "anything", "image_base64": PNG},
        )
        self.assertEqual(refused.status_code, 404)
        self.assertEqual(len(self.registry), 0)

    # ---- switch on ----

    def test_enabled_pod_advertises_the_feature(self) -> None:
        self.registry.enabled = True
        client = self.login()
        state = client.get("/api/state")
        self.assertIs(state.json()["features"]["session_report_share"], True)

    def test_a_login_that_never_recorded_leaves_no_pending_notice(self) -> None:
        """Otherwise the tablet's socket waits eight seconds for nothing."""
        self.registry.enabled = True
        client = self.login()
        ended = client.post("/api/session/logout", headers=csrf(client))
        self.assertEqual(ended.status_code, 200, ended.text)
        self.assertIs(ended.json()["recording_started"], False)
        self.assertIsNone(ended.json()["report_share"])
        self.assertEqual(len(self.registry), 0)

    def test_a_ticket_is_exchanged_for_a_qr_and_cannot_be_reused(self) -> None:
        self.registry.enabled = True
        ticket = self.issue_ticket()
        client = TestClient(pod_app.app)
        with patch.object(pod_app, "_zeep_request", return_value=UPLOADED) as upload:
            first = client.post(
                "/api/session/report-share",
                json={"ticket": ticket, "image_base64": PNG},
            )
        self.assertEqual(first.status_code, 200, first.text)
        body = first.json()
        self.assertTrue(body["ok"])
        self.assertTrue(body["qr_data_url"].startswith("data:image/png;base64,"))
        self.assertEqual(body["expires_in_minutes"], 60)
        # The occupant's own token authorizes the upload; no api_key path.
        self.assertEqual(upload.call_args.kwargs["token"], "occupant-access-token")
        self.assertEqual(upload.call_args.args[1], "/uploads")
        # The token must not travel back to the browser.
        self.assertNotIn("occupant-access-token", first.text)

        reused = client.post(
            "/api/session/report-share",
            json={"ticket": ticket, "image_base64": PNG},
        )
        self.assertEqual(reused.status_code, 404)

    def test_an_offline_backend_degrades_instead_of_failing(self) -> None:
        self.registry.enabled = True
        ticket = self.issue_ticket()
        client = TestClient(pod_app.app)
        with patch.object(
            pod_app, "_zeep_request",
            side_effect=pod_app.ZeepApiOffline("ConnectError: no route"),
        ):
            response = client.post(
                "/api/session/report-share",
                json={"ticket": ticket, "image_base64": PNG},
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"ok": False, "reason": "upload_failed"})

    def test_a_non_png_is_refused_without_spending_an_upload(self) -> None:
        self.registry.enabled = True
        ticket = self.issue_ticket()
        client = TestClient(pod_app.app)
        with patch.object(pod_app, "_zeep_request") as upload:
            response = client.post(
                "/api/session/report-share",
                json={"ticket": ticket, "image_base64": base64.b64encode(b"GIF89a").decode()},
            )
        self.assertEqual(response.json(), {"ok": False, "reason": "invalid_image"})
        upload.assert_not_called()

    def start_recording(self) -> None:
        """Pass the bed + fresh HR/RR gate the way the sampler would."""
        with pod_app.session_lock:
            active = pod_app._active_session
        with pod_app.state_lock:
            pod_app.state["sensor"]["bcg"].update({
                "connected": True,
                "last_update": time.time(),
                "status_code": 0,
                "status_text": "On bed",
                "heart_rate_bpm": 61.0,
                "respiration_rate": 14.5,
                "heart_rate_current_valid": True,
                "respiration_current_valid": True,
                "heart_rate_held": False,
                "respiration_held": False,
                "packets": (
                    active["vital_gate_start_packet_count"]
                    + pod_app.SESSION_VITAL_START_PACKETS
                ),
                "vital_valid_streak": pod_app.SESSION_VITAL_START_PACKETS,
            })
        pod_app._begin_recording(active)
        with pod_app.session_lock:
            # A report needs a non-zero duration; backdate rather than sleep.
            active["record"]["started_monotonic"] -= 600.0
            now = time.time() - 600.0
            for index in range(3):
                sample = pod_app.take_session_sample()
                sample["t"] = round(now + index * 10.0, 1)
                active["samples"].append(sample)

    def test_a_recorded_session_hands_its_tablet_a_working_ticket(self) -> None:
        """The whole point: finalize must leave a ticket the tablet can spend."""
        self.registry.enabled = True
        client = self.login()
        subject = pod_app._active_session["record"]["identity_subject"]
        self.addCleanup(self.registry.discard, subject)
        self.start_recording()

        ended = client.post("/api/session/logout", headers=csrf(client))
        self.assertEqual(ended.status_code, 200, ended.text)
        body = ended.json()
        self.assertIs(body["recording_started"], True)
        self.assertIs(body["session_report"]["available"], True)
        ticket = body["report_share"]["ticket"]
        self.assertTrue(ticket)
        self.assertNotIn("occupant-access-token", ended.text)

        with patch.object(pod_app, "_zeep_request", return_value=UPLOADED):
            shared = client.post(
                "/api/session/report-share",
                json={"ticket": ticket, "image_base64": PNG},
            )
        self.assertEqual(shared.status_code, 200, shared.text)
        self.assertTrue(shared.json()["ok"])

    def test_the_socket_waits_for_a_reserved_notice_before_closing_4403(self) -> None:
        """The bug this reservation exists for.

        ``_finalize_active_session`` clears ownership on its first line and
        only issues the ticket after the database flush and the account
        upload.  Without the reservation the tablet's socket closes 4403 into
        that gap and the occupant loses the screen the ticket was meant for.
        """
        self.registry.enabled = True
        client = self.login()
        record = dict(pod_app._active_session["record"])
        subject = record["identity_subject"]
        self.addCleanup(self.registry.discard, subject)
        record.update(finished_record())
        record["identity_subject"] = subject

        with client.websocket_connect("/ws") as ws:
            self.assertIn("session", ws.receive_json())
            # Production ordering: reserve, drop ownership, then do slow work.
            self.registry.reserve(subject)
            self.drop_active_session()
            timer = threading.Timer(
                0.6, self.registry.fulfil, args=(record,),
                kwargs={"access_token": "occupant-access-token"},
            )
            timer.start()
            self.addCleanup(timer.cancel)
            while True:
                message = ws.receive_json()
                if message.get("type") == "session_ended":
                    break
            self.assertEqual(message["report"]["session_id"], "share-session-1")
            self.assertTrue(message["report_share"]["ticket"])
            self.assertNotIn("occupant-access-token", str(message))

    def test_the_socket_still_closes_at_once_when_nothing_is_reserved(self) -> None:
        self.registry.enabled = True
        client = self.login()
        with client.websocket_connect("/ws") as ws:
            self.assertIn("session", ws.receive_json())
            self.drop_active_session()
            with self.assertRaises(WebSocketDisconnect) as closed:
                for _ in range(20):
                    ws.receive_json()
        self.assertEqual(closed.exception.code, 4403)

    def test_an_unknown_ticket_is_refused(self) -> None:
        self.registry.enabled = True
        client = TestClient(pod_app.app)
        response = client.post(
            "/api/session/report-share",
            json={"ticket": "forged", "image_base64": PNG},
        )
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
