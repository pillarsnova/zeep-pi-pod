"""Canonical, dependency-free policy manifest for the ZEEP sleep system.

Live estimation, historical replay, post-session scoring, documentation checks,
and the Admin policy API import this module.  Keeping policy data here prevents
the same transition or score version from being edited independently in several
files.  The values are ZEEP engineering/wellness rules, not AASM scoring rules
and not a clinical validation claim.
"""

from __future__ import annotations

from typing import Any


# Every persisted decision/report carries these versions for provenance.
SLEEP_PIPELINE_CONTRACT_VERSION = (
    "zeep-sleep-health-pipeline-v1.12-complete-occupied-epochs"
)
SLEEP_ESTIMATOR_VERSION = (
    "bcg-audio-bed-5state-v1.29-complete-occupied-epochs"
)
SLEEP_EVIDENCE_VERSION = (
    "zeep-sleep-state-evidence-v3.7-complete-occupied-epochs"
)
ZEEP_SLEEP_BASELINE_VERSION = "zeep-sleep-state-baseline-v1.8-sep1-cutover"
ZEEP_SLEEP_TRANSITION_POLICY_VERSION = (
    "zeep-semimarkov-30s-v1.18-scoreable-continuity"
)
SLEEP_G2_ONTOLOGY_VERSION = "g2-aasm-5class-v1.0"
SLEEP_HISTORY_BACKFILL_VERSION = (
    "zeep-sleep-history-reclass-v28-complete-occupied-epochs"
)
SESSION_REPORT_VERSION = "zeep-session-report-v10.8-respiratory-wellness"
SLEEP_QUALITY_VERSION = (
    "zeep-rest-quality-v8.6-state-evidence-coverage-split"
)
SLEEP_SCORE_FORMULA_VERSION = (
    "zeep-sleep-score-v1.1-20-30-30-15-5-evidence-coverage"
)
# v10.8 adds a claim-bounded respiratory Wellness interpretation without
# changing Sleep State or either score. v10.7 guarantees five-state attribution
# for every occupied recording
# interval and separates that coverage from measured HR/RR/BCG evidence.
# Keep every reviewed predecessor readable, but never generate a current
# report beside stale quality during a report-only rebuild.
PRE_RESPIRATORY_SESSION_REPORT_VERSION = (
    "zeep-session-report-v10.7-complete-occupied-epochs"
)
PRE_COMPLETE_SESSION_REPORT_VERSION = (
    "zeep-session-report-v10.6-continuity-accounting"
)
PRE_COMPLETE_SLEEP_QUALITY_VERSION = (
    "zeep-rest-quality-v8.5-continuity-score-eligibility"
)
PRE_RESTORE_SESSION_REPORT_VERSION = (
    "zeep-session-report-v10.4-recovery-target-guardrails"
)
PRE_CONTINUITY_SESSION_REPORT_VERSION = (
    "zeep-session-report-v10.5-restore-summary"
)
PRE_CONTINUITY_SLEEP_QUALITY_VERSION = (
    "zeep-rest-quality-v8.4-recovery-target-guardrails"
)
PREVIOUS_SESSION_REPORT_VERSION = "zeep-session-report-v10.3-nap-goal-duration"
PREVIOUS_SLEEP_QUALITY_VERSION = "zeep-rest-quality-v8.3-nap-goal-duration"
APPROVED_SLEEP_RESULT_VERSION_PAIRS = frozenset({
    (SESSION_REPORT_VERSION, SLEEP_QUALITY_VERSION),
    (PRE_RESPIRATORY_SESSION_REPORT_VERSION, SLEEP_QUALITY_VERSION),
    (
        PRE_COMPLETE_SESSION_REPORT_VERSION,
        PRE_COMPLETE_SLEEP_QUALITY_VERSION,
    ),
    (
        PRE_CONTINUITY_SESSION_REPORT_VERSION,
        PRE_CONTINUITY_SLEEP_QUALITY_VERSION,
    ),
    (
        PRE_RESTORE_SESSION_REPORT_VERSION,
        PRE_CONTINUITY_SLEEP_QUALITY_VERSION,
    ),
    (PREVIOUS_SESSION_REPORT_VERSION, PREVIOUS_SLEEP_QUALITY_VERSION),
})
RECOVERY_SCORE_FORMULA_VERSION = (
    "zeep-recovery-score-v2.1-complete-rest-25-35-30-10"
)
RESTORE_SUMMARY_VERSION = "zeep-restore-summary-v1.0"
RESPIRATORY_WELLNESS_VERSION = "zeep-respiratory-wellness-v1.1"
RESTORE_ACTION_BANDS_VERSION = "zeep-restore-action-bands-v1.0"
RESTORE_DRIVER_POLICY_VERSION = "zeep-restore-drivers-v1.0"
RESTORE_BASELINE_COMPARISON_VERSION = (
    "zeep-restore-personal-baseline-v1.0"
)
RESTORE_RECOMMENDATION_VERSION = "zeep-restore-recommendation-v1.0"
RESTORE_BASELINE_MIN_COMPARISON_SESSIONS = 7
RESTORE_BASELINE_STABLE_SESSIONS = 14
RESTORE_TREND_MAX_SESSIONS = 30
ENVIRONMENT_CONTEXT_POLICY_VERSION = (
    "zeep-environment-context-v2.1-optional-acoustic-input"
)
ENVIRONMENT_SESSION_AGGREGATION_VERSION = (
    "zeep-environment-session-v1.0-sustained-decile"
)
TERMINAL_WAKE_POLICY_VERSION = "zeep-terminal-wake-boundary-v1.0"


ZEEP_SLEEP_STATES = ("wake", "n1", "n2", "n3", "rem")
ZEEP_OFF_BED_DATA_STATUSES = frozenset({
    "empty_bed",
    "confirmed_off_bed",
    "confirmed_or_dominant_off_bed",
    "off_bed",
    "no_session",
})
# Vendor labels remain useful presentation/ingest vocabulary, but a raw label
# alone is not a confirmed occupancy boundary. Projectors may latch OFF BED only
# from a canonical status above or an explicit confirmed bed-exit evidence item.
ZEEP_OFF_BED_LABELS = frozenset({
    "get out of bed", "off bed", "off_bed", "empty bed",
})
ZEEP_ON_BED_LABELS = frozenset({
    "on bed", "moving", "weak breathing", "snoring",
})
ZEEP_ON_BED_STATUS_CODES = frozenset({0, 2, 3, 5})

# Broad, overlapping population priors used until sufficient personal history
# exists. They are engineering references for a contactless Wellness estimate,
# not clinical Sleep Stage boundaries. Live and replay import this same table.
AGE_SLEEP_BASELINES = {
    "unspecified": {
        "wake": {"hr": (65, 94), "rr": (13, 21)}, "n1": {"hr": (61, 85), "rr": (12, 19)},
        "n2": {"hr": (56, 79), "rr": (11, 18)}, "n3": {"hr": (50, 72), "rr": (10, 17)},
        "rem": {"hr": (59, 90), "rr": (12, 21)},
    },
    "18-29": {
        "wake": {"hr": (65, 88), "rr": (13, 20)}, "n1": {"hr": (61, 80), "rr": (12, 18)},
        "n2": {"hr": (56, 74), "rr": (11, 17)}, "n3": {"hr": (50, 67), "rr": (10, 16)},
        "rem": {"hr": (59, 84), "rr": (12, 20)},
    },
    "30-44": {
        "wake": {"hr": (66, 90), "rr": (13, 20)}, "n1": {"hr": (62, 81), "rr": (12, 18)},
        "n2": {"hr": (57, 75), "rr": (11, 17)}, "n3": {"hr": (51, 68), "rr": (10, 16)},
        "rem": {"hr": (60, 86), "rr": (12, 20)},
    },
    "45-59": {
        "wake": {"hr": (67, 92), "rr": (13, 21)}, "n1": {"hr": (63, 83), "rr": (12, 19)},
        "n2": {"hr": (58, 77), "rr": (11, 18)}, "n3": {"hr": (52, 70), "rr": (10, 17)},
        "rem": {"hr": (61, 88), "rr": (12, 21)},
    },
    "60+": {
        "wake": {"hr": (68, 94), "rr": (13, 21)}, "n1": {"hr": (64, 85), "rr": (12, 19)},
        "n2": {"hr": (59, 79), "rr": (11, 18)}, "n3": {"hr": (53, 72), "rr": (10, 17)},
        "rem": {"hr": (62, 90), "rr": (12, 21)},
    },
}
AGE_GROUP_DEFAULT_AGE = {"18-29": 24, "30-44": 37, "45-59": 52, "60+": 65}
GENDER_BASELINE_ADJUSTMENTS = {
    "male": {"label": "ชาย", "hr_offset": 0, "rr_offset": 0,
             "rem_variability_weight": 1.10,
             "note": "REM sympathetic/HR variability weighting สูงขึ้นเล็กน้อย"},
    "female": {"label": "หญิง", "hr_offset": 2, "rr_offset": 0,
               "rem_variability_weight": 1.00,
               "note": "HR starting range +2 BPM; RR คงเดิม"},
    "other": {"label": "อื่น ๆ", "hr_offset": 0, "rr_offset": 0,
              "rem_variability_weight": 1.00,
              "note": "ใช้ neutral baseline จนมี Personal Baseline"},
    "unspecified": {"label": "ไม่ระบุ", "hr_offset": 0, "rr_offset": 0,
                    "rem_variability_weight": 1.00,
                    "note": "ใช้ neutral baseline จนมี Personal Baseline"},
}


