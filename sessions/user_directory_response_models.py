"""Response contracts for the Admin person-level usage directory."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, root_validator

from sessions._response_model_base import ContractModel
from sessions.usage_response_models import ApiResponseBase, UsageIdentity


class UsageUserModeSummary(ContractModel):
    session_count: int = Field(ge=0)
    scored_count: int = Field(ge=0)
    latest_score: float | None = Field(..., ge=0, le=100)
    latest_score_at_utc: datetime | None = Field(...)

    @root_validator(skip_on_failure=True)
    def score_count_cannot_exceed_sessions(cls, values):
        if values["scored_count"] > values["session_count"]:
            raise ValueError("scored_count cannot exceed session_count")
        if (values["latest_score"] is None) != (values["latest_score_at_utc"] is None):
            raise ValueError("latest score and timestamp must be published together")
        return values


class UsageUserModes(ContractModel):
    sleep: UsageUserModeSummary
    nap_recovery: UsageUserModeSummary
    unknown: UsageUserModeSummary


class UsageUserSummary(ContractModel):
    user: UsageIdentity
    usage_count: int = Field(ge=0)
    total_duration_s: float = Field(ge=0)
    last_used_at_utc: datetime | None = Field(...)
    without_sensor_data_count: int = Field(ge=0)
    without_score_count: int = Field(ge=0)
    modes: UsageUserModes

    @root_validator(skip_on_failure=True)
    def mode_counts_must_reconcile(cls, values):
        modes = values["modes"]
        mode_total = sum(
            mode.session_count
            for mode in (modes.sleep, modes.nap_recovery, modes.unknown)
        )
        if mode_total != values["usage_count"]:
            raise ValueError("mode counts must equal usage_count")
        if values["without_sensor_data_count"] > values["usage_count"]:
            raise ValueError("missing Sensor count cannot exceed usage_count")
        if values["without_score_count"] > values["usage_count"]:
            raise ValueError("missing score count cannot exceed usage_count")
        return values


class UsageUserDirectorySummary(ContractModel):
    user_count: int = Field(ge=0)
    users_with_sessions: int = Field(ge=0)
    users_without_sessions: int = Field(ge=0)
    usage_count: int = Field(ge=0)
    overnight_count: int = Field(ge=0)
    nap_recovery_count: int = Field(ge=0)
    unresolved_count: int = Field(ge=0)

    @root_validator(skip_on_failure=True)
    def counts_must_reconcile(cls, values):
        if (
            values["users_with_sessions"] + values["users_without_sessions"]
            != values["user_count"]
        ):
            raise ValueError("user totals must reconcile")
        if (
            values["overnight_count"]
            + values["nap_recovery_count"]
            + values["unresolved_count"]
            != values["usage_count"]
        ):
            raise ValueError("mode totals must equal usage_count")
        return values


class UsageUserDirectory(ContractModel):
    contract_version: Literal["zeep.usage-user-directory.v1"]
    users: list[UsageUserSummary]
    summary: UsageUserDirectorySummary
    history_start_utc: datetime


class UsageUserDirectoryResponse(ApiResponseBase):
    kind: Literal["usage_user_directory"]
    data: UsageUserDirectory
