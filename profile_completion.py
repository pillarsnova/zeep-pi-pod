"""Collect the health facts a Session needs before this pod claims an occupant.

An account created in the phone app may still carry no gender, date of birth,
height or weight.  Those four decide which baseline a Session is scored
against, so the pod asks for them once, writes them back to the ZEEP account —
still the only source of truth — and only then starts the Session.  Blood
group rides along when the user knows it and never blocks anyone.

The verified ZEEP tokens are parked in ``PendingProfileRegistry`` between the
two requests: a QR poll releases its tokens exactly once, so an approved login
cannot simply be replayed after the form is filled in.
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, Dict, Optional, Tuple

from fastapi import APIRouter, HTTPException, Response

from api_models import ProfileCompletionCommand
from zeep_pod.identity.profile_fields import (
    age_from_dob,
    normalise_body_measurement,
    normalise_date_of_birth,
    profile_value,
)

# One form, filled at the tablet while the user waits.  Long enough to type
# four fields, short enough that an abandoned form does not keep a live access
# token in memory.
TICKET_TTL_SECONDS = 600.0

# The phone app offers exactly these three (the third is labelled "ไม่ระบุ" but
# stores ``other``), so the pod must not invent a fourth value the account API
# would reject.
SUPPORTED_GENDERS = ("male", "female", "other")

# ABO without Rh, matching the phone app's five buttons where "ไม่ทราบ" simply
# sends nothing.
SUPPORTED_BLOOD_GROUPS = ("A", "B", "AB", "O")

# Blood group is deliberately absent: it explains nothing about rest and must
# never stand between an occupant and a Session.
REQUIRED_FIELDS = ("gender", "date_of_birth", "height_cm", "weight_kg")

_FIELD_SOURCE_KEYS: Dict[str, Tuple[str, ...]] = {
    "gender": ("gender", "sex"),
    "date_of_birth": ("dateOfBirth", "date_of_birth", "birthDate", "birth_date"),
    "height_cm": ("heightCm", "height_cm", "height"),
    "weight_kg": ("weightKg", "weight_kg", "weight"),
}

# Kept in step with the Session guards in ``_start_pod_session``: a value that
# passes here but fails there would be written to the ZEEP account and still
# leave the user unable to start a Session.
MIN_AGE_YEARS = 18
MAX_AGE_YEARS = 100


def missing_required_fields(me: dict[str, Any]) -> tuple[str, ...]:
    """Name the required health facts this ZEEP account has not filled in yet.

    Read the ``/users/me`` payload directly rather than a normalised health
    reference: normalisation answers "unspecified" for a missing gender and
    cannot be told apart from an account that really chose not to say.
    """
    missing: list[str] = []
    for field in REQUIRED_FIELDS:
        raw = profile_value(me, *_FIELD_SOURCE_KEYS[field])
        if raw is None:
            missing.append(field)
            continue
        if field == "date_of_birth" and age_from_dob(raw) is None:
            missing.append(field)
        elif field in ("height_cm", "weight_kg") and (
            normalise_body_measurement(raw, measurement=field) is None
        ):
            missing.append(field)
    return tuple(missing)


def _reject(message: str) -> HTTPException:
    return HTTPException(422, {"code": "profile_invalid", "message": message})


def build_zeep_patch(
    *,
    gender: Any,
    date_of_birth: Any,
    height_cm: Any,
    weight_kg: Any,
    blood_group: Any = None,
    today: date | None = None,
) -> dict[str, Any]:
    """Validate one submitted form and shape it for ``PATCH /v1/users/me``.

    Bounds match what a Session will accept, so a form that passes here cannot
    update the account and then be refused at the Session gate.
    """
    clean_gender = str(gender or "").strip().lower()
    if clean_gender not in SUPPORTED_GENDERS:
        raise _reject("เลือกเพศก่อนเริ่มการพัก")

    dob = normalise_date_of_birth(date_of_birth)
    age = age_from_dob(dob, today=today) if dob else None
    if dob is None or age is None:
        raise _reject("กรอกวันเกิดให้ถูกต้อง")
    if not MIN_AGE_YEARS <= age <= MAX_AGE_YEARS:
        raise _reject(f"ZEEP รองรับผู้ใช้อายุ {MIN_AGE_YEARS}–{MAX_AGE_YEARS} ปี")

    height = normalise_body_measurement(height_cm, measurement="height_cm")
    if height is None:
        raise _reject("กรอกส่วนสูงระหว่าง 80–250 ซม.")
    weight = normalise_body_measurement(weight_kg, measurement="weight_kg")
    if weight is None:
        raise _reject("กรอกน้ำหนักระหว่าง 20–400 กก.")

    blood = str(blood_group or "").strip().upper()
    if blood and blood not in SUPPORTED_BLOOD_GROUPS:
        raise _reject("กรุ๊ปเลือดต้องเป็น A, B, AB หรือ O")

    # ``bloodGroup`` is always sent: the account API updates only the keys it
    # receives, so omitting it would make "ไม่ทราบ" unable to clear a value.
    return {
        "gender": clean_gender,
        "dateOfBirth": dob,
        "heightCm": height,
        "weightKg": weight,
        "bloodGroup": blood or None,
    }


@dataclass(frozen=True)
class PendingProfile:
    """One verified ZEEP login waiting for its profile form."""

    auth: dict[str, Any]
    me: dict[str, Any]
    missing: tuple[str, ...]
    expires_at: float


class PendingProfileRegistry:
    """Hold verified ZEEP tokens between the profile prompt and its answer."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        ttl_seconds: float = TICKET_TTL_SECONDS,
    ) -> None:
        self._clock = clock
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._pending: Dict[str, PendingProfile] = {}

    def remember(
        self,
        auth: dict[str, Any],
        me: dict[str, Any],
        missing: tuple[str, ...],
    ) -> str:
        """Park one verified login and return the ticket that reclaims it."""
        ticket = secrets.token_urlsafe(24)
        with self._lock:
            self._prune_locked()
            self._pending[ticket] = PendingProfile(
                auth=auth,
                me=me,
                missing=missing,
                expires_at=self._clock() + self._ttl,
            )
        return ticket

    def consume(self, ticket: str) -> Optional[PendingProfile]:
        """Return the parked login once; ``None`` once used, unknown or stale."""
        with self._lock:
            self._prune_locked()
            item = self._pending.pop(str(ticket or ""), None)
        if item is None or item.expires_at <= self._clock():
            return None
        return item

    def forget(self, ticket: str) -> None:
        with self._lock:
            self._pending.pop(str(ticket or ""), None)

    def _prune_locked(self) -> None:
        now = self._clock()
        for key in [k for k, v in self._pending.items() if v.expires_at <= now]:
            del self._pending[key]


