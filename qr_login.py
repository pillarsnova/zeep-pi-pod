"""Pi-side registry for the ZEEP QR login handshake.

The pod tablet is a browser on the Pi's offline Wi-Fi hotspot, so it cannot
reach the ZEEP API itself and the Pi has to proxy the handshake.  That leaves
the Pi as the only holder of ``pollSecret``, which the ZEEP contract keeps out
of the QR image and off access logs: the browser only ever learns ``loginId``.
Anyone who photographs the QR therefore still cannot poll for the tokens.

``QrLoginRegistry`` itself touches no network, disk or request state, so the
expiry and secret-handling rules stay testable without starting a pod; the
router below is the thin transport layer over it.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from fastapi import APIRouter, HTTPException, Response

from api_models import QrLoginPollCommand
from zeep_pod.identity.zeep_account import identity_from_auth_data

# ZEEP issues a 180 s QR plus a further 60 s window to collect tokens after the
# phone approves.  The Pi keeps the secret for both windows so a poll that
# races the QR expiry still reaches ZEEP and learns the real verdict instead of
# being answered "expired" locally.
DEFAULT_TTL_SECONDS = 180.0
APPROVAL_GRACE_SECONDS = 60.0


@dataclass(frozen=True)
class QrTicket:
    """One in-flight QR login.  ``poll_secret`` never leaves the Pi."""

    login_id: str
    poll_secret: str
    expires_at: float


class QrLoginRegistry:
    """Hold ``pollSecret`` for in-flight QR logins, keyed by the public id."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        grace_seconds: float = APPROVAL_GRACE_SECONDS,
    ) -> None:
        self._clock = clock
        self._grace = grace_seconds
        self._lock = threading.Lock()
        self._tickets: Dict[str, QrTicket] = {}

    def remember(
        self, login_id: str, poll_secret: str, expires_in: Optional[float] = None
    ) -> QrTicket:
        """Store a freshly issued ticket and return it."""
        if not login_id or not poll_secret:
            raise ValueError("QR login needs both loginId and pollSecret")
        try:
            ttl = float(expires_in)
        except (TypeError, ValueError):
            ttl = DEFAULT_TTL_SECONDS
        if ttl <= 0:
            ttl = DEFAULT_TTL_SECONDS
        ticket = QrTicket(login_id, poll_secret, self._clock() + ttl + self._grace)
        with self._lock:
            self._prune_locked()
            self._tickets[login_id] = ticket
        return ticket

    def secret_for(self, login_id: str) -> Optional[str]:
        """Return the stored secret, or ``None`` when this pod holds no ticket.

        ``None`` covers both a loginId this pod never issued and one whose
        window has closed; the caller answers the browser "expired" either way
        rather than forwarding a guessed id to ZEEP.
        """
        if not login_id:
            return None
        with self._lock:
            self._prune_locked()
            ticket = self._tickets.get(login_id)
        return ticket.poll_secret if ticket is not None else None

    def forget(self, login_id: str) -> None:
        """Drop a ticket once ZEEP has reached a terminal state for it."""
        with self._lock:
            self._tickets.pop(login_id, None)

    def __len__(self) -> int:
        with self._lock:
            self._prune_locked()
            return len(self._tickets)

    def _prune_locked(self) -> None:
        now = self._clock()
        expired = [key for key, ticket in self._tickets.items() if ticket.expires_at <= now]
        for key in expired:
            del self._tickets[key]


