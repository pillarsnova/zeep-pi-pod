"""Turn a finished Session into a link the occupant can scan and take home.

The pod tablet is a shared kiosk screen: once a Session ends, its result has to
leave with the person who slept rather than stay behind for the next occupant.
The tablet also sits on the pod's offline Wi-Fi hotspot and cannot reach the
ZEEP API itself, so the split is:

* the browser renders the night as a PNG (it is the only party here that can
  shape and lay out Thai text correctly), and
* the Pi uploads that PNG to the ZEEP account backend on the occupant's behalf
  and encodes the temporary read URL it gets back as a QR code.

Two disciplines are load-bearing.

The occupant's ZEEP access token never leaves this process.  It is held in
memory only, keyed by the immutable identity subject, and dropped with the
ticket; it is never returned to the browser, written to the database, or
handed to ``log_event``.  This mirrors how ``qr_login`` holds ``pollSecret``.

No :class:`ReportShareRegistry` method raises.  Finalizing a Session is the
point at which a night becomes durable, and a share is a courtesy layered on
top of it, so a defect here must never be able to fail that.

The browser proves its right to the upload with a single-use ``ticket``, not
with a cookie.  By the time the PNG exists the occupant's login is already
revoked -- always for an Admin "kick", and by the tablet's own account logout
on the normal path -- so a ticket is the only credential both paths share.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import secrets
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import segno
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

# A reserved-but-unfulfilled notice is a Session still inside finalization.
# The WebSocket waits for it, so it must self-expire well before that wait
# would otherwise hang a tablet whose finalization died part way through.
PENDING_TIMEOUT_SECONDS = 25.0
NOTICE_WAIT_SECONDS = 8.0
NOTICE_POLL_SECONDS = 0.25
# The QR is only worth anything while the occupant is still standing at the
# pod, so the ticket is deliberately short-lived and is never retried later.
TICKET_TTL_SECONDS = 900.0
# One flaky upload should not cost the occupant their QR, but a ticket is not
# an upload endpoint either.
MAX_ATTEMPTS = 3
MAX_IMAGE_BYTES = 4 * 1024 * 1024
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

# NestJS mounts UploadsController without a version segment, unlike the
# versioned auth/ingest routes, so this path carries no /v1.
UPLOAD_PATH = "/uploads"
UPLOAD_PREFIX = "sleep-reports"
UPLOAD_TIMEOUT_SECONDS = 20.0
UPLOAD_FILENAME = "sleep-report.png"
# SIGNED_URL_TTL_MINS on the account backend.  Reported to the occupant so the
# screen can say how long the QR stays good for.
SIGNED_URL_TTL_MINUTES = 60


class ReportShareCommand(BaseModel):
    """A rendered night plus the ticket that authorizes uploading it."""

    ticket: str
    image_base64: str


@dataclass
class ShareEntry:
    """One finished Session waiting for its tablet to send the rendered PNG."""

    subject: str
    expires_at: float
    session_id: str | None = None
    access_token: str | None = None
    report: dict[str, Any] = field(default_factory=dict)
    ticket: str | None = None
    ready: bool = False
    attempts: int = 0


def _shareable_report(record: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return the display half of a finished record, or None if there is none.

    A Login that never passed the bed + HR/RR gate produces no report, and a
    recorded night whose report is unavailable has nothing worth carrying home
    either.  Both cases end the share here instead of showing an empty QR.
    """
    report = record.get("session_report")
    if not isinstance(report, dict) or not report.get("available"):
        return None
    return {
        "session_id": record.get("session_id"),
        "username": record.get("username"),
        "display_name": record.get("display_name") or record.get("username"),
        "duration_s": record.get("duration_s"),
        "ended_at_utc": record.get("ended_at_utc"),
        "rest_mode": record.get("rest_mode"),
        "recording_started": record.get("recording_started", True),
        "sleep_quality": record.get("sleep_quality"),
        "session_report": report,
    }