def age_group(age: Any) -> str:
    """Map exact age to the shared ZEEP population-prior group."""
    try:
        value = int(age)
    except (TypeError, ValueError):
        return "unspecified"
    if value < 30:
        return "18-29"
    if value < 45:
        return "30-44"
    if value < 60:
        return "45-59"
    return "60+"


def gender_adjusted_baseline(
    selected_age_group: str, gender: Any,
) -> tuple[dict[str, dict[str, tuple[float, float]]], dict[str, Any]]:
    """Return the shared broad HR/RR prior plus demographic provenance."""
    group = selected_age_group if selected_age_group in AGE_SLEEP_BASELINES else "unspecified"
    gender_key = str(gender or "unspecified").strip().lower()
    adjustment = dict(GENDER_BASELINE_ADJUSTMENTS.get(
        gender_key, GENDER_BASELINE_ADJUSTMENTS["unspecified"]
    ))
    adjusted = {}
    for stage, ranges in AGE_SLEEP_BASELINES[group].items():
        adjusted[stage] = {
            "hr": tuple(float(value) + float(adjustment["hr_offset"])
                        for value in ranges["hr"]),
            "rr": tuple(float(value) + float(adjustment["rr_offset"])
                        for value in ranges["rr"]),
        }
    adjustment.update({"gender_key": gender_key, "age_group": group})
    return adjusted, adjustment

# Canonical Thai presentation copy for every surface that explains a confirmed
# Sleep State.  These labels describe ZEEP's five-state wellness estimate; they
# do not make the estimate equivalent to an AASM/PSG score.
SLEEP_STAGE_PRESENTATION = {
    "wake": {
        "code": "W",
        "title": "ตื่น",
        "meaning": "ช่วงที่ระบบประเมินว่ายังตื่นหรือกลับเข้าสู่สถานะตื่น",
    },
    "n1": {
        "code": "N1",
        "title": "หลับตื้น / เคลิ้มหลับ",
        "meaning": "เริ่มเข้าสู่การนอน ร่างกายผ่อนคลาย และปลุกให้ตื่นได้ง่าย",
    },
    "n2": {
        "code": "N2",
        "title": "หลับสนิทขึ้น / หลับตื้นต่อเนื่อง",
        "meaning": "หัวใจและการหายใจช้าลง ร่างกายเข้าสู่การนอนที่ต่อเนื่องขึ้น",
    },
    "n3": {
        "code": "N3",
        "title": "หลับลึก",
        "meaning": "ช่วงหลับลึกที่ร่างกายได้พักอย่างต่อเนื่อง",
    },
    "rem": {
        "code": "REM",
        "title": "ระยะ REM / หลับฝัน",
        "meaning": "ช่วงหลับที่สมองยังทำงานมากขึ้นและมักมีความฝัน",
    },
}

# Normal adjacency graph. Bed exit or sustained movement corroborated by a
# same-window physiological rise is an explicit Wake override. Brief body or
# blanket movement while remaining on-bed is sleep-compatible and cannot use
# that override.
SLEEP_ALLOWED_TRANSITIONS = {
    "wake": frozenset({"wake", "n1"}),
    # N1->REM is a rare SOREMP-like edge, not the default sleep sequence.
    # The graph only makes the edge reachable: the existing REM physiology
    # gate and two 30-second evidence epochs must still pass. Quiet wake,
    # sleepiness, or daydreaming alone can therefore never create REM.
    "n1": frozenset({"wake", "n1", "n2", "rem"}),
    # A direct N2->Wake requires the strong-Wake override. Without a same-window
    # BCG/movement/bed-exit proxy the path first emits N1.
    "n2": frozenset({"n1", "n2", "n3", "rem"}),
    "n3": frozenset({"n3", "n2", "rem"}),
    # REM may end in Wake naturally, including when the sleeper is awakened.
    # The change still waits for two evidence epochs; occupancy/bed-exit uses
    # its separate faster safety path.
    "rem": frozenset({"rem", "n2", "n1", "wake"}),
}

# A replayed sequence may contain a direct sleep->Wake only when the same
# analysis window has the required strong-Wake proxy. These pairs can never be
# accepted, even with that override.
SLEEP_PROHIBITED_TRANSITIONS = frozenset({
    ("wake", "n2"), ("wake", "n3"), ("wake", "rem"),
    ("n1", "n3"),
    ("n3", "n1"),
    ("rem", "n3"),
})

# Sensors are retained every 10 seconds, three frames form one evidence epoch,
# and two consecutive evidence epochs are required before changing the
# confirmed Sleep State. These are ZEEP engineering controls, not AASM/PSG
# scoring criteria. Life-safety and occupancy continue on their faster clocks.
SLEEP_SENSOR_SAMPLE_SECONDS = 10.0
SLEEP_EVIDENCE_EPOCH_SECONDS = 30.0
SLEEP_CONFIRMATION_SECONDS = 60.0
SLEEP_LONG_CONTEXT_SECONDS = 270.0
SLEEP_SENSOR_FRAMES_PER_EPOCH = 3
SLEEP_CONFIRM_EPOCHS = 2
SLEEP_STAGE_CONFIRM_TICKS = {
    "wake": SLEEP_CONFIRM_EPOCHS,
    "n1": SLEEP_CONFIRM_EPOCHS,
    # First/returning N2 evidence is deliberately required for two minutes.
    # Stable physiology alone is not enough to separate N2 from quiet Wake.
    "n2": 4,
    "n3": SLEEP_CONFIRM_EPOCHS,
    "rem": SLEEP_CONFIRM_EPOCHS,
}
SLEEP_STAGE_CONFIRMATION_SECONDS = {
    stage: float(ticks) * SLEEP_EVIDENCE_EPOCH_SECONDS
    for stage, ticks in SLEEP_STAGE_CONFIRM_TICKS.items()
}
# Backward-compatible public field. The former two-Epoch provisional window
# repeatedly removed real occupied time whenever evidence oscillated around a
# boundary. v1.29 has one rule instead: the confirmed State owns every occupied
# Epoch until a challenger is confirmed, so no carry Epoch is provisional.
SLEEP_PROVISIONAL_HOLD_EPOCHS = 0
SLEEP_STAGE_MIN_DWELL_SECONDS = {
    "wake": 10.0, "n1": 30.0, "n2": 60.0, "n3": 60.0, "rem": 60.0,
}

# Quiet wake and N1 overlap strongly in contactless BCG.  A new Session must
# therefore collect a conservative awake/settling interval before the
# semi-Markov path may leave Wake.  After that interval, two consecutive
# evidence epochs must show a quiet bed and a sustained downward HR/RR trend.
# This is an engineering false-positive guard, not an AASM sleep-onset rule.
SLEEP_ONSET_MIN_OBSERVATION_SECONDS = 5 * 60.0
SLEEP_ONSET_MAX_MOVEMENT_RATIO = 0.15
SLEEP_ONSET_MIN_DOWNWARD_TRANSITION = 0.20
# A falling slope is observable only while the user is settling.  Once HR/RR
# have reached a lower plateau the slope becomes flat even though the level
# shift remains.  This gate accepts that sustained, session-relative change;
# elapsed time by itself still cannot create N1.
SLEEP_ONSET_MIN_RELATIVE_SLEEP_SUPPORT = 0.20
SLEEP_ONSET_MAX_HR_RISE_BPM_PER_MIN = 0.50
SLEEP_ONSET_MAX_RR_RISE_PER_MIN = 0.50
SLEEP_ONSET_INITIAL_WAKE_SUPPORT = 0.75

# Probability telemetry is filtered independently from the rolling feature
# window. EMA remains the default continuity source. A current gated N2 winner
# may bypass a trailing N1 EMA only for natural N1 -> N2 progression; a current
# N3 winner has the equivalent strict-gate override. The semi-Markov guard still
# requires the target's configured confirmation (N2: 120 s; N3: 60 s). These
# targeted exceptions prevent stale EMA inertia from trapping genuine sleep.
# They are engineering controls, not AASM/PSG scoring criteria.
SLEEP_PROBABILITY_EMA_ALPHA = 0.20
SLEEP_PROBABILITY_SWITCH_MARGIN = 0.05
# These are engineering abstention gates, not calibrated medical probabilities.
# Evidence below either gate is retained for Admin inspection but cannot create
# a new confirmed W/N1/N2/N3/REM label.
# Evidence still abstains when stages are close, while two 30-second epochs
# provide the second layer of confirmation.  The former 0.50/0.10 boundary
# discarded too much valid multi-state evidence after sleep onset.
SLEEP_EVIDENCE_MIN_WINNER = 0.45
SLEEP_EVIDENCE_MIN_MARGIN = 0.08
# N3 already passes the strict waveform, movement, variability, regularity and
# session-relative drop gates before this specialised evidence boundary is
# considered.  Requiring the generic five-state 50% winner after all of those
# independent gates made valid N3 windows unreachable in historical replay.
# Until paired reference validation is available, N3 uses the same conservative
# ambiguity boundary as every other stage.  The previous 0.40/0.05 sensitivity
# setting remains an offline experiment only; it must not be a live shortcut.
SLEEP_N3_GATED_MIN_WINNER = SLEEP_EVIDENCE_MIN_WINNER
SLEEP_N3_GATED_MIN_MARGIN = SLEEP_EVIDENCE_MIN_MARGIN
# Temperature sharpens *relative engineering evidence* after every state's
# features have been normalised to the same 0..1 budget.  The output remains an
# evidence distribution and must not be described as a calibrated probability.
SLEEP_SCORE_SOFTMAX_TEMPERATURE = 4.0
# HR/RR interval proximity is pooled with gated physiology evidence before
# temporal smoothing. Agreement between the overall Fit winner and the current
# confirmed state receives a 35% continuity contribution, but only while that
# state remains gate-eligible. Disagreement must still pass the normal gate,
# margin, dwell and confirmation rules.
SLEEP_HR_RR_FIT_FUSION_WEIGHT = 0.20
SLEEP_HR_RR_FIT_FUSION_AGREEMENT_WEIGHT = 0.35


