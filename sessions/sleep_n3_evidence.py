"""N3 candidate compatibility and physiology, separate from score orchestration."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from common.numbers import coerce_finite_number as _finite
from sessions.sleep_baseline_support import n3_baseline_support


@dataclass(frozen=True)
class N3Evidence:
    """Unrounded evidence reused for score arithmetic and audit projection."""

    gate: bool
    baseline_support: dict[str, Any]
    hr_cv_limit: float
    rr_cv_limit: float
    hr_conflict: float
    rr_conflict: float


def evaluate_n3_evidence(
    hr_fits: Mapping[str, float],
    rr_fits: Mapping[str, float],
    *,
    mean_hr: float | None,
    mean_rr: float | None,
    deep_cv_threshold: float,
    waveform_available: bool,
    drift_flag: bool,
    current_stage: str,
    movement: float,
    move_deep_ratio: float,
    hr_cv: float,
    rr_cv: float,
    regularity: float | None,
    relative_sleep_support: float,
    hr_drop: float,
) -> N3Evidence:
    """Evaluate prepared telemetry without changing the existing N3 formula."""
    hr_conflict = max(0.0, _finite(hr_fits.get("n2")) - _finite(hr_fits.get("n3")))
    rr_conflict = max(0.0, _finite(rr_fits.get("n2")) - _finite(rr_fits.get("n3")))
    hr_cv_limit = max(0.010, _finite(deep_cv_threshold, 0.025))
    rr_cv_limit = max(0.025, min(0.050, hr_cv_limit * 1.6))
    reference = n3_baseline_support(hr_fits, rr_fits, mean_hr=mean_hr, mean_rr=mean_rr)
    gate = bool(
        waveform_available
        and not drift_flag
        and reference["passed"]
        and current_stage in {"n2", "n3"}
        and movement < move_deep_ratio
        and hr_cv <= hr_cv_limit
        and rr_cv <= rr_cv_limit
        and regularity is not None
        and regularity >= 0.58
        and hr_conflict < 0.08
        and max(relative_sleep_support, hr_drop) >= 0.40
    )
    return N3Evidence(
        gate=gate,
        baseline_support=reference,
        hr_cv_limit=hr_cv_limit,
        rr_cv_limit=rr_cv_limit,
        hr_conflict=hr_conflict,
        rr_conflict=rr_conflict,
    )