def require_complete_profile(
    auth: dict[str, Any],
    me: dict[str, Any],
    *,
    registry: "PendingProfileRegistry",
    log_event: Callable[..., None],
) -> None:
    """Stop a login whose ZEEP account still lacks the facts a Session needs.

    Raises before the cookie and the occupancy lease exist: an occupant who
    walks away from the form must leave the pod free for the next person, and
    the Session snapshot must never freeze health facts we are about to ask
    for.  The ticket carries the tokens because an approved QR poll hands them
    over exactly once.

    Only a profile this login actually fetched can be called incomplete.  When
    ``/users/me`` was unreachable the pod knows nothing new about the account
    and keeps falling back to the last verified snapshot, exactly as before.
    """
    if not auth.get("profile_refreshed", True):
        return
    missing = missing_required_fields(me)
    if not missing:
        return
    ticket = registry.remember(auth, me, missing)
    log_event("auth", "profile_incomplete", user=auth["username"], missing=list(missing))
    raise HTTPException(
        422,
        {
            "code": "profile_incomplete",
            "message": "บัญชี ZEEP ยังไม่มีข้อมูลสุขภาพพื้นฐาน — กรอกก่อนเริ่มการพัก",
            "missing": list(missing),
            "profile_ticket": ticket,
        },
    )