def continuity_hold_contract(
    previous_state: Any,
    *,
    candidate: Any = None,
    decision: str,
    hold_epochs: int = 1,
) -> dict[str, Any]:
    """Return the canonical contract for an uncertain State transition.

    A physiology/evidence gate controls entry into a *new* State. Until that
    challenger is confirmed, the previous W/N1/N2/N3/REM State owns the whole
    occupied Epoch and remains score-eligible. If this is the first occupied
    Epoch, W is the explicit conscious-entry anchor.

    Callers must resolve confirmed OFF BED and an inactive Session before using
    this contract. Missing or ambiguous evidence lowers confidence and remains
    excluded from Personal Baseline learning; it does not create a sixth State
    or remove real occupied time from the Session score.
    """
    previous = (
        str(previous_state).lower()
        if str(previous_state).lower() in ZEEP_SLEEP_STATES
        else None
    )
    initial_anchor = previous is None
    attributed_state = previous or "wake"
    pending = (
        str(candidate).lower()
        if str(candidate).lower() in ZEEP_SLEEP_STATES
        and str(candidate).lower() != attributed_state
        else None
    )
    epochs = max(1, int(hold_epochs or 1))
    return {
        "held": not initial_anchor,
        "held_previous_state": not initial_anchor,
        "confirmed_state": attributed_state,
        "pending_state": pending,
        "continuity_hold_epochs": epochs if not initial_anchor else 0,
        "provisional": False,
        "data_status": (
            "initial_awake_anchor" if initial_anchor else "continuity_hold"
        ),
        "decision": decision if not initial_anchor else "initial_awake_anchor",
        "decision_kind": (
            "continuity_hold" if not initial_anchor else "confirmed_state"
        ),
        "score_attribution_state": attributed_state,
        "challenger_counted_as_new_state": False,
        "score_eligible": True,
        "excluded_from_score": False,
        "excluded_from_stage_statistics": False,
        "excluded_from_personal_baseline": True,
        "state_source": (
            "initial_awake_anchor"
            if initial_anchor
            else "carry_previous_confirmed"
        ),
    }


# Backward-compatible constant name: this threshold detects a discontinuity
# between valid classification windows. It no longer resets the confirmed
# Sleep State/onset for the same active Session; only pending evidence is reset.
SLEEP_CONTEXT_RESET_GAP_SECONDS = 60.0
# Compatibility name for the bounded post-restart cache bridge. Recording
# itself is never left blank: the preceding confirmed State remains scoreable
# at low confidence until fresh evidence returns, while confirmed Bed Exit
# overrides it immediately. The bridge never teaches Personal Baseline.
SLEEP_RESTART_STATE_HOLD_SECONDS_DEFAULT = 60.0
SLEEP_MIN_PAIRED_VITAL_COVERAGE = 0.80
SLEEP_BUCKET_MIN_BCG_PACKETS = 8
SLEEP_MIN_WAVEFORM_COVERAGE = 0.80
SLEEP_DISPLAY_WINNER_MARGIN = 0.01

# Canonical estimator defaults. A Pod may override these through environment
# variables for a versioned field experiment, but replay records the effective
# values explicitly and uses these defaults when no override is supplied.
SLEEP_DEFAULT_BASELINE_HR_WEIGHT = 0.50
SLEEP_DEFAULT_BASELINE_RR_WEIGHT = 0.40
SLEEP_DEFAULT_N3_RR_CONFLICT_PENALTY = 1.20
SLEEP_DEFAULT_N2_RR_CONFLICT_SUPPORT = 0.30
SLEEP_DEFAULT_MOVE_WAKE_RATIO = 0.15
SLEEP_DEFAULT_MOVE_DEEP_RATIO = 0.05
SLEEP_DEFAULT_HR_CV_DEEP = 0.025
SLEEP_DEFAULT_HR_CV_REM = 0.060
SLEEP_DEFAULT_ACOUSTIC_DISTURBANCE_DBA = 55.0
SLEEP_DEFAULT_ACOUSTIC_MIN_COVERAGE = 0.50
SLEEP_DEFAULT_ACOUSTIC_WAKE_SUPPORT_MAX = 0.35

# Personal physiology is learned only from completed Sessions that the current
# versioned report classified as genuine sleep.  Stable HR/RR during meditation
# or quiet awake rest must never be folded into the user's Sleep Baseline.
PERSONAL_BASELINE_MIN_NIGHTS = 3
PERSONAL_BASELINE_MAX_NIGHTS = 7
PERSONAL_BASELINE_MIN_SESSION_SECONDS = 25 * 60
PERSONAL_BASELINE_MIN_DETECTED_SLEEP_SECONDS = 20 * 60
PERSONAL_BASELINE_MIN_HR_SAMPLES = 20
# During the pilot, prior Sessions describe expected behaviour and confidence
# only.  Direct personal influence is held until a frozen estimator is checked
# against independent labels; this prevents model outputs training themselves.
PERSONAL_BASELINE_STAGE_INFLUENCE_ENABLED = False
# Product-data cutover requested for the new pilot.  2026-09-01 00:00 in
# Asia/Bangkok equals 2026-08-31 17:00 UTC.  Older Sessions remain auditable,
# but are excluded from every new personal/behaviour baseline. Raw BCG and
# Sensor records are never deleted by this policy.
PERSONAL_BASELINE_LEARNING_START_LOCAL_DATE = "2026-09-01"
PERSONAL_BASELINE_LEARNING_START_TIMEZONE = "Asia/Bangkok"
PERSONAL_BASELINE_LEARNING_START_UTC = "2026-08-31T17:00:00+00:00"


# Mode-aware duration targets apply only to the 15-point duration term. The
# 7-hour AASM/SRS recommendation is used for adult overnight/main sleep, not for
# a nap, shift-rest, or short jet-lag rest.
REST_MODE_DURATION_TARGETS_S = {
    "short_nap": 30 * 60,
    "cycle_nap": 90 * 60,
    "shift_rest": 90 * 60,
    "overnight": 7 * 3600,
}

# Nap & Refresh has two deliberately selected opportunities.  The target is
# persisted when the Session starts; elapsed time must never silently turn a
# 30-minute Session into a 90-minute Session (or the reverse).  Historical
# records without this field remain reviewable, but are not assigned a target
# by inference.
NAP_RECOVERY_TARGET_OPTIONS = {
    30 * 60: {
        "key": "nap_30",
        "label": "Nap & Refresh · 30 นาที",
        "recommended_range_seconds": [25 * 60, 35 * 60],
        "extended_max_seconds": 45 * 60,
    },
    90 * 60: {
        "key": "nap_90",
        "label": "Nap & Refresh · 90 นาที",
        "recommended_range_seconds": [75 * 60, 105 * 60],
        "extended_max_seconds": 120 * 60,
    },
}
NAP_RECOVERY_DEFAULT_TARGET_SECONDS = 30 * 60
NAP_RECOVERY_MINIMUM_SCORE_SECONDS = 10 * 60
NAP_RECOVERY_LEGACY_HARD_MAX_SECONDS = 120 * 60
RECOVERY_SCORE_COMPONENT_MAX_POINTS = {
    "goal_duration": 25.0,
    "physiological_response": 35.0,
    "rest_continuity": 30.0,
    "environment_support": 10.0,
}

# The Pilot exposes exactly two Session goals. Detailed sub-modes remain
# internal for historical replay and duration scoring; they must not reappear
# as extra choices in the user flow.
REST_SESSION_GROUPS = {
    "sleep": {
        "label": "Overnight Recovery",
        "score_title": "Sleep Score",
        "score_scope": "ค่าประเมินการนอนจาก Sensor",
        "description": "พักค้างคืนอย่างน้อย 5 ชั่วโมง; คะแนนเวลาสำหรับผู้ใหญ่เต็มที่ 7 ชั่วโมง",
        "sleep_required": True,
    },
    "nap_recovery": {
        "label": "Nap & Refresh",
        "score_title": "Recovery Score",
        "score_scope": "คะแนนสนับสนุนการฟื้นตัวจาก Sensor",
        "description": (
            "พักระหว่างวันตามเป้าหมาย 30 หรือ 90 นาที "
            "จะหลับ พักสายตา หรือทำสมาธิก็ได้"
        ),
        "sleep_required": False,
    },
}

