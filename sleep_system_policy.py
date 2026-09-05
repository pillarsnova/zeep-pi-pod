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
SLEEP_PIPELINE_CONTRACT_VERSION = "zeep-sleep-health-pipeline-v1.9-restart-continuity"
SLEEP_ESTIMATOR_VERSION = "bcg-audio-bed-5state-v1.26-fit-continuity-35"
SLEEP_EVIDENCE_VERSION = "zeep-sleep-state-evidence-v3.4-fit-continuity-35"
ZEEP_SLEEP_BASELINE_VERSION = "zeep-sleep-state-baseline-v1.8-sep1-cutover"
ZEEP_SLEEP_TRANSITION_POLICY_VERSION = "zeep-semimarkov-30s-v1.15-restart-continuity"
SLEEP_G2_ONTOLOGY_VERSION = "g2-aasm-5class-v1.0"
SLEEP_HISTORY_BACKFILL_VERSION = (
    "zeep-sleep-history-reclass-v25-fit-continuity-35"
)
SESSION_REPORT_VERSION = "zeep-session-report-v10.3-nap-goal-duration"
SLEEP_QUALITY_VERSION = "zeep-rest-quality-v8.3-nap-goal-duration"
ENVIRONMENT_CONTEXT_POLICY_VERSION = "zeep-environment-context-v2.0-mode-aware-fair-floor"
TERMINAL_WAKE_POLICY_VERSION = "zeep-terminal-wake-boundary-v1.0"
SLEEP_CLASSIFICATION_GAP_VERSION = (
    "zeep-sleep-classification-gap-v1.3-operational-restart-hold"
)