def create_profile_completion_router(
    registry: PendingProfileRegistry,
    *,
    zeep_request: Callable[..., Dict[str, Any]],
    zeep_offline: type[BaseException],
    complete_login: Callable[..., Dict[str, Any]],
    pod_occupied: Callable[[], bool],
    log_event: Callable[..., None],
) -> APIRouter:
    """The one route that answers the profile gate.

    Public like login itself: the ticket is the proof, and it stands for
    credentials the pod has already verified.
    """
    router = APIRouter()

    def retry(pending: PendingProfile, error: HTTPException) -> HTTPException:
        """Re-park a pending login so a retryable failure costs no re-auth.

        A QR login cannot be replayed — its tokens are released once — so the
        browser gets a fresh ticket for the same parked login instead of being
        sent back to the QR screen.
        """
        detail = dict(error.detail) if isinstance(error.detail, dict) else {"message": error.detail}
        detail["profile_ticket"] = registry.remember(pending.auth, pending.me, pending.missing)
        return HTTPException(error.status_code, detail)

    @router.post("/api/auth/profile/complete")
    def auth_profile_complete(cmd: ProfileCompletionCommand, response: Response):
        """Update the ZEEP account with the form, then finish the login.

        The account stays the source of truth: the pod writes the answers back,
        reads ``/users/me`` again and binds the Session to what ZEEP confirmed,
        never to what was typed at the tablet.
        """
        pending = registry.consume(cmd.profile_ticket)
        if pending is None:
            raise HTTPException(422, {
                "code": "profile_ticket_invalid",
                "message": "แบบฟอร์มหมดอายุแล้ว — เข้าสู่ระบบอีกครั้ง",
            })
        if pod_occupied():
            raise HTTPException(409, {
                "code": "pod_already_occupied", "message": "ตู้นี้กำลังมีผู้ใช้งาน",
            })

        # Validate before spending the ticket's tokens: a rejected form leaves
        # the pending login re-parked so only the bad field is retyped.
        try:
            patch = build_zeep_patch(
                gender=cmd.gender,
                date_of_birth=cmd.date_of_birth,
                height_cm=cmd.height_cm,
                weight_kg=cmd.weight_kg,
                blood_group=cmd.blood_group,
            )
        except HTTPException as exc:
            raise retry(pending, exc) from exc

        token = pending.auth.get("access_token")
        try:
            zeep_request("PATCH", "/v1/users/me", json_body=patch, token=token)
            me = zeep_request("GET", "/v1/users/me", token=token).get("data") or {}
        except zeep_offline as exc:
            # These facts live in the account; with ZEEP unreachable there is
            # nothing to fall back to, so block rather than start a Session on
            # values this pod alone believes.
            log_event("auth", "zeep_offline", stage="profile_complete", error=str(exc))
            raise retry(pending, HTTPException(503, {
                "code": "profile_update_offline",
                "message": "ต่อ ZEEP API ไม่ได้ — ยังบันทึกข้อมูลไม่สำเร็จ กรุณาลองอีกครั้ง",
            })) from exc
        if not isinstance(me, dict):
            me = {}

        still_missing = missing_required_fields(me)
        if still_missing:
            # The write was accepted but the account still reads incomplete;
            # prompting again would loop, so say so instead.
            log_event(
                "auth", "profile_update_ineffective",
                user=pending.auth["username"], missing=list(still_missing),
            )
            raise HTTPException(502, {
                "code": "profile_update_failed",
                "message": "ZEEP API ยังไม่บันทึกข้อมูลที่กรอก กรุณาลองใหม่อีกครั้ง",
            })

        log_event(
            "auth", "profile_completed",
            user=pending.auth["username"], fields=list(pending.missing),
        )
        return complete_login(
            pending.auth, me, age_group_choice=None, rest_mode=cmd.rest_mode,
            target_duration_minutes=cmd.target_duration_minutes, response=response,
        )

    return router
