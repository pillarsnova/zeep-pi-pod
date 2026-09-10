"""Guards for the post-Session QR share.

Two things must hold no matter what the ZEEP backend does: finalizing a
Session never fails because of a share, and the occupant's access token never
leaves the Pi.  The upload boundary is faked at ``zeep_request``, the same seam
``test_session_ingest`` and ``test_qr_login_api`` use.
"""
from __future__ import annotations

import asyncio
import base64
import unittest

from zeep_pod.sessions.report_share import (
    MAX_ATTEMPTS,
    SIGNED_URL_TTL_MINUTES,
    UPLOAD_PATH,
    UPLOAD_PREFIX,
    ReportShareRegistry,
    decode_report_png,
    qr_data_uri,
    upload_report_png,
)

SUBJECT = "zeep:sleeper-1"
TOKEN = "occupant-access-token"


def png_bytes(payload: bytes = b"pixels") -> bytes:
    """A byte string that starts with the PNG magic number, like a canvas does."""
    return b"\x89PNG\r\n\x1a\n" + payload


def finished_record(**overrides) -> dict:
    record = {
        "session_id": "session-1",
        "identity_subject": SUBJECT,
        "username": "sleeper@example.test",
        "duration_s": 21_600.0,
        "ended_at_utc": "2026-09-10T00:10:00+00:00",
        "recording_started": True,
        "sleep_quality": {"available": True, "score": 78},
        "session_report": {"available": True, "sleep": {"estimated_sleep_s": 19_000}},
    }
    record.update(overrides)
    return record


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


class RegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FakeClock()
        self.registry = ReportShareRegistry(
            enabled=True, clock=self.clock, ttl_seconds=900.0
        )

    def fulfilled(self) -> str:
        self.registry.reserve(SUBJECT)
        self.registry.fulfil(finished_record(), access_token=TOKEN)
        share = self.registry.share_for(SUBJECT)
        assert share is not None
        return share["ticket"]

    def test_a_reservation_is_visible_to_the_websocket_only_once_ready(self) -> None:
        self.registry.reserve(SUBJECT)
        self.assertIsNone(self.registry.notice_for(SUBJECT))
        self.registry.fulfil(finished_record(), access_token=TOKEN)
        notice = self.registry.notice_for(SUBJECT)
        self.assertIsNotNone(notice)
        self.assertEqual(notice["session_id"], "session-1")
        self.assertEqual(notice["report"]["sleep_quality"]["score"], 78)

    def test_a_notice_never_carries_the_access_token(self) -> None:
        self.fulfilled()
        self.assertNotIn(TOKEN, repr(self.registry.notice_for(SUBJECT)))

    def test_fulfil_without_a_token_leaves_no_ticket(self) -> None:
        self.registry.reserve(SUBJECT)
        self.registry.fulfil(finished_record(), access_token=None)
        self.assertIsNone(self.registry.share_for(SUBJECT))
        self.assertEqual(len(self.registry), 0)

    def test_a_session_without_a_report_leaves_no_ticket(self) -> None:
        self.registry.reserve(SUBJECT)
        self.registry.fulfil(
            finished_record(session_report={"available": False}), access_token=TOKEN
        )
        self.assertIsNone(self.registry.share_for(SUBJECT))

    def test_fulfil_without_a_reservation_is_ignored(self) -> None:
        self.registry.fulfil(finished_record(), access_token=TOKEN)
        self.assertIsNone(self.registry.share_for(SUBJECT))

    def test_discard_releases_a_waiting_websocket_at_once(self) -> None:
        self.registry.reserve(SUBJECT)
        self.registry.discard(SUBJECT)
        self.assertIsNone(
            asyncio.run(self.registry.await_notice(SUBJECT, timeout=5.0))
        )

    def test_await_notice_returns_a_reservation_once_it_is_fulfilled(self) -> None:
        self.registry.reserve(SUBJECT)

        async def scenario():
            async def finish():
                await asyncio.sleep(0.02)
                self.registry.fulfil(finished_record(), access_token=TOKEN)

            waiter = asyncio.create_task(
                self.registry.await_notice(SUBJECT, timeout=5.0, poll=0.01)
            )
            await finish()
            return await waiter

        self.assertIsNotNone(asyncio.run(scenario()))

    def test_a_reservation_that_is_never_fulfilled_stops_the_wait(self) -> None:
        self.registry.reserve(SUBJECT)
        self.assertIsNone(
            asyncio.run(self.registry.await_notice(SUBJECT, timeout=0.03, poll=0.01))
        )

    def test_a_ticket_is_single_use(self) -> None:
        ticket = self.fulfilled()
        self.assertIsNotNone(self.registry.claim(ticket))
        self.registry.settle(ticket)
        self.assertIsNone(self.registry.claim(ticket))

    def test_a_ticket_survives_a_failed_attempt_but_not_a_flood(self) -> None:
        ticket = self.fulfilled()
        for _ in range(MAX_ATTEMPTS):
            self.assertIsNotNone(self.registry.claim(ticket))
        self.assertIsNone(self.registry.claim(ticket))
        self.assertEqual(len(self.registry), 0)

    def test_a_ticket_expires(self) -> None:
        ticket = self.fulfilled()
        self.clock.now += 901.0
        self.assertIsNone(self.registry.claim(ticket))

    def test_an_unknown_ticket_is_refused(self) -> None:
        self.fulfilled()
        self.assertIsNone(self.registry.claim("not-a-ticket"))
        self.assertIsNone(self.registry.claim(None))

    def test_a_disabled_registry_does_nothing_at_all(self) -> None:
        off = ReportShareRegistry(enabled=False)
        off.reserve(SUBJECT)
        off.fulfil(finished_record(), access_token=TOKEN)
        self.assertEqual(len(off), 0)
        self.assertIsNone(off.share_for(SUBJECT))
        self.assertIsNone(asyncio.run(off.await_notice(SUBJECT, timeout=5.0)))

    def test_registry_calls_never_raise_on_junk(self) -> None:
        # Finalization must not be able to fail because of a share.
        self.registry.reserve(None)
        self.registry.reserve("")
        self.registry.fulfil({}, access_token=TOKEN)
        self.registry.fulfil({"identity_subject": None}, access_token=TOKEN)
        self.registry.discard(None)
        self.registry.settle(None)
        self.assertEqual(len(self.registry), 0)


