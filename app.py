"""ZEEP Pod Raspberry Pi 5 composition root.

Domain rules remain in reviewable modules without hardware import side effects.
"""

import asyncio
import json
import math
import os
import secrets
import shutil
import socket
import subprocess
import threading
import time
import uuid
from collections import deque
from collections.abc import Mapping
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
import serial

try:
    import paho.mqtt.client as mqtt

    MQTT_AVAILABLE = True
except Exception:
    mqtt = None
    MQTT_AVAILABLE = False
from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Request,
    Response,
    Security,
)
from fastapi.security import APIKeyCookie
from fastapi.staticfiles import StaticFiles
from api.fleet import create_fleet_router
from api.history import create_history_router
from api.live_websocket import create_live_websocket_router
from api.control_routes import create_control_router
from api.models import (
    ActiveSessionProfileCommand,
    AdminLoginCommand,
    AirconCommand,
    AirconFanLevelReferenceCommand,
    AuthLoginCommand,
    BedControlCommand,
    ForceLogoutCommand,
    LabelCommand,
    LoginCommand,
    ProgressiveProfileAnswerCommand,
    ProgressiveProfileConsentCommand,
    ProgressiveProfileDeferCommand,
    SensorBiasCommand,
)
from access_control import COOKIE_NAME, CSRF_COOKIE_NAME, AuthSessionManager, Principal
from backup import DailyBackup
from bcg_storage import BCGStorage
from brainwave_audio import public_presets as brainwave_public_presets
from brainwave_audio import render_preview as render_brainwave_preview
from control_protocol import (
    AIRCON_TEMPERATURE_MAX_C,
    AIRCON_TEMPERATURE_MIN_C,
    normalize_aircon_command,
    normalize_bed_command,
    resolve_aircon_temperature_command,
)
from database import DatabaseManager
from api.v1 import create_api_v1_router
from api.shell_routes import create_shell_router
from acoustics import build_acoustic_monitor_snapshot, live_timeline_reader
from adaptive.learning import build_adaptive_learning_snapshot
from api.state_projection import (
    LiveDeviceProjectionPolicy,
    project_consumer_snapshot,
    project_live_device_statuses,
)
from identity.account_aliases import verified_alias_mapping
from identity.account_erasure_api import create_account_erasure_router
from identity.lifecycle_lock import synchronized_by
from identity.startup_migration import migrate_identity_stores
from identity.profile_fields import (
    health_reference_from_profile as build_health_reference,
    normalise_blood_group as _normalise_blood_group,
    normalise_body_measurement as _normalise_body_measurement,
    normalise_date_of_birth as _normalise_date_of_birth,
    normalize_account_key as _normalize_account_key,
    normalize_email as _normalize_email,
    normalize_username as _normalize_username,
    zeep_health_reference as _zeep_health_reference,
)
from identity.zeep_account import authenticate_password, identity_from_auth_data
from hardware.aircon_reference import AirconFanReferenceStore
from hardware.audio import AudioPlayer, default_music_state
from hardware.audio_api import AudioControlService, create_audio_router
from hardware.bcg import (
    BCGPacketPublisher,
    BCGPublicationPorts,
    BCGReaderConfig,
    BCGReaderPorts,
    LSM800TReader,
)
from hardware.controlhub1 import ControlHub1MQTT, configure_controlhub1
from hardware.controlhub2 import ControlHub2BedMQTT, configure_controlhub2
from hardware.bed_motion import MOVEMENT_COMMANDS
from hardware.gpio import GPIOManager
from hardware.fleet_health import local_pod_health
from hardware.sensorhub2 import run_sensorhub2_reader
from safety.faults import SafetyThresholds, evaluate_safety_faults
from hardware.sensorhub1 import (
    SensorHub1Reader,
    SensorHub1StateStore,
)
from sessions.cadence import (
    cadence_interval_at as _cadence_interval_at,
    normalise_cadence_segments as _normalise_cadence_segments,
    normalise_samples_for_report as _normalise_samples_for_report,
    sample_interval_seconds as _sample_interval_seconds_impl,
    timeline_sample_interval as _timeline_sample_interval,
)
from sessions.finalization_commit import (
    FinalizationPorts,
    commit_live_session_finalization as commit_session_finalization,
)
from sessions.finalization import SessionFinalizer
from sessions.finalization_contracts import FinalizationPolicy, SessionFinalizationPorts
from sessions.live_sleep_estimator import (
    estimate_sleep_state as _estimate_sleep_state_impl,
)
from sessions.live_sleep_runtime import LiveSleepRuntime
from sessions.lifecycle import (
    SESSION_CHECKPOINT_VERSION,
    SessionCheckpointStore,
    bed_is_occupied,
    evaluate_vital_start_gate,
)
from sessions.live_projection import (
    LiveSessionProjection,
    inactive_session_projection,
)
from sessions.live_sampler import LiveSamplerPorts, LiveSessionSampler
from sessions.recording_start import RecordingStartPorts, begin_recording
from sessions.restart import SessionRestarter
from sessions.restart_contracts import RestartPolicy, RestartPorts
from sessions.start import SessionStarter
from sessions.start_contracts import (
    SessionStartRejected,
    StartPolicy,
    StartPorts,
    StartRequest,
)
from sessions.sleep_context import (
    checkpoint_sleep_context,
    restore_session_sleep_context,
)
from sessions.history import (
    session_availability_by_account,
    users_ordered_by_latest_session as _users_ordered_by_latest_session,
)
from sessions.history_service import SessionHistoryService, local_history_day
from sessions.history_service import resolve_history_window, safe_account_profile
from sessions.history_quality import (
    released_historical_quality as _released_historical_quality,
)
from sessions import history_detail_support as history_support
from sessions import respiratory_evidence as rr_evidence
from sessions.history_sleep_timeline import (
    clip_history_sleep_timeline as _clip_history_sleep_timeline,  # noqa: F401
    compress_sleep_stage_points as _compress_sleep_stage_points,  # noqa: F401
    history_sleep_timeline as _history_sleep_timeline,  # noqa: F401
)
from sessions import report_projection
from sessions.ingest_payload import (
    build_ingest_payload as _build_account_ingest_payload,
)
from sessions.ingest_outbox import IngestOutbox
from sessions.sleep_between_epochs import (
    between_evidence_epoch_value,
    current_frame_issue,
    sensor_frame_wait_value,
)
from sessions.sensor_frame_sampler import (
    SensorFramePolicy,
    SensorFrameRuntime,
    SensorFrameSampler,
)
from sessions.sleep_runtime_evidence import (
    baseline_interval_proximity as _baseline_interval_proximity,
    sleep_auxiliary_evidence as _build_sleep_auxiliary_evidence,
    sleep_environment_context as _build_sleep_environment_context,
    sleep_status_event as _build_sleep_status_event,
)
from sessions.sleep_transition_state import (
    stabilize_path_transition,
    transition_allowed as _path_transition_allowed,
    transition_fallback_state as _path_transition_fallback_state,
)
from sessions.report_share import ReportShareRegistry, create_report_share_router
from sessions.usage_api import create_usage_sessions_router
from sessions.user_baseline_context import rest_window
from api.legacy_control_routes import create_legacy_control_router
from maintenance_registry import maintenance_contract_snapshot
from migration import migrate_jsonl
from personal import BaselineStore
from qr_login import QrLoginRegistry, create_qr_login_router
from profile_completion import PendingProfileRegistry, create_profile_completion_router, require_complete_profile
from progressive_profile import (
    admin_progress_summary,
    apply_answer as apply_progressive_answer,
    defer_question as defer_progressive_question,
    delete_answer as delete_progressive_answer,
    public_snapshot as progressive_profile_snapshot,
    session_context_snapshot,
    set_consent as set_progressive_consent,
)
from pod_occupancy import (
    CoordinatorUnavailable,
    OccupancyConflict,
    OccupancyLease,
    OccupancyStore,
    build_occupancy_client,
    create_occupancy_router,
    pod_id_from_env,
)
from hardware.pulse_control import PulseControlService
from sensors.contracts import (
    ENVIRONMENT_DEVICE_SPECS,
    SOUND_DBA_DISPLAY_MAX,
    SOUND_DBA_DISPLAY_MIN,
    decode_hub_payload,
    parse_lsm800t_frame,
    sensor_contract_snapshot,
)
from sensors.calibration import (
    SENSOR_CALIBRATION_SPECS,
    apply_additive_bias,
    load_calibration,
    persist_calibration,
    resolve_biases,
    sound_inspector_channel,
)
from sensors.runtime import (
    compose_environment_snapshot,
    energy_average_db,
    hold_last_valid_sound as hold_sound_value,
    normalize_hub1_sensor,
    summarize_sound_window,
    valid_sound_level,
)
from smart_response import (
    SmartResponsePolicy,
    evaluate_smart_response,
)
from sleep_signal_features import (
    BCG_SAMPLE_RATE_HZ,
    HR_SANITY_RANGE_BPM,
    RR_SANITY_RANGE_PER_MIN,
    arousal_proxy_evidence,
    bed_exit_window_evidence,
    debounced_bed_status_labels,
    filter_vital_values,
    movement_window_metrics,
    summary_features,
    waveform_features,
)
from sleep_stage_scoring import (
    align_probabilities_to_emitted_stage,
    candidate_from_stage_evidence,
    evidence_candidate_with_abstention,
    fuse_hr_rr_fit_with_stage_probabilities,
    interpret_baseline_fit,
    score_sleep_evidence,
    softmax_stage_evidence,
    smooth_stage_probabilities,
    stable_probability_candidate,  # noqa: F401
)
from sleep_stage_annotations import apply_annotations, load_annotations
from sleep_session_report import (
    build_session_report,
    build_sleep_quality,
    normalise_rest_mode,
)
from sleep_system_policy import (
    AGE_GROUP_DEFAULT_AGE,
    AGE_SLEEP_BASELINES,
    ENVIRONMENT_CONTEXT_POLICY_VERSION,
    GENDER_BASELINE_ADJUSTMENTS,
    PERSONAL_BASELINE_LEARNING_START_UTC,
    SESSION_REPORT_VERSION,
    SLEEP_ALLOWED_TRANSITIONS,
    SLEEP_ESTIMATOR_VERSION,
    SLEEP_EVIDENCE_VERSION,
    SLEEP_STAGE_CONFIRMATION_SECONDS,
    SLEEP_G2_ONTOLOGY_VERSION,
    SLEEP_DISPLAY_WINNER_MARGIN,
    SLEEP_DEFAULT_ACOUSTIC_DISTURBANCE_DBA,
    SLEEP_DEFAULT_ACOUSTIC_MIN_COVERAGE,
    SLEEP_DEFAULT_ACOUSTIC_WAKE_SUPPORT_MAX,
    SLEEP_DEFAULT_BASELINE_HR_WEIGHT,
    SLEEP_DEFAULT_BASELINE_RR_WEIGHT,
    SLEEP_DEFAULT_HR_CV_DEEP,
    SLEEP_DEFAULT_HR_CV_REM,
    SLEEP_DEFAULT_MOVE_DEEP_RATIO,
    SLEEP_DEFAULT_MOVE_WAKE_RATIO,
    SLEEP_DEFAULT_N2_RR_CONFLICT_SUPPORT,
    SLEEP_DEFAULT_N3_RR_CONFLICT_PENALTY,
    SLEEP_CONFIRMATION_SECONDS,
    SLEEP_CONFIRM_EPOCHS,
    SLEEP_CONTEXT_RESET_GAP_SECONDS,
    SLEEP_EVIDENCE_EPOCH_SECONDS,
    SLEEP_EVIDENCE_MIN_MARGIN,
    SLEEP_EVIDENCE_MIN_WINNER,
    SLEEP_HR_RR_FIT_FUSION_AGREEMENT_WEIGHT,
    SLEEP_HR_RR_FIT_FUSION_WEIGHT,
    SLEEP_LONG_CONTEXT_SECONDS,
    SLEEP_BUCKET_MIN_BCG_PACKETS,
    SLEEP_MIN_PAIRED_VITAL_COVERAGE,
    SLEEP_MIN_WAVEFORM_COVERAGE,
    SLEEP_N3_GATED_MIN_MARGIN,
    SLEEP_N3_GATED_MIN_WINNER,
    SLEEP_PROBABILITY_EMA_ALPHA,
    SLEEP_PROBABILITY_SWITCH_MARGIN,
    SLEEP_PROVISIONAL_HOLD_EPOCHS,
    SLEEP_RESTART_STATE_HOLD_SECONDS_DEFAULT,
    SLEEP_ONSET_INITIAL_WAKE_SUPPORT,
    SLEEP_ONSET_MAX_HR_RISE_BPM_PER_MIN,
    SLEEP_ONSET_MAX_MOVEMENT_RATIO,
    SLEEP_ONSET_MAX_RR_RISE_PER_MIN,
    SLEEP_ONSET_MIN_DOWNWARD_TRANSITION,
    SLEEP_ONSET_MIN_RELATIVE_SLEEP_SUPPORT,
    SLEEP_ONSET_MIN_OBSERVATION_SECONDS,
    SLEEP_SENSOR_FRAMES_PER_EPOCH,
    SLEEP_SENSOR_SAMPLE_SECONDS,
    SLEEP_SCORE_SOFTMAX_TEMPERATURE,
    SLEEP_STAGE_CONFIRM_TICKS,
    SLEEP_STAGE_MIN_DWELL_SECONDS,
    PERSONAL_BASELINE_STAGE_INFLUENCE_ENABLED,
    TERMINAL_WAKE_POLICY_VERSION,
    ZEEP_SLEEP_BASELINE_VERSION,
    ZEEP_OFF_BED_DATA_STATUSES,
    ZEEP_ON_BED_STATUS_CODES,
    ZEEP_SLEEP_STATES,
    ZEEP_SLEEP_TRANSITION_POLICY_VERSION,
    age_group as _age_group,
    assess_environment_values,
    continuity_hold_contract,
    gender_adjusted_baseline as _gender_adjusted_baseline,
    resolve_rest_target,
    sleep_policy_snapshot,
)


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
MUSIC_DIR = Path(os.getenv("MUSIC_DIR", str(BASE_DIR / "music")))

# ---------- EDIT THESE PINS TO MATCH YOUR WIRING ----------
GPIO_PINS = {
    "door_open": int(os.getenv("GPIO_DOOR_OPEN", "17")),
    "door_close": int(os.getenv("GPIO_DOOR_CLOSE", "27")),
    "led": int(os.getenv("GPIO_LED", "22")),
    # Decorative ceiling star light. BCM4 (physical pin 7) was verified free
    # on pod-01; override GPIO_STAR_LIGHT if another Pod uses that pin.
    "star_light": int(os.getenv("GPIO_STAR_LIGHT", "4")),
    "aroma1": int(os.getenv("GPIO_AROMA1", "5")),
    "aroma2": int(os.getenv("GPIO_AROMA2", "6")),
    "aroma3": int(os.getenv("GPIO_AROMA3", "13")),
    "aroma4": int(os.getenv("GPIO_AROMA4", "19")),
    "steam": int(os.getenv("GPIO_STEAM", "26")),
    # Red light therapy zones: persistent HIGH/LOW outputs (not pulse).
    # Defaults use currently-free BCM pins; override with env vars if wiring differs.
    "red_light_face": int(os.getenv("GPIO_RED_LIGHT_FACE", "23")),
    "red_light_body": int(os.getenv("GPIO_RED_LIGHT_BODY", "24")),
    "red_light_leg": int(os.getenv("GPIO_RED_LIGHT_LEG", "25")),
}
DOOR_PULSE_SECONDS = float(os.getenv("DOOR_PULSE_SECONDS", "0.7"))
# Aroma and steam are momentary outputs. Keep the relay HIGH for the requested
# five-second actuation window, then always return it LOW in ``finally``.
# Deployments may still override the duration explicitly when hardware differs.
AROMA_STEAM_PULSE_SECONDS = float(os.getenv("AROMA_STEAM_PULSE_SECONDS", "5.0"))
PULSE_OUTPUTS = {"aroma1", "aroma2", "aroma3", "aroma4", "steam"}
# Minimum idle time between pulses on the same output (relay wear / spam guard).
PULSE_COOLDOWN_SECONDS = float(os.getenv("PULSE_COOLDOWN_SECONDS", "1.0"))
# Sensor values older than these are reported as disconnected/stale to the UI.
# BCG (LSM-800-T) emits a frame only every few seconds — quiet gaps are normal,
# so its threshold must sit well above the inter-frame interval.
# Sensor Hub 1 publishes one coherent three-sensor snapshot every 10 seconds.
# Two missed windows plus scheduling/USB jitter mark it stale; each individual
# sensor still reports its own validity inside every packet.
ESP32_STALE_SECONDS = float(os.getenv("ESP32_STALE_SECONDS", "25"))
# LSM-800-T ส่ง frame ห่างมากเมื่อเตียงว่าง — 60 วิคือ "เงียบผิดปกติจริง"
# (ตอนมีคนบนเตียง frame มาทุก ~2-4 วิ; ค่าสั้นกว่านี้ทำให้ pill กระพริบทั้งที่ปกติ)
BCG_STALE_SECONDS = float(os.getenv("BCG_STALE_SECONDS", "60"))
# The LSM-800-T can emit a transient zero while motion disturbs its internal
# vital-sign estimator. Keep the last valid display value briefly, but clear it
# immediately when the bed no longer represents a person so stale vitals are
# never attributed to a new occupant.
BCG_VITAL_HOLD_SECONDS = float(os.getenv("BCG_VITAL_HOLD_SECONDS", "15"))
# A service/code restart is not physiological evidence.  Keep the last
# confirmed label visible briefly while the serial readers rebuild a fresh
# 30/60-second evidence window.  This bridge is display-only and can never be
# persisted as a new Sleep State decision.
RESTART_SLEEP_STATE_HOLD_SECONDS = min(
    60.0,
    max(
        30.0,
        float(
            os.getenv(
                "RESTART_SLEEP_STATE_HOLD_SECONDS",
                str(SLEEP_RESTART_STATE_HOLD_SECONDS_DEFAULT),
            )
        ),
    ),
)
SAFETY_REQUIRE_CO2 = os.getenv("SAFETY_REQUIRE_CO2", "1") == "1"
SAFETY_CO2_WARN_PPM = float(os.getenv("SAFETY_CO2_WARN_PPM", "1000"))
SAFETY_CO2_FAIR_MAX_PPM = float(os.getenv("SAFETY_CO2_FAIR_MAX_PPM", "1150"))
SAFETY_CO2_CRITICAL_PPM = float(os.getenv("SAFETY_CO2_CRITICAL_PPM", "1300"))
SAFETY_THRESHOLD_BASIS_VERSION = os.getenv("SAFETY_THRESHOLD_BASIS_VERSION", "").strip()
SAFETY_THRESHOLD_BASIS_APPROVED = os.getenv("SAFETY_THRESHOLD_BASIS_APPROVED", "0") == "1"
_SAFETY_MAX_TEMP = os.getenv("SAFETY_MAX_TEMP_C", "").strip()
# ZEEP Atmosphere Operating Basis v1.0 uses the same five-level temperature
# bands as Dashboard/Admin.  The legacy SAFETY_MAX_TEMP_C value, when present,
# still overrides the new critical maximum for deployment compatibility.
SAFETY_TEMP_WARN_MIN_C = float(os.getenv("SAFETY_TEMP_WARN_MIN_C", "17"))
SAFETY_TEMP_WARN_MAX_C = float(os.getenv("SAFETY_TEMP_WARN_MAX_C", "28"))
SAFETY_TEMP_CRITICAL_MIN_C = float(os.getenv("SAFETY_TEMP_CRITICAL_MIN_C", "13"))
SAFETY_TEMP_CRITICAL_MAX_C = float(_SAFETY_MAX_TEMP or os.getenv("SAFETY_TEMP_CRITICAL_MAX_C", "32"))
SAFETY_MAX_TEMP_C = SAFETY_TEMP_CRITICAL_MAX_C
SAFETY_ARMED_DEFAULT = os.getenv("SAFETY_ARMED_DEFAULT", "0") == "1"

# ---------- sleep-state estimator (internal telemetry, pre-G2) ----------
# Rule-based v1 over a rolling window of BCG summary frames. This is a
# DIRECTIONAL five-state wellness estimate for the lab dashboard only:
# Wake/N1/N2/N3/REM are baseline-derived proxy labels, not AASM/PSG staging.
# It is not validated against PSG (G2 open), is never an actuator trigger, and
# carries its version with every session record for provenance.
SLEEP_SAMPLE_SECONDS = float(os.getenv("SLEEP_SAMPLE_SECONDS", "10"))
SLEEP_WINDOW_SECONDS = float(os.getenv("SLEEP_WINDOW_SECONDS", "60"))
if SLEEP_SAMPLE_SECONDS <= 0 or SLEEP_WINDOW_SECONDS <= 0:
    raise RuntimeError("Sleep cadence and rolling window must be positive")
if not math.isclose(SLEEP_SAMPLE_SECONDS, SLEEP_SENSOR_SAMPLE_SECONDS):
    raise RuntimeError(f"stable-30s-epoch requires 10-second sensor samples; received {SLEEP_SAMPLE_SECONDS:g} seconds")