# Two user-facing protocols are the only canonical Session goals.  The phase
# plan is metadata for UI, reports and test design; it does not permit Sleep
# State to drive actuators.  Environment changes remain clock/user controlled.
REST_MODE_PROTOCOLS = {
    "sleep": {
        "session_character": "sleep",
        "minimum_seconds": 5 * 3600,
        "maximum_seconds": None,
        "recommended_range_seconds": [7 * 3600, 9 * 3600],
        "full_credit_target_seconds": 7 * 3600,
        "phases": ["settle", "protected_sleep", "gentle_wake"],
        "primary_outcomes": [
            "sleep_onset", "sleep_continuity", "sleep_architecture",
            "wake_events", "morning_freshness",
        ],
    },
    "nap_recovery": {
        "session_character": "rest_or_nap",
        "minimum_seconds": NAP_RECOVERY_MINIMUM_SCORE_SECONDS,
        "maximum_seconds": NAP_RECOVERY_LEGACY_HARD_MAX_SECONDS,
        "recommended_range_seconds": [25 * 60, 35 * 60],
        "full_credit_target_seconds": NAP_RECOVERY_DEFAULT_TARGET_SECONDS,
        "supported_target_seconds": sorted(NAP_RECOVERY_TARGET_OPTIONS),
        "target_required_for_new_sessions": True,
        "legacy_missing_target_requires_review": True,
        "phases": ["settle", "rest_or_nap", "gentle_close"],
        "primary_outcomes": [
            "rest_continuity", "hr_rr_settling", "stillness",
            "sleep_observed_optional", "post_rest_refresh_self_report",
        ],
    },
}

# Historical values are normalised on read.  Raw records are not rewritten,
# preserving auditability while every new report exposes one of two goals.
REST_MODE_LEGACY_ALIASES = {
    "relax_meditation": "nap_recovery",
    "recovery_readiness": "nap_recovery",
    "performance_prep": "nap_recovery",
    "physical_comfort": "nap_recovery",
    "performance": "nap_recovery",
    "prepare": "nap_recovery",
    "comfort": "nap_recovery",
    "recovery": "nap_recovery",
    "meditation": "nap_recovery",
    "relax": "nap_recovery",
}


def rest_mode_group(value: Any) -> str | None:
    """Return a canonical public Session group without guessing ``auto``.

    This helper is intentionally stricter than the environment profile mapper:
    an unresolved historical value may use conservative sleep atmosphere bands,
    but it may not acquire a Sleep/Recovery score identity by implication.
    """
    mode = str(value or "auto").strip().lower()
    mode = REST_MODE_LEGACY_ALIASES.get(mode, mode)
    if mode in {"sleep", "overnight"}:
        return "sleep"
    if mode in {
        "nap_recovery",
        "general_rest",
        "short_nap",
        "cycle_nap",
        "shift_rest",
        "jet_lag",
    }:
        return "nap_recovery"
    return None


def is_approved_sleep_result_version(
    report_version: Any,
    quality_version: Any,
) -> bool:
    """Accept only reviewed version pairs for an explicit Overnight result."""
    return (
        str(report_version or ""),
        str(quality_version or ""),
    ) in APPROVED_SLEEP_RESULT_VERSION_PAIRS


def resolve_rest_target(
    rest_mode: Any,
    persisted_seconds: Any = None,
    *,
    use_mode_default: bool = False,
) -> dict[str, Any]:
    """Validate one persisted duration target without elapsed-time inference.

    New Sessions call this with ``use_mode_default=True`` before recording and
    persist the result. Historical reports call it with the stored value only;
    a missing/invalid target stays explicit and requires review.
    """
    group = rest_mode_group(rest_mode)
    if group is None:
        return {
            "available": False,
            "valid": False,
            "group": None,
            "seconds": None,
            "minutes": None,
            "source": "unresolved_mode",
            "review_required": True,
            "supported_seconds": [],
        }

    if group == "sleep":
        target = REST_MODE_PROTOCOLS["sleep"]["full_credit_target_seconds"]
        return {
            "available": True,
            "valid": True,
            "group": group,
            "key": "overnight_7h",
            "label": "Overnight Recovery · 7 ชั่วโมง",
            "seconds": target,
            "minutes": target / 60,
            "source": "persisted" if persisted_seconds is not None else "policy_default",
            "review_required": False,
            "supported_seconds": [target],
        }

    supported = sorted(NAP_RECOVERY_TARGET_OPTIONS)
    value = None
    if isinstance(persisted_seconds, (int, float)) and not isinstance(
        persisted_seconds, bool
    ):
        value = float(persisted_seconds)
    matched = next(
        (target for target in supported if value is not None and abs(value - target) <= 1),
        None,
    )
    source = "persisted"
    if matched is None and persisted_seconds is None and use_mode_default:
        requested = str(rest_mode or "").strip().lower()
        matched = (
            90 * 60
            if requested in {"cycle_nap", "shift_rest"}
            else NAP_RECOVERY_DEFAULT_TARGET_SECONDS
        )
        source = "policy_default_at_session_start"
    if matched is None:
        return {
            "available": False,
            "valid": persisted_seconds is None,
            "group": group,
            "seconds": None,
            "minutes": None,
            "source": (
                "legacy_missing" if persisted_seconds is None else "invalid_persisted"
            ),
            "review_required": True,
            "supported_seconds": supported,
        }

    option = NAP_RECOVERY_TARGET_OPTIONS[matched]
    return {
        "available": True,
        "valid": True,
        "group": group,
        "key": option["key"],
        "label": option["label"],
        "seconds": matched,
        "minutes": matched / 60,
        "source": source,
        "review_required": False,
        "supported_seconds": supported,
        "recommended_range_seconds": list(option["recommended_range_seconds"]),
        "extended_max_seconds": option["extended_max_seconds"],
    }

# Environment is an explanatory context layer, not Sleep-Stage evidence.  A
# value passes the ZEEP operating expectation at ``fair`` or above.  Internal
# keys stay stable for scoring and audit, while labels use calm product copy.
# Only ``poor`` and ``critical`` need action; ``critical`` here is a Wellness
# operating band and must not be presented as a life-safety alarm by itself.
# Independent life-safety alarms/clamps remain authoritative and are never
# relaxed by these wellness-mode profiles.
ENVIRONMENT_ACCEPTABLE_MIN_LEVEL = "fair"
ENVIRONMENT_LEVELS = {
    "critical": {
        "rank": 0, "label": "แนะนำให้ปรับตอนนี้", "english": "Critical", "symbol": "!",
        "decision": "required",
        "description": "พบค่าที่ควรตรวจและปรับสภาพแวดล้อมตอนนี้",
    },
    "poor": {
        "rank": 1, "label": "ควรปรับ", "english": "Poor", "symbol": "↓",
        "decision": "required",
        "description": "มีปัจจัยที่ควรปรับเพื่อให้พักสบายขึ้น",
    },
    "fair": {
        "rank": 2, "label": "พอใช้", "english": "Fair", "symbol": "–",
        "decision": "optimise",
        "description": "ใช้งานได้ และยังปรับให้สบายขึ้นได้",
    },
    "good": {
        "rank": 3, "label": "ดี", "english": "Good", "symbol": "✓",
        "decision": "maintain", "description": "เหมาะสมกับรูปแบบการพัก รักษาค่าปัจจุบัน",
    },
    "excellent": {
        "rank": 4, "label": "ยอดเยี่ยม", "english": "Excellent", "symbol": "★",
        "decision": "maintain", "description": "อยู่ในเป้าหมายสูงสุดของ ZEEP",
    },
}
ENVIRONMENT_SESSION_SUSTAINED_FLOOR_QUANTILE = 0.10


def summarize_environment_session_levels(level_keys: list[str]) -> dict[str, Any]:
    """Aggregate a Session without promoting one transient spike to its label.

    The Session level is the sustained lower decile of sample-level ranks. A
    peak remains explicit context for engineering review. Live life-safety
    controls continue to operate on current values and do not use this helper.
    """
    levels = [key for key in level_keys if key in ENVIRONMENT_LEVELS]
    if not levels:
        return {
            "available": False,
            "version": ENVIRONMENT_SESSION_AGGREGATION_VERSION,
            "status_key": "unavailable",
            "sample_count": 0,
        }
    ranks = sorted(ENVIRONMENT_LEVELS[key]["rank"] for key in levels)
    count = len(ranks)
    floor_index = max(
        0,
        min(
            count - 1,
            int(
                count * ENVIRONMENT_SESSION_SUSTAINED_FLOOR_QUANTILE
                + 0.999999
            ) - 1,
        ),
    )
    sustained_rank = ranks[floor_index]
    status_key = next(
        key
        for key, definition in ENVIRONMENT_LEVELS.items()
        if definition["rank"] == sustained_rank
    )
    peak_key = min(
        levels,
        key=lambda key: ENVIRONMENT_LEVELS[key]["rank"],
    )
    counts = {key: levels.count(key) for key in ENVIRONMENT_LEVELS}
    critical_count = counts["critical"]
    return {
        "available": True,
        "version": ENVIRONMENT_SESSION_AGGREGATION_VERSION,
        "method": "sustained_lower_decile_of_sample_levels",
        "quantile": ENVIRONMENT_SESSION_SUSTAINED_FLOOR_QUANTILE,
        "status_key": status_key,
        "rank": sustained_rank,
        "peak_status_key": peak_key,
        "sample_count": count,
        "level_counts": counts,
        "critical_sample_count": critical_count,
        "critical_sample_pct": round(100.0 * critical_count / count, 3),
        "transient_critical_observed": bool(
            critical_count and status_key != "critical"
        ),
    }