class DecodeReportPngTests(unittest.TestCase):
    def test_a_canvas_data_url_is_accepted(self) -> None:
        raw = png_bytes()
        payload = "data:image/png;base64," + base64.b64encode(raw).decode()
        self.assertEqual(decode_report_png(payload), raw)

    def test_bare_base64_is_accepted(self) -> None:
        raw = png_bytes()
        self.assertEqual(decode_report_png(base64.b64encode(raw).decode()), raw)

    def test_a_non_png_is_refused(self) -> None:
        jpeg = base64.b64encode(b"\xff\xd8\xff\xe0jpeg").decode()
        with self.assertRaisesRegex(ValueError, "not a PNG"):
            decode_report_png(jpeg)

    def test_broken_base64_is_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "base64"):
            decode_report_png("data:image/png;base64,!!!not-base64!!!")

    def test_an_oversized_image_is_refused_before_it_is_decoded(self) -> None:
        payload = base64.b64encode(png_bytes(b"x" * 4096)).decode()
        with self.assertRaisesRegex(ValueError, "larger than"):
            decode_report_png(payload, max_bytes=64)


class UploadReportPngTests(unittest.TestCase):
    def setUp(self) -> None:
        self.calls: list[dict] = []

    def responder(self, data):
        def zeep_request(method, path, **kwargs):
            self.calls.append({"method": method, "path": path, **kwargs})
            return {"status": "success", "data": data}

        return zeep_request

    def test_the_upload_matches_the_backend_contract(self) -> None:
        signed_url, blob_name = upload_report_png(
            png_bytes(),
            access_token=TOKEN,
            zeep_request=self.responder(
                {
                    "blobName": "sleep-reports/abc.png",
                    "url": "https://blob.example/private/abc.png",
                    "signedUrl": "https://blob.example/private/abc.png?sig=x",
                }
            ),
        )
        call = self.calls[0]
        self.assertEqual((call["method"], call["path"]), ("POST", UPLOAD_PATH))
        self.assertEqual(call["data"], {"prefix": UPLOAD_PREFIX})
        self.assertEqual(call["token"], TOKEN)
        self.assertEqual(call["files"]["file"][2], "image/png")
        self.assertTrue(call["files"]["file"][1].startswith(b"\x89PNG"))
        # data.url addresses a private container; only the SAS URL can be opened.
        self.assertEqual(signed_url, "https://blob.example/private/abc.png?sig=x")
        self.assertEqual(blob_name, "sleep-reports/abc.png")

    def test_a_response_without_a_signed_url_is_an_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "signed read URL"):
            upload_report_png(
                png_bytes(),
                access_token=TOKEN,
                zeep_request=self.responder({"blobName": "x", "url": "y"}),
            )


class QrDataUriTests(unittest.TestCase):
    def test_the_qr_is_an_inline_png(self) -> None:
        uri = qr_data_uri("https://blob.example/private/abc.png?sig=x")
        self.assertTrue(uri.startswith("data:image/png;base64,"))
        self.assertGreater(len(uri), 200)

    def test_the_expiry_matches_the_backend_default(self) -> None:
        self.assertEqual(SIGNED_URL_TTL_MINUTES, 60)


if __name__ == "__main__":
    unittest.main()
