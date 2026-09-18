"""Additive public contract for one after-rest action."""

from typing import Literal

from pydantic import Field

from sessions._response_model_base import ContractModel


class RestoreRecommendation(ContractModel):
    primary: str
    source_driver_key: str | None = Field(...)
    version: str
    one_action_only: Literal[True]
    automatic_actuation: Literal[False]
    medical_advice: Literal[False]
    tip_id: str | None = None
    title: str | None = None
    when_label: str | None = None
    reason: str | None = None
    basis: (
        Literal[
            "session_sensor",
            "personal_baseline",
            "self_report",
            "limited_data",
            "safety",
        ]
        | None
    ) = None
    historical_session_context: Literal[True] | None = None
    whole_day_readiness_claim: Literal[False] | None = None