# Each list is ordered Excellent -> Good -> Fair -> Poor.  Values outside the
# last band are Critical.  Temperature, RH and air-quality bands remain common
# to all modes; light and sound reflect the selected experience.  These are
# versioned internal operating bands, not universal medical thresholds.
ENVIRONMENT_CONTEXT_CRITERIA = {
    "temperature": {
        "sample_key": "temp", "environment_key": "temperature_c",
        "device_key": "sht3x_dis", "source": "SHT3x-DIS",
        "label": "อุณหภูมิ", "unit": "°C", "digits": 1, "kind": "range",
        "bands": [[18.0, 27.0], [17.0, 28.0], [16.0, 29.0], [13.0, 32.0]],
        # Keep Safety provenance separate from the four Wellness bands.  These
        # values match the approved default Pi-local Safety Supervisor basis.
        "critical_below": 13.0,
        "critical_above": 32.0,
        "action_low": "เพิ่มอุณหภูมิที่เลือกหรือลดความเย็น",
        "action_high": "ลดอุณหภูมิที่เลือกหรือเปิดแอร์",
        "control": "เครื่องปรับอากาศ",
        "principle": "Thermal comfort จากอุณหภูมิจริงใน ZEEP",
    },
    "humidity": {
        "sample_key": "hum", "environment_key": "humidity_rh",
        "device_key": "sht3x_dis", "source": "SHT3x-DIS",
        "label": "ความชื้น", "unit": "%RH", "digits": 1, "kind": "range",
        "bands": [[40.0, 60.0], [35.0, 65.0], [30.0, 70.0], [20.0, 80.0]],
        "action_low": "เปิดไอน้ำเป็นช่วงและติดตามค่าความชื้น",
        "action_high": "ปิดไอน้ำและเพิ่มการระบายอากาศ",
        "control": "ไอน้ำ · ระบบระบายอากาศ",
        "principle": "ติดตามความแห้ง ความชื้นสะสม และการควบแน่น",
    },
    "light": {
        "sample_key": "lux", "environment_key": "lux",
        "device_key": "opt3001", "source": "OPT3001",
        "label": "ความสว่าง", "unit": "lux", "digits": 1, "kind": "upper",
        "mode_bands": {
            "sleep": [5.0, 10.0, 30.0, 100.0],
            "nap_recovery": [10.0, 30.0, 100.0, 300.0],
            "relax_meditation": [50.0, 150.0, 300.0, 500.0],
            "recovery_readiness": [300.0, 500.0, 750.0, 1000.0],
        },
        "action_high": "ลดแสงหรือเลือกฉากแสงให้ตรงกับโหมด",
        "control": "ไฟเพดาน · แสงแดง · ไฟดาว",
        "principle": "แสงที่เหมาะขึ้นกับการนอน งีบ ผ่อนคลาย หรือช่วงเตรียมพร้อม",
    },
    "sound": {
        "sample_key": "dba", "environment_key": "sound_dba_est",
        "device_key": "sph0645", "source": "SPH0645",
        "label": "เสียง", "unit": "dBA", "digits": 1, "kind": "upper",
        # Acoustic comfort remains visible and contributes whenever a valid
        # firmware LAeq(A) measurement exists. It is not a life-safety input,
        # so a missing/invalid microphone must degrade coverage without
        # blocking an otherwise usable Pod atmosphere assessment.
        "required_for_overall": False,
        "excellent_upper_exclusive": True,
        "mode_bands": {
            "sleep": [40.0, 45.0, 50.0, 60.0],
            "nap_recovery": [40.0, 45.0, 50.0, 60.0],
            "relax_meditation": [45.0, 50.0, 55.0, 65.0],
            "recovery_readiness": [50.0, 55.0, 60.0, 70.0],
        },
        "action_high": "ลดเสียงเพลงและตรวจพัดลม คอมเพรสเซอร์ หรือการสั่น",
        "control": "เสียงบรรยากาศ · พัดลม · คอมเพรสเซอร์",
        "principle": "แยกเสียงรบกวนจากเสียงที่ผู้ใช้เลือกตามวัตถุประสงค์ของโหมด",
    },
    "co2": {
        "sample_key": "co2", "environment_key": "co2_ppm",
        "device_key": "mhz19c", "source": "MH-Z19C",
        "label": "CO₂", "unit": "ppm", "digits": 0, "kind": "upper",
        "bands": [800.0, 1000.0, 1150.0, 1300.0],
        "critical_at_or_above": 1300.0,
        "action_high": "เพิ่มการเติมและระบายอากาศ พร้อมตรวจ Filter",
        "control": "พัดลมลมเข้า · พัดลมลมออก",
        "principle": "ตัวชี้การระบายอากาศ ไม่ใช่ค่าปริมาณออกซิเจน",
    },
    "pm25": {
        "sample_key": "pm2_5", "environment_key": "pm2_5_ug_m3",
        "device_key": "pms7003", "source": "PMS7003",
        "label": "PM2.5", "unit": "µg/m³", "digits": 1, "kind": "upper",
        "bands": [15.0, 25.0, 37.5, 50.0],
        "action_high": "ตรวจหรือเปลี่ยน Pre/HEPA Filter และตรวจรอยรั่ว",
        "control": "Pre-Filter · HEPA · ซีลประตู",
        "principle": "ติดตามฝุ่นละเอียด การกรอง และการรั่วของอากาศ",
    },
    "voc": {
        "sample_key": "voc", "environment_key": "voc_index",
        "device_key": "sgp40", "source": "SGP40",
        "label": "VOC Index", "unit": "", "digits": 0, "kind": "upper",
        "bands": [120.0, 150.0, 200.0, 300.0],
        "action_high": "หยุดแหล่งกลิ่น เร่งระบาย และตรวจ Carbon Filter",
        "control": "กลิ่น · พัดลมระบาย · Carbon Filter",
        "principle": "เทียบกับ Adaptive Baseline ของ SGP40 ซึ่งปรับตัวใกล้ 100",
    },
}

_ENVIRONMENT_MODE_ALIASES = {
    "auto": "sleep", "overnight": "sleep", "sleep": "sleep",
    "short_nap": "nap_recovery", "cycle_nap": "nap_recovery",
    "shift_rest": "nap_recovery", "jet_lag": "nap_recovery",
    "nap_recovery": "nap_recovery", "general_rest": "nap_recovery",
    **REST_MODE_LEGACY_ALIASES,
}


def environment_mode_group(value: Any) -> str:
    """Map historical/sub-mode names to one of the two Pilot profiles."""
    mode = str(value or "auto").strip().lower()
    mode = REST_MODE_LEGACY_ALIASES.get(mode, mode)
    return _ENVIRONMENT_MODE_ALIASES.get(mode, "sleep")


def environment_criterion(metric: str, rest_mode: Any) -> dict[str, Any]:
    """Return one JSON-safe criterion with its selected mode bands."""
    source = ENVIRONMENT_CONTEXT_CRITERIA[metric]
    result = dict(source)
    result["key"] = metric
    result["mode"] = environment_mode_group(rest_mode)
    selected = (source.get("mode_bands") or {}).get(result["mode"], source.get("bands"))
    result["selected_bands"] = [list(value) if isinstance(value, list) else value for value in selected]
    result.pop("mode_bands", None)
    return result


def environment_level_for_value(metric: str, value: float, rest_mode: Any) -> str:
    """Classify one live value against the selected internal operating bands."""
    criterion = environment_criterion(metric, rest_mode)
    bands = criterion["selected_bands"]
    if criterion.get("critical_at_or_above") is not None and value >= criterion["critical_at_or_above"]:
        return "critical"
    ordered_levels = ("excellent", "good", "fair", "poor")
    if criterion["kind"] == "range":
        for level, (minimum, maximum) in zip(ordered_levels, bands):
            if minimum <= value <= maximum:
                return level
    else:
        for index, (level, maximum) in enumerate(zip(ordered_levels, bands)):
            if index == 0 and criterion.get("excellent_upper_exclusive"):
                if value < maximum:
                    return level
            elif value <= maximum:
                return level
    return "critical"


def _environment_band_text(criterion: dict[str, Any], index: int) -> str:
    band = criterion["selected_bands"][index]
    unit = criterion.get("unit") or ""
    if criterion["kind"] == "range":
        return f"{band[0]:g}–{band[1]:g}{unit}"
    operator = "<" if index == 0 and criterion.get("excellent_upper_exclusive") else "≤"
    return f"{operator}{band:g}{(' ' + unit) if unit else ''}"