# LSM-800-T bed exit is a high-impact occupancy/safety result, so it must
# survive a temporal confirmation guard. Three 10-second buckets confirm an
# exit. Raw packet bursts are retained for Admin diagnostics but cannot create
# a Wake epoch because field data contained false exit pulses up to seven frames.
BED_EXIT_CONFIRM_BUCKETS = max(3, int(os.getenv("BED_EXIT_CONFIRM_BUCKETS", "3")))
BED_EXIT_RAW_MIN_FRAMES = max(3, int(os.getenv("BED_EXIT_RAW_MIN_FRAMES", "5")))
BED_EXIT_RAW_MIN_RATIO = min(1.0, max(0.6, float(os.getenv("BED_EXIT_RAW_MIN_RATIO", "0.8"))))
BED_EXIT_RAW_CONFIRMATION_ENABLED = os.getenv("BED_EXIT_RAW_CONFIRMATION_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
# Target context for one evidence estimate. Sensor frames arrive every 10 s,
# become one evidence epoch every 30 s, and require two matching evidence
# epochs before a W/N1/N2/N3/REM state is confirmed. Until then the API exposes
# the evidence candidate but deliberately returns no confirmed stage.
SLEEP_MIN_FRAMES = max(
    1,
    int(
        os.getenv(
            "SLEEP_MIN_FRAMES",
            str(math.ceil(SLEEP_WINDOW_SECONDS / SLEEP_SAMPLE_SECONDS)),
        )
    ),
)
# Fraction of "Moving" frames in the window at/above which we call Wake.
SLEEP_MOVE_WAKE_RATIO = float(os.getenv("SLEEP_MOVE_WAKE_RATIO", str(SLEEP_DEFAULT_MOVE_WAKE_RATIO)))
# Legacy/personal calibration thresholds for the coefficient of variation of
# fixed-cadence HR summaries. This is explicitly NOT RMSSD/SDNN or ECG HRV. v1.8
# keeps it as a weak proxy and does not introduce a beat detector.
SLEEP_HR_CV_REM = float(os.getenv("SLEEP_HR_CV_REM", str(SLEEP_DEFAULT_HR_CV_REM)))
# NREM depth proxy (NOT AASM N1/N2/N3 — those are EEG-defined and PSG-only).
# The five output labels now map one-to-one to the amended five-class G2
# validation ontology, but remain exploratory until paired-PSG validation.
SLEEP_HR_CV_DEEP = float(os.getenv("SLEEP_HR_CV_DEEP", str(SLEEP_DEFAULT_HR_CV_DEEP)))
SLEEP_MOVE_DEEP_RATIO = float(os.getenv("SLEEP_MOVE_DEEP_RATIO", str(SLEEP_DEFAULT_MOVE_DEEP_RATIO)))
# Baseline fit keeps 10% of the score budget for movement/variability/timing.
# RR is raised slightly from 0.35 to 0.40 after the Pod produced excessive N3
# while measured RR remained closer to its N2 range. These are versioned ZEEP
# engineering weights, not AASM scoring coefficients.
SLEEP_BASELINE_HR_WEIGHT = float(os.getenv("SLEEP_BASELINE_HR_WEIGHT", str(SLEEP_DEFAULT_BASELINE_HR_WEIGHT)))
SLEEP_BASELINE_RR_WEIGHT = float(os.getenv("SLEEP_BASELINE_RR_WEIGHT", str(SLEEP_DEFAULT_BASELINE_RR_WEIGHT)))
SLEEP_N3_RR_CONFLICT_PENALTY = float(os.getenv("SLEEP_N3_RR_CONFLICT_PENALTY", str(SLEEP_DEFAULT_N3_RR_CONFLICT_PENALTY)))
SLEEP_N2_RR_CONFLICT_SUPPORT = float(os.getenv("SLEEP_N2_RR_CONFLICT_SUPPORT", str(SLEEP_DEFAULT_N2_RR_CONFLICT_SUPPORT)))
# A microphone event can support Wake only when the same rolling window also
# contains BCG amplitude change or bed motion.  Continuous background sound,
# air quality and comfort telemetry never create a stage by themselves.
SLEEP_ACOUSTIC_DISTURBANCE_DBA = float(os.getenv("SLEEP_ACOUSTIC_DISTURBANCE_DBA", str(SLEEP_DEFAULT_ACOUSTIC_DISTURBANCE_DBA)))
SLEEP_ACOUSTIC_MIN_COVERAGE = float(os.getenv("SLEEP_ACOUSTIC_MIN_COVERAGE", str(SLEEP_DEFAULT_ACOUSTIC_MIN_COVERAGE)))
SLEEP_ACOUSTIC_WAKE_SUPPORT_MAX = float(os.getenv("SLEEP_ACOUSTIC_WAKE_SUPPORT_MAX", str(SLEEP_DEFAULT_ACOUSTIC_WAKE_SUPPORT_MAX)))
if SLEEP_BASELINE_HR_WEIGHT < 0 or SLEEP_BASELINE_RR_WEIGHT < 0:
    raise RuntimeError("Sleep baseline weights must not be negative")
if SLEEP_BASELINE_HR_WEIGHT + SLEEP_BASELINE_RR_WEIGHT <= 0:
    raise RuntimeError("At least one sleep baseline weight must be positive")
if SLEEP_N3_RR_CONFLICT_PENALTY < 0 or SLEEP_N2_RR_CONFLICT_SUPPORT < 0:
    raise RuntimeError("Sleep RR conflict weights must not be negative")
if not 0 <= SLEEP_ACOUSTIC_MIN_COVERAGE <= 1:
    raise RuntimeError("SLEEP_ACOUSTIC_MIN_COVERAGE must be between 0 and 1")
if not 0 <= SLEEP_ACOUSTIC_WAKE_SUPPORT_MAX <= 0.35:
    raise RuntimeError("SLEEP_ACOUSTIC_WAKE_SUPPORT_MAX must be between 0 and 0.35")
# Optional shared token. When set, every control POST must send X-Api-Token.
API_TOKEN = os.getenv("API_TOKEN", "").strip()
# ---------- ZEEP account login (same backend the mobile app talks to) ----------
# Pi ยิง /v1/auth/login แทน browser: access/refresh token ไม่โผล่ในหน้าเว็บของตู้
# และไม่ต้องพึ่ง CORS ของ API. NestJS ตั้ง global prefix /api → base ต้องมี /api.
ZEEP_API_BASE_URL = os.getenv("ZEEP_API_BASE_URL", "https://api.zeep.world/api").rstrip("/")
ZEEP_API_TIMEOUT = float(os.getenv("ZEEP_API_TIMEOUT", "12"))
# x-client-platform ของ backend รับ web/ios/android/desktop — ตู้เป็น Linux → desktop
ZEEP_CLIENT_HEADERS = {
    "x-client-platform": "desktop",
    "x-device-vendor": "Raspberry Pi",
    "x-device-model": "ZEEP Pod",
}
# Service-to-service upload of a finished Session to the ZEEP account backend.
# The ingest route is excluded from the user JWT middleware and authenticates
# with the shared x-api-key instead, so it does not depend on the occupant's
# access token and still works for a Session recovered after a service restart.
# Either value empty disables the upload entirely (no outbox is written).
ZEEP_INGEST_API_KEY = os.getenv("ZEEP_INGEST_API_KEY", "").strip()
ZEEP_INGEST_DEVICE_ID = os.getenv("ZEEP_DEVICE_ID", "").strip()
ZEEP_INGEST_PATH = "/v1/sleep-sessions/ingest"
ZEEP_INGEST_SWEEP_SECONDS = float(os.getenv("ZEEP_INGEST_SWEEP_SECONDS", "900"))
# Ending a Session already waits on the ZEEP logout call. Bound the upload
# attempt made on that path more tightly so an offline Pod does not add a
# second full timeout to a User/Admin request; the outbox sweep retries it
# with the normal timeout anyway.
ZEEP_INGEST_INLINE_TIMEOUT = float(os.getenv("ZEEP_INGEST_INLINE_TIMEOUT", "5"))
# IANA zone this Pod stands in. The Pod records UTC, and the account
# backend needs a zone to decide which night a Session belongs to. Leave
# empty to let the backend use the account profile instead of guessing.
POD_TIMEZONE = os.getenv("POD_TIMEZONE", "").strip()
MAX_VOLUME = 100  # mpv >100 is digital gain (distortion); keep sleep-safe ceiling
# Old tablet pages once advanced a queue in the browser as well as on the Pi.
# After an explicit Stop, reject those legacy automatic play requests briefly;
# a current page marks real touch actions and can start again immediately.
MUSIC_STOP_GUARD_SECONDS = max(0.5, float(os.getenv("MUSIC_STOP_GUARD_SECONDS", "4.0")))
# The selected temperature is the physical IR setpoint: no hidden offset or
# installation bias is applied. Product and Admin controls share 15-28 °C.
AIRCON_POWER_ON_DEFAULT_TEMP_C = 18

# ---------- user profiles & test sessions (stored only on this pod) ----------
# PDPA boundary: profiles/sessions live in DATA_DIR on the Pi itself, never in
# git. Records carry named users + HR/RR trends, so treat DATA_DIR as personal
# data: keep it on-device and honor deletion via DELETE /api/users/{account_key}.
# ZEEP accounts use normalized email as the canonical data key; mutable
# username/displayName values are presentation metadata only.
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data")))
BRAINWAVE_PREVIEW_DIR = DATA_DIR / "brainwave_audio"
PROFILES_PATH = DATA_DIR / "profiles.json"
SESSIONS_PATH = DATA_DIR / "sessions.jsonl"
LABELS_PATH = DATA_DIR / "output_labels.json"
AIRCON_CONTROL_STATE_PATH = DATA_DIR / "aircon_control_state.json"
ACTIVE_SESSION_CHECKPOINT_PATH = DATA_DIR / "active_session_checkpoint.json"
# Canonical 10-second Sensor frame saved during an orderly service restart.
# It prevents a blank Dashboard while hardware readers wait for their first
# post-boot packet. Restored values are always marked stale and can never arm
# Safety, start a Session, or become Sleep Stage evidence.
LAST_SENSOR_FRAME_PATH = DATA_DIR / "last_sensor_frame.json"
# One JSON file per finished Session still waiting to reach the account
# backend. The file holds the finished upload payload so a retry never has
# to rebuild it from SQLite. PDPA: same personal boundary as DATA_DIR.
INGEST_OUTBOX_DIR = DATA_DIR / "ingest_outbox"
AIRCON_FAN_LEVEL_DEFAULT = int(os.getenv("AIRCON_FAN_LEVEL_DEFAULT", "1"))
if not 1 <= AIRCON_FAN_LEVEL_DEFAULT <= 5:
    raise RuntimeError("AIRCON_FAN_LEVEL_DEFAULT must be between 1 and 5")
# Display names for the outputs card; aroma slots are user-editable so the
# label can carry the actual oil loaded in each slot.
DEFAULT_LABELS = {
    "led": "Lighting Room",
    "star_light": "ไฟดาวบนท้องฟ้า",
    "aroma1": "Aroma 1",
    "aroma2": "Aroma 2",
    "aroma3": "Aroma 3",
    "aroma4": "Aroma 4",
    "steam": "ไอน้ำ (Steam)",
}
EDITABLE_LABELS = {"aroma1", "aroma2", "aroma3", "aroma4"}
SESSION_SAMPLE_SECONDS = float(os.getenv("SESSION_SAMPLE_SECONDS", "10"))
SESSION_TIMELINE_SCHEMA_VERSION = 5
if SESSION_SAMPLE_SECONDS <= 0:
    raise RuntimeError("Session sample cadence must be positive")
_sleep_quality_summary = partial(build_sleep_quality, sample_interval_s=SESSION_SAMPLE_SECONDS)
# Keep at least the previous 16 h 40 m capacity. At the new 10-second cadence,
# 12,000 rows cover 33 h 20 m and still allow a legacy 5-second active Session
# to resume without truncation during this deployment.
SESSION_SAMPLE_LIMIT = int(os.getenv("SESSION_SAMPLE_LIMIT", "12000"))


def _sample_interval_seconds(
    value: Any,
    fallback: float = SESSION_SAMPLE_SECONDS,
) -> float:
    """Compatibility facade for the extracted Session cadence module."""
    return _sample_interval_seconds_impl(value, fallback)


# เริ่มนับ/บันทึกจริงเมื่อผู้ใช้นอนบนเตียงต่อเนื่องครบตามนี้ (ลุกก่อนครบ = รีเซ็ต)
BED_START_SECONDS = float(os.getenv("BED_START_SECONDS", "20"))
# A Session row/timeline must not start from bed status alone. Require fresh,
# sane HR and RR in consecutive *new* BCG packets after Login/restart. Values
# held for display while the module reacquires a signal never pass this gate.
SESSION_VITAL_START_PACKETS = max(1, int(os.getenv("SESSION_VITAL_START_PACKETS", "3")))
GENDERS = ("male", "female", "other", "unspecified")
POD_ID = pod_id_from_env()
OCCUPANCY_LEASE_SECONDS = max(15, int(os.getenv("OCCUPANCY_LEASE_SECONDS", "45")))
OCCUPANCY_RENEW_SECONDS = max(5, int(os.getenv("OCCUPANCY_RENEW_SECONDS", "10")))

BCG_PORT = os.getenv("BCG_PORT", "/dev/ttyUSB_HRB")
BCG_BAUD = int(os.getenv("BCG_BAUD", "115200"))
ESP32_PORT = os.getenv("ESP32_PORT", "/dev/ttyACM0")
ESP32_BAUD = int(os.getenv("ESP32_BAUD", "115200"))

# Sensor Hub 2 uses the Pi-local MQTT broker.  It stays separate from the
# original USB hub so one transport cannot overwrite or mask the other.
MQTT_HOST = os.getenv("MQTT_HOST", "127.0.0.1")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_KEEPALIVE = int(os.getenv("MQTT_KEEPALIVE", "30"))
SENSORHUB2_TELEMETRY_TOPIC = os.getenv("SENSORHUB2_TELEMETRY_TOPIC", "zeep/pod1/sensorhub2/telemetry")
SENSORHUB2_STATUS_TOPIC = os.getenv("SENSORHUB2_STATUS_TOPIC", "zeep/pod1/sensorhub2/status")
SENSORHUB2_STALE_SECONDS = float(os.getenv("SENSORHUB2_STALE_SECONDS", "15"))

# Control Hub 1 receives plain-text air-conditioner commands and publishes
# retained status plus a non-retained command event after sending IR.
CONTROLHUB1_COMMAND_TOPIC = os.getenv("CONTROLHUB1_COMMAND_TOPIC", "zeep/pod1/controlhub1/command")
CONTROLHUB1_STATUS_TOPIC = os.getenv("CONTROLHUB1_STATUS_TOPIC", "zeep/pod1/controlhub1/status")
CONTROLHUB1_EVENT_TOPIC = os.getenv("CONTROLHUB1_EVENT_TOPIC", "zeep/pod1/controlhub1/event")
CONTROLHUB1_STALE_SECONDS = float(os.getenv("CONTROLHUB1_STALE_SECONDS", "70"))
CONTROLHUB1_ACK_TIMEOUT_SECONDS = float(os.getenv("CONTROLHUB1_ACK_TIMEOUT_SECONDS", "3"))
# Air-conditioner IR receivers commonly ignore frames that arrive while the
# previous command is still being processed. Keep every Control Hub 1 command
# in one serialized queue and enforce a guard interval between IR frames.
# Power ON needs a longer settle period before applying the default setpoint.
CONTROLHUB1_MIN_IR_GAP_SECONDS = float(os.getenv("CONTROLHUB1_MIN_IR_GAP_SECONDS", "1.2"))
CONTROLHUB1_POWER_ON_SETTLE_SECONDS = float(os.getenv("CONTROLHUB1_POWER_ON_SETTLE_SECONDS", "2.0"))
CONTROLHUB1_FAN_WAKE_SETTLE_SECONDS = float(os.getenv("CONTROLHUB1_FAN_WAKE_SETTLE_SECONDS", "0.25"))
if CONTROLHUB1_MIN_IR_GAP_SECONDS < 0:
    raise RuntimeError("CONTROLHUB1_MIN_IR_GAP_SECONDS must not be negative")
if CONTROLHUB1_POWER_ON_SETTLE_SECONDS < 0:
    raise RuntimeError("CONTROLHUB1_POWER_ON_SETTLE_SECONDS must not be negative")
if CONTROLHUB1_FAN_WAKE_SETTLE_SECONDS < 0:
    raise RuntimeError("CONTROLHUB1_FAN_WAKE_SETTLE_SECONDS must not be negative")

# Control Hub 2 drives the four servos that press the bed remote.  It uses the
# same Pi-local broker as Control Hub 1, but separate topics and state so an
# air-conditioner command can never be interpreted as a bed command.
CONTROLHUB2_COMMAND_TOPIC = os.getenv("CONTROLHUB2_COMMAND_TOPIC", "zeep/pod1/controlhub2/bed/command")
CONTROLHUB2_STATUS_TOPIC = os.getenv("CONTROLHUB2_STATUS_TOPIC", "zeep/pod1/controlhub2/bed/status")
CONTROLHUB2_EVENT_TOPIC = os.getenv("CONTROLHUB2_EVENT_TOPIC", "zeep/pod1/controlhub2/bed/event")
CONTROLHUB2_STALE_SECONDS = float(os.getenv("CONTROLHUB2_STALE_SECONDS", "70"))
CONTROLHUB2_ACK_TIMEOUT_SECONDS = float(os.getenv("CONTROLHUB2_ACK_TIMEOUT_SECONDS", "3"))
# Every user bed movement is a bounded one-shot action. The Pi publishes an
# explicit BED STOP after this window even if a browser disconnects, so a held
# direction cannot continue indefinitely. Safety Supervisor can still stop it
# immediately through the internal bed_stop command.
BED_MOVE_SECONDS = max(0.5, float(os.getenv("BED_MOVE_SECONDS", "2")))

LIVE_DEVICE_PROJECTION_POLICY = LiveDeviceProjectionPolicy(
    esp32_stale_s=ESP32_STALE_SECONDS,
    sensorhub2_stale_s=SENSORHUB2_STALE_SECONDS,
    bcg_stale_s=BCG_STALE_SECONDS,
    controlhub1_stale_s=CONTROLHUB1_STALE_SECONDS,
    controlhub2_stale_s=CONTROLHUB2_STALE_SECONDS,
    aircon_power_on_default_c=AIRCON_POWER_ON_DEFAULT_TEMP_C,
    aircon_temperature_min_c=AIRCON_TEMPERATURE_MIN_C,
    aircon_temperature_max_c=AIRCON_TEMPERATURE_MAX_C,
)

# Calibration file for environmental channels. Sensor Hub 1 owns SPH0645
# processing; the Pi consumes its finite, in-range ``sound_dba`` directly.
# Signed dBFS remains Admin diagnostics and is never converted with abs().
CALIBRATION_PATH = BASE_DIR / "calibration.json"


def _load_calibration() -> Dict[str, Any]:
    try:
        return load_calibration(CALIBRATION_PATH)
    except Exception as exc:
        print(f"[CAL] ignoring invalid calibration.json: {exc}")
        return {}


CALIBRATION = _load_calibration()

# SHT3x-DIS display values follow the versioned policy in calibration.json.
# The active policy is direct passthrough (zero additive bias); raw Hub 1 data
# remains unchanged for audit and any future controlled recalibration.
_ENV_HUMIDITY_BIAS = os.getenv("HUMIDITY_RH_BIAS")
if _ENV_HUMIDITY_BIAS is not None:
    HUMIDITY_RH_BIAS = float(_ENV_HUMIDITY_BIAS)
    HUMIDITY_BIAS_SOURCE = "env"
elif "humidity_rh_bias" in CALIBRATION:
    HUMIDITY_RH_BIAS = float(CALIBRATION["humidity_rh_bias"])
    HUMIDITY_BIAS_SOURCE = "calibration.json"
else:
    HUMIDITY_RH_BIAS = 0.0
    HUMIDITY_BIAS_SOURCE = "default"
if not math.isfinite(HUMIDITY_RH_BIAS) or not -20.0 <= HUMIDITY_RH_BIAS <= 20.0:
    raise RuntimeError("HUMIDITY_RH_BIAS must be finite and between -20 and +20 %RH")

# Calibration definitions and file mechanics live in sensor_calibration.py.
# app.py owns only authorization and publishing the resulting runtime state.
SENSOR_CALIBRATION_LOCK = threading.RLock()


def _load_sensor_biases() -> tuple[Dict[str, float], Dict[str, str]]:
    return resolve_biases(
        CALIBRATION,
        humidity_bias=HUMIDITY_RH_BIAS,
        humidity_source=HUMIDITY_BIAS_SOURCE,
    )


SENSOR_BIASES, SENSOR_BIAS_SOURCES = _load_sensor_biases()


def sensor_bias_value(metric: str) -> float:
    with SENSOR_CALIBRATION_LOCK:
        return float(SENSOR_BIASES.get(metric, 0.0))


def _apply_sensor_bias(metric: str, raw_value: Optional[float]) -> Optional[float]:
    # Keep the original read/write synchronization: Admin may update a bias
    # while Sensor Hub threads are composing the next canonical snapshot.
    with SENSOR_CALIBRATION_LOCK:
        return apply_additive_bias(metric, raw_value, biases=SENSOR_BIASES)


def _persist_calibration(data: Dict[str, Any]) -> None:
    persist_calibration(CALIBRATION_PATH, data)


def update_sensor_bias(metric: str, bias: float, *, operator: str, reference_value: Optional[float] = None) -> Dict[str, Any]:
    """Validate, persist and activate one Admin calibration adjustment."""
    global HUMIDITY_RH_BIAS, HUMIDITY_BIAS_SOURCE
    spec = SENSOR_CALIBRATION_SPECS.get(metric)
    if spec is None:
        raise ValueError("metric_not_calibratable")
    value = float(bias)
    if not math.isfinite(value) or not spec["bias_min"] <= value <= spec["bias_max"]:
        raise ValueError("bias_out_of_range")
    reference = None if reference_value is None else float(reference_value)
    if reference is not None and not math.isfinite(reference):
        raise ValueError("invalid_reference")
    rounded = round(value, 3)
    changed_at = datetime.now(timezone.utc).isoformat()
    with SENSOR_CALIBRATION_LOCK:
        updated = dict(CALIBRATION)
        updated[spec["config_key"]] = rounded
        metadata = dict(updated.get("sensor_bias_metadata") or {})
        metadata[metric] = {
            "updated_at": changed_at,
            "operator": operator,
            "reference_value": reference,
            "unit": spec["unit"],
            "raw_unit": spec.get("raw_unit", spec["unit"]),
            "parameter_unit": spec.get("parameter_unit", spec["unit"]),
        }
        updated["sensor_bias_metadata"] = metadata
        _persist_calibration(updated)
        CALIBRATION.clear()
        CALIBRATION.update(updated)
        SENSOR_BIASES[metric] = rounded
        SENSOR_BIAS_SOURCES[metric] = "calibration.json"
        if metric == "humidity_rh":
            HUMIDITY_RH_BIAS = rounded
            HUMIDITY_BIAS_SOURCE = "calibration.json"
    with state_lock:
        environment_calibration = state["system"].setdefault("environment_calibration", {})
        environment_calibration["biases"] = dict(SENSOR_BIASES)
        environment_calibration["sources"] = dict(SENSOR_BIAS_SOURCES)
        environment_calibration["humidity_rh_bias"] = HUMIDITY_RH_BIAS
        environment_calibration["humidity_bias_source"] = HUMIDITY_BIAS_SOURCE
    return {
        "metric": metric,
        "bias": rounded,
        "source": "calibration.json",
        "updated_at": changed_at,
        "reference_value": reference,
    }


# Operational sleep-comfort target used by Monitor recommendations. This is
# separate from validation against the 30–130 dBA reference-meter envelope.
SOUND_DBA_SLEEP_TARGET = 35.0

# Shared temperature comfort band for the user dashboard and Monitor advice.
# Values at either boundary are still considered inside the excellent range.
TEMPERATURE_EXCELLENT_MIN_C = 18.0
TEMPERATURE_EXCELLENT_MAX_C = 27.0

# LSM-800-T bed-status mapping from the confirmed 66-byte protocol.
STATUS_TEXT = {
    0: "On bed",
    1: "Get out of bed",
    2: "Moving",
    3: "Weak breathing",
    4: "Heavy object on bed",
    5: "Snoring",
}
ON_BED_CODES = ZEEP_ON_BED_STATUS_CODES

# Rolling BCG summary history feeding the sleep-state estimator
# (~1 frame per 2-4 s → maxlen 600 covers well over the analysis window).
history_lock = threading.Lock()
bcg_history: deque = deque(maxlen=600)
# Fixed-cadence features for Sleep State: 1 snapshot / 10 seconds, 6 snapshots
# per 60-second confidence window. Raw ingestion remains independent and lossless.
sleep_feature_history: deque = deque(maxlen=720)
# Short in-memory inspector for developers. Raw frames remain byte-for-byte
# representations of the serial packets and are never used for device control.
bcg_raw_history: deque = deque(maxlen=200)
# Every valid SPH0645 level is retained briefly so the canonical analysis
# frame can publish an energy average (Leq) instead of whichever serial sample
# happened to arrive last. This also prevents a single low transient such as
# 4 dB from pulling an otherwise 45–50 dBA window to a false quiet state.
sound_history_lock = threading.Lock()
sound_level_history: deque = deque(maxlen=600)

labels_lock = threading.Lock()


def _load_labels() -> Dict[str, str]:
    labels = dict(DEFAULT_LABELS)
    try:
        with LABELS_PATH.open("r", encoding="utf-8") as f:
            saved = json.load(f)
        if isinstance(saved, dict):
            for key, value in saved.items():
                if key in EDITABLE_LABELS and isinstance(value, str) and value.strip():
                    labels[key] = value.strip()[:24]
    except FileNotFoundError:
        pass
    except Exception as exc:
        print(f"[LABELS] ignoring invalid output_labels.json: {exc}")
    return labels


def _save_labels(labels: Dict[str, str]):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = LABELS_PATH.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump({k: labels[k] for k in EDITABLE_LABELS}, f, ensure_ascii=False, indent=1)
    tmp.replace(LABELS_PATH)


def _persist_aircon_fan_level(
    level: int,
    source: str,
    *,
    operator: Optional[str] = None,
) -> Dict[str, Any]:
    """Persist the last acknowledged/declared fan step, never a measured speed.

    The installed air conditioner has no physical fan-state return channel.
    This small on-device file lets the Pi keep its 1..5 IR-cycle reference
    across service restarts. It contains no user or Session data.
    """
    return aircon_fan_reference_store.save(
        level,
        source,
        operator=operator,
    )


def _load_aircon_fan_level_reference() -> Dict[str, Any]:
    """Load the persisted fan-cycle reference or establish Pod default level 1."""
    saved = aircon_fan_reference_store.initialize()
    return {
        "fan_level": saved["fan_level"],
        "fan_level_source": saved["source"],
        "fan_level_updated_at": saved["updated_at"],
    }


state_lock = threading.Lock()
state: Dict[str, Any] = {
    "gpio": {name: False for name in GPIO_PINS},
    "labels": _load_labels(),
    "sensor": {
        "esp32": {},
        "sensorhub2": {
            "connected": False,
            "transport": "mqtt",
            "device_id": "sensorhub2-pod1",
            "last_update": None,
        },
        "bcg": {
            "connected": False,
            "samples": [],
            "sensor_packet_id": None,
            "status_code": None,
            "status_text": None,
            "heart_rate_bpm": None,
            "heart_rate_last_valid": None,
            "heart_rate_held": False,
            "heart_rate_current_valid": False,
            "respiration_raw": None,
            "respiration_rate": None,
            "respiration_last_valid": None,
            "respiration_held": False,
            "respiration_current_valid": False,
            "vital_valid_streak": 0,
            "vital_valid_since": None,
            "packets": 0,
            "last_update": None,
        },
    },
    "aircon": {
        "connected": False,
        "transport": "mqtt",
        "device_id": "controlhub1-pod1",
        "power": None,
        "temperature_c": None,
        # Control Hub 1 currently acknowledges that an IR frame was sent but
        # cannot read the air conditioner's physical fan state.  Keep the
        # latest acknowledged FAN step (1..5) as an operator-facing intent.
        "fan_level": AIRCON_FAN_LEVEL_DEFAULT,
        "fan_level_source": "startup_default_pending",
        "fan_level_updated_at": None,
        "tx_count": 0,
        "last_command": None,
        "last_event": None,
        "last_update": None,
        "command_pending": False,
        "pending_command": None,
        "error": None,
    },
    "bed_control": {
        "connected": False,
        "transport": "mqtt",
        "device_id": "controlhub2-bed-pod1",
        "active_command": "none",
        "active_servo": None,
        "command_count": 0,
        "last_command": None,
        "last_event": None,
        "last_update": None,
        "command_pending": False,
        "pending_command": None,
        "motion_duration_s": BED_MOVE_SECONDS,
        "auto_stop_at": None,
        "auto_stop_pending": False,
        "error": None,
    },
    "music": default_music_state(),
    "safety": {
        "armed": SAFETY_ARMED_DEFAULT,
        "ready": False,
        "level": "initializing",
        "latched": False,
        "faults": [],
        "last_check": None,
        "last_transition": None,
        "last_action": None,
        "automatic_actions": [
            "stop_music",
            "accessories_off",
            "star_light_off",
            "red_light_off",
            "door_drive_off",
            "led_on",
        ],
        "door_auto_open": False,
        "ventilation_control_available": False,
        "threshold_basis": {
            "version": SAFETY_THRESHOLD_BASIS_VERSION,
            "approved": SAFETY_THRESHOLD_BASIS_APPROVED,
            "scope": "zeep_internal_operating_policy",
            "document": "docs/zeep-sleep-system-current.md#environment-operating-bands",
        },
        "thresholds": {
            "esp32_stale_s": ESP32_STALE_SECONDS,
            "co2_warn_ppm": SAFETY_CO2_WARN_PPM,
            "co2_fair_max_ppm": SAFETY_CO2_FAIR_MAX_PPM,
            "co2_critical_ppm": SAFETY_CO2_CRITICAL_PPM,
            "temperature_warn_min_c": SAFETY_TEMP_WARN_MIN_C,
            "temperature_warn_max_c": SAFETY_TEMP_WARN_MAX_C,
            "temperature_critical_min_c": SAFETY_TEMP_CRITICAL_MIN_C,
            "temperature_critical_max_c": SAFETY_TEMP_CRITICAL_MAX_C,
            # Legacy response field retained for older clients.
            "max_temperature_c": SAFETY_MAX_TEMP_C,
        },
    },
    # Start gate: Login remains active, but no DB Session/timeline exists until
    # both bed duration and fresh HR+RR confirmation pass.
    "session": inactive_session_projection(
        required_packets=SESSION_VITAL_START_PACKETS,
        reason="waiting_for_bcg",
    ),
    "system": {
        "started_at": time.time(),
        "gpio_available": False,  # set for real after GPIOManager init — no mock
        "gpio_error": None,
        "gpio_pins": dict(GPIO_PINS),
        # Browser login is always required. API_TOKEN is only an optional
        # service/admin credential; it no longer switches authentication off.
        "auth_required": True,
        "pod_id": POD_ID,
        "occupancy": {"mode": "initializing", "available": False, "multi_pod": False},
        "max_volume": MAX_VOLUME,
        "data_dir": str(DATA_DIR),
        "session_sample_s": SESSION_SAMPLE_SECONDS,
        "bed_start_s": BED_START_SECONDS,
        "session_vital_start_packets": SESSION_VITAL_START_PACKETS,
        "player": None,  # filled in once the audio backend is chosen
        "sound_transform": {
            "formula": "ESP32 sound_dba -> Pi direct",
            "source": "sensorhub1_firmware",
            "source_field": "sound_dba",
            "legacy_dbfs_policy": "invalid",
            "pi_abs_transform_allowed": False,
            "pi_bias": 0.0,
            "status": "direct",
            "accepted_range_dba": [
                SOUND_DBA_DISPLAY_MIN,
                SOUND_DBA_DISPLAY_MAX,
            ],
        },
        "environment_calibration": {
            "biases": dict(SENSOR_BIASES),
            "sources": dict(SENSOR_BIAS_SOURCES),
            "humidity_rh_bias": HUMIDITY_RH_BIAS,
            "humidity_bias_source": HUMIDITY_BIAS_SOURCE,
            "humidity_method": CALIBRATION.get("humidity_method"),
            "humidity_calibrated_at": CALIBRATION.get("humidity_calibrated_at"),
        },
        "sound_analysis": {
            "method": "energy_average_leq",
            "window_s": SLEEP_SAMPLE_SECONDS,
            "sample_count": 0,
            "status": "waiting",
        },
    },
}


def _replace_session_projection_locked(
    projection: LiveSessionProjection,
) -> None:
    """Publish one complete Session projection while the caller holds the lock."""
    current = state["session"]
    current.clear()
    current.update(projection)


def _patch_session_projection_locked(patch: Mapping[str, Any]) -> None:
    """Publish a phase delta while the caller holds ``state_lock``."""
    state["session"].update(patch)


aircon_fan_reference_store = AirconFanReferenceStore(
    AIRCON_CONTROL_STATE_PATH,
    AIRCON_FAN_LEVEL_DEFAULT,
    on_invalid=lambda exc: print(
        f"[AIRCON] replacing invalid fan-level reference: {exc}"
    ),
)


def _initialize_aircon_fan_reference() -> Dict[str, Any]:
    """Load durable fan intent and publish it after lifespan initialization."""
    reference = _load_aircon_fan_level_reference()
    with state_lock:
        state["aircon"].update(reference)
    return reference


gpio = GPIOManager(GPIO_PINS, state, state_lock)
_pulse_control = PulseControlService(
    gpio=gpio,
    pulse_outputs=PULSE_OUTPUTS,
    door_pulse_seconds=DOOR_PULSE_SECONDS,
    accessory_pulse_seconds=AROMA_STEAM_PULSE_SECONDS,
    cooldown_seconds=PULSE_COOLDOWN_SECONDS,
    sleep=lambda seconds: asyncio.sleep(seconds),
)
# Transitional compatibility aliases for operational tests and local tooling.
# Ownership lives in ``PulseControlService``; remove these after callers move.
door_lock = _pulse_control.door_lock
pulse_locks = _pulse_control.pulse_locks
pulse_last_end = _pulse_control.pulse_last_end
player = AudioPlayer(
    music_dir=MUSIC_DIR,
    max_volume=MAX_VOLUME,
    state=state,
    state_lock=state_lock,
)

# SQLite V2 storage. Serial readers only enqueue; the writer thread owns writes.
database = DatabaseManager(DATA_DIR, int(os.getenv("DB_QUEUE_SIZE", "10000")))
# One BCG packet arrives about once per second. A 60-packet epoch is the
# operator-facing one-minute transaction window: epoch_index 1 == tx1.
bcg_storage = BCGStorage(database, int(os.getenv("BCG_EPOCH_PACKETS", "60")))
daily_backup = DailyBackup(
    database,
    Path(os.getenv("BACKUP_DIR", str(BASE_DIR / "backup"))),
    retention_count=int(os.getenv("BACKUP_RETENTION_COUNT", "3")),
    supplemental_paths=(PROFILES_PATH, DATA_DIR / "baselines.json"),
)

# Browser authentication and physical occupancy intentionally use separate
# stores.  One pod session can coexist with one or more admin browser sessions.
auth_sessions = AuthSessionManager(DATA_DIR)
auth_cookie = APIKeyCookie(name=COOKIE_NAME, auto_error=False)
# In-flight QR logins.  Process memory only: a pollSecret must never reach the
# browser, the QR image, disk or the log.
qr_logins = QrLoginRegistry()
# Verified logins whose ZEEP account still lacks the facts a Session is scored
# against: holds their tokens while the form is filled, never the pod itself.
pending_profiles = PendingProfileRegistry()
# Post-Session QR share. Off by default: it sends a rendered report off-pod.
report_shares = ReportShareRegistry(enabled=os.getenv("SESSION_REPORT_SHARE_ENABLED", "0") == "1")
occupancy_store = OccupancyStore(DATA_DIR, OCCUPANCY_LEASE_SECONDS)
occupancy_client = build_occupancy_client(occupancy_store)
OCCUPANCY_COORDINATOR_TOKEN = os.getenv("OCCUPANCY_COORDINATOR_TOKEN", "").strip()

# Adaptive layer: baseline ส่วนบุคคล (เรียนรู้ 3–7 คืน) + hybrid staging engine
baselines = BaselineStore(database, DATA_DIR)


# ---------- event log (ตรวจสอบย้อนหลังได้ทุกเหตุการณ์สำคัญ) ----------
EVENT_LOG_PATH = Path(os.getenv("EVENT_LOG_PATH", str(BASE_DIR / "logs" / "events.jsonl")))
EVENT_RING_LIMIT = int(os.getenv("EVENT_RING_LIMIT", "200"))
# Durable event logging cannot be disabled on a production Pod.  Tests use a
# reserved Pod identifier and opt out of disk/console I/O explicitly.
_TEST_POD = POD_ID.startswith("test-")
EVENT_LOG_FILE_ENABLED = (
    not _TEST_POD or os.getenv("EVENT_LOG_FILE_ENABLED", "1") == "1"
)
EVENT_LOG_STDOUT_ENABLED = (
    not _TEST_POD or os.getenv("EVENT_LOG_STDOUT_ENABLED", "1") == "1"
)
event_log_lock = threading.Lock()
_event_ring: deque = deque(maxlen=EVENT_RING_LIMIT)


def log_event(component: str, event: str, **detail):
    """บันทึกเหตุการณ์ระบบ: ring buffer (โชว์บนจอ/API) + ไฟล์ logs/events.jsonl"""
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "component": component,
        "event": event,
        **{k: v for k, v in detail.items() if v is not None},
    }
    with event_log_lock:
        _event_ring.append(entry)
        if EVENT_LOG_FILE_ENABLED:
            try:
                EVENT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
                with EVENT_LOG_PATH.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            except Exception as exc:
                if EVENT_LOG_STDOUT_ENABLED:
                    print(f"[LOG] write failed: {exc}")
    if EVENT_LOG_STDOUT_ENABLED:
        print(f"[{component.upper()}] {event} {detail if detail else ''}")


