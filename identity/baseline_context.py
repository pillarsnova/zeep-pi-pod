"""Versioned demographic strata from a Session's health-profile snapshot.

BMI is descriptive context, not a Sleep Stage threshold or score adjustment.
This module does not read profiles, update history or learn population ranges.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from sleep_system_policy import AGE_SLEEP_BASELINES, age_group

BASELINE_CONTEXT_VERSION = "zeep-baseline-demographics-v1.0"
BMI_REFERENCE = "who-adult-international-v1"
BMI_BANDS = (
    (18.5, "below_18_5", "ต่ำกว่า 18.5"),
    (25.0, "18_5_to_25", "18.5–<25"),
    (30.0, "25_to_30", "25–<30"),
    (math.inf, "30_and_above", "30 ขึ้นไป"),
)


def _number(value: Any, minimum: float, maximum: float) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return result if math.isfinite(result) and minimum <= result <= maximum else None


def _age_context(reference: Mapping[str, Any]) -> tuple[int | None, str, bool]:
    raw_age = reference.get("age_years")
    age = _number(raw_age, 0, 120)
    if age is not None and age.is_integer():
        return int(age), age_group(int(age)), age >= 18
    # An explicit invalid age must not be hidden by a conflicting age group.
    if raw_age is not None:
        return None, "unspecified", False
    selected = str(reference.get("age_group") or "unspecified")
    if selected in AGE_SLEEP_BASELINES and selected != "unspecified":
        return None, selected, True
    return None, "unspecified", False


def build_baseline_context(reference: Mapping[str, Any]) -> dict[str, Any]:
    """Describe sex/profile-gender × age × BMI without inventing a norm.

    Callers pass the immutable health snapshot for that Session, not the latest
    profile when reconstructing a past result. Height is centimetres, weight
    is kilograms. Classify using unrounded BMI, round only its display value.
    """
    age, group, adult = _age_context(reference)
    gender = str(reference.get("gender") or "unspecified").lower().strip()
    if gender not in {"male", "female", "other", "unspecified"}:
        gender = "unspecified"
    height = _number(reference.get("height_cm"), 80, 250)
    weight = _number(reference.get("weight_kg"), 20, 400)
    bmi = weight / (height / 100) ** 2 if height and weight else None
    band, label = None, None
    if adult and bmi is not None:
        band, label = next((key, text) for upper, key, text in BMI_BANDS if bmi < upper)
    missing = []
    if gender == "unspecified":
        missing.append("gender")
    if group == "unspecified":
        missing.append("adult_age_group")
    if height is None:
        missing.append("height_cm")
    if weight is None:
        missing.append("weight_kg")
    return {
        "version": BASELINE_CONTEXT_VERSION,
        "gender": gender,
        "gender_source": "profile_gender_not_inferred_biological_sex",
        "age_years": age,
        "age_group": group,
        "adult_reference_applicable": adult,
        "bmi": {
            "value": round(bmi, 2) if bmi is not None else None,
            "unit": "kg/m2",
            "band": band,
            "band_label": label,
            "reference": BMI_REFERENCE,
            "status": (
                "missing_measurements"
                if bmi is None
                else "available"
                if adult
                else "adult_reference_not_applicable"
            ),
        },
        "cohort_key": f"{gender}|{group}|{band}" if not missing and band else None,
        "missing_fields": missing,
        "role": "stratification_context_only",
        "matched_cohort_reference_available": False,
        "bmi_direct_stage_influence": False,
        "bmi_score_adjustment": False,
    }


def project_health_reference(
    reference: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Enrich an old/new Session snapshot without editing it or its owner."""
    if reference is None:
        return None
    result = deepcopy(dict(reference))
    result["baseline_context"] = build_baseline_context(result)
    return result