def environment_policy_snapshot(rest_mode: Any = "sleep") -> dict[str, Any]:
    """Expose the exact Mode-aware context baseline used by Live and reports."""
    mode = environment_mode_group(rest_mode)
    criteria = []
    for key in ENVIRONMENT_CONTEXT_CRITERIA:
        criterion = environment_criterion(key, mode)
        criterion["excellent_target"] = _environment_band_text(criterion, 0)
        criterion["acceptable_floor"] = _environment_band_text(criterion, 2)
        criterion["bands_text"] = " · ".join(
            f"{ENVIRONMENT_LEVELS[level]['label']} {_environment_band_text(criterion, index)}"
            for index, level in enumerate(("excellent", "good", "fair", "poor"))
        ) + " · แนะนำให้ปรับตอนนี้เมื่ออยู่นอกช่วง"
        criteria.append(criterion)
    return {
        "version": ENVIRONMENT_CONTEXT_POLICY_VERSION,
        "mode": mode,
        "requested_mode": str(rest_mode or "auto"),
        "auto_mode_policy": "conservative_sleep_until_resolved",
        "acceptable_min_level": ENVIRONMENT_ACCEPTABLE_MIN_LEVEL,
        "levels": [dict(ENVIRONMENT_LEVELS[key], key=key) for key in
                   ("critical", "poor", "fair", "good", "excellent")],
        "session_aggregation": {
            "version": ENVIRONMENT_SESSION_AGGREGATION_VERSION,
            "method": "sustained_lower_decile_of_sample_levels",
            "lower_quantile": ENVIRONMENT_SESSION_SUSTAINED_FLOOR_QUANTILE,
            "peak_retained_as_context": True,
            "changes_live_safety_logic": False,
        },
        "criteria": criteria,
        "direct_stage_influence": False,
        "changes_life_safety_thresholds": False,
    }


def assess_environment_values(
    environment: dict[str, Any],
    rest_mode: Any = "sleep",
    *,
    require_live_devices: bool = False,
) -> dict[str, Any]:
    """Assess current Pod values using the same policy as Session reports."""
    policy = environment_policy_snapshot(rest_mode)
    devices = environment.get("devices") if isinstance(environment.get("devices"), dict) else {}
    evaluations = []
    for criterion in policy["criteria"]:
        raw = environment.get(criterion["environment_key"])
        numeric = (
            isinstance(raw, (int, float)) and not isinstance(raw, bool)
        )
        device = devices.get(criterion["device_key"], {})
        live = numeric and (
            not require_live_devices or device.get("status") == "live"
        )
        base = {
            "id": criterion["key"], "key": criterion["key"],
            "name": criterion["label"], "label": criterion["label"],
            "device_key": criterion["device_key"], "source": criterion["source"],
            "unit": criterion["unit"], "digits": criterion["digits"],
            "target": criterion["excellent_target"],
            "expected_floor": criterion["acceptable_floor"],
            "bands": criterion["bands_text"], "principle": criterion["principle"],
            "control": criterion["control"],
            "required_for_overall": bool(
                criterion.get("required_for_overall", True)
            ),
        }
        if not live:
            # A restart cache may carry the last validated numeric value while
            # its device is deliberately marked stale. Keep that value visible
            # for continuity, but never assign a level, recommendation or
            # passing assessment until a fresh packet arrives.
            display = (
                f"{float(raw):.{criterion['digits']}f}"
                f"{(' ' + criterion['unit']) if criterion['unit'] else ''}"
                if numeric else "--"
            )
            evaluations.append({
                **base, "status": "unavailable",
                "device_status": device.get("status", "no_data"),
                "value": float(raw) if numeric else None, "display": display,
                "decision": "sensor_check", "score": None, "level": None,
            })
            continue
        value = float(raw)
        level_key = environment_level_for_value(criterion["key"], value, policy["mode"])
        level = dict(ENVIRONMENT_LEVELS[level_key], key=level_key)
        first_band = criterion["selected_bands"][0]
        if criterion["kind"] == "range":
            midpoint = (first_band[0] + first_band[1]) / 2.0
            recommendation = (
                criterion.get("action_high") if value > midpoint
                else criterion.get("action_low")
            )
        else:
            recommendation = criterion.get("action_high")
        if level["decision"] == "maintain":
            recommendation = "รักษาการตั้งค่าปัจจุบัน"
        evaluations.append({
            **base, "status": "live", "device_status": "live", "value": value,
            "score": level["rank"], "level": level, "decision": level["decision"],
            "meets_expected": level["rank"] >= ENVIRONMENT_LEVELS[ENVIRONMENT_ACCEPTABLE_MIN_LEVEL]["rank"],
            "display": f"{value:.{criterion['digits']}f}{(' ' + criterion['unit']) if criterion['unit'] else ''}",
            "recommendation": recommendation,
        })
    metrics = [item for item in evaluations if item["status"] == "live"]
    unavailable = [item for item in evaluations if item["status"] != "live"]
    blocking_unavailable = [
        item for item in unavailable if item["required_for_overall"]
    ]
    advisory_unavailable = [
        item for item in unavailable if not item["required_for_overall"]
    ]
    required = sorted(
        [item for item in metrics if item["decision"] == "required"],
        key=lambda item: item["score"],
    )
    optimise = [item for item in metrics if item["decision"] == "optimise"]
    blocking_missing_actions = [{
        "type": "sensor", "priority": "required", "name": item["name"],
        "current": "ไม่มีข้อมูล Live", "target": item["expected_floor"],
        "control": item["source"],
        "action": f"ตรวจการเชื่อมต่อ {item['source']} และ freshness ก่อนประเมิน",
        "blocks_overall": True,
    } for item in blocking_unavailable]
    advisory_actions = [{
        "type": "sensor", "priority": "advisory", "name": item["name"],
        "current": "ไม่มีข้อมูล Live", "target": item["expected_floor"],
        "control": item["source"],
        "action": f"ตรวจการเชื่อมต่อ {item['source']} โดยภาพรวมยังทำงานต่อ",
        "blocks_overall": False,
    } for item in advisory_unavailable]
    required_actions = [{
        "type": "condition", "priority": "required", "name": item["name"],
        "current": item["display"], "target": item["expected_floor"],
        "control": item["control"], "action": item["recommendation"],
        "score": item["score"],
    } for item in required] + blocking_missing_actions
    optimisation_actions = [{
        "type": "condition", "priority": "optimise", "name": item["name"],
        "current": item["display"], "target": item["target"],
        "control": item["control"], "action": item["recommendation"],
        "score": item["score"],
    } for item in optimise]
    if not metrics:
        return {
            **policy, "key": "unknown", "label": "รอข้อมูล", "english": "Waiting",
            "symbol": "?", "description": "Sensor ยังไม่พร้อมสำหรับประเมิน",
            "reason": f"รอข้อมูล Sensor {len(evaluations)} เกณฑ์",
            "metrics": metrics, "evaluations": evaluations,
            "required_actions": required_actions,
            "advisory_actions": advisory_actions,
            "optimisation_actions": optimisation_actions,
            "actions": required_actions + advisory_actions + optimisation_actions,
            "meets_expected": False,
            "assessment_quality": "insufficient",
            "required_count": len(required_actions),
            "advisory_count": len(advisory_actions),
            "available_factor_count": 0,
            "blocking_unavailable_count": len(blocking_unavailable),
            "optional_unavailable_count": len(advisory_unavailable),
            "optimisation_count": 0,
            "expected_factors": len(evaluations),
        }
    minimum = min(metrics, key=lambda item: item["score"])
    level = minimum["level"]
    # A missing required factor blocks a Good/Excellent claim. SPH0645 is an
    # optional acoustic input: its absence lowers coverage and stays visible
    # to Admin, but does not collapse the whole assessment to Unknown. A known
    # Poor/Critical value remains visible immediately in either case.
    unknown = bool(blocking_unavailable and minimum["score"] >= 2)
    if unknown:
        summary = {
            "key": "unknown", "label": "รอข้อมูล", "english": "Waiting", "symbol": "?",
            "description": "ข้อมูลไม่ครบ จึงยังยืนยันภาพรวมไม่ได้",
            "reason": (
                f"Sensor หลักพร้อม {len(metrics)}/{len(evaluations)} เกณฑ์ · "
                f"ตรวจ {blocking_unavailable[0]['source']}"
            ),
        }
    else:
        summary = dict(level)
        summary["reason"] = (
            f"แนะนำให้ปรับ {required[0]['name']} · {required[0]['recommendation']}"
            if required else
            f"ผ่านขั้นต่ำพอใช้ · ปรับเพิ่มได้ {optimise[0]['name']}"
            if optimise else
            f"ประเมินจาก {len(metrics)}/{len(evaluations)} เกณฑ์ · "
            f"{advisory_unavailable[0]['name']}ไม่มีข้อมูล แต่ไม่บล็อกภาพรวม"
            if advisory_unavailable else
            f"ครบ {len(metrics)}/{len(evaluations)} เกณฑ์ · รักษาค่าปัจจุบัน"
        )
    return {
        **policy, **summary, "score": minimum["score"],
        "metrics": metrics, "evaluations": evaluations,
        "limiting": [item for item in metrics if item["score"] == minimum["score"]],
        "required_actions": required_actions,
        "advisory_actions": advisory_actions,
        "optimisation_actions": optimisation_actions,
        "actions": required_actions + advisory_actions + optimisation_actions,
        "meets_expected": bool(not blocking_unavailable and not required),
        "assessment_quality": (
            "incomplete_required" if blocking_unavailable
            else "degraded_optional" if advisory_unavailable
            else "complete"
        ),
        "passed_expected_count": sum(bool(item.get("meets_expected")) for item in metrics),
        "required_count": len(required_actions),
        "advisory_count": len(advisory_actions),
        "available_factor_count": len(metrics),
        "blocking_unavailable_count": len(blocking_unavailable),
        "optional_unavailable_count": len(advisory_unavailable),
        "optimisation_count": len(optimisation_actions),
        "expected_factors": len(evaluations),
    }