class ReportShareRegistry:
    """Hold the post-Session share state for one pod, in memory only.

    Keyed by ``Principal.subject`` -- the same immutable identity that
    ``record["identity_subject"]`` carries -- so the WebSocket can find the
    notice for a browser whose Session has already been cleared.

    Every method is total: bad input, an unknown subject or a disabled feature
    are all answered with a no-op rather than an exception.
    """

    def __init__(
        self,
        *,
        enabled: bool = False,
        clock: Callable[[], float] = time.monotonic,
        ttl_seconds: float = TICKET_TTL_SECONDS,
        max_image_bytes: int = MAX_IMAGE_BYTES,
    ) -> None:
        self.enabled = bool(enabled)
        self.max_image_bytes = int(max_image_bytes)
        self._clock = clock
        self._ttl = float(ttl_seconds)
        self._lock = threading.Lock()
        self._entries: dict[str, ShareEntry] = {}
        self._by_ticket: dict[str, str] = {}

    def reserve(self, subject: str | None) -> None:
        """Mark a Session as finalizing, before any of the slow work starts.

        ``_active_session`` is cleared on the first line of finalization but
        the ticket cannot exist until the database flush and the account
        upload are done.  Without this placeholder the tablet's WebSocket sees
        the ownership drop in that gap and closes 4403 on an empty registry,
        so the occupant loses the screen the ticket was meant to fill.
        """
        if not self.enabled or not subject:
            return
        with self._lock:
            self._purge_locked()
            self._forget_locked(subject)
            self._entries[subject] = ShareEntry(
                subject=subject,
                expires_at=self._clock() + PENDING_TIMEOUT_SECONDS,
            )

    def fulfil(self, record: Mapping[str, Any], *, access_token: str | None) -> None:
        """Attach the finished record and issue the ticket for its tablet.

        Called with the whole record so the composition root stays a single
        line.  A Session with no ZEEP token (a local fallback Login, or one
        restored after a restart) cannot be uploaded as that user, so it drops
        the reservation instead: the occupant still sees the summary, only the
        QR is absent.
        """
        if not self.enabled:
            return
        subject = str((record or {}).get("identity_subject") or "")
        if not subject:
            return
        report = _shareable_report(record)
        with self._lock:
            if subject not in self._entries:
                return
            if not access_token or report is None:
                self._forget_locked(subject)
                return
            ticket = secrets.token_urlsafe(32)
            self._entries[subject] = ShareEntry(
                subject=subject,
                expires_at=self._clock() + self._ttl,
                session_id=str(record.get("session_id") or "") or None,
                access_token=access_token,
                report=report,
                ticket=ticket,
                ready=True,
            )
            self._by_ticket[ticket] = subject

    def discard(self, subject: str | None) -> None:
        """Drop a reservation so a waiting WebSocket stops waiting at once."""
        if not subject:
            return
        with self._lock:
            self._forget_locked(subject)

    def share_for(self, subject: str | None) -> dict[str, Any] | None:
        """Return the ticket half a browser may see, or None."""
        notice = self.notice_for(subject)
        return None if notice is None else notice["report_share"]

    def notice_for(self, subject: str | None) -> dict[str, Any] | None:
        """Return the full end-of-Session notice, or None when not ready."""
        if not self.enabled or not subject:
            return None
        with self._lock:
            self._purge_locked()
            entry = self._entries.get(subject)
            return None if entry is None or not entry.ready else self._notice(entry)

    async def await_notice(
        self,
        subject: str | None,
        *,
        timeout: float = NOTICE_WAIT_SECONDS,
        poll: float = NOTICE_POLL_SECONDS,
    ) -> dict[str, Any] | None:
        """Wait, briefly and without blocking the loop, for a pending notice.

        Returns None immediately when this pod holds nothing for the subject,
        which keeps an ordinary un-owned socket closing as fast as it does
        today.
        """
        if not self.enabled or not subject:
            return None
        # Bounded against the real clock, not the injected one: this wait is
        # paced by ``asyncio.sleep`` and a test clock that never advances must
        # not be able to hold a tablet's socket open forever.
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            with self._lock:
                self._purge_locked()
                entry = self._entries.get(subject)
                if entry is None:
                    return None
                if entry.ready:
                    return self._notice(entry)
            if time.monotonic() >= deadline:
                return None
            await asyncio.sleep(poll)

    def claim(self, ticket: str | None) -> ShareEntry | None:
        """Authorize one upload attempt for a ticket, counting the attempt.

        The entry stays until :meth:`settle` so a single dropped connection
        does not cost the occupant their QR, but the attempt budget stops a
        leaked ticket from becoming an open upload endpoint.
        """
        if not self.enabled or not ticket:
            return None
        with self._lock:
            self._purge_locked()
            subject = self._by_ticket.get(ticket)
            entry = self._entries.get(subject) if subject else None
            if entry is None or entry.ticket != ticket:
                return None
            entry.attempts += 1
            if entry.attempts > MAX_ATTEMPTS:
                self._forget_locked(entry.subject)
                return None
            return entry

    def settle(self, ticket: str | None) -> None:
        """Drop a ticket once its upload has succeeded."""
        if not ticket:
            return
        with self._lock:
            subject = self._by_ticket.get(ticket)
            if subject:
                self._forget_locked(subject)

    def __len__(self) -> int:
        with self._lock:
            self._purge_locked()
            return len(self._entries)

    def _notice(self, entry: ShareEntry) -> dict[str, Any]:
        """Build the browser-facing notice.  The access token is not in it."""
        return {
            "session_id": entry.session_id,
            "report": dict(entry.report),
            "report_share": {
                "ticket": entry.ticket,
                "expires_in": max(0, int(entry.expires_at - self._clock())),
            },
        }

    def _forget_locked(self, subject: str) -> None:
        entry = self._entries.pop(subject, None)
        if entry is not None and entry.ticket:
            self._by_ticket.pop(entry.ticket, None)

    def _purge_locked(self) -> None:
        now = self._clock()
        for subject in [
            key for key, entry in self._entries.items() if entry.expires_at <= now
        ]:
            self._forget_locked(subject)


