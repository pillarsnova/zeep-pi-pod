"""Pure N3 compatibility policy shared by estimation and policy projection."""

from typing import Any

# Absolute axis proximity floor, not a physiological cutoff or N3 probability.
# In-range values have fit >= 0.863 under baseline_interval_proximity; 0.25
# deliberately tolerates some distance beyond each interval. A merely nearest
# range cannot pass when HR or RR is far from every sleep-stage reference.
SLEEP_N3_MIN_AXIS_BASELINE_FIT = 0.25


def n3_policy_snapshot() -> dict[str, Any]:
    """Return detached metadata describing the effective compatibility rule."""
    return {
        "minimum_axis_fit": SLEEP_N3_MIN_AXIS_BASELINE_FIT,
        "both_hr_and_rr_required": True,
        "rr_rate_drop_required": False,
        "nap_n3_prohibited": False,
        "engineering_guard_not_clinical_normal_range": True,
        "existing_continuity_policy_unchanged": True,
    }
