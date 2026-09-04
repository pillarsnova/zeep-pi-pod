"""Normalize ZEEP profile fields without inventing health information."""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import date
from typing import Any

from fastapi import HTTPException

SUPPORTED_GENDERS = ("male", "female", "other", "unspecified")


def zeep_gender(raw: Any) -> str:
    """Normalize the account API gender field."""
    gender = str(raw or "").strip().lower()
    if gender in SUPPORTED_GENDERS:
        return gender
    return "unspecified"


def age_from_dob(raw: Any, *, today: date | None = None) -> int | None:
    """Calculate completed years from an ISO date of birth."""
    try:
        dob = date.fromisoformat(str(raw or "").strip()[:10])
    except ValueError:
        return None
    reference_day = today or date.today()
    age = reference_day.year - dob.year
    if (reference_day.month, reference_day.day) < (dob.month, dob.day):
        age -= 1
    if 0 < age <= 120:
        return age
    return None


def profile_value(profile: dict[str, Any], *keys: str) -> Any:
    """Read one field across supported account-profile envelopes."""
    scopes = [profile]
    for container in (
        "profile",
        "healthProfile",
        "health_profile",
        "health",
    ):
        nested = profile.get(container)
        if isinstance(nested, dict):
            scopes.append(nested)
    for scope in scopes:
        for key in keys:
            if key in scope and scope[key] not in (None, ""):
                return scope[key]
    return None


def normalise_date_of_birth(raw: Any) -> str | None:
    """Return an ISO date only for a valid calendar date."""
    try:
        return date.fromisoformat(str(raw or "").strip()[:10]).isoformat()
    except ValueError:
        return None


def normalise_body_measurement(
    raw: Any,
    *,
    measurement: str,
) -> float | None:
    """Normalize optional body measurements within plausible bounds."""
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    if measurement == "height_cm":
        if 0.8 <= value <= 2.5:
            value *= 100.0
        return round(value, 1) if 80.0 <= value <= 250.0 else None
    if measurement == "weight_kg":
        return round(value, 1) if 20.0 <= value <= 400.0 else None
    return None


def normalise_blood_group(raw: Any) -> str | None:
    """Normalize supported ABO/Rh notation."""
    value = str(raw or "").strip().upper().replace(" ", "_").replace("-", "_")
    aliases = {
        "A+": "A+",
        "A_POSITIVE": "A+",
        "APOSITIVE": "A+",
        "A_": "A-",
        "A_NEGATIVE": "A-",
        "ANEGATIVE": "A-",
        "B+": "B+",
        "B_POSITIVE": "B+",
        "BPOSITIVE": "B+",
        "B_": "B-",
        "B_NEGATIVE": "B-",
        "BNEGATIVE": "B-",
        "AB+": "AB+",
        "AB_POSITIVE": "AB+",
        "ABPOSITIVE": "AB+",
        "AB_": "AB-",
        "AB_NEGATIVE": "AB-",
        "ABNEGATIVE": "AB-",
        "O+": "O+",
        "O_POSITIVE": "O+",
        "OPOSITIVE": "O+",
        "O_": "O-",
        "O_NEGATIVE": "O-",
        "ONEGATIVE": "O-",
    }
    return aliases.get(value)


def health_reference_from_profile(
    profile: dict[str, Any],
    *,
    age_group_for: Callable[[Any], str],
) -> dict[str, Any]:
    """Build display-safe wellness context from a stored Pod profile."""
    age = profile.get("age")
    dob = normalise_date_of_birth(profile.get("date_of_birth"))
    exact_age_known = bool(dob) or profile.get("age_is_estimated") is False
    valid_age = isinstance(age, int) and 0 < age <= 120 and exact_age_known
    return {
        "schema_version": 1,
        "gender": profile.get("gender") or "unspecified",
        "date_of_birth": dob,
        "age_years": int(age) if valid_age else None,
        "age_group": profile.get("age_group")
        or (age_group_for(age) if age is not None else None),
        "height_cm": normalise_body_measurement(
            profile.get("height_cm"),
            measurement="height_cm",
        ),
        "weight_kg": normalise_body_measurement(
            profile.get("weight_kg"),
            measurement="weight_kg",
        ),
        "blood_group": normalise_blood_group(profile.get("blood_group")),
        "source": profile.get("health_reference_source")
        or (
            "zeep_profile"
            if profile.get("zeep_public_id") or profile.get("zeep_email")
            else "local_profile"
        ),
        "refresh_status": profile.get("health_reference_refresh_status"),
        "updated_at_utc": profile.get("health_reference_updated_at_utc"),
        "intended_use": "health_reference_only",
    }


def zeep_health_reference(me: dict[str, Any]) -> dict[str, Any]:
    """Extract health-reference fields actually present in the account API."""
    dob = normalise_date_of_birth(
        profile_value(
            me,
            "dateOfBirth",
            "date_of_birth",
            "birthDate",
            "birth_date",
        )
    )
    return {
        "schema_version": 1,
        "gender": zeep_gender(profile_value(me, "gender", "sex")),
        "date_of_birth": dob,
        "age_years": age_from_dob(dob),
        "height_cm": normalise_body_measurement(
            profile_value(me, "heightCm", "height_cm", "height"),
            measurement="height_cm",
        ),
        "weight_kg": normalise_body_measurement(
            profile_value(me, "weightKg", "weight_kg", "weight"),
            measurement="weight_kg",
        ),
        "blood_group": normalise_blood_group(
            profile_value(
                me,
                "bloodGroup",
                "blood_group",
                "bloodType",
                "blood_type",
            )
        ),
        "source": "zeep_profile",
    }


def normalize_username(raw: str) -> str:
    """Return a compact display identifier or reject unusable input."""
    name = " ".join((raw or "").split())[:40]
    if len(name) < 2:
        raise HTTPException(422, "username ต้องยาวอย่างน้อย 2 ตัวอักษร")
    return name


def normalize_email(raw: str) -> str:
    """Return the canonical, case-insensitive ZEEP account email."""
    email = (raw or "").strip().casefold()
    local, separator, domain = email.partition("@")
    valid = (
        separator
        and local
        and domain
        and "." in domain
        and not any(char.isspace() for char in email)
        and len(email) <= 254
    )
    if not valid:
        raise HTTPException(
            422,
            "บัญชี ZEEP ต้องมี Email ที่ถูกต้องสำหรับผูกประวัติ",
        )
    return email


def normalize_account_key(raw: str) -> str:
    """Normalize email-backed and legacy local account keys."""
    value = (raw or "").strip()
    if "@" in value:
        return normalize_email(value)
    return normalize_username(value).casefold()