# ---------- local Safety Supervisor (Pi-local; no Internet dependency) ----------
_safety_action_lock = threading.Lock()


def _systemd_notify(message: str) -> bool:
    """Send watchdog/status notification directly from the main process."""
    address = os.getenv("NOTIFY_SOCKET")
    if not address:
        return False
    if address.startswith("@"):
        address = "\0" + address[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.connect(address)
            sock.sendall(message.encode("utf-8"))
        return True
    except Exception:
        return False


def _safety_faults() -> list:
    """Return current supervisory faults without treating stale values as live."""
    now = time.time()
    health = system_health_cached()
    with state_lock:
        e = dict(state["sensor"].get("esp32") or {})
        h2 = dict(state["sensor"].get("sensorhub2") or {})
        b = dict(state["sensor"].get("bcg") or {})
        session = dict(state.get("session") or {})
        gpio_ok = bool(state["system"].get("gpio_available"))
    environment = build_environment_snapshot(e, h2, now)
    occupied = bool(session.get("active") and session.get("recording"))
    return evaluate_safety_faults(
        now=now,
        health=health,
        environment=environment,
        esp32_last_update=e.get("last_update"),
        bcg_last_update=b.get("last_update"),
        occupied=occupied,
        gpio_ok=gpio_ok,
        thresholds=SafetyThresholds(
            basis_version=SAFETY_THRESHOLD_BASIS_VERSION,
            basis_approved=SAFETY_THRESHOLD_BASIS_APPROVED,
            require_co2=SAFETY_REQUIRE_CO2,
            esp32_stale_seconds=ESP32_STALE_SECONDS,
            bcg_stale_seconds=BCG_STALE_SECONDS,
            co2_warning_ppm=SAFETY_CO2_WARN_PPM,
            co2_fair_max_ppm=SAFETY_CO2_FAIR_MAX_PPM,
            co2_critical_ppm=SAFETY_CO2_CRITICAL_PPM,
            temperature_warning_min_c=SAFETY_TEMP_WARN_MIN_C,
            temperature_warning_max_c=SAFETY_TEMP_WARN_MAX_C,
            temperature_critical_min_c=SAFETY_TEMP_CRITICAL_MIN_C,
            temperature_critical_max_c=SAFETY_TEMP_CRITICAL_MAX_C,
        ),
    )


def apply_safety_profile(trigger: str) -> Dict[str, Any]:
    """Idempotent local safe profile. Door auto-open intentionally excluded."""
    results: Dict[str, Any] = {}
    with _safety_action_lock:
        # Reject new movement before sending STOP; otherwise a concurrent
        # request could restart a device between the stop and the latch.
        with state_lock:
            state["safety"]["latched"] = True
        try:
            player.stop()
            results["stop_music"] = True
        except Exception as exc:
            results.update({"stop_music": False, "music_error": str(exc)})
        for name in (
            "aroma1",
            "aroma2",
            "aroma3",
            "aroma4",
            "steam",
            "star_light",
            "red_light_face",
            "red_light_body",
            "red_light_leg",
            "door_open",
            "door_close",
        ):
            try:
                gpio.set(name, False)
                results[name] = False
            except Exception as exc:
                results[f"{name}_error"] = str(exc)
        try:
            gpio.set("led", True)
            results["led"] = True
        except Exception as exc:
            results["led_error"] = str(exc)
        # Bed movement is remote and must receive an explicit stop when the
        # local supervisor enters its safe profile.
        results["bed_stop"] = controlhub2_bed_mqtt.publish_stop_best_effort()
        action = {"at": time.time(), "trigger": trigger, "results": results}
        with state_lock:
            state["safety"]["last_action"] = action
        try:
            _refresh_active_session_safety_checkpoint(latched=True)
        except Exception as exc:
            # The live latch remains fail-safe even if durable storage is
            # unavailable. Surface the persistence failure for Admin review.
            log_event(
                "safety",
                "checkpoint_refresh_failed",
                operation="safe_profile",
                error=str(exc),
            )
        log_event("safety", "safe_profile_applied", trigger=trigger, results=results)
        return action


def safety_supervisor():
    previous_level = None
    while True:
        faults = _safety_faults()
        severities = {f["severity"] for f in faults}
        with state_lock:
            armed = bool(state["safety"].get("armed"))
            latched = bool(state["safety"].get("latched"))
        critical = "critical" in severities
        ready = not ({"critical", "blocking"} & severities)
        if armed and critical and not latched:
            trigger = ",".join(f["code"] for f in faults if f["severity"] == "critical")
            apply_safety_profile(trigger or "critical_fault")
            latched = True
        level = "emergency" if latched else "not_ready" if not ready else "degraded" if faults else "armed" if armed else "monitor"
        transition = time.time() if level != previous_level else None
        with state_lock:
            state["safety"].update(
                {
                    "ready": ready,
                    "level": level,
                    "faults": faults,
                    "last_check": time.time(),
                }
            )
            if transition is not None:
                state["safety"]["last_transition"] = transition
        if level != previous_level:
            log_event(
                "safety",
                "state",
                level=level,
                armed=armed,
                faults=[f["code"] for f in faults],
            )
            previous_level = level
        _systemd_notify(f"WATCHDOG=1\nSTATUS=Safety Supervisor: {level}")
        time.sleep(1)


# ---------- profile & session store (on-device only) ----------
profile_lock = threading.Lock()
sessions_file_lock = threading.Lock()
session_lock = threading.RLock()
last_sensor_frame_lock = threading.Lock()
ingest_outbox_lock = threading.RLock()
# RLock permits atomic nested Sleep lifecycle helpers.
sleep_path_lock = threading.RLock()
analysis_frame_lock = threading.Lock()
# {"record": {...}, "samples": [...], "counters": {...}, "last_sample": float}
_active_session: Optional[Dict[str, Any]] = None
acoustic_timeline_snapshot = live_timeline_reader(session_lock, lambda: _active_session)
_sleep_stage_path = {
    "session_id": None,
    "seen": [],
    "last": None,
    "stage_since": None,
    "candidate": None,
    "candidate_ticks": 0,
    "cycle_has_n1": False,
    "continuity_hold_ticks": 0,
    "sensor_tick_count": 0,
    "last_evidence_epoch_s": None,
    "last_evidence_result": None,
    "awake_vital_pairs": [],
    "awake_hr_reference": None,
    "awake_rr_reference": None,
    "sleep_onset_at": None,
    "last_valid_frame_t": None,
    "off_bed_latched": False,
    "restart_hold_result": None,
    "restart_hold_until_epoch_s": None,
}
_analysis_frame: Optional[Dict[str, Any]] = None
LAST_SENSOR_FRAME_VERSION = 1
INGEST_OUTBOX_VERSION = 1


def _log_invalid_session_checkpoint(exc: Exception) -> None:
    log_event("session", "restart_checkpoint_invalid", error=str(exc))


session_checkpoint_store = SessionCheckpointStore(
    path=ACTIVE_SESSION_CHECKPOINT_PATH,
    bed_start_seconds=BED_START_SECONDS,
    on_invalid=_log_invalid_session_checkpoint,
)
active_session_checkpoint_lock = session_checkpoint_store.lock
ACTIVE_SESSION_CHECKPOINT_VERSION = SESSION_CHECKPOINT_VERSION


def _active_session_checkpoint_payload(active: Dict[str, Any]) -> Dict[str, Any]:
    """Compatibility facade for the extracted Session checkpoint store."""
    return session_checkpoint_store.build_payload(_active_with_sleep_context(active))


def _save_active_session_checkpoint(active: Dict[str, Any]) -> Dict[str, Any]:
    """Compatibility facade for durable Session checkpoint persistence."""
    with session_lock:
        if active is not _active_session:
            return {}
        return session_checkpoint_store.save(_active_with_sleep_context(active))


def _load_active_session_checkpoint() -> Optional[Dict[str, Any]]:
    return session_checkpoint_store.load()


def _clear_active_session_checkpoint() -> None:
    session_checkpoint_store.clear()


def _current_safety_checkpoint_context() -> Dict[str, bool]:
    """Return only Safety conditions that are safe to carry across restart."""
    with state_lock:
        safety = state["safety"]
        return {key: True for key in ("armed", "latched") if bool(safety.get(key))}


def _restore_safety_checkpoint_context(
    checkpoint: Dict[str, Any],
) -> Dict[str, bool]:
    """Restore optional Safety booleans from a validated v1 checkpoint."""
    saved = checkpoint.get("safety_context")
    if not isinstance(saved, dict):
        return _current_safety_checkpoint_context()
    with state_lock:
        for key in ("armed", "latched"):
            # Persisted state may only increase protection. A legacy false
            # value is ignored so disarm remains process-local.
            if saved.get(key) is True:
                state["safety"][key] = True
        return {key: True for key in ("armed", "latched") if bool(state["safety"].get(key))}


def _refresh_active_session_safety_checkpoint(
    *,
    armed: Optional[bool] = None,
    latched: Optional[bool] = None,
) -> bool:
    """Atomically refresh Safety continuity for an active Session."""
    with session_lock:
        active = _active_session
        if active is None:
            return False
        previous = active.get("safety_context")
        safety_context = dict(previous or {})
        for key, value in (("armed", armed), ("latched", latched)):
            if value is True:
                safety_context[key] = True
            elif value is False:
                safety_context.pop(key, None)
        active["safety_context"] = safety_context
        try:
            _save_active_session_checkpoint(active)
        except Exception:
            if previous is None:
                active.pop("safety_context", None)
            else:
                active["safety_context"] = previous
            raise
    return True


def _persist_last_sensor_frame(frame: Optional[Dict[str, Any]]) -> bool:
    """Atomically preserve the last canonical frame for an orderly restart."""
    if not isinstance(frame, dict) or not isinstance(frame.get("environment"), dict):
        return False
    payload = {
        "schema_version": LAST_SENSOR_FRAME_VERSION,
        "saved_at_utc": datetime.now(timezone.utc).isoformat(),
        "frame": json.loads(json.dumps(frame)),
    }
    with last_sensor_frame_lock:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        temporary = LAST_SENSOR_FRAME_PATH.with_suffix(".json.tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, LAST_SENSOR_FRAME_PATH)
    return True


def _load_last_sensor_frame() -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Read a restart frame without ever treating it as current telemetry."""
    try:
        with last_sensor_frame_lock:
            with LAST_SENSOR_FRAME_PATH.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        if not isinstance(payload, dict):
            raise ValueError("restart Sensor frame is not an object")
        if payload.get("schema_version") != LAST_SENSOR_FRAME_VERSION:
            raise ValueError("unsupported restart Sensor frame version")
        frame = payload.get("frame")
        if not isinstance(frame, dict) or not isinstance(frame.get("environment"), dict):
            raise ValueError("restart Sensor frame is incomplete")
        epoch_s = float(frame.get("epoch_s"))
        if not math.isfinite(epoch_s) or epoch_s <= 0:
            raise ValueError("restart Sensor frame has invalid time")
        return frame, str(payload.get("saved_at_utc") or "") or None
    except FileNotFoundError:
        return None, None
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        log_event("sensor_frame", "restart_cache_invalid", error=str(exc))
        return None, None


def _timeline_restart_frame() -> Optional[Dict[str, Any]]:
    """Build the first-deployment fallback from the active Session timeline."""
    with session_lock:
        active = _active_session
        session_id = (active or {}).get("record", {}).get("session_id")
        samples = list((active or {}).get("samples") or [])
    if not session_id or not samples:
        return None
    sample = next(
        (
            item
            for item in reversed(samples)
            if any(
                item.get(key) is not None
                for key in (
                    "temp",
                    "hum",
                    "co2",
                    "pm2_5",
                    "voc",
                    "lux",
                    "dba",
                    "hr",
                    "rr",
                    "bed",
                )
            )
        ),
        None,
    )
    if sample is None:
        return None
    epoch_s = float(sample.get("t") or 0)
    if not math.isfinite(epoch_s) or epoch_s <= 0:
        return None
    restart_sound = sample.get("dba")
    if not valid_sound_level(
        restart_sound,
        SOUND_DBA_DISPLAY_MIN,
        SOUND_DBA_DISPLAY_MAX,
    ):
        restart_sound = None
    values = {
        "temperature_c": sample.get("temp"),
        "humidity_rh": sample.get("hum"),
        "lux": sample.get("lux"),
        "sound_dba_est": restart_sound,
        "co2_ppm": sample.get("co2"),
        "pm1_0_ug_m3": None,
        "pm2_5_ug_m3": sample.get("pm2_5"),
        "pm10_ug_m3": None,
        "voc_index": sample.get("voc"),
        "sgp40_raw": None,
    }
    availability = {
        "sht3x_dis": values["temperature_c"] is not None and values["humidity_rh"] is not None,
        "opt3001": values["lux"] is not None,
        "sph0645": values["sound_dba_est"] is not None,
        "mhz19c": values["co2_ppm"] is not None,
        "pms7003": values["pm2_5_ug_m3"] is not None,
        "sgp40": values["voc_index"] is not None,
    }
    models = {
        "sht3x_dis": "SHT3x-DIS",
        "opt3001": "OPT3001",
        "sph0645": ENVIRONMENT_DEVICE_SPECS["sph0645"]["model"],
        "mhz19c": "MH-Z19C",
        "pms7003": "PMS7003",
        "sgp40": "SGP40",
    }
    devices = {
        key: {
            "model": models[key],
            "status": "stale" if available else "offline",
            "source": "session_timeline",
            "source_label": "Session Timeline · SQLite",
            "data_age_s": round(max(0.0, time.time() - epoch_s), 1),
            "invalid_values": {},
        }
        for key, available in availability.items()
    }
    bed_text = sample.get("bed")
    status_code = next((code for code, text in STATUS_TEXT.items() if text == bed_text), None)
    environment = {
        **values,
        "temperature": values["temperature_c"],
        "humidity": values["humidity_rh"],
        "co2": values["co2_ppm"],
        "pm2_5": values["pm2_5_ug_m3"],
        "raw_values": dict(values),
        "calibration": {},
        "devices": devices,
        "live_count": 0,
        "total_count": len(devices),
        "status": "stale" if any(availability.values()) else "offline",
        "sources": {
            "timeline": {
                "label": "Session Timeline · SQLite",
                "live": False,
                "age_s": round(max(0.0, time.time() - epoch_s), 1),
                "has_history": True,
            },
        },
    }
    return {
        "sequence": int(epoch_s // SLEEP_SAMPLE_SECONDS),
        "timestamp": datetime.fromtimestamp(epoch_s, timezone.utc).isoformat(),
        "epoch_s": epoch_s,
        "refresh_s": SLEEP_SAMPLE_SECONDS,
        "evidence_refresh_s": SLEEP_EVIDENCE_EPOCH_SECONDS,
        "confirmation_s": SLEEP_CONFIRMATION_SECONDS,
        "provisional_hold_max_epochs": SLEEP_PROVISIONAL_HOLD_EPOCHS,
        "source": "session_timeline",
        "session_id": session_id,
        "environment": environment,
        "bcg": {
            "analysis_epoch_s": epoch_s,
            "status_code": status_code,
            "status_text": bed_text,
            "heart_rate_bpm": sample.get("hr"),
            "respiration_rate": sample.get("rr"),
            "bcg_frames": 0,
            "analysis_valid": False,
            "analysis_source_connected": False,
        },
        "sleep": {},
    }


def _restore_latest_sensor_frame() -> bool:
    """Publish the newest saved values immediately, explicitly as stale."""
    global _analysis_frame
    cached, saved_at_utc = _load_last_sensor_frame()
    timeline = _timeline_restart_frame()
    candidates = [frame for frame in (cached, timeline) if isinstance(frame, dict)]
    if not candidates:
        return False
    with state_lock:
        current_session_id = state["session"].get("session_id")
        session_recording = bool(state["session"].get("recording"))
    frame = max(candidates, key=lambda item: float(item.get("epoch_s") or 0))
    original_session_id = frame.get("session_id")
    same_session = bool(current_session_id and original_session_id == current_session_id)
    restored = json.loads(json.dumps(frame))
    environment = restored.get("environment") or {}
    for device in (environment.get("devices") or {}).values():
        if device.get("status") not in {"offline", "fault", "invalid", "no_data"}:
            device["status"] = "stale"
        device["data_age_s"] = round(max(0.0, time.time() - float(restored["epoch_s"])), 1)
    environment["live_count"] = 0
    environment["status"] = (
        "stale"
        if any(
            value is not None
            for key, value in environment.items()
            if key
            in {
                "temperature_c",
                "humidity_rh",
                "lux",
                "sound_dba_est",
                "co2_ppm",
                "pm2_5_ug_m3",
                "voc_index",
            }
        )
        else "offline"
    )
    bcg = dict(restored.get("bcg") or {}) if same_session else {}
    bcg.update(
        {
            "analysis_valid": False,
            "analysis_stale": True,
            "analysis_source_connected": False,
            "restored_after_restart": True,
        }
    )
    # The Timeline row can be a few seconds newer than the analysis frame, but
    # it deliberately contains no current Sleep label.  Environment/BCG may
    # use that freshest row; the restart bridge must come from the separately
    # persisted analysis frame that actually carried the confirmed decision.
    sleep_source_frame = cached if isinstance(cached, dict) and cached.get("session_id") == current_session_id else frame
    held_sleep = (
        _install_restart_sleep_hold(
            dict(sleep_source_frame.get("sleep") or {}),
            session_id=current_session_id,
            source_epoch_s=float(sleep_source_frame["epoch_s"]),
        )
        if same_session
        else None
    )
    with sleep_path_lock:
        restored_off_bed = bool(_sleep_stage_path.get("off_bed_latched"))
    restart_fallback = {
        "state": "off_bed" if restored_off_bed else "no_data",
        "confirmed_state": None,
        "version": SLEEP_ESTIMATOR_VERSION,
        "evidence_version": SLEEP_EVIDENCE_VERSION,
        "classification_active": False,
        "evidence_active": False,
        "probabilities": {key: 0.0 for key in ZEEP_SLEEP_STATES},
        "confidence": "low",
        "data_status": ("empty_bed" if restored_off_bed else "restored_waiting_live_frame"),
        "reason": ("สถานะล่าสุดยืนยัน OFF BED · รอหลักฐานว่ากลับขึ้นเตียง" if restored_off_bed else "แสดงค่าล่าสุดก่อน Restart · รอ Sensor frame สด"),
        "score_eligible": False,
        "excluded_from_score": True,
        "excluded_from_personal_baseline": True,
    }
    if same_session and session_recording and not restored_off_bed:
        confirmation = continuity_hold_contract(
            None,
            decision="restart_initial_awake_anchor",
        )
        restart_fallback.update(
            {
                "state": "wake",
                "confirmed_state": "wake",
                "classification_active": True,
                "provisional": False,
                "data_status": confirmation["data_status"],
                "reason": "Session กำลังบันทึก · เริ่มความต่อเนื่องที่ W",
                "score_eligible": True,
                "excluded_from_score": False,
                "confirmation": confirmation,
                "score_attribution_state": "wake",
            }
        )
    restored.update(
        {
            "source": "restored_after_restart",
            "restored_source": frame.get("source") or "unknown",
            "restored_after_restart": True,
            "restored_at_utc": datetime.now(timezone.utc).isoformat(),
            "saved_at_utc": saved_at_utc,
            "session_id": current_session_id,
            "environment": environment,
            "bcg": bcg,
            "sleep": held_sleep or restart_fallback,
        }
    )
    with analysis_frame_lock:
        _analysis_frame = restored
    _sleep_cache.update(
        {
            "t": time.monotonic(),
            "value": json.loads(json.dumps(held_sleep or restart_fallback)),
            "session_id": current_session_id,
            "sequence": None,
        }
    )
    log_event(
        "sensor_frame",
        "restored_after_restart",
        source=restored["restored_source"],
        data_age_s=round(max(0.0, time.time() - float(restored["epoch_s"])), 1),
        same_session=same_session,
        sleep_state_held=bool(held_sleep),
        held_state=held_sleep.get("state") if held_sleep else None,
    )
    return True


def _reset_sleep_stage_path(session_id: Optional[str]) -> None:
    """Reset the per-session semi-Markov memory; caller holds sleep_path_lock."""
    _sleep_stage_path.update(
        {
            "session_id": session_id,
            "seen": [],
            "last": None,
            "stage_since": None,
            "candidate": None,
            "candidate_ticks": 0,
            "cycle_has_n1": False,
            "continuity_hold_ticks": 0,
            "probability_ema": None,
            "sensor_tick_count": 0,
            "last_evidence_epoch_s": None,
            "last_evidence_result": None,
            "awake_vital_pairs": [],
            "awake_hr_reference": None,
            "awake_rr_reference": None,
            "sleep_onset_at": None,
            "last_valid_frame_t": None,
            "off_bed_latched": False,
            "restart_hold_result": None,
            "restart_hold_until_epoch_s": None,
        }
    )


def _clear_restart_sleep_hold_locked() -> None:
    """Clear restart-only display state; caller holds ``sleep_path_lock``."""
    _sleep_stage_path["restart_hold_result"] = None
    _sleep_stage_path["restart_hold_until_epoch_s"] = None
    cached = _sleep_stage_path.get("last_evidence_result")
    if isinstance(cached, dict) and cached.get("display_only_after_restart"):
        _sleep_stage_path["last_evidence_result"] = None


def _install_restart_sleep_hold(
    source_sleep: Dict[str, Any],
    *,
    session_id: Optional[str],
    source_epoch_s: float,
) -> Optional[Dict[str, Any]]:
    """Restore a verified pre-restart label as occupied continuity.

    Trust the saved frame only when it matches this Session's latest durable
    State. Keep that State until fresh evidence confirms a challenger; a
    confirmed OFF BED event still overrides it.
    """
    source_stage = source_sleep.get("confirmed_state") or source_sleep.get("state")
    with sleep_path_lock:
        durable_stage = _sleep_stage_path.get("last")
        if not (session_id and _sleep_stage_path.get("session_id") == session_id and source_sleep.get("classification_active") is True and source_stage in ZEEP_SLEEP_STATES and source_stage == durable_stage and not _sleep_stage_path.get("off_bed_latched")):
            _clear_restart_sleep_hold_locked()
            return None
        held = json.loads(json.dumps(source_sleep))
        confirmation = continuity_hold_contract(
            durable_stage,
            decision="restart_continuity_hold",
        )
        held.update(
            {
                "state": durable_stage,
                "confirmed_state": durable_stage,
                "classification_active": True,
                "evidence_active": False,
                "confidence": "low",
                "provisional": False,
                "data_status": "restored_confirmed_state",
                "reason": ("ยึดสถานะยืนยันล่าสุดก่อน Restart · กำลังสร้างหลักฐานสดรอบใหม่"),
                "held_previous_state": bool(confirmation["held_previous_state"]),
                "score_attribution_state": confirmation["score_attribution_state"],
                "challenger_counted_as_new_state": False,
                "score_eligible": bool(confirmation["score_eligible"]),
                "excluded_from_score": bool(confirmation["excluded_from_score"]),
                "excluded_from_personal_baseline": True,
                "confirmation": confirmation,
                "display_only_after_restart": False,
                "restored_after_restart": True,
                "restored_source_epoch_s": source_epoch_s,
                "restart_hold_max_s": RESTART_SLEEP_STATE_HOLD_SECONDS,
            }
        )
        # A code restart begins a new confirmation window.  Preserve the
        # durable State itself, but never inherit a pending challenger or the
        # score-eligibility age of a pre-restart continuity hold.
        _sleep_stage_path["candidate"] = None
        _sleep_stage_path["candidate_ticks"] = 0
        _sleep_stage_path["continuity_hold_ticks"] = 0
        _sleep_stage_path["probability_ema"] = None
        _sleep_stage_path["restart_hold_result"] = json.loads(json.dumps(held))
        _sleep_stage_path["restart_hold_until_epoch_s"] = time.time() + RESTART_SLEEP_STATE_HOLD_SECONDS
        _sleep_stage_path["last_evidence_result"] = json.loads(json.dumps(held))
        return held


def _restart_sleep_hold_result(session_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """Return the unexpired display-only restart bridge for this Session."""
    with sleep_path_lock:
        held = _sleep_stage_path.get("restart_hold_result")
        expires = _sleep_stage_path.get("restart_hold_until_epoch_s")
        valid = bool(session_id and _sleep_stage_path.get("session_id") == session_id and isinstance(held, dict) and held.get("state") == _sleep_stage_path.get("last") and isinstance(expires, (int, float)) and time.time() <= float(expires))
        if not valid:
            _clear_restart_sleep_hold_locked()
            return None
        value = json.loads(json.dumps(held))
        value["restart_hold_remaining_s"] = max(0, round(float(expires) - time.time()))
        return value


def _median(values: List[float]) -> Optional[float]:
    ordered = sorted(float(value) for value in values if math.isfinite(float(value)))
    if not ordered:
        return None
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _upper_quartile(values: List[float]) -> Optional[float]:
    """Robust high reference for the pre-onset within-Session physiology."""
    ordered = sorted(float(value) for value in values if math.isfinite(float(value)))
    if not ordered:
        return None
    return ordered[min(len(ordered) - 1, int(round((len(ordered) - 1) * 0.75)))]


def _active_with_sleep_context(active: Dict[str, Any]) -> Dict[str, Any]:
    """Attach only restart-safe Sleep context to a checkpoint copy."""
    checkpoint_active = dict(active)
    session_id = (active.get("record") or {}).get("session_id")
    with sleep_path_lock:
        context = checkpoint_sleep_context(_sleep_stage_path, session_id)
    if context is not None:
        checkpoint_active["sleep_context"] = context
    return checkpoint_active


def _update_sleep_session_context(
    frames: List[Dict[str, Any]],
    *,
    now: float,
    session_started: Optional[float],
) -> Dict[str, Any]:
    """Maintain prior-only awake references across transient evidence gaps.

    Confirmed pre-onset frames form a within-Session settling reference; they
    are not ground-truth Wake labels.  The upper quartile is used because the
    first few packets can arrive after the occupant has already relaxed and a
    low first-packet median would otherwise trap the path in Wake all night.
    Historical behaviour may describe
    expected onset/time-of-day, but never overwrites these observed HR/RR
    references or directly selects a Sleep State.

    A missing HR/RR window is an observation gap, not physiological evidence
    that a sleeping occupant woke up.  On recovery we therefore discard only
    an incomplete challenger and its EMA.  The last confirmed state, the
    established sleep sequence, the original onset and the pre-onset awake
    reference survive while the same Session remains active. Session-owner
    changes and confirmed Bed Exit continue to use their dedicated paths.
    """
    valid = [frame for frame in frames if frame.get("bcg_valid") and isinstance(frame.get("hr"), (int, float)) and isinstance(frame.get("rr"), (int, float)) and isinstance(frame.get("t"), (int, float))]
    with sleep_path_lock:
        latest_t = float(valid[-1]["t"]) if valid else None
        previous_t = _sleep_stage_path.get("last_valid_frame_t")
        gap_detected = bool(latest_t is not None and isinstance(previous_t, (int, float)) and latest_t - float(previous_t) >= SLEEP_CONTEXT_RESET_GAP_SECONDS)
        if gap_detected:
            # Do not turn a telemetry/processing gap into Wake.  Clear only
            # evidence that was still waiting for confirmation; continuity
            # state is retained and will be challenged by fresh evidence.
            _sleep_stage_path["candidate"] = None
            _sleep_stage_path["candidate_ticks"] = 0
            _sleep_stage_path["probability_ema"] = None
            _sleep_stage_path["last_evidence_result"] = None
        if latest_t is not None:
            _sleep_stage_path["last_valid_frame_t"] = latest_t

        references = list(_sleep_stage_path.get("awake_vital_pairs") or [])
        known_times = {item[0] for item in references if len(item) == 3}
        sleep_onset_at = _sleep_stage_path.get("sleep_onset_at")
        for frame in valid:
            timestamp = float(frame["t"])
            if sleep_onset_at is not None:
                continue
            if timestamp not in known_times:
                references.append((timestamp, float(frame["hr"]), float(frame["rr"])))
                known_times.add(timestamp)
        # Two hours covers delayed sleep onset without unbounded memory. The
        # high quantile remains robust to a short low-valued startup window.
        references = sorted(references, key=lambda item: item[0])[-720:]
        _sleep_stage_path["awake_vital_pairs"] = references
        if len(references) >= 6:
            _sleep_stage_path["awake_hr_reference"] = _upper_quartile([item[1] for item in references])
            _sleep_stage_path["awake_rr_reference"] = _upper_quartile([item[2] for item in references])
        return {
            "awake_hr_reference": _sleep_stage_path.get("awake_hr_reference"),
            "awake_rr_reference": _sleep_stage_path.get("awake_rr_reference"),
            "awake_reference_pairs": len(references),
            "sleep_onset_established": sleep_onset_at is not None,
            "sleep_elapsed_min": (max(0.0, (now - float(sleep_onset_at)) / 60.0) if isinstance(sleep_onset_at, (int, float)) else 0.0),
            # ``gap_reset`` is retained for response compatibility.  It now
            # truthfully reports that no full context reset was performed.
            "gap_reset": False,
            "gap_detected": gap_detected,
            "context_preserved_after_gap": bool(gap_detected and _sleep_stage_path.get("last") is not None),
        }


def _advance_sleep_evidence_clock(session_id: Optional[str]) -> Dict[str, Any]:
    """Advance one 10-second sensor frame and schedule a 30-second epoch.

    The clock belongs to the active Session rather than wall-clock boundaries,
    so a newly recording user always contributes three complete sensor frames
    before the first physiological evidence summary is produced.
    """
    with sleep_path_lock:
        if _sleep_stage_path.get("session_id") != session_id:
            _reset_sleep_stage_path(session_id)
        _sleep_stage_path["sensor_tick_count"] = int(_sleep_stage_path.get("sensor_tick_count") or 0) + 1
        tick_count = int(_sleep_stage_path["sensor_tick_count"])
        frame_in_epoch = ((tick_count - 1) % SLEEP_SENSOR_FRAMES_PER_EPOCH) + 1
        due = frame_in_epoch == SLEEP_SENSOR_FRAMES_PER_EPOCH
        frames_remaining = 0 if due else SLEEP_SENSOR_FRAMES_PER_EPOCH - frame_in_epoch
        return {
            "sensor_tick_count": tick_count,
            "frame_in_epoch": frame_in_epoch,
            "sensor_frames_per_epoch": SLEEP_SENSOR_FRAMES_PER_EPOCH,
            "evidence_due": due,
            "frames_remaining": frames_remaining,
            "next_evidence_s": frames_remaining * SLEEP_SAMPLE_SECONDS,
        }


def _remember_sleep_evidence(result: Dict[str, Any], epoch_s: float) -> None:
    with sleep_path_lock:
        _sleep_stage_path["last_evidence_epoch_s"] = epoch_s
        _sleep_stage_path["last_evidence_result"] = json.loads(json.dumps(result))


def _last_sleep_evidence_result() -> Optional[Dict[str, Any]]:
    with sleep_path_lock:
        value = _sleep_stage_path.get("last_evidence_result")
        return json.loads(json.dumps(value)) if isinstance(value, dict) else None


def _apply_stage_to_path(stage: str, now: Optional[float] = None) -> None:
    """Keep the current sleep-cycle trail; WAKE starts a new cycle."""
    now = time.time() if now is None else now
    seen = _sleep_stage_path["seen"]
    if stage == "wake":
        seen.clear()
        _sleep_stage_path["cycle_has_n1"] = False
        # Preserve the first Session onset across a brief Wake. A new N1 is
        # still required before deeper stages, while a signal/off-bed reset
        # continues to clear the complete Session context.
    elif stage == "n1":
        _sleep_stage_path["cycle_has_n1"] = True
        if _sleep_stage_path.get("sleep_onset_at") is None:
            _sleep_stage_path["sleep_onset_at"] = now
    if _sleep_stage_path["last"] != stage:
        seen.append(stage)
        del seen[:-8]
        _sleep_stage_path["stage_since"] = now
        _sleep_stage_path["candidate"] = None
        _sleep_stage_path["candidate_ticks"] = 0
        _sleep_stage_path["continuity_hold_ticks"] = 0
    _sleep_stage_path["last"] = stage


def _latch_confirmed_bed_exit(
    session_id: Optional[str],
    *,
    now: float,
) -> bool:
    """Keep OFF BED authoritative until fresh on-bed vitals return."""
    with sleep_path_lock:
        if _sleep_stage_path.get("session_id") != session_id:
            _reset_sleep_stage_path(session_id)
        changed = not bool(_sleep_stage_path.get("off_bed_latched"))
        _apply_stage_to_path("wake", now=now)
        _sleep_stage_path["off_bed_latched"] = True
        _sleep_stage_path["probability_ema"] = None
        _clear_restart_sleep_hold_locked()
    if changed:
        with session_lock:
            active = _active_session
        if active is not None and active.get("phase") == "recording" and active["record"].get("session_id") == session_id:
            try:
                _save_active_session_checkpoint(active)
            except Exception as exc:
                log_event(
                    "session",
                    "off_bed_checkpoint_failed",
                    session_id=session_id,
                    error=str(exc),
                )
    return changed


def _off_bed_remains_latched(
    *,
    status_code: Any,
    current_vitals_valid: bool,
) -> bool:
    """Release OFF BED only on affirmative Bed Status plus fresh vitals."""
    released = False
    with sleep_path_lock:
        latched = bool(_sleep_stage_path.get("off_bed_latched"))
        if latched and status_code in ON_BED_CODES and current_vitals_valid:
            _sleep_stage_path["off_bed_latched"] = False
            released = True
            latched = False
    if released:
        with session_lock:
            active = _active_session
        if active is not None and active.get("phase") == "recording":
            try:
                _save_active_session_checkpoint(active)
            except Exception as exc:
                log_event(
                    "session",
                    "on_bed_checkpoint_failed",
                    session_id=active["record"].get("session_id"),
                    error=str(exc),
                )
    return latched


def _sleep_decision_provenance() -> Dict[str, str]:
    """Versions persisted with every decision and final Session summary."""
    return {
        "estimator_version": SLEEP_ESTIMATOR_VERSION,
        "evidence_version": SLEEP_EVIDENCE_VERSION,
        "baseline_version": ZEEP_SLEEP_BASELINE_VERSION,
        "transition_policy_version": ZEEP_SLEEP_TRANSITION_POLICY_VERSION,
        "g2_ontology_version": SLEEP_G2_ONTOLOGY_VERSION,
    }


def _persist_sleep_stage_evidence(
    candidate: Optional[str],
    probabilities: Dict[str, float],
    reason: str,
    *,
    confidence: Optional[str] = None,
    metrics: Optional[Dict[str, Any]] = None,
    window_start: Optional[str] = None,
    window_end: Optional[str] = None,
    sample_count: Optional[int] = None,
    confirmation: Optional[Dict[str, Any]] = None,
) -> None:
    """Persist physiological evidence without presenting it as a stage.

    One record represents a 30-second evidence epoch assembled from three
    10-second sensor frames. A separate ``sleep_stage`` record is written only
    for the currently confirmed state, preserving a clear audit boundary.
    """
    with state_lock:
        session_id = state["session"].get("session_id")
    with session_lock:
        persist = bool(_active_session and _active_session.get("phase") == "recording" and _active_session["record"].get("session_id") == session_id)
    if not persist:
        return
    database.enqueue(
        "sessions",
        "event",
        {
            "session_id": session_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": "sleep_stage_evidence",
            "value": {
                "candidate": candidate,
                "probabilities": probabilities,
                "confidence": confidence,
                "reason": reason,
                "metrics": metrics or {},
                **_sleep_decision_provenance(),
                "window_start": window_start,
                "window_end": window_end,
                "sample_count": sample_count,
                "sensor_sample_interval_s": SLEEP_SAMPLE_SECONDS,
                "evidence_epoch_s": SLEEP_EVIDENCE_EPOCH_SECONDS,
                "confirmation": confirmation or {},
                "decision_kind": "physiological_evidence",
            },
        },
    )


def _persist_sleep_stage_status(
    sleep_result: Dict[str, Any],
    *,
    epoch_s: float,
) -> None:
    """Persist confirmed OFF BED; never persist a Recording data gap."""
    with state_lock:
        session_id = state["session"].get("session_id")
        state_recording = bool(state["session"].get("recording"))
    data_status = str(sleep_result.get("data_status") or "").lower()
    off_bed = bool(sleep_result.get("state") == "off_bed" or data_status in ZEEP_OFF_BED_DATA_STATUSES - {"no_session"})
    with session_lock:
        active = _active_session
        recording = bool(state_recording and off_bed and active and active.get("phase") == "recording" and active["record"].get("session_id") == session_id)
    if not recording:
        return
    database.enqueue(
        "sessions",
        "event",
        _build_sleep_status_event(
            sleep_result,
            session_id=str(session_id),
            epoch_s=float(epoch_s),
            evidence_epoch_s=SLEEP_EVIDENCE_EPOCH_SECONDS,
            provenance=_sleep_decision_provenance(),
        ),
    )


def _commit_sleep_stage(
    stage: str,
    probabilities: Dict[str, float],
    reason: str,
    *,
    confidence: Optional[str] = None,
    metrics: Optional[Dict[str, Any]] = None,
    window_start: Optional[str] = None,
    window_end: Optional[str] = None,
    sample_count: Optional[int] = None,
    confirmation: Optional[Dict[str, Any]] = None,
) -> list:
    with state_lock:
        session_id = state["session"].get("session_id")
    with sleep_path_lock:
        if _sleep_stage_path["session_id"] != session_id:
            _reset_sleep_stage_path(session_id)
        changed = _sleep_stage_path["last"] != stage
        _apply_stage_to_path(stage)
        # A completed live evidence epoch now owns the display again.  The
        # pre-restart bridge must disappear before this decision is persisted.
        _clear_restart_sleep_hold_locked()
        seen = list(_sleep_stage_path["seen"])
    # Persist one five-state attribution per valid on-bed 30-second epoch. A
    # continuity-hold row attributes time to the preceding confirmed State;
    # its challenger remains only in Evidence/confirmation metadata.
    with session_lock:
        active_for_checkpoint = _active_session
        persist_decision = bool(active_for_checkpoint and active_for_checkpoint.get("phase") == "recording" and active_for_checkpoint["record"].get("session_id") == session_id)
    if persist_decision:
        database.enqueue(
            "sessions",
            "event",
            {
                "session_id": session_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "type": "sleep_stage",
                "value": {
                    "state": stage,
                    "probabilities": probabilities,
                    "confidence": confidence,
                    "reason": reason,
                    "progression": seen,
                    "metrics": metrics or {},
                    **_sleep_decision_provenance(),
                    "window_start": window_start,
                    "window_end": window_end,
                    "attribution_start": (
                        datetime.fromtimestamp(
                            datetime.fromisoformat(window_end).timestamp() - SLEEP_EVIDENCE_EPOCH_SECONDS,
                            timezone.utc,
                        ).isoformat()
                        if window_end
                        else None
                    ),
                    "attribution_end": window_end,
                    "sample_count": sample_count,
                    "sensor_sample_interval_s": SLEEP_SAMPLE_SECONDS,
                    "sample_interval_s": SLEEP_EVIDENCE_EPOCH_SECONDS,
                    "confirmation_seconds": float(
                        (confirmation or {}).get(
                            "confirmation_seconds",
                            SLEEP_STAGE_CONFIRMATION_SECONDS.get(stage, SLEEP_CONFIRMATION_SECONDS),
                        )
                    ),
                    "confirmation": confirmation or {},
                    "decision_kind": ((confirmation or {}).get("decision_kind") or "confirmed_state"),
                    "held_previous_state": bool((confirmation or {}).get("held_previous_state")),
                    "provisional": bool((confirmation or {}).get("provisional")),
                    "pending_state": (confirmation or {}).get("pending_state"),
                    "score_attribution_state": stage,
                    "challenger_counted_as_new_state": bool((confirmation or {}).get("challenger_counted_as_new_state")),
                    "score_eligible": bool((confirmation or {}).get("score_eligible", True)),
                    "excluded_from_score": bool((confirmation or {}).get("excluded_from_score", False)),
                    "excluded_from_personal_baseline": bool((confirmation or {}).get("excluded_from_personal_baseline", False)),
                    "state_changed": changed,
                },
            },
        )
        if changed:
            try:
                _save_active_session_checkpoint(active_for_checkpoint)
            except Exception as exc:
                log_event(
                    "session",
                    "sleep_context_checkpoint_failed",
                    session_id=session_id,
                    error=str(exc),
                )
    return seen


def _transition_allowed(candidate: str, *, strong_wake: bool = False) -> tuple[bool, Optional[str]]:
    """Apply the ZEEP continuity graph to noisy non-EEG estimates."""
    with sleep_path_lock:
        previous = _sleep_stage_path["last"]
        cycle_has_n1 = bool(_sleep_stage_path.get("cycle_has_n1"))
    return _path_transition_allowed(
        candidate,
        previous=previous,
        cycle_has_n1=cycle_has_n1,
        strong_wake=strong_wake,
        allowed_transitions=SLEEP_ALLOWED_TRANSITIONS,
    ), previous


def _transition_fallback_state(blocked: str, previous: Optional[str]) -> str:
    """Hold the last confirmed State; never fabricate a bridge label."""
    return _path_transition_fallback_state(
        previous,
        sleep_states=ZEEP_SLEEP_STATES,
    )


def _stabilize_sleep_stage(candidate: str, *, now: float, strong_wake: bool = False) -> tuple[str, Dict[str, Any]]:
    """Resolve adjacency, dwell and repeated evidence under the path lock."""
    allowed, previous = _transition_allowed(candidate, strong_wake=strong_wake)
    target = candidate if allowed else _transition_fallback_state(candidate, previous)
    with sleep_path_lock:
        return stabilize_path_transition(
            _sleep_stage_path,
            candidate=candidate,
            target=target,
            allowed=allowed,
            previous=previous,
            strong_wake=strong_wake,
            now=now,
            policy_version=ZEEP_SLEEP_TRANSITION_POLICY_VERSION,
            stage_confirmation_seconds=SLEEP_STAGE_CONFIRMATION_SECONDS,
            default_confirmation_seconds=SLEEP_CONFIRMATION_SECONDS,
            confirm_epochs=SLEEP_CONFIRM_EPOCHS,
            confirm_ticks=SLEEP_STAGE_CONFIRM_TICKS,
            minimum_dwell_seconds=SLEEP_STAGE_MIN_DWELL_SECONDS,
        )


def _physiological_baseline_fit(hr_fit: float, rr_fit: float) -> float:
    """Combine HR/RR proximity using the versioned ZEEP scoring weights."""
    return SLEEP_BASELINE_HR_WEIGHT * hr_fit + SLEEP_BASELINE_RR_WEIGHT * rr_fit


def _rr_n3_conflict_adjustment(rr_stage_fits: Dict[str, float]) -> Dict[str, float]:
    """Resist an N3 label when mean RR fits N2 better than N3.

    Mean respiratory rate alone is not a clinical discriminator between N2
    and N3. This guard therefore only resolves a disagreement inside the ZEEP
    baseline score; it cannot create a stage and does not replace RR
    variability, movement, transition order or future PSG validation.
    """
    conflict = max(0.0, float(rr_stage_fits.get("n2", 0.0)) - float(rr_stage_fits.get("n3", 0.0)))
    return {
        "conflict": conflict,
        "n3_penalty": conflict * SLEEP_N3_RR_CONFLICT_PENALTY,
        "n2_support": conflict * SLEEP_N2_RR_CONFLICT_SUPPORT,
    }


def _sleep_environment_context(
    environment: Dict[str, Any],
    rest_mode: Any = "sleep",
) -> Dict[str, Any]:
    """Bind runtime policy versions to the pure environment assessment."""
    return _build_sleep_environment_context(
        environment,
        rest_mode,
        context_version=ENVIRONMENT_CONTEXT_POLICY_VERSION,
        baseline_version=ZEEP_SLEEP_BASELINE_VERSION,
    )


def _sleep_auxiliary_evidence(
    frames: List[Dict[str, Any]],
    statuses: List[int],
    movement_ratio: float,
    waveform_signal: Dict[str, Any],
) -> Dict[str, Any]:
    """Bind runtime thresholds to auditable audio/Bed corroboration."""
    return _build_sleep_auxiliary_evidence(
        frames,
        statuses,
        movement_ratio,
        waveform_signal,
        acoustic_disturbance_dba=SLEEP_ACOUSTIC_DISTURBANCE_DBA,
        acoustic_min_coverage=SLEEP_ACOUSTIC_MIN_COVERAGE,
        acoustic_wake_support_max=SLEEP_ACOUSTIC_WAKE_SUPPORT_MAX,
        move_wake_ratio=SLEEP_MOVE_WAKE_RATIO,
    )


def note_session_activity(kind: str, value: Any = None):
    """Count an action for the report and persist its timestamped event to DB."""
    session_id = None
    with session_lock:
        if _active_session is not None:
            counters = _active_session["counters"]
            counters[kind] = counters.get(kind, 0) + 1
            if _active_session.get("phase") == "recording":
                session_id = _active_session["record"]["session_id"]
    if session_id:
        database.enqueue(
            "sessions",
            "event",
            {
                "session_id": session_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "type": kind,
                "value": value,
            },
        )


class ZeepApiOffline(Exception):
    """เรียก ZEEP API ไม่ถึงเลย (เน็ตหลุด / DNS / timeout).

    แยกจากรหัสผ่านผิดโดยตั้งใจ: กรณีนี้เท่านั้นที่หน้าเว็บจะเสนอโหมด local
    fallback — รหัสผ่านผิดต้องแจ้งผิดตรง ๆ ห้ามข้ามไปเข้าแบบไม่ใช้รหัส.
    """


def _zeep_request(
    method: str,
    path: str,
    *,
    json_body: Optional[dict] = None,
    token: Optional[str] = None,
    api_key: Optional[str] = None,
    files: Optional[dict] = None,
    data: Optional[dict] = None,
    timeout: Optional[float] = None,
) -> Dict[str, Any]:
    """เรียก ZEEP API แล้วคืน envelope `{status, statusCode, message, data}`.

    ทีม backend ห่อทุก response เป็น envelope นี้ และบาง endpoint ส่ง
    `status:"error"` มาพร้อม HTTP 200 → เช็คทั้ง HTTP status และ body.

    ``token`` คือ access token ของผู้ใช้; ``api_key`` ใช้กับ route แบบ
    service-to-service ที่ backend กันไว้ด้วย x-api-key แทน JWT
    (เช่น sleep-session ingest) — ทั้งสองทางใช้ envelope เดียวกัน.
    """
    headers = dict(ZEEP_CLIENT_HEADERS)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if api_key:
        headers["x-api-key"] = api_key
    try:
        response = httpx.request(
            method,
            f"{ZEEP_API_BASE_URL}{path}",
            json=json_body,
            files=files,
            data=data,
            headers=headers,
            timeout=ZEEP_API_TIMEOUT if timeout is None else timeout,
        )
    except httpx.HTTPError as exc:
        raise ZeepApiOffline(f"{type(exc).__name__}: {exc}") from exc
    try:
        body = response.json()
    except ValueError:
        raise HTTPException(502, f"ZEEP API ตอบข้อมูลที่อ่านไม่ได้ (HTTP {response.status_code})")
    if not isinstance(body, dict):
        raise HTTPException(502, "ZEEP API ตอบรูปแบบที่ไม่รู้จัก")
    if response.status_code >= 400 or body.get("status") == "error":
        message = body.get("message") or f"ZEEP API ปฏิเสธคำขอ (HTTP {response.status_code})"
        raise HTTPException(response.status_code if response.status_code >= 400 else 401, message)
    return body


def _health_reference_from_profile(profile: Dict[str, Any]) -> Dict[str, Any]:
    """Compatibility facade for normalized, display-safe health facts."""
    return build_health_reference(profile, age_group_for=_age_group)


def _load_profiles() -> Dict[str, Any]:
    try:
        with PROFILES_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as exc:
        raise HTTPException(500, f"profiles.json unreadable: {exc}")


def _save_profiles(profiles: Dict[str, Any]):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = PROFILES_PATH.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(profiles, f, ensure_ascii=False, indent=1)
    tmp.replace(PROFILES_PATH)


def _migrate_profiles_to_email_keys() -> Dict[str, str]:
    """Re-key known ZEEP profiles by email without discarding legacy data.

    The returned mapping is also applied to Session rows, learned Baselines and
    persisted browser logins during startup. Local/offline profiles keep their
    normalized username because no verified email exists for them.
    """
    with profile_lock:
        profiles = _load_profiles()
        if not profiles:
            return {}
        migrated: Dict[str, Dict[str, Any]] = {}
        changed = False
        for stored_key, stored_profile in profiles.items():
            old_key = str(stored_key or "").strip().casefold()
            profile = dict(stored_profile or {})
            raw_email = profile.get("zeep_email") or profile.get("email")
            try:
                email = _normalize_email(str(raw_email or "")) if raw_email else None
            except HTTPException:
                email = None
            new_key = email or old_key
            if email:
                profile["email"] = email
                profile["zeep_email"] = email
            profile["account_key"] = new_key
            if new_key != old_key:
                aliases = {str(value).strip().casefold() for value in (profile.get("legacy_account_keys") or []) if value}
                aliases.add(old_key)
                profile["legacy_account_keys"] = sorted(aliases)
                changed = True

            existing = migrated.get(new_key)
            if existing is None:
                migrated[new_key] = profile
                continue
            existing_public_id = str(existing.get("zeep_public_id") or "").strip()
            incoming_public_id = str(profile.get("zeep_public_id") or "").strip()
            if existing_public_id and incoming_public_id and existing_public_id != incoming_public_id:
                raise RuntimeError(
                    "refusing to merge Profiles with conflicting immutable identities"
                )
            # profile. Preserve the newest metadata and combine counters.
            old_last = str(existing.get("last_session_utc") or "")
            new_last = str(profile.get("last_session_utc") or "")
            newer, older = (profile, existing) if new_last >= old_last else (existing, profile)
            combined = {**older, **newer}
            combined["sessions"] = int(existing.get("sessions", 0)) + int(profile.get("sessions", 0))
            aliases = set(existing.get("legacy_account_keys") or [])
            aliases.update(profile.get("legacy_account_keys") or [])
            combined["legacy_account_keys"] = sorted(
                normalized
                for alias in aliases
                if alias and (normalized := str(alias).strip().casefold()) != new_key
            )
            created = [existing.get("created_at_utc"), profile.get("created_at_utc")]
            created = [value for value in created if value]
            if created:
                combined["created_at_utc"] = min(created)
            combined["account_key"] = new_key
            migrated[new_key] = combined
            changed = True
        if changed or migrated != profiles:
            _save_profiles(migrated)
        return verified_alias_mapping(migrated)


def _read_sessions() -> list:
    with sessions_file_lock:
        try:
            with SESSIONS_PATH.open("r", encoding="utf-8") as f:
                lines = f.readlines()
        except FileNotFoundError:
            return []
    records = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def _append_session_record(record: Dict[str, Any]):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with sessions_file_lock:
        with SESSIONS_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _rewrite_sessions(records: list):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with sessions_file_lock:
        tmp = SESSIONS_PATH.with_suffix(".jsonl.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            for record in records:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        tmp.replace(SESSIONS_PATH)


def _series_stats(values):
    vals = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if not vals:
        return None
    return {
        "avg": round(sum(vals) / len(vals), 2),
        "min": round(min(vals), 2),
        "max": round(max(vals), 2),
        "n": len(vals),
    }


def estimate_sleep_state() -> Dict[str, Any]:
    """Compatibility facade for the extracted live Sleep estimator."""
    return _estimate_sleep_state_impl(LiveSleepRuntime.from_namespace(globals()))


# Sampler owns the 10-second analysis cache; REST/WebSocket never reclassifies.
# Live control and safety feedback may continue on their faster clocks.
_sleep_cache = {"t": 0.0, "value": None, "session_id": None, "sequence": None}
_health_cache = {"t": 0.0, "value": {}}


def _reset_live_sleep_inference(
    session_id: Optional[str],
    *,
    recording: bool = False,
) -> None:
    """Drop rolling physiology when occupant ownership changes.

    A completed occupant's BCG window must never be classified for an empty Pod
    or leak into the next Login. Environment ingestion continues independently.
    """
    global _analysis_frame
    with history_lock:
        sleep_feature_history.clear()
    with sleep_path_lock:
        _reset_sleep_stage_path(session_id)
    with analysis_frame_lock:
        _analysis_frame = None
    initial = (
        sensor_frame_wait_value(
            recording=recording,
            sleep_states=tuple(ZEEP_SLEEP_STATES),
            estimator_version=SLEEP_ESTIMATOR_VERSION,
            evidence_version=SLEEP_EVIDENCE_VERSION,
        )
        if recording
        else None
    )
    _sleep_cache.update(
        {
            "t": time.monotonic() if initial else 0.0,
            "value": initial,
            "session_id": session_id,
            "sequence": None,
        }
    )


def analysis_frame_cached() -> Optional[Dict[str, Any]]:
    with analysis_frame_lock:
        return json.loads(json.dumps(_analysis_frame)) if _analysis_frame is not None else None


def sleep_state_cached() -> Dict[str, Any]:
    now = time.monotonic()
    with state_lock:
        session_id = state["session"].get("session_id")
        recording = bool(state["session"].get("recording"))
    frame = analysis_frame_cached()
    if frame is not None and not frame.get("restored_after_restart") and frame.get("session_id") == session_id and (not recording or (frame.get("sleep") or {}).get("state") in {*ZEEP_SLEEP_STATES, "off_bed"}):
        value = dict(frame["sleep"])
        age_s = max(0.0, time.time() - float(frame["epoch_s"]))
        value["next_update_s"] = max(0, round(SLEEP_SAMPLE_SECONDS - age_s))
        return value
    cached = _sleep_cache["value"]
    refresh_s = SLEEP_SAMPLE_SECONDS
    if cached is None or session_id != _sleep_cache["session_id"] or recording and cached.get("state") not in {*ZEEP_SLEEP_STATES, "off_bed"}:
        # REST/WebSocket reads must never manufacture an evidence epoch. Only
        # the sensor sampler may advance the 10s -> 30s -> 60s pipeline.
        _sleep_cache["value"] = sensor_frame_wait_value(
            recording=recording,
            sleep_states=tuple(ZEEP_SLEEP_STATES),
            estimator_version=SLEEP_ESTIMATOR_VERSION,
            evidence_version=SLEEP_EVIDENCE_VERSION,
        )
        _sleep_cache["t"] = now
        _sleep_cache["session_id"] = session_id
    value = dict(_sleep_cache["value"])
    value["next_update_s"] = max(0, round(refresh_s - (now - _sleep_cache["t"])))
    return value


def system_health_cached() -> Dict[str, Any]:
    """Low-cost host telemetry for the shared header (refresh at most every 5s)."""
    now = time.monotonic()
    if now - _health_cache["t"] < 5 and _health_cache["value"]:
        return dict(_health_cache["value"])
    cpu_count = os.cpu_count() or 1
    load1, load5, load15 = os.getloadavg()
    mem = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, value = line.split(":", 1)
            mem[key] = int(value.strip().split()[0]) * 1024
    except Exception:
        pass
    mem_total = mem.get("MemTotal", 0)
    mem_available = mem.get("MemAvailable", 0)
    disk = shutil.disk_usage(DATA_DIR)
    wifi_dbm = None
    try:
        for line in Path("/proc/net/wireless").read_text().splitlines():
            if ":" in line and line.split(":", 1)[0].strip() == "wlan0":
                wifi_dbm = int(float(line.split()[3].rstrip(".")))
                break
    except Exception:
        pass

    def command_text(args):
        try:
            return subprocess.run(args, capture_output=True, text=True, timeout=1, check=False).stdout.strip() or None
        except Exception:
            return None

    ssid = command_text(["iwgetid", "-r"])
    ip_text = command_text(["hostname", "-I"])
    ip_address = ip_text.split()[0] if ip_text else None
    cpu_temp = None
    try:
        cpu_temp = round(int(Path("/sys/class/thermal/thermal_zone0/temp").read_text()) / 1000, 1)
    except Exception:
        pass
    host_uptime = None
    try:
        host_uptime = int(float(Path("/proc/uptime").read_text().split()[0]))
    except Exception:
        pass
    value = {
        "cpu_count": cpu_count,
        "load_1m": round(load1, 2),
        "load_5m": round(load5, 2),
        "load_15m": round(load15, 2),
        "load_percent": round(min(999, load1 / cpu_count * 100), 1),
        "cpu_temp_c": cpu_temp,
        "memory_percent": round((mem_total - mem_available) / mem_total * 100, 1) if mem_total else None,
        "memory_used_mb": round((mem_total - mem_available) / 1024 / 1024) if mem_total else None,
        "memory_total_mb": round(mem_total / 1024 / 1024) if mem_total else None,
        "disk_percent": round(disk.used / disk.total * 100, 1),
        "disk_free_gb": round(disk.free / 1024 / 1024 / 1024, 1),
        "host_uptime_s": host_uptime,
        "wifi_interface": "wlan0",
        "wifi_ssid": ssid,
        "wifi_dbm": wifi_dbm,
        "wifi_connected": bool(ssid and wifi_dbm is not None),
        "ip_address": ip_address,
    }
    _health_cache.update({"t": now, "value": value})
    return dict(value)


def snapshot() -> Dict[str, Any]:
    with state_lock:
        # JSON round-trip gives a detached copy for websocket/API responses.
        result = json.loads(json.dumps(state))
    now = time.time()
    result["system"]["uptime_s"] = int(now - result["system"]["started_at"])
    result["system"]["health"] = system_health_cached()
    # Display freshness is projected from last_update on the detached copy;
    # quiet or stale transports must never mutate their live reader state.
    esp32, hub2, bcg = project_live_device_statuses(
        result,
        now=now,
        policy=LIVE_DEVICE_PROJECTION_POLICY,
    )
    live_environment = build_environment_snapshot(esp32, hub2, now)
    analysis_frame = analysis_frame_cached()
    frame_available = bool(analysis_frame)
    frame_age_s = max(0.0, now - float(analysis_frame.get("epoch_s") or 0)) if analysis_frame else None
    frame_fresh = bool(analysis_frame and not analysis_frame.get("restored_after_restart") and frame_age_s is not None and frame_age_s <= max(15.0, SLEEP_SAMPLE_SECONDS * 3))
    if frame_available:
        environment_view = json.loads(json.dumps(analysis_frame["environment"]))
        if not frame_fresh:
            for device in (environment_view.get("devices") or {}).values():
                if device.get("status") not in {"offline", "fault"}:
                    device["status"] = "stale"
                device["data_age_s"] = round(frame_age_s, 1)
            environment_view["live_count"] = 0
            environment_view["status"] = "stale"
    else:
        # Never leak asynchronous Raw packets into the health/environment UI
        # during the first 10 seconds after boot. Preserve device identity and
        # connectivity context, but publish values only at a Sensor-frame tick.
        environment_view = json.loads(json.dumps(live_environment))
        for key in (
            "temperature_c",
            "humidity_rh",
            "lux",
            "sound_dba_est",
            "co2_ppm",
            "pm1_0_ug_m3",
            "pm2_5_ug_m3",
            "pm10_ug_m3",
            "voc_index",
            "sgp40_raw",
        ):
            environment_view[key] = None
        for device in (environment_view.get("devices") or {}).values():
            if device.get("status") == "live":
                device["status"] = "warming"
        environment_view["live_count"] = 0
        environment_view["status"] = "warming"
    # Live, historical reports and the Admin policy screen share one versioned
    # evaluator.  The assessment is explanatory context only: it cannot create
    # or change Wake/N1/N2/N3/REM and it does not relax any safety alarm.
    environment_view["assessment"] = assess_environment_values(
        environment_view,
        result.get("session", {}).get("rest_mode") or "auto",
        require_live_devices=True,
    )
    result["sensor"]["environment"] = environment_view
    if frame_available:
        for key, value in analysis_frame["bcg"].items():
            bcg[key] = value
        if not frame_fresh:
            bcg["analysis_valid"] = False
            bcg["analysis_stale"] = True
            bcg["fallback_active"] = True
            bcg["fallback_reason"] = "sensor_frame_stale"
        frame_metadata = {key: analysis_frame[key] for key in ("sequence", "timestamp", "epoch_s", "refresh_s", "source")}
        frame_metadata.update(
            {
                "data_age_s": round(frame_age_s, 1),
                "stale": not frame_fresh,
                "restored_after_restart": bool(analysis_frame.get("restored_after_restart")),
                "restored_source": analysis_frame.get("restored_source"),
            }
        )
    else:
        for key in (
            "status_code",
            "status_text",
            "raw_status_code",
            "raw_status_text",
            "heart_rate_bpm",
            "respiration_rate",
            "analysis_epoch_s",
        ):
            bcg[key] = None
        bcg["analysis_valid"] = False
        frame_metadata = {
            "sequence": None,
            "timestamp": None,
            "epoch_s": None,
            "refresh_s": SLEEP_SAMPLE_SECONDS,
            "source": "waiting_sensor_tick",
            "data_age_s": None,
            "stale": False,
        }
    frame_metadata["contains"] = [
        "environment",
        "heart_rate",
        "respiration_rate",
        "bed_status",
    ]
    # ``analysis_frame`` remains as a compatibility alias for existing clients.
    # New clients should use ``sensor_frame``: only Sleep Evidence/State has a
    # longer 30/60-second computation cadence.
    result["sensor_frame"] = dict(frame_metadata)
    result["analysis_frame"] = dict(frame_metadata)
    # Internal telemetry (pre-G2): displayed on this lab dashboard only,
    # logged with its version — never a control input.
    result["sleep"] = dict(analysis_frame["sleep"]) if frame_fresh else sleep_state_cached()
    # Smart Response remains observation-only. It consumes the same canonical
    # canonical environmental frame shown by every page, never sleep stage.
    result["smart_response"] = build_smart_response(result, now)
    with event_log_lock:
        result["events_tail"] = list(_event_ring)[-8:]
    return result


def snapshot_for(principal: Principal) -> Dict[str, Any]:
    """Return the minimum telemetry required by the principal's interface."""
    result = snapshot()
    result["features"] = {"session_report_share": report_shares.enabled}
    if principal.is_admin:
        with session_lock:
            recent_samples = [
                dict(item)
                for item in ((_active_session or {}).get("samples") or [])[-30:]
            ]
        sleep = result.get("sleep") or {}
        result["adaptive_learning"] = build_adaptive_learning_snapshot(
            result,
            baseline=sleep.get("personal_baseline"),
            behaviour=sleep.get("personal_behaviour"),
            recent_samples=recent_samples,
        )
        result["acoustic_intelligence"] = build_acoustic_monitor_snapshot(result)
        result["auth"] = {
            "principal": principal.public_dict(),
            "session_store": auth_sessions.health(),
        }
        return result

    return project_consumer_snapshot(result, principal.public_dict())


def build_environment_snapshot(esp32: Dict[str, Any], hub2: Dict[str, Any], now: Optional[float] = None) -> Dict[str, Any]:
    """Compatibility facade over the pure two-hub Sensor runtime."""
    return compose_environment_snapshot(
        esp32,
        hub2,
        now=now,
        hub1_stale_s=ESP32_STALE_SECONDS,
        hub2_stale_s=SENSORHUB2_STALE_SECONDS,
        device_specs=ENVIRONMENT_DEVICE_SPECS,
        calibration_metrics=tuple(SENSOR_CALIBRATION_SPECS),
        apply_bias=_apply_sensor_bias,
        bias_value=sensor_bias_value,
        bias_sources=SENSOR_BIAS_SOURCES,
    )


SMART_RESPONSE_POLICY_VERSION = "shadow-env-v1.0"


def build_smart_response(snap: Dict[str, Any], now: Optional[float] = None) -> Dict[str, Any]:
    """Compatibility facade over the side-effect-free Shadow evaluator."""
    policy = SmartResponsePolicy(
        version=SMART_RESPONSE_POLICY_VERSION,
        temperature_min_c=TEMPERATURE_EXCELLENT_MIN_C,
        temperature_max_c=TEMPERATURE_EXCELLENT_MAX_C,
        co2_warn_ppm=SAFETY_CO2_WARN_PPM,
        co2_critical_ppm=SAFETY_CO2_CRITICAL_PPM,
        sound_sleep_target_dba=SOUND_DBA_SLEEP_TARGET,
    )
    return evaluate_smart_response(snap, policy, now=now)


sound_energy_average_db = partial(
    energy_average_db, display_min=SOUND_DBA_DISPLAY_MIN,
    display_max=SOUND_DBA_DISPLAY_MAX,
)


def sound_window_summary(start_s: float, end_s: float) -> Dict[str, Any]:
    """Summarize SPH0645 samples aligned to one canonical analysis bucket."""
    with sound_history_lock:
        rows = list(sound_level_history)
    return summarize_sound_window(
        rows,
        start_s,
        end_s,
        display_min=SOUND_DBA_DISPLAY_MIN,
        display_max=SOUND_DBA_DISPLAY_MAX,
    )


def normalize_esp32_sensor(obj: Dict[str, Any]) -> Dict[str, Any]:
    """Compatibility facade for deterministic Hub 1 normalization."""
    return normalize_hub1_sensor(
        obj,
        sound_display_min=SOUND_DBA_DISPLAY_MIN,
        sound_display_max=SOUND_DBA_DISPLAY_MAX,
    )


def hold_last_valid_sound(current: Dict[str, Any], previous: Dict[str, Any]) -> Dict[str, Any]:
    """Compatibility facade for fail-closed sound validation."""
    return hold_sound_value(
        current,
        previous,
        display_min=SOUND_DBA_DISPLAY_MIN,
        display_max=SOUND_DBA_DISPLAY_MAX,
    )


def esp32_reader():
    """Run the modular Sensor Hub 1 USB adapter."""
    store = SensorHub1StateStore(
        sensor_state=state["sensor"],
        state_lock=state_lock,
        sound_history=sound_level_history,
        sound_history_lock=sound_history_lock,
    )
    SensorHub1Reader(
        port=ESP32_PORT,
        baud=ESP32_BAUD,
        serial_factory=serial.Serial,
        normalize=normalize_esp32_sensor,
        hold_sound=hold_last_valid_sound,
        previous_payload=store.previous_payload,
        publish_payload=store.publish_payload,
        publish_disconnect=store.publish_disconnect,
        append_sound=store.append_sound,
        log_event=log_event,
    ).run_forever()


def sensorhub2_mqtt_reader():
    """Subscribe to Hub 2 telemetry without replacing Hub 1 serial data."""
    run_sensorhub2_reader(
        mqtt_module=mqtt,
        mqtt_available=MQTT_AVAILABLE,
        mqtt_host=MQTT_HOST,
        mqtt_port=MQTT_PORT,
        mqtt_keepalive=MQTT_KEEPALIVE,
        telemetry_topic=SENSORHUB2_TELEMETRY_TOPIC,
        status_topic=SENSORHUB2_STATUS_TOPIC,
        shared_state=state,
        shared_state_lock=state_lock,
        decode_payload=decode_hub_payload,
        event_logger=log_event,
    )


configure_controlhub1(
    mqtt_module=mqtt,
    mqtt_available=MQTT_AVAILABLE,
    mqtt_host=MQTT_HOST,
    mqtt_port=MQTT_PORT,
    mqtt_keepalive=MQTT_KEEPALIVE,
    command_topic=CONTROLHUB1_COMMAND_TOPIC,
    status_topic=CONTROLHUB1_STATUS_TOPIC,
    event_topic=CONTROLHUB1_EVENT_TOPIC,
    stale_seconds=CONTROLHUB1_STALE_SECONDS,
    ack_timeout_seconds=CONTROLHUB1_ACK_TIMEOUT_SECONDS,
    min_ir_gap_seconds=CONTROLHUB1_MIN_IR_GAP_SECONDS,
    shared_state=state,
    shared_state_lock=state_lock,
    event_logger=log_event,
    safety_guard=lambda action: _require_safety_allows(action),
)
controlhub1_mqtt = ControlHub1MQTT()
configure_controlhub2(
    mqtt_module=mqtt,
    mqtt_available=MQTT_AVAILABLE,
    mqtt_host=MQTT_HOST,
    mqtt_port=MQTT_PORT,
    mqtt_keepalive=MQTT_KEEPALIVE,
    command_topic=CONTROLHUB2_COMMAND_TOPIC,
    status_topic=CONTROLHUB2_STATUS_TOPIC,
    event_topic=CONTROLHUB2_EVENT_TOPIC,
    stale_seconds=CONTROLHUB2_STALE_SECONDS,
    ack_timeout_seconds=CONTROLHUB2_ACK_TIMEOUT_SECONDS,
    shared_state=state,
    shared_state_lock=state_lock,
    event_logger=log_event,
    # Resolve the route-layer guard only when a command is requested.  The
    # function is declared later while FastAPI routes are assembled.
    safety_guard=lambda action: _require_safety_allows(action),
)
controlhub2_bed_mqtt = ControlHub2BedMQTT(move_seconds=BED_MOVE_SECONDS)


def bcg_reader():
    """Compatibility facade for the extracted LSM-800-T adapter."""
    config = BCGReaderConfig(
        port=BCG_PORT,
        baud=BCG_BAUD,
        status_text=STATUS_TEXT,
        on_bed_codes=frozenset(ON_BED_CODES),
        heart_rate_range=HR_SANITY_RANGE_BPM,
        respiration_range=RR_SANITY_RANGE_PER_MIN,
        vital_hold_seconds=BCG_VITAL_HOLD_SECONDS,
    )
    publisher = BCGPacketPublisher(
        config=config,
        ports=BCGPublicationPorts(
            storage=bcg_storage,
            shared_state=state,
            state_lock=state_lock,
            history=bcg_history,
            raw_history=bcg_raw_history,
            history_lock=history_lock,
        ),
    )
    LSM800TReader(
        config=config,
        ports=BCGReaderPorts(
            serial_factory=serial.Serial,
            parse_frame=parse_lsm800t_frame,
            publisher=publisher,
            log_event=log_event,
        ),
    ).run_forever()


def sensor_frame_sampler():
    """Compatibility facade for the extracted fixed-cadence sampler."""
    policy = SensorFramePolicy(
        sample_seconds=SLEEP_SAMPLE_SECONDS,
        minimum_bcg_packets=SLEEP_BUCKET_MIN_BCG_PACKETS,
        minimum_paired_vital_coverage=SLEEP_MIN_PAIRED_VITAL_COVERAGE,
        bed_exit_confirm_buckets=BED_EXIT_CONFIRM_BUCKETS,
        bed_exit_raw_min_frames=BED_EXIT_RAW_MIN_FRAMES,
        bed_exit_raw_min_ratio=BED_EXIT_RAW_MIN_RATIO,
        bed_exit_raw_confirmation_enabled=BED_EXIT_RAW_CONFIRMATION_ENABLED,
        on_bed_codes=frozenset(ON_BED_CODES),
        heart_rate_range=HR_SANITY_RANGE_BPM,
        respiration_range=RR_SANITY_RANGE_PER_MIN,
    )
    runtime = SensorFrameRuntime(
        shared_state=state,
        state_lock=state_lock,
        history_lock=history_lock,
        bcg_history=bcg_history,
        feature_history=sleep_feature_history,
        build_environment=build_environment_snapshot,
        summarize_sound_window=sound_window_summary,
        filter_vital_values=filter_vital_values,
        bed_exit_window_evidence=bed_exit_window_evidence,
        publish_frame=_publish_sensor_frame,
    )
    SensorFrameSampler(policy, runtime).run_forever()


def _sleep_value_between_evidence_epochs(
    feature: Dict[str, Any],
    session_id: Optional[str],
    clock: Dict[str, Any],
) -> Dict[str, Any]:
    """Hold a confirmed state between epochs without creating new evidence."""
    with state_lock:
        session_active = bool(state["session"].get("active"))
        session_recording = bool(state["session"].get("recording"))
    status_code = feature.get("confirmed_status", feature.get("status"))
    exit_confirmed = bool(status_code == 1 and (feature.get("bed_exit_evidence") or {}).get("confirmed"))
    current_vitals_valid = bool(feature.get("bcg_valid"))
    newly_latched_off_bed = False
    if exit_confirmed:
        newly_latched_off_bed = _latch_confirmed_bed_exit(
            session_id,
            now=float(feature["t"]),
        )
    exit_confirmed = bool(
        exit_confirmed
        or _off_bed_remains_latched(
            status_code=status_code,
            current_vitals_valid=current_vitals_valid,
        )
    )
    restart_hold = _restart_sleep_hold_result(session_id)
    cached = _last_sleep_evidence_result()
    with sleep_path_lock:
        previous_stage = _sleep_stage_path.get("last")
        continuity_hold_epochs = int(_sleep_stage_path.get("continuity_hold_ticks") or 0)
    issue = current_frame_issue(
        session_active=session_active,
        session_recording=session_recording,
        exit_confirmed=exit_confirmed,
        current_vitals_valid=current_vitals_valid,
    )
    if issue is not None and not (restart_hold is not None and issue.data_status == "invalid_or_missing_current_vitals"):
        with sleep_path_lock:
            _sleep_stage_path["candidate"] = None
            _sleep_stage_path["candidate_ticks"] = 0
            _sleep_stage_path["continuity_hold_ticks"] = 0
            if issue.data_status in {
                "no_session",
                "waiting_for_vitals",
                "empty_bed",
            }:
                _clear_restart_sleep_hold_locked()
                _sleep_stage_path["last_evidence_result"] = None
    value = between_evidence_epoch_value(
        issue=issue,
        restart_hold=restart_hold,
        cached=cached,
        previous_stage=previous_stage,
        continuity_hold_epochs=continuity_hold_epochs,
        sleep_states=tuple(ZEEP_SLEEP_STATES),
        estimator_version=SLEEP_ESTIMATOR_VERSION,
        evidence_version=SLEEP_EVIDENCE_VERSION,
    )
    value.update(
        {
            "sensor_frame_clock": clock,
            "evidence_epoch_due": False,
            "next_evidence_s": clock["next_evidence_s"],
        }
    )
    if newly_latched_off_bed:
        # Bed-exit confirmation may arrive between 30-second evidence ticks.
        # Persist it immediately so a fast End/Restart cannot lose occupancy.
        _persist_sleep_stage_status(value, epoch_s=float(feature["t"]))
    return value


def _publish_sensor_frame(feature: Dict[str, Any], environment: Dict[str, Any], bcg_state: Dict[str, Any]) -> None:
    """Publish the 10-second Sensor frame, then advance Sleep-only evidence."""
    global _analysis_frame
    epoch_s = float(feature["t"])
    with state_lock:
        session_id = state["session"].get("session_id")
    clock = _advance_sleep_evidence_clock(session_id)
    if clock["evidence_due"]:
        sleep_value = estimate_sleep_state()
        sleep_value.update(
            {
                "sensor_frame_clock": clock,
                "evidence_epoch_due": True,
                "next_evidence_s": SLEEP_EVIDENCE_EPOCH_SECONDS,
            }
        )
        if sleep_value.get("classification_active") is not True or sleep_value.get("display_only_after_restart") is True or sleep_value.get("state") not in ZEEP_SLEEP_STATES:
            _persist_sleep_stage_status(sleep_value, epoch_s=epoch_s)
        _remember_sleep_evidence(sleep_value, epoch_s)
    else:
        sleep_value = _sleep_value_between_evidence_epochs(feature, session_id, clock)
    status_code = feature.get("confirmed_status", feature.get("status"))
    raw_status_code = feature.get("status")
    bcg = {
        "analysis_epoch_s": epoch_s,
        "status_code": status_code,
        "status_text": STATUS_TEXT.get(status_code, "Unknown") if status_code is not None else None,
        "raw_status_code": raw_status_code,
        "raw_status_text": (STATUS_TEXT.get(raw_status_code, "Unknown") if raw_status_code is not None else None),
        "bed_exit_evidence": dict(feature.get("bed_exit_evidence") or {}),
        "heart_rate_bpm": feature.get("hr"),
        "respiration_rate": feature.get("rr"),
        "bcg_frames": feature.get("bcg_frames", 0),
        "analysis_valid": bool(feature.get("bcg_valid")),
        **rr_evidence.live_sensor_frame_fields(feature),
        "analysis_data_age_s": (round(max(0.0, epoch_s - feature["bcg_latest_t"]), 1) if isinstance(feature.get("bcg_latest_t"), (int, float)) else None),
        # snapshot() refreshes fallbacks; these fields describe this exact frame.
        "analysis_source_connected": bool(bcg_state.get("connected")),
    }
    frame = {
        "sequence": int(epoch_s // SLEEP_SAMPLE_SECONDS),
        "timestamp": datetime.fromtimestamp(epoch_s, timezone.utc).isoformat(),
        "epoch_s": epoch_s,
        "refresh_s": SLEEP_SAMPLE_SECONDS,
        "evidence_refresh_s": SLEEP_EVIDENCE_EPOCH_SECONDS,
        "confirmation_s": SLEEP_CONFIRMATION_SECONDS,
        "source": "pi_local_sensor_tick",
        "session_id": session_id,
        "environment": json.loads(json.dumps(environment)),
        "bcg": bcg,
        "sleep": json.loads(json.dumps(sleep_value)),
    }
    with analysis_frame_lock:
        _analysis_frame = frame
        _sleep_cache.update(
            {
                "t": time.monotonic(),
                "value": sleep_value,
                "session_id": session_id,
                "sequence": frame["sequence"],
            }
        )


def _publish_analysis_frame(feature: Dict[str, Any], environment: Dict[str, Any], bcg_state: Dict[str, Any]) -> None:
    """Backward-compatible internal alias; new code uses Sensor terminology."""
    _publish_sensor_frame(feature, environment, bcg_state)


# ---------- session sampling & lifecycle ----------
def take_session_sample() -> Dict[str, Any]:
    snap = snapshot()
    e = snap["sensor"].get("environment") or {}
    b = snap["sensor"]["bcg"] or {}
    sleep = snap.get("sleep") or {}
    sleep_recordable = bool(sleep.get("classification_active") and not sleep.get("display_only_after_restart"))
    sleep_metrics = sleep.get("metrics") or {}
    auxiliary = sleep_metrics.get("auxiliary_evidence") or {}
    acoustic = auxiliary.get("acoustic") or {}
    acoustic_dsp = e.get("acoustic") or {}
    devices = e.get("devices") or {}
    live = lambda key: (devices.get(key) or {}).get("status") == "live"
    b_ok = bool(b.get("connected"))
    waveform = sleep.get("signal_features") or {}
    sample_arousal_proxy = arousal_proxy_evidence(
        {
            "bcg_amplitude_shift_ratio": waveform.get("bcg_amplitude_shift_ratio"),
            "movement_ratio": sleep.get("movement_ratio"),
            "bed_status": b.get("status_text") if b_ok else None,
        },
        SLEEP_MOVE_WAKE_RATIO,
    )
    return {
        # Use acquisition time; frame boundaries can duplicate timestamps during
        # a cadence migration.
        "t": round(time.time(), 1),
        "analysis_epoch_s": (snap.get("analysis_frame") or {}).get("epoch_s"),
        "temp": e.get("temperature_c") if live("sht3x_dis") else None,
        "hum": e.get("humidity_rh") if live("sht3x_dis") else None,
        "co2": e.get("co2_ppm") if live("mhz19c") else None,
        "pm2_5": e.get("pm2_5_ug_m3") if live("pms7003") else None,
        "voc": e.get("voc_index") if live("sgp40") else None,
        "lux": e.get("lux") if live("opt3001") else None,
        "dba": e.get("sound_dba_est") if live("sph0645") else None,
        "acoustic_label": acoustic_dsp.get("label"),
        "acoustic_state": acoustic_dsp.get("state"),
        "acoustic_confidence": acoustic_dsp.get("confidence"),
        "acoustic_event_detected": bool(acoustic_dsp.get("event_detected")),
        "acoustic_classifier_version": acoustic_dsp.get("classifier_version"),
        "acoustic_window_sequence": acoustic_dsp.get("window_sequence"),
        "acoustic_features": dict(acoustic_dsp.get("features") or {}),
        "hr": b.get("heart_rate_bpm") if b_ok else None,
        "rr": b.get("respiration_rate") if b_ok else None,
        "bed": b.get("status_text") if b_ok else None,
        "bed_exit_evidence": dict(b.get("bed_exit_evidence") or {}),
        # Acquisition integrity permits a provisional State on a <30 s tail;
        # this field is not written to the immutable Sensor Timeline.
        "bcg_analysis_valid": bool(b_ok and b.get("analysis_valid")),
        **rr_evidence.live_session_sample_fields(
            b,
            snap.get("sensor_frame") or {},
            minimum_packets=SLEEP_BUCKET_MIN_BCG_PACKETS,
            minimum_coverage=SLEEP_MIN_PAIRED_VITAL_COVERAGE,
            hr_range=HR_SANITY_RANGE_BPM, rr_range=RR_SANITY_RANGE_PER_MIN,
        ),
        # Operational statuses are never counted or learned as Sleep Stages.
        "sleep": sleep.get("state") if sleep_recordable else None,
        "sleep_confirmed_state": (sleep.get("confirmed_state") if sleep_recordable else None),
        "sleep_evidence_candidate": (sleep.get("evidence") or {}).get("candidate"),
        "sleep_confirmation": sleep.get("confirmation") or {},
        "sleep_provisional": bool(sleep.get("provisional")),
        "sleep_held_previous_state": bool(sleep.get("held_previous_state")),
        "sleep_data_status": sleep.get("data_status"),
        "sleep_score_attribution_state": (sleep.get("score_attribution_state") if sleep_recordable else None),
        "sleep_challenger_counted_as_new_state": bool(sleep.get("challenger_counted_as_new_state")),
        "sleep_score_eligible": bool(sleep_recordable and sleep.get("score_eligible", True)),
        "sleep_excluded_from_score": bool(not sleep_recordable or sleep.get("excluded_from_score", False)),
        "sleep_excluded_from_personal_baseline": bool(sleep.get("excluded_from_personal_baseline", False)),
        "sleep_estimator_version": sleep.get("version"),
        "sleep_evidence_version": sleep.get("evidence_version"),
        "sleep_baseline_version": (sleep.get("baseline_definition") or {}).get("version"),
        "sleep_transition_policy": (sleep.get("baseline_definition") or {}).get("transition_policy"),
        # Kept for final_summary; audio/environment never creates a Stage, while
        # corroborated sound can explain disturbance when BCG/Bed agrees.
        "sleep_confidence": sleep.get("confidence"),
        "sleep_probability": (sleep.get("probabilities") or {}).get(sleep.get("state")),
        "acoustic_corroborated": bool(acoustic.get("corroborated")),
        # Persist compact evidence so reports reproduce the disturbance index.
        "arousal_proxy": sample_arousal_proxy,
    }


def bed_occupied_now() -> bool:
    """มีคนบนเตียงจริงตอนนี้ไหม — จาก frame BCG ล่าสุดที่ยังสด"""
    with state_lock:
        b = dict(state["sensor"]["bcg"])
    return bed_is_occupied(
        b,
        now_epoch_s=time.time(),
        stale_seconds=BCG_STALE_SECONDS,
        on_bed_codes=ON_BED_CODES,
    )


def session_vital_gate_now(active: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Return the pre-recording HR/RR gate from latest raw BCG packets.

    The dashboard may briefly hold the last valid vital sign to prevent visual
    flicker. Held values are intentionally excluded here: Session recording
    begins only after fresh HR *and* RR are sane in consecutive packets that
    arrived after this Login (or service restart).
    """
    with state_lock:
        b = dict(state["sensor"]["bcg"])
    return evaluate_vital_start_gate(
        b,
        active,
        now_epoch_s=time.time(),
        stale_seconds=BCG_STALE_SECONDS,
        on_bed_codes=ON_BED_CODES,
        required_packets=SESSION_VITAL_START_PACKETS,
    )


def _begin_recording(active: Dict[str, Any]) -> None:
    """Compose the durable recording-start service with live runtime ports."""
    begin_recording(
        active,
        ports=RecordingStartPorts(
            session_lock=session_lock,
            state_lock=state_lock,
            get_active=lambda: _active_session,
            vital_gate=session_vital_gate_now,
            enqueue=database.enqueue,
            flush=database.flush,
            reset_inference=_reset_live_sleep_inference,
            start_bcg=bcg_storage.start_session,
            patch_projection=_patch_session_projection_locked,
            save_checkpoint=_save_active_session_checkpoint,
            log_event=log_event,
            clock=time.time,
            monotonic=time.monotonic,
            utc_now=lambda: datetime.now(timezone.utc),
        ),
        default_interval_s=SESSION_SAMPLE_SECONDS,
        bed_start_seconds=BED_START_SECONDS,
        required_packets=SESSION_VITAL_START_PACKETS,
    )


def _update_session_projection(patch: Dict[str, Any]) -> None:
    with state_lock:
        _patch_session_projection_locked(patch)


_live_session_sampler = LiveSessionSampler(
    LiveSamplerPorts(
        session_lock=session_lock,
        get_active=lambda: _active_session,
        bed_occupied_now=lambda: bed_occupied_now(),
        vital_gate_now=lambda active: session_vital_gate_now(active),
        begin_recording=lambda active: _begin_recording(active),
        update_projection=_update_session_projection,
        log_event=lambda *args, **kwargs: log_event(*args, **kwargs),
        take_sample=lambda: take_session_sample(),
        sample_interval=lambda value, fallback: _sample_interval_seconds(
            value, fallback
        ),
        enqueue_timeline=lambda payload: database.enqueue(
            "sessions", "timeline", payload
        ),
        sleep=lambda seconds: time.sleep(seconds),
    ),
    bed_start_seconds=BED_START_SECONDS,
    default_interval_seconds=SESSION_SAMPLE_SECONDS,
    sample_limit=SESSION_SAMPLE_LIMIT,
)


def session_sampler() -> None:
    """Compatibility entry point for the extracted lifecycle sampler."""
    _live_session_sampler.run_forever()


def occupancy_lease_supervisor():
    """Renew the cross-pod lease without delaying sensor/session sampling.

    Network loss marks the pod DEGRADED for the admin but never ejects a person
    who is already sleeping.  The short coordinator lease prevents a dead Pi
    from blocking the account indefinitely after the Pi disappears.
    """
    last_error: Optional[str] = None
    while True:
        time.sleep(1.0)
        with session_lock:
            active = _active_session
            due = bool(active and time.monotonic() - active.get("last_lease_renew", 0) >= OCCUPANCY_RENEW_SECONDS)
            lease = active.get("occupancy_lease") if active else None
            if due:
                active["last_lease_renew"] = time.monotonic()
        if not due or lease is None:
            continue
        try:
            renewed = occupancy_client.renew(lease)
            with session_lock:
                if _active_session is active:
                    active["occupancy_lease"] = renewed
                    active["occupancy_error"] = None
            if last_error:
                log_event("occupancy", "coordinator_recovered", pod_id=POD_ID)
            last_error = None
        except (CoordinatorUnavailable, OccupancyConflict) as exc:
            error = getattr(exc, "reason", None) or str(exc)
            with session_lock:
                if _active_session is active:
                    active["occupancy_error"] = error
            if error != last_error:
                log_event("occupancy", "lease_degraded", pod_id=POD_ID, error=error)
            last_error = error
        with state_lock:
            health = occupancy_client.health()
            health["active_lease"] = bool(active)
            health["lease_error"] = last_error
            state["system"]["occupancy"] = health


# Upload a finished Session to the ZEEP account backend (POST /v1/sleep-sessions/ingest)
# The account backend stores ``record`` verbatim in the ``scoring_result`` jsonb
# column and returns the whole row from both the sleep-history list and detail
# endpoints, so the payload is built as a fresh whitelist literal.  Copying
# ``record`` and deleting keys would drag ``samples`` (one row per cadence tick,
# ~1 MB a night) plus the frozen Profile context into every history request.
# ``score_type`` names which of ``sleep_score``/``recovery_score`` is meaningful.
# Pi scores AASM W/N1/N2/N3/REM. The backend tests ``stage != 0`` to
# find sleep onset and ``stage == 0`` to count awakenings, so Wake keeps index 0
# and ``stage_name`` carries the real meaning: the same jsonb column also holds
# 4-level (0=Awake 1=Light 2=Deep 3=REM) rows from the Python AI service, and
# the name is what lets a reader tell the two encodings apart.
def _build_ingest_payload(
    record: Dict[str, Any],
    report_samples: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Bind deployment settings to the pure account-ingest builder."""
    return _build_account_ingest_payload(
        record,
        report_samples,
        api_key=ZEEP_INGEST_API_KEY,
        device_id=ZEEP_INGEST_DEVICE_ID,
        timezone_name=POD_TIMEZONE,
        current_report_version=SESSION_REPORT_VERSION,
    )


_session_ingest_outbox = IngestOutbox(
    directory=INGEST_OUTBOX_DIR,
    schema_version=INGEST_OUTBOX_VERSION,
    lock=ingest_outbox_lock,
    ingest_path=ZEEP_INGEST_PATH,
    api_key=lambda: ZEEP_INGEST_API_KEY,
    device_id=lambda: ZEEP_INGEST_DEVICE_ID,
    payload_builder=_build_ingest_payload,
    request=lambda *args, **kwargs: _zeep_request(*args, **kwargs),
    offline_error=ZeepApiOffline,
    logger=log_event,
    inline_timeout=ZEEP_INGEST_INLINE_TIMEOUT,
)


def _ingest_outbox_path(session_id: str) -> Path:
    return _session_ingest_outbox.path(session_id)


def _write_ingest_outbox(entry: Dict[str, Any]) -> None:
    _session_ingest_outbox.write(entry)


def _clear_ingest_outbox(session_id: str) -> bool:
    return _session_ingest_outbox.clear(session_id)


def _post_ingest_entry(entry: Dict[str, Any], *, timeout: Optional[float] = None) -> bool:
    return _session_ingest_outbox.post(entry, timeout=timeout)


def _enqueue_session_ingest(record: Dict[str, Any], report_samples: List[Dict[str, Any]]) -> None:
    _session_ingest_outbox.enqueue(record, report_samples)


@synchronized_by(ingest_outbox_lock)
def _sweep_ingest_outbox() -> None:
    _session_ingest_outbox.sweep()


def ingest_outbox_sweeper() -> None:
    """Retry queued uploads periodically so a Pod that never reboots catches up."""
    while True:
        time.sleep(ZEEP_INGEST_SWEEP_SECONDS)
        try:
            _sweep_ingest_outbox()
        except Exception as exc:
            log_event("ingest", "sweep_failed", error=str(exc))


def _database_flush_failure(context: str) -> RuntimeError:
    error = database.health().get("last_error")
    detail = f"; writer error: {error}" if error else ""
    return RuntimeError(f"database writer did not flush {context}{detail}")


def _restore_active_after_finalization_failure(active: Dict[str, Any]) -> None:
    """Keep the live Session recoverable when its durable close did not commit."""
    global _active_session
    with session_lock:
        if _active_session is None:
            _active_session = active
    report_shares.discard(active["record"].get("identity_subject"))
    try:
        bcg_storage.start_session(active["record"]["session_id"])
    except Exception as exc:
        log_event(
            "session",
            "bcg_restart_after_finalize_failure_failed",
            session_id=active["record"]["session_id"],
            error=str(exc),
        )


def _commit_live_session_finalization(
    active: Dict[str, Any],
    final_summary: Dict[str, Any],
    terminal_wake: Optional[Dict[str, Any]],
) -> None:
    """Compatibility facade for the extracted atomic commit boundary."""
    commit_session_finalization(
        active,
        final_summary,
        terminal_wake,
        ports=FinalizationPorts(
            enqueue=database.enqueue,
            flush=database.flush,
            flush_failure=_database_flush_failure,
            recover_active=_restore_active_after_finalization_failure,
            clear_checkpoint=_clear_active_session_checkpoint,
        ),
        flush_timeout_s=30,
    )


def _logout_zeep_session(active: Dict[str, Any]) -> None:
    """Revoke the account token best-effort after local Session persistence."""
    refresh_token = (active.get("auth") or {}).get("refresh_token")
    if not refresh_token:
        return
    try:
        _zeep_request(
            "POST", "/v1/auth/logout", json_body={"refreshToken": refresh_token}
        )
    except (ZeepApiOffline, HTTPException) as exc:
        log_event(
            "auth", "zeep_logout_failed", user=active["record"]["username"],
            error=str(getattr(exc, "detail", exc)),
        )


def _session_finalizer() -> SessionFinalizer:
    """Bind current adapters without copying Session state or policy formulas."""
    return SessionFinalizer(
        SessionFinalizationPorts(
            session_lock=session_lock,
            state_lock=state_lock,
            profile_lock=profile_lock,
            get_active=lambda: _active_session,
            set_active=_set_active_session,
            reserve_share=report_shares.reserve,
            discard_share=report_shares.discard,
            fulfil_share=report_shares.fulfil,
            flush=database.flush,
            writer_health=database.health,
            flush_failure=_database_flush_failure,
            read_sessions=database.read_sessions,
            clear_checkpoint=_clear_active_session_checkpoint,
            recover_active=_restore_active_after_finalization_failure,
            commit=_commit_live_session_finalization,
            project_samples=report_projection.project_report_samples,
            series_stats=_series_stats,
            end_bcg=bcg_storage.end_session,
            vital_gate=session_vital_gate_now,
            build_quality=build_sleep_quality,
            build_report=build_session_report,
            baseline_context=baselines.behaviour_context,
            update_baseline=baselines.update_user,
            availability=session_availability_by_account,
            load_profiles=_load_profiles,
            save_profiles=_save_profiles,
            release_lease=occupancy_client.release,
            logout_account=_logout_zeep_session,
            enqueue_ingest=_enqueue_session_ingest,
            replace_projection=_replace_session_projection_locked,
            reset_inference=_reset_live_sleep_inference,
            log_event=log_event,
            clock=time.time,
            monotonic=time.monotonic,
            utc_now=lambda: datetime.now(timezone.utc),
        ),
        FinalizationPolicy(
            pod_id=POD_ID,
            sample_interval_s=SESSION_SAMPLE_SECONDS,
            evidence_interval_s=SLEEP_EVIDENCE_EPOCH_SECONDS,
            heart_rate_range=HR_SANITY_RANGE_BPM,
            respiration_rate_range=RR_SANITY_RANGE_PER_MIN,
            required_packets=SESSION_VITAL_START_PACKETS,
            timeline_schema_version=SESSION_TIMELINE_SCHEMA_VERSION,
            bed_start_seconds=BED_START_SECONDS,
            baseline_start_utc=PERSONAL_BASELINE_LEARNING_START_UTC,
            estimator_version=SLEEP_ESTIMATOR_VERSION,
            evidence_version=SLEEP_EVIDENCE_VERSION,
            baseline_version=ZEEP_SLEEP_BASELINE_VERSION,
            transition_policy=ZEEP_SLEEP_TRANSITION_POLICY_VERSION,
            g2_ontology=SLEEP_G2_ONTOLOGY_VERSION,
            terminal_wake_policy=TERMINAL_WAKE_POLICY_VERSION,
        ),
    )


@synchronized_by(session_lock)
def _finalize_active_session(reason: str = "logout") -> Optional[Dict[str, Any]]:
    """Compatibility facade; keep the original lifecycle lock across closure."""
    return _session_finalizer().finalize(reason)


def _set_active_session(active: Optional[Dict[str, Any]]) -> None:
    """Assign live ownership; lifecycle services retain the original lock scope."""
    global _active_session
    _active_session = active


def _session_restarter() -> SessionRestarter:
    """Bind the current adapters per call, never a stale copy of runtime globals."""
    return SessionRestarter(
        RestartPorts(
            session_lock=session_lock,
            state_lock=state_lock,
            profile_lock=profile_lock,
            sleep_path_lock=sleep_path_lock,
            state=state,
            sleep_path=_sleep_stage_path,
            get_active=lambda: _active_session,
            set_active=_set_active_session,
            load_checkpoint=_load_active_session_checkpoint,
            clear_checkpoint=_clear_active_session_checkpoint,
            save_checkpoint=_save_active_session_checkpoint,
            restore_safety=_restore_safety_checkpoint_context,
            current_safety=_current_safety_checkpoint_context,
            read_sessions=database.read_sessions,
            enqueue=database.enqueue,
            flush=database.flush,
            load_profiles=_load_profiles,
            save_profiles=_save_profiles,
            age_group=_age_group,
            health_reference=_health_reference_from_profile,
            resolve_target=resolve_rest_target,
            rest_baseline=partial(rest_window, baselines),
            acquire_lease=occupancy_client.acquire,
            availability=session_availability_by_account,
            reset_inference=_reset_live_sleep_inference,
            reset_sleep_path=_reset_sleep_stage_path,
            restore_sleep_context=restore_session_sleep_context,
            start_bcg=bcg_storage.start_session,
            vital_gate=session_vital_gate_now,
            replace_projection=_replace_session_projection_locked,
            log_event=log_event,
            clock=time.time,
            monotonic=time.monotonic,
            utc_now=lambda: datetime.now(timezone.utc),
        ),
        RestartPolicy(
            pod_id=POD_ID,
            sample_interval_s=SESSION_SAMPLE_SECONDS,
            sample_limit=SESSION_SAMPLE_LIMIT,
            required_packets=SESSION_VITAL_START_PACKETS,
            heart_rate_range=HR_SANITY_RANGE_BPM,
            respiration_rate_range=RR_SANITY_RANGE_PER_MIN,
            evidence_interval_s=SLEEP_EVIDENCE_EPOCH_SECONDS,
            baseline_start_utc=PERSONAL_BASELINE_LEARNING_START_UTC,
        ),
    )


def _restore_waiting_session(checkpoint: Dict[str, Any]) -> Optional[str]:
    """Compatibility facade for restoring an authenticated waiting occupant."""
    return _session_restarter().restore_waiting(checkpoint)


def _restore_interrupted_session() -> Optional[str]:
    """Resume the newest Session without an explicit User/Admin completion."""
    return _session_restarter().restore()


@asynccontextmanager
async def lifespan(_: FastAPI):
    database.initialize()
    auth_sessions.initialize()
    occupancy_store.initialize()
    baselines.initialize()
    _initialize_aircon_fan_reference()
    try:
        gpio.initialize()
        player.initialize()
        log_event("system", "start", gpio=gpio.ready, player=player.backend)
        with state_lock:
            state["system"]["occupancy"] = occupancy_client.health()
        try:
            result = migrate_jsonl(database, SESSIONS_PATH)
            if result["status"] == "migrated":
                log_event(
                    "db",
                    "migrated_jsonl",
                    imported=result["imported"],
                    backup=str(result["backup"]),
                )
        except Exception as exc:
            # Never rename or discard the legacy file on a failed migration.
            log_event("db", "migration_skipped", error=str(exc))
        try:
            account_mapping = _migrate_profiles_to_email_keys()
        except Exception as exc:
            log_event("db", "profile_key_migration_failed", error=str(exc))
        else:
            if account_mapping:
                outcome = migrate_identity_stores(
                    account_mapping,
                    session_migration=database.rekey_session_accounts,
                    baseline_migration=baselines.rebuild_rekeyed_users,
                    auth_migration=auth_sessions.rekey_account_keys,
                )
                log_event("db", "account_keys_migrated_to_email", **outcome)
        database.start()
        try:
            _restore_interrupted_session()
        except Exception as exc:
            log_event("session", "restart_resume_failed", error=str(exc))
        try:
            _restore_latest_sensor_frame()
        except Exception as exc:
            # A damaged display cache must not block startup; live readers replace it.
            log_event("sensor_frame", "restart_restore_failed", error=str(exc))
        try:
            # Nights recorded while the account backend was unreachable.
            _sweep_ingest_outbox()
        except Exception as exc:
            log_event("ingest", "sweep_failed", error=str(exc))
        daily_backup.start()
        threading.Thread(target=esp32_reader, daemon=True).start()
        threading.Thread(target=sensorhub2_mqtt_reader, daemon=True).start()
        threading.Thread(target=controlhub1_mqtt.run, daemon=True).start()
        threading.Thread(target=controlhub2_bed_mqtt.run, daemon=True).start()
        threading.Thread(target=bcg_reader, daemon=True).start()
        threading.Thread(target=sensor_frame_sampler, daemon=True).start()
        threading.Thread(target=session_sampler, daemon=True).start()
        threading.Thread(target=occupancy_lease_supervisor, daemon=True).start()
        threading.Thread(target=safety_supervisor, daemon=True).start()
        threading.Thread(target=ingest_outbox_sweeper, daemon=True).start()
        yield
    finally:
        with session_lock:
            active = _active_session
        if active is not None:
            try:
                _save_active_session_checkpoint(active)
            except Exception as exc:
                log_event("session", "restart_checkpoint_save_failed", error=str(exc))
            if active.get("phase") == "recording":
                database.enqueue(
                    "sessions",
                    "event",
                    {
                        "session_id": active["record"]["session_id"],
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "type": "service_pause",
                        "value": {"reason": "server_shutdown"},
                    },
                )
            database.flush(30)
        player.shutdown()
        controlhub2_bed_mqtt.motion.close()
        try:
            _persist_last_sensor_frame(analysis_frame_cached())
        except Exception as exc:
            log_event("sensor_frame", "restart_cache_save_failed", error=str(exc))
        gpio.shutdown()
        bcg_storage.flush()
        daily_backup.stop()
        database.stop(30)
        log_event("system", "stop")


def _service_principal() -> Principal:
    """Map the optional automation token to an auditable admin identity."""
    return Principal(
        session_id="service-api-token",
        subject="service:api-token",
        username="service",
        display_name="Service automation",
        account_key="service",
        email=None,
        role="admin",
        auth_source="api_token",
        csrf_token="",
        expires_at=float("inf"),
    )


def optional_principal(
    request: Request,
    x_api_token: Optional[str] = Header(default=None),
) -> Optional[Principal]:
    if API_TOKEN and x_api_token and secrets.compare_digest(x_api_token, API_TOKEN):
        return _service_principal()
    return auth_sessions.resolve(request.cookies.get(COOKIE_NAME))


def require_user(
    request: Request,
    _cookie_token: Optional[str] = Security(auth_cookie),
    x_api_token: Optional[str] = Header(default=None),
    x_csrf_token: Optional[str] = Header(default=None),
) -> Principal:
    """Require a browser login and CSRF proof for every state-changing call."""
    principal = optional_principal(request, x_api_token)
    if principal is None:
        raise HTTPException(401, {"code": "login_required", "message": "กรุณาเข้าสู่ระบบ"})
    if request.method not in {"GET", "HEAD", "OPTIONS"} and principal.auth_source != "api_token":
        if not secrets.compare_digest(x_csrf_token or "", principal.csrf_token):
            raise HTTPException(403, {"code": "csrf_failed", "message": "Session verification failed"})
    return principal


def require_admin(principal: Principal = Depends(require_user)) -> Principal:
    if not principal.is_admin:
        raise HTTPException(403, {"code": "admin_required", "message": "สำหรับผู้ดูแลระบบเท่านั้น"})
    return principal


def _principal_owns_active(active: Optional[Dict[str, Any]], principal: Principal) -> bool:
    if not active:
        return False
    owner_session_id = active.get("owner_auth_session_id")
    if owner_session_id:
        return secrets.compare_digest(owner_session_id, principal.session_id)
    # A restored legacy session has no browser-session ID. Fall back to its
    # immutable identity so the occupant can recover after a Pi restart.
    return active["record"].get("identity_subject") == principal.subject


def require_pod_operator(principal: Principal = Depends(require_user)) -> Principal:
    """Allow admins or the browser identity that owns the active pod session."""
    if principal.is_admin:
        return principal
    with session_lock:
        active = _active_session
    if active is None:
        raise HTTPException(409, {"code": "pod_session_required", "message": "ยังไม่มี Session ของตู้นอน"})
    if not _principal_owns_active(active, principal):
        raise HTTPException(403, {"code": "not_session_owner", "message": "ตู้นี้กำลังใช้งานโดยบัญชีอื่น"})
    return principal


def _set_auth_cookies(response: Response, cookie_token: str, principal: Principal) -> None:
    max_age = max(0, int(principal.expires_at - time.time()))
    response.set_cookie(
        COOKIE_NAME,
        cookie_token,
        max_age=max_age,
        httponly=True,
        secure=auth_sessions.secure_cookie,
        samesite="strict",
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE_NAME,
        principal.csrf_token,
        max_age=max_age,
        httponly=False,
        secure=auth_sessions.secure_cookie,
        samesite="strict",
        path="/",
    )


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")
    response.delete_cookie(CSRF_COOKIE_NAME, path="/")


app = FastAPI(title="Zeep Pod Control", docs_url=None, redoc_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _pod_is_occupied() -> bool:
    with session_lock:
        return _active_session is not None


def _active_session_token() -> Optional[str]:
    """Identify the current occupant without exposing account information."""
    with session_lock:
        active = _active_session
        if active is None:
            return None
        session_id = (active.get("record") or {}).get("session_id")
        return str(session_id or f"active:{id(active)}")


def _active_session_for_live() -> Optional[Dict[str, Any]]:
    """Return the current immutable-by-convention live Session reference."""
    with session_lock:
        return _active_session


app.include_router(
    create_qr_login_router(
        qr_logins,
        zeep_request=lambda *a, **kw: _zeep_request(*a, **kw),
        zeep_offline=ZeepApiOffline,
        complete_login=lambda *a, **kw: _complete_occupant_login(*a, **kw),
        pod_occupied=_pod_is_occupied,
        log_event=log_event,
        lifecycle_lock=session_lock,
    )
)
app.include_router(
    create_live_websocket_router(
        cookie_name=COOKIE_NAME,
        resolve_principal=auth_sessions.resolve,
        active_session=_active_session_for_live,
        principal_owns_active=_principal_owns_active,
        snapshot_for=snapshot_for,
        await_end_notice=report_shares.await_notice,
    )
)
app.include_router(
    create_fleet_router(
        require_admin=require_admin,
        fleet_snapshot=lambda: local_pod_health(
            snapshot(),
            pod_id=POD_ID,
            stale_seconds={
                "sensorhub1": ESP32_STALE_SECONDS,
                "sensorhub2": SENSORHUB2_STALE_SECONDS,
                "bcg": BCG_STALE_SECONDS,
                "controlhub1": CONTROLHUB1_STALE_SECONDS,
                "controlhub2": CONTROLHUB2_STALE_SECONDS,
            },
        ),
    )
)
app.include_router(create_profile_completion_router(
    pending_profiles,
    zeep_request=lambda *a, **kw: _zeep_request(*a, **kw), zeep_offline=ZeepApiOffline,
    complete_login=lambda *a, **kw: _complete_occupant_login(*a, **kw),
    pod_occupied=_pod_is_occupied, log_event=log_event, lifecycle_lock=session_lock,
))
app.include_router(
    create_report_share_router(
        report_shares,
        zeep_request=lambda *a, **kw: _zeep_request(*a, **kw),
        zeep_offline=ZeepApiOffline,
        log_event=log_event,
        lifecycle_lock=session_lock,
    )
)
app.include_router(create_history_router(database, require_admin=require_admin))
app.include_router(create_occupancy_router(occupancy_store, OCCUPANCY_COORDINATOR_TOKEN))
app.include_router(
    create_account_erasure_router(
        require_admin=require_admin,
        lifecycle_lock=session_lock,
        normalize_account_key=_normalize_account_key,
        active_account_key=lambda: (
            _active_session["record"]["username_key"]
            if _active_session is not None
            else None
        ),
        database=database,
        baseline_store=baselines,
        auth_sessions=auth_sessions,
        profiles_lock=profile_lock,
        load_profiles=_load_profiles,
        save_profiles=_save_profiles,
        clear_pending_ingest=_clear_ingest_outbox,
        clear_report_shares=report_shares.discard_account, clear_pending_profiles=pending_profiles.discard_account,
        clear_session_checkpoint=session_checkpoint_store.discard_accounts,
        log_event=log_event,
        backup_retention_count=lambda: daily_backup.retention_count,
    )
)
app.include_router(
    create_api_v1_router(
        require_pod_operator=require_pod_operator,
        require_admin=require_admin,
        snapshot_for=snapshot_for,
        public_status=lambda: public_status(),
        sensor_contract_snapshot=sensor_contract_snapshot,
        sleep_policy_snapshot=sleep_policy_snapshot,
        maintenance_contract_snapshot=maintenance_contract_snapshot,
        acoustic_timeline_snapshot=acoustic_timeline_snapshot,
    )
)
app.include_router(
    create_usage_sessions_router(
        require_user=require_user,
        require_admin=require_admin,
        history_service=lambda: _session_history_service(),
        profiles_snapshot=lambda: _load_profiles(),
        profiles_lock=profile_lock,
        timezone_name=POD_TIMEZONE or "Asia/Bangkok",
        baseline_snapshot=baselines.ensure_rest_window_current,
    )
)


def _require_username_access(username: str, principal: Principal) -> str:
    """Authorize one canonical account key (email for a ZEEP user)."""
    key = _normalize_account_key(username)
    if not principal.is_admin and key != principal.account_key:
        # Compatibility for a tablet that still has the pre-migration page in
        # memory. Resolve only aliases recorded on this same authenticated
        # Profile; arbitrary cross-account usernames remain forbidden.
        with profile_lock:
            profile = _load_profiles().get(principal.account_key) or {}
        aliases = {str(value).strip().casefold() for value in (profile.get("legacy_account_keys") or []) if value}
        aliases.add(str(profile.get("username") or "").strip().casefold())
        if key not in aliases:
            raise HTTPException(403, "ดูข้อมูลการนอนของบัญชีอื่นไม่ได้")
        key = principal.account_key
    return key


@app.get("/api/baseline/{username}")
def api_baseline(username: str, principal: Principal = Depends(require_user)):
    """Baseline ส่วนบุคคล + คำแนะนำ (advisory เท่านั้น — คนตัดสินใจ/กดปุ่มเอง)"""
    key = _require_username_access(username, principal)
    record = baselines.get(key) or {
        "status": "no_data",
        "nights_used": 0,
        "min_nights": 3,
    }
    return {
        "username": username,
        "baseline": record,
        "recommendations": baselines.recommendations(key),
        "guardrail": (
            "ระบบเรียนรู้และแนะนำเท่านั้น — ไม่สั่งอุปกรณ์อัตโนมัติจาก Sleep State; "
            "ดูขอบเขตที่ docs/adaptive-control-recommendation-plan-v1.md"
        ),
    }


@app.get("/api/bcg/trend", dependencies=[Depends(require_admin)])
async def bcg_trend(response: Response, minutes: int = 10):
    """แนวโน้ม HR/RR/การขยับ/บนเตียง แบบ bucket ละ 5 วิ"""
    response.headers["Cache-Control"] = "private, no-store"
    minutes = max(1, min(10, int(minutes)))
    now = time.time()
    bucket_s = SLEEP_SAMPLE_SECONDS
    start = now - minutes * 60
    n = int(minutes * 60 / bucket_s)
    with history_lock:
        frames = [f for f in bcg_history if f["t"] >= start]
    grouped: Dict[int, list] = {}
    for f in frames:
        idx = int((f["t"] - start) / bucket_s)
        if 0 <= idx < n:
            grouped.setdefault(idx, []).append(f)
    buckets = []
    for i in range(n):
        fs = grouped.get(i)
        if not fs:
            buckets.append(
                {
                    "t": start + i * bucket_s,
                    "hr": None,
                    "rr": None,
                    "move": None,
                    "onbed": None,
                }
            )
            continue
        hrs = [f["hr"] for f in fs if f["hr"]]
        rrs = [f["rr"] for f in fs if f["rr"]]
        buckets.append(
            {
                "t": start + i * bucket_s,
                "hr": round(sum(hrs) / len(hrs), 1) if hrs else None,
                "rr": round(sum(rrs) / len(rrs), 1) if rrs else None,
                "move": round(sum(1 for f in fs if f["status"] == 2) / len(fs), 2),
                "onbed": any(f["status"] in ON_BED_CODES for f in fs),
            }
        )
    return {
        "bucket_s": bucket_s,
        "minutes": minutes,
        "buckets": buckets,
        "sleep": sleep_state_cached(),
    }


@app.get("/api/bcg/raw", dependencies=[Depends(require_admin)])
async def bcg_raw(limit: int = 12):
    """Recent byte-exact LSM-800-T packets for the developer monitor."""
    limit = max(1, min(100, int(limit)))
    with history_lock:
        packets = list(bcg_raw_history)[-limit:]
    return {"frame_bytes": 66, "count": len(packets), "packets": packets}


def sensor_calibration_inspector_snapshot() -> Dict[str, Any]:
    """Build the Admin-only Raw → Parameter → Output comparison table."""
    snap = snapshot()
    sensor = snap.get("sensor") or {}
    environment = sensor.get("environment") or {}
    raw_values = environment.get("raw_values") or {}
    devices = environment.get("devices") or {}
    hub1 = sensor.get("esp32") or {}
    bcg = sensor.get("bcg") or {}
    with SENSOR_CALIBRATION_LOCK:
        metadata = dict(CALIBRATION.get("sensor_bias_metadata") or {})
    channels = []
    for metric, spec in SENSOR_CALIBRATION_SPECS.items():
        device = devices.get(spec["device_key"]) or {}
        raw_value = hub1.get(spec.get("raw_field")) if spec.get("raw_field") else raw_values.get(metric)
        channel_meta = metadata.get(metric) or {}
        channels.append(
            {
                "metric": metric,
                "device": spec["device"],
                "device_key": spec["device_key"],
                "label": spec["label"],
                "unit": spec["unit"],
                "raw_unit": spec.get("raw_unit", spec["unit"]),
                "raw": raw_value,
                "bias": sensor_bias_value(metric),
                "bias_label": spec.get("bias_label", "additive bias"),
                "parameter_unit": spec.get("parameter_unit", spec["unit"]),
                "formula": spec.get("formula", "clamp(raw + bias)"),
                "calibrated": environment.get(metric),
                "editable": True,
                "bias_min": spec["bias_min"],
                "bias_max": spec["bias_max"],
                "step": spec["step"],
                "source": device.get("source_label"),
                "status": device.get("status", "offline"),
                "data_age_s": device.get("data_age_s"),
                "bias_source": SENSOR_BIAS_SOURCES.get(metric, "default"),
                "updated_at": channel_meta.get("updated_at"),
                "reference_value": channel_meta.get("reference_value"),
            }
        )

    sound_device = devices.get("sph0645") or {}
    channels.append(
        sound_inspector_channel(
            hub1,
            environment,
            sound_device,
        )
    )

    # These algorithm-owned values are inspected beside the adjustable
    # channels, but are intentionally not offset in software. SGP40 learns its
    # own 24-hour baseline; BCG summary bytes feed the physiology estimator.
    sgp = devices.get("sgp40") or {}
    channels.extend(
        [
            {
                "metric": "voc_index",
                "device": "SGP40",
                "device_key": "sgp40",
                "label": "VOC Index",
                "unit": "index",
                "raw": raw_values.get("voc_index"),
                "bias": 0.0,
                "calibrated": environment.get("voc_index"),
                "editable": False,
                "source": sgp.get("source_label"),
                "status": sgp.get("status", "offline"),
                "data_age_s": sgp.get("data_age_s"),
                "lock_reason": "Adaptive Baseline ของ SGP40 — ไม่ควรบวก offset ด้วยมือ",
            },
            {
                "metric": "sgp40_raw",
                "device": "SGP40",
                "device_key": "sgp40",
                "label": "SRAW VOC",
                "unit": "raw",
                "raw": raw_values.get("sgp40_raw"),
                "bias": 0.0,
                "calibrated": environment.get("sgp40_raw"),
                "editable": False,
                "source": sgp.get("source_label"),
                "status": sgp.get("status", "offline"),
                "data_age_s": sgp.get("data_age_s"),
                "lock_reason": "ค่าดิบสำหรับตรวจ Algorithm เท่านั้น",
            },
            {
                "metric": "bcg_heart_rate",
                "device": "LSM-800-T",
                "device_key": "bcg",
                "label": "Heart Rate",
                "unit": "BPM",
                "raw": bcg.get("heart_rate_bpm"),
                "bias": 0.0,
                "calibrated": bcg.get("heart_rate_bpm"),
                "editable": False,
                "source": "BCG · Serial",
                "status": "live" if bcg.get("connected") else "offline",
                "data_age_s": bcg.get("data_age_s"),
                "lock_reason": "Firmware physiology output — แสดงดิบเพื่อเทียบเครื่องอ้างอิง",
            },
            {
                "metric": "bcg_respiration_rate",
                "device": "LSM-800-T",
                "device_key": "bcg",
                "label": "Respiratory Rate",
                "unit": "ครั้ง/นาที",
                "raw": bcg.get("respiration_rate"),
                "bias": 0.0,
                "calibrated": bcg.get("respiration_rate"),
                "editable": False,
                "source": "BCG · Serial",
                "status": "live" if bcg.get("connected") else "offline",
                "data_age_s": bcg.get("data_age_s"),
                "lock_reason": "ใช้โดย Sleep Estimator — ห้ามปรับ bias โดยไม่มี validation",
            },
        ]
    )
    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "session_active": bool((snap.get("session") or {}).get("active")),
        "channels": channels,
        "calibration_file": str(CALIBRATION_PATH),
        "formula": {
            "default": "calibrated = clamp(raw + bias)",
            "sound_dba_est": "ESP32 sound_dba → Pi โดยตรง",
        },
    }


@app.get("/api/admin/calibration", dependencies=[Depends(require_admin)])
def sensor_calibration_inspector():
    return sensor_calibration_inspector_snapshot()


@app.post("/api/admin/calibration/bias")
def sensor_calibration_bias(
    cmd: SensorBiasCommand,
    principal: Principal = Depends(require_admin),
):
    metric = str(cmd.metric or "").strip()
    try:
        updated = update_sensor_bias(
            metric,
            cmd.bias,
            operator=principal.username,
            reference_value=cmd.reference_value,
        )
    except ValueError as exc:
        code = str(exc)
        if code == "metric_not_calibratable":
            raise HTTPException(422, "Sensor channel นี้ไม่อนุญาตให้ปรับ bias") from exc
        raise HTTPException(422, "ค่า bias/reference อยู่นอกช่วงที่อนุญาต") from exc
    log_event(
        "calibration",
        "sensor_bias_updated",
        operator=principal.username,
        metric=metric,
        bias=updated["bias"],
        reference_value=updated.get("reference_value"),
        active_session=bool(_active_session),
    )
    return {
        "ok": True,
        "update": updated,
        "calibration": sensor_calibration_inspector_snapshot(),
    }


@app.get("/api/logs", dependencies=[Depends(require_admin)])
async def api_logs(limit: int = 100):
    """Event log ล่าสุด (ring buffer) — ใช้ไล่ตรวจ connect/disconnect/คำสั่ง"""
    limit = max(1, min(EVENT_RING_LIMIT, int(limit)))
    with event_log_lock:
        events = list(_event_ring)[-limit:]
    return {
        "events": events,
        "log_file": str(EVENT_LOG_PATH),
        "db_health": database.health(),
    }


def _normalize_aircon_command(raw: str) -> str:
    try:
        return normalize_aircon_command(raw)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


def _resolve_aircon_temperature_command(
    command: str,
) -> Tuple[str, Optional[int], Optional[int]]:
    try:
        return resolve_aircon_temperature_command(command)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


def _normalize_bed_command(raw: str) -> str:
    try:
        return normalize_bed_command(raw)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post("/api/safety/arm", dependencies=[Depends(require_admin)])
def safety_arm():
    faults = _safety_faults()
    blocking = [f for f in faults if f["severity"] in ("blocking", "critical")]
    if blocking:
        raise HTTPException(409, {"message": "Safety Supervisor ยังไม่พร้อม Arm", "faults": blocking})
    with state_lock:
        state["safety"]["armed"] = True
    try:
        _refresh_active_session_safety_checkpoint(armed=True)
    except Exception as exc:
        log_event(
            "safety",
            "checkpoint_refresh_failed",
            operation="arm",
            error=str(exc),
        )
        raise HTTPException(500, "บันทึกสถานะ Safety ไม่สำเร็จ") from exc
    log_event("safety", "armed")
    return {"ok": True, "safety": snapshot()["safety"]}


@app.post("/api/safety/disarm", dependencies=[Depends(require_admin)])
def safety_disarm():
    with state_lock:
        state["safety"]["armed"] = False
    # Deliberately process-local: a restart must never preserve a disarmed Pod.
    log_event("safety", "disarmed")
    return {"ok": True, "safety": snapshot()["safety"]}


@app.post("/api/safety/safe-mode", dependencies=[Depends(require_admin)])
def safety_safe_mode():
    action = apply_safety_profile("manual_dashboard")
    return {"ok": True, "action": action, "safety": snapshot()["safety"]}


@app.post("/api/safety/ack", dependencies=[Depends(require_admin)])
def safety_acknowledge():
    with _safety_action_lock:
        faults = _safety_faults()
        critical = [f for f in faults if f["severity"] == "critical"]
        if critical:
            raise HTTPException(
                409,
                {
                    "message": "ยังมี critical fault จึง acknowledge ไม่ได้",
                    "faults": critical,
                },
            )
        with state_lock:
            state["safety"]["latched"] = False
        try:
            _refresh_active_session_safety_checkpoint(latched=False)
        except Exception as exc:
            # ACK succeeds only after memory and the checkpoint agree. Restore
            # the fail-safe latch when durable storage cannot be refreshed.
            with state_lock:
                state["safety"]["latched"] = True
            log_event(
                "safety",
                "checkpoint_refresh_failed",
                operation="ack",
                error=str(exc),
            )
            raise HTTPException(500, "บันทึกการรับทราบ Safety ไม่สำเร็จ") from exc
    log_event("safety", "acknowledged")
    return {"ok": True, "safety": snapshot()["safety"]}


def _require_safety_allows(action: str):
    with state_lock:
        latched = bool(state["safety"].get("latched"))
    if latched:
        raise HTTPException(423, f"Safety EMERGENCY latch: ไม่อนุญาต {action}")


def public_status():
    """Non-sensitive boot information used before a browser is authenticated."""
    occupied = _pod_is_occupied()
    with state_lock:
        safety = state.get("safety") or {}
    return {
        "pod_id": POD_ID,
        "occupied": occupied,
        "safety": {
            "ready": bool(safety.get("ready")),
            "armed": bool(safety.get("armed")),
            "latched": bool(safety.get("latched")),
            "level": safety.get("level"),
        },
        "admin_login_available": True,
        "local_admin_enabled": auth_sessions.local_admin_enabled,
    }


app.include_router(
    create_shell_router(
        static_dir=STATIC_DIR,
        require_pod_operator=require_pod_operator,
        snapshot_for=snapshot_for,
        public_status=public_status,
        smart_response=lambda: snapshot()["smart_response"],
    )
)


def aircon_command(
    cmd: AirconCommand,
    principal: Principal = Depends(require_pod_operator),
):
    requested_command = _normalize_aircon_command(cmd.command)
    direct_temperature = bool(cmd.direct and requested_command.startswith("temp "))
    if cmd.direct and not getattr(principal, "is_admin", False):
        raise HTTPException(
            403,
            {
                "code": "admin_required",
                "message": "Direct Aircon command ใช้ได้เฉพาะผู้ดูแลระบบ",
            },
        )
    command, desired_temperature, commanded_temperature = _resolve_aircon_temperature_command(requested_command)
    # OFF and read-only status remain available during a safety latch. Other
    # commands follow the same safe-default policy as controllable outputs.
    if command not in ("off", "status"):
        _require_safety_allows(f"Air Con {command}")
    followup_command = None
    followup_ack = None
    swing_command = None
    swing_ack = None
    preflight_command = None
    preflight_ack = None
    if command == "on":
        # Keep power, the 18 °C default setpoint and swing in one atomic
        # sequence.  The IR guards let the appliance finish each frame and no
        # other API request can interleave a conflicting command.
        followup_command = f"temp {AIRCON_POWER_ON_DEFAULT_TEMP_C}"
        swing_command = "swing_on"
        acknowledgements = controlhub1_mqtt.publish_sequence_and_wait(
            [command, followup_command, swing_command],
            [
                0.0,
                CONTROLHUB1_POWER_ON_SETTLE_SECONDS,
                CONTROLHUB1_MIN_IR_GAP_SECONDS,
            ],
        )
        acknowledgement, followup_ack, swing_ack = acknowledgements
    elif command == "fan":
        # Some Control Hub 1 units can acknowledge MQTT while their command
        # task is only just waking. Ask for STATUS first and wait for its ACK,
        # then send FAN under the same lock so no other IR request can
        # interleave. If STATUS fails, FAN is never transmitted and the Pi's
        # logical 1..5 reference remains unchanged.
        preflight_command = "status"
        acknowledgements = controlhub1_mqtt.publish_sequence_and_wait(
            [preflight_command, command],
            [0.0, CONTROLHUB1_FAN_WAKE_SETTLE_SECONDS],
        )
        preflight_ack, acknowledgement = acknowledgements
    else:
        acknowledgement = controlhub1_mqtt.publish_and_wait(command)
    fan_level = None
    if command == "fan":
        # The firmware's FAN command advances one native IR step.  Since this
        # air conditioner has no return channel, expose a bounded 1..5 command
        # counter and never describe it as measured fan speed.
        reported_level = acknowledgement.get("fan_level")
        with state_lock:
            aircon_state = state.get("aircon") or {}
            current_level = aircon_state.get("fan_level")
            if isinstance(reported_level, int) and 1 <= reported_level <= 5:
                fan_level = reported_level
                fan_level_source = "esp_ack"
            else:
                fan_level = current_level % 5 + 1 if isinstance(current_level, int) and 1 <= current_level <= 5 else 1
                fan_level_source = "acknowledged_ir_cycle"
            aircon_state["fan_level"] = fan_level
            aircon_state["fan_level_source"] = fan_level_source
            aircon_state["fan_level_updated_at"] = time.time()
            state["aircon"] = aircon_state
        # Advance durable state only after Control Hub 1 acknowledges the IR
        # transmit routine. A timeout/error therefore leaves the reference at
        # the last known level instead of guessing that the command worked.
        _persist_aircon_fan_level(fan_level, fan_level_source)
    note_session_activity(
        "aircon_command",
        {
            "requested_command": requested_command,
            "command": command,
            "direct": direct_temperature,
            "fan_level": fan_level,
            "desired_temperature_c": desired_temperature,
            "commanded_temperature_c": commanded_temperature,
            "temperature_mapping": "direct_1_to_1",
            "power_on_default_temperature_c": (AIRCON_POWER_ON_DEFAULT_TEMP_C if command == "on" else None),
            "preflight_command": preflight_command,
            "followup_command": followup_command,
            "swing_command": swing_command,
            "tx_count": (swing_ack or followup_ack or acknowledgement).get("tx_count"),
        },
    )
    return {
        "ok": True,
        "command": command,
        "requested_command": requested_command,
        "direct": direct_temperature,
        "fan_level": fan_level,
        "desired_temperature_c": desired_temperature,
        "commanded_temperature_c": commanded_temperature,
        "temperature_mapping": "direct_1_to_1",
        "power_on_default_temperature_c": (AIRCON_POWER_ON_DEFAULT_TEMP_C if command == "on" else None),
        "preflight_command": preflight_command,
        "preflight_ack": preflight_ack,
        "followup_command": followup_command,
        "followup_ack": followup_ack,
        "swing_command": swing_command,
        "swing_ack": swing_ack,
        "ack": acknowledgement,
        # ACK means the ESP32 reported running its IR transmit routine. The
        # air conditioner has no return channel, so physical state is unknown.
        "delivery_status": "ir_transmitted_unverified",
        "physical_confirmation": False,
        "min_ir_gap_seconds": CONTROLHUB1_MIN_IR_GAP_SECONDS,
        "power_on_settle_seconds": (CONTROLHUB1_POWER_ON_SETTLE_SECONDS if command == "on" else None),
        "fan_wake_settle_seconds": (CONTROLHUB1_FAN_WAKE_SETTLE_SECONDS if command == "fan" else None),
        "aircon": snapshot().get("aircon", {}),
    }


def set_aircon_fan_level_reference(
    cmd: AirconFanLevelReferenceCommand,
    principal: Principal = Depends(require_admin),
):
    """Align the Pi fan-cycle reference without transmitting an IR frame.

    The value is operator-observed / last-known intent, not telemetry measured
    by the air conditioner, so this correction stays in Admin Control Debug.
    """
    if not 1 <= cmd.level <= 5:
        raise HTTPException(422, "ระดับพัดลมอ้างอิงต้องอยู่ระหว่าง 1-5")
    operator = getattr(principal, "username", None) or getattr(principal, "subject", None)
    saved = _persist_aircon_fan_level(
        int(cmd.level),
        "admin_declared_reference",
        operator=operator,
    )
    with state_lock:
        aircon_state = state.get("aircon") or {}
        aircon_state["fan_level"] = int(cmd.level)
        aircon_state["fan_level_source"] = "admin_declared_reference"
        aircon_state["fan_level_updated_at"] = saved["updated_at"]
        state["aircon"] = aircon_state
    log_event(
        "aircon",
        "fan_level_reference_declared",
        level=int(cmd.level),
        operator=operator,
        note=(cmd.note or "")[:200],
        ir_transmitted=False,
    )
    note_session_activity(
        "aircon_fan_level_reference",
        {
            "level": int(cmd.level),
            "source": "admin_declared_reference",
            "ir_transmitted": False,
        },
    )
    return {
        "ok": True,
        "fan_level": int(cmd.level),
        "fan_level_source": "admin_declared_reference",
        "persisted": True,
        "ir_transmitted": False,
        "physical_confirmation": False,
        "aircon": snapshot().get("aircon", {}),
    }


def bed_control_command(cmd: BedControlCommand):
    requested_command = _normalize_bed_command(cmd.command)
    acknowledgement, command = controlhub2_bed_mqtt.publish_and_wait(requested_command, toggle_repeat=False)
    # The transport arms the deadline at publication, even if its ACK is lost.
    auto_stop_after_s = BED_MOVE_SECONDS if command in MOVEMENT_COMMANDS else None
    note_session_activity(
        "bed_command",
        {
            "requested_command": requested_command,
            "command": command,
            "auto_stop_after_s": auto_stop_after_s,
        },
    )
    return {
        "ok": True,
        "command": command,
        "requested_command": requested_command,
        "toggle_stop": False,
        "auto_stop_after_s": auto_stop_after_s,
        "ack": acknowledgement,
        "bed_control": snapshot().get("bed_control", {}),
    }


app.include_router(
    create_control_router(
        require_pod_operator=require_pod_operator,
        require_admin=require_admin,
        aircon_command=aircon_command,
        set_fan_reference=set_aircon_fan_level_reference,
        bed_command=bed_control_command,
    )
)


@app.post("/api/labels/{name}", dependencies=[Depends(require_admin)])
def set_label(name: str, cmd: LabelCommand):
    if name not in EDITABLE_LABELS:
        raise HTTPException(400, "แก้ชื่อได้เฉพาะช่อง Aroma 1-4")
    label = " ".join(cmd.label.split())[:24]
    if not label:
        raise HTTPException(422, "ชื่อว่างไม่ได้")
    with labels_lock:
        with state_lock:
            state["labels"][name] = label
            labels = dict(state["labels"])
        _save_labels(labels)
    return {"ok": True, "name": name, "label": label}


async def door_pulse(name: str) -> None:
    """Compatibility facade for serialized door actuation."""
    await _pulse_control.pulse_door(name)


async def accessory_pulse(name: str) -> None:
    """Compatibility facade for serialized aroma/steam actuation."""
    await _pulse_control.pulse_accessory(name)


app.include_router(
    create_legacy_control_router(
        require_pod_operator=require_pod_operator,
        gpio=gpio,
        gpio_outputs=GPIO_PINS,
        pulse_outputs=PULSE_OUTPUTS,
        require_safety=_require_safety_allows,
        door_pulse=door_pulse,
        accessory_pulse=accessory_pulse,
        note_activity=note_session_activity,
        log_event=log_event,
        door_pulse_seconds=DOOR_PULSE_SECONDS,
        accessory_pulse_seconds=AROMA_STEAM_PULSE_SECONDS,
    )
)


# ---------- session login / logout / history ----------
def _session_starter() -> SessionStarter:
    """Bind current adapters and clocks without copying lifecycle ownership."""
    return SessionStarter(
        StartPorts(
            session_lock=session_lock,
            state_lock=state_lock,
            profile_lock=profile_lock,
            state=state,
            get_active=lambda: _active_session,
            set_active=_set_active_session,
            normalize_username=_normalize_username,
            normalize_email=_normalize_email,
            normalize_mode=normalise_rest_mode,
            resolve_target=resolve_rest_target,
            age_group=_age_group,
            date_of_birth=_normalise_date_of_birth,
            body_measurement=_normalise_body_measurement,
            blood_group=_normalise_blood_group,
            health_reference=_health_reference_from_profile,
            wellness_context=session_context_snapshot,
            load_profiles=_load_profiles,
            save_profiles=_save_profiles,
            rest_baseline=partial(rest_window, baselines),
            acquire_lease=occupancy_client.acquire,
            release_lease=occupancy_client.release,
            occupancy_mode=lambda: occupancy_client.mode,
            current_safety=_current_safety_checkpoint_context,
            save_checkpoint=_save_active_session_checkpoint,
            reset_inference=_reset_live_sleep_inference,
            vital_gate=session_vital_gate_now,
            replace_projection=_replace_session_projection_locked,
            snapshot=snapshot,
            log_event=log_event,
            clock=time.time,
            monotonic=time.monotonic,
            utc_now=lambda: datetime.now(timezone.utc),
            session_suffix=lambda: uuid.uuid4().hex[:6],
        ),
        StartPolicy(
            pod_id=POD_ID,
            sample_interval_s=SESSION_SAMPLE_SECONDS,
            bed_start_seconds=BED_START_SECONDS,
            age_groups=AGE_SLEEP_BASELINES,
            default_ages=AGE_GROUP_DEFAULT_AGE,
            genders=GENDERS,
        ),
    )


def _start_pod_session(
    username: str,
    gender: Optional[str],
    age: Optional[int],
    age_group: Optional[str],
    *,
    owner: Principal,
    auth: Optional[Dict[str, Any]] = None,
    health_reference: Optional[Dict[str, Any]] = None,
    rest_mode: str = "nap_recovery",
    target_duration_minutes: Optional[int] = None,
) -> Dict[str, Any]:
    """Compatibility facade preserving Login inputs, HTTP errors and ownership."""
    request = StartRequest(
        username,
        gender,
        age,
        age_group,
        owner,
        auth=auth,
        health_reference=health_reference,
        rest_mode=rest_mode,
        target_duration_minutes=target_duration_minutes,
    )
    try:
        return _session_starter().start(request)
    except SessionStartRejected as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc


# Password and QR login bind an account identically; only the HTTP client, the
# event log and the offline sentinel stay in the composition root.
_zeep_binding = {
    "zeep_request": _zeep_request,
    "log_event": log_event,
    "offline_error": ZeepApiOffline,
}
_zeep_identity_from_auth_data = partial(identity_from_auth_data, **_zeep_binding)
_authenticate_zeep_account = partial(authenticate_password, **_zeep_binding)


@synchronized_by(session_lock)
def _complete_occupant_login(
    auth: Dict[str, Any],
    me: Dict[str, Any],
    *,
    age_group_choice: Optional[str],
    rest_mode: str,
    target_duration_minutes: Optional[int],
    response: Response,
) -> Dict[str, Any]:
    """Bind a verified ZEEP identity to this pod: profile, cookie, pod session.

    Password and QR login both land here so the profile gate, the Pod-only
    overrides and the revoke-on-failure guarantee cannot drift apart.
    """
    require_complete_profile(auth, me, registry=pending_profiles, log_event=log_event)
    health_reference = _zeep_health_reference(me)
    age = health_reference.get("age_years")
    age_group = (age_group_choice or "").strip() or (_age_group(age) if age is not None else None)
    account_key = auth["email"]
    # Local research aliases and verified demographic corrections are Pod-only
    # presentation/baseline overrides.  Email/publicId remain canonical and the
    # external ZEEP profile is never mutated from this appliance.
    with profile_lock:
        prior = _load_profiles().get(account_key) or {}
    if age_group is None:
        age_group = prior.get("age_group")
    if age_group is None:
        raise HTTPException(
            422,
            {
                "code": "age_group_required",
                "message": "โปรไฟล์ ZEEP ยังไม่ได้ตั้งวันเกิด — เลือกช่วงอายุเพื่อกำหนด Baseline ของ Session นี้",
            },
        )

    display_override = str(prior.get("display_name_override") or "").strip()
    gender_override = str(prior.get("gender_override") or "").strip().lower()
    if display_override:
        auth = dict(auth)
        auth["display_name"] = display_override
    if gender_override in GENDERS:
        health_reference = dict(health_reference)
        health_reference["gender"] = gender_override
        health_reference["source"] = "admin_profile_correction"

    cookie_token, principal = auth_sessions.create(
        subject=f"zeep:{auth['public_id']}",
        username=auth["username"],
        display_name=auth["display_name"],
        account_key=account_key,
        email=account_key,
        role="user",
        auth_source="zeep",
    )
    try:
        result = _start_pod_session(
            auth["username"],
            health_reference.get("gender"),
            age,
            age_group,
            owner=principal,
            auth=auth,
            health_reference=health_reference,
            rest_mode=rest_mode,
            target_duration_minutes=target_duration_minutes,
        )
    except Exception:
        auth_sessions.revoke(cookie_token)
        raise
    _set_auth_cookies(response, cookie_token, principal)
    result["user"] = {k: auth[k] for k in ("public_id", "username", "email", "display_name", "role", "plan")}
    result["principal"] = principal.public_dict()
    return result


@app.post("/api/auth/login")
@synchronized_by(session_lock)
def auth_login(cmd: AuthLoginCommand, response: Response):
    """Authenticate an occupant, acquire the pod lease, then start a pod session."""
    identifier = (cmd.identifier or "").strip()
    if not identifier or not cmd.password:
        raise HTTPException(422, "กรอก Username/Email และรหัสผ่านให้ครบ")
    if _active_session is not None:
        raise HTTPException(409, {"code": "pod_already_occupied", "message": "ตู้นี้กำลังมีผู้ใช้งาน"})
    try:
        auth, me = _authenticate_zeep_account(identifier, cmd.password)
    except ZeepApiOffline as exc:
        ticket = auth_sessions.issue_offline_ticket(identifier)
        log_event("auth", "zeep_offline", stage="login", error=str(exc))
        raise HTTPException(
            503,
            {
                "code": "offline",
                "message": "ต่อ ZEEP API ไม่ได้ — สามารถใช้ Local fallback ได้ภายใน 5 นาที",
                "offline_ticket": ticket,
                "identifier": identifier,
            },
        ) from exc

    return _complete_occupant_login(
        auth,
        me,
        age_group_choice=cmd.age_group,
        rest_mode=cmd.rest_mode,
        target_duration_minutes=cmd.target_duration_minutes,
        response=response,
    )


@app.post("/api/admin/auth/login")
def admin_auth_login(cmd: AdminLoginCommand, response: Response):
    """Create an admin browser session without becoming the pod occupant."""
    identifier = (cmd.identifier or "").strip()
    if not identifier or not cmd.password:
        raise HTTPException(422, "กรอก Username/Email และรหัสผ่านให้ครบ")

    local_admin_username = auth_sessions.authenticate_local_admin(identifier, cmd.password)
    if local_admin_username is not None:
        username = local_admin_username
        subject = f"local-admin:{username.casefold()}"
        display_name = "Local Pod Administrator"
        account_key = username.casefold()
        email = None
        source = "local_admin"
    else:
        try:
            auth, _ = _authenticate_zeep_account(identifier, cmd.password)
        except ZeepApiOffline as exc:
            raise HTTPException(
                503,
                {
                    "code": "admin_auth_offline",
                    "message": "ZEEP API ใช้งานไม่ได้ และ Local Admin ไม่ผ่านการยืนยัน",
                },
            ) from exc
        allowed_roles = {role.strip().casefold() for role in os.getenv("ZEEP_ADMIN_ROLES", "admin").split(",") if role.strip()}
        if str(auth.get("role") or "").casefold() not in allowed_roles:
            if auth.get("refresh_token"):
                try:
                    _zeep_request(
                        "POST",
                        "/v1/auth/logout",
                        json_body={"refreshToken": auth["refresh_token"]},
                    )
                except (ZeepApiOffline, HTTPException):
                    pass
            raise HTTPException(403, {"code": "admin_required", "message": "บัญชีนี้ไม่มีสิทธิ์ผู้ดูแลระบบ"})
        username = auth["username"]
        subject = f"zeep:{auth['public_id']}"
        display_name = auth["display_name"]
        account_key = auth["email"]
        email = auth["email"]
        source = "zeep_admin"
        # The browser session uses an opaque local cookie. Revoke the short-lived
        # ZEEP token family immediately because it is not needed for admin APIs.
        if auth.get("refresh_token"):
            try:
                _zeep_request(
                    "POST",
                    "/v1/auth/logout",
                    json_body={"refreshToken": auth["refresh_token"]},
                )
            except (ZeepApiOffline, HTTPException):
                pass

    cookie_token, principal = auth_sessions.create(
        subject=subject,
        username=username,
        display_name=display_name,
        account_key=account_key,
        email=email,
        role="admin",
        auth_source=source,
    )
    _set_auth_cookies(response, cookie_token, principal)
    log_event("auth", "admin_login", admin=username, source=source)
    return {"ok": True, "principal": principal.public_dict(), "pod_id": POD_ID}


@app.get("/api/auth/me")
def auth_me(principal: Principal = Depends(require_user)):
    with session_lock:
        active = _active_session
        pod_session_id = active["record"].get("session_id") if active else None
        occupant_name = active["record"].get("username") if active and principal.is_admin else None
    return {
        "principal": principal.public_dict(),
        "pod": {
            "pod_id": POD_ID,
            "occupied": bool(active),
            "owns_active_session": _principal_owns_active(active, principal),
            "session_id": pod_session_id if principal.is_admin or _principal_owns_active(active, principal) else None,
            "occupant_username": occupant_name,
        },
    }


def _require_profile_owner(principal: Principal) -> str:
    """Return the authenticated account key for self-service Profile APIs."""
    if principal.is_admin:
        raise HTTPException(
            403,
            {
                "code": "user_profile_required",
                "message": "แบบสอบถามนี้เป็นสิทธิ์ของผู้ใช้งานแต่ละบัญชี",
            },
        )
    return principal.account_key


@app.get("/api/profile/progressive")
def progressive_profile_get(principal: Principal = Depends(require_user)):
    """Return one optional, non-blocking Profile prompt for this user."""
    account_key = _require_profile_owner(principal)
    with profile_lock:
        profile = _load_profiles().get(account_key)
        if profile is None:
            raise HTTPException(404, "ไม่พบ Profile ของผู้ใช้งาน")
        snapshot = progressive_profile_snapshot(profile)
    return {"account_key": account_key, "profile": snapshot}


@app.post("/api/profile/progressive/consent")
def progressive_profile_consent(
    cmd: ProgressiveProfileConsentCommand,
    principal: Principal = Depends(require_user),
):
    """Grant or withdraw optional lifestyle-profile consent.

    Withdrawal deletes the optional answers immediately. Identity, safety and
    completed Session records remain governed by their separate purposes.
    """
    account_key = _require_profile_owner(principal)
    with profile_lock:
        profiles = _load_profiles()
        profile = profiles.get(account_key)
        if profile is None:
            raise HTTPException(404, "ไม่พบ Profile ของผู้ใช้งาน")
        set_progressive_consent(profile, cmd.granted)
        profiles[account_key] = profile
        _save_profiles(profiles)
        snapshot = progressive_profile_snapshot(profile)
    log_event(
        "profile",
        "progressive_consent_updated",
        account_key=account_key,
        status="granted" if cmd.granted else "withdrawn",
    )
    return {"ok": True, "profile": snapshot}


@app.post("/api/profile/progressive/answer")
def progressive_profile_answer(
    cmd: ProgressiveProfileAnswerCommand,
    principal: Principal = Depends(require_user),
):
    """Validate and persist one answer; free-form health text is not accepted."""
    account_key = _require_profile_owner(principal)
    question_id = str(cmd.question_id or "").strip()
    with profile_lock:
        profiles = _load_profiles()
        profile = profiles.get(account_key)
        if profile is None:
            raise HTTPException(404, "ไม่พบ Profile ของผู้ใช้งาน")
        try:
            apply_progressive_answer(profile, question_id, cmd.value)
        except PermissionError as exc:
            raise HTTPException(
                409,
                {
                    "code": str(exc),
                    "message": "กรุณาให้ความยินยอมก่อนตอบแบบสอบถาม",
                },
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                422,
                {
                    "code": str(exc),
                    "message": "คำตอบไม่อยู่ในรูปแบบที่กำหนด",
                },
            ) from exc
        profiles[account_key] = profile
        _save_profiles(profiles)
        snapshot = progressive_profile_snapshot(profile)
    # Do not put the answer value in application logs. The audit trail records
    # only who changed which versioned question and when.
    log_event(
        "profile",
        "progressive_answer_updated",
        account_key=account_key,
        question_id=question_id,
    )
    return {"ok": True, "profile": snapshot}


@app.post("/api/profile/progressive/defer")
def progressive_profile_defer(
    cmd: ProgressiveProfileDeferCommand,
    principal: Principal = Depends(require_user),
):
    """Hide the current prompt for seven days without counting it as answered."""
    account_key = _require_profile_owner(principal)
    question_id = str(cmd.question_id or "").strip() or None
    with profile_lock:
        profiles = _load_profiles()
        profile = profiles.get(account_key)
        if profile is None:
            raise HTTPException(404, "ไม่พบ Profile ของผู้ใช้งาน")
        try:
            defer_progressive_question(profile, question_id)
        except ValueError as exc:
            raise HTTPException(
                422,
                {
                    "code": str(exc),
                    "message": "ไม่พบคำถามที่ต้องการเลื่อน",
                },
            ) from exc
        profiles[account_key] = profile
        _save_profiles(profiles)
        snapshot = progressive_profile_snapshot(profile)
    return {"ok": True, "profile": snapshot}


@app.delete("/api/profile/progressive/answers/{question_id}")
def progressive_profile_delete_answer(
    question_id: str,
    principal: Principal = Depends(require_user),
):
    """Delete one optional answer and make it eligible to be asked again."""
    account_key = _require_profile_owner(principal)
    with profile_lock:
        profiles = _load_profiles()
        profile = profiles.get(account_key)
        if profile is None:
            raise HTTPException(404, "ไม่พบ Profile ของผู้ใช้งาน")
        try:
            delete_progressive_answer(profile, question_id)
        except ValueError as exc:
            raise HTTPException(
                404,
                {
                    "code": str(exc),
                    "message": "ไม่พบคำตอบที่ต้องการลบ",
                },
            ) from exc
        profiles[account_key] = profile
        _save_profiles(profiles)
        snapshot = progressive_profile_snapshot(profile)
    log_event(
        "profile",
        "progressive_answer_deleted",
        account_key=account_key,
        question_id=question_id,
    )
    return {"ok": True, "profile": snapshot}


@app.post("/api/auth/logout")
def auth_logout(
    response: Response,
    request: Request,
    principal: Principal = Depends(require_user),
):
    with session_lock:
        active = _active_session
        owns_active = _principal_owns_active(active, principal)
    if owns_active and not principal.is_admin:
        raise HTTPException(
            409,
            {
                "code": "pod_session_active",
                "message": "กรุณาจบและบันทึก Session การนอนก่อนออกจากระบบ",
            },
        )
    auth_sessions.revoke(request.cookies.get(COOKIE_NAME))
    _clear_auth_cookies(response)
    log_event("auth", "browser_logout", user=principal.username, role=principal.role)
    return {"ok": True}


@app.post("/api/session/login")
@synchronized_by(session_lock)
def session_login(cmd: LoginCommand, response: Response):
    """Local fallback: เปิด session โดยไม่ใช้บัญชี ZEEP (ไม่มีรหัสผ่าน).

    มีไว้ให้ตู้ยังเก็บข้อมูลวิจัยต่อได้ตอนเน็ตหลุด/ZEEP API ล่ม — หน้าเว็บจะเสนอ
    Backend บังคับ one-time offline ticket จึงเรียก endpoint นี้ตรง ๆ ไม่ได้.
    """
    if not auth_sessions.consume_offline_ticket(cmd.offline_ticket, cmd.offline_identifier):
        raise HTTPException(
            403,
            {
                "code": "offline_ticket_invalid",
                "message": "Local fallback หมดอายุ กรุณาลองเชื่อมต่อ ZEEP ใหม่",
            },
        )
    username = _normalize_username(cmd.username)
    cookie_token, principal = auth_sessions.create(
        subject=f"local:{POD_ID}:{username.casefold()}",
        username=username,
        display_name=username,
        account_key=username.casefold(),
        email=None,
        role="user",
        auth_source="local_fallback",
    )
    try:
        result = _start_pod_session(
            username,
            cmd.gender,
            cmd.age,
            cmd.age_group,
            owner=principal,
            health_reference={
                "gender": cmd.gender,
                "age_years": cmd.age,
                "height_cm": cmd.height_cm,
                "weight_kg": cmd.weight_kg,
                "blood_group": cmd.blood_group,
                "source": "local_profile",
            },
            rest_mode=cmd.rest_mode,
            target_duration_minutes=cmd.target_duration_minutes,
        )
    except Exception:
        auth_sessions.revoke(cookie_token)
        raise
    _set_auth_cookies(response, cookie_token, principal)
    result["principal"] = principal.public_dict()
    return result


@app.post("/api/session/logout")
def session_logout(
    principal: Principal = Depends(require_user),
):
    with session_lock:
        active = _active_session
    if active is not None and not principal.is_admin and not _principal_owns_active(active, principal):
        raise HTTPException(403, "Session นี้เป็นของผู้ใช้งานคนอื่น")
    try:
        record = _finalize_active_session("logout")
    except Exception as exc:
        raise HTTPException(500, f"บันทึก session ไม่สำเร็จ: {exc}")
    if record is None:
        raise HTTPException(409, "ไม่มี session ที่กำลังใช้งาน")
    return {
        "ok": True,
        "session_id": record["session_id"],
        "username": record["username"],
        "duration_s": record["duration_s"],
        "samples": len(record["samples"]),
        "recording_started": record.get("recording_started", True),
        "summary": record.get("summary"),
        "counters": record.get("counters") or {},
        "sleep_quality": record.get("sleep_quality"),
        "session_report": record.get("session_report"),
        "report_share": report_shares.share_for(record.get("identity_subject")),
        "auth_retained": True,
    }


@app.post("/api/admin/session/force-logout")
def admin_force_logout(
    cmd: ForceLogoutCommand,
    principal: Principal = Depends(require_admin),
):
    # Backward-compatible alias.  Existing Admin clients that call
    # force-logout receive the same strong semantics as the new kick command.
    return _admin_finish_occupant_session(cmd, principal, action="kick", default_reason="admin_force_logout")


@app.post("/api/admin/session/profile")
def admin_update_active_session_profile(
    cmd: ActiveSessionProfileCommand,
    principal: Principal = Depends(require_admin),
):
    """Correct the active participant alias and physiological gender.

    The correction is atomic across the local Profile, active Session,
    restart checkpoint, browser identity and SQLite Session row.  It never
    changes the verified email/publicId and never calls the external ZEEP API.
    """
    display_name = " ".join(str(cmd.display_name or "").strip().split())
    gender = str(cmd.gender or "").strip().lower()
    session_id = str(cmd.session_id or "").strip()
    reason = str(cmd.reason or "admin_profile_correction").strip()[:120]
    if not display_name or len(display_name) > 80:
        raise HTTPException(422, "ชื่อผู้ทดสอบต้องมี 1–80 ตัวอักษร")
    if any(ord(char) < 32 for char in display_name):
        raise HTTPException(422, "ชื่อผู้ทดสอบมีอักขระควบคุมที่ไม่อนุญาต")
    if gender not in GENDERS:
        raise HTTPException(422, f"gender ต้องเป็นหนึ่งใน {', '.join(GENDERS)}")

    with session_lock:
        active = _active_session
        if active is None:
            raise HTTPException(409, "ไม่มี Session ที่กำลังใช้งาน")
        record = active.get("record") or {}
        if not session_id or record.get("session_id") != session_id:
            raise HTTPException(409, "Session เปลี่ยนแล้ว กรุณาโหลดสถานะล่าสุด")
        account_key = str(record.get("username_key") or "").strip().casefold()
        recording_started = record.get("started_monotonic") is not None
    if not account_key:
        raise HTTPException(409, "Session ไม่มี Account Key สำหรับแก้ไข Profile")

    corrected_at = datetime.now(timezone.utc).isoformat()
    with profile_lock:
        profiles = _load_profiles()
        profile = dict(profiles.get(account_key) or {})
        if not profile:
            raise HTTPException(404, "ไม่พบ Profile ของ Session ปัจจุบัน")
        profile.update(
            {
                "display_name": display_name,
                "display_name_override": display_name,
                "gender": gender,
                "gender_override": gender,
                "health_reference_source": "admin_profile_correction",
                "health_reference_refresh_status": "admin_corrected",
                "health_reference_updated_at_utc": corrected_at,
                "profile_override_updated_at_utc": corrected_at,
                "profile_override_operator": principal.username,
                "profile_override_reason": reason,
            }
        )
        health_reference = _health_reference_from_profile(profile)
        profiles[account_key] = profile
        _save_profiles(profiles)

    with session_lock:
        active = _active_session
        if active is None or (active.get("record") or {}).get("session_id") != session_id:
            raise HTTPException(409, "Session สิ้นสุดระหว่างแก้ไข Profile")
        active["record"].update(
            {
                "display_name": display_name,
                "gender": gender,
                "health_reference": health_reference,
            }
        )
        if isinstance(active.get("auth"), dict):
            active["auth"]["display_name"] = display_name
        _save_active_session_checkpoint(active)

    browser_sessions = auth_sessions.update_user_display_name(account_key, display_name)
    with state_lock:
        _patch_session_projection_locked(
            {
                "display_name": display_name,
                "gender": gender,
                "health_reference": health_reference,
            }
        )
    if recording_started:
        database.enqueue(
            "sessions",
            "session_profile_update",
            {
                "session_id": session_id,
                "gender": gender,
            },
        )
        database.enqueue(
            "sessions",
            "event",
            {
                "session_id": session_id,
                "timestamp": corrected_at,
                "type": "profile_metadata_correction",
                "value": {
                    "display_name": display_name,
                    "gender": gender,
                    "reason": reason,
                    "operator": principal.username,
                },
            },
        )
        if not database.flush(5.0):
            raise HTTPException(503, "บันทึก Profile correction ลงฐานข้อมูลยังไม่เสร็จ")
    _reset_live_sleep_inference(session_id)
    log_event(
        "admin",
        "active_profile_corrected",
        admin=principal.username,
        session_id=session_id,
        account_key=account_key,
        display_name=display_name,
        gender=gender,
        reason=reason,
        browser_sessions_updated=browser_sessions,
    )
    return {
        "ok": True,
        "session_id": session_id,
        "display_name": display_name,
        "gender": gender,
        "account_key_unchanged": True,
        "browser_sessions_updated": browser_sessions,
        "sleep_inference_reset": True,
        "session": snapshot()["session"],
    }


def _admin_finish_occupant_session(
    cmd: ForceLogoutCommand,
    principal: Principal,
    *,
    action: str,
    default_reason: str,
) -> Dict[str, Any]:
    """Persist the active record, then optionally revoke the occupant login.

    Owner identity is copied before finalization clears ``_active_session``.
    The database flush and occupancy-lease release are therefore always
    completed before a browser is removed from the Pod.
    """
    with session_lock:
        active = _active_session
        owner_session_id = active.get("owner_auth_session_id") if active else None
        owner_subject = active["record"].get("identity_subject") if active else None
    if active is None:
        raise HTTPException(409, "ไม่มี Session ที่กำลังใช้งาน")
    reason = (cmd.reason or default_reason).strip()[:80] or default_reason
    try:
        record = _finalize_active_session(reason)
    except Exception as exc:
        raise HTTPException(500, f"บันทึก Session ไม่สำเร็จ: {exc}") from exc
    if record is None:
        raise HTTPException(409, "ไม่มี Session ที่กำลังใช้งาน")

    # "end" revokes only the browser that owned this physical Session.  A
    # force kick revokes all local User cookies for the same immutable account.
    # Both return the shared tablet to Login; Admin authentication is untouched.
    revoked = auth_sessions.revoke_user_identity(
        session_id=owner_session_id,
        subject=owner_subject,
        all_for_subject=action == "kick",
    )
    event = "occupant_kicked" if action == "kick" else "session_ended"
    log_event(
        "admin",
        event,
        admin=principal.username,
        session_id=record["session_id"],
        user=record["username"],
        reason=reason,
        revoked_browser_sessions=revoked,
    )
    return {
        "ok": True,
        "action": action,
        "session_id": record["session_id"],
        "username": record["username"],
        "account_key": record["username_key"],
        "email": (record["username_key"] if "@" in str(record.get("username_key") or "") else None),
        "duration_s": record["duration_s"],
        "samples": len(record["samples"]),
        "recording_started": record.get("recording_started", True),
        "sleep_quality": record.get("sleep_quality"),
        "session_report": record.get("session_report"),
        "revoked_browser_sessions": revoked,
    }


@app.post("/api/admin/session/end")
def admin_end_session(
    cmd: ForceLogoutCommand,
    principal: Principal = Depends(require_admin),
):
    """Gracefully finish the current recording and sign out its owner."""
    return _admin_finish_occupant_session(cmd, principal, action="end", default_reason="admin_end_session")


@app.post("/api/admin/session/kick")
def admin_kick_occupant(
    cmd: ForceLogoutCommand,
    principal: Principal = Depends(require_admin),
):
    """Finish the Session and revoke every local User login for its owner."""
    return _admin_finish_occupant_session(cmd, principal, action="kick", default_reason="admin_kick_occupant")


@app.get("/api/users", dependencies=[Depends(require_admin)])
def users_list():
    with profile_lock:
        profiles = _load_profiles()
    availability = session_availability_by_account(
        database.read_sessions,
        PERSONAL_BASELINE_LEARNING_START_UTC,
    )
    with session_lock:
        active_record = dict((_active_session or {}).get("record") or {})
    return {
        "users": _users_ordered_by_latest_session(
            profiles,
            active_record,
            availability,
            progress_summary=admin_progress_summary,
        )
    }


@app.get("/api/sleep/baselines")
def sleep_baselines():
    """Single source of truth for the age-range selector and estimator UI."""
    return {
        "age_groups": AGE_SLEEP_BASELINES,
        "gender_adjustments": GENDER_BASELINE_ADJUSTMENTS,
        "order": ["18-29", "30-44", "45-59", "60+"],
    }


@app.get("/api/admin/sleep/policy", dependencies=[Depends(require_admin)])
def sleep_policy_admin():
    """Expose the exact deployed sleep policy to Admin for audit/debug only."""
    policy = sleep_policy_snapshot()
    policy["runtime"] = {
        "analysis_interval_seconds": SLEEP_SAMPLE_SECONDS,
        "sensor_sample_seconds": SLEEP_SAMPLE_SECONDS,
        "evidence_epoch_seconds": SLEEP_EVIDENCE_EPOCH_SECONDS,
        "evidence_sensor_frames": SLEEP_SENSOR_FRAMES_PER_EPOCH,
        "confirmation_seconds": SLEEP_CONFIRMATION_SECONDS,
        "confirmation_seconds_by_target": dict(SLEEP_STAGE_CONFIRMATION_SECONDS),
        "confirmation_epochs": SLEEP_CONFIRM_EPOCHS,
        "evidence_and_confirmed_state_separate": True,
        "rolling_window_seconds": SLEEP_WINDOW_SECONDS,
        "rolling_window_frames": SLEEP_MIN_FRAMES,
        "session_sample_seconds": SESSION_SAMPLE_SECONDS,
        "bed_exit_confirmation": {
            "consecutive_analysis_buckets": BED_EXIT_CONFIRM_BUCKETS,
            "raw_packet_minimum": BED_EXIT_RAW_MIN_FRAMES,
            "raw_packet_ratio": BED_EXIT_RAW_MIN_RATIO,
            "raw_packet_can_confirm": BED_EXIT_RAW_CONFIRMATION_ENABLED,
            "isolated_mid_session_code": "transient_rejected",
            "raw_status_retained_for_admin": True,
        },
        "baseline_weights": {
            "hr": SLEEP_BASELINE_HR_WEIGHT,
            "rr": SLEEP_BASELINE_RR_WEIGHT,
            "n3_rr_conflict_penalty": SLEEP_N3_RR_CONFLICT_PENALTY,
            "n2_rr_conflict_support": SLEEP_N2_RR_CONFLICT_SUPPORT,
        },
        "humidity_bias_percentage_points": HUMIDITY_RH_BIAS,
        "sound_display_transform": {
            "formula": "ESP32 sound_dba -> Pi direct",
            "legacy_dbfs_policy": "invalid",
            "pi_abs_transform_allowed": False,
        },
        "sensor_biases": dict(SENSOR_BIASES),
    }
    return policy


def _session_history_service() -> SessionHistoryService:
    """Build the read service from the current reviewed report contracts."""
    return SessionHistoryService(
        database,
        history_start_utc=PERSONAL_BASELINE_LEARNING_START_UTC,
        report_version=SESSION_REPORT_VERSION,
        release_quality=_released_historical_quality,
        health_reference=_health_reference_from_profile,
    )


def _history_window(
    date_from: Optional[str],
    date_to: Optional[str],
    time_from: str,
    time_to: str,
    *,
    default_today: bool,
):
    timezone_name = POD_TIMEZONE or "Asia/Bangkok"
    if default_today and not date_from and not date_to:
        date_from = local_history_day(timezone_name)
        date_to = date_from
    try:
        return resolve_history_window(
            date_from,
            date_to,
            time_from,
            time_to,
            timezone_name=timezone_name,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/admin/history", dependencies=[Depends(require_admin)])
def admin_history_list(
    response: Response,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    time_from: str = "00:00",
    time_to: str = "23:59",
    account_key: Optional[str] = None,
    query: Optional[str] = None,
    limit: int = 500,
):
    """Return a local-day roster and released score for each participant."""
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"
    window = _history_window(
        date_from,
        date_to,
        time_from,
        time_to,
        default_today=True,
    )
    with profile_lock:
        profiles = _load_profiles()
    return _session_history_service().admin_history(
        profiles,
        window=window,
        account_key=account_key,
        query=query,
        limit=limit,
    )


@app.get("/api/history/{username}")
def history_list(
    username: str,
    response: Response,
    limit: int = 200,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    time_from: str = "00:00",
    time_to: str = "23:59",
    principal: Principal = Depends(require_user),
):
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"
    key = _require_username_access(username, principal)
    window = _history_window(
        date_from,
        date_to,
        time_from,
        time_to,
        default_today=False,
    )
    with profile_lock:
        profiles = _load_profiles()
        history_profile = safe_account_profile(key, dict(profiles.get(key) or {}), profiles)
    return _session_history_service().account_history(
        key,
        history_profile,
        window=window,
        limit=limit,
    )


@app.get("/api/history/{username}/{session_id}")
def history_detail(
    username: str,
    session_id: str,
    response: Response,
    principal: Principal = Depends(require_user),
):
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"
    key = _require_username_access(username, principal)
    with profile_lock:
        profiles = _load_profiles()
        profile = safe_account_profile(key, dict(profiles.get(key) or {}), profiles)
    authorized = _session_history_service().session_by_id(session_id, profiles, account_key=key)
    if authorized is None:
        raise HTTPException(404, "ไม่พบ session นี้")
    rows = database.read_sessions(
        "SELECT s.* FROM sessions AS s WHERE s.session_id=?",
        (session_id,),
    )
    row = rows[0]
    timeline = database.read_sessions("SELECT * FROM timeline WHERE session_id=? ORDER BY timestamp", (session_id,))
    timeline_interval_s = _timeline_sample_interval(timeline, 5.0)
    canonical_bed_labels = debounced_bed_status_labels([x["bed_status"] for x in timeline])
    samples = history_support.history_samples_from_rows(
        timeline,
        canonical_bed_labels,
        sample_interval_s=timeline_interval_s,
        include_raw_bed_status=principal.is_admin,
    )
    events = database.read_sessions(
        "SELECT timestamp,type,value FROM events WHERE session_id=? ORDER BY timestamp",
        (session_id,),
    )
    final_summary = history_support.latest_final_summary(events)
    history_interval_s = _sample_interval_seconds(final_summary.get("sample_interval_s"), timeline_interval_s)
    cadence_segments = _normalise_cadence_segments(
        final_summary.get("sample_cadence_segments"),
        start_at_utc=row["start_time"],
        fallback_interval_s=history_interval_s,
    )
    for sample in samples:
        sample["sample_interval_s"] = _cadence_interval_at(sample.get("t"), cadence_segments, history_interval_s)
    report_samples, history_interval_s, cadence_summary = _normalise_samples_for_report(samples, history_interval_s)
    annotation_rows = [event for event in events if event["type"] == "sleep_stage_annotation"]
    annotations = load_annotations(annotation_rows)
    parsed_events = history_support.parse_history_sleep_events(
        events,
        annotations=annotations,
        sample_interval_s=history_interval_s,
        apply_annotations=apply_annotations,
    )
    stage_points = parsed_events["stage_points"]
    status_points = parsed_events["status_points"]
    terminal_wake_event = parsed_events["terminal_wake_event"]
    counters = parsed_events["counters"]
    bed_counts = history_support.history_bed_counts(
        report_samples,
        final_summary.get("bed_status_counts"),
    )
    report_end = row["end_time"] or datetime.now(timezone.utc).isoformat()
    timeline_result = history_support.assemble_history_sleep_timeline(
        stage_points,
        status_points,
        raw_timeline=timeline,
        report_end=report_end,
        session_start=row["start_time"],
        session_end=row["end_time"],
        end_reason=row["end_reason"],
        sample_interval_s=history_interval_s,
        fallback_estimator=final_summary.get("sleep_estimator"),
        persisted_terminal_wake=final_summary.get("terminal_wake_transition"),
        terminal_wake_event=terminal_wake_event,
    )
    sleep_timeline = timeline_result["sleep_timeline"]
    terminal_occupancy = timeline_result["terminal_occupancy"]
    classification_end = timeline_result["classification_end"]
    terminal_wake = timeline_result["terminal_wake"]
    classification_gaps: List[Dict[str, Any]] = []
    sleep_continuity_accounting = history_support.history_continuity_accounting(
        sleep_timeline,
        session_start=row["start_time"],
        classification_end=classification_end,
    )
    history_rest_mode, history_target_duration_s = (
        history_support.canonical_history_rest_metadata(row, final_summary)
    )
    night_summary = final_summary.get("night_summary") or {}
    sleep_quality = night_summary.get("sleep_quality")
    sleep_quality = _released_historical_quality(
        final_summary,
        sleep_quality,
    )
    persisted_session_report = final_summary.get("session_report")
    restore_context = final_summary.get("restore_context")
    if not isinstance(restore_context, dict):
        restore_context = None
    health_reference = final_summary.get("health_reference")
    if not isinstance(health_reference, dict):
        health_reference = _health_reference_from_profile(profile)
    persisted_report_version = persisted_session_report.get("version") if isinstance(persisted_session_report, dict) else None
    session_report = persisted_session_report
    history_sleep_counts = final_summary.get("sleep_state_counts") or {}
    if not isinstance(session_report, dict) or persisted_report_version != SESSION_REPORT_VERSION:
        projection = history_support.project_history_report_samples(
            samples,
            start_at=row["start_time"],
            end_at=report_end,
            cadence_segments=cadence_segments,
            sensor_interval_s=_sample_interval_seconds(
                final_summary.get("sensor_sample_interval_s"),
                timeline_interval_s,
            ),
            decision_interval_s=history_interval_s,
            stage_points=stage_points,
            status_points=status_points,
            timeline_periods=sleep_timeline,
            terminal_occupancy=terminal_occupancy,
            heart_rate_range=HR_SANITY_RANGE_BPM,
            respiration_rate_range=RR_SANITY_RANGE_PER_MIN,
        )
        projected_report_samples = projection["report_samples"]
        projected_interval_s = projection["report_interval_s"]
        projected_sleep_counts = projection["sleep_state_counts"]
        projected_score_counts = projection["sleep_score_state_counts"]
        history_sleep_counts = projected_sleep_counts
        session_report = build_session_report(
            row["duration"],
            projected_report_samples,
            night_summary,
            projected_sleep_counts,
            sleep_quality,
            rest_mode=history_rest_mode,
            sample_interval_s=projected_interval_s,
            estimator_version=final_summary.get("sleep_estimator"),
            completed=bool(row["end_time"]),
            timeline_schema_version=int(final_summary.get("timeline_schema_version") or 3),
            target_duration_s=history_target_duration_s,
            personal_context=restore_context,
            trend_context=restore_context,
            health_reference=health_reference,
            sleep_score_state_counts=projected_score_counts,
        )
        session_report["display_recomputed"] = True
        session_report["display_recomputed_from_version"] = persisted_report_version
        session_report["persisted_record_unchanged"] = True
    canonical_key = str(authorized.get("account_key") or key)
    canonical_email = authorized.get("email") or profile.get("email") or profile.get("zeep_email")
    return {
        "session_id": row["session_id"],
        "username": profile.get("username") or row["user"],
        "display_name": authorized.get("display_name") or row["user"],
        "account_key": canonical_key,
        "email": canonical_email or (canonical_key if "@" in canonical_key else None),
        # Legacy response alias retained for existing Admin tools.
        "username_key": canonical_key,
        "gender": row["gender"],
        "age": profile.get("age"),
        "age_group": profile.get("age_group"),
        "health_reference": health_reference,
        "wellness_context": final_summary.get("wellness_context"),
        "started_at_utc": row["start_time"],
        "ended_at_utc": row["end_time"],
        "duration_s": row["duration"],
        "end_reason": row["end_reason"],
        "sample_interval_s": history_interval_s,
        "sensor_sample_interval_s": final_summary.get("sensor_sample_interval_s", history_interval_s),
        "sample_cadence_segments": cadence_segments,
        "sample_cadence_summary": (final_summary.get("sample_cadence_summary") or cadence_summary),
        "samples": samples,
        "sleep_timeline": sleep_timeline,
        "sleep_timeline_rounds": len(stage_points),
        "sleep_status_timeline_rounds": len(status_points),
        "sleep_timeline_source": ("persisted_decisions_with_continuity_fill"),
        "sleep_continuity_accounting": sleep_continuity_accounting,
        "sleep_classification_gap_count": len(classification_gaps),
        "sleep_classification_gap_seconds": round(
            sum(float(period.get("duration_s") or 0.0) for period in classification_gaps),
            1,
        ),
        "terminal_occupancy_timeline": terminal_occupancy,
        "terminal_wake_transition": terminal_wake,
        "sleep_stage_annotation_count": len(annotations),
        "sleep_estimator": final_summary.get("sleep_estimator"),
        "sleep_estimator_versions": final_summary.get("sleep_estimator_versions") or {},
        "sleep_provenance_complete": final_summary.get("sleep_provenance_complete"),
        "sleep_policy_versions": {
            "evidence": final_summary.get("sleep_evidence_version"),
            "baseline": final_summary.get("sleep_baseline_version"),
            "transition": final_summary.get("sleep_transition_policy"),
            "g2_ontology": final_summary.get("sleep_g2_ontology"),
            "terminal_wake": final_summary.get("terminal_wake_policy"),
        },
        "rest_mode": history_rest_mode,
        "target_duration_s": history_target_duration_s,
        "sleep_quality": sleep_quality,
        "session_report": session_report,
        "summary": {
            "temperature_c": _series_stats([s["temp"] for s in samples]),
            "humidity_rh": _series_stats([s["hum"] for s in samples]),
            "sound_dba_est": _series_stats([s["dba"] for s in samples]),
            "lux": _series_stats([s["lux"] for s in samples]),
            "heart_rate_bpm": _series_stats([s["hr"] for s in samples]),
            "respiration_rate": _series_stats([s["rr"] for s in samples]),
            "bed_status_counts": bed_counts,
            "sleep_state_counts": history_sleep_counts,
        },
        "counters": final_summary.get("counters") or counters,
    }


# ---------- audio API ----------
audio_service = AudioControlService(
    player=player,
    music_dir=MUSIC_DIR,
    preview_dir=BRAINWAVE_PREVIEW_DIR,
    command_lock=threading.Lock(),
    stop_guard_seconds=MUSIC_STOP_GUARD_SECONDS,
    occupancy_token=_active_session_token,
    safety_guard=_require_safety_allows,
    snapshot_music=player.snapshot,
    note_activity=note_session_activity,
    logger=log_event,
    presets=brainwave_public_presets,
    # Resolve through this module at call time so diagnostics can replace the
    # renderer without rebuilding the API service.
    render_preview=lambda *args: render_brainwave_preview(*args),
)
app.include_router(
    create_audio_router(
        audio_service,
        require_admin=require_admin,
        require_pod_operator=require_pod_operator,
    )
)


def _graceful_poweroff() -> None:
    """Drain research data before handing power-off to systemd."""
    time.sleep(1.0)  # allow the HTTP response to reach the tablet
    try:
        with session_lock:
            active = _active_session
        if active is not None:
            _save_active_session_checkpoint(active)
            if active.get("phase") == "recording":
                database.enqueue(
                    "sessions",
                    "event",
                    {
                        "session_id": active["record"]["session_id"],
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "type": "service_pause",
                        "value": {"reason": "system_poweroff"},
                    },
                )
        bcg_storage.flush()
        database.flush(30)
        daily_backup.stop()
        database.stop(30)
        player.shutdown()
        gpio.all_off()
        log_event("system", "poweroff")
        if hasattr(os, "sync"):
            os.sync()
        subprocess.run(["systemctl", "poweroff"], check=True)
    except Exception as exc:
        log_event("system", "poweroff_failed", error=str(exc))


@app.post("/api/system/shutdown", dependencies=[Depends(require_admin)], status_code=202)
def system_shutdown():
    if os.getenv("ENABLE_SYSTEM_POWEROFF", "0") != "1":
        raise HTTPException(503, "Set ENABLE_SYSTEM_POWEROFF=1 on the Raspberry Pi")
    threading.Thread(target=_graceful_poweroff, name="system-poweroff", daemon=False).start()
    return {"ok": True, "status": "flushing_before_poweroff"}


if __name__ == "__main__":
    import uvicorn

    # Do not let long-lived tablet WebSockets consume systemd's entire
    # TimeoutStopSec.  Uvicorn closes them after five seconds, leaving the
    # lifespan shutdown enough time to flush the active Session database.
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        timeout_graceful_shutdown=5,
    )
