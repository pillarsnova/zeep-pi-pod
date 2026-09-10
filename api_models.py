"""Typed request contracts shared by ZEEP FastAPI routes.

Keeping transport schemas outside ``app.py`` makes API changes reviewable and
prevents device/session orchestration code from becoming the schema registry.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel


PublicRestMode = Literal["sleep", "nap_recovery"]


class SensorBiasCommand(BaseModel):
    metric: str
    bias: float
    reference_value: Optional[float] = None


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
    gender: Optional[str] = None
    age: Optional[int] = None
    age_group: Optional[str] = None
    # Reserved for Local fallback/future Profile editing. Missing means unknown.
    height_cm: Optional[float] = None
    weight_kg: Optional[float] = None
    blood_group: Optional[str] = None
    rest_mode: PublicRestMode = "nap_recovery"
    target_duration_minutes: Optional[Literal[30, 90]] = None
    # One-time proof returned only after this Pi failed to reach ZEEP.
    offline_ticket: str
    offline_identifier: str


class AuthLoginCommand(BaseModel):
    identifier: str
    password: str
    age_group: Optional[str] = None
    rest_mode: PublicRestMode = "nap_recovery"
    target_duration_minutes: Optional[Literal[30, 90]] = None


class QrLoginPollCommand(BaseModel):
    """Poll a QR login.  ``pollSecret`` stays on the Pi and is never accepted
    from the browser, so a photographed QR cannot be polled for tokens."""

    login_id: str
    age_group: Optional[str] = None
    rest_mode: PublicRestMode = "nap_recovery"
    target_duration_minutes: Optional[Literal[30, 90]] = None


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
    question_id: Optional[str] = None


class LabelCommand(BaseModel):
    label: str


class AirconCommand(BaseModel):
    command: str
    # Admin Control Debug may bypass the user-facing -5 °C comfort bias.
    direct: bool = False


class AirconFanLevelReferenceCommand(BaseModel):
    # Administrative correction only; no IR frame is transmitted.
    level: int
    note: Optional[str] = None


class BedControlCommand(BaseModel):
    command: str