SLEEP_QUALITY_COMPONENT_MAX_POINTS = {
    "sleep_opportunity": 20.0,
    "sleep_stability": 30.0,
    "restorative_architecture": 30.0,
    "cycle_expression": 15.0,
    "data_coverage": 5.0,
}

# Overnight restorative architecture is a transparent ZEEP wellness formula.
# It is not an AASM normative distribution. N3 is deliberately not penalised
# above 20%; full N3 credit starts at 10% and remains open-ended.
OVERNIGHT_ARCHITECTURE_MAX_POINTS = {"n2": 10.0, "n3": 12.0, "rem": 8.0}
OVERNIGHT_N2_FULL_CREDIT_PCT = (45.0, 75.0)
OVERNIGHT_N3_ZERO_BELOW_PCT = 3.0
OVERNIGHT_N3_FULL_CREDIT_FROM_PCT = 10.0
OVERNIGHT_REM_FULL_CREDIT_PCT = (15.0, 25.0)


def sleep_policy_snapshot() -> dict[str, Any]:
    """Return a JSON-safe manifest for tests, Admin inspection, and audits."""
    return {
        "versions": {
            "pipeline_contract": SLEEP_PIPELINE_CONTRACT_VERSION,
            "estimator": SLEEP_ESTIMATOR_VERSION,
            "evidence": SLEEP_EVIDENCE_VERSION,
            "baseline": ZEEP_SLEEP_BASELINE_VERSION,
            "transition": ZEEP_SLEEP_TRANSITION_POLICY_VERSION,
            "g2_ontology": SLEEP_G2_ONTOLOGY_VERSION,
            "historical_replay": SLEEP_HISTORY_BACKFILL_VERSION,
            "sleep_quality": SLEEP_QUALITY_VERSION,
            "sleep_score_formula": SLEEP_SCORE_FORMULA_VERSION,
            "session_report": SESSION_REPORT_VERSION,
            "restore_summary": RESTORE_SUMMARY_VERSION,
            "respiratory_wellness": RESPIRATORY_WELLNESS_VERSION,
            "restore_action_bands": RESTORE_ACTION_BANDS_VERSION,
            "restore_driver_policy": RESTORE_DRIVER_POLICY_VERSION,
            "restore_baseline_comparison": (
                RESTORE_BASELINE_COMPARISON_VERSION
            ),
            "restore_recommendation": RESTORE_RECOMMENDATION_VERSION,
            "environment_context": ENVIRONMENT_CONTEXT_POLICY_VERSION,
            "terminal_wake": TERMINAL_WAKE_POLICY_VERSION,
        },
        "states": list(ZEEP_SLEEP_STATES),
        "stage_presentation": {
            state: dict(SLEEP_STAGE_PRESENTATION[state])
            for state in ZEEP_SLEEP_STATES
        },
        "normal_transitions": {
            source: sorted(targets)
            for source, targets in SLEEP_ALLOWED_TRANSITIONS.items()
        },
        "prohibited_transitions": [
            list(edge) for edge in sorted(SLEEP_PROHIBITED_TRANSITIONS)
        ],
        "confirm_ticks": dict(SLEEP_STAGE_CONFIRM_TICKS),
        "confirmation_seconds_by_target": dict(SLEEP_STAGE_CONFIRMATION_SECONDS),
        "provisional_hold_epochs": SLEEP_PROVISIONAL_HOLD_EPOCHS,
        "cadence": {
            "sensor_sample_seconds": SLEEP_SENSOR_SAMPLE_SECONDS,
            "sensor_frames_per_evidence_epoch": SLEEP_SENSOR_FRAMES_PER_EPOCH,
            "evidence_epoch_seconds": SLEEP_EVIDENCE_EPOCH_SECONDS,
            "confirmation_epochs": SLEEP_CONFIRM_EPOCHS,
            "confirmation_seconds": SLEEP_CONFIRMATION_SECONDS,
            "confirmation_seconds_range": [
                min(SLEEP_STAGE_CONFIRMATION_SECONDS.values()),
                max(SLEEP_STAGE_CONFIRMATION_SECONDS.values()),
            ],
            "long_transition_context_seconds": SLEEP_LONG_CONTEXT_SECONDS,
            "detect_signal_gap_seconds": SLEEP_CONTEXT_RESET_GAP_SECONDS,
            "preserve_confirmed_context_after_signal_gap": True,
            "signal_gap_display": (
                "carry_previous_or_initial_wake_scoreable_low_confidence"
            ),
            "restart_same_session_display": (
                "last_confirmed_scoreable_continuity"
            ),
            "restart_display_hold_max_seconds": (
                SLEEP_RESTART_STATE_HOLD_SECONDS_DEFAULT
            ),
            "restart_display_persisted_as_stage": True,
            "full_context_reset_triggers": [
                "session_owner_change",
                "session_end",
            ],
            "confirmed_bed_exit_effect": "OFF display and new Wake cycle",
            "evidence_and_confirmed_state_separate": True,
            "safety_supervisor_seconds": 1.0,
        },
        "minimum_dwell_seconds": dict(SLEEP_STAGE_MIN_DWELL_SECONDS),
        "sleep_onset_guard": {
            "minimum_observation_seconds": SLEEP_ONSET_MIN_OBSERVATION_SECONDS,
            "maximum_movement_ratio": SLEEP_ONSET_MAX_MOVEMENT_RATIO,
            "minimum_downward_transition": SLEEP_ONSET_MIN_DOWNWARD_TRANSITION,
            "minimum_relative_sleep_support": SLEEP_ONSET_MIN_RELATIVE_SLEEP_SUPPORT,
            "maximum_hr_rise_bpm_per_min": SLEEP_ONSET_MAX_HR_RISE_BPM_PER_MIN,
            "maximum_rr_rise_per_min": SLEEP_ONSET_MAX_RR_RISE_PER_MIN,
            "initial_wake_score_support": SLEEP_ONSET_INITIAL_WAKE_SUPPORT,
            "confirmation_epochs_after_gate": SLEEP_CONFIRM_EPOCHS,
            "quiet_wake_defaults_to_wake": True,
            "hr_drop_or_downward_trend_required": True,
            "respiratory_regularity_is_supporting_evidence": True,
            "rr_rate_drop_is_mandatory": False,
            "time_alone_can_create_n1": False,
            "engineering_guard_not_aasm_rule": True,
        },
        "probability_filter": {
            "method": "ema_after_60s_rolling_features",
            "alpha": SLEEP_PROBABILITY_EMA_ALPHA,
            "candidate_switch_margin": SLEEP_PROBABILITY_SWITCH_MARGIN,
            "candidate_source": (
                "ema_with_gated_n1_onset_n2_progression_"
                "and_n3_current_evidence_override"
            ),
            "ema_role": "default_candidate_stability_and_display",
            "n2_current_evidence_override_requires_gate": True,
            "n2_current_evidence_override_from_stage": "n1",
            "n3_current_evidence_override_requires_gate": True,
            "display_winner_margin": SLEEP_DISPLAY_WINNER_MARGIN,
            "instant_strong_wake_bypass": False,
            "strong_wake_still_requires_confirmation": True,
            "score_budget_per_state": "0..1",
            "softmax_temperature": SLEEP_SCORE_SOFTMAX_TEMPERATURE,
            "minimum_winner": SLEEP_EVIDENCE_MIN_WINNER,
            "minimum_margin": SLEEP_EVIDENCE_MIN_MARGIN,
            "n3_gated_minimum_winner": SLEEP_N3_GATED_MIN_WINNER,
            "n3_gated_minimum_margin": SLEEP_N3_GATED_MIN_MARGIN,
            "ambiguous_evidence_action": (
                "carry_previous_scoreable_low_confidence"
            ),
            "initial_state_action": "anchor_W_on_first_occupied_epoch",
            "gate_role": "new_state_entry_only",
            "challenger_receives_stage_time_before_confirmation": False,
            "provisional_hold_enabled": False,
            "continuity_hold_score_eligible": True,
            "continuity_hold_personal_baseline_eligible": False,
            "hr_rr_fit_fusion": {
                "method": "gated_linear_pool_before_ema_and_semimarkov",
                "weight": SLEEP_HR_RR_FIT_FUSION_WEIGHT,
                "weight_when_confirmed_state_agrees": (
                    SLEEP_HR_RR_FIT_FUSION_AGREEMENT_WEIGHT
                ),
                "ineligible_stage_mass": 0.0,
                "can_bypass_stage_gate": False,
                "can_bypass_confirmation": False,
            },
        },
        "personal_baseline_learning": {
            "completed_final_summary_required": True,
            "quality_type_required": "sleep",
            "sleep_detected_required": True,
            "minimum_session_seconds": PERSONAL_BASELINE_MIN_SESSION_SECONDS,
            "minimum_detected_sleep_seconds": PERSONAL_BASELINE_MIN_DETECTED_SLEEP_SECONDS,
            "minimum_valid_hr_samples": PERSONAL_BASELINE_MIN_HR_SAMPLES,
            "minimum_nights": PERSONAL_BASELINE_MIN_NIGHTS,
            "rolling_max_nights": PERSONAL_BASELINE_MAX_NIGHTS,
            "learning_start_local_date": PERSONAL_BASELINE_LEARNING_START_LOCAL_DATE,
            "learning_start_timezone": PERSONAL_BASELINE_LEARNING_START_TIMEZONE,
            "learning_start_utc": PERSONAL_BASELINE_LEARNING_START_UTC,
            "awake_rest_sessions_excluded": True,
            "direct_stage_influence_enabled": (
                PERSONAL_BASELINE_STAGE_INFLUENCE_ENABLED
            ),
            "current_role": "report_and_confidence_context_only",
        },
        "strong_wake_override": True,
        "classification_gate": {
            # Lifecycle and confirmed occupancy delimit five-state output.
            # HR/RR/BCG quality gates control entry into a new State; temporary
            # evidence loss carries the current State at low confidence.
            "active_session_required": True,
            "recording_phase_required": True,
            "confirmed_occupied_bed_required": True,
            "fresh_current_hr_required": True,
            "fresh_current_rr_required": True,
            "hr_rr_same_packet_required": True,
            "off_bed_return_requires_same_packet_hr_rr_bcg": True,
            "durable_stage_event_confirms_occupied_return": True,
            "minimum_paired_window_coverage": SLEEP_MIN_PAIRED_VITAL_COVERAGE,
            "minimum_packets_per_10s_bucket": SLEEP_BUCKET_MIN_BCG_PACKETS,
            "minimum_waveform_sample_coverage": SLEEP_MIN_WAVEFORM_COVERAGE,
            "waveform_required_for_n2_n3_rem": True,
            "inactive_probabilities_zero": True,
            "inactive_stage_persistence": False,
            "hold_last_stage_when_inactive": False,
            "gate_controls_new_state_entry_only": True,
            "valid_on_bed_gate_failure_action": (
                "carry_previous_scoreable_low_confidence"
            ),
            "no_previous_state_action": "initial_awake_anchor",
            "occupied_epoch_always_has_five_state": True,
            "no_unclassified_during_occupied_recording": True,
            "continuity_carry_score_eligible": True,
            "continuity_carry_personal_baseline_eligible": False,
            "evidence_event_type": "sleep_stage_evidence",
            "confirmed_state_event_type": "sleep_stage",
        },
        "report_gap_policy": {
            "operational_gaps_visible": True,
            "minimum_gap_seconds": 15.0,
            "labels": ["off_bed", "no_session"],
            "counted_as_sleep_stage": False,
            "counted_in_score": False,
            "temporary_evidence_loss_action": (
                "carry_previous_or_initial_wake"
            ),
            "temporary_evidence_loss_counted_in_score": True,
            "ambiguous_valid_epoch_is_gap": False,
        },
        "signal_roles": {
            "primary_stage_evidence": [
                "lsm800t_bcg_waveform",
                "fresh_heart_rate_summary",
                "fresh_respiration_rate_summary",
                "confirmed_bed_occupancy",
                "bed_movement_context",
            ],
            "bounded_corroboration": ["sph0645_time_aligned_sound"],
            "explanatory_environment_only": [
                "temperature", "humidity", "co2", "lux", "pm2_5", "voc_index",
            ],
            "environment_can_create_stage": False,
            "temporary_missing_hr_rr_result": (
                "carry_previous_or_initial_wake"
            ),
            "confirmed_no_occupancy_result": "off_bed_no_sleep_stage",
        },
        "movement_guard": {
            "brief_on_bed_max_ratio": 0.25,
            "brief_on_bed_max_consecutive_analysis_frames": 2,
            "sustained_on_bed_min_ratio": 0.35,
            "sustained_on_bed_min_consecutive_analysis_frames": 3,
            "strong_wake_requires_vital_rise_and_bcg_shift": True,
            "bed_exit_direct_wake": False,
            # Bed exit is an occupancy/safety result, not a sleep stage.  It
            # therefore stops classification without manufacturing a Wake
            # epoch.  A completed report records the exit on its own timeline.
            "bed_exit_direct_wake_after_confirmation": False,
            "bed_exit_operational_result": "off_bed_no_sleep_stage",
            "bed_exit_confirm_consecutive_analysis_buckets": 3,
            "bed_exit_confirm_raw_packets": 5,
            "bed_exit_confirm_raw_ratio": 0.8,
            "bed_exit_raw_packet_confirmation_enabled": False,
            "isolated_mid_session_bed_exit_is_transient": True,
            "raw_bed_label_can_latch_off_bed": False,
            "off_bed_latch_sources": [
                "confirmed_bed_exit_evidence",
                "canonical_off_bed_status_event",
            ],
            "off_bed_return_requires_affirmative_on_bed_status": True,
            "off_bed_return_requires_same_packet_hr_rr_bcg": True,
            "durable_stage_event_confirms_occupied_return": True,
            "terminal_single_bed_exit_counts_in_completed_report": True,
            # Missing physiology alone remains no-classification. A completed
            # report may connect that gap to a later confirmed terminal exit,
            # but keeps the result in an Occupancy timeline outside Sleep %.
            "terminal_exit_sequence_separate_from_sleep_stage": True,
            "terminal_exit_requires_no_returning_valid_hr_rr": True,
            "terminal_wake_boundary_before_exit_or_end": True,
            "terminal_wake_boundary_duration_seconds": 0.0,
            "terminal_wake_boundary_counted_as_sleep_stage": False,
            "terminal_wake_boundary_counted_in_score": False,
            "anatomy_or_blanket_identification": False,
        },
        "rest_mode_duration_targets_seconds": dict(REST_MODE_DURATION_TARGETS_S),
        "rest_session_groups": {
            key: dict(value) for key, value in REST_SESSION_GROUPS.items()
        },
        "rest_mode_protocols": {
            key: dict(value) for key, value in REST_MODE_PROTOCOLS.items()
        },
        "nap_recovery_targets": {
            str(seconds): dict(value, seconds=seconds)
            for seconds, value in NAP_RECOVERY_TARGET_OPTIONS.items()
        },
        "recovery_score": {
            "formula_version": RECOVERY_SCORE_FORMULA_VERSION,
            "component_max_points": dict(
                RECOVERY_SCORE_COMPONENT_MAX_POINTS
            ),
            "coverage_is_score_component": False,
            "sleep_required": False,
        },
        "sleep_score": {
            "formula_version": SLEEP_SCORE_FORMULA_VERSION,
            "component_max_points": dict(
                SLEEP_QUALITY_COMPONENT_MAX_POINTS
            ),
            "sleep_required": True,
        },
        "restore_summary": {
            "version": RESTORE_SUMMARY_VERSION,
            "action_bands_version": RESTORE_ACTION_BANDS_VERSION,
            "driver_policy_version": RESTORE_DRIVER_POLICY_VERSION,
            "baseline_comparison_version": (
                RESTORE_BASELINE_COMPARISON_VERSION
            ),
            "recommendation_version": RESTORE_RECOMMENDATION_VERSION,
            "creates_independent_score": False,
            "source_scores": {
                "sleep": "Sleep Score",
                "nap_recovery": "Recovery Score",
            },
            "whole_day_readiness": False,
            "automatic_actuation": False,
            "personal_comparison_minimum_sessions": (
                RESTORE_BASELINE_MIN_COMPARISON_SESSIONS
            ),
            "personal_baseline_stable_from_sessions": (
                RESTORE_BASELINE_STABLE_SESSIONS
            ),
            "trend_max_sessions": RESTORE_TREND_MAX_SESSIONS,
        },
        "rest_mode_legacy_aliases": dict(REST_MODE_LEGACY_ALIASES),
        "environment_context": environment_policy_snapshot("sleep"),
        "score_component_max_points": dict(SLEEP_QUALITY_COMPONENT_MAX_POINTS),
        "overnight_architecture": {
            "max_points": dict(OVERNIGHT_ARCHITECTURE_MAX_POINTS),
            "n2_full_credit_pct": list(OVERNIGHT_N2_FULL_CREDIT_PCT),
            "n3_zero_below_pct": OVERNIGHT_N3_ZERO_BELOW_PCT,
            "n3_full_credit_from_pct": OVERNIGHT_N3_FULL_CREDIT_FROM_PCT,
            "n3_upper_penalty": False,
            "rem_full_credit_pct": list(OVERNIGHT_REM_FULL_CREDIT_PCT),
        },
        "claim_boundary": {
            "intended_use": "exploratory_wellness_telemetry",
            "aasm_psg_equivalent": False,
            "validated_ibi_hrv": False,
            "environment_direct_stage_influence": False,
            "actuator_trigger": False,
        },
        "research_alignment": {
            "aasm_reference_output_classes": ["W", "N1", "N2", "N3", "R"],
            "aasm_scoring_requires_eeg_eog_emg": True,
            "zeep_is_aasm_scoring": False,
            "bcg_validation_reference": "Kortelainen et al. 2010, DOI 10.1109/TITB.2010.2044797",
            "bcg_reference_scope": "BCG/HBI and movement can support estimation but must be validated against PSG",
            "transition_graph_is_engineering_hysteresis_not_aasm_rule": True,
            "five_second_output_is_not_aasm_epoch": True,
        },
    }
