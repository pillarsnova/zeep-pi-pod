"""Typed request contracts shared by ZEEP FastAPI routes.

Keeping transport schemas outside ``app.py`` makes API changes reviewable and
prevents device/session orchestration code from becoming the schema registry.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

PublicRestMode = Literal["sleep", "nap_recovery"]

__all__ = (
    "ActiveSessionProfileCommand",
    "AdminLoginCommand",
    "AirconCommand",
    "AirconFanLevelReferenceCommand",
    "AuthLoginCommand",
    "BedControlCommand",
    "BrainwavePreviewCommand",
    "ForceLogoutCommand",
    "LabelCommand",
    "LoginCommand",
    "ProfileCompletionCommand",
    "ProgressiveProfileAnswerCommand",
    "ProgressiveProfileConsentCommand",
    "ProgressiveProfileDeferCommand",
    "PublicRestMode",
    "QrLoginPollCommand",
    "SensorBiasCommand",
    "SwitchCommand",
    "TrackCommand",
    "VolumeCommand",
)


class SensorBiasCommand(BaseModel):
    metric: str
    bias: float
    reference_value: float | None = None


class SwitchCommand(BaseModel):
    on: bool


class VolumeCommand(BaseModel):
    volume: int


class TrackCommand(BaseModel):
    track: str
    loop: bool = True
    queue: bool = False
    user_initiated: bool = False

    @property
    def resolved_loop(self) -> bool:
        """Queue wins if a legacy caller sends both mode flags."""
        return bool(self.loop) and not bool(self.queue)


class BrainwavePreviewCommand(BaseModel):
    preset_id: str
    duration_seconds: int = 30
    volume: int = 35
    confirm_occupied: bool = False


class LoginCommand(BaseModel):
    username: str
    gender: str | None = None
    age: int | None = None
    age_group: str | None = None
    # Reserved for Local fallback/future Profile editing. Missing means unknown.
    height_cm: float | None = None
    weight_kg: float | None = None
    blood_group: str | None = None
    rest_mode: PublicRestMode = "nap_recovery"
    target_duration_minutes: Literal[30, 90] | None = None
    # One-time proof returned only after this Pi failed to reach ZEEP.
    offline_ticket: str
    offline_identifier: str


class AuthLoginCommand(BaseModel):
    identifier: str
    password: str
    age_group: str | None = None
    rest_mode: PublicRestMode = "nap_recovery"
    target_duration_minutes: Literal[30, 90] | None = None


class QrLoginPollCommand(BaseModel):
    """Poll a QR login.  ``pollSecret`` stays on the Pi and is never accepted
    from the browser, so a photographed QR cannot be polled for tokens."""

    login_id: str
    age_group: str | None = None
    rest_mode: PublicRestMode = "nap_recovery"
    target_duration_minutes: Literal[30, 90] | None = None


class ProfileCompletionCommand(BaseModel):
    """Answer the profile form a ZEEP account was gated on.

    ``profile_ticket`` stands in for the credentials: the pod already verified
    them, and a QR login cannot present its own a second time.
    """

    profile_ticket: str
    gender: str
    date_of_birth: str
    height_cm: float
    weight_kg: float
    blood_group: str | None = None
    rest_mode: PublicRestMode = "nap_recovery"
    target_duration_minutes: Literal[30, 90] | None = None


class AdminLoginCommand(BaseModel):
    identifier: str
    password: str


class ForceLogoutCommand(BaseModel):
    reason: str = "admin_force_logout"


class ActiveSessionProfileCommand(BaseModel):
    session_id: str
    display_name: str
    gender: str
    reason: str = "admin_profile_correction"


class ProgressiveProfileConsentCommand(BaseModel):
    granted: bool


class ProgressiveProfileAnswerCommand(BaseModel):
    question_id: str
    value: Any


class ProgressiveProfileDeferCommand(BaseModel):
    question_id: str | None = None


class LabelCommand(BaseModel):
    label: str


class AirconCommand(BaseModel):
    command: str
    # Admin Debug is separately authorized but uses the same 15-28 °C mapping.
    direct: bool = False


class AirconFanLevelReferenceCommand(BaseModel):
    # Administrative correction only; no IR frame is transmitted.
    level: int
    note: str | None = None


class BedControlCommand(BaseModel):
    command: str
