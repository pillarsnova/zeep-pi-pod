"""Independent HR/RR compatibility checks for N3 candidate evidence.

These are versioned engineering checks, not clinical normal ranges or the
probability of EEG-defined N3. Population intervals remain overlapping priors.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from sessions.sleep_n3_policy import SLEEP_N3_MIN_AXIS_BASELINE_FIT


def n3_baseline_support(
    hr_fits: Mapping[str, float],
    rr_fits: Mapping[str, float],
    *,
    mean_hr: Any,
    mean_rr: Any,
) -> dict[str, Any]:
    """Reject a nearest-but-distant range without averaging away a weak axis.

    Require finite paired vitals and independently usable N3 proximity on both
    axes. A constant RR may pass: a respiratory-rate decrease is not required.
    The caller still applies waveform, movement and temporal confirmation.
    """
    reasons: list[str] = []
    fits: dict[str, float | None] = {}
    for axis, values, measured in (
        ("hr", hr_fits, mean_hr),
        ("rr", rr_fits, mean_rr),
    ):
        try:
            value = float(measured)
            valid_value = not isinstance(measured, bool) and math.isfinite(value)
            valid_value = valid_value and value > 0
        except (TypeError, ValueError, OverflowError):
            valid_value = False
        try:
            fit = float(values["n3"])
            valid_fit = not isinstance(values["n3"], bool)
            valid_fit = valid_fit and math.isfinite(fit) and 0 <= fit <= 1
        except (KeyError, TypeError, ValueError, OverflowError):
            fit, valid_fit = 0.0, False
        fits[axis] = round(fit, 6) if valid_fit else None
        if not valid_value:
            reasons.append(f"{axis}_measurement_invalid")
        if not valid_fit:
            reasons.append(f"{axis}_fit_invalid")
        elif fit < SLEEP_N3_MIN_AXIS_BASELINE_FIT:
            reasons.append(f"{axis}_outside_n3_reference_support")
    return {
        "passed": not reasons,
        "axis_fits": fits,
        "minimum_axis_fit": SLEEP_N3_MIN_AXIS_BASELINE_FIT,
        "reason_codes": reasons,
        "role": "candidate_compatibility_not_stage_probability",
        "rr_rate_drop_required": False,
    }
