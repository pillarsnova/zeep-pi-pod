"""Longitudinal, raw-free understanding of one ZEEP user.

The contract deliberately separates observed Session facts from derived
patterns and AI readiness.  It never issues a hardware command and it never
turns usage frequency, environment exposure or questionnaire completion into
a medical or preference claim.
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping
from typing import Any

from common.mappings import as_mapping as _mapping
from common.numbers import as_number as _number
from sessions.user_baseline_context import (
    baseline_context,
)
from sessions.user_score_history import (
    nap_target_histories,
    score_entry,
    score_trend,
)
from sleep_system_policy import PERSONAL_BEHAVIOUR_BASELINE_VERSION

USER_LEARNING_PROFILE_VERSION = "zeep.user-learning-profile.v1"
USER_LEARNING_POLICY_VERSION = "zeep.user-learning-policy.v1"
MODE_ORDER = ("sleep", "nap_recovery")
MODE_METADATA = {
    "sleep": {
        "label": "Overnight Recovery",
        "score_type": "sleep_score",
        "score_title": "Sleep Score",
    },
    "nap_recovery": {
        "label": "Nap & Refresh",
        "score_type": "recovery_score",
        "score_title": "Recovery Score",
    },
}


def _profile_value(profile: Mapping[str, Any], *keys: str) -> Any:
    scopes = [profile]
    for container in ("profile", "healthProfile", "health_profile", "health"):
        nested = profile.get(container)
        if isinstance(nested, Mapping):
            scopes.append(nested)
    for scope in scopes:
        for key in keys:
            if scope.get(key) not in (None, ""):
                return scope[key]
    return None


def _gender(value: Any) -> str:
    gender = str(value or "").strip().lower()
    return gender if gender in {"male", "female", "other"} else "unspecified"


def _median(values: list[float]) -> float | None:
    return round(statistics.median(values), 1) if values else None


def _mode_key(session: Mapping[str, Any]) -> str:
    mode = _mapping(session.get("mode"))
    key = str(mode.get("group") or mode.get("key") or "unknown")
    return key if key in {*MODE_ORDER, "unknown"} else "unknown"


def _mode_summary(
    mode: str,
    sessions: list[Mapping[str, Any]],
    baseline: Mapping[str, Any],
) -> dict[str, Any]:
    entries = [entry for session in sessions if (entry := score_entry(session))]
    active_formula = entries[0].get("formula_version") if entries else None
    comparable = (
        [entry for entry in entries if entry.get("formula_version") == active_formula]
        if active_formula
        else []
    )
    values = [float(entry["value"]) for entry in comparable]
    comparable_ids = {entry["session_id"] for entry in comparable}
    durations = [
        value
        for session in sessions
        if (value := _number(session.get("duration_s"))) is not None and value >= 0
    ]
    comparable_durations = [
        value
        for session in sessions
        if session.get("session_id") in comparable_ids
        and (value := _number(session.get("duration_s"))) is not None
        and value >= 0
    ]
    latest_entry = score_entry(sessions[0]) if sessions else None
    metadata = MODE_METADATA[mode]
    data_backed = sum(int(session.get("sample_count") or 0) > 0 for session in sessions)
    targets = nap_target_histories(sessions, baseline) if mode == "nap_recovery" else []
    if mode == "nap_recovery":
        comparable = []
        comparable_durations = []
        values = []
        trend = {
            "available": False,
            "direction": "target_specific_only",
            "label": "ดูแนวโน้มแยกตามเป้าหมาย 30 หรือ 90 นาที",
            "change_points": None,
            "formula_version": None,
            "comparable_scores": 0,
            "method": "latest_vs_previous_same_formula",
        }
    else:
        trend = score_trend(entries)
    return {
        "key": mode,
        **metadata,
        "session_count": len(sessions),
        "data_backed_session_count": data_backed,
        "without_sensor_data_count": len(sessions) - data_backed,
        "scored_count": len(entries),
        "comparable_scored_count": (
            sum(item["comparable_scored_count"] for item in targets)
            if mode == "nap_recovery"
            else len(comparable)
        ),
        "without_score_count": len(sessions) - len(entries),
        "first_used_at_utc": sessions[-1].get("ended_at_utc") if sessions else None,
        "last_used_at_utc": sessions[0].get("ended_at_utc") if sessions else None,
        "usage_minutes": round(sum(durations) / 60.0, 1),
        "typical_duration_minutes": (
            round(statistics.median(comparable_durations) / 60.0, 1)
            if comparable_durations
            else None
        ),
        "latest_score": latest_entry["value"] if latest_entry else None,
        "average_score": round(sum(values) / len(values), 1) if values else None,
        "median_score": _median(values),
        "active_formula_version": active_formula,
        "trend": trend,
        "targets": targets,
        "unresolved_target_session_count": (
            len(sessions) - sum(item["session_count"] for item in targets)
            if mode == "nap_recovery"
            else 0
        ),
        "baseline": baseline_context(baseline, mode),
        "recent_scores": comparable[:5],
    }


def _profile_context(
    profile: Mapping[str, Any],
    questionnaire: Mapping[str, Any],
) -> dict[str, Any]:
    field_sources = {
        "age": _profile_value(profile, "age", "age_years", "dateOfBirth"),
        "gender": _profile_value(profile, "gender", "sex"),
        "height": _profile_value(profile, "height_cm", "height"),
        "weight": _profile_value(profile, "weight_kg", "weight"),
        "blood_group": _profile_value(profile, "blood_group", "bloodType"),
    }
    age_group = str(profile.get("age_group") or "").strip() or None
    return {
        "age_group": age_group,
        "gender": _gender(field_sources["gender"]),
        "available_fields": sorted(
            key for key, value in field_sources.items() if value
        ),
        "questionnaire": {
            "consent_status": questionnaire.get("consent_status") or "pending",
            "answered": max(0, int(questionnaire.get("answered") or 0)),
            "total": max(0, int(questionnaire.get("total") or 0)),
            "percent": max(0, min(100, int(questionnaire.get("percent") or 0))),
            "version": questionnaire.get("questionnaire_version"),
            "answer_values_included": False,
        },
        "role": "wellness_context_only",
        "medical_diagnosis_input": False,
    }


def _learning_gaps(
    modes: Mapping[str, Mapping[str, Any]],
    profile_context: Mapping[str, Any],
) -> list[str]:
    gaps = []
    sleep = modes["sleep"]
    sleep_needed = max(
        0,
        sleep["baseline"]["minimum_sessions"] - sleep["baseline"]["sessions_used"],
    )
    if sleep_needed:
        gaps.append(f"{sleep['label']} อีก {sleep_needed} ครั้ง เพื่อเริ่มเทียบรูปแบบส่วนบุคคล")
    nap = modes["nap_recovery"]
    for target in nap["targets"]:
        needed = max(
            0,
            target["baseline"]["minimum_sessions"]
            - target["baseline"]["sessions_used"],
        )
        if needed:
            gaps.append(
                f"Nap & Refresh {target['minutes']:g} นาที อีก {needed} ครั้ง "
                "เพื่อเริ่มเทียบรูปแบบส่วนบุคคล"
            )
    if nap["unresolved_target_session_count"]:
        gaps.append(
            f"Nap & Refresh {nap['unresolved_target_session_count']} ครั้ง "
            "ไม่มีเป้าหมาย 30/90 นาที จึงไม่นำไปเทียบ Baseline"
        )
    questionnaire = _mapping(profile_context.get("questionnaire"))
    if questionnaire.get("consent_status") != "granted":
        gaps.append("ข้อมูลไลฟ์สไตล์ยังไม่ถูกนำมาใช้ เพราะยังไม่มีความยินยอมเฉพาะส่วน")
    return gaps


def _learning_readiness(
    modes: dict[str, dict[str, Any]],
    profile_context: Mapping[str, Any],
) -> dict[str, Any]:
    sleep_cohort = modes["sleep"]["comparable_scored_count"]
    nap_cohort = max(
        (
            target["comparable_scored_count"]
            for target in modes["nap_recovery"]["targets"]
        ),
        default=0,
    )
    largest_cohort = max(sleep_cohort, nap_cohort)
    if largest_cohort == 0:
        status = "no_data"
        label = "ยังไม่มีประวัติให้เรียนรู้"
    elif largest_cohort < 3:
        status = "learning"
        label = "กำลังเริ่มเรียนรู้รูปแบบของคุณ"
    elif largest_cohort < 7:
        status = "growing"
        label = "เริ่มเห็นรูปแบบการพักของคุณ"
    else:
        status = "established"
        label = "รูปแบบการพักของคุณชัดเจนขึ้น"

    def comparison_ready(item: Mapping[str, Any], target_key: str) -> bool:
        baseline = _mapping(item.get("baseline"))
        return bool(
            baseline.get("status") == "active"
            and baseline.get("target_specific") is True
            and baseline.get("target_key") == target_key
            and baseline.get("baseline_policy_version")
            == PERSONAL_BEHAVIOUR_BASELINE_VERSION
            and baseline.get("score_reference_status") == "active"
            and baseline.get("score_formula_version")
            == item.get("active_formula_version")
        )

    ready_modes = []
    if comparison_ready(modes["sleep"], "overnight_7h"):
        ready_modes.append("sleep")
    ready_nap_targets = [
        target["key"]
        for target in modes["nap_recovery"]["targets"]
        if comparison_ready(target, target["key"])
    ]
    if ready_nap_targets:
        ready_modes.append("nap_recovery")
    return {
        "status": status,
        "label": label,
        "personal_comparison_ready_modes": ready_modes,
        "personal_comparison_ready_targets": ready_nap_targets,
        "multi_mode_context_ready": all(
            modes[key]["comparable_scored_count"] for key in MODE_ORDER
        ),
        "personalization_data_ready": bool(ready_modes),
        "personalization_inference_authorized": False,
        "inference_authorization_status": ("purpose_specific_consent_unavailable"),
        "recommendation_mode": "not_authorized",
        "automatic_device_control": False,
        "sleep_state_direct_control": False,
        "data_gaps": _learning_gaps(modes, profile_context),
    }


def build_user_learning_profile(
    *,
    account_key: str,
    profile: Mapping[str, Any],
    sessions: list[Mapping[str, Any]],
    baseline: Mapping[str, Any] | None = None,
    questionnaire: Mapping[str, Any] | None = None,
    history_start_utc: str,
) -> dict[str, Any]:
    """Build one deterministic profile for UI and future recommendation AI."""
    rows = list(sessions)
    mode_rows = {
        mode: [session for session in rows if _mode_key(session) == mode]
        for mode in MODE_ORDER
    }
    baseline_data = dict(baseline or {})
    modes = {
        mode: _mode_summary(mode, mode_rows[mode], baseline_data) for mode in MODE_ORDER
    }
    questionnaire_data = dict(questionnaire or {})
    context = _profile_context(profile, questionnaire_data)
    unresolved = sum(_mode_key(session) == "unknown" for session in rows)
    durations = [
        value
        for session in rows
        if (value := _number(session.get("duration_s"))) is not None and value >= 0
    ]
    first_session = rows[-1] if rows else {}
    latest_session = rows[0] if rows else {}
    data_backed = sum(int(session.get("sample_count") or 0) > 0 for session in rows)
    return {
        "contract_version": USER_LEARNING_PROFILE_VERSION,
        "policy_version": USER_LEARNING_POLICY_VERSION,
        "user": {
            "email": (
                profile.get("email")
                or profile.get("zeep_email")
                or (account_key if "@" in account_key else None)
            ),
            "display_name": profile.get("display_name") or profile.get("username"),
            "canonical_identifier": account_key,
            "identity_type": "email" if "@" in account_key else "legacy_account_key",
        },
        "history_scope": {
            "starts_at_utc": history_start_utc,
            "completed_sessions_only": True,
            "sessions_without_sensor_data_included": True,
            "raw_sensor_included": False,
        },
        "observed_history": {
            "session_count": len(rows),
            "data_backed_session_count": data_backed,
            "without_sensor_data_count": len(rows) - data_backed,
            "scored_count": sum(item["scored_count"] for item in modes.values()),
            "without_score_count": len(rows)
            - sum(item["scored_count"] for item in modes.values()),
            "unresolved_mode_count": unresolved,
            "first_used_at_utc": first_session.get("ended_at_utc"),
            "last_used_at_utc": latest_session.get("ended_at_utc"),
            "usage_minutes": round(sum(durations) / 60.0, 1),
            "modes_used": [key for key in MODE_ORDER if mode_rows[key]],
        },
        "modes": modes,
        "profile_context": context,
        "learning_readiness": _learning_readiness(modes, context),
        "ai_contract": {
            "observations_are_facts": True,
            "derived_trends_are_not_medical_findings": True,
            "usage_frequency_is_not_preference": True,
            "environment_history_is_exposure_not_preference": True,
            "cross_mode_score_comparison_allowed": False,
            "questionnaire_answers_used": False,
            "model_training_consent_available": False,
            "purpose_specific_ai_inference_consent_available": False,
            "identity_input_allowed": False,
            "personalized_inference_allowed": False,
            "allowed_output": "none_until_purpose_specific_consent",
            "automatic_actuation_allowed": False,
        },
    }