def decode_report_png(image_base64: str, *, max_bytes: int = MAX_IMAGE_BYTES) -> bytes:
    """Decode a canvas ``toDataURL`` payload, or say why it is refused.

    The account backend sniffs the real magic number rather than trusting a
    declared content type, so anything that is not a PNG is rejected here
    instead of spending an upload on it.
    """
    text = (image_base64 or "").strip()
    if text.startswith("data:"):
        text = text.partition(",")[2]
    if len(text) > (max_bytes // 3 + 1) * 4 + 1024:
        raise ValueError("report image is larger than the accepted size")
    try:
        png = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("report image is not valid base64") from exc
    if len(png) > max_bytes:
        raise ValueError("report image is larger than the accepted size")
    if not png.startswith(PNG_MAGIC):
        raise ValueError("report image is not a PNG")
    return png


def upload_report_png(
    png: bytes,
    *,
    access_token: str,
    zeep_request: Callable[..., dict[str, Any]],
) -> tuple[str, str]:
    """Upload one PNG as the occupant; return ``(signed_url, blob_name)``.

    ``data.url`` addresses a private container and cannot be opened, so the
    QR must carry ``data.signedUrl`` -- the time-limited read URL.
    """
    body = zeep_request(
        "POST",
        UPLOAD_PATH,
        files={"file": (UPLOAD_FILENAME, png, "image/png")},
        data={"prefix": UPLOAD_PREFIX},
        token=access_token,
        timeout=UPLOAD_TIMEOUT_SECONDS,
    )
    data = (body or {}).get("data") or {}
    signed_url = str(data.get("signedUrl") or "").strip()
    if not signed_url:
        raise ValueError("ZEEP upload returned no signed read URL")
    return signed_url, str(data.get("blobName") or "")


def qr_data_uri(url: str) -> str:
    """Encode a URL as an inline PNG QR code.

    Inline like the QR login image: nothing personal is written to ``static/``
    and there is no file left to clean up after the occupant leaves.
    """
    return segno.make(url, error="m").png_data_uri(scale=8, border=2)


def create_report_share_router(
    registry: ReportShareRegistry,
    *,
    zeep_request: Callable[..., dict[str, Any]],
    zeep_offline: type[BaseException],
    log_event: Callable[..., None],
) -> APIRouter:
    """One public route: exchange a ticket plus a PNG for a QR code.

    Public on purpose.  The occupant's cookie is already gone by the time the
    tablet calls this, so the single-use ticket -- which only the pod issued
    and only that tablet was handed -- is the credential.
    """
    router = APIRouter()

    @router.post("/api/session/report-share")
    def session_report_share(cmd: ReportShareCommand) -> dict[str, Any]:
        if not registry.enabled:
            raise HTTPException(404, "การแชร์ผลการนอนถูกปิดอยู่")
        entry = registry.claim(cmd.ticket)
        if entry is None:
            raise HTTPException(
                404,
                {
                    "code": "share_ticket_expired",
                    "message": "หมดเวลาสร้าง QR ของผลการนอนนี้แล้ว",
                },
            )
        try:
            png = decode_report_png(
                cmd.image_base64, max_bytes=registry.max_image_bytes
            )
        except ValueError as exc:
            log_event(
                "report_share",
                "image_rejected",
                session_id=entry.session_id,
                error=str(exc),
            )
            return {"ok": False, "reason": "invalid_image"}
        try:
            signed_url, blob_name = upload_report_png(
                png,
                access_token=entry.access_token or "",
                zeep_request=zeep_request,
            )
        except (zeep_offline, HTTPException, ValueError) as exc:
            # Never a 500: the night is already saved and the screen has a
            # fallback for a missing QR.  There is no retry queue on purpose --
            # a link that arrives after the occupant has left is worthless.
            log_event(
                "report_share",
                "upload_failed",
                session_id=entry.session_id,
                error=str(getattr(exc, "detail", exc)),
            )
            return {"ok": False, "reason": "upload_failed"}
        registry.settle(cmd.ticket)
        # blobName only: signedUrl embeds a SAS signature, and the token must
        # not reach an event.  The blob name is what a later deletion request
        # would need.
        log_event(
            "report_share",
            "uploaded",
            session_id=entry.session_id,
            blob_name=blob_name,
        )
        return {
            "ok": True,
            "qr_data_url": qr_data_uri(signed_url),
            "expires_in_minutes": SIGNED_URL_TTL_MINUTES,
        }

    return router
