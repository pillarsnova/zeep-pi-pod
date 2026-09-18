"""Login Profile preparation; persistence and locking belong to SessionStarter."""

from __future__ import annotations

from typing import Any

from sessions.start_contracts import (
    SessionStartRejected,
    StartPorts,
    StartRequest,
    ValidatedStart,
)


def prepare_start_profile(
    profile: dict[str, Any] | None,
    start: ValidatedStart,
    request: StartRequest,
    ports: StartPorts,
    *,
    refreshed_at: str,
) -> dict[str, Any]:
    """Preserve authoritative refresh versus cached/local profile semantics."""
    refreshed = bool(request.auth and request.auth.get("profile_refreshed", True))
    if profile is None:
        profile = _new_profile(start, ports)
    else:
        _refresh_profile(profile, start, request, ports, refreshed=refreshed)
    _set_health_provenance(
        profile, start, request, refreshed=refreshed, refreshed_at=refreshed_at
    )
    if request.auth:
        # Email owns data identity; publicId owns authorization. Presentation
        # fields may change without creating another user's history.
        profile["zeep_public_id"] = request.auth.get("public_id")
        profile["zeep_email"] = start.email
        profile["email"] = start.email
        profile["display_name"] = request.auth.get("display_name")
    return profile


def _optional_health(start: ValidatedStart, ports: StartPorts) -> dict[str, Any]:
    health = start.incoming_health
    return {
        "date_of_birth": ports.date_of_birth(health.get("date_of_birth")),
        "height_cm": ports.body_measurement(
            health.get("height_cm"), measurement="height_cm"
        ),
        "weight_kg": ports.body_measurement(
            health.get("weight_kg"), measurement="weight_kg"
        ),
        "blood_group": ports.blood_group(health.get("blood_group")),
    }


def _new_profile(start: ValidatedStart, ports: StartPorts) -> dict[str, Any]:
    if start.gender is None:
        raise SessionStartRejected(422, "ผู้ใช้ใหม่ต้องเลือกเพศ (ชาย/หญิง/อื่น ๆ/ไม่ระบุ)")
    if start.age_group is None:
        raise SessionStartRejected(422, "ผู้ใช้ใหม่ต้องเลือกช่วงอายุสำหรับ Baseline")
    return {
        "username": start.username,
        "account_key": start.key,
        "email": start.email,
        "gender": start.gender,
        "age": start.age,
        "age_is_estimated": start.incoming_health.get("age_years") is None,
        "age_group": start.age_group,
        **_optional_health(start, ports),
        "created_at_utc": ports.utc_now().isoformat(),
        "sessions": 0,
        "last_session_utc": None,
    }


def _refresh_profile(
    profile: dict[str, Any],
    start: ValidatedStart,
    request: StartRequest,
    ports: StartPorts,
    *,
    refreshed: bool,
) -> None:
    profile["username"] = start.username
    profile["account_key"] = start.key
    if start.email:
        profile["email"] = start.email
    age = start.age if start.age is not None else profile.get("age")
    group = start.age_group
    if group is None:
        group = profile.get("age_group") or ports.age_group(age)
    if start.gender and (not request.auth or refreshed):
        profile["gender"] = start.gender
    if age is not None and (not request.auth or refreshed):
        profile["age"] = age
        if start.incoming_health.get("age_years") is not None:
            profile["age_is_estimated"] = False
    profile["age_group"] = group
    optional = _optional_health(start, ports)
    if refreshed:
        # A complete verified snapshot clears optional facts removed in the app.
        profile.update(optional)
        profile["age_is_estimated"] = start.incoming_health.get("age_years") is None
    else:
        # An unavailable profile refresh must not erase verified health facts.
        for field, value in optional.items():
            if value is not None:
                profile[field] = value


def _set_health_provenance(
    profile: dict[str, Any],
    start: ValidatedStart,
    request: StartRequest,
    *,
    refreshed: bool,
    refreshed_at: str,
) -> None:
    if request.auth and refreshed:
        profile["health_reference_source"] = (
            start.incoming_health.get("source") or "zeep_profile"
        )
        profile["health_reference_refresh_status"] = "live_login"
        profile["health_reference_updated_at_utc"] = refreshed_at
    elif request.auth:
        profile.setdefault("health_reference_source", "zeep_login_identity")
        profile["health_reference_refresh_status"] = "cached"
        profile.setdefault("health_reference_updated_at_utc", None)
    else:
        profile["health_reference_source"] = (
            start.incoming_health.get("source") or "local_profile"
        )
        profile["health_reference_refresh_status"] = "local_login"
        profile["health_reference_updated_at_utc"] = refreshed_at