def create_qr_login_router(
    registry: QrLoginRegistry,
    *,
    zeep_request: Callable[..., Dict[str, Any]],
    zeep_offline: type[BaseException],
    complete_login: Callable[..., Dict[str, Any]],
    pod_occupied: Callable[[], bool],
    log_event: Callable[..., None],
) -> APIRouter:
    """QR login routes: the Pi runs the ZEEP handshake on the tablet's behalf.

    Both routes are public, exactly like password login — the QR itself is the
    only thing the browser proves, and ``pollSecret`` never leaves this process.
    """
    router = APIRouter()
    occupied_error = {"code": "pod_already_occupied", "message": "ตู้นี้กำลังมีผู้ใช้งาน"}

    @router.post("/api/auth/qr/session")
    def auth_qr_session():
        """Start a QR login and return only the half a browser may see.

        ZEEP rate-limits session creation per source IP and every tablet here
        shares one egress IP, so refuse before spending a QR that nobody could
        complete anyway.
        """
        if pod_occupied():
            raise HTTPException(409, occupied_error)
        try:
            data = zeep_request("POST", "/v1/auth/qr/session").get("data") or {}
        except zeep_offline as exc:
            log_event("auth", "zeep_offline", stage="qr_session", error=str(exc))
            raise HTTPException(503, {
                "code": "offline",
                "message": "ต่อ ZEEP API ไม่ได้ — เข้าสู่ระบบด้วย QR ไม่ได้ในตอนนี้",
            }) from exc

        login_id = str(data.get("loginId") or "").strip()
        qr_code = str(data.get("qrCode") or "").strip()
        poll_secret = str(data.get("pollSecret") or "")
        if not login_id or not qr_code or not poll_secret:
            raise HTTPException(502, "ZEEP API ตอบข้อมูล QR ไม่ครบ")

        registry.remember(login_id, poll_secret, data.get("expiresIn"))
        # loginId is the public half and already rides inside the QR image; the
        # secret must never appear in an event, so log only the id.
        log_event("auth", "qr_session_created", login_id=login_id)
        return {
            "login_id": login_id,
            "qr_code": qr_code,
            "expires_at": data.get("expiresAt"),
            "expires_in": data.get("expiresIn"),
        }

    @router.post("/api/auth/qr/poll")
    def auth_qr_poll(cmd: QrLoginPollCommand, response: Response):
        """Forward one poll to ZEEP, adding the pollSecret this pod held back.

        ZEEP releases the tokens exactly once and answers every later poll with
        "expired", so an approved poll has to finish the pod login inside this
        same request — there is no second chance to read them.
        """
        login_id = (cmd.login_id or "").strip()
        poll_secret = registry.secret_for(login_id)
        if poll_secret is None:
            # Either this pod never issued the id or its window has closed;
            # answer "expired" instead of forwarding a guessed id to ZEEP.
            return {"state": "expired"}
        if pod_occupied():
            registry.forget(login_id)
            raise HTTPException(409, occupied_error)

        try:
            data = zeep_request(
                "POST", "/v1/auth/qr/poll",
                json_body={"loginId": login_id, "pollSecret": poll_secret},
            ).get("data") or {}
        except zeep_offline as exc:
            log_event("auth", "zeep_offline", stage="qr_poll", error=str(exc))
            raise HTTPException(503, {
                "code": "offline", "message": "ต่อ ZEEP API ไม่ได้ — กำลังลองใหม่",
            }) from exc

        state = str(data.get("state") or "").strip() or "expired"
        if state != "approved":
            # ZEEP reports an unknown or timed-out loginId as state="expired"
            # with HTTP 200, so terminal states arrive here, not as an error.
            if state in ("expired", "rejected"):
                registry.forget(login_id)
            scanned = data.get("scannedBy") or {}
            return {
                "state": state,
                "scanned_by": ({"display_name": scanned.get("displayName")} if scanned else None),
                "expires_at": data.get("expiresAt"),
            }

        # ZEEP consumed the ticket to release these tokens, so drop it here too
        # rather than leave a ticket that can only ever answer "expired".
        registry.forget(login_id)
        auth, me = identity_from_auth_data(
            data, zeep_request=zeep_request, log_event=log_event,
            offline_error=zeep_offline,
        )
        log_event("auth", "qr_login", user=auth["username"], login_id=login_id)
        result = complete_login(
            auth, me, age_group_choice=cmd.age_group, rest_mode=cmd.rest_mode,
            target_duration_minutes=cmd.target_duration_minutes,
            response=response,
        )
        result["state"] = "approved"
        return result

    return router