ZEEP_SLEEP_STATES = ("wake", "n1", "n2", "n3", "rem")

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
        "meaning": "รูปแบบ BCG/HR/RR ที่สอดคล้องกับ N3; ตามสรีรวิทยาการนอน N3 เชื่อมโยงกับการฟื้นฟู แต่ ZEEP ไม่ได้วัดการซ่อมแซมโดยตรง",
    },
    "rem": {
        "code": "REM",
        "title": "ระยะ REM",
        "meaning": "รูปแบบ BCG/HR/RR ที่สอดคล้องกับ REM; ตามสรีรวิทยา REM สัมพันธ์กับความฝันและความจำ แต่ ZEEP ไม่ได้วัดความฝันหรือความจำโดยตรง",
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
# window. EMA remains the default continuity source for Wake/N1/N2/REM. A
# current N3 winner may bypass EMA only when the strict physiology gate and the
# normal winner margin both pass; the semi-Markov guard then still requires two
# consecutive evidence epochs (60 seconds). This targeted exception prevents
# duplicate historical inertia from making valid N3 runs unreachable without
# making the other states more reactive. These are engineering controls, not
# AASM/PSG scoring criteria.
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
# Backward-compatible constant name: this threshold detects a discontinuity
# between valid classification windows. It no longer resets the confirmed
# Sleep State/onset for the same active Session; only pending evidence is reset.
SLEEP_CONTEXT_RESET_GAP_SECONDS = 60.0
# Display-only grace period after the same active Session is restored.  No held
# label is persisted or counted, and confirmed Bed Exit overrides it at once.
SLEEP_RESTART_STATE_HOLD_SECONDS_DEFAULT = 180.0
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
        "description": "พักระหว่างวันประมาณ 30 นาที จะหลับ พักสายตา หรือทำสมาธิก็ได้",
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
        "minimum_seconds": None,
        "maximum_seconds": 45 * 60,
        "recommended_range_seconds": [25 * 60, 35 * 60],
        "full_credit_target_seconds": 30 * 60,
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

# Environment is an explanatory context layer, not Sleep-Stage evidence.  A
# value passes the ZEEP operating expectation at ``fair`` or above.  Only
# ``poor`` and ``critical`` require correction; ``fair`` is usable but worth
# optimising, while ``good`` and ``excellent`` should simply be maintained.
# Independent life-safety alarms/clamps remain authoritative and are never
# relaxed by these wellness-mode profiles.
ENVIRONMENT_ACCEPTABLE_MIN_LEVEL = "fair"
ENVIRONMENT_LEVELS = {
    "critical": {
        "rank": 0, "label": "วิกฤต", "english": "Critical", "symbol": "!",
        "decision": "required", "description": "ต้องตรวจสาเหตุและแก้ไขทันที",
    },
    "poor": {
        "rank": 1, "label": "แย่", "english": "Poor", "symbol": "↓",
        "decision": "required", "description": "ต่ำกว่าระดับที่คาดหวัง ต้องแก้ไข",
    },
    "fair": {
        "rank": 2, "label": "พอใช้", "english": "Fair", "symbol": "–",
        "decision": "optimise", "description": "ผ่านขั้นต่ำ ใช้งานได้และควรติดตามแนวโน้ม",
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
        ) + " · วิกฤตนอกช่วง"
        criteria.append(criterion)
    return {
        "version": ENVIRONMENT_CONTEXT_POLICY_VERSION,
        "mode": mode,
        "requested_mode": str(rest_mode or "auto"),
        "auto_mode_policy": "conservative_sleep_until_resolved",
        "acceptable_min_level": ENVIRONMENT_ACCEPTABLE_MIN_LEVEL,
        "levels": [dict(ENVIRONMENT_LEVELS[key], key=key) for key in
                   ("critical", "poor", "fair", "good", "excellent")],
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
    required = sorted(
        [item for item in metrics if item["decision"] == "required"],
        key=lambda item: item["score"],
    )
    optimise = [item for item in metrics if item["decision"] == "optimise"]
    missing_actions = [{
        "type": "sensor", "priority": "required", "name": item["name"],
        "current": "ไม่มีข้อมูล Live", "target": item["expected_floor"],
        "control": item["source"],
        "action": f"ตรวจการเชื่อมต่อ {item['source']} และ freshness ก่อนประเมิน",
    } for item in unavailable]
    required_actions = [{
        "type": "condition", "priority": "required", "name": item["name"],
        "current": item["display"], "target": item["expected_floor"],
        "control": item["control"], "action": item["recommendation"],
        "score": item["score"],
    } for item in required] + missing_actions
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
            "optimisation_actions": optimisation_actions,
            "actions": required_actions + optimisation_actions,
            "meets_expected": False,
        }
    minimum = min(metrics, key=lambda item: item["score"])
    level = minimum["level"]
    # Missing data blocks a Good/Excellent claim. A known Poor/Critical value
    # remains visible immediately instead of being hidden behind Unknown.
    unknown = bool(unavailable and minimum["score"] >= 2)
    if unknown:
        summary = {
            "key": "unknown", "label": "รอข้อมูล", "english": "Waiting", "symbol": "?",
            "description": "ข้อมูลไม่ครบ จึงยังยืนยันภาพรวมไม่ได้",
            "reason": f"Sensor พร้อม {len(metrics)}/{len(evaluations)} เกณฑ์ · ตรวจ {unavailable[0]['source']}",
        }
    else:
        summary = dict(level)
        summary["reason"] = (
            f"ต้องแก้ {required[0]['name']} · {required[0]['recommendation']}"
            if required else
            f"ผ่านขั้นต่ำพอใช้ · ปรับเพิ่มได้ {optimise[0]['name']}"
            if optimise else
            f"ครบ {len(metrics)}/{len(evaluations)} เกณฑ์ · รักษาค่าปัจจุบัน"
        )
    return {
        **policy, **summary, "score": minimum["score"],
        "metrics": metrics, "evaluations": evaluations,
        "limiting": [item for item in metrics if item["score"] == minimum["score"]],
        "required_actions": required_actions,
        "optimisation_actions": optimisation_actions,
        "actions": required_actions + optimisation_actions,
        "meets_expected": bool(not unavailable and not required),
        "passed_expected_count": sum(bool(item.get("meets_expected")) for item in metrics),
        "required_count": len(required_actions),
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
            "session_report": SESSION_REPORT_VERSION,
            "environment_context": ENVIRONMENT_CONTEXT_POLICY_VERSION,
            "terminal_wake": TERMINAL_WAKE_POLICY_VERSION,
            "classification_gap": SLEEP_CLASSIFICATION_GAP_VERSION,
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
            "signal_gap_display": "WAIT/no_data",
            "restart_same_session_display": "last_confirmed_display_only",
            "restart_display_hold_max_seconds": (
                SLEEP_RESTART_STATE_HOLD_SECONDS_DEFAULT
            ),
            "restart_display_persisted_as_stage": False,
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
            "candidate_source": "ema_with_gated_n1_onset_and_n3_current_evidence_override",
            "ema_role": "default_candidate_stability_and_display",
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
            "ambiguous_evidence_action": "abstain_without_stage_persistence",
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
            # These are hard preconditions, not confidence penalties. When any
            # condition fails the live response is an operational status
            # (no_data/off_bed), all five probabilities are zero, and no stage
            # event is persisted.
            "active_session_required": True,
            "recording_phase_required": True,
            "confirmed_occupied_bed_required": True,
            "fresh_current_hr_required": True,
            "fresh_current_rr_required": True,
            "hr_rr_same_packet_required": True,
            "minimum_paired_window_coverage": SLEEP_MIN_PAIRED_VITAL_COVERAGE,
            "minimum_packets_per_10s_bucket": SLEEP_BUCKET_MIN_BCG_PACKETS,
            "minimum_waveform_sample_coverage": SLEEP_MIN_WAVEFORM_COVERAGE,
            "waveform_required_for_n2_n3_rem": True,
            "inactive_probabilities_zero": True,
            "inactive_stage_persistence": False,
            "hold_last_stage_when_inactive": False,
            "evidence_event_type": "sleep_stage_evidence",
            "confirmed_state_event_type": "sleep_stage",
        },
        "report_gap_policy": {
            "unclassified_periods_visible": True,
            "minimum_gap_seconds": 15.0,
            "labels": ["off_bed", "missing_vitals", "sensor_gap", "confirming"],
            "counted_as_sleep_stage": False,
            "counted_in_score": False,
            "fills_with_adjacent_stage": False,
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
            "missing_hr_rr_or_occupancy_result": "no_classification",
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
