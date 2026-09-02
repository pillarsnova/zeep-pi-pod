"""ZEEP Pod local dashboard server (Raspberry Pi 5).

Single-file FastAPI app: ESP32 + BCG serial readers, GPIO outputs
(door/ceiling light/star light/aroma/steam), local music playback, per-person test sessions with
on-device history. Built and maintained in the zeep-lab Claude session —
keep changes going through that session so the trail stays in git.
"""
import asyncio
import json
import math
import os
import shutil
import socket
import struct
import subprocess
import tempfile
import threading
import time
import uuid
import secrets
from collections import Counter, deque
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
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
    Cookie,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Team database layer (SQLite V2): queue-based single-writer + BCG epoch
# storage + daily backup + read-side history router. Merged 2026-08-04.
from api_history import create_history_router
from access_control import (
    COOKIE_NAME,
    CSRF_COOKIE_NAME,
    AuthSessionManager,
    Principal,
)
from backup import DailyBackup
from bcg_storage import BCGStorage
from database import DatabaseManager
from api_v1 import create_api_v1_router
from maintenance_registry import maintenance_contract_snapshot
from migration import migrate_jsonl
from personal import BaselineStore
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
from sensor_contracts import (
    ENVIRONMENT_DEVICE_SPECS,
    decode_hub_payload,
    parse_lsm800t_frame,
    sensor_contract_snapshot,
)
from sleep_signal_features import (
    HR_SANITY_RANGE_BPM,
    RR_SANITY_RANGE_PER_MIN,
    arousal_proxy_evidence,
    bed_exit_window_evidence,
    debounced_bed_status_labels,
    filter_vital_values,
    movement_window_metrics,
    sleep_classification_gap_timeline,
    summary_features,
    terminal_occupancy_timeline,
    terminal_wake_transition,
    waveform_features,
)
from sleep_stage_scoring import (
    align_probabilities_to_emitted_stage,
    score_sleep_evidence,
    smooth_stage_probabilities,
    stable_probability_candidate,
)
from sleep_stage_annotations import apply_annotations, load_annotations
from sleep_session_report import (
    build_session_report,
    build_sleep_quality,
    normalise_rest_mode,
)
from sleep_system_policy import (
    ENVIRONMENT_CONTEXT_POLICY_VERSION,
    SESSION_REPORT_VERSION,
    SLEEP_ALLOWED_TRANSITIONS,
    SLEEP_ESTIMATOR_VERSION,
    SLEEP_EVIDENCE_VERSION,
    SLEEP_G2_ONTOLOGY_VERSION,
    SLEEP_DISPLAY_WINNER_MARGIN,
    SLEEP_CONFIRMATION_SECONDS,
    SLEEP_CONFIRM_EPOCHS,
    SLEEP_EVIDENCE_EPOCH_SECONDS,
    SLEEP_PROBABILITY_EMA_ALPHA,
    SLEEP_PROBABILITY_SWITCH_MARGIN,
    SLEEP_SENSOR_FRAMES_PER_EPOCH,
    SLEEP_SENSOR_SAMPLE_SECONDS,
    SLEEP_STAGE_CONFIRM_TICKS,
    SLEEP_STAGE_MIN_DWELL_SECONDS,
    TERMINAL_WAKE_POLICY_VERSION,
    ZEEP_SLEEP_BASELINE_VERSION,
    ZEEP_SLEEP_STATES,
    ZEEP_SLEEP_TRANSITION_POLICY_VERSION,
    assess_environment_values,
    sleep_policy_snapshot,
)


try:
    from gpiozero import OutputDevice
    from gpiozero.pins.lgpio import LGPIOFactory
    GPIO_AVAILABLE = True
except Exception:
    OutputDevice = None
    LGPIOFactory = None
    GPIO_AVAILABLE = False

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
MUSIC_DIR = Path(os.getenv("MUSIC_DIR", str(BASE_DIR / "music")))
MUSIC_DIR.mkdir(parents=True, exist_ok=True)

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
AROMA_STEAM_PULSE_SECONDS = float(os.getenv("AROMA_STEAM_PULSE_SECONDS", "1.0"))
PULSE_OUTPUTS = {"aroma1", "aroma2", "aroma3", "aroma4", "steam"}
# Minimum idle time between pulses on the same output (relay wear / spam guard).
PULSE_COOLDOWN_SECONDS = float(os.getenv("PULSE_COOLDOWN_SECONDS", "1.0"))
# Sensor values older than these are reported as disconnected/stale to the UI.
# BCG (LSM-800-T) emits a frame only every few seconds — quiet gaps are normal,
# so its threshold must sit well above the inter-frame interval.
ESP32_STALE_SECONDS = float(os.getenv("ESP32_STALE_SECONDS", "5"))
# LSM-800-T ส่ง frame ห่างมากเมื่อเตียงว่าง — 60 วิคือ "เงียบผิดปกติจริง"
# (ตอนมีคนบนเตียง frame มาทุก ~2-4 วิ; ค่าสั้นกว่านี้ทำให้ pill กระพริบทั้งที่ปกติ)
BCG_STALE_SECONDS = float(os.getenv("BCG_STALE_SECONDS", "60"))
# The LSM-800-T can emit a transient zero while motion disturbs its internal
# vital-sign estimator. Keep the last valid display value briefly, but clear it
# immediately when the bed no longer represents a person so stale vitals are
# never attributed to a new occupant.
BCG_VITAL_HOLD_SECONDS = float(os.getenv("BCG_VITAL_HOLD_SECONDS", "15"))
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
SAFETY_TEMP_CRITICAL_MAX_C = float(
    _SAFETY_MAX_TEMP or os.getenv("SAFETY_TEMP_CRITICAL_MAX_C", "32")
)
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
    raise RuntimeError(
        "stable-30s-epoch requires 10-second sensor samples; "
        f"received {SLEEP_SAMPLE_SECONDS:g} seconds"
    )
# LSM-800-T bed exit is a high-impact occupancy/safety result, so it must
# survive a temporal confirmation guard. Three 10-second buckets confirm an
# exit. Raw packet bursts are retained for Admin diagnostics but cannot create
# a Wake epoch because field data contained false exit pulses up to seven frames.
BED_EXIT_CONFIRM_BUCKETS = max(3, int(os.getenv("BED_EXIT_CONFIRM_BUCKETS", "3")))
BED_EXIT_RAW_MIN_FRAMES = max(3, int(os.getenv("BED_EXIT_RAW_MIN_FRAMES", "5")))
BED_EXIT_RAW_MIN_RATIO = min(
    1.0, max(0.6, float(os.getenv("BED_EXIT_RAW_MIN_RATIO", "0.8"))))
BED_EXIT_RAW_CONFIRMATION_ENABLED = (
    os.getenv("BED_EXIT_RAW_CONFIRMATION_ENABLED", "false").strip().lower()
    in {"1", "true", "yes", "on"}
)
# Target context for one evidence estimate. Sensor frames arrive every 10 s,
# become one evidence epoch every 30 s, and require two matching evidence
# epochs before a W/N1/N2/N3/REM state is confirmed. Until then the API exposes
# the evidence candidate but deliberately returns no confirmed stage.
SLEEP_MIN_FRAMES = max(1, int(os.getenv(
    "SLEEP_MIN_FRAMES",
    str(math.ceil(SLEEP_WINDOW_SECONDS / SLEEP_SAMPLE_SECONDS)),
)))
# Fraction of "Moving" frames in the window at/above which we call Wake.
SLEEP_MOVE_WAKE_RATIO = float(os.getenv("SLEEP_MOVE_WAKE_RATIO", "0.15"))
# Legacy/personal calibration thresholds for the coefficient of variation of
# fixed-cadence HR summaries. This is explicitly NOT RMSSD/SDNN or ECG HRV. v1.8
# keeps it as a weak proxy and does not introduce a beat detector.
SLEEP_HR_CV_REM = float(os.getenv("SLEEP_HR_CV_REM", "0.06"))
# NREM depth proxy (NOT AASM N1/N2/N3 — those are EEG-defined and PSG-only).
# The five output labels now map one-to-one to the amended five-class G2
# validation ontology, but remain exploratory until paired-PSG validation.
SLEEP_HR_CV_DEEP = float(os.getenv("SLEEP_HR_CV_DEEP", "0.025"))
SLEEP_MOVE_DEEP_RATIO = float(os.getenv("SLEEP_MOVE_DEEP_RATIO", "0.05"))
# Baseline fit keeps 10% of the score budget for movement/variability/timing.
# RR is raised slightly from 0.35 to 0.40 after the Pod produced excessive N3
# while measured RR remained closer to its N2 range. These are versioned ZEEP
# engineering weights, not AASM scoring coefficients.
SLEEP_BASELINE_HR_WEIGHT = float(os.getenv("SLEEP_BASELINE_HR_WEIGHT", "0.50"))
SLEEP_BASELINE_RR_WEIGHT = float(os.getenv("SLEEP_BASELINE_RR_WEIGHT", "0.40"))
SLEEP_N3_RR_CONFLICT_PENALTY = float(os.getenv("SLEEP_N3_RR_CONFLICT_PENALTY", "1.20"))
SLEEP_N2_RR_CONFLICT_SUPPORT = float(os.getenv("SLEEP_N2_RR_CONFLICT_SUPPORT", "0.30"))
# A microphone event can support Wake only when the same rolling window also
# contains BCG amplitude change or bed motion.  Continuous background sound,
# air quality and comfort telemetry never create a stage by themselves.
SLEEP_ACOUSTIC_DISTURBANCE_DBA = float(
    os.getenv("SLEEP_ACOUSTIC_DISTURBANCE_DBA", "55"))
SLEEP_ACOUSTIC_MIN_COVERAGE = float(
    os.getenv("SLEEP_ACOUSTIC_MIN_COVERAGE", "0.50"))
SLEEP_ACOUSTIC_WAKE_SUPPORT_MAX = float(
    os.getenv("SLEEP_ACOUSTIC_WAKE_SUPPORT_MAX", "0.35"))
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
MUSIC_STOP_GUARD_SECONDS = max(
    0.5, float(os.getenv("MUSIC_STOP_GUARD_SECONDS", "4.0")))
# User-facing temperatures describe the preferred Pod setting. The aircon IR
# command is intentionally biased colder because the current installation's
# measured room response runs warmer than its setpoint. Keep this conversion
# on the Pi API so every UI/client applies exactly the same rule.
AIRCON_TEMPERATURE_BIAS_C = int(os.getenv("AIRCON_TEMPERATURE_BIAS_C", "-5"))
AIRCON_DESIRED_TEMP_MIN_C = 15
AIRCON_DESIRED_TEMP_MAX_C = 25
AIRCON_POWER_ON_DEFAULT_TEMP_C = int(os.getenv("AIRCON_POWER_ON_DEFAULT_TEMP_C", "18"))
if not 5 <= AIRCON_POWER_ON_DEFAULT_TEMP_C <= 32:
    raise RuntimeError("AIRCON_POWER_ON_DEFAULT_TEMP_C must be between 5 and 32 °C")

# ---------- user profiles & test sessions (stored only on this pod) ----------
# PDPA boundary: profiles/sessions live in DATA_DIR on the Pi itself, never in
# git. Records carry named users + HR/RR trends, so treat DATA_DIR as personal
# data: keep it on-device and honor deletion via DELETE /api/users/{account_key}.
# ZEEP accounts use normalized email as the canonical data key; mutable
# username/displayName values are presentation metadata only.
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data")))
PROFILES_PATH = DATA_DIR / "profiles.json"
SESSIONS_PATH = DATA_DIR / "sessions.jsonl"
LABELS_PATH = DATA_DIR / "output_labels.json"
AIRCON_CONTROL_STATE_PATH = DATA_DIR / "aircon_control_state.json"
ACTIVE_SESSION_CHECKPOINT_PATH = DATA_DIR / "active_session_checkpoint.json"
# One JSON file per finished Session still waiting to reach the account
# backend. The file holds the finished upload payload so a retry never has
# to rebuild it from SQLite. PDPA: same personal boundary as DATA_DIR.
INGEST_OUTBOX_DIR = DATA_DIR / "ingest_outbox"
AIRCON_CONTROL_STATE_LOCK = threading.Lock()
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
SESSION_TIMELINE_SCHEMA_VERSION = 4
if SESSION_SAMPLE_SECONDS <= 0:
    raise RuntimeError("Session sample cadence must be positive")
# Keep at least the previous 16 h 40 m capacity. At the new 10-second cadence,
# 12,000 rows cover 33 h 20 m and still allow a legacy 5-second active Session
# to resume without truncation during this deployment.
SESSION_SAMPLE_LIMIT = int(os.getenv("SESSION_SAMPLE_LIMIT", "12000"))


def _sample_interval_seconds(value: Any, fallback: float = SESSION_SAMPLE_SECONDS) -> float:
    """Return a sane persisted cadence without rewriting legacy Sessions."""
    try:
        interval = float(value)
    except (TypeError, ValueError):
        interval = float(fallback)
    return interval if math.isfinite(interval) and interval > 0 else float(fallback)


def _timeline_sample_interval(rows: List[Dict[str, Any]], fallback: float = 5.0) -> float:
    """Infer old Session cadence from timestamps when no versioned value exists."""
    timestamps: List[float] = []
    for row in rows[:120]:
        try:
            timestamps.append(datetime.fromisoformat(str(row["timestamp"])).timestamp())
        except (KeyError, TypeError, ValueError):
            continue
    gaps = sorted(
        current - previous
        for previous, current in zip(timestamps, timestamps[1:])
        if 0.5 <= current - previous <= 60.0
    )
    if not gaps:
        return _sample_interval_seconds(fallback, 5.0)
    return round(gaps[len(gaps) // 2], 3)


def _cadence_segment(
    start_at_utc: Any,
    sample_interval_s: Any,
) -> Optional[Dict[str, Any]]:
    """Return one validated, JSON-safe Session cadence segment."""
    try:
        start = datetime.fromisoformat(str(start_at_utc))
    except (TypeError, ValueError):
        return None
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    return {
        "start_at_utc": start.astimezone(timezone.utc).isoformat(),
        "sample_interval_s": _sample_interval_seconds(sample_interval_s),
    }


def _normalise_cadence_segments(
    raw_segments: Any,
    *,
    start_at_utc: Any,
    fallback_interval_s: Any,
) -> List[Dict[str, Any]]:
    """Validate persisted cadence history and guarantee an initial segment."""
    segments: List[Dict[str, Any]] = []
    for raw in raw_segments if isinstance(raw_segments, list) else []:
        if not isinstance(raw, dict):
            continue
        segment = _cadence_segment(
            raw.get("start_at_utc"), raw.get("sample_interval_s"))
        if segment is not None:
            segments.append(segment)
    segments.sort(key=lambda item: item["start_at_utc"])
    if not segments:
        initial = _cadence_segment(start_at_utc, fallback_interval_s)
        if initial is not None:
            segments.append(initial)
    return segments


def _cadence_interval_at(
    epoch_s: Any,
    segments: Any,
    fallback_interval_s: Any,
) -> float:
    """Resolve the acquisition cadence that applied at a Timeline timestamp."""
    interval = _sample_interval_seconds(fallback_interval_s)
    try:
        sample_epoch = float(epoch_s)
    except (TypeError, ValueError):
        return interval
    for raw in segments if isinstance(segments, list) else []:
        if not isinstance(raw, dict):
            continue
        try:
            start_epoch = datetime.fromisoformat(
                str(raw.get("start_at_utc"))).timestamp()
        except (TypeError, ValueError):
            continue
        if sample_epoch + 0.001 < start_epoch:
            break
        interval = _sample_interval_seconds(
            raw.get("sample_interval_s"), interval)
    return interval


def _normalise_samples_for_report(
    samples: List[Dict[str, Any]],
    fallback_interval_s: Any,
) -> tuple[List[Dict[str, Any]], float, List[Dict[str, Any]]]:
    """Convert mixed 5/10-second acquisition rows to equal-duration units.

    Raw Timeline rows are never modified.  Report algorithms currently accept
    one cadence, so a 10-second row is represented as two 5-second units when
    the same Session also contains legacy 5-second rows.  This preserves TST,
    WASO, stage proportions and time-weighted Sensor averages across a live
    cadence migration without pretending that every raw row has equal weight.
    """
    if not samples:
        interval = _sample_interval_seconds(fallback_interval_s)
        return [], interval, []
    intervals = [
        _sample_interval_seconds(sample.get("sample_interval_s"), fallback_interval_s)
        for sample in samples
    ]
    # Millisecond GCD keeps common production cadences (5/10/30 s) exact while
    # avoiding floating-point ratio drift.
    base_ms = max(100, int(round(intervals[0] * 1000)))
    for interval in intervals[1:]:
        base_ms = math.gcd(base_ms, max(100, int(round(interval * 1000))))
    report_interval_s = base_ms / 1000.0
    normalised: List[Dict[str, Any]] = []
    summary: Dict[float, Dict[str, Any]] = {}
    for sample, interval in zip(samples, intervals):
        repeats = max(1, int(round(interval / report_interval_s)))
        # Guard corrupt metadata from exploding report memory. Production
        # 5/10-second segments require only one or two units.
        repeats = min(repeats, 120)
        for _ in range(repeats):
            unit = dict(sample)
            unit["sample_interval_s"] = report_interval_s
            normalised.append(unit)
        key = round(interval, 3)
        bucket = summary.setdefault(key, {
            "sample_interval_s": key, "raw_samples": 0, "covered_seconds": 0.0,
        })
        bucket["raw_samples"] += 1
        bucket["covered_seconds"] = round(
            float(bucket["covered_seconds"]) + interval, 3)
    return normalised, report_interval_s, [summary[key] for key in sorted(summary)]
# เริ่มนับ/บันทึกจริงเมื่อผู้ใช้นอนบนเตียงต่อเนื่องครบตามนี้ (ลุกก่อนครบ = รีเซ็ต)
BED_START_SECONDS = float(os.getenv("BED_START_SECONDS", "20"))
# A Session row/timeline must not start from bed status alone. Require fresh,
# sane HR and RR in consecutive *new* BCG packets after Login/restart. Values
# held for display while the module reacquires a signal never pass this gate.
SESSION_VITAL_START_PACKETS = max(
    1, int(os.getenv("SESSION_VITAL_START_PACKETS", "3")))
GENDERS = ("male", "female", "other", "unspecified")
POD_ID = pod_id_from_env()
OCCUPANCY_LEASE_SECONDS = max(15, int(os.getenv("OCCUPANCY_LEASE_SECONDS", "45")))
OCCUPANCY_RENEW_SECONDS = max(5, int(os.getenv("OCCUPANCY_RENEW_SECONDS", "10")))

# Directional starting baselines used only until a personal baseline is
# available. The ranges intentionally overlap; scoring also uses movement,
# variability, time in session and transition context.
AGE_SLEEP_BASELINES = {
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
    # Conservative ZEEP Wellness priors. Literature supports sex-related HRV
    # direction, but not universal stage-specific HR/RR cut-offs.
    "male": {"label": "ชาย", "hr_offset": 0, "rr_offset": 0, "rem_variability_weight": 1.10,
             "note": "REM sympathetic/HR variability weighting สูงขึ้นเล็กน้อย"},
    "female": {"label": "หญิง", "hr_offset": 2, "rr_offset": 0, "rem_variability_weight": 1.00,
               "note": "HR starting range +2 BPM; RR คงเดิม"},
    "other": {"label": "อื่น ๆ", "hr_offset": 0, "rr_offset": 0, "rem_variability_weight": 1.00,
              "note": "ใช้ neutral baseline จนมี Personal Baseline"},
    "unspecified": {"label": "ไม่ระบุ", "hr_offset": 0, "rr_offset": 0, "rem_variability_weight": 1.00,
                    "note": "ใช้ neutral baseline จนมี Personal Baseline"},
}


def _gender_adjusted_baseline(age_group: str, gender: Optional[str]):
    adjustment = GENDER_BASELINE_ADJUSTMENTS.get(gender or "unspecified",
                                                  GENDER_BASELINE_ADJUSTMENTS["unspecified"])
    adjusted = {}
    for stage, ranges in AGE_SLEEP_BASELINES[age_group].items():
        adjusted[stage] = {
            "hr": tuple(x + adjustment["hr_offset"] for x in ranges["hr"]),
            "rr": tuple(x + adjustment["rr_offset"] for x in ranges["rr"]),
        }
    return adjusted, adjustment


def _age_group(age: Optional[int]) -> str:
    if age is None or age < 30:
        return "18-29"
    if age < 45:
        return "30-44"
    if age < 60:
        return "45-59"
    return "60+"

BCG_PORT = os.getenv("BCG_PORT", "/dev/ttyUSB_HRB")
BCG_BAUD = int(os.getenv("BCG_BAUD", "115200"))
ESP32_PORT = os.getenv("ESP32_PORT", "/dev/ttyACM0")
ESP32_BAUD = int(os.getenv("ESP32_BAUD", "115200"))

# Sensor Hub 2 uses the Pi-local MQTT broker.  It stays separate from the
# original USB hub so one transport cannot overwrite or mask the other.
MQTT_HOST = os.getenv("MQTT_HOST", "127.0.0.1")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_KEEPALIVE = int(os.getenv("MQTT_KEEPALIVE", "30"))
SENSORHUB2_TELEMETRY_TOPIC = os.getenv(
    "SENSORHUB2_TELEMETRY_TOPIC", "zeep/pod1/sensorhub2/telemetry")
SENSORHUB2_STATUS_TOPIC = os.getenv(
    "SENSORHUB2_STATUS_TOPIC", "zeep/pod1/sensorhub2/status")
SENSORHUB2_STALE_SECONDS = float(os.getenv("SENSORHUB2_STALE_SECONDS", "15"))

# Control Hub 1 receives plain-text air-conditioner commands and publishes
# retained status plus a non-retained command event after sending IR.
CONTROLHUB1_COMMAND_TOPIC = os.getenv(
    "CONTROLHUB1_COMMAND_TOPIC", "zeep/pod1/controlhub1/command")
CONTROLHUB1_STATUS_TOPIC = os.getenv(
    "CONTROLHUB1_STATUS_TOPIC", "zeep/pod1/controlhub1/status")
CONTROLHUB1_EVENT_TOPIC = os.getenv(
    "CONTROLHUB1_EVENT_TOPIC", "zeep/pod1/controlhub1/event")
CONTROLHUB1_STALE_SECONDS = float(os.getenv("CONTROLHUB1_STALE_SECONDS", "70"))
CONTROLHUB1_ACK_TIMEOUT_SECONDS = float(
    os.getenv("CONTROLHUB1_ACK_TIMEOUT_SECONDS", "3"))
# Air-conditioner IR receivers commonly ignore frames that arrive while the
# previous command is still being processed. Keep every Control Hub 1 command
# in one serialized queue and enforce a guard interval between IR frames.
# Power ON needs a longer settle period before applying the default setpoint.
CONTROLHUB1_MIN_IR_GAP_SECONDS = float(
    os.getenv("CONTROLHUB1_MIN_IR_GAP_SECONDS", "1.2"))
CONTROLHUB1_POWER_ON_SETTLE_SECONDS = float(
    os.getenv("CONTROLHUB1_POWER_ON_SETTLE_SECONDS", "2.0"))
CONTROLHUB1_FAN_WAKE_SETTLE_SECONDS = float(
    os.getenv("CONTROLHUB1_FAN_WAKE_SETTLE_SECONDS", "0.25"))
if CONTROLHUB1_MIN_IR_GAP_SECONDS < 0:
    raise RuntimeError("CONTROLHUB1_MIN_IR_GAP_SECONDS must not be negative")
if CONTROLHUB1_POWER_ON_SETTLE_SECONDS < 0:
    raise RuntimeError("CONTROLHUB1_POWER_ON_SETTLE_SECONDS must not be negative")
if CONTROLHUB1_FAN_WAKE_SETTLE_SECONDS < 0:
    raise RuntimeError("CONTROLHUB1_FAN_WAKE_SETTLE_SECONDS must not be negative")

# Control Hub 2 drives the four servos that press the bed remote.  It uses the
# same Pi-local broker as Control Hub 1, but separate topics and state so an
# air-conditioner command can never be interpreted as a bed command.
CONTROLHUB2_COMMAND_TOPIC = os.getenv(
    "CONTROLHUB2_COMMAND_TOPIC", "zeep/pod1/controlhub2/bed/command")
CONTROLHUB2_STATUS_TOPIC = os.getenv(
    "CONTROLHUB2_STATUS_TOPIC", "zeep/pod1/controlhub2/bed/status")
CONTROLHUB2_EVENT_TOPIC = os.getenv(
    "CONTROLHUB2_EVENT_TOPIC", "zeep/pod1/controlhub2/bed/event")
CONTROLHUB2_STALE_SECONDS = float(os.getenv("CONTROLHUB2_STALE_SECONDS", "70"))
CONTROLHUB2_ACK_TIMEOUT_SECONDS = float(
    os.getenv("CONTROLHUB2_ACK_TIMEOUT_SECONDS", "3"))
# Every user bed movement is a bounded one-shot action. The Pi publishes an
# explicit BED STOP after this window even if a browser disconnects, so a held
# direction cannot continue indefinitely. Safety Supervisor can still stop it
# immediately through the internal bed_stop command.
BED_MOVE_SECONDS = max(0.5, float(os.getenv("BED_MOVE_SECONDS", "2")))

# Requested SPH0645 display transform for the current field trial.
# dBA_est = abs(sound_dbfs) + adjustment, with the adjustment fixed at -2 dB
# in calibration.json. Raw dBFS remains untouched for audit/recalibration.
# This is an estimated display value, not a traceable SPL calibration.
# Priority: SOUND_DBFS_MAGNITUDE_ADJUSTMENT_DB env > calibration.json > -2.0.
CALIBRATION_PATH = BASE_DIR / "calibration.json"


def _load_calibration() -> Dict[str, Any]:
    try:
        with CALIBRATION_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as exc:
        print(f"[CAL] ignoring invalid calibration.json: {exc}")
        return {}


CALIBRATION = _load_calibration()
_ENV_SOUND_ADJUSTMENT = os.getenv("SOUND_DBFS_MAGNITUDE_ADJUSTMENT_DB")
if _ENV_SOUND_ADJUSTMENT is not None:
    SOUND_DBFS_MAGNITUDE_ADJUSTMENT_DB = float(_ENV_SOUND_ADJUSTMENT)
    SOUND_TRANSFORM_SOURCE = "env"
elif "sound_dbfs_magnitude_adjustment_db" in CALIBRATION:
    SOUND_DBFS_MAGNITUDE_ADJUSTMENT_DB = float(
        CALIBRATION["sound_dbfs_magnitude_adjustment_db"]
    )
    SOUND_TRANSFORM_SOURCE = "calibration.json"
else:
    SOUND_DBFS_MAGNITUDE_ADJUSTMENT_DB = -2.0
    SOUND_TRANSFORM_SOURCE = "default"

# SHT3x-DIS currently uses raw pass-through (0.0 percentage-point bias).
# A future validated adjustment may still be supplied through env or
# calibration.json without modifying the raw Hub 1 payload.
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

# Admin calibration is deliberately additive and applied only after a raw
# value has passed the sensor's physical-range validation.  Raw hub payloads
# and byte-exact BCG frames are never rewritten, which keeps every adjustment
# auditable and reversible.  SGP40 VOC Index and LSM-800-T HR/RR stay read-only:
# the former owns an adaptive baseline and the latter feeds sleep physiology,
# so an arbitrary UI offset would invalidate their algorithms.
SENSOR_CALIBRATION_LOCK = threading.RLock()
SENSOR_CALIBRATION_SPECS: Dict[str, Dict[str, Any]] = {
    "temperature_c": {
        "device": "SHT3x-DIS", "device_key": "sht3x_dis",
        "label": "อุณหภูมิ", "unit": "°C", "config_key": "temperature_c_bias",
        "default": 0.0, "bias_min": -20.0, "bias_max": 20.0,
        "value_min": -40.0, "value_max": 125.0, "step": 0.1,
    },
    "humidity_rh": {
        "device": "SHT3x-DIS", "device_key": "sht3x_dis",
        "label": "ความชื้น", "unit": "%RH", "config_key": "humidity_rh_bias",
        "default": 0.0, "bias_min": -20.0, "bias_max": 20.0,
        "value_min": 0.0, "value_max": 100.0, "step": 0.1,
    },
    "lux": {
        "device": "OPT3001", "device_key": "opt3001",
        "label": "ความสว่าง", "unit": "lux", "config_key": "lux_bias",
        "default": 0.0, "bias_min": -5000.0, "bias_max": 5000.0,
        "value_min": 0.0, "value_max": 83865.0, "step": 0.1,
    },
    "sound_dba_est": {
        "device": "SPH0645", "device_key": "sph0645",
        "label": "ระดับเสียงโดยประมาณ", "unit": "dBA est.",
        "config_key": "sound_dbfs_magnitude_adjustment_db",
        "default": -2.0, "bias_min": -30.0, "bias_max": 30.0,
        "value_min": 0.0, "value_max": 120.0, "step": 0.1,
        "raw_field": "sound_dbfs", "bias_label": "ABS(dBFS) ADJUSTMENT",
        "raw_unit": "dBFS",
        "formula": "abs(raw dBFS) + adjustment",
    },
    "co2_ppm": {
        "device": "MH-Z19C", "device_key": "mhz19c",
        "label": "คาร์บอนไดออกไซด์", "unit": "ppm", "config_key": "co2_ppm_bias",
        "default": 0.0, "bias_min": -2000.0, "bias_max": 2000.0,
        "value_min": 400.0, "value_max": 5000.0, "step": 1.0,
    },
    "pm1_0_ug_m3": {
        "device": "PMS7003", "device_key": "pms7003",
        "label": "PM1.0", "unit": "µg/m³", "config_key": "pm1_0_bias",
        "default": 0.0, "bias_min": -500.0, "bias_max": 500.0,
        "value_min": 0.0, "value_max": 1000.0, "step": 0.1,
    },
    "pm2_5_ug_m3": {
        "device": "PMS7003", "device_key": "pms7003",
        "label": "PM2.5", "unit": "µg/m³", "config_key": "pm2_5_bias",
        "default": 0.0, "bias_min": -500.0, "bias_max": 500.0,
        "value_min": 0.0, "value_max": 1000.0, "step": 0.1,
    },
    "pm10_ug_m3": {
        "device": "PMS7003", "device_key": "pms7003",
        "label": "PM10", "unit": "µg/m³", "config_key": "pm10_bias",
        "default": 0.0, "bias_min": -500.0, "bias_max": 500.0,
        "value_min": 0.0, "value_max": 1000.0, "step": 0.1,
    },
}


def _load_sensor_biases() -> tuple[Dict[str, float], Dict[str, str]]:
    biases: Dict[str, float] = {}
    sources: Dict[str, str] = {}
    for metric, spec in SENSOR_CALIBRATION_SPECS.items():
        if metric == "sound_dba_est":
            value = SOUND_DBFS_MAGNITUDE_ADJUSTMENT_DB
            source = SOUND_TRANSFORM_SOURCE
        elif metric == "humidity_rh":
            value, source = HUMIDITY_RH_BIAS, HUMIDITY_BIAS_SOURCE
        elif spec["config_key"] in CALIBRATION:
            value, source = float(CALIBRATION[spec["config_key"]]), "calibration.json"
        else:
            value, source = float(spec["default"]), "default"
        if not math.isfinite(value) or not spec["bias_min"] <= value <= spec["bias_max"]:
            raise RuntimeError(
                f"{spec['config_key']} must be finite and between "
                f"{spec['bias_min']} and {spec['bias_max']}"
            )
        biases[metric] = float(value)
        sources[metric] = source
    return biases, sources


SENSOR_BIASES, SENSOR_BIAS_SOURCES = _load_sensor_biases()


def sensor_bias_value(metric: str) -> float:
    with SENSOR_CALIBRATION_LOCK:
        return float(SENSOR_BIASES.get(metric, 0.0))


def _apply_sensor_bias(metric: str, raw_value: Optional[float]) -> Optional[float]:
    if raw_value is None:
        return None
    spec = SENSOR_CALIBRATION_SPECS.get(metric)
    if spec is None:
        return raw_value
    adjusted = float(raw_value) + sensor_bias_value(metric)
    adjusted = min(float(spec["value_max"]), max(float(spec["value_min"]), adjusted))
    return round(adjusted, 2)


def _persist_calibration(data: Dict[str, Any]) -> None:
    """Atomically replace calibration.json so power loss cannot truncate it."""
    temporary = CALIBRATION_PATH.with_name(f".{CALIBRATION_PATH.name}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, CALIBRATION_PATH)


def update_sensor_bias(metric: str, bias: float, *, operator: str,
                       reference_value: Optional[float] = None) -> Dict[str, Any]:
    """Validate, persist and activate one Admin calibration adjustment."""
    global SOUND_DBFS_MAGNITUDE_ADJUSTMENT_DB, SOUND_TRANSFORM_SOURCE
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
        }
        updated["sensor_bias_metadata"] = metadata
        _persist_calibration(updated)
        CALIBRATION.clear()
        CALIBRATION.update(updated)
        SENSOR_BIASES[metric] = rounded
        SENSOR_BIAS_SOURCES[metric] = "calibration.json"
        if metric == "sound_dba_est":
            SOUND_DBFS_MAGNITUDE_ADJUSTMENT_DB = rounded
            SOUND_TRANSFORM_SOURCE = "calibration.json"
        elif metric == "humidity_rh":
            HUMIDITY_RH_BIAS = rounded
            HUMIDITY_BIAS_SOURCE = "calibration.json"
    with state_lock:
        environment_calibration = state["system"].setdefault(
            "environment_calibration", {})
        environment_calibration["biases"] = dict(SENSOR_BIASES)
        environment_calibration["sources"] = dict(SENSOR_BIAS_SOURCES)
        environment_calibration["humidity_rh_bias"] = HUMIDITY_RH_BIAS
        environment_calibration["humidity_bias_source"] = HUMIDITY_BIAS_SOURCE
        if metric == "sound_dba_est":
            sound_transform = state["system"]["sound_transform"]
            sound_transform["adjustment_db"] = SOUND_DBFS_MAGNITUDE_ADJUSTMENT_DB
            sound_transform["source"] = SOUND_TRANSFORM_SOURCE
    return {
        "metric": metric, "bias": rounded, "source": "calibration.json",
        "updated_at": changed_at, "reference_value": reference,
    }

# User-facing SPL range. Raw dBFS and the unbounded calibrated estimate remain
# available for developer diagnostics, but the dashboard must never show a
# negative estimate or a value above the supported 120 dBA est. display range.
SOUND_DBA_DISPLAY_MIN = 0.0
SOUND_DBA_DISPLAY_MAX = 120.0
# Operational sleep-comfort target used by Monitor recommendations. This is
# separate from the sound transform and the 0–120 dBA est. display envelope.
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
ON_BED_CODES = {0, 2, 3, 5}  # On bed / Moving / Weak breathing / Snoring

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
# 4 dB from pulling an otherwise 45–50 dBA est. window to a false quiet state.
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
    if not isinstance(level, int) or not 1 <= level <= 5:
        raise ValueError("aircon fan level reference must be between 1 and 5")
    payload: Dict[str, Any] = {
        "schema_version": 1,
        "fan_level": level,
        "source": str(source or "unknown"),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if operator:
        payload["operator"] = str(operator)[:120]
    with AIRCON_CONTROL_STATE_LOCK:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = AIRCON_CONTROL_STATE_PATH.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
        tmp.replace(AIRCON_CONTROL_STATE_PATH)
    return payload


def _load_aircon_fan_level_reference() -> Dict[str, Any]:
    """Load the persisted fan-cycle reference or establish Pod default level 1."""
    try:
        with AIRCON_CONTROL_STATE_PATH.open("r", encoding="utf-8") as file:
            saved = json.load(file)
        level = saved.get("fan_level") if isinstance(saved, dict) else None
        if not isinstance(level, int) or not 1 <= level <= 5:
            raise ValueError("fan_level is outside 1..5")
        return {
            "fan_level": level,
            "fan_level_source": saved.get("source") or "persisted_reference",
            "fan_level_updated_at": saved.get("updated_at"),
        }
    except FileNotFoundError:
        source = "pod_default_reference"
        saved = _persist_aircon_fan_level(AIRCON_FAN_LEVEL_DEFAULT, source)
        return {
            "fan_level": AIRCON_FAN_LEVEL_DEFAULT,
            "fan_level_source": source,
            "fan_level_updated_at": saved["updated_at"],
        }
    except Exception as exc:
        # A corrupt reference must not stop the safety service. Replace it with
        # the installation default and leave an explicit diagnostic on stdout.
        print(f"[AIRCON] replacing invalid fan-level reference: {exc}")
        source = "recovered_default_reference"
        saved = _persist_aircon_fan_level(AIRCON_FAN_LEVEL_DEFAULT, source)
        return {
            "fan_level": AIRCON_FAN_LEVEL_DEFAULT,
            "fan_level_source": source,
            "fan_level_updated_at": saved["updated_at"],
        }


_INITIAL_AIRCON_FAN_REFERENCE = _load_aircon_fan_level_reference()


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
        "fan_level": _INITIAL_AIRCON_FAN_REFERENCE["fan_level"],
        "fan_level_source": _INITIAL_AIRCON_FAN_REFERENCE["fan_level_source"],
        "fan_level_updated_at": _INITIAL_AIRCON_FAN_REFERENCE["fan_level_updated_at"],
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
    "music": {"playing": False, "paused": False, "track": None, "volume": 75,
              "loop": False, "mode": "queue", "queue_position": 0,
              "queue_length": 0, "error": None},
    "safety": {
        "armed": SAFETY_ARMED_DEFAULT, "ready": False, "level": "initializing",
        "latched": False, "faults": [], "last_check": None,
        "last_transition": None, "last_action": None,
        "automatic_actions": ["stop_music", "accessories_off", "star_light_off",
                              "red_light_off", "door_drive_off", "led_on"],
        "door_auto_open": False, "ventilation_control_available": False,
        "threshold_basis": {
            "version": SAFETY_THRESHOLD_BASIS_VERSION,
            "approved": SAFETY_THRESHOLD_BASIS_APPROVED,
            "scope": "zeep_internal_operating_policy",
            "document": "docs/zeep-atmosphere-operating-basis-v1.0.md",
        },
        "thresholds": {"esp32_stale_s": ESP32_STALE_SECONDS,
                       "co2_warn_ppm": SAFETY_CO2_WARN_PPM,
                       "co2_fair_max_ppm": SAFETY_CO2_FAIR_MAX_PPM,
                       "co2_critical_ppm": SAFETY_CO2_CRITICAL_PPM,
                       "temperature_warn_min_c": SAFETY_TEMP_WARN_MIN_C,
                       "temperature_warn_max_c": SAFETY_TEMP_WARN_MAX_C,
                       "temperature_critical_min_c": SAFETY_TEMP_CRITICAL_MIN_C,
                       "temperature_critical_max_c": SAFETY_TEMP_CRITICAL_MAX_C,
                       # Legacy response field retained for older clients.
                       "max_temperature_c": SAFETY_MAX_TEMP_C},
    },
    "session": {
        "active": False,
        "username": None,
        "account_key": None,
        "email": None,
        # ชื่อที่โชว์บนหน้าจอ (displayName ของบัญชี ZEEP) เปลี่ยนได้โดยไม่ทำให้
        # Profile/Baseline/History แตกเป็นผู้ใช้คนใหม่ เพราะข้อมูลผูกกับ email.
        "display_name": None,
        "auth_source": None,     # "zeep" = login ด้วยบัญชีจริง · "local" = โหมดออฟไลน์
        "gender": None,
        "age": None,
        "age_group": None,
        # Optional Profile facts used only as wellness-reference context. They
        # are never treated as a diagnosis or a direct Sleep Stage input.
        "health_reference": None,
        "rest_mode": None,
        "session_id": None,
        "started_at": None,
        "samples": 0,
        # Start gate: Login remains active, but no DB Session/timeline exists
        # until both bed duration and fresh HR+RR confirmation pass.
        "recording": False,
        "bed_wait_s": 0,
        "vital_gate": {
            "ready": False,
            "heart_rate_valid": False,
            "respiration_rate_valid": False,
            "confirmed_packets": 0,
            "required_packets": SESSION_VITAL_START_PACKETS,
            "reason": "waiting_for_bcg",
        },
    },
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
            "formula": "abs(sound_dbfs) + adjustment_db",
            "adjustment_db": SOUND_DBFS_MAGNITUDE_ADJUSTMENT_DB,
            "source": SOUND_TRANSFORM_SOURCE,
            "calibrated_at": CALIBRATION.get("calibrated_at"),
            "method": CALIBRATION.get("method"),
            # Calibration provenance is Admin-only because snapshot_for()
            # removes sound_transform from the consumer system payload.
            "status": CALIBRATION.get("status"),
            "operator": CALIBRATION.get("operator"),
            "reference_meter": CALIBRATION.get("reference_meter"),
            "reference_range": CALIBRATION.get("reference_dba_range"),
            "valid_sample_count": CALIBRATION.get("valid_sample_count"),
            "median_error_db": CALIBRATION.get("median_error_db"),
            "fit_r_squared": CALIBRATION.get("fit_r_squared"),
            "photo_audit": CALIBRATION.get("photo_audit"),
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


class GPIOManager:
    """Real GPIO only — นโยบาย: ไม่มี mock ในระบบเด็ดขาด

    ถ้าเชื่อมต่อฮาร์ดแวร์ไม่ได้ ทุกคำสั่งควบคุมต้อง fail พร้อมข้อความชัดเจน
    และ UI ปิดปุ่ม — ห้ามจำลองว่าสั่งสำเร็จ"""

    def __init__(self):
        self.devices: Dict[str, Any] = {}
        self.factory = None
        self.error: Optional[str] = None
        if not GPIO_AVAILABLE:
            self.error = "GPIO เชื่อมต่อไม่ได้ (ไม่พบ gpiozero/lgpio ในเครื่องนี้)"
            print(f"[GPIO] {self.error}")
            return
        attempts = max(1, int(os.getenv("GPIO_INIT_ATTEMPTS", "10")))
        delay = max(0.1, float(os.getenv("GPIO_INIT_RETRY_SECONDS", "0.5")))
        for attempt in range(1, attempts + 1):
            try:
                self.factory = LGPIOFactory(chip=0)
                for name, pin in GPIO_PINS.items():
                    self.devices[name] = OutputDevice(
                        pin,
                        active_high=True,
                        initial_value=False,
                        pin_factory=self.factory,
                    )
                self.error = None
                print(f"[GPIO] connected: chip=0, outputs={len(self.devices)}")
                return
            except Exception as exc:
                self.close()
                self.error = f"GPIO เชื่อมต่อไม่ได้: {exc}"
                if attempt < attempts and "busy" in str(exc).lower():
                    print(f"[GPIO] busy; retry {attempt}/{attempts} in {delay}s")
                    time.sleep(delay)
                    continue
                print(f"[GPIO] {self.error}")
                return

    def close(self):
        for device in self.devices.values():
            try:
                device.close()
            except Exception:
                pass
        self.devices = {}
        if self.factory is not None:
            try:
                self.factory.close()
            except Exception:
                pass
        self.factory = None

    @property
    def ready(self) -> bool:
        return len(self.devices) == len(GPIO_PINS)

    def require_ready(self):
        if not self.ready:
            raise HTTPException(503, self.error or "GPIO เชื่อมต่อไม่ได้")

    def set(self, name: str, on: bool):
        if name not in GPIO_PINS:
            raise KeyError(name)
        if not self.ready:
            raise RuntimeError(self.error or "GPIO เชื่อมต่อไม่ได้")
        device = self.devices[name]
        device.on() if on else device.off()
        with state_lock:
            state["gpio"][name] = bool(on)

    def all_off(self):
        for name in GPIO_PINS:
            try:
                self.set(name, False)
            except Exception:
                pass

    def shutdown(self):
        self.all_off()
        self.close()


gpio = GPIOManager()
with state_lock:
    state["system"]["gpio_available"] = gpio.ready
    state["system"]["gpio_error"] = gpio.error


class AudioPlayer:
    """mpv on the Pi (IPC pause/volume/loop). Fallbacks for bench machines:
    afplay (macOS) or ffplay (Linux/Windows with ffmpeg) — play/stop/loop only,
    no pause, volume applies from the next track."""

    def __init__(self):
        self.proc: Optional[subprocess.Popen] = None
        self.sock_path = os.path.join(tempfile.gettempdir(), "pi5_local_mpv.sock")
        self.lock = threading.Lock()
        self.backend = next(
            (b for b in ("mpv", "afplay", "ffplay") if shutil.which(b)), None
        )
        self.audio_device = os.getenv("MPV_AUDIO_DEVICE", "").strip() or None
        # Raspberry Pi exposes the installed USB adapter through this stable
        # ALSA card-id symlink even if its numeric card index changes.
        if self.backend == "mpv" and not self.audio_device:
            if Path("/proc/asound/Device").exists():
                self.audio_device = "alsa/plughw:CARD=Device,DEV=0"
        self.loop = False
        self.current_path: Optional[Path] = None
        self.queue_paths: List[Path] = []
        self.queue_index = 0
        with state_lock:
            state["system"]["player"] = self.backend
            state["system"]["audio_device"] = self.audio_device

    def _cleanup_socket(self):
        try:
            os.unlink(self.sock_path)
        except FileNotFoundError:
            pass

    def _send(self, command):
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                s.connect(self.sock_path)
                s.sendall((json.dumps({"command": command}) + "\n").encode())
                return True
        except Exception:
            return False

    def _send_commands(self, commands: List[List[Any]]) -> bool:
        """Send ordered MPV IPC commands through one short-lived socket.

        Reusing the active MPV process avoids releasing and reopening the USB
        audio device every time a user changes tracks.  One socket write also
        preserves command order: replace file, update loop mode, then unpause.
        """
        try:
            payload = "".join(
                json.dumps({"command": command}) + "\n" for command in commands
            ).encode()
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                s.connect(self.sock_path)
                s.sendall(payload)
            return True
        except Exception:
            return False

    def _send_retry(self, command, attempts: int = 5, delay: float = 0.2) -> bool:
        for _ in range(attempts):
            if self._send(command):
                return True
            time.sleep(delay)
        return False

    def _spawn(self, file_path: Path, volume: int) -> subprocess.Popen:
        if self.backend == "mpv":
            cmd = [
                "mpv", "--no-config", "--no-video", "--really-quiet",
                f"--volume={volume}",
                f"--loop-file={'inf' if self.loop else 'no'}",
                f"--input-ipc-server={self.sock_path}",
            ]
            if self.audio_device:
                cmd.append(f"--audio-device={self.audio_device}")
            cmd.append(str(file_path))
        elif self.backend == "afplay":
            cmd = ["afplay", "-v", f"{max(0, min(100, volume)) / 100:.2f}",
                   str(file_path)]
        elif self.backend == "ffplay":
            cmd = ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet",
                   "-volume", str(max(0, min(100, volume)))]
            if self.loop:
                cmd += ["-loop", "0"]  # ffplay loops natively
            cmd.append(str(file_path))
        else:
            raise RuntimeError(
                "ไม่พบโปรแกรมเล่นเสียง — Pi/Linux: sudo apt install -y mpv · "
                "macOS: brew install mpv · Windows: ติดตั้ง ffmpeg"
            )
        return subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                stderr=subprocess.PIPE, text=True)

    @staticmethod
    def _process_error(proc: subprocess.Popen) -> str:
        try:
            detail = (proc.stderr.read() if proc.stderr else "").strip()
        except Exception:
            detail = ""
        return detail[-1000:] or f"player exited with code {proc.returncode}"

    def play(self, file_path: Path, loop: bool = False, queue: bool = False):
        with self.lock:
            self.loop = bool(loop)
            if queue and not self.loop:
                extensions = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac"}
                ordered = sorted(
                    path for path in MUSIC_DIR.iterdir()
                    if path.is_file() and path.suffix.lower() in extensions
                )
                queue_paths = (ordered[ordered.index(file_path):]
                               if file_path in ordered else [file_path])
            else:
                queue_paths = [file_path]

            # Track changes use MPV's loadfile command instead of terminating
            # the process. This keeps ALSA open and removes most of the silent
            # gap that previously occurred between selection and playback.
            active_mpv = (
                self.backend == "mpv"
                and self.proc is not None
                and self.proc.poll() is None
            )
            if active_mpv and self._send_commands([
                ["loadfile", str(file_path), "replace"],
                ["set_property", "loop-file", "inf" if self.loop else "no"],
                ["set_property", "pause", False],
            ]):
                self.current_path = file_path
                self.queue_paths = queue_paths
                self.queue_index = 0
                with state_lock:
                    state["music"].update({
                        "playing": True, "paused": False,
                        "track": file_path.name, "loop": self.loop,
                        "mode": "repeat_one" if self.loop else "queue" if queue else "single",
                        "queue_position": 1,
                        "queue_length": len(self.queue_paths), "error": None,
                    })
                return

            self._stop_locked()
            self._cleanup_socket()
            self.loop = bool(loop)
            self.current_path = file_path
            self.queue_paths = queue_paths
            self.queue_index = 0
            with state_lock:
                volume = int(state["music"]["volume"])
            self.proc = self._spawn(file_path, volume)
            proc = self.proc
            # mpv can spawn successfully and immediately exit when the audio
            # output is unavailable. Surface that as an API error, not 200 OK.
            time.sleep(0.2)
            if proc.poll() is not None:
                error = self._process_error(proc)
                self.proc = None
                self.current_path = None
                with state_lock:
                    state["music"].update({"playing": False, "paused": False,
                                           "track": None, "loop": False,
                                           "queue_position": 0, "queue_length": 0,
                                           "error": error})
                raise RuntimeError(error)
            with state_lock:
                state["music"].update({
                    "playing": True, "paused": False,
                    "track": file_path.name, "loop": self.loop,
                    "mode": "repeat_one" if self.loop else "queue" if queue else "single",
                    "queue_position": 1,
                    "queue_length": len(self.queue_paths), "error": None,
                })
        threading.Thread(target=self._watch, args=(proc,), daemon=True).start()

    def _watch(self, proc: subprocess.Popen):
        """Clear playback state when a track ends; afplay loop = respawn."""
        proc.wait()
        error = self._process_error(proc) if proc.returncode else None
        with self.lock:
            if self.proc is not proc:
                return  # superseded by a newer play()/stop()
            if (self.backend == "afplay" and self.loop
                    and self.current_path is not None
                    and proc.returncode == 0):
                with state_lock:
                    volume = int(state["music"]["volume"])
                self.proc = self._spawn(self.current_path, volume)
                threading.Thread(target=self._watch, args=(self.proc,),
                                 daemon=True).start()
                return
            if (not error and not self.loop
                    and self.queue_index + 1 < len(self.queue_paths)):
                # Continue locally even when the tablet/browser is closed. A
                # manual stop supersedes this watcher through self.proc.
                self.queue_index += 1
                self.current_path = self.queue_paths[self.queue_index]
                self._cleanup_socket()
                with state_lock:
                    volume = int(state["music"]["volume"])
                self.proc = self._spawn(self.current_path, volume)
                next_proc = self.proc
                with state_lock:
                    state["music"].update({
                        "playing": True, "paused": False,
                        "track": self.current_path.name, "loop": False,
                        "mode": "queue", "queue_position": self.queue_index + 1,
                        "queue_length": len(self.queue_paths), "error": None,
                    })
                threading.Thread(target=self._watch, args=(next_proc,),
                                 daemon=True).start()
                return
            self.proc = None
            self._cleanup_socket()
            with state_lock:
                state["music"].update({"playing": False, "paused": False,
                                       "track": None, "loop": False,
                                       "queue_position": 0, "queue_length": 0,
                                       "error": error})
            if error:
                print(f"[MUSIC] player failed: {error}")

    def _stop_locked(self):
        self.loop = False
        self.current_path = None
        self.queue_paths = []
        self.queue_index = 0
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None
        self._cleanup_socket()
        with state_lock:
            state["music"].update({"playing": False, "paused": False,
                                   "track": None, "loop": False,
                                   "queue_position": 0, "queue_length": 0})

    def stop(self):
        with self.lock:
            self._stop_locked()

    def pause_toggle(self) -> bool:
        with self.lock:
            with state_lock:
                if not state["music"]["playing"]:
                    return True
                paused = not bool(state["music"]["paused"])
            if self.backend != "mpv":
                return False  # afplay has no pause control
            if self._send_retry(["set_property", "pause", paused]):
                with state_lock:
                    state["music"]["paused"] = paused
                return True
            return False

    def set_volume(self, volume: int):
        volume = max(0, min(MAX_VOLUME, int(volume)))
        with self.lock:
            if self.backend == "mpv":
                self._send(["set_property", "volume", volume])
            # afplay: volume applies from the next track (no live control)
        with state_lock:
            state["music"]["volume"] = volume


player = AudioPlayer()
music_command_lock = threading.Lock()
# A fresh service start also presents a falling edge to connected legacy
# tablets. Guard that first edge so a stale queue script cannot resurrect the
# track that shutdown just stopped.
music_stop_guard_until = time.monotonic() + MUSIC_STOP_GUARD_SECONDS

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
occupancy_store = OccupancyStore(DATA_DIR, OCCUPANCY_LEASE_SECONDS)
occupancy_client = build_occupancy_client(occupancy_store)
OCCUPANCY_COORDINATOR_TOKEN = os.getenv("OCCUPANCY_COORDINATOR_TOKEN", "").strip()

# Adaptive layer: baseline ส่วนบุคคล (เรียนรู้ 3–7 คืน) + hybrid staging engine
baselines = BaselineStore(database, DATA_DIR)


# ---------- event log (ตรวจสอบย้อนหลังได้ทุกเหตุการณ์สำคัญ) ----------
EVENT_LOG_PATH = Path(os.getenv("EVENT_LOG_PATH", str(BASE_DIR / "logs" / "events.jsonl")))
EVENT_RING_LIMIT = int(os.getenv("EVENT_RING_LIMIT", "200"))
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
        try:
            EVENT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with EVENT_LOG_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as exc:
            print(f"[LOG] write failed: {exc}")
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
    faults = []
    if not SAFETY_THRESHOLD_BASIS_VERSION or not SAFETY_THRESHOLD_BASIS_APPROVED:
        faults.append({
            "code": "safety_threshold_basis_unapproved",
            "severity": "blocking",
            "message": (
                "เกณฑ์ CO₂/อุณหภูมิยังไม่มี versioned approved basis — "
                "ใช้ดู telemetry ได้ แต่ห้าม Arm"
            ),
        })
    if not gpio_ok:
        faults.append({"code": "gpio_unavailable", "severity": "critical",
                       "message": "GPIO ควบคุมอุปกรณ์ไม่ได้"})
    e_last = e.get("last_update")
    e_age = now - e_last if isinstance(e_last, (int, float)) else None
    if e_age is None:
        faults.append({"code": "esp32_no_data",
                       "severity": "critical" if occupied else "blocking",
                       "message": "ยังไม่มีข้อมูลจาก ESP32"})
    elif e_age > ESP32_STALE_SECONDS:
        faults.append({"code": "esp32_stale",
                       "severity": "critical" if occupied else "blocking",
                       "message": f"ESP32 ไม่มีข้อมูลใหม่ {e_age:.1f} วินาที"})
    co2 = environment.get("co2_ppm")
    co2_device = (environment.get("devices") or {}).get("mhz19c") or {}
    if co2_device.get("status") != "live" or not isinstance(co2, (int, float)):
        if SAFETY_REQUIRE_CO2:
            faults.append({"code": "co2_unavailable", "severity": "blocking",
                           "message": ("CO₂ sensor ไม่มีข้อมูลสดที่ valid — ห้าม Arm "
                                       f"({co2_device.get('status', 'offline')})")})
    elif float(co2) >= SAFETY_CO2_CRITICAL_PPM:
        faults.append({"code": "co2_critical", "severity": "critical",
                       "message": (f"CO₂ {float(co2):.0f} ppm · ภาพรวมระดับวิกฤต "
                                   f"(≥{SAFETY_CO2_CRITICAL_PPM:.0f})")})
    elif float(co2) > SAFETY_CO2_WARN_PPM:
        atmosphere_level = (
            "พอใช้" if float(co2) <= SAFETY_CO2_FAIR_MAX_PPM else "แย่"
        )
        faults.append({"code": "co2_warning", "severity": "warning",
                       "message": (f"CO₂ {float(co2):.0f} ppm · ภาพรวมระดับ"
                                   f"{atmosphere_level} ควรเพิ่มการระบายอากาศ")})
    temp = environment.get("temperature_c")
    if (isinstance(temp, (int, float)) and not isinstance(temp, bool)
            and math.isfinite(float(temp))):
        temperature = float(temp)
        if (temperature < SAFETY_TEMP_CRITICAL_MIN_C
                or temperature > SAFETY_TEMP_CRITICAL_MAX_C):
            faults.append({
                "code": "temperature_critical", "severity": "critical",
                "message": (
                    f"อุณหภูมิ {temperature:.1f}°C · ภาพรวมระดับวิกฤต "
                    f"(ต้องอยู่ {SAFETY_TEMP_CRITICAL_MIN_C:g}–"
                    f"{SAFETY_TEMP_CRITICAL_MAX_C:g}°C)"
                ),
            })
        elif (temperature < SAFETY_TEMP_WARN_MIN_C
                or temperature > SAFETY_TEMP_WARN_MAX_C):
            atmosphere_level = (
                "พอใช้"
                if 16 <= temperature <= 29
                else "แย่"
            )
            faults.append({
                "code": "temperature_warning", "severity": "warning",
                "message": (
                    f"อุณหภูมิ {temperature:.1f}°C · ภาพรวมระดับ"
                    f"{atmosphere_level} ควรปรับแอร์"
                ),
            })
    b_last = b.get("last_update")
    if occupied and (not isinstance(b_last, (int, float)) or now - b_last > BCG_STALE_SECONDS):
        faults.append({"code": "bcg_stale", "severity": "warning",
                       "message": "BCG ไม่มีข้อมูลใหม่ (telemetry ไม่ใช่ life-safety)"})
    if not health.get("wifi_connected"):
        faults.append({"code": "network_degraded", "severity": "warning",
                       "message": "Wi‑Fi/Network หลุด — Pi ยังควบคุม local ต่อ"})
    return faults


def apply_safety_profile(trigger: str) -> Dict[str, Any]:
    """Idempotent local safe profile. Door auto-open intentionally excluded."""
    results: Dict[str, Any] = {}
    with _safety_action_lock:
        try:
            player.stop(); results["stop_music"] = True
        except Exception as exc:
            results.update({"stop_music": False, "music_error": str(exc)})
        for name in ("aroma1", "aroma2", "aroma3", "aroma4", "steam", "star_light",
                     "red_light_face", "red_light_body", "red_light_leg",
                     "door_open", "door_close"):
            try:
                gpio.set(name, False); results[name] = False
            except Exception as exc:
                results[f"{name}_error"] = str(exc)
        try:
            gpio.set("led", True); results["led"] = True
        except Exception as exc:
            results["led_error"] = str(exc)
        # Bed movement is remote and must receive an explicit stop when the
        # local supervisor enters its safe profile.
        results["bed_stop"] = controlhub2_bed_mqtt.publish_stop_best_effort()
        action = {"at": time.time(), "trigger": trigger, "results": results}
        with state_lock:
            state["safety"]["latched"] = True
            state["safety"]["last_action"] = action
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
        level = ("emergency" if latched else "not_ready" if not ready
                 else "degraded" if faults else "armed" if armed else "monitor")
        transition = time.time() if level != previous_level else None
        with state_lock:
            state["safety"].update({"ready": ready, "level": level,
                                    "faults": faults, "last_check": time.time()})
            if transition is not None:
                state["safety"]["last_transition"] = transition
        if level != previous_level:
            log_event("safety", "state", level=level, armed=armed,
                      faults=[f["code"] for f in faults])
            previous_level = level
        _systemd_notify(f"WATCHDOG=1\nSTATUS=Safety Supervisor: {level}")
        time.sleep(1)

# ---------- profile & session store (on-device only) ----------
profile_lock = threading.Lock()
sessions_file_lock = threading.Lock()
session_lock = threading.Lock()
active_session_checkpoint_lock = threading.Lock()
ingest_outbox_lock = threading.Lock()
sleep_path_lock = threading.Lock()
analysis_frame_lock = threading.Lock()
# {"record": {...}, "samples": [...], "counters": {...}, "last_sample": float}
_active_session: Optional[Dict[str, Any]] = None
_sleep_stage_path = {
    "session_id": None, "seen": [], "last": None, "stage_since": None,
    "candidate": None, "candidate_ticks": 0, "cycle_has_n1": False,
    "sensor_tick_count": 0, "last_evidence_epoch_s": None,
    "last_evidence_result": None,
}
_analysis_frame: Optional[Dict[str, Any]] = None

ACTIVE_SESSION_CHECKPOINT_VERSION = 1
INGEST_OUTBOX_VERSION = 1
_CHECKPOINT_RECORD_FIELDS = {
    "session_id", "username", "username_key", "display_name", "gender", "age", "age_group",
    "health_reference", "wellness_context",
    "rest_mode", "auth_source", "zeep_public_id", "identity_subject", "pod_id",
    "armed_at_utc", "started_at_utc", "sample_interval_s",
    "sample_cadence_segments",
}


def _active_session_checkpoint_payload(active: Dict[str, Any]) -> Dict[str, Any]:
    """Build the restart checkpoint without persisting ZEEP credentials.

    Browser Login is already durable in ``auth.db``.  This checkpoint stores
    only the minimum link between that browser identity and the physical Pod
    Session, including the pre-recording ``waiting_bed`` phase which has no
    row in ``sessions.db`` yet.  Access/refresh tokens and passwords are never
    copied from ``active['auth']``.
    """
    record = dict(active.get("record") or {})
    safe_record = {
        key: record.get(key)
        for key in _CHECKPOINT_RECORD_FIELDS
        if key in record
    }
    phase = active.get("phase")
    if phase not in {"waiting_bed", "recording"}:
        raise ValueError("active session phase is not restart-safe")
    onbed_since = active.get("onbed_since")
    onbed_elapsed_s = (
        max(0.0, time.monotonic() - float(onbed_since))
        if phase == "waiting_bed" and isinstance(onbed_since, (int, float))
        else 0.0
    )
    return {
        "schema_version": ACTIVE_SESSION_CHECKPOINT_VERSION,
        "saved_at_utc": datetime.now(timezone.utc).isoformat(),
        "phase": phase,
        "owner_auth_session_id": active.get("owner_auth_session_id"),
        "onbed_elapsed_s": round(min(onbed_elapsed_s, BED_START_SECONDS), 3),
        "record": safe_record,
    }


def _save_active_session_checkpoint(active: Dict[str, Any]) -> Dict[str, Any]:
    """Atomically persist the active Login/Session link for service restart."""
    payload = _active_session_checkpoint_payload(active)
    with active_session_checkpoint_lock:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        temporary = ACTIVE_SESSION_CHECKPOINT_PATH.with_suffix(".json.tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, ACTIVE_SESSION_CHECKPOINT_PATH)
    return payload


def _load_active_session_checkpoint() -> Optional[Dict[str, Any]]:
    try:
        with active_session_checkpoint_lock:
            with ACTIVE_SESSION_CHECKPOINT_PATH.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        if not isinstance(payload, dict):
            raise ValueError("checkpoint is not an object")
        if payload.get("schema_version") != ACTIVE_SESSION_CHECKPOINT_VERSION:
            raise ValueError("unsupported checkpoint version")
        if payload.get("phase") not in {"waiting_bed", "recording"}:
            raise ValueError("invalid checkpoint phase")
        record = payload.get("record")
        if not isinstance(record, dict):
            raise ValueError("checkpoint record is missing")
        required = {"session_id", "username", "username_key", "identity_subject", "pod_id"}
        if any(not record.get(key) for key in required):
            raise ValueError("checkpoint identity is incomplete")
        return payload
    except FileNotFoundError:
        return None
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        log_event("session", "restart_checkpoint_invalid", error=str(exc))
        return None


def _clear_active_session_checkpoint() -> None:
    with active_session_checkpoint_lock:
        ACTIVE_SESSION_CHECKPOINT_PATH.unlink(missing_ok=True)

def _reset_sleep_stage_path(session_id: Optional[str]) -> None:
    """Reset the per-session semi-Markov memory; caller holds sleep_path_lock."""
    _sleep_stage_path.update({
        "session_id": session_id, "seen": [], "last": None,
        "stage_since": None, "candidate": None, "candidate_ticks": 0,
        "cycle_has_n1": False, "probability_ema": None,
        "sensor_tick_count": 0, "last_evidence_epoch_s": None,
        "last_evidence_result": None,
    })


def _advance_sleep_evidence_clock(session_id: Optional[str]) -> Dict[str, Any]:
    """Advance one 10-second sensor frame and schedule a 30-second epoch.

    The clock belongs to the active Session rather than wall-clock boundaries,
    so a newly recording user always contributes three complete sensor frames
    before the first physiological evidence summary is produced.
    """
    with sleep_path_lock:
        if _sleep_stage_path.get("session_id") != session_id:
            _reset_sleep_stage_path(session_id)
        _sleep_stage_path["sensor_tick_count"] = int(
            _sleep_stage_path.get("sensor_tick_count") or 0
        ) + 1
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
    elif stage == "n1":
        _sleep_stage_path["cycle_has_n1"] = True
    if _sleep_stage_path["last"] != stage:
        seen.append(stage)
        del seen[:-8]
        _sleep_stage_path["stage_since"] = now
        _sleep_stage_path["candidate"] = None
        _sleep_stage_path["candidate_ticks"] = 0
    _sleep_stage_path["last"] = stage


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
    candidate: str,
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
        persist = bool(
            _active_session
            and _active_session.get("phase") == "recording"
            and _active_session["record"].get("session_id") == session_id
        )
    if not persist:
        return
    database.enqueue("sessions", "event", {
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
    })


def _commit_sleep_stage(stage: str, probabilities: Dict[str, float], reason: str,
                        *, confidence: Optional[str] = None,
                        metrics: Optional[Dict[str, Any]] = None,
                        window_start: Optional[str] = None,
                        window_end: Optional[str] = None,
                        sample_count: Optional[int] = None,
                        confirmation: Optional[Dict[str, Any]] = None) -> list:
    with state_lock:
        session_id = state["session"].get("session_id")
    with sleep_path_lock:
        if _sleep_stage_path["session_id"] != session_id:
            _reset_sleep_stage_path(session_id)
        changed = _sleep_stage_path["last"] != stage
        _apply_stage_to_path(stage)
        seen = list(_sleep_stage_path["seen"])
    # Persist one confirmed-state record per 30-second evidence epoch, even
    # when the label is unchanged. Evidence itself has its own event stream.
    with session_lock:
        persist_decision = bool(
            _active_session
            and _active_session.get("phase") == "recording"
            and _active_session["record"].get("session_id") == session_id
        )
    if persist_decision:
        database.enqueue("sessions", "event", {
            "session_id": session_id, "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": "sleep_stage", "value": {
                "state": stage, "probabilities": probabilities,
                "confidence": confidence, "reason": reason, "progression": seen,
                "metrics": metrics or {}, **_sleep_decision_provenance(),
                "window_start": window_start, "window_end": window_end,
                "sample_count": sample_count,
                "sensor_sample_interval_s": SLEEP_SAMPLE_SECONDS,
                "sample_interval_s": SLEEP_EVIDENCE_EPOCH_SECONDS,
                "confirmation_seconds": SLEEP_CONFIRMATION_SECONDS,
                "confirmation": confirmation or {},
                "decision_kind": "confirmed_state",
                "state_changed": changed,
            },
        })
    return seen


def _transition_allowed(candidate: str, *, strong_wake: bool = False) -> tuple[bool, Optional[str]]:
    """Apply the ZEEP continuity guard to noisy non-EEG state estimates.

    This is an engineering prior, not an AASM scoring rule.  AASM stages are
    scored from EEG/EOG/EMG evidence in each epoch.  ZEEP has contactless BCG,
    so every new sleep cycle is deliberately anchored at WAKE and follows an
    guarded graph. N3→REM and the rarer N1→REM edge are valid only when the
    existing REM physiology gate persists; REM→Wake is also a normal edge.
    Every one of those changes still waits for two evidence epochs. Strong
    physiology-corroborated Wake evidence may open otherwise blocked Wake
    edges, while bed exit and safety use separate fast operational paths.
    """
    with sleep_path_lock:
        previous = _sleep_stage_path["last"]
        cycle_has_n1 = bool(_sleep_stage_path.get("cycle_has_n1"))

    # A fresh session/cycle always publishes WAKE first.
    if previous is None:
        return candidate == "wake", previous
    if candidate == "wake" and strong_wake:
        return True, previous
    # Once awake, N1 is the only entry into the estimated sleep sequence.
    if previous == "wake":
        return candidate in {"wake", "n1"}, previous
    # Defensive guard for restored/legacy paths that may not contain N1.
    if candidate in {"n2", "n3", "rem"} and not cycle_has_n1:
        return False, previous
    return candidate in SLEEP_ALLOWED_TRANSITIONS.get(previous, frozenset({"wake"})), previous


def _transition_fallback_state(blocked: str, previous: Optional[str]) -> str:
    """Return the bridge state when a noisy candidate violates the path.

    A fresh cycle first emits WAKE.  Once WAKE is established, a direct
    N2/N3/REM candidate is bridged through N1 instead of holding WAKE forever.
    This guarantees the visible Wake -> N1 ordering without inventing a later
    deep/REM label.  It remains an engineering continuity policy, not AASM.
    """
    with sleep_path_lock:
        cycle_has_n1 = bool(_sleep_stage_path.get("cycle_has_n1"))
    if previous is None:
        return "wake"
    if previous == "wake" and blocked in {"n2", "n3", "rem"}:
        return "n1"
    if blocked in {"n2", "n3", "rem"} and not cycle_has_n1:
        return "n1"
    if previous == "n1" and blocked == "n3":
        return "n2"
    if previous == "n2" and blocked == "wake":
        return "n1"
    if previous == "n3" and blocked in {"wake", "n1"}:
        return "n2"
    if previous == "rem" and blocked == "n3":
        return "n2"
    if previous in ZEEP_SLEEP_STATES and previous != blocked:
        return previous
    return "wake"


def _stabilize_sleep_stage(candidate: str, *, now: float,
                           strong_wake: bool = False) -> tuple[str, Dict[str, Any]]:
    """Resolve adjacency, minimum dwell and repeated-evidence hysteresis.

    The resolver works in 30-second evidence epochs. It models plausible
    continuity and requires two consecutive epochs before changing a confirmed
    state. Strong Wake opens the transition path but does not bypass the
    60-second confirmation; occupancy and safety remain separate fast paths.
    """
    allowed, previous = _transition_allowed(candidate, strong_wake=strong_wake)
    target = candidate if allowed else _transition_fallback_state(candidate, previous)
    guard: Dict[str, Any] = {
        "raw_candidate": candidate, "bridge_state": target if target != candidate else None,
        "previous_state": previous, "strong_wake_override": strong_wake,
        "policy": ZEEP_SLEEP_TRANSITION_POLICY_VERSION,
    }
    with sleep_path_lock:
        if previous is None:
            if _sleep_stage_path.get("candidate") == target:
                _sleep_stage_path["candidate_ticks"] += 1
            else:
                _sleep_stage_path["candidate"] = target
                _sleep_stage_path["candidate_ticks"] = 1
            ticks = int(_sleep_stage_path["candidate_ticks"])
            required = int(SLEEP_STAGE_CONFIRM_TICKS.get(target, SLEEP_CONFIRM_EPOCHS))
            held = ticks < required
            guard.update({
                "required_ticks": required,
                "candidate_ticks": ticks,
                "candidate_epochs": ticks,
                "required_epochs": required,
                "confirmation_seconds": SLEEP_CONFIRMATION_SECONDS,
                "held": held,
                "confirmation_complete": not held,
                "confirmed_state": None if held else target,
            })
            return target, guard
        if target == previous:
            _sleep_stage_path["candidate"] = None
            _sleep_stage_path["candidate_ticks"] = 0
            guard.update({
                "required_ticks": SLEEP_CONFIRM_EPOCHS,
                "candidate_ticks": SLEEP_CONFIRM_EPOCHS,
                "candidate_epochs": SLEEP_CONFIRM_EPOCHS,
                "required_epochs": SLEEP_CONFIRM_EPOCHS,
                "confirmation_seconds": SLEEP_CONFIRMATION_SECONDS,
                "held": False,
                "confirmation_complete": True,
                "confirmed_state": previous,
            })
            return previous, guard

        stage_since = _sleep_stage_path.get("stage_since")
        dwell_s = max(0.0, now - stage_since) if isinstance(stage_since, (int, float)) else 0.0
        min_dwell_s = SLEEP_STAGE_MIN_DWELL_SECONDS.get(previous, 0.0)
        if _sleep_stage_path.get("candidate") == target:
            _sleep_stage_path["candidate_ticks"] += 1
        else:
            _sleep_stage_path["candidate"] = target
            _sleep_stage_path["candidate_ticks"] = 1
        ticks = int(_sleep_stage_path["candidate_ticks"])
        required = int(SLEEP_STAGE_CONFIRM_TICKS.get(target, 2))
        held = dwell_s < min_dwell_s or ticks < required
        guard.update({
            "required_ticks": required, "candidate_ticks": ticks,
            "candidate_epochs": ticks, "required_epochs": required,
            "confirmation_seconds": SLEEP_CONFIRMATION_SECONDS,
            "dwell_s": round(dwell_s, 1), "minimum_dwell_s": min_dwell_s,
            "held": held, "confirmation_complete": not held,
            "confirmed_state": previous if held else target,
        })
        return (previous if held else target), guard


def _baseline_interval_proximity(value: float, pair) -> tuple[float, Dict[str, float]]:
    """Measure distance from a value to both baseline edges and its midpoint.

    Distance-to-interval alone is zero for every overlapping baseline. The
    midpoint term therefore acts only as a transparent tie-breaker. These
    population/personal ranges are engineering priors, not medical limits.
    """
    lo, hi = sorted((float(pair[0]), float(pair[1])))
    midpoint = (lo + hi) / 2.0
    half_span = max((hi - lo) / 2.0, 0.5)
    outside_distance = max(lo - value, 0.0, value - hi)
    midpoint_distance = abs(value - midpoint)
    normalized_distance = (
        outside_distance / half_span
        + 0.35 * midpoint_distance / half_span
    )
    proximity = math.exp(-1.2 * normalized_distance ** 2)
    return proximity, {
        "min": round(lo, 2), "max": round(hi, 2),
        "midpoint": round(midpoint, 2),
        "distance_to_range": round(outside_distance, 2),
        "distance_to_midpoint": round(midpoint_distance, 2),
        "proximity_percent": round(proximity * 100.0, 1),
    }


def _physiological_baseline_fit(hr_fit: float, rr_fit: float) -> float:
    """Combine HR/RR proximity using the versioned ZEEP scoring weights."""
    return (SLEEP_BASELINE_HR_WEIGHT * hr_fit
            + SLEEP_BASELINE_RR_WEIGHT * rr_fit)


def _rr_n3_conflict_adjustment(rr_stage_fits: Dict[str, float]) -> Dict[str, float]:
    """Resist an N3 label when mean RR fits N2 better than N3.

    Mean respiratory rate alone is not a clinical discriminator between N2
    and N3. This guard therefore only resolves a disagreement inside the ZEEP
    baseline score; it cannot create a stage and does not replace RR
    variability, movement, transition order or future PSG validation.
    """
    conflict = max(0.0, float(rr_stage_fits.get("n2", 0.0))
                   - float(rr_stage_fits.get("n3", 0.0)))
    return {
        "conflict": conflict,
        "n3_penalty": conflict * SLEEP_N3_RR_CONFLICT_PENALTY,
        "n2_support": conflict * SLEEP_N2_RR_CONFLICT_SUPPORT,
    }


def _sleep_environment_context(
    environment: Dict[str, Any], rest_mode: Any = "sleep",
) -> Dict[str, Any]:
    """Build the versioned Mode-aware ZEEP environmental context baseline.

    ``fair`` is the minimum expected operating level.  Poor/Critical require
    correction, Fair is usable/optimisable and Good/Excellent are maintained.
    This layer never changes Wake/N1/N2/N3/REM and never actuates hardware.
    """
    # Feature frames historically use ``sound_dba`` while the canonical live
    # environment contract uses ``sound_dba_est``.
    values = dict(environment)
    if values.get("sound_dba_est") is None:
        values["sound_dba_est"] = values.get("sound_dba")
    assessment = assess_environment_values(values, rest_mode)
    factors: Dict[str, Any] = {}
    deviations = []
    for metric in assessment["evaluations"]:
        if metric["status"] != "live":
            factors[metric["key"]] = {
                "available": False, "value": None, "target": metric["target"],
                "expected_floor": metric["expected_floor"], "deviation": None,
                "level": "unavailable",
            }
            continue
        deviation = round((4 - metric["score"]) / 4.0, 3)
        deviations.append(deviation)
        factors[metric["key"]] = {
            "available": True, "value": round(float(metric["value"]), 2),
            "target": metric["target"],
            "expected_floor": metric["expected_floor"],
            "deviation": deviation, "level": metric["level"]["key"],
            "decision": metric["decision"],
        }
    disruption = round(sum(deviations) / len(deviations), 3) if deviations else None
    available = len(deviations)
    return {
        "version": ENVIRONMENT_CONTEXT_POLICY_VERSION,
        "sleep_baseline_version": ZEEP_SLEEP_BASELINE_VERSION,
        "role": "context_and_confidence_only",
        "mode": assessment["mode"],
        "acceptable_min_level": assessment["acceptable_min_level"],
        "factors": factors,
        "available_factors": available,
        "expected_factors": len(assessment["evaluations"]),
        "coverage_percent": round(available / len(assessment["evaluations"]) * 100, 1),
        "disruption_index": disruption,
        "sleep_support_score": round((1.0 - disruption) * 100) if disruption is not None else None,
        "overall_level": assessment["key"],
        "meets_expected": assessment["meets_expected"],
        "required_count": assessment.get("required_count", 0),
        "optimisation_count": assessment.get("optimisation_count", 0),
        "direct_stage_influence": False,
        # Retain the field for API compatibility with older Admin clients. It
        # is deliberately fixed at zero in v1.5; the scorer no longer accepts
        # an environment-derived stage prior.
        "wake_prior": 0.0,
    }


def _sleep_auxiliary_evidence(
    frames: List[Dict[str, Any]],
    statuses: List[int],
    movement_ratio: float,
    waveform_signal: Dict[str, Any],
) -> Dict[str, Any]:
    """Build auditable SPH0645 + Bed Status corroboration for the BCG model.

    Loud sound alone cannot mean that a sleeper is awake. It supplies a small,
    bounded Wake support only when the same rolling window contains independent
    BCG amplitude change or bed motion. Vendor Weak-breathing/Snoring codes are
    exposed as respiratory context and quality flags, never as sleep stages or
    diagnoses.
    """
    total_frames = max(1, len(frames))
    sound_values = [
        float(frame["sound_leq_dba"])
        for frame in frames
        if isinstance(frame.get("sound_leq_dba"), (int, float))
        and not isinstance(frame.get("sound_leq_dba"), bool)
        and math.isfinite(float(frame["sound_leq_dba"]))
    ]
    sound_coverage = len(sound_values) / total_frames
    high_sound_frames = sum(
        value >= SLEEP_ACOUSTIC_DISTURBANCE_DBA for value in sound_values)
    dynamic_frames = sum(bool(frame.get("sound_large_step")) for frame in frames)
    acoustic_event = bool(
        sound_coverage >= SLEEP_ACOUSTIC_MIN_COVERAGE
        and (high_sound_frames > 0 or dynamic_frames > 0)
    )

    shift_ratio = waveform_signal.get("bcg_amplitude_shift_ratio")
    bcg_shift = bool(
        isinstance(shift_ratio, (int, float))
        and not isinstance(shift_ratio, bool)
        and float(shift_ratio) >= 0.12
    )
    bed_motion = bool(
        movement_ratio >= SLEEP_MOVE_WAKE_RATIO
        or (statuses and statuses[-1] == 2)
    )
    corroborated = bool(acoustic_event and (bcg_shift or bed_motion))
    wake_support = SLEEP_ACOUSTIC_WAKE_SUPPORT_MAX if corroborated else 0.0

    status_sets = [set(frame.get("status_codes_seen") or []) for frame in frames]
    weak_breathing_frames = sum(3 in values for values in status_sets)
    snoring_frames = sum(5 in values for values in status_sets)
    # Raw code 1 remains visible in ``status_codes_seen`` for diagnostics. A
    # debounced exit belongs to the separate occupancy/safety pipeline and must
    # not manufacture a Wake epoch for an empty bed.
    bed_exit_frames = sum(
        bool((frame.get("bed_exit_evidence") or {}).get("confirmed"))
        for frame in frames
    )
    raw_bed_exit_frames = sum(1 in values for values in status_sets)
    moving_frames = sum(2 in values for values in status_sets)

    return {
        "version": "zeep-bcg-audio-bed-evidence-v1.2-bed-exit-event-guarded",
        "role": "bcg_corroboration_and_quality",
        "direct_stage_sources": ["bcg", "bed_motion"],
        "operational_occupancy_sources": ["bed_exit"],
        "acoustic": {
            "source": "SPH0645",
            "available_frames": len(sound_values),
            "total_frames": len(frames),
            "coverage_percent": round(sound_coverage * 100.0, 1),
            "mean_leq_dba": (
                round(sum(sound_values) / len(sound_values), 2)
                if sound_values else None
            ),
            "max_leq_dba": round(max(sound_values), 2) if sound_values else None,
            "high_sound_frames": high_sound_frames,
            "dynamic_frames": dynamic_frames,
            "disturbance_detected": acoustic_event,
            "bcg_or_motion_corroborated": corroborated,
            "standalone_stage_influence": False,
        },
        "bed_status": {
            "source": "LSM-800-T",
            "moving_frames": moving_frames,
            "bed_exit_frames": bed_exit_frames,
            "raw_bed_exit_frames": raw_bed_exit_frames,
            "weak_breathing_frames": weak_breathing_frames,
            "snoring_frames": snoring_frames,
            "weak_breathing_is_diagnostic": False,
            "snoring_is_stage_evidence": False,
        },
        "bcg_corroboration": {
            "amplitude_shift": bcg_shift,
            "bed_motion": bed_motion,
        },
        "corroborated_acoustic_wake_support": round(wake_support, 4),
    }


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
        database.enqueue("sessions", "event", {
            "session_id": session_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": kind,
            "value": value,
        })


class ZeepApiOffline(Exception):
    """เรียก ZEEP API ไม่ถึงเลย (เน็ตหลุด / DNS / timeout).

    แยกจากรหัสผ่านผิดโดยตั้งใจ: กรณีนี้เท่านั้นที่หน้าเว็บจะเสนอโหมด local
    fallback — รหัสผ่านผิดต้องแจ้งผิดตรง ๆ ห้ามข้ามไปเข้าแบบไม่ใช้รหัส.
    """


def _zeep_request(method: str, path: str, *, json_body: Optional[dict] = None,
                  token: Optional[str] = None,
                  api_key: Optional[str] = None,
                  timeout: Optional[float] = None) -> Dict[str, Any]:
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
        response = httpx.request(method, f"{ZEEP_API_BASE_URL}{path}", json=json_body,
                                 headers=headers,
                                 timeout=ZEEP_API_TIMEOUT if timeout is None else timeout)
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


def _zeep_gender(raw: Any) -> str:
    """gender ของโปรไฟล์ ZEEP (male/female/other) ตรงกับ GENDERS ของตู้อยู่แล้ว."""
    gender = str(raw or "").strip().lower()
    return gender if gender in GENDERS else "unspecified"


def _age_from_dob(raw: Any) -> Optional[int]:
    """อายุเต็มปีจาก dateOfBirth (ISO YYYY-MM-DD) ของโปรไฟล์ ZEEP."""
    try:
        dob = date.fromisoformat(str(raw or "").strip()[:10])
    except ValueError:
        return None
    today = date.today()
    age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    return age if 0 < age <= 120 else None


def _profile_value(profile: Dict[str, Any], *keys: str) -> Any:
    """Read one profile field across current and anticipated ZEEP envelopes.

    The production API currently returns ``gender`` and ``dateOfBirth`` at the
    top level.  Height/weight/blood group are deliberately accepted from a few
    conventional aliases so the Pod does not need another data migration when
    those optional fields are added to the account service.
    """
    scopes = [profile]
    for container in ("profile", "healthProfile", "health_profile", "health"):
        nested = profile.get(container)
        if isinstance(nested, dict):
            scopes.append(nested)
    for scope in scopes:
        for key in keys:
            if key in scope and scope[key] not in (None, ""):
                return scope[key]
    return None


def _normalise_date_of_birth(raw: Any) -> Optional[str]:
    """Return an ISO date only when the upstream value is a real calendar date."""
    try:
        return date.fromisoformat(str(raw or "").strip()[:10]).isoformat()
    except ValueError:
        return None


def _normalise_body_measurement(raw: Any, *, measurement: str) -> Optional[float]:
    """Normalise optional health-reference measurements without inventing data."""
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    if measurement == "height_cm":
        # Some profile APIs expose a generic height field in metres.
        if 0.8 <= value <= 2.5:
            value *= 100.0
        return round(value, 1) if 80.0 <= value <= 250.0 else None
    if measurement == "weight_kg":
        return round(value, 1) if 20.0 <= value <= 400.0 else None
    return None


def _normalise_blood_group(raw: Any) -> Optional[str]:
    """Normalise ABO/Rh notation; unknown or unsupported values stay absent."""
    value = str(raw or "").strip().upper().replace(" ", "_").replace("-", "_")
    aliases = {
        "A+": "A+", "A_POSITIVE": "A+", "APOSITIVE": "A+",
        "A_": "A-", "A_NEGATIVE": "A-", "ANEGATIVE": "A-",
        "B+": "B+", "B_POSITIVE": "B+", "BPOSITIVE": "B+",
        "B_": "B-", "B_NEGATIVE": "B-", "BNEGATIVE": "B-",
        "AB+": "AB+", "AB_POSITIVE": "AB+", "ABPOSITIVE": "AB+",
        "AB_": "AB-", "AB_NEGATIVE": "AB-", "ABNEGATIVE": "AB-",
        "O+": "O+", "O_POSITIVE": "O+", "OPOSITIVE": "O+",
        "O_": "O-", "O_NEGATIVE": "O-", "ONEGATIVE": "O-",
    }
    return aliases.get(value)


def _health_reference_from_profile(profile: Dict[str, Any]) -> Dict[str, Any]:
    """Canonical, display-safe user facts for wellness context (not diagnosis)."""
    age = profile.get("age")
    date_of_birth = _normalise_date_of_birth(profile.get("date_of_birth"))
    exact_age_known = bool(date_of_birth) or profile.get("age_is_estimated") is False
    return {
        "schema_version": 1,
        "gender": profile.get("gender") or "unspecified",
        "date_of_birth": date_of_birth,
        "age_years": (
            int(age)
            if isinstance(age, int) and 0 < age <= 120
            and exact_age_known else None
        ),
        "age_group": profile.get("age_group") or (_age_group(age) if age is not None else None),
        "height_cm": _normalise_body_measurement(
            profile.get("height_cm"), measurement="height_cm"),
        "weight_kg": _normalise_body_measurement(
            profile.get("weight_kg"), measurement="weight_kg"),
        "blood_group": _normalise_blood_group(profile.get("blood_group")),
        "source": profile.get("health_reference_source") or (
            "zeep_profile"
            if profile.get("zeep_public_id") or profile.get("zeep_email")
            else "local_profile"
        ),
        "refresh_status": profile.get("health_reference_refresh_status"),
        "updated_at_utc": profile.get("health_reference_updated_at_utc"),
        "intended_use": "health_reference_only",
    }


def _zeep_health_reference(me: Dict[str, Any]) -> Dict[str, Any]:
    """Extract only health-reference fields actually present in the ZEEP profile."""
    dob = _normalise_date_of_birth(
        _profile_value(me, "dateOfBirth", "date_of_birth", "birthDate", "birth_date"))
    gender = _zeep_gender(_profile_value(me, "gender", "sex"))
    return {
        "schema_version": 1,
        "gender": gender,
        "date_of_birth": dob,
        "age_years": _age_from_dob(dob),
        "height_cm": _normalise_body_measurement(
            _profile_value(me, "heightCm", "height_cm", "height"),
            measurement="height_cm",
        ),
        "weight_kg": _normalise_body_measurement(
            _profile_value(me, "weightKg", "weight_kg", "weight"),
            measurement="weight_kg",
        ),
        "blood_group": _normalise_blood_group(
            _profile_value(me, "bloodGroup", "blood_group", "bloodType", "blood_type")),
        "source": "zeep_profile",
    }


def _normalize_username(raw: str) -> str:
    name = " ".join((raw or "").split())[:40]
    if len(name) < 2:
        raise HTTPException(422, "username ต้องยาวอย่างน้อย 2 ตัวอักษร")
    return name


def _normalize_email(raw: str) -> str:
    """Return the canonical case-insensitive ZEEP account email."""
    email = (raw or "").strip().casefold()
    local, separator, domain = email.partition("@")
    if (
        not separator or not local or not domain or "." not in domain
        or any(char.isspace() for char in email) or len(email) > 254
    ):
        raise HTTPException(422, "บัญชี ZEEP ต้องมี Email ที่ถูกต้องสำหรับผูกประวัติ")
    return email


def _normalize_account_key(raw: str) -> str:
    """Normalize email-backed ZEEP keys and legacy/local username keys."""
    value = (raw or "").strip()
    if "@" in value:
        return _normalize_email(value)
    return _normalize_username(value).casefold()


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
        mapping: Dict[str, str] = {}
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
                mapping[old_key] = new_key
                aliases = {
                    str(value).strip().casefold()
                    for value in (profile.get("legacy_account_keys") or []) if value
                }
                aliases.add(old_key)
                profile["legacy_account_keys"] = sorted(aliases)
                changed = True
            for alias in profile.get("legacy_account_keys") or []:
                alias_key = str(alias or "").strip().casefold()
                if alias_key and alias_key != new_key:
                    mapping[alias_key] = new_key

            existing = migrated.get(new_key)
            if existing is None:
                migrated[new_key] = profile
                continue
            # A renamed legacy profile can collide with an already email-keyed
            # profile. Preserve the newest metadata and combine counters.
            old_last = str(existing.get("last_session_utc") or "")
            new_last = str(profile.get("last_session_utc") or "")
            newer, older = (profile, existing) if new_last >= old_last else (existing, profile)
            combined = {**older, **newer}
            combined["sessions"] = int(existing.get("sessions", 0)) + int(
                profile.get("sessions", 0)
            )
            created = [
                value for value in (
                    existing.get("created_at_utc"), profile.get("created_at_utc")
                ) if value
            ]
            if created:
                combined["created_at_utc"] = min(created)
            combined["account_key"] = new_key
            migrated[new_key] = combined
            changed = True
        if changed or migrated != profiles:
            _save_profiles(migrated)
        return mapping


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
    vals = [v for v in values
            if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if not vals:
        return None
    return {
        "avg": round(sum(vals) / len(vals), 2),
        "min": round(min(vals), 2),
        "max": round(max(vals), 2),
        "n": len(vals),
    }


def _sleep_quality_summary(
    duration_s: Any,
    night_summary: Optional[Dict[str, Any]],
    sleep_state_counts: Optional[Dict[str, Any]] = None,
    *,
    completed: bool = True,
    rest_mode: Any = "auto",
    stage_sequence: Optional[List[Any]] = None,
    sensor_samples: Optional[List[Dict[str, Any]]] = None,
    sample_interval_s: Optional[float] = None,
) -> Dict[str, Any]:
    """Compatibility wrapper around the hardware-independent report module."""
    return build_sleep_quality(
        duration_s, night_summary, sleep_state_counts, completed=completed,
        rest_mode=rest_mode, stage_sequence=stage_sequence,
        sensor_samples=sensor_samples,
        sample_interval_s=_sample_interval_seconds(
            sample_interval_s, SESSION_SAMPLE_SECONDS),
    )


def estimate_sleep_state() -> Dict[str, Any]:
    """Five-state wellness estimate with explainable probabilities."""
    now = time.time()
    with history_lock:
        # Rolling context: publish every 10 s; confidence stabilizes at 6 frames.
        frames = list(sleep_feature_history)[-SLEEP_MIN_FRAMES:]
    with state_lock:
        age = state["session"].get("age")
        selected_age_group = state["session"].get("age_group")
        gender = state["session"].get("gender")
        session_started = state["session"].get("started_at")
        active_session_id = state["session"].get("session_id")
        session_active = bool(state["session"].get("active"))
        session_recording = bool(state["session"].get("recording"))
        rest_mode = state["session"].get("rest_mode") or "auto"
    age_group = selected_age_group if selected_age_group in AGE_SLEEP_BASELINES else _age_group(age)
    age_baseline = AGE_SLEEP_BASELINES[age_group]
    baseline, gender_adjustment = _gender_adjusted_baseline(age_group, gender)
    # Adaptive layer: เมื่อผู้ใช้มีคืนที่เรียนรู้ครบ (≥3 คืน) ให้เลื่อนช่วง HR/RR
    # ตามค่าจริงของเขาเอง แทนการใช้ตัวเลขกลางกับทุกคน
    with state_lock:
        _account_key = state["session"].get("account_key")
    personal_meta = {"source": "age_gender_default", "status": "no_session"}
    if _account_key:
        baseline, personal_meta = baselines.personalize_baseline(
            _account_key, baseline)
    personal_thresholds = baselines.thresholds_for(
        _account_key) if _account_key else None
    cv_deep_threshold = float((personal_thresholds or {}).get(
        "cv_deep", SLEEP_HR_CV_DEEP))
    cv_rem_threshold = float((personal_thresholds or {}).get(
        "cv_rem", SLEEP_HR_CV_REM))
    with sleep_path_lock:
        if session_active and _sleep_stage_path.get("session_id") != active_session_id:
            _reset_sleep_stage_path(active_session_id)
        previous_valid_stage = _sleep_stage_path.get("last")
    had_previous_stage = previous_valid_stage in {"wake", "n1", "n2", "n3", "rem"}
    if not had_previous_stage:
        previous_valid_stage = "wake"
    result: Dict[str, Any] = {
        # A Sleep State exists only while an occupied, recording Session has a
        # fresh HR+RR pair. ``no_data``/``off_bed`` are operational statuses,
        # not a sixth Sleep Stage and are never persisted as stage decisions.
        "state": "no_data",
        "version": SLEEP_ESTIMATOR_VERSION,
        "evidence_version": SLEEP_EVIDENCE_VERSION,
        "window_s": SLEEP_WINDOW_SECONDS,
        "frames": len(frames),
        "sample_s": SLEEP_SAMPLE_SECONDS,
        "required_samples": SLEEP_MIN_FRAMES,
        "evidence_epoch_s": SLEEP_EVIDENCE_EPOCH_SECONDS,
        "confirmation_s": SLEEP_CONFIRMATION_SECONDS,
        "evidence_frames_per_epoch": SLEEP_SENSOR_FRAMES_PER_EPOCH,
        "coverage_s": round(frames[-1]["t"] - frames[0]["t"], 1) if len(frames) > 1 else 0,
        "age": age,
        "age_group": age_group,
        "gender": gender,
        "age_baseline": age_baseline,
        "gender_adjustment": gender_adjustment,
        "baseline": baseline,
        "personal_baseline": personal_meta,
        "variability_thresholds": {
            "cv_deep": cv_deep_threshold,
            "cv_rem": cv_rem_threshold,
            "source": "personal" if personal_thresholds else "population_default",
        },
        "baseline_definition": {
            "version": ZEEP_SLEEP_BASELINE_VERSION,
            "transition_policy": ZEEP_SLEEP_TRANSITION_POLICY_VERSION,
            "display_ontology": list(ZEEP_SLEEP_STATES),
            "g2_ontology_version": SLEEP_G2_ONTOLOGY_VERSION,
            "g2_ontology": ["W", "N1", "N2", "N3", "REM"],
            "g2_psg_crosswalk": {
                "wake": "W", "n1": "N1", "n2": "N2",
                "n3": "N3", "rem": "REM",
            },
            "primary_inputs": [
                "bed_status", "movement", "heart_rate", "respiration_rate",
                "heart_rate_summary_cv", "respiration_rate_cv",
                "hr_rr_trend", "bcg_respiratory_regularity",
                "bcg_fast_amplitude_stability", "elapsed_time",
                "transition_path", "age_gender_baseline", "personal_baseline",
            ],
            "corroborating_inputs": [
                "sph0645_acoustic_disturbance", "bed_status_weak_breathing",
                "bed_status_snoring",
            ],
            "scoring_weights": {
                "hr_baseline": SLEEP_BASELINE_HR_WEIGHT,
                "rr_baseline": SLEEP_BASELINE_RR_WEIGHT,
                "n3_rr_conflict_penalty": SLEEP_N3_RR_CONFLICT_PENALTY,
                "n2_rr_conflict_support": SLEEP_N2_RR_CONFLICT_SUPPORT,
            },
            "context_inputs": [
                "temperature", "humidity", "co2", "light", "sound",
                "pm2_5", "voc_index",
            ],
            "environment_direct_stage_influence": False,
            "acoustic_requires_bcg_or_motion_corroboration": True,
            "intended_use": "exploratory_wellness_telemetry",
            "actuator_trigger": False,
            "aasm_aligned_labels": True,
            "aasm_psg_equivalent": False,
            "validated_ibi_hrv": False,
            "eeg_k_complex_or_spindle": False,
        },
        "classification_source": personal_meta.get("source", "age_gender_default"),
        "probabilities": {k: 0.0 for k in ("wake", "n1", "n2", "n3", "rem")},
        "classification_active": False,
        "confidence": "low",
        "provisional": True,
        "data_status": "warming",
        "reason": "กำลังสะสมข้อมูล HR/RR และการเคลื่อนไหว",
    }
    def suspend_classification(
        reason: str,
        data_status: str,
        *,
        display_state: str = "no_data",
    ) -> Dict[str, Any]:
        """Return an explicit non-classification instead of inventing sleep.

        The last valid stage is retained only as Admin provenance. It is never
        shown as the current result, assigned 100%, or written to the Session
        Sleep State event stream while occupancy/vital evidence is unavailable.
        """
        result.update({
            "state": display_state,
            "probabilities": {
                key: 0.0 for key in ("wake", "n1", "n2", "n3", "rem")
            },
            "classification_active": False,
            "evidence_active": False,
            "confirmed_state": None,
            "confidence": "low",
            "provisional": True,
            "data_status": data_status,
            "reason": reason,
            "last_valid_state": previous_valid_stage if had_previous_stage else None,
            "held_previous_state": False,
        })
        return result

    if not session_active:
        return suspend_classification(
            "ไม่มีผู้ใช้งาน Session · ไม่ประเมิน Sleep State",
            "no_session",
            display_state="off_bed",
        )
    if not session_recording:
        return suspend_classification(
            "รอผู้ใช้งานบนเตียงและ HR/RR สดก่อนเริ่มประเมิน",
            "waiting_for_vitals",
        )
    if not frames:
        return suspend_classification("ยังไม่มีรอบข้อมูล BCG ใหม่", "no_frame")
    latest_bcg_t = max((f.get("bcg_latest_t") or 0 for f in frames), default=0)
    if not latest_bcg_t or now - latest_bcg_t > max(15, SLEEP_SAMPLE_SECONDS * 3):
        return suspend_classification("BCG ขาดข้อมูลใหม่ · ไม่ประเมิน Sleep State", "stale")
    statuses = [
        f.get("confirmed_status", f.get("status"))
        for f in frames
        if f.get("confirmed_status", f.get("status")) is not None
    ]
    if not statuses:
        return suspend_classification(
            "ไม่มี Bed Status ในรอบล่าสุด · ไม่ประเมิน Sleep State",
            "missing_bed_status",
        )
    latest_exit = dict(frames[-1].get("bed_exit_evidence") or {})
    if statuses[-1] == 1 and latest_exit.get("confirmed"):
        # Reset the continuity path for a possible return to bed, but do not
        # label an empty Pod as Wake: Wake is a human state, not occupancy.
        with sleep_path_lock:
            if _sleep_stage_path["session_id"] != active_session_id:
                _reset_sleep_stage_path(active_session_id)
            _apply_stage_to_path("wake", now=now)
            _sleep_stage_path["probability_ema"] = None
        result["bed_exit_evidence"] = latest_exit
        return suspend_classification(
            "Bed Status ยืนยันว่าไม่มีผู้ใช้งานบนเตียง · ไม่ประเมิน Sleep State",
            "empty_bed",
            display_state="off_bed",
        )
    latest_frame = frames[-1]
    latest_hr = filter_vital_values([latest_frame.get("hr")], HR_SANITY_RANGE_BPM)
    latest_rr = filter_vital_values([latest_frame.get("rr")], RR_SANITY_RANGE_PER_MIN)
    if not latest_frame.get("bcg_valid") or not latest_hr or not latest_rr:
        return suspend_classification(
            "รอบปัจจุบันไม่มี HR/RR สดที่ใช้ได้ · ไม่ประเมิน Sleep State",
            "invalid_or_missing_current_vitals",
        )
    movement_window = movement_window_metrics(statuses)
    move_ratio = float(movement_window["movement_ratio"])
    result["movement_ratio"] = round(move_ratio, 3)
    valid_bcg = [f for f in frames if f.get("bcg_valid")]
    raw_hrs = [f.get("hr") for f in valid_bcg]
    raw_rrs = [f.get("rr") for f in valid_bcg]
    hrs = filter_vital_values(raw_hrs, HR_SANITY_RANGE_BPM)
    rrs = filter_vital_values(raw_rrs, RR_SANITY_RANGE_PER_MIN)
    missing_ratio = 1.0 - len(valid_bcg) / len(frames)
    clip_values = [f["clip_ratio"] for f in frames if isinstance(f.get("clip_ratio"), (int, float))]
    result["signal_quality"] = {
        "valid_buckets": len(valid_bcg), "total_buckets": len(frames),
        "valid_percent": round((1 - missing_ratio) * 100, 1),
        "invalid_hr_buckets": len([value for value in raw_hrs if value is not None]) - len(hrs),
        "invalid_rr_buckets": len([value for value in raw_rrs if value is not None]) - len(rrs),
        "average_clip_percent": round(sum(clip_values) / len(clip_values) * 100, 2) if clip_values else None,
    }
    if not hrs or not rrs:
        return suspend_classification(
            "HR/RR อยู่นอกช่วงตรวจสอบหรือไม่มีข้อมูล · ไม่ประเมิน Sleep State",
            "invalid_or_missing_vitals",
        )
    mean_hr = sum(hrs) / len(hrs)
    mean_rr = sum(rrs) / len(rrs)
    summary_signal = summary_features(hrs, rrs, SLEEP_SAMPLE_SECONDS)
    hr_cv = float(summary_signal.get("hr_cv") or 0.0)
    rr_cv = float(summary_signal.get("rr_cv") or 0.0)
    raw_window = [sample for frame in valid_bcg
                  for sample in (frame.get("bcg_samples") or [])]
    waveform_signal = waveform_features(raw_window)
    result["signal_quality"].update({
        "bcg_baseline_drift_ratio": waveform_signal.get("bcg_baseline_drift_ratio"),
        "bcg_baseline_drift_flag": waveform_signal.get("bcg_baseline_drift_flag", False),
    })
    elapsed_min = max(0.0, (now - session_started) / 60) if session_started else 0.0

    def avg_field(name: str):
        values = [f[name] for f in frames if isinstance(f.get(name), (int, float))]
        return round(sum(values) / len(values), 1) if values else None

    environment = {
        "temperature_c": avg_field("temperature"), "humidity_rh": avg_field("humidity"),
        "co2_ppm": avg_field("co2"), "lux": avg_field("lux"),
        "sound_dba": avg_field("sound_dba"), "pm2_5_ug_m3": avg_field("pm2_5"),
        "voc_index": avg_field("voc"),
        "coverage_percent": round(sum(1 for f in frames if f.get("esp_fresh")) / len(frames) * 100, 1),
    }
    latest_sensor_status = next((f.get("sensor_status") for f in reversed(frames)
                                 if isinstance(f.get("sensor_status"), dict)), {})
    environment["unavailable_sensors"] = [k for k, available in latest_sensor_status.items()
                                             if available is False]
    comfort_flags = []
    if environment["temperature_c"] is not None and environment["temperature_c"] > 27:
        comfort_flags.append("อุณหภูมิค่อนข้างสูง")
    if environment["humidity_rh"] is not None and environment["humidity_rh"] > 65:
        comfort_flags.append("ความชื้นค่อนข้างสูง")
    if environment["co2_ppm"] is not None and environment["co2_ppm"] > 1000:
        comfort_flags.append("CO₂ สูง ควรตรวจการระบายอากาศ")
    if environment["pm2_5_ug_m3"] is not None and environment["pm2_5_ug_m3"] > 35:
        comfort_flags.append("PM2.5 ค่อนข้างสูง")
    if environment["lux"] is not None and environment["lux"] > 15:
        comfort_flags.append("ห้องยังมีแสง")
    if environment["sound_dba"] is not None and environment["sound_dba"] > 55:
        comfort_flags.append("เสียงแวดล้อมค่อนข้างดัง")
    environment["comfort_flags"] = comfort_flags
    environment_context = _sleep_environment_context(environment, rest_mode)
    environment["zeep_context"] = environment_context
    result["environment"] = environment
    auxiliary_evidence = _sleep_auxiliary_evidence(
        frames, statuses, move_ratio, waveform_signal)
    result["auxiliary_evidence"] = auxiliary_evidence

    base_scores: Dict[str, float] = {}
    baseline_proximity: Dict[str, Any] = {}
    hr_stage_fits: Dict[str, float] = {}
    rr_stage_fits: Dict[str, float] = {}
    for name in ("wake", "n1", "n2", "n3", "rem"):
        hr_fit, hr_distance = _baseline_interval_proximity(mean_hr, baseline[name]["hr"])
        rr_fit, rr_distance = _baseline_interval_proximity(mean_rr, baseline[name]["rr"])
        physiological_fit = _physiological_baseline_fit(hr_fit, rr_fit)
        base_scores[name] = physiological_fit
        hr_stage_fits[name] = hr_fit
        rr_stage_fits[name] = rr_fit
        baseline_proximity[name] = {
            "hr": hr_distance, "rr": rr_distance,
            "weighted_percent": round(
                physiological_fit
                / (SLEEP_BASELINE_HR_WEIGHT + SLEEP_BASELINE_RR_WEIGHT)
                * 100.0, 1),
        }
    scoring_metrics = {
        "hr_cv": hr_cv,
        "rr_cv": rr_cv,
        "movement_ratio": move_ratio,
        "bed_status": STATUS_TEXT.get(statuses[-1], "Unknown"),
        "max_moving_run_frames": movement_window["max_moving_run_frames"],
        "movement_burst_count": movement_window["movement_burst_count"],
        "corroborated_acoustic_wake_support": auxiliary_evidence[
            "corroborated_acoustic_wake_support"],
        **summary_signal,
        **waveform_signal,
    }
    arousal_proxy = arousal_proxy_evidence(scoring_metrics, SLEEP_MOVE_WAKE_RATIO)
    scores, sleep_evidence = score_sleep_evidence(
        base_scores=base_scores,
        hr_fits=hr_stage_fits,
        rr_fits=rr_stage_fits,
        metrics=scoring_metrics,
        elapsed_min=elapsed_min,
        rem_variability_weight=float(gender_adjustment["rem_variability_weight"]),
        n3_rr_conflict_penalty=SLEEP_N3_RR_CONFLICT_PENALTY,
        n2_rr_conflict_support=SLEEP_N2_RR_CONFLICT_SUPPORT,
        move_wake_ratio=SLEEP_MOVE_WAKE_RATIO,
        move_deep_ratio=SLEEP_MOVE_DEEP_RATIO,
    )
    rr_stage_guard = {
        "conflict": sleep_evidence["n3_rr_conflict"],
        "n3_penalty": sleep_evidence["n3_rr_conflict"] * SLEEP_N3_RR_CONFLICT_PENALTY,
        "n2_support": sleep_evidence["n3_rr_conflict"] * SLEEP_N2_RR_CONFLICT_SUPPORT,
    }

    max_score = max(scores.values())
    weights = {k: math.exp((v - max_score) * 1.8) for k, v in scores.items()}
    total = sum(weights.values())
    raw_probabilities = {k: weights[k] / total for k in weights}
    instant_candidate = max(raw_probabilities, key=raw_probabilities.get)
    with sleep_path_lock:
        smoothed_probabilities = smooth_stage_probabilities(
            _sleep_stage_path.get("probability_ema"),
            raw_probabilities,
            alpha=SLEEP_PROBABILITY_EMA_ALPHA,
        )
        _sleep_stage_path["probability_ema"] = dict(smoothed_probabilities)
        probability_current_stage = _sleep_stage_path.get("last")
    filtered_candidate, probability_transition = stable_probability_candidate(
        smoothed_probabilities,
        probability_current_stage,
        switch_margin=SLEEP_PROBABILITY_SWITCH_MARGIN,
    )
    # A position change or blanket adjustment is sleep-compatible movement.
    # Only the shared, physiology-corroborated movement rule may bypass the
    # normal N2/N3/REM -> N1 -> Wake progression.
    strong_wake = bool(
        instant_candidate == "wake"
        and sleep_evidence["movement"]["strong_wake"]
    )
    raw_candidate = "wake" if strong_wake else filtered_candidate
    selected, transition_meta = _stabilize_sleep_stage(
        raw_candidate, now=now, strong_wake=strong_wake)

    # Evidence probabilities deliberately remain independent from the
    # confirmed state. A pending challenger can therefore be inspected without
    # rewriting the probability distribution to make the held state win.
    probabilities = {k: round(v, 4) for k, v in smoothed_probabilities.items()}
    rounding_delta = round(1.0 - sum(probabilities.values()), 4)
    probabilities[raw_candidate] = round(
        probabilities[raw_candidate] + rounding_delta, 4)
    confirmed_state = transition_meta.get("confirmed_state")
    if confirmed_state not in ZEEP_SLEEP_STATES:
        confirmed_state = None
    confirmed_probabilities = (
        align_probabilities_to_emitted_stage(
            smoothed_probabilities,
            confirmed_state,
            winner_margin=SLEEP_DISPLAY_WINNER_MARGIN,
        )
        if confirmed_state else {key: 0.0 for key in ZEEP_SLEEP_STATES}
    )
    confirmed_probabilities = {
        key: round(value, 4) for key, value in confirmed_probabilities.items()
    }
    previous_state = transition_meta.get("previous_state")
    transition_guard = None
    if transition_meta.get("bridge_state") or transition_meta.get("held"):
        bridge = transition_meta.get("bridge_state")
        pending = transition_meta.get("candidate_ticks", 0)
        required = transition_meta.get("required_ticks", 1)
        transition_guard = (
            f"{raw_candidate.upper()} → {(bridge or selected).upper()} ตามลำดับธรรมชาติ; "
            f"ยืนยัน {pending}/{required} รอบ"
        )
    top = probabilities[raw_candidate]
    confidence = "high" if top >= 0.72 else "medium" if top >= 0.48 else "low"
    if transition_guard:
        # A bridge label preserves continuity but is not direct physiological
        # evidence for that stage, so never present it with high confidence.
        confidence = "low"
    # A result is available from the first bucket, but a full rolling baseline
    # window is required before it can be labelled non-provisional.
    provisional = len(frames) < SLEEP_MIN_FRAMES
    if provisional:
        confidence = "low"
    if (missing_ratio > 0.25 or environment["coverage_percent"] < 50
            or environment_context["coverage_percent"] < 50):
        confidence = "low"
    if clip_values and sum(clip_values) / len(clip_values) >= 0.20:
        confidence = "low"
    if waveform_signal.get("bcg_baseline_drift_flag"):
        confidence = "low"
    if (isinstance(environment_context.get("disruption_index"), (int, float))
            and environment_context["disruption_index"] >= 0.5
            and confidence == "high"):
        # Air/light/comfort can make the physiology less representative of an
        # undisturbed sleep window, but cannot select another stage.
        confidence = "medium"
    reason_bits = [f"HR เฉลี่ย {mean_hr:.1f}", f"RR เฉลี่ย {mean_rr:.1f}", f"movement {move_ratio*100:.0f}%"]
    movement_category = sleep_evidence["movement"]["category"]
    if movement_category == "position_change_or_blanket_adjustment_candidate":
        reason_bits.append("ขยับสั้นขณะอยู่บนเตียง · ไม่ถือเป็น Wake โดยลำพัง")
    elif movement_category == "sustained_on_bed_motion":
        reason_bits.append("ขยับต่อเนื่องบนเตียง · ลดความมั่นใจแต่ยังไม่ยืนยัน Wake")
    elif movement_category == "wake_compatible_motion":
        reason_bits.append("การขยับต่อเนื่องสอดคล้องกับ HR/RR และ BCG")
    if rr_stage_guard["conflict"] >= 0.05:
        reason_bits.append(
            f"RR ใกล้ N2 มากกว่า N3 {rr_stage_guard['conflict']*100:.0f}%")
    if transition_guard:
        reason_bits.append(transition_guard)
    if environment_context["sleep_support_score"] is not None:
        reason_bits.append(
            f"environment context {environment_context['sleep_support_score']}/100")
    if auxiliary_evidence["acoustic"]["bcg_or_motion_corroborated"]:
        reason_bits.append("เสียงรบกวนสอดคล้องกับ BCG/การเคลื่อนไหว")
    if auxiliary_evidence["bed_status"]["weak_breathing_frames"]:
        reason_bits.append("Bed Status พบ weak-breathing context")
    if auxiliary_evidence["bed_status"]["snoring_frames"]:
        reason_bits.append("Bed Status พบ snoring context")
    if raw_candidate == "wake": reason_bits.append("หลักฐานใกล้ Awake baseline เด่นที่สุด")
    elif raw_candidate == "n1": reason_bits.append("หลักฐานกำลังลดจาก Awake baseline และอยู่ในช่วงเปลี่ยนผ่าน")
    elif raw_candidate == "n2": reason_bits.append("หลักฐาน HR/RR และ BCG คงที่ต่อเนื่อง")
    elif raw_candidate == "n3": reason_bits.append("หลักฐาน HR/RR ต่ำ การหายใจสม่ำเสมอ และ N3 gate ผ่าน")
    else: reason_bits.append("RR แปรปรวนบนเตียงที่นิ่งและ REM gate ผ่าน")
    if environment["lux"] is not None:
        reason_bits.append(f"แสงเฉลี่ย {environment['lux']:.0f} lux")
    if environment["sound_dba"] is not None:
        reason_bits.append(f"เสียงเฉลี่ย {environment['sound_dba']:.1f} dBA est.")
    result.update({
        "state": confirmed_state or "no_data",
        "confirmed_state": confirmed_state,
        "probabilities": probabilities,
        "evidence_probabilities": probabilities,
        "confirmed_probabilities": confirmed_probabilities,
        "confidence": confidence,
        "classification_active": confirmed_state is not None,
        "evidence_active": True,
        "raw_probabilities": {k: round(v, 4) for k, v in raw_probabilities.items()},
        "smoothed_probabilities": {
            k: round(v, 4) for k, v in smoothed_probabilities.items()
        },
        "instant_candidate": instant_candidate,
        "raw_candidate": raw_candidate,
        "probability_winner": raw_candidate,
        "winner_percent": round(probabilities[raw_candidate] * 100, 1),
        "provisional": provisional or confirmed_state is None,
        "data_status": "live" if confirmed_state else "confirming_state",
        "reason": " · ".join(reason_bits), "mean_hr": round(mean_hr, 1), "mean_rr": round(mean_rr, 1),
        "hr_cv": round(hr_cv, 4), "rr_cv": round(rr_cv, 4), "elapsed_min": round(elapsed_min, 1),
        "baseline_proximity": baseline_proximity,
        "scoring_weights": {
            "hr_baseline": SLEEP_BASELINE_HR_WEIGHT,
            "rr_baseline": SLEEP_BASELINE_RR_WEIGHT,
        },
        "probability_filter": {
            "method": "ema_after_60s_rolling_features",
            "alpha": SLEEP_PROBABILITY_EMA_ALPHA,
            "candidate_switch_margin": SLEEP_PROBABILITY_SWITCH_MARGIN,
            "display_winner_margin": SLEEP_DISPLAY_WINNER_MARGIN,
            **probability_transition,
        },
        "rr_stage_guard": {k: round(v, 4) for k, v in rr_stage_guard.items()},
        "signal_features": {**summary_signal, **waveform_signal},
        "sleep_evidence": sleep_evidence,
        "timing_priors": {
            "rem_gate": sleep_evidence["rem_gate"],
            "rem_time_support": sleep_evidence["rem_time_support"],
        },
        "evidence": {
            "candidate": raw_candidate,
            "probabilities": probabilities,
            "confidence": confidence,
            "epoch_seconds": SLEEP_EVIDENCE_EPOCH_SECONDS,
            "sensor_frames": SLEEP_SENSOR_FRAMES_PER_EPOCH,
            "window_seconds": SLEEP_WINDOW_SECONDS,
        },
        "confirmation": {
            "confirmed_state": confirmed_state,
            "pending_state": (
                raw_candidate if transition_meta.get("held") else None
            ),
            "candidate_epochs": transition_meta.get("candidate_epochs", 0),
            "required_epochs": transition_meta.get(
                "required_epochs", SLEEP_CONFIRM_EPOCHS),
            "required_seconds": SLEEP_CONFIRMATION_SECONDS,
            "complete": bool(transition_meta.get("confirmation_complete")),
        },
    })
    result["transition_guard"] = transition_guard
    result["transition_policy"] = transition_meta
    result["previous_state"] = previous_state
    decision_metrics = {"mean_hr": round(mean_hr, 1), "mean_rr": round(mean_rr, 1),
                 "hr_cv": round(hr_cv, 4), "rr_cv": round(rr_cv, 4),
                 "movement_ratio": round(move_ratio, 3),
                 "max_moving_run_frames": movement_window["max_moving_run_frames"],
                 "movement_burst_count": movement_window["movement_burst_count"],
                 "rr_n2_fit": round(rr_stage_fits["n2"], 4),
                 "rr_n3_fit": round(rr_stage_fits["n3"], 4),
                 "rr_n3_conflict": round(rr_stage_guard["conflict"], 4),
                 "rr_n3_penalty": round(rr_stage_guard["n3_penalty"], 4),
                 **summary_signal,
                 **waveform_signal,
                 "arousal_proxy": arousal_proxy,
                 "auxiliary_evidence": auxiliary_evidence,
                 "corroborated_acoustic_wake_support": auxiliary_evidence[
                     "corroborated_acoustic_wake_support"],
                 "sleep_evidence": sleep_evidence,
                 "bed_status": STATUS_TEXT.get(statuses[-1], "Unknown"),
                 "environment_support_score": environment_context["sleep_support_score"],
                 "environment_coverage_percent": environment_context["coverage_percent"]}
    window_start = datetime.fromtimestamp(
        frames[0]["t"] - SLEEP_SAMPLE_SECONDS, timezone.utc).isoformat()
    window_end = datetime.fromtimestamp(frames[-1]["t"], timezone.utc).isoformat()
    result["evidence"]["window_start"] = window_start
    result["evidence"]["window_end"] = window_end
    _persist_sleep_stage_evidence(
        raw_candidate, probabilities, result["reason"], confidence=confidence,
        metrics=decision_metrics,
        window_start=window_start,
        window_end=window_end,
        sample_count=len(frames),
        confirmation=result["confirmation"],
    )
    if confirmed_state:
        result["stage_progression"] = _commit_sleep_stage(
            confirmed_state, confirmed_probabilities, result["reason"],
            confidence=confidence,
            metrics=decision_metrics,
            confirmation=result["confirmation"],
            window_start=window_start,
            window_end=window_end,
            sample_count=len(frames))
    else:
        with sleep_path_lock:
            result["stage_progression"] = list(_sleep_stage_path["seen"])
    return result


# Cache: the sampler publishes exactly one canonical analysis frame per
# 10-second bucket. WebSocket/REST can still carry live control/safety feedback
# more frequently without reclassifying physiology between sensor rounds.
_sleep_cache = {"t": 0.0, "value": None, "session_id": None, "sequence": None}
_health_cache = {"t": 0.0, "value": {}}


def _reset_live_sleep_inference(session_id: Optional[str]) -> None:
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
    _sleep_cache.update({"t": 0.0, "value": None, "session_id": session_id, "sequence": None})


def analysis_frame_cached() -> Optional[Dict[str, Any]]:
    with analysis_frame_lock:
        return (json.loads(json.dumps(_analysis_frame))
                if _analysis_frame is not None else None)


def sleep_state_cached() -> Dict[str, Any]:
    now = time.monotonic()
    with state_lock:
        session_id = state["session"].get("session_id")
    frame = analysis_frame_cached()
    if frame is not None and frame.get("session_id") == session_id:
        value = dict(frame["sleep"])
        age_s = max(0.0, time.time() - float(frame["epoch_s"]))
        value["next_update_s"] = max(0, round(SLEEP_SAMPLE_SECONDS - age_s))
        return value
    cached = _sleep_cache["value"]
    refresh_s = SLEEP_SAMPLE_SECONDS
    if cached is None or session_id != _sleep_cache["session_id"]:
        # REST/WebSocket reads must never manufacture an evidence epoch. Only
        # the sensor sampler may advance the 10s -> 30s -> 60s pipeline.
        _sleep_cache["value"] = {
            "state": "no_data",
            "confirmed_state": None,
            "version": SLEEP_ESTIMATOR_VERSION,
            "evidence_version": SLEEP_EVIDENCE_VERSION,
            "classification_active": False,
            "evidence_active": False,
            "probabilities": {key: 0.0 for key in ZEEP_SLEEP_STATES},
            "confidence": "low",
            "data_status": "waiting_for_sensor_frame",
            "reason": "รอ Sensor frame 10 วินาที",
            "sample_s": SLEEP_SAMPLE_SECONDS,
            "evidence_epoch_s": SLEEP_EVIDENCE_EPOCH_SECONDS,
            "confirmation_s": SLEEP_CONFIRMATION_SECONDS,
        }
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
            return subprocess.run(args, capture_output=True, text=True, timeout=1,
                                  check=False).stdout.strip() or None
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
        "load_1m": round(load1, 2), "load_5m": round(load5, 2),
        "load_15m": round(load15, 2),
        "load_percent": round(min(999, load1 / cpu_count * 100), 1),
        "cpu_temp_c": cpu_temp,
        "memory_percent": round((mem_total - mem_available) / mem_total * 100, 1) if mem_total else None,
        "memory_used_mb": round((mem_total - mem_available) / 1024 / 1024) if mem_total else None,
        "memory_total_mb": round(mem_total / 1024 / 1024) if mem_total else None,
        "disk_percent": round(disk.used / disk.total * 100, 1),
        "disk_free_gb": round(disk.free / 1024 / 1024 / 1024, 1),
        "host_uptime_s": host_uptime,
        "wifi_interface": "wlan0", "wifi_ssid": ssid,
        "wifi_dbm": wifi_dbm, "wifi_connected": bool(ssid and wifi_dbm is not None),
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
    # ESP32 readline() timeout returns empty without raising, so a hub that
    # stops sending would otherwise stay "connected" with frozen values.
    esp32 = result["sensor"].get("esp32") or {}
    last = esp32.get("last_update")
    esp32["data_age_s"] = round(max(0.0, now - last), 1) if isinstance(last, (int, float)) else None
    if esp32.get("connected") and (last is None or now - last > ESP32_STALE_SECONDS):
        esp32["connected"] = False
        esp32["stale"] = True
    esp32["fallback_active"] = bool(not esp32.get("connected") and last is not None)
    if esp32["fallback_active"]:
        esp32["fallback_reason"] = "stale" if esp32.get("stale") else "serial_disconnected"
    hub2 = result["sensor"].get("sensorhub2") or {}
    hub2_last = hub2.get("last_update")
    hub2["data_age_s"] = round(max(0.0, now - hub2_last), 1) if isinstance(hub2_last, (int, float)) else None
    if hub2.get("connected") and (
        hub2_last is None or now - hub2_last > SENSORHUB2_STALE_SECONDS
    ):
        hub2["connected"] = False
        hub2["stale"] = True
    hub2["fallback_active"] = bool(not hub2.get("connected") and hub2_last is not None)
    if hub2["fallback_active"]:
        hub2["fallback_reason"] = "stale" if hub2.get("stale") else "mqtt_disconnected"
    aircon = result.get("aircon") or {}
    aircon_last = aircon.get("last_update")
    aircon["data_age_s"] = (
        round(max(0.0, now - aircon_last), 1)
        if isinstance(aircon_last, (int, float)) else None
    )
    if aircon.get("connected") and (
        aircon_last is None or now - aircon_last > CONTROLHUB1_STALE_SECONDS
    ):
        aircon["connected"] = False
        aircon["stale"] = True
    # ESP32 reports the actual temperature sent over IR. Publish the matching
    # user-facing value as a separate field; never relabel the hardware value.
    aircon["temperature_bias_c"] = AIRCON_TEMPERATURE_BIAS_C
    aircon["power_on_default_temperature_c"] = AIRCON_POWER_ON_DEFAULT_TEMP_C
    aircon["desired_temperature_min_c"] = AIRCON_DESIRED_TEMP_MIN_C
    aircon["desired_temperature_max_c"] = AIRCON_DESIRED_TEMP_MAX_C
    commanded_temperature = aircon.get("temperature_c")
    if isinstance(commanded_temperature, (int, float)) and not isinstance(commanded_temperature, bool):
        desired_temperature = int(commanded_temperature) - AIRCON_TEMPERATURE_BIAS_C
        aircon["desired_temperature_c"] = (
            desired_temperature
            if AIRCON_DESIRED_TEMP_MIN_C <= desired_temperature <= AIRCON_DESIRED_TEMP_MAX_C
            else None
        )
    else:
        aircon["desired_temperature_c"] = None
    result["aircon"] = aircon
    bed_control = result.get("bed_control") or {}
    bed_control_last = bed_control.get("last_update")
    bed_control["data_age_s"] = (
        round(max(0.0, now - bed_control_last), 1)
        if isinstance(bed_control_last, (int, float)) else None
    )
    if bed_control.get("connected") and (
        bed_control_last is None
        or now - bed_control_last > CONTROLHUB2_STALE_SECONDS
    ):
        bed_control["connected"] = False
        bed_control["stale"] = True
    result["bed_control"] = bed_control
    live_environment = build_environment_snapshot(esp32, hub2, now)
    analysis_frame = analysis_frame_cached()
    frame_available = bool(analysis_frame)
    frame_age_s = (
        max(0.0, now - float(analysis_frame.get("epoch_s") or 0))
        if analysis_frame else None
    )
    frame_fresh = bool(
        analysis_frame
        and frame_age_s is not None
        and frame_age_s <= max(15.0, SLEEP_SAMPLE_SECONDS * 3)
    )
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
            "temperature_c", "humidity_rh", "lux", "sound_dba_est",
            "co2_ppm", "pm1_0_ug_m3", "pm2_5_ug_m3", "pm10_ug_m3",
            "voc_index", "sgp40_raw",
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
    # BCG freshness is decided here (display level), not in the reader —
    # the serial line being quiet between frames is normal device behaviour.
    bcg = result["sensor"].get("bcg") or {}
    bcg_last = bcg.get("last_update")
    bcg["data_age_s"] = round(max(0.0, now - bcg_last), 1) if isinstance(bcg_last, (int, float)) else None
    if bcg.get("connected") and (bcg_last is None or now - bcg_last > BCG_STALE_SECONDS):
        bcg["connected"] = False
        bcg["stale"] = True
    bcg["fallback_active"] = bool(not bcg.get("connected") and bcg_last is not None)
    if bcg["fallback_active"]:
        bcg["fallback_reason"] = "stale" if bcg.get("stale") else "serial_disconnected"
    if frame_available:
        for key, value in analysis_frame["bcg"].items():
            bcg[key] = value
        if not frame_fresh:
            bcg["analysis_valid"] = False
            bcg["analysis_stale"] = True
            bcg["fallback_active"] = True
            bcg["fallback_reason"] = "sensor_frame_stale"
        frame_metadata = {
            key: analysis_frame[key]
            for key in ("sequence", "timestamp", "epoch_s", "refresh_s", "source")
        }
        frame_metadata.update({
            "data_age_s": round(frame_age_s, 1),
            "stale": not frame_fresh,
        })
    else:
        for key in (
            "status_code", "status_text", "raw_status_code", "raw_status_text",
            "heart_rate_bpm", "respiration_rate", "analysis_epoch_s",
        ):
            bcg[key] = None
        bcg["analysis_valid"] = False
        frame_metadata = {
            "sequence": None, "timestamp": None, "epoch_s": None,
            "refresh_s": SLEEP_SAMPLE_SECONDS, "source": "waiting_sensor_tick",
            "data_age_s": None, "stale": False,
        }
    frame_metadata["contains"] = [
        "environment", "heart_rate", "respiration_rate", "bed_status",
    ]
    # ``analysis_frame`` remains as a compatibility alias for existing clients.
    # New clients should use ``sensor_frame``: only Sleep Evidence/State has a
    # longer 30/60-second computation cadence.
    result["sensor_frame"] = dict(frame_metadata)
    result["analysis_frame"] = dict(frame_metadata)
    # Internal telemetry (pre-G2): displayed on this lab dashboard only,
    # logged with its version — never a control input.
    result["sleep"] = (dict(analysis_frame["sleep"])
                       if frame_fresh else sleep_state_cached())
    # Smart Response remains observation-only. It consumes the same canonical
    # canonical environmental frame shown by every page, never sleep stage.
    result["smart_response"] = build_smart_response(result, now)
    with event_log_lock:
        result["events_tail"] = list(_event_ring)[-8:]
    return result


def snapshot_for(principal: Principal) -> Dict[str, Any]:
    """Return the minimum telemetry required by the principal's interface."""
    result = snapshot()
    if principal.is_admin:
        result["auth"] = {"principal": principal.public_dict(), "session_store": auth_sessions.health()}
        return result

    # Consumer pages need health values and device state, never infrastructure
    # addresses, GPIO mapping, raw BCG or internal event logs.
    result.pop("events_tail", None)
    system = result.get("system") or {}
    result["system"] = {
        key: system.get(key)
        for key in (
            "uptime_s", "gpio_available", "gpio_error", "max_volume", "player",
            "session_sample_s", "bed_start_s", "pod_id", "occupancy",
        )
    }
    environment = ((result.get("sensor") or {}).get("environment") or {})
    environment.pop("raw_values", None)
    environment.pop("calibration", None)
    bcg = (result.get("sensor") or {}).get("bcg") or {}
    bcg.pop("samples", None)
    bcg.pop("raw_status_code", None)
    bcg.pop("raw_status_text", None)
    bcg.pop("bed_exit_evidence", None)
    result["auth"] = {"principal": principal.public_dict()}
    return result


def _first_numeric(obj: Dict[str, Any], keys):
    for key in keys:
        value = obj.get(key)
        if value is None or isinstance(value, bool):
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _source_freshness(payload: Dict[str, Any], stale_s: float,
                      now: float) -> Dict[str, Any]:
    last = payload.get("last_update")
    age = max(0.0, now - last) if isinstance(last, (int, float)) else None
    live = bool(payload.get("connected") and age is not None and age <= stale_s)
    return {
        "live": live,
        "age_s": round(age, 1) if age is not None else None,
        "has_history": last is not None,
    }


def _sensor_flag(payload: Dict[str, Any], keys) -> Optional[bool]:
    status = payload.get("sensor_status")
    if not isinstance(status, dict):
        return None
    for key in keys:
        if key in status:
            return bool(status[key])
    return None


def _bounded_number(payload: Dict[str, Any], aliases, low: float,
                    high: float) -> tuple[Optional[float], Optional[float]]:
    value = _first_numeric(payload, aliases)
    if value is None or not math.isfinite(value):
        return None, value
    if value < low or value > high:
        return None, value
    return value, None


def build_environment_snapshot(esp32: Dict[str, Any], hub2: Dict[str, Any],
                               now: Optional[float] = None) -> Dict[str, Any]:
    """Create one validated view from both environment hubs.

    Raw hub payloads remain available for diagnostics.  This view is the only
    source used by the dashboard, session sampling and the safety supervisor,
    preventing a live Hub 2 CO2 value from being hidden by an empty Hub 1 field.
    """
    now = time.time() if now is None else now
    sources = {
        "hub1": {
            "payload": esp32,
            "label": "Hub 1 · USB",
            **_source_freshness(esp32, ESP32_STALE_SECONDS, now),
        },
        "hub2": {
            "payload": hub2,
            "label": "Hub 2 · MQTT",
            **_source_freshness(hub2, SENSORHUB2_STALE_SECONDS, now),
        },
    }
    # Electrical limits, aliases and physical ranges live in the versioned
    # sensor contract.  Dashboard, Session storage and Safety therefore cannot
    # drift to different definitions of the same device.
    specs = ENVIRONMENT_DEVICE_SPECS
    values: Dict[str, Optional[float]] = {}
    devices: Dict[str, Dict[str, Any]] = {}
    for key, spec in specs.items():
        attempts = []
        for source_id in spec["sources"]:
            source = sources[source_id]
            payload = source["payload"]
            field_values: Dict[str, Optional[float]] = {}
            invalid_values: Dict[str, Any] = {}
            for field, (aliases, low, high) in spec["fields"].items():
                value, invalid = _bounded_number(payload, aliases, low, high)
                field_values[field] = value
                if invalid is not None:
                    invalid_values[field] = invalid
            flag = _sensor_flag(payload, spec["status"])
            valid = all(value is not None for value in field_values.values())
            attempts.append({
                "source": source_id, "source_label": source["label"],
                "live": source["live"], "age_s": source["age_s"],
                "has_history": source["has_history"], "flag": flag,
                "valid": valid, "values": field_values,
                "invalid_values": invalid_values,
            })
        selected = next((a for a in attempts if a["live"] and a["flag"] is not False and a["valid"]), None)
        if selected is None:
            selected = next((a for a in attempts if a["flag"] is not False and a["valid"]), None)
        primary = attempts[0]
        chosen = selected or primary
        warmup = False
        if key == "mhz19c":
            chosen_payload = sources[chosen["source"]]["payload"]
            warmup = bool(chosen_payload.get("co2_warmup"))
            warmup = warmup or bool(
                (chosen_payload.get("warmup") or {}).get("mhz19c")
            )
        if selected and selected["live"]:
            status = "live"
        elif selected:
            status = "stale"
        elif warmup and primary["live"]:
            status = "warming"
        elif primary["live"] and primary["flag"] is False:
            status = "fault"
        elif primary["live"]:
            status = "invalid" if primary["invalid_values"] else "no_data"
        elif primary["has_history"]:
            status = "stale"
        else:
            status = "offline"
        if key == "sph0645" and esp32.get("sound_value_held") and selected:
            status = "held"
        for field in spec["fields"]:
            values[field] = selected["values"].get(field) if selected else None
        devices[key] = {
            "model": spec["model"], "status": status,
            "source": chosen["source"], "source_label": chosen["source_label"],
            "data_age_s": chosen["age_s"],
            "invalid_values": chosen["invalid_values"],
        }
    live_count = sum(1 for device in devices.values() if device["status"] == "live")
    stale_count = sum(1 for device in devices.values() if device["status"] in ("stale", "held"))
    overall = "live" if live_count == len(devices) else "degraded" if live_count or stale_count else "offline"
    # Preserve the selected, range-validated source value before applying any
    # software adjustment. Packet Inspector uses this immutable view to show
    # Raw → Bias → Calibrated without modifying serial/MQTT payloads.
    raw_values = dict(values)
    for metric in SENSOR_CALIBRATION_SPECS:
        # SPH0645 is already converted from dBFS in normalize_esp32_sensor().
        # Applying its offset here again would double-calibrate the microphone.
        if metric == "sound_dba_est":
            continue
        values[metric] = _apply_sensor_bias(metric, values.get(metric))
    return {
        **values,
        "temperature": values.get("temperature_c"),
        "humidity": values.get("humidity_rh"),
        "co2": values.get("co2_ppm"),
        "pm2_5": values.get("pm2_5_ug_m3"),
        "raw_values": raw_values,
        "calibration": {
            metric: {
                "bias": sensor_bias_value(metric),
                "source": SENSOR_BIAS_SOURCES.get(metric, "default"),
            }
            for metric in SENSOR_CALIBRATION_SPECS
        },
        "devices": devices,
        "live_count": live_count,
        "total_count": len(devices),
        "status": overall,
        "sources": {
            key: {k: v for k, v in source.items() if k != "payload"}
            for key, source in sources.items()
        },
    }


SMART_RESPONSE_POLICY_VERSION = "shadow-env-v1.0"


def build_smart_response(snap: Dict[str, Any],
                         now: Optional[float] = None) -> Dict[str, Any]:
    """Evaluate sleep-environment recommendations without actuating anything.

    This is intentionally a separate control path from the BCG sleep-stage
    estimator.  Before G2/PSG validation, stage labels are telemetry only and
    must not trigger the bed, HVAC, lighting, audio, aroma or other outputs.
    """
    now = time.time() if now is None else now
    environment = ((snap.get("sensor") or {}).get("environment") or {})
    devices = environment.get("devices") or {}
    safety = snap.get("safety") or {}
    session = snap.get("session") or {}
    aircon = snap.get("aircon") or {}

    if session.get("active") and session.get("recording"):
        phase = "sleep_session"
        phase_label = "กำลังบันทึกการนอน"
    elif session.get("active"):
        phase = "wind_down"
        phase_label = "เตรียมเข้านอน"
    else:
        phase = "standby"
        phase_label = "Standby"

    recommendations: list[Dict[str, Any]] = []
    blockers: list[Dict[str, str]] = []

    def recommend(domain: str, level: str, title: str, detail: str,
                  suggestion: Optional[str] = None) -> None:
        item: Dict[str, Any] = {
            "domain": domain, "level": level, "title": title,
            "detail": detail,
        }
        if suggestion:
            item["suggestion"] = suggestion
        recommendations.append(item)

    def numeric(name: str) -> Optional[float]:
        value = environment.get(name)
        if (not isinstance(value, (int, float)) or isinstance(value, bool)
                or not math.isfinite(float(value))):
            return None
        return float(value)

    # Blocking conditions are explicit; missing data never becomes zero and
    # never produces an actuator recommendation from a stale last value.
    if not safety.get("ready"):
        blockers.append({"code": "safety_not_ready",
                         "message": "Safety Supervisor ยังไม่ READY"})
    if not safety.get("armed"):
        blockers.append({"code": "safety_not_armed",
                         "message": "ระบบยังไม่ได้ ARM"})
    for key in ("mhz19c", "pms7003", "sgp40"):
        device = devices.get(key) or {}
        if device.get("status") != "live":
            blockers.append({
                "code": f"{key}_not_live",
                "message": f"{device.get('model', key)} ไม่ได้ส่งข้อมูล Live",
            })
    if not aircon.get("connected") or aircon.get("stale"):
        blockers.append({"code": "aircon_offline",
                         "message": "Control Hub 1 ของแอร์ Offline"})

    temperature = numeric("temperature_c")
    if temperature is None:
        recommend("temperature", "blocked", "ไม่มีข้อมูลอุณหภูมิสด",
                  "คงสถานะเดิมและรอ SHT3x-DIS กลับมา")
    elif temperature > TEMPERATURE_EXCELLENT_MAX_C:
        recommend("temperature", "attention", "อุณหภูมิสูงกว่าช่วงเป้าหมาย",
                  f"วัดได้ {temperature:.1f}°C; ตรวจความสบายก่อนลด setpoint แบบทีละ 1°C",
                  "เสนอให้ลด setpoint 1°C (ยังไม่สั่งจริง)")
    elif temperature < TEMPERATURE_EXCELLENT_MIN_C:
        recommend("temperature", "attention", "อุณหภูมิต่ำกว่าช่วงเป้าหมาย",
                  f"วัดได้ {temperature:.1f}°C; ตรวจความสบายก่อนเพิ่ม setpoint แบบทีละ 1°C",
                  "เสนอให้เพิ่ม setpoint 1°C (ยังไม่สั่งจริง)")
    else:
        recommend("temperature", "stable", "อุณหภูมิอยู่ในช่วงยอดเยี่ยม",
                  f"{temperature:.1f}°C · คงค่าปัจจุบันและติดตามแนวโน้ม")

    humidity = numeric("humidity_rh")
    if humidity is None:
        recommend("humidity", "blocked", "ไม่มีข้อมูลความชื้นสด",
                  "คงสถานะเดิมและรอ SHT3x-DIS กลับมา")
    elif humidity > 60.0:
        recommend("humidity", "attention", "ความชื้นเริ่มสูง",
                  f"วัดได้ {humidity:.1f}%RH; ตรวจ condensation และการระบายอากาศ")
    elif humidity < 40.0:
        recommend("humidity", "attention", "ความชื้นค่อนข้างต่ำ",
                  f"วัดได้ {humidity:.1f}%RH; หลีกเลี่ยงการพ่นไอน้ำอัตโนมัติจนผ่าน safety review")
    else:
        recommend("humidity", "stable", "ความชื้นอยู่ในช่วงเฝ้าดู",
                  f"{humidity:.1f}%RH · คงค่าปัจจุบัน")

    co2 = numeric("co2_ppm")
    if co2 is None or (devices.get("mhz19c") or {}).get("status") != "live":
        recommend("air", "blocked", "ยังประเมินอากาศสดไม่ได้",
                  "MH-Z19C Offline — ห้ามสั่ง ventilation อัตโนมัติจากค่าค้าง")
    elif co2 >= SAFETY_CO2_CRITICAL_PPM:
        recommend("air", "critical", "CO₂ ถึงระดับฉุกเฉิน",
                  f"{co2:.0f} ppm · ใช้ Safety SOP และเพิ่มอากาศสดทันทีเมื่อระบบระบายพร้อม")
    elif co2 >= SAFETY_CO2_WARN_PPM:
        recommend("air", "attention", "CO₂ เริ่มสูง",
                  f"{co2:.0f} ppm · เสนอเพิ่มอากาศสดและติดตามค่าเฉลี่ยเคลื่อนที่")
    elif co2 >= 800:
        recommend("air", "watch", "CO₂ กำลังไต่ขึ้น",
                  f"{co2:.0f} ppm · เตรียมเพิ่มอากาศสดก่อนถึง 1,000 ppm")
    else:
        recommend("air", "stable", "CO₂ อยู่ในช่วงเฝ้าดู",
                  f"{co2:.0f} ppm · คง ventilation ปัจจุบัน")

    pm25 = numeric("pm2_5_ug_m3")
    if pm25 is None or (devices.get("pms7003") or {}).get("status") != "live":
        recommend("particles", "blocked", "ยังประเมิน PM2.5 ไม่ได้",
                  "PMS7003 Offline — ไม่อนุมานว่าฝุ่นเป็นศูนย์")
    elif pm25 >= 35:
        recommend("particles", "attention", "PM2.5 สูงกว่าช่วง Pilot",
                  f"{pm25:.1f} µg/m³ · เสนอเพิ่ม HEPA recirculation")
    elif pm25 >= 15:
        recommend("particles", "watch", "PM2.5 ควรติดตาม",
                  f"{pm25:.1f} µg/m³ · ตรวจ filter และแนวโน้มต่อเนื่อง")
    else:
        recommend("particles", "stable", "PM2.5 อยู่ในช่วงเฝ้าดู",
                  f"{pm25:.1f} µg/m³ · คงการกรองปัจจุบัน")

    voc = numeric("voc_index")
    if voc is None or (devices.get("sgp40") or {}).get("status") != "live":
        recommend("voc", "blocked", "ยังประเมิน VOC Index ไม่ได้",
                  "SGP40 Offline — รอ Adaptive Baseline กลับมาทำงาน")
    elif voc >= 200:
        recommend("voc", "attention", "VOC เพิ่มสูงจาก Baseline",
                  f"VOC Index {voc:.0f} · เสนอเพิ่ม carbon filtration/อากาศสด")
    elif voc >= 150:
        recommend("voc", "watch", "VOC สูงกว่าค่ากลางของห้อง",
                  f"VOC Index {voc:.0f} · ติดตามแนวโน้มก่อนสั่งงาน")
    else:
        recommend("voc", "stable", "VOC ใกล้ Adaptive Baseline",
                  f"VOC Index {voc:.0f} · ค่า 100 คือ Baseline ที่ SGP40 เรียนรู้")

    sound = numeric("sound_dba_est")
    if sound is None:
        recommend("sound", "blocked", "ไม่มีข้อมูลเสียงสด",
                  "คงระดับเสียงเดิมและรอ SPH0645 กลับมา")
    elif sound > SOUND_DBA_SLEEP_TARGET:
        recommend("sound", "attention", "เสียงสูงกว่าเป้าหมายกลางคืน",
                  f"ประเมินได้ {sound:.1f} dBA est.; เป้าหมายไม่เกิน {SOUND_DBA_SLEEP_TARGET:.0f} — ตรวจเทียบ LAeq ที่ตำแหน่งหมอนและลดเสียงอย่างนุ่มนวล",
                  "เสนอให้ลดระดับเสียง (ยังไม่สั่งจริง)")
    else:
        recommend("sound", "stable", "ระดับเสียงอยู่ในเป้าหมาย",
                  f"{sound:.1f} dBA est. · เป้าหมาย ≤{SOUND_DBA_SLEEP_TARGET:.0f} · คงระดับปัจจุบัน")

    lux = numeric("lux")
    lux_limit = 1.0 if phase == "sleep_session" else 10.0
    if lux is not None and phase != "standby" and lux > lux_limit:
        recommend("light", "attention", "แสงสูงกว่าช่วงของ Session",
                  f"Photopic {lux:.2f} lux; เสนอหรี่ไฟ แต่ยังยืนยัน mEDI ไม่ได้หากไม่มี spectral sensor")
    elif lux is not None:
        recommend("light", "stable", "แสงอยู่ในช่วงเฝ้าดู",
                  f"Photopic {lux:.2f} lux · ไม่อ้าง mEDI จาก lux เพียงค่าเดียว")

    severe_levels = {"critical", "attention", "blocked"}
    attention_count = sum(1 for item in recommendations
                          if item["level"] in severe_levels)
    status = "blocked" if blockers else "attention" if attention_count else "stable"
    summary = ("ยังไม่พร้อมทดสอบ Auto Response"
               if blockers else "พร้อมเก็บผล Shadow เพื่อทวนกฎควบคุม")
    return {
        "enabled": True,
        "mode": "shadow",
        "status": status,
        "policy_version": SMART_RESPONSE_POLICY_VERSION,
        "cadence_s": 1,
        "evaluated_at": now,
        "phase": phase,
        "phase_label": phase_label,
        "summary": summary,
        "recommendations": recommendations,
        "blockers": blockers,
        "attention_count": attention_count,
        "automatic_actuation": False,
        "sleep_stage_used": False,
        "bed_auto_move": False,
        "guardrails": [
            "Sleep Stage เป็น telemetry เท่านั้นและไม่ใช้สั่งอุปกรณ์",
            "เตียงควบคุมด้วยผู้ใช้และปุ่มหยุดเท่านั้น",
            "ค่าที่ Offline/Stale ไม่ถูกแทนเป็นศูนย์หรือใช้สั่งงาน",
        ],
    }


def sound_energy_average_db(levels: List[float]) -> Optional[float]:
    """Return an energy-domain average for valid 0–120 dBA estimates.

    Arithmetic averaging in decibels is physically incorrect. Subtracting the
    peak before exponentiation keeps the calculation numerically stable while
    preserving the same Leq result.
    """
    valid = [
        float(value) for value in levels
        if isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and SOUND_DBA_DISPLAY_MIN <= float(value) <= SOUND_DBA_DISPLAY_MAX
    ]
    if not valid:
        return None
    peak = max(valid)
    relative_energy = sum(10 ** ((value - peak) / 10.0) for value in valid) / len(valid)
    return round(peak + 10.0 * math.log10(relative_energy), 2)


def sound_window_summary(start_s: float, end_s: float) -> Dict[str, Any]:
    """Summarize SPH0645 samples aligned to one canonical analysis bucket."""
    with sound_history_lock:
        levels = [
            float(row["dba"]) for row in sound_level_history
            if start_s < float(row["t"]) <= end_s
        ]
    leq = sound_energy_average_db(levels)
    if leq is None:
        return {
            "method": "energy_average_leq", "window_s": round(end_s - start_s, 2),
            "sample_count": 0, "status": "no_samples",
        }
    span = max(levels) - min(levels)
    return {
        "method": "energy_average_leq", "window_s": round(end_s - start_s, 2),
        "sample_count": len(levels), "leq_dba": leq,
        "min_dba": round(min(levels), 2), "max_dba": round(max(levels), 2),
        "span_db": round(span, 2),
        # Keep displaying non-negative readings as required, but identify a
        # window whose dynamics are too large to treat as a steady calibration point.
        "large_step_detected": span >= 20.0,
        "status": "dynamic" if span >= 20.0 else "valid",
    }


def normalize_esp32_sensor(obj: Dict[str, Any]) -> Dict[str, Any]:
    """Keep the original ESP32 payload and add normalized dashboard fields."""
    out = dict(obj)
    aliases = {
        "temperature": ("temperature_c", "temperature", "temp", "temp_c"),
        "humidity": ("humidity", "hum", "rh", "humidity_rh"),
        "lux": ("lux", "light", "illuminance"),
        "co2": ("co2", "co2_ppm", "carbon_dioxide"),
        "sound_dbfs": ("sound_dbfs",),
        "sound_rms": ("sound_rms",),
        "sound_peak": ("sound_peak",),
    }
    for target, keys in aliases.items():
        value = _first_numeric(obj, keys)
        if value is not None:
            out[target] = value
    # Preserve raw dBFS and apply the field-requested magnitude transform.
    # Estimates from 0-120 are displayed as dBA est. An estimate below zero
    # is left invalid so hold_last_valid_sound() can keep the prior valid
    # display value; estimates above 120 are capped for the user display.
    sound_dbfs = out.get("sound_dbfs")
    if isinstance(sound_dbfs, (int, float)) and not isinstance(sound_dbfs, bool):
        unbounded = (
            abs(float(sound_dbfs)) + SOUND_DBFS_MAGNITUDE_ADJUSTMENT_DB
        )
        if math.isfinite(unbounded):
            unbounded = round(unbounded, 2)
            out["sound_dba_est_unbounded"] = unbounded
            out["sound_dba_est"] = round(min(SOUND_DBA_DISPLAY_MAX, unbounded), 2)
            out["sound_value_limited"] = unbounded > SOUND_DBA_DISPLAY_MAX
            out["sound_display_adjustment_db"] = (
                SOUND_DBFS_MAGNITUDE_ADJUSTMENT_DB
            )
    return out


def hold_last_valid_sound(current: Dict[str, Any], previous: Dict[str, Any]) -> Dict[str, Any]:
    """Publish only a finite SPH0645 value inside the display range.

    The signed dBFS and unbounded estimate remain available for developer
    diagnostics. A non-finite/missing sample may hold the last valid value;
    ordinary out-of-range values are already bounded by normalization.
    """
    value = current.get("sound_dba_est")
    if (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and SOUND_DBA_DISPLAY_MIN <= float(value) <= SOUND_DBA_DISPLAY_MAX
    ):
        current["sound_value_held"] = False
        return current
    old = previous.get("sound_dba_est")
    if (
        isinstance(old, (int, float))
        and not isinstance(old, bool)
        and math.isfinite(float(old))
        and SOUND_DBA_DISPLAY_MIN <= float(old) <= SOUND_DBA_DISPLAY_MAX
    ):
        current["sound_dba_est"] = old
        current["sound_value_held"] = True
        current["sound_invalid_value"] = value
    else:
        current.pop("sound_dba_est", None)
        current["sound_value_held"] = True
        current["sound_invalid_value"] = value
    return current


def esp32_reader():
    """ESP32 sends one JSON object per line over USB serial."""
    last_error = None
    while True:
        try:
            with serial.Serial(ESP32_PORT, ESP32_BAUD, timeout=1) as ser:
                log_event("esp32", "connected", port=ESP32_PORT, baud=ESP32_BAUD)
                last_error = None
                while True:
                    raw = ser.readline()
                    if not raw:
                        continue
                    try:
                        obj = json.loads(raw.decode("utf-8", errors="ignore").strip())
                        if isinstance(obj, dict):
                            obj = decode_hub_payload(obj, expected_hub="sensorhub1")
                            obj = normalize_esp32_sensor(obj)
                            obj["connected"] = True
                            obj["last_update"] = time.time()
                            with state_lock:
                                obj = hold_last_valid_sound(
                                    obj, state["sensor"].get("esp32", {}) or {})
                                state["sensor"]["esp32"] = obj
                            sound_value = obj.get("sound_dba_est")
                            if (
                                not obj.get("sound_value_held")
                                and isinstance(sound_value, (int, float))
                                and not isinstance(sound_value, bool)
                                and math.isfinite(float(sound_value))
                            ):
                                with sound_history_lock:
                                    sound_level_history.append({
                                        "t": obj["last_update"],
                                        "dba": float(sound_value),
                                        "dbfs": obj.get("sound_dbfs"),
                                    })
                    except json.JSONDecodeError:
                        pass
        except Exception as exc:
            if str(exc) != last_error:  # log แค่ตอนอาการเปลี่ยน ไม่ spam ทุก 2 วิ
                log_event("esp32", "disconnected", error=str(exc))
                last_error = str(exc)
            with state_lock:
                old = dict(state["sensor"].get("esp32", {}))
                old["connected"] = False
                old["error"] = str(exc)
                state["sensor"]["esp32"] = old
            time.sleep(2)


def sensorhub2_mqtt_reader():
    """Subscribe to Hub 2 telemetry without replacing Hub 1 serial data."""
    if not MQTT_AVAILABLE:
        log_event("sensorhub2", "mqtt_library_missing", install="paho-mqtt")
        with state_lock:
            state["sensor"]["sensorhub2"]["error"] = "paho-mqtt is not installed"
        return

    def on_connect(client, _userdata, _flags, reason_code, _properties=None):
        if reason_code == 0:
            client.subscribe([
                (SENSORHUB2_TELEMETRY_TOPIC, 0),
                (SENSORHUB2_STATUS_TOPIC, 0),
            ])
            log_event("sensorhub2", "mqtt_connected", host=MQTT_HOST, port=MQTT_PORT)
        else:
            log_event("sensorhub2", "mqtt_connect_failed", reason=str(reason_code))

    def on_disconnect(_client, _userdata, _disconnect_flags, reason_code,
                      _properties=None):
        with state_lock:
            hub = dict(state["sensor"].get("sensorhub2") or {})
            hub["connected"] = False
            hub["error"] = f"MQTT disconnected: {reason_code}"
            state["sensor"]["sensorhub2"] = hub
        log_event("sensorhub2", "mqtt_disconnected", reason=str(reason_code))

    def on_message(_client, _userdata, message):
        try:
            obj = json.loads(message.payload.decode("utf-8"))
            if not isinstance(obj, dict):
                raise ValueError("payload is not a JSON object")
            now = time.time()
            with state_lock:
                previous = dict(state["sensor"].get("sensorhub2") or {})
                if message.topic == SENSORHUB2_TELEMETRY_TOPIC:
                    obj = decode_hub_payload(obj, expected_hub="sensorhub2")
                    obj["connected"] = True
                    obj["transport"] = "mqtt"
                    obj["topic"] = message.topic
                    obj["last_update"] = now
                    obj["stale"] = False
                    obj.pop("error", None)
                    state["sensor"]["sensorhub2"] = obj
                else:
                    previous["mqtt_status"] = obj
                    previous["status_last_update"] = now
                    if obj.get("online") is False:
                        previous["connected"] = False
                    state["sensor"]["sensorhub2"] = previous
        except Exception as exc:
            log_event("sensorhub2", "invalid_mqtt_payload", topic=message.topic,
                      error=str(exc))

    while True:
        try:
            client = mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION2,
                client_id=f"zeep-pi5-dashboard-{socket.gethostname()}",
            )
            client.on_connect = on_connect
            client.on_disconnect = on_disconnect
            client.on_message = on_message
            client.reconnect_delay_set(min_delay=1, max_delay=30)
            client.connect(MQTT_HOST, MQTT_PORT, MQTT_KEEPALIVE)
            client.loop_forever(retry_first_connection=True)
        except Exception as exc:
            log_event("sensorhub2", "mqtt_error", error=str(exc))
            with state_lock:
                hub = dict(state["sensor"].get("sensorhub2") or {})
                hub["connected"] = False
                hub["error"] = str(exc)
                state["sensor"]["sensorhub2"] = hub
            time.sleep(5)


class ControlHub1MQTT:
    """MQTT command/ack bridge for the ESP32-S3 air-conditioner IR hub.

    This uses a separate client from Sensor Hub 2 so a control regression cannot
    replace or interrupt the proven telemetry reader. Commands are serialized
    because the current ESP32 event schema has no unique command_id.
    """

    def __init__(self):
        self._client = None
        self._client_lock = threading.Lock()
        self._command_lock = threading.Lock()
        self._ack_condition = threading.Condition()
        self._ack_seq = 0
        self._last_ack = None
        # Monotonic time of the latest ESP acknowledgement for a command that
        # emits IR. Access is protected by _command_lock.
        self._last_ir_ack_monotonic = None

    def _set_client(self, client):
        with self._client_lock:
            self._client = client

    def _get_client(self):
        with self._client_lock:
            return self._client

    def _on_connect(self, client, _userdata, _flags, reason_code,
                    _properties=None):
        if reason_code == 0:
            self._set_client(client)
            client.subscribe([
                (CONTROLHUB1_STATUS_TOPIC, 0),
                (CONTROLHUB1_EVENT_TOPIC, 0),
            ])
            with state_lock:
                state["aircon"]["mqtt_connected"] = True
                state["aircon"].pop("mqtt_error", None)
            log_event("controlhub1", "mqtt_connected", host=MQTT_HOST,
                      port=MQTT_PORT)
        else:
            log_event("controlhub1", "mqtt_connect_failed",
                      reason=str(reason_code))

    def _on_disconnect(self, client, _userdata, _disconnect_flags, reason_code,
                       _properties=None):
        with self._client_lock:
            if self._client is client:
                self._client = None
        with state_lock:
            aircon = dict(state.get("aircon") or {})
            aircon["connected"] = False
            aircon["mqtt_connected"] = False
            aircon["error"] = f"MQTT disconnected: {reason_code}"
            aircon["command_pending"] = False
            aircon["pending_command"] = None
            state["aircon"] = aircon
        with self._ack_condition:
            self._ack_condition.notify_all()
        log_event("controlhub1", "mqtt_disconnected", reason=str(reason_code))

    def _on_message(self, _client, _userdata, message):
        try:
            obj = json.loads(message.payload.decode("utf-8"))
            if not isinstance(obj, dict):
                raise ValueError("payload is not a JSON object")
            now = time.time()
            with state_lock:
                aircon = dict(state.get("aircon") or {})
                if message.topic == CONTROLHUB1_STATUS_TOPIC:
                    aircon.update(obj)
                    aircon["connected"] = obj.get("online") is not False
                    aircon["transport"] = "mqtt"
                    aircon["status_last_update"] = now
                else:
                    aircon["connected"] = True
                    aircon["last_event"] = obj
                    aircon["last_command"] = obj.get("command")
                    aircon["last_command_ok"] = bool(obj.get("ok"))
                    aircon["event_last_update"] = now
                    if obj.get("tx_count") is not None:
                        aircon["tx_count"] = obj.get("tx_count")
                aircon["last_update"] = now
                aircon["stale"] = False
                aircon["mqtt_connected"] = True
                aircon.pop("error", None)
                state["aircon"] = aircon

            if message.topic == CONTROLHUB1_EVENT_TOPIC:
                with self._ack_condition:
                    self._ack_seq += 1
                    self._last_ack = (dict(obj), now)
                    self._ack_condition.notify_all()
        except Exception as exc:
            log_event("controlhub1", "invalid_mqtt_payload",
                      topic=message.topic, error=str(exc))

    def run(self):
        if not MQTT_AVAILABLE:
            with state_lock:
                state["aircon"]["error"] = "paho-mqtt is not installed"
            log_event("controlhub1", "mqtt_library_missing",
                      install="paho-mqtt")
            return

        while True:
            try:
                client = mqtt.Client(
                    mqtt.CallbackAPIVersion.VERSION2,
                    client_id=f"zeep-pi5-controlhub1-{socket.gethostname()}",
                )
                client.on_connect = self._on_connect
                client.on_disconnect = self._on_disconnect
                client.on_message = self._on_message
                client.reconnect_delay_set(min_delay=1, max_delay=30)
                client.connect(MQTT_HOST, MQTT_PORT, MQTT_KEEPALIVE)
                client.loop_forever(retry_first_connection=True)
            except Exception as exc:
                self._set_client(None)
                with state_lock:
                    aircon = dict(state.get("aircon") or {})
                    aircon["connected"] = False
                    aircon["mqtt_connected"] = False
                    aircon["error"] = str(exc)
                    state["aircon"] = aircon
                log_event("controlhub1", "mqtt_error", error=str(exc))
                time.sleep(5)

    @staticmethod
    def _emits_ir(command: str) -> bool:
        """STATUS reads state only; every other current command emits IR."""
        return command != "status"

    def _wait_for_ir_guard(self, command: str,
                           minimum_gap_seconds: Optional[float]) -> float:
        if not self._emits_ir(command) or self._last_ir_ack_monotonic is None:
            return 0.0
        required_gap = max(
            CONTROLHUB1_MIN_IR_GAP_SECONDS,
            float(minimum_gap_seconds or 0.0),
        )
        elapsed = time.monotonic() - self._last_ir_ack_monotonic
        wait_seconds = max(0.0, required_gap - elapsed)
        if wait_seconds > 0:
            log_event(
                "controlhub1",
                "ir_guard_wait",
                command=command,
                wait_seconds=round(wait_seconds, 3),
                required_gap_seconds=required_gap,
            )
            time.sleep(wait_seconds)
        return wait_seconds

    def _publish_and_wait_locked(
        self,
        command: str,
        minimum_gap_seconds: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Publish one command while the caller owns _command_lock."""
        self._wait_for_ir_guard(command, minimum_gap_seconds)
        now = time.time()
        with state_lock:
            aircon = dict(state.get("aircon") or {})
            last_update = aircon.get("last_update")
            fresh = isinstance(last_update, (int, float)) and (
                now - last_update <= CONTROLHUB1_STALE_SECONDS)
            online = bool(aircon.get("connected") and fresh)
        client = self._get_client()
        if client is None or not client.is_connected() or not online:
            raise HTTPException(503, "Control Hub 1 ไม่เชื่อมต่อ")

        with self._ack_condition:
            initial_ack_seq = self._ack_seq

        with state_lock:
            state["aircon"]["command_pending"] = True
            state["aircon"]["pending_command"] = command
            state["aircon"].pop("last_command_error", None)

        # retain=False is mandatory: an old command must never replay when
        # the ESP32 reconnects. QoS 0 matches the current firmware; changing
        # to QoS 1 could duplicate a toggle-style IR command.
        info = client.publish(
            CONTROLHUB1_COMMAND_TOPIC, command, qos=0, retain=False)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            raise HTTPException(503, f"MQTT publish failed: {info.rc}")

        log_event("controlhub1", "command_published", command=command)
        deadline = time.monotonic() + CONTROLHUB1_ACK_TIMEOUT_SECONDS
        acknowledgement = None
        with self._ack_condition:
            while time.monotonic() < deadline:
                if self._ack_seq > initial_ack_seq and self._last_ack:
                    candidate, received_at = self._last_ack
                    if (received_at >= now and
                            candidate.get("command") == command):
                        acknowledgement = dict(candidate)
                        break
                remaining = deadline - time.monotonic()
                if remaining > 0:
                    self._ack_condition.wait(remaining)

        if acknowledgement is None:
            with state_lock:
                state["aircon"]["last_command_error"] = "ack_timeout"
            log_event("controlhub1", "command_ack_timeout", command=command)
            raise HTTPException(
                504,
                "ส่ง MQTT แล้ว แต่ไม่ได้รับคำยืนยันจาก Control Hub 1",
            )
        if acknowledgement.get("ok") is not True:
            detail = acknowledgement.get("detail") or "command rejected"
            log_event("controlhub1", "command_rejected", command=command,
                      detail=detail)
            raise HTTPException(502, f"Control Hub 1 ปฏิเสธคำสั่ง: {detail}")

        if self._emits_ir(command):
            self._last_ir_ack_monotonic = time.monotonic()
        # The current ESP event confirms that its IR send routine ran. There
        # is no feedback wire from the air conditioner, so this must never be
        # presented as proof that the appliance changed state.
        log_event(
            "controlhub1",
            "command_acknowledged",
            command=command,
            tx_count=acknowledgement.get("tx_count"),
            acknowledgement_scope="esp_ir_transmit_only",
        )
        return acknowledgement

    def publish_sequence_and_wait(
        self,
        commands: List[str],
        minimum_gaps_before: Optional[List[float]] = None,
    ) -> List[Dict[str, Any]]:
        """Run an atomic IR sequence so another request cannot interleave."""
        if not commands:
            return []
        if minimum_gaps_before is not None and (
                len(minimum_gaps_before) != len(commands)):
            raise ValueError("minimum_gaps_before must match commands")
        if not self._command_lock.acquire(blocking=False):
            raise HTTPException(429, "Air Con command already in progress")
        try:
            acknowledgements = []
            for index, command in enumerate(commands):
                minimum_gap = (
                    minimum_gaps_before[index]
                    if minimum_gaps_before is not None else None
                )
                acknowledgements.append(
                    self._publish_and_wait_locked(command, minimum_gap)
                )
            return acknowledgements
        finally:
            with state_lock:
                state["aircon"]["command_pending"] = False
                state["aircon"]["pending_command"] = None
            self._command_lock.release()

    def publish_and_wait(self, command: str) -> Dict[str, Any]:
        return self.publish_sequence_and_wait([command])[0]


controlhub1_mqtt = ControlHub1MQTT()


class ControlHub2BedMQTT:
    """MQTT command/ack bridge for the ESP32-S3 bed-remote servo hub."""

    def __init__(self):
        self._client = None
        self._client_lock = threading.Lock()
        self._command_lock = threading.Lock()
        self._ack_condition = threading.Condition()
        self._ack_seq = 0
        self._last_ack = None

    def _set_client(self, client):
        with self._client_lock:
            self._client = client

    def _get_client(self):
        with self._client_lock:
            return self._client

    def _on_connect(self, client, _userdata, _flags, reason_code,
                    _properties=None):
        if reason_code == 0:
            self._set_client(client)
            client.subscribe([
                (CONTROLHUB2_STATUS_TOPIC, 0),
                (CONTROLHUB2_EVENT_TOPIC, 0),
            ])
            with state_lock:
                state["bed_control"]["mqtt_connected"] = True
                state["bed_control"].pop("mqtt_error", None)
            log_event("controlhub2_bed", "mqtt_connected", host=MQTT_HOST,
                      port=MQTT_PORT)
        else:
            log_event("controlhub2_bed", "mqtt_connect_failed",
                      reason=str(reason_code))

    def _on_disconnect(self, client, _userdata, _disconnect_flags,
                       reason_code, _properties=None):
        with self._client_lock:
            if self._client is client:
                self._client = None
        with state_lock:
            bed = dict(state.get("bed_control") or {})
            bed.update({
                "connected": False,
                "mqtt_connected": False,
                "error": f"MQTT disconnected: {reason_code}",
                "command_pending": False,
                "pending_command": None,
            })
            state["bed_control"] = bed
        with self._ack_condition:
            self._ack_condition.notify_all()
        log_event("controlhub2_bed", "mqtt_disconnected",
                  reason=str(reason_code))

    def _on_message(self, _client, _userdata, message):
        try:
            obj = json.loads(message.payload.decode("utf-8"))
            if not isinstance(obj, dict):
                raise ValueError("payload is not a JSON object")
            now = time.time()
            with state_lock:
                bed = dict(state.get("bed_control") or {})
                if message.topic == CONTROLHUB2_STATUS_TOPIC:
                    bed.update(obj)
                    bed["connected"] = obj.get("online") is not False
                    bed["transport"] = "mqtt"
                    bed["status_last_update"] = now
                else:
                    bed["connected"] = True
                    bed["last_event"] = obj
                    bed["last_command"] = obj.get("command")
                    bed["last_command_ok"] = bool(obj.get("ok"))
                    bed["event_last_update"] = now
                    if obj.get("command_count") is not None:
                        bed["command_count"] = obj.get("command_count")
                    if obj.get("active_command") is not None:
                        bed["active_command"] = obj.get("active_command")
                    if "active_servo" in obj:
                        bed["active_servo"] = obj.get("active_servo")
                bed["last_update"] = now
                bed["stale"] = False
                bed["mqtt_connected"] = True
                bed.pop("error", None)
                state["bed_control"] = bed

            if message.topic == CONTROLHUB2_EVENT_TOPIC:
                with self._ack_condition:
                    self._ack_seq += 1
                    self._last_ack = (dict(obj), now)
                    self._ack_condition.notify_all()
        except Exception as exc:
            log_event("controlhub2_bed", "invalid_mqtt_payload",
                      topic=message.topic, error=str(exc))

    def run(self):
        if not MQTT_AVAILABLE:
            with state_lock:
                state["bed_control"]["error"] = "paho-mqtt is not installed"
            log_event("controlhub2_bed", "mqtt_library_missing",
                      install="paho-mqtt")
            return

        while True:
            try:
                client = mqtt.Client(
                    mqtt.CallbackAPIVersion.VERSION2,
                    client_id=f"zeep-pi5-controlhub2-bed-{socket.gethostname()}",
                )
                client.on_connect = self._on_connect
                client.on_disconnect = self._on_disconnect
                client.on_message = self._on_message
                client.reconnect_delay_set(min_delay=1, max_delay=30)
                client.connect(MQTT_HOST, MQTT_PORT, MQTT_KEEPALIVE)
                client.loop_forever(retry_first_connection=True)
            except Exception as exc:
                self._set_client(None)
                with state_lock:
                    bed = dict(state.get("bed_control") or {})
                    bed.update({"connected": False, "mqtt_connected": False,
                                "error": str(exc)})
                    state["bed_control"] = bed
                log_event("controlhub2_bed", "mqtt_error", error=str(exc))
                time.sleep(5)

    def _publish(self, command: str):
        client = self._get_client()
        if client is None or not client.is_connected():
            raise HTTPException(503, "Control Hub 2 Bed ไม่เชื่อมต่อ")
        info = client.publish(
            CONTROLHUB2_COMMAND_TOPIC, command, qos=0, retain=False)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            raise HTTPException(503, f"MQTT publish failed: {info.rc}")

    def publish_stop_best_effort(self, reason: str = "safety") -> bool:
        """Non-blocking stop for safety/one-shot motion; never raises."""
        try:
            self._publish("bed_stop")
            log_event("controlhub2_bed", "stop_published", reason=reason)
            return True
        except Exception as exc:
            log_event("controlhub2_bed", "stop_failed", reason=reason, error=str(exc))
            return False

    def publish_and_wait(
        self, requested_command: str, toggle_repeat: bool = False
    ) -> Tuple[Dict[str, Any], str]:
        if not self._command_lock.acquire(blocking=False):
            raise HTTPException(429, "Bed command already in progress")
        try:
            now = time.time()
            with state_lock:
                bed = dict(state.get("bed_control") or {})
                active_command = bed.get("active_command")
                last_update = bed.get("last_update")
                fresh = isinstance(last_update, (int, float)) and (
                    now - last_update <= CONTROLHUB2_STALE_SECONDS)
                online = bool(bed.get("connected") and fresh)
            if not online:
                raise HTTPException(503, "Control Hub 2 Bed ไม่เชื่อมต่อ")

            directional_commands = {
                "head_up", "head_down", "foot_up", "foot_down",
            }
            command = requested_command
            if (toggle_repeat and requested_command in directional_commands
                    and active_command == requested_command):
                command = "bed_stop"

            # Resolve the toggle while holding the per-device command lock, so
            # repeated clicks from multiple browser clients cannot race. A
            # repeated active direction becomes STOP and remains available
            # during a safety latch; FLAT is never toggled.
            if command not in ("bed_stop", "status"):
                _require_safety_allows(f"Bed {command}")

            with self._ack_condition:
                initial_ack_seq = self._ack_seq
            with state_lock:
                state["bed_control"]["command_pending"] = True
                state["bed_control"]["pending_command"] = command
                state["bed_control"].pop("last_command_error", None)

            self._publish(command)
            log_event("controlhub2_bed", "command_published",
                      requested_command=requested_command, command=command)
            deadline = time.monotonic() + CONTROLHUB2_ACK_TIMEOUT_SECONDS
            acknowledgement = None
            with self._ack_condition:
                while time.monotonic() < deadline:
                    if self._ack_seq > initial_ack_seq and self._last_ack:
                        candidate, received_at = self._last_ack
                        if (received_at >= now and
                                candidate.get("command") == command):
                            acknowledgement = dict(candidate)
                            break
                    remaining = deadline - time.monotonic()
                    if remaining > 0:
                        self._ack_condition.wait(remaining)

            if acknowledgement is None:
                with state_lock:
                    state["bed_control"]["last_command_error"] = "ack_timeout"
                raise HTTPException(
                    504,
                    "ส่ง MQTT แล้ว แต่ไม่ได้รับคำยืนยันจาก Control Hub 2 Bed",
                )
            if acknowledgement.get("ok") is not True:
                detail = acknowledgement.get("detail") or "command rejected"
                raise HTTPException(
                    502, f"Control Hub 2 Bed ปฏิเสธคำสั่ง: {detail}")
            log_event("controlhub2_bed", "command_acknowledged",
                      command=command,
                      command_count=acknowledgement.get("command_count"))
            return acknowledgement, command
        finally:
            with state_lock:
                state["bed_control"]["command_pending"] = False
                state["bed_control"]["pending_command"] = None
            self._command_lock.release()


controlhub2_bed_mqtt = ControlHub2BedMQTT()

# Generation tokens cancel an older delayed stop when a new movement starts.
# Without this guard, command B could be stopped early by command A's timer.
_bed_motion_timer_lock = threading.Lock()
_bed_motion_generation = 0


def _cancel_bed_auto_stop(reason: str) -> None:
    global _bed_motion_generation
    with _bed_motion_timer_lock:
        _bed_motion_generation += 1
    with state_lock:
        state["bed_control"]["auto_stop_at"] = None
        state["bed_control"]["auto_stop_pending"] = False
    log_event("controlhub2_bed", "auto_stop_cancelled", reason=reason)


def _schedule_bed_auto_stop(source_command: str) -> None:
    """Schedule one authoritative stop for the latest movement command."""
    global _bed_motion_generation
    with _bed_motion_timer_lock:
        _bed_motion_generation += 1
        generation = _bed_motion_generation
    stop_at = time.time() + BED_MOVE_SECONDS
    with state_lock:
        state["bed_control"]["motion_duration_s"] = BED_MOVE_SECONDS
        state["bed_control"]["auto_stop_at"] = stop_at
        state["bed_control"]["auto_stop_pending"] = True

    def worker():
        time.sleep(BED_MOVE_SECONDS)
        with _bed_motion_timer_lock:
            if generation != _bed_motion_generation:
                return
        published = controlhub2_bed_mqtt.publish_stop_best_effort(
            reason=f"auto_{BED_MOVE_SECONDS:g}s:{source_command}"
        )
        with _bed_motion_timer_lock:
            still_latest = generation == _bed_motion_generation
        if still_latest:
            with state_lock:
                state["bed_control"]["auto_stop_at"] = None
                state["bed_control"]["auto_stop_pending"] = False
        log_event(
            "controlhub2_bed",
            "auto_stop_completed" if published else "auto_stop_publish_failed",
            source_command=source_command,
            duration_s=BED_MOVE_SECONDS,
        )

    threading.Thread(
        target=worker,
        daemon=True,
        name=f"bed-auto-stop-{generation}",
    ).start()


def _read_exact(ser: serial.Serial, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = ser.read(n - len(buf))
        if not chunk:
            raise TimeoutError("serial timeout")
        buf.extend(chunk)
    return bytes(buf)


def bcg_reader():
    """66-byte Odata/Bdata frame: 25 x int16 samples + confirmed summary bytes.

    The LSM-800-T sends a frame only every few seconds. A quiet line is NOT a
    failure — treating the inter-frame gap as an error made the UI flap
    connected/disconnected constantly. The reader now keeps the port open
    through silence and mid-frame hiccups; only real port errors reconnect.
    Freshness for the UI comes from last_update + BCG_STALE_SECONDS.
    """
    last_error = None
    while True:
        try:
            with serial.Serial(BCG_PORT, BCG_BAUD, timeout=1) as ser:
                log_event("bcg", "connected", port=BCG_PORT, baud=BCG_BAUD)
                last_error = None
                with state_lock:
                    state["sensor"]["bcg"].pop("error", None)
                sync = bytearray()
                while True:
                    b = ser.read(1)
                    if not b:
                        continue  # quiet gap between frames — normal, stay open
                    sync += b
                    if len(sync) > 5:
                        del sync[0]
                    if bytes(sync) != b"Odata":
                        continue
                    try:
                        rest = _read_exact(ser, 61)
                    except TimeoutError:
                        sync.clear()
                        continue  # partial frame — drop it and resync
                    frame = b"Odata" + rest
                    if frame[57:62] != b"Bdata":
                        continue
                    parsed = parse_lsm800t_frame(frame)
                    samples = parsed["samples"]
                    status_code = parsed["status_code"]
                    hr_value = parsed["heart_rate_bpm"]
                    rr_value = parsed["respiration_rate"]
                    hr_current_valid = bool(
                        hr_value is not None
                        and HR_SANITY_RANGE_BPM[0] <= hr_value <= HR_SANITY_RANGE_BPM[1]
                    )
                    rr_current_valid = bool(
                        rr_value is not None
                        and RR_SANITY_RANGE_PER_MIN[0] <= rr_value <= RR_SANITY_RANGE_PER_MIN[1]
                    )
                    # Persist raw packet to SQLite (epoch-batched, queue-based)
                    bcg_storage.add_packet(
                        frame,
                        sensor_packet_id=parsed["sensor_packet_id"],
                        status_code=status_code,
                        heart_rate=hr_value,
                        respiration_rate=rr_value,
                    )
                    with history_lock:
                        bcg_history.append({
                            "t": time.time(),
                            "status": status_code,
                            "hr": hr_value,
                            "rr": rr_value,
                            "samples": samples,
                        })
                        bcg_raw_history.append({
                            "t": time.time(),
                            "packet_id": parsed["sensor_packet_id"],
                            "status_code": status_code,
                            "heart_rate": hr_value,
                            "respiration_raw": parsed["respiration_raw"],
                            "respiration_rate": rr_value,
                            "samples": samples,
                            "raw_hex": frame.hex(" "),
                        })
                    packet_time = time.time()
                    with state_lock:
                        bcg = state["sensor"]["bcg"]
                        current_vitals_valid = bool(
                            status_code in ON_BED_CODES
                            and hr_current_valid
                            and rr_current_valid
                        )
                        previous_streak = int(bcg.get("vital_valid_streak") or 0)
                        bcg.update({
                            "connected": True,
                            "samples": samples,
                            "sensor_packet_id": parsed["sensor_packet_id"],
                            "status_code": status_code,
                            "status_text": STATUS_TEXT.get(status_code, "Unknown"),
                            "respiration_raw": parsed["respiration_raw"],
                            "heart_rate_current_valid": hr_current_valid,
                            "respiration_current_valid": rr_current_valid,
                            "vital_valid_streak": (
                                previous_streak + 1 if current_vitals_valid else 0
                            ),
                            "vital_valid_since": (
                                bcg.get("vital_valid_since")
                                if current_vitals_valid and previous_streak > 0
                                else packet_time if current_vitals_valid else None
                            ),
                            "last_update": packet_time,
                            "packets": int(bcg.get("packets", 0)) + 1,
                        })
                        # Raw zeros remain stored as None in bcg.db. The live
                        # interface alone gets a short hold to avoid flicker
                        # between valid packets while the user is still on bed.
                        for field, last_field, held_field, value in (
                            ("heart_rate_bpm", "heart_rate_last_valid", "heart_rate_held", hr_value),
                            ("respiration_rate", "respiration_last_valid", "respiration_held", rr_value),
                        ):
                            if value is not None:
                                bcg[field] = value
                                bcg[last_field] = packet_time
                                bcg[held_field] = False
                            else:
                                last_valid = bcg.get(last_field)
                                can_hold = (
                                    status_code in ON_BED_CODES
                                    and isinstance(last_valid, (int, float))
                                    and packet_time - last_valid <= BCG_VITAL_HOLD_SECONDS
                                )
                                if not can_hold:
                                    bcg[field] = None
                                bcg[held_field] = bool(can_hold)
        except Exception as exc:
            if str(exc) != last_error:  # log แค่ตอนอาการเปลี่ยน ไม่ spam ทุก 2 วิ
                log_event("bcg", "disconnected", error=str(exc))
                last_error = str(exc)
            with state_lock:
                state["sensor"]["bcg"]["connected"] = False
                state["sensor"]["bcg"]["error"] = str(exc)
            time.sleep(2)


def sensor_frame_sampler():
    """Publish one canonical 10-second display/recording Sensor frame.

    Serial readers remain event-driven at each device's native cadence. This
    sampler aggregates every BCG frame that actually arrived in the bucket and
    joins the freshest ESP32 environment payload without resampling serial I/O.
    Environment, HR, RR and Bed Status therefore share this clock independently
    of whether a User Session exists. Sleep Evidence is the only downstream
    consumer that aggregates these frames further to 30/60 seconds.
    """
    next_tick = time.monotonic()
    bucket_start = time.time()
    while True:
        next_tick += SLEEP_SAMPLE_SECONDS
        time.sleep(max(0.0, next_tick - time.monotonic()))
        bucket_end = time.time()
        with history_lock:
            bcg_frames = [f for f in bcg_history if bucket_start < f["t"] <= bucket_end]
        with state_lock:
            b = dict(state["sensor"]["bcg"])
            e = dict(state["sensor"].get("esp32") or {})
            h2 = dict(state["sensor"].get("sensorhub2") or {})
        raw_hr = [f.get("hr") for f in bcg_frames]
        raw_rr = [f.get("rr") for f in bcg_frames]
        valid_hr = filter_vital_values(raw_hr, HR_SANITY_RANGE_BPM)
        valid_rr = filter_vital_values(raw_rr, RR_SANITY_RANGE_PER_MIN)
        statuses = [f.get("status") for f in bcg_frames if f.get("status") is not None]
        raw_points = [v for f in bcg_frames for v in (f.get("samples") or [])]
        clipped = sum(1 for v in raw_points if v in (-32768, 32767))
        clip_ratio = clipped / len(raw_points) if raw_points else None
        # Any motion within the bucket is more informative than the final quiet frame.
        bucket_status = 2 if 2 in statuses else (statuses[-1] if statuses else None)
        raw_exit_frames = sum(status == 1 for status in statuses)
        # Keep enough completed buckets for the configured exit debounce. The
        # previous implementation supplied only one previous bucket, making a
        # three-bucket confirmation mathematically impossible in the live path.
        with history_lock:
            previous_features = list(sleep_feature_history)[
                -max(0, BED_EXIT_CONFIRM_BUCKETS - 1):
            ]
        previous_feature = previous_features[-1] if previous_features else None
        recent_raw_statuses = [
            previous.get("status")
            for previous in previous_features
            if previous.get("status") is not None
        ]
        if bucket_status is not None:
            recent_raw_statuses.append(bucket_status)
        bed_exit_evidence = bed_exit_window_evidence(
            recent_raw_statuses,
            latest_raw_exit_frames=raw_exit_frames,
            latest_raw_total_frames=len(statuses),
            minimum_consecutive_buckets=BED_EXIT_CONFIRM_BUCKETS,
            minimum_raw_frames=BED_EXIT_RAW_MIN_FRAMES,
            minimum_raw_ratio=BED_EXIT_RAW_MIN_RATIO,
            raw_packet_confirmation_enabled=BED_EXIT_RAW_CONFIRMATION_ENABLED,
        )
        confirmed_status = bucket_status
        if bucket_status == 1 and not bed_exit_evidence["confirmed"]:
            previous_confirmed = (
                previous_feature.get("confirmed_status", previous_feature.get("status"))
                if previous_feature is not None else None
            )
            # A transient code must not manufacture a bed exit. During an
            # active stream, hold the last canonical on-bed status for this
            # analysis decision; startup with no history defaults to On bed.
            confirmed_status = (
                previous_confirmed if previous_confirmed in ON_BED_CODES else 0)
        environment = build_environment_snapshot(e, h2, bucket_end)
        sound_summary = sound_window_summary(bucket_start, bucket_end)
        sph0645_status = ((environment.get("devices") or {}).get("sph0645") or {}).get("status")
        if sound_summary.get("leq_dba") is not None and sph0645_status == "live":
            # All pages and analytical consumers receive this same analysis
            # energy average. Raw dBFS and latest estimate remain in Admin state.
            environment["sound_dba_est"] = sound_summary["leq_dba"]
        with state_lock:
            state["system"]["sound_analysis"] = {
                **sound_summary,
                "window_start": datetime.fromtimestamp(bucket_start, timezone.utc).isoformat(),
                "window_end": datetime.fromtimestamp(bucket_end, timezone.utc).isoformat(),
            }
        device_status = {
            key: device.get("status") == "live"
            for key, device in (environment.get("devices") or {}).items()
        }
        esp_fresh = any(device_status.values())
        feature = {
            "t": bucket_end, "bucket_start": bucket_start,
            "status": bucket_status,
            "confirmed_status": confirmed_status,
            "bed_exit_evidence": bed_exit_evidence,
            # Preserve every vendor status observed inside the analysis
            # bucket. The final status alone can hide a short snoring or weak-
            # breathing flag that returned to ordinary On-bed before the tick.
            "status_codes_seen": sorted({int(value) for value in statuses}),
            "hr": round(sum(valid_hr) / len(valid_hr), 2) if valid_hr else None,
            "rr": round(sum(valid_rr) / len(valid_rr), 2) if valid_rr else None,
            "invalid_hr_count": len([value for value in raw_hr if value is not None]) - len(valid_hr),
            "invalid_rr_count": len([value for value in raw_rr if value is not None]) - len(valid_rr),
            "packet_count": b.get("packets"), "bcg_frames": len(bcg_frames),
            "bcg_latest_t": bcg_frames[-1]["t"] if bcg_frames else None,
            "clip_ratio": round(clip_ratio, 4) if clip_ratio is not None else None,
            # HR/RR/status are device summary bytes and remain usable even when
            # the raw waveform clips; clipping lowers confidence separately.
            "bcg_valid": bool(bcg_frames and valid_hr and valid_rr),
            # Internal rolling waveform only. It is not copied into the public
            # analysis frame; the canonical raw record remains bcg.db.
            "bcg_samples": raw_points,
            "temperature": environment.get("temperature_c") if device_status.get("sht3x_dis") else None,
            "humidity": environment.get("humidity_rh") if device_status.get("sht3x_dis") else None,
            "co2": environment.get("co2_ppm") if device_status.get("mhz19c") else None,
            "lux": environment.get("lux") if device_status.get("opt3001") else None,
            "sound_dba": environment.get("sound_dba_est") if device_status.get("sph0645") else None,
            # Analytical audio evidence must use samples captured inside this
            # exact bucket, never a held display value from an older packet.
            "sound_leq_dba": (
                sound_summary.get("leq_dba")
                if device_status.get("sph0645") else None
            ),
            "sound_sample_count": int(sound_summary.get("sample_count") or 0),
            "sound_window_status": sound_summary.get("status"),
            "sound_span_db": sound_summary.get("span_db"),
            "sound_large_step": bool(sound_summary.get("large_step_detected")),
            "pm2_5": environment.get("pm2_5_ug_m3") if device_status.get("pms7003") else None,
            "voc": environment.get("voc_index") if device_status.get("sgp40") else None,
            "esp_fresh": esp_fresh,
            "sensor_status": device_status,
        }
        with history_lock:
            sleep_feature_history.append(feature)
        _publish_sensor_frame(feature, environment, b)
        bucket_start = bucket_end


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
    exit_confirmed = bool(
        status_code == 1
        and (feature.get("bed_exit_evidence") or {}).get("confirmed")
    )
    current_vitals_valid = bool(feature.get("bcg_valid"))
    cached = _last_sleep_evidence_result()

    reason = None
    data_status = "collecting_evidence_epoch"
    display_state = "no_data"
    if not session_active:
        reason = "ไม่มีผู้ใช้งาน Session · ไม่ประเมิน Sleep State"
        data_status = "no_session"
        display_state = "off_bed"
    elif not session_recording:
        reason = "รอเริ่มบันทึก Session ก่อนสะสม Evidence epoch"
        data_status = "waiting_for_vitals"
    elif exit_confirmed:
        reason = "Bed Status ยืนยันว่าไม่มีผู้ใช้งานบนเตียง · ไม่ประเมิน Sleep State"
        data_status = "empty_bed"
        display_state = "off_bed"
    elif not current_vitals_valid:
        reason = "รอบ Sensor ปัจจุบันไม่มี HR/RR สด · ยกเลิก Evidence ที่กำลังรอยืนยัน"
        data_status = "invalid_or_missing_current_vitals"

    if reason is not None:
        with sleep_path_lock:
            _sleep_stage_path["candidate"] = None
            _sleep_stage_path["candidate_ticks"] = 0
            # A previously valid state must not reappear on a later 10-second
            # frame until a complete new 30-second evidence epoch is produced.
            _sleep_stage_path["last_evidence_result"] = None
        value = dict(cached or {})
        value.update({
            "state": display_state,
            "confirmed_state": None,
            "classification_active": False,
            "evidence_active": False,
            "probabilities": {key: 0.0 for key in ZEEP_SLEEP_STATES},
            "evidence_probabilities": {key: 0.0 for key in ZEEP_SLEEP_STATES},
            "confidence": "low",
            "provisional": True,
            "data_status": data_status,
            "reason": reason,
        })
    elif cached is not None:
        value = cached
        value["data_status"] = (
            "live" if value.get("classification_active") else "confirming_state"
        )
        value["evidence_held_between_epochs"] = True
    else:
        value = {
            "state": "no_data",
            "confirmed_state": None,
            "version": SLEEP_ESTIMATOR_VERSION,
            "evidence_version": SLEEP_EVIDENCE_VERSION,
            "classification_active": False,
            "evidence_active": False,
            "probabilities": {key: 0.0 for key in ZEEP_SLEEP_STATES},
            "evidence_probabilities": {key: 0.0 for key in ZEEP_SLEEP_STATES},
            "confidence": "low",
            "provisional": True,
            "data_status": "collecting_evidence_epoch",
            "reason": "กำลังสะสม Sensor 10 วินาทีเพื่อสร้าง Evidence epoch 30 วินาที",
            "sample_s": SLEEP_SAMPLE_SECONDS,
            "required_samples": SLEEP_MIN_FRAMES,
            "evidence_epoch_s": SLEEP_EVIDENCE_EPOCH_SECONDS,
            "confirmation_s": SLEEP_CONFIRMATION_SECONDS,
        }
    value.update({
        "sensor_frame_clock": clock,
        "evidence_epoch_due": False,
        "next_evidence_s": clock["next_evidence_s"],
    })
    return value


def _publish_sensor_frame(feature: Dict[str, Any], environment: Dict[str, Any],
                          bcg_state: Dict[str, Any]) -> None:
    """Publish the 10-second Sensor frame, then advance Sleep-only evidence."""
    global _analysis_frame
    epoch_s = float(feature["t"])
    with state_lock:
        session_id = state["session"].get("session_id")
    clock = _advance_sleep_evidence_clock(session_id)
    if clock["evidence_due"]:
        sleep_value = estimate_sleep_state()
        sleep_value.update({
            "sensor_frame_clock": clock,
            "evidence_epoch_due": True,
            "next_evidence_s": SLEEP_EVIDENCE_EPOCH_SECONDS,
        })
        _remember_sleep_evidence(sleep_value, epoch_s)
    else:
        sleep_value = _sleep_value_between_evidence_epochs(
            feature, session_id, clock)
    status_code = feature.get("confirmed_status", feature.get("status"))
    raw_status_code = feature.get("status")
    bcg = {
        "analysis_epoch_s": epoch_s,
        "status_code": status_code,
        "status_text": STATUS_TEXT.get(status_code, "Unknown") if status_code is not None else None,
        "raw_status_code": raw_status_code,
        "raw_status_text": (
            STATUS_TEXT.get(raw_status_code, "Unknown")
            if raw_status_code is not None else None
        ),
        "bed_exit_evidence": dict(feature.get("bed_exit_evidence") or {}),
        "heart_rate_bpm": feature.get("hr"),
        "respiration_rate": feature.get("rr"),
        "bcg_frames": feature.get("bcg_frames", 0),
        "analysis_valid": bool(feature.get("bcg_valid")),
        "analysis_data_age_s": (
            round(max(0.0, epoch_s - feature["bcg_latest_t"]), 1)
            if isinstance(feature.get("bcg_latest_t"), (int, float)) else None
        ),
        # Connection/fallback values are refreshed by snapshot(); these fields
        # describe the source used for this exact analysis frame.
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
        _sleep_cache.update({
            "t": time.monotonic(), "value": sleep_value,
            "session_id": session_id, "sequence": frame["sequence"],
        })


def _publish_analysis_frame(feature: Dict[str, Any], environment: Dict[str, Any],
                            bcg_state: Dict[str, Any]) -> None:
    """Backward-compatible internal alias; new code uses Sensor terminology."""
    _publish_sensor_frame(feature, environment, bcg_state)


# ---------- session sampling & lifecycle ----------
def take_session_sample() -> Dict[str, Any]:
    snap = snapshot()
    e = snap["sensor"].get("environment") or {}
    b = snap["sensor"]["bcg"] or {}
    sleep = snap.get("sleep") or {}
    sleep_metrics = sleep.get("metrics") or {}
    auxiliary = sleep_metrics.get("auxiliary_evidence") or {}
    acoustic = auxiliary.get("acoustic") or {}
    devices = e.get("devices") or {}
    live = lambda key: (devices.get(key) or {}).get("status") == "live"
    b_ok = bool(b.get("connected"))
    waveform = sleep.get("signal_features") or {}
    sample_arousal_proxy = arousal_proxy_evidence({
        "bcg_amplitude_shift_ratio": waveform.get("bcg_amplitude_shift_ratio"),
        "movement_ratio": sleep.get("movement_ratio"),
        "bed_status": b.get("status_text") if b_ok else None,
    }, SLEEP_MOVE_WAKE_RATIO)
    return {
        # Timeline time is the acquisition time, not the latest 10-second
        # analysis-frame boundary. Reusing a frame timestamp could create two
        # apparent rows at the same instant during a cadence migration.
        "t": round(time.time(), 1),
        "analysis_epoch_s": (snap.get("analysis_frame") or {}).get("epoch_s"),
        "temp": e.get("temperature_c") if live("sht3x_dis") else None,
        "hum": e.get("humidity_rh") if live("sht3x_dis") else None,
        "co2": e.get("co2_ppm") if live("mhz19c") else None,
        "pm2_5": e.get("pm2_5_ug_m3") if live("pms7003") else None,
        "voc": e.get("voc_index") if live("sgp40") else None,
        "lux": e.get("lux") if live("opt3001") else None,
        "dba": e.get("sound_dba_est") if live("sph0645") else None,
        "hr": b.get("heart_rate_bpm") if b_ok else None,
        "rr": b.get("respiration_rate") if b_ok else None,
        "bed": b.get("status_text") if b_ok else None,
        # Operational statuses such as no_data/off_bed are not Sleep Stages and
        # must not enter stage counts, architecture percentages or baselines.
        "sleep": sleep.get("state") if sleep.get("classification_active") else None,
        "sleep_confirmed_state": (
            sleep.get("confirmed_state")
            if sleep.get("classification_active") else None
        ),
        "sleep_evidence_candidate": (sleep.get("evidence") or {}).get("candidate"),
        "sleep_confirmation": sleep.get("confirmation") or {},
        "sleep_estimator_version": sleep.get("version"),
        "sleep_evidence_version": sleep.get("evidence_version"),
        "sleep_baseline_version": (sleep.get("baseline_definition") or {}).get("version"),
        "sleep_transition_policy": (sleep.get("baseline_definition") or {}).get(
            "transition_policy"),
        # These fields remain in the in-memory Session record and are reduced
        # into final_summary. They do not turn audio/environment into a stage
        # input: confidence is reported, while corroborated sound explains a
        # possible disturbance only when BCG or Bed Status agrees.
        "sleep_confidence": sleep.get("confidence"),
        "sleep_probability": (sleep.get("probabilities") or {}).get(sleep.get("state")),
        "acoustic_corroborated": bool(acoustic.get("corroborated")),
        # Compact evidence is persisted with the same canonical Session sample
        # so the post-session score can reproduce its debounced disturbance index.
        "arousal_proxy": sample_arousal_proxy,
    }


def bed_occupied_now() -> bool:
    """มีคนบนเตียงจริงตอนนี้ไหม — จาก frame BCG ล่าสุดที่ยังสด"""
    with state_lock:
        b = dict(state["sensor"]["bcg"])
    last = b.get("last_update")
    return bool(
        b.get("connected")
        and isinstance(last, (int, float))
        and time.time() - last <= BCG_STALE_SECONDS
        and b.get("status_code") in ON_BED_CODES
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
    now = time.time()
    last = b.get("last_update")
    fresh = bool(
        b.get("connected")
        and isinstance(last, (int, float))
        and now - last <= BCG_STALE_SECONDS
    )
    on_bed = bool(fresh and b.get("status_code") in ON_BED_CODES)
    hr_valid = bool(
        on_bed
        and b.get("heart_rate_current_valid")
        and not b.get("heart_rate_held")
    )
    rr_valid = bool(
        on_bed
        and b.get("respiration_current_valid")
        and not b.get("respiration_held")
    )
    packet_count = int(b.get("packets") or 0)
    raw_start_packet_count = (active or {}).get("vital_gate_start_packet_count")
    start_packet_count = (
        int(raw_start_packet_count)
        if isinstance(raw_start_packet_count, (int, float))
        else packet_count
    )
    packets_since_start = max(0, packet_count - start_packet_count)
    confirmed_packets = min(
        packets_since_start,
        int(b.get("vital_valid_streak") or 0),
    ) if hr_valid and rr_valid else 0
    ready = bool(
        on_bed
        and hr_valid
        and rr_valid
        and confirmed_packets >= SESSION_VITAL_START_PACKETS
    )
    if not fresh:
        reason = "waiting_for_bcg"
    elif not on_bed:
        reason = "waiting_for_bed"
    elif not hr_valid and not rr_valid:
        reason = "waiting_for_hr_rr"
    elif not hr_valid:
        reason = "waiting_for_hr"
    elif not rr_valid:
        reason = "waiting_for_rr"
    elif not ready:
        reason = "confirming_hr_rr"
    else:
        reason = "ready"
    return {
        "ready": ready,
        "heart_rate_valid": hr_valid,
        "respiration_rate_valid": rr_valid,
        "confirmed_packets": confirmed_packets,
        "required_packets": SESSION_VITAL_START_PACKETS,
        "packets_since_login": packets_since_start,
        "bcg_fresh": fresh,
        "on_bed": on_bed,
        "reason": reason,
    }


def _begin_recording(active: Dict[str, Any]):
    """ยืนยันเตียง + HR/RR สดครบเกณฑ์ → เริ่มนับเวลาและบันทึกจริง"""
    record = active["record"]
    vital_gate = session_vital_gate_now(active)
    if not vital_gate["ready"]:
        raise RuntimeError(
            f"cannot start Session before HR/RR gate: {vital_gate['reason']}"
        )
    now_iso = datetime.now(timezone.utc).isoformat()
    with session_lock:
        active["phase"] = "recording"
        active["last_sample"] = float("-inf")  # เก็บ sample แรกทันที
        record["started_at_utc"] = now_iso
        record["started_monotonic"] = time.monotonic()
        record["sample_cadence_segments"] = [{
            "start_at_utc": now_iso,
            "sample_interval_s": _sample_interval_seconds(
                record.get("sample_interval_s"), SESSION_SAMPLE_SECONDS),
        }]
    database.enqueue("sessions", "session_start", {
        "session_id": record["session_id"], "user": record["username"],
        "username_key": record["username_key"], "gender": record["gender"],
        "identity_subject": record.get("identity_subject"), "pod_id": record.get("pod_id"),
        "zeep_public_id": record.get("zeep_public_id"),
        "start_time": now_iso, "created_at": record["armed_at_utc"],
    })
    # The open DB row must be durable before the checkpoint announces the
    # recording phase. A hard reboot at either side can therefore restore a
    # coherent state instead of inventing or truncating a sleep record.
    if not database.flush(30):
        raise RuntimeError("database writer did not flush Session start")
    _save_active_session_checkpoint(active)
    bcg_storage.start_session(record["session_id"])
    log_event("session", "bed_confirmed_start", session_id=record["session_id"],
              user=record["username"], required_s=BED_START_SECONDS,
              vital_packets=SESSION_VITAL_START_PACKETS)
    with state_lock:
        state["session"].update({
            "recording": True, "started_at": time.time(), "bed_wait_s": 0,
            "vital_gate": {
                **vital_gate,
                "ready": True,
                "reason": "recording",
            },
        })
    # Start the stable-30s epoch clock at the recording boundary. Frames used
    # only to satisfy the pre-recording HR/RR gate must not shorten the first
    # 30-second evidence epoch or the initial 60-second confirmation.
    _reset_live_sleep_inference(record["session_id"])


def session_sampler():
    while True:
        time.sleep(1.0)
        with session_lock:
            active = _active_session
        if active is None:
            continue

        # ---- ระยะรอ: เตียงครบเวลา + HR/RR สดยืนยันครบ ----
        if active.get("phase") == "waiting_bed":
            occupied = bed_occupied_now()
            vital_gate = session_vital_gate_now(active)
            promote = False
            wait_s = 0.0
            with session_lock:
                if _active_session is not active or active.get("phase") != "waiting_bed":
                    continue
                if occupied:
                    if active.get("onbed_since") is None:
                        active["onbed_since"] = time.monotonic()
                    wait_s = time.monotonic() - active["onbed_since"]
                    if wait_s >= BED_START_SECONDS and vital_gate["ready"]:
                        promote = True
                else:
                    active["onbed_since"] = None
            if promote:
                try:
                    _begin_recording(active)
                except RuntimeError as exc:
                    # A new BCG packet can invalidate one vital between the
                    # sampler check and the durable DB start. Keep waiting;
                    # never let this race terminate the Session sampler.
                    vital_gate = session_vital_gate_now(active)
                    with state_lock:
                        state["session"]["vital_gate"] = vital_gate
                    log_event(
                        "session", "vital_start_gate_changed",
                        session_id=active["record"]["session_id"], error=str(exc),
                    )
            else:
                with state_lock:
                    state["session"].update({
                        "bed_wait_s": round(min(wait_s, BED_START_SECONDS), 1),
                        "vital_gate": vital_gate,
                    })
            continue

        # ---- ระยะบันทึกจริง ----
        with session_lock:
            if _active_session is not active:
                continue
            sample_interval_s = _sample_interval_seconds(
                (active.get("record") or {}).get("sample_interval_s"),
                SESSION_SAMPLE_SECONDS,
            )
            if time.monotonic() - active["last_sample"] < sample_interval_s:
                continue
            active["last_sample"] = time.monotonic()
        sample = take_session_sample()  # snapshot() takes state_lock — outside session_lock
        sample["sample_interval_s"] = sample_interval_s
        count = None
        session_id = None
        with session_lock:
            if _active_session is active and len(active["samples"]) < SESSION_SAMPLE_LIMIT:
                active["samples"].append(sample)
                count = len(active["samples"])
                session_id = active["record"]["session_id"]
        if count is not None:
            with state_lock:
                state["session"]["samples"] = count
            # Persist the timeline row (DB writer thread owns the actual write)
            database.enqueue("sessions", "timeline", {
                "session_id": session_id,
                "timestamp": datetime.fromtimestamp(sample["t"], timezone.utc).isoformat(),
                "temperature": sample["temp"], "humidity": sample["hum"],
                "co2": sample["co2"], "pm2_5": sample.get("pm2_5"),
                "voc_index": sample.get("voc"), "lux": sample["lux"],
                "sound": sample["dba"],
                "heart_rate": sample["hr"], "respiration_rate": sample["rr"],
                "bed_status": sample["bed"],
            })


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
            due = bool(
                active
                and time.monotonic() - active.get("last_lease_renew", 0)
                >= OCCUPANCY_RENEW_SECONDS
            )
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


# ---------------------------------------------------------------------------
# Upload a finished Session to the ZEEP account backend (POST /v1/sleep-sessions/ingest)
#
# The account backend stores ``record`` verbatim in the ``scoring_result`` jsonb
# column and returns the whole row from both the sleep-history list and detail
# endpoints, so the payload is built as a fresh whitelist literal.  Copying
# ``record`` and deleting keys would drag ``samples`` (one row per cadence tick,
# ~1 MB a night) plus the frozen Profile context into every history request.
#
# Percentages/minutes come from ``session_report`` rather than being recomputed
# so the uploaded numbers are exactly what the Pod itself displays.

# pi5 scores AASM W/N1/N2/N3/REM.  The backend only ever tests ``stage != 0`` to
# find sleep onset and ``stage == 0`` to count awakenings, so Wake keeps index 0
# and ``stage_name`` carries the real meaning: the same jsonb column also holds
# 4-level (0=Awake 1=Light 2=Deep 3=REM) rows from the Python AI service, and
# the name is what lets a reader tell the two encodings apart.
_INGEST_STAGE_INDEX = {
    "wake": 0, "n1": 1, "n2": 2, "nrem_light": 2, "n3": 3, "nrem_deep": 3, "rem": 4,
    # Leaving the Pod is not a Sleep Stage and is excluded from every stage
    # total, but it must not disappear from the run-length encoding either:
    # dropping it would merge the sleep either side of it into one unbroken
    # bout and hide the bed exit.  Index 0 makes the backend count it as an
    # awakening, which is what the Pod's own night summary already does.
    "off_bed": 0,
}
_INGEST_STAGE_NAME = {
    "wake": "wake", "n1": "n1", "n2": "n2", "nrem_light": "n2",
    "n3": "n3", "nrem_deep": "n3", "rem": "rem", "off_bed": "off_bed",
}
# Pod criterion key -> the key the account backend promotes to a typed column.
_INGEST_ENVIRONMENT_KEYS = {
    "temperature": "temperature",
    "humidity": "humidity",
    "co2": "co2",
    "light": "lux",
    "sound": "noise",
    "pm25": "pm25",
    "voc": "voc",
}


def _ingest_stage_runs(report_samples: List[Dict[str, Any]],
                       epoch_seconds: float) -> tuple[List[Dict[str, Any]],
                                                      List[Dict[str, Any]]]:
    """Run-length encode the scored stage series into segments + hypnogram.

    Runs over ``report_samples`` (the cadence-expanded series that produced
    ``sleep_state_counts``) so segment minutes add up to the stage minutes sent
    alongside them.  Unscored rows are ignored rather than breaking the run:
    they are already absent from every stage total, and splitting a run around
    a sensor gap would report one awakening as two.
    """
    segments: List[Dict[str, Any]] = []
    hypnogram: List[Dict[str, int]] = []
    current: Optional[str] = None
    run = 0

    def close() -> None:
        if current is None or run <= 0:
            return
        segments.append({
            "stage": _INGEST_STAGE_INDEX[current],
            "stage_name": _INGEST_STAGE_NAME[current],
            "epochs": run,
            # Always send minutes: without it the backend falls back to a
            # 30-second epoch that this Pod never uses.
            "minutes": round(run * epoch_seconds / 60.0, 1),
        })
        hypnogram.append({"s": _INGEST_STAGE_INDEX[current], "n": run})

    for sample in report_samples:
        stage = sample.get("sleep")
        if stage not in _INGEST_STAGE_INDEX:
            continue
        if stage == current:
            run += 1
            continue
        close()
        current, run = stage, 1
    close()
    return segments, hypnogram


def _ingest_environment(report_environment: Any) -> Dict[str, Any]:
    """Re-key the Pod's environment list into the object the backend reads.

    The backend promotes ``metric["avg"]`` to a numeric column and stores the
    rest of the object as-is, so ``avg`` is added beside the Pod's ``average``
    and every explanatory field (Thai label/target/status/action) is kept.
    """
    result: Dict[str, Any] = {}
    for metric in report_environment or []:
        if not isinstance(metric, dict):
            continue
        target_key = _INGEST_ENVIRONMENT_KEYS.get(metric.get("key"))
        if not target_key:
            continue
        # An unavailable sensor has no "average" at all; send an explicit null
        # so the shape stays uniform and the column simply stays empty.
        result[target_key] = dict(metric, avg=metric.get("average"))
    return result


def _build_ingest_payload(record: Dict[str, Any],
                          report_samples: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Return the account-backend upload body, or None when it does not apply."""
    if not (ZEEP_INGEST_API_KEY and ZEEP_INGEST_DEVICE_ID):
        return None
    # A local/offline Login has no ZEEP account to attach the night to; the
    # backend requires a uuid and would reject it on every retry forever.
    public_id = record.get("zeep_public_id")
    if not public_id:
        return None
    report = record.get("session_report")
    quality = record.get("sleep_quality")
    if not isinstance(report, dict) or not isinstance(quality, dict):
        return None
    if not record.get("started_at_utc") or not record.get("ended_at_utc"):
        return None

    stages = {
        str(entry.get("state")): entry
        for entry in report.get("stages") or [] if isinstance(entry, dict)
    }
    if not stages:
        return None
    sleep = report.get("sleep") or {}
    # _normalise_samples_for_report returns a millisecond GCD, so production
    # cadences (5 s / 10 s, mixed or not) are whole seconds and
    # total_epochs * epoch_seconds == total_scored_minutes exactly. The backend
    # column is an integer; floor it at 1 so corrupt sub-second metadata cannot
    # send a zero and stretch the hypnogram time base.
    epoch_seconds = _sample_interval_seconds(record.get("sample_interval_s"))
    epoch_seconds_sent = max(1, int(round(epoch_seconds)))
    segments, hypnogram = _ingest_stage_runs(report_samples, epoch_seconds)

    def minutes(state: str) -> Optional[float]:
        entry = stages.get(state) or {}
        value = entry.get("duration_s")
        return round(value / 60.0, 1) if isinstance(value, (int, float)) else None

    def seconds_to_minutes(value: Any) -> Optional[float]:
        return round(value / 60.0, 1) if isinstance(value, (int, float)) else None

    def vitals(summary_key: str) -> Dict[str, Any]:
        """Keep only the three statistics a reader needs; drop _series_stats' n."""
        series = ((record.get("summary") or {}).get(summary_key)) or {}
        return {key: series[key] for key in ("avg", "min", "max") if key in series}

    slim: Dict[str, Any] = {
        # sleep_score must be present: the backend skips a session with a null
        # score in every history statistic, not just in the average.
        "sleep_score": quality.get("score"),
        "sleep_efficiency": quality.get("sleep_efficiency_pct"),
        "epoch_seconds": epoch_seconds_sent,
        # Count the scored rounds the report itself used, so
        # total_epochs * epoch_seconds == total_scored_minutes holds.  The raw
        # sleep_state_counts also contains off_bed and legacy aliases that the
        # report drops, and would not reconcile.
        "total_epochs": sum(
            int(entry.get("samples") or 0) for entry in report.get("stages") or []
        ),
        "total_scored_minutes": seconds_to_minutes(sleep.get("actual_scored_s")),
        "total_sleep_minutes": seconds_to_minutes(sleep.get("estimated_sleep_s")),
        "wake_minutes": minutes("wake"),
        "n1_minutes": minutes("n1"),
        "n2_minutes": minutes("n2"),
        "n3_minutes": minutes("n3"),
        "rem_minutes": minutes("rem"),
        # All five use pct_scored (share of scored time, wake included) so the
        # row's percentages are one comparable set that totals 100. The
        # backend's light/deep columns describe a 4-level ontology and stay
        # empty rather than being filled from N2/N3, which are not the same
        # thing; stage_n1/n2/n3_pct is what carries the AASM detail instead.
        "wake_percent": (stages.get("wake") or {}).get("pct_scored"),
        "n1_percent": (stages.get("n1") or {}).get("pct_scored"),
        "n2_percent": (stages.get("n2") or {}).get("pct_scored"),
        "n3_percent": (stages.get("n3") or {}).get("pct_scored"),
        "rem_percent": (stages.get("rem") or {}).get("pct_scored"),
        "heart_rate": vitals("heart_rate_bpm"),
        # The account backend has no respiration column, so this rides along in
        # the scoring_result jsonb that the history detail returns verbatim.
        # BCG measures it every round beside HR; leaving it behind would drop
        # the one vital the Pod records that the account cannot show at all.
        "respiration_rate": vitals("respiration_rate"),
        "start": record["started_at_utc"],
        "segments": segments,
        "total_segments": len(segments),
        "hypnogram": hypnogram,
        "environment": _ingest_environment(report.get("environment")),
    }
    body: Dict[str, Any] = {
        "userPublicId": public_id,
        "deviceId": ZEEP_INGEST_DEVICE_ID,
        "externalSessionId": record["session_id"],
        "startedAt": record["started_at_utc"],
        "endedAt": record["ended_at_utc"],
        "record": slim,
    }
    if POD_TIMEZONE:
        body["timezone"] = POD_TIMEZONE
    return body


def _ingest_outbox_path(session_id: str) -> Path:
    # session_id is generated by this process (s-<utc>-<hex>) and never reaches
    # here from a request, but keep the filename to one path component anyway.
    return INGEST_OUTBOX_DIR / f"{Path(str(session_id)).name}.json"


def _write_ingest_outbox(entry: Dict[str, Any]) -> None:
    """Atomically persist one pending upload, mirroring the session checkpoint."""
    path = _ingest_outbox_path(entry["payload"]["externalSessionId"])
    with ingest_outbox_lock:
        INGEST_OUTBOX_DIR.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(entry, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)


def _clear_ingest_outbox(session_id: str) -> None:
    with ingest_outbox_lock:
        _ingest_outbox_path(session_id).unlink(missing_ok=True)


def _post_ingest_entry(entry: Dict[str, Any], *, timeout: Optional[float] = None) -> bool:
    """Send one queued upload. True = done (delivered or permanently rejected).

    Returns False only for a failure worth retrying, so a Pod that is merely
    offline keeps its night queued while a payload the backend refuses does not
    retry forever.
    """
    payload = entry["payload"]
    session_id = payload["externalSessionId"]
    entry["attempts"] = int(entry.get("attempts") or 0) + 1
    try:
        body = _zeep_request("POST", ZEEP_INGEST_PATH, json_body=payload,
                             api_key=ZEEP_INGEST_API_KEY, timeout=timeout)
    except ZeepApiOffline as exc:
        entry["last_error"] = str(exc)
        log_event("ingest", "deferred", session_id=session_id,
                  attempts=entry["attempts"], error=str(exc))
        return False
    except HTTPException as exc:
        detail = str(getattr(exc, "detail", exc))
        entry["last_error"] = detail
        status = getattr(exc, "status_code", 0)
        # A rejected payload or an unknown user/device will be rejected the same
        # way forever, so park it instead of retrying every sweep for the life
        # of the Pod. 401/403 are deliberately excluded: a rotated or mistyped
        # ZEEP_INGEST_API_KEY is fixed by an operator, and the queued nights
        # should then flush on their own rather than need unparking by hand.
        if 400 <= status < 500 and status not in (401, 403, 408, 429):
            entry["parked"] = True
            log_event("ingest", "rejected", session_id=session_id,
                      status=status, error=detail)
            return True
        log_event("ingest", "deferred", session_id=session_id,
                  attempts=entry["attempts"], status=status, error=detail)
        return False
    remote = (body.get("data") or {}) if isinstance(body, dict) else {}
    log_event("ingest", "uploaded", session_id=session_id,
              attempts=entry["attempts"], remote_id=remote.get("id"),
              remote_type=remote.get("type"), message=body.get("message"))
    return True


def _enqueue_session_ingest(record: Dict[str, Any],
                            report_samples: List[Dict[str, Any]]) -> None:
    """Best-effort upload of a finished Session; never fails finalization.

    The pending marker is written before the request so a power cut mid-upload
    leaves the night queued rather than lost.  Re-sending is free: the backend
    is idempotent on externalSessionId.
    """
    payload = _build_ingest_payload(record, report_samples)
    if payload is None:
        log_event("ingest", "skipped", session_id=record.get("session_id"),
                  configured=bool(ZEEP_INGEST_API_KEY and ZEEP_INGEST_DEVICE_ID),
                  zeep_account=bool(record.get("zeep_public_id")))
        return
    entry = {
        "schema_version": INGEST_OUTBOX_VERSION,
        "queued_at_utc": datetime.now(timezone.utc).isoformat(),
        "attempts": 0,
        "last_error": None,
        "parked": False,
        "payload": payload,
    }
    try:
        _write_ingest_outbox(entry)
    except OSError as exc:
        # Without a durable marker a failed upload could not be retried, so a
        # one-shot attempt is still better than nothing.
        log_event("ingest", "outbox_write_failed",
                  session_id=record.get("session_id"), error=str(exc))
    try:
        if (_post_ingest_entry(entry, timeout=ZEEP_INGEST_INLINE_TIMEOUT)
                and not entry.get("parked")):
            _clear_ingest_outbox(payload["externalSessionId"])
            return
        _write_ingest_outbox(entry)
    except Exception as exc:
        log_event("ingest", "upload_failed",
                  session_id=record.get("session_id"), error=str(exc))


def _sweep_ingest_outbox() -> None:
    """Retry every queued upload, oldest first. Safe to call at any time."""
    if not (ZEEP_INGEST_API_KEY and ZEEP_INGEST_DEVICE_ID):
        return
    try:
        pending = sorted(INGEST_OUTBOX_DIR.glob("*.json"),
                         key=lambda item: item.stat().st_mtime)
    except OSError:
        return
    for path in pending:
        try:
            with path.open("r", encoding="utf-8") as handle:
                entry = json.load(handle)
            if not isinstance(entry, dict) or not isinstance(entry.get("payload"), dict):
                raise ValueError("outbox entry is not a pending upload")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            log_event("ingest", "outbox_entry_invalid", file=path.name, error=str(exc))
            continue
        if entry.get("parked"):
            continue
        try:
            done = _post_ingest_entry(entry)
        except Exception as exc:
            log_event("ingest", "upload_failed", file=path.name, error=str(exc))
            continue
        try:
            if done and not entry.get("parked"):
                _clear_ingest_outbox(entry["payload"]["externalSessionId"])
            else:
                _write_ingest_outbox(entry)
        except OSError as exc:
            log_event("ingest", "outbox_write_failed", file=path.name, error=str(exc))
        if not done:
            # One unreachable backend means the rest will not go through
            # either; leave them for the next sweep instead of timing out once
            # per queued night.
            break


def ingest_outbox_sweeper() -> None:
    """Retry queued uploads periodically so a Pod that never reboots catches up."""
    while True:
        time.sleep(ZEEP_INGEST_SWEEP_SECONDS)
        try:
            _sweep_ingest_outbox()
        except Exception as exc:
            log_event("ingest", "sweep_failed", error=str(exc))


def _finalize_active_session(reason: str = "logout") -> Optional[Dict[str, Any]]:
    """Close the active session and persist its record. Returns None if idle."""
    global _active_session
    with session_lock:
        active = _active_session
        _active_session = None
    if active is None:
        return None
    record = active["record"]
    samples = active["samples"]
    acquisition_interval_s = _sample_interval_seconds(
        record.get("sample_interval_s"), SESSION_SAMPLE_SECONDS)
    report_samples, sample_interval_s, cadence_summary = (
        _normalise_samples_for_report(samples, acquisition_interval_s)
    )
    started_monotonic = record.pop("started_monotonic", None)
    never_recorded = started_monotonic is None
    duration = 0.0 if never_recorded else max(0.0, time.monotonic() - started_monotonic)
    if never_recorded:
        # Login/occupancy is not a recorded sleep Session. If the bed + fresh
        # HR/RR gate never passes, close only the Login lease/checkpoint and do
        # not create a zero-duration report, timeline, or personal baseline.
        vital_gate = session_vital_gate_now(active)
        record.update({
            "ended_at_utc": datetime.now(timezone.utc).isoformat(),
            "end_reason": (
                "not_recorded" if reason == "logout"
                else f"{reason}_not_recorded"
            ),
            "duration_s": 0.0,
            "samples": [],
            "recording_started": False,
            "start_gate": vital_gate,
        })
        _clear_active_session_checkpoint()
        log_event(
            "session", "closed_without_recording",
            session_id=record["session_id"], user=record["username"],
            reason=record["end_reason"], gate_reason=vital_gate["reason"],
        )
        lease = active.get("occupancy_lease")
        if lease is not None:
            try:
                occupancy_client.release(lease)
            except (CoordinatorUnavailable, OccupancyConflict) as exc:
                log_event(
                    "occupancy", "lease_release_deferred",
                    session_id=record["session_id"], pod_id=POD_ID, error=str(exc),
                )
        refresh_token = (active.get("auth") or {}).get("refresh_token")
        if refresh_token:
            try:
                _zeep_request(
                    "POST", "/v1/auth/logout",
                    json_body={"refreshToken": refresh_token},
                )
            except (ZeepApiOffline, HTTPException) as exc:
                log_event(
                    "auth", "zeep_logout_failed", user=record["username"],
                    error=str(getattr(exc, "detail", exc)),
                )
        with state_lock:
            state["session"].update({
                "active": False, "username": None, "account_key": None,
                "email": None, "display_name": None, "auth_source": None,
                "gender": None, "age": None, "age_group": None,
                "health_reference": None, "rest_mode": None,
                "session_id": None, "started_at": None, "samples": 0,
                "recording": False, "bed_wait_s": 0,
                "vital_gate": {
                    "ready": False,
                    "heart_rate_valid": False,
                    "respiration_rate_valid": False,
                    "confirmed_packets": 0,
                    "required_packets": SESSION_VITAL_START_PACKETS,
                    "reason": "no_session",
                },
            })
        _reset_live_sleep_inference(None)
        return record
    bed_counts: Dict[str, int] = {}
    sleep_counts: Dict[str, int] = {}
    for smp in report_samples:
        if smp.get("bed"):
            bed_counts[smp["bed"]] = bed_counts.get(smp["bed"], 0) + 1
        if smp.get("sleep"):
            sleep_counts[smp["sleep"]] = sleep_counts.get(smp["sleep"], 0) + 1
    estimator_versions = Counter(
        smp.get("sleep_estimator_version") for smp in samples
        if smp.get("sleep_estimator_version")
    )
    latest_estimator_version = next(
        (smp.get("sleep_estimator_version") for smp in reversed(samples)
         if smp.get("sleep_estimator_version")),
        SLEEP_ESTIMATOR_VERSION,
    )
    record.update({
        "ended_at_utc": datetime.now(timezone.utc).isoformat(),
        "end_reason": reason,
        "duration_s": round(duration, 1),
        "sample_interval_s": sample_interval_s,
        "sensor_sample_interval_s": acquisition_interval_s,
        "sample_cadence_segments": record.get("sample_cadence_segments") or [],
        "sample_cadence_summary": cadence_summary,
        "samples": samples,
        "summary": {
            # Mixed-cadence rows are expanded only for calculation so these are
            # time-weighted statistics; ``record['samples']`` stays raw/auditable.
            "temperature_c": _series_stats([s["temp"] for s in report_samples]),
            "humidity_rh": _series_stats([s["hum"] for s in report_samples]),
            "sound_dba_est": _series_stats([s["dba"] for s in report_samples]),
            "lux": _series_stats([s["lux"] for s in report_samples]),
            "heart_rate_bpm": _series_stats([s["hr"] for s in report_samples]),
            "respiration_rate": _series_stats([s["rr"] for s in report_samples]),
            "bed_status_counts": bed_counts,
            "sleep_state_counts": sleep_counts,
        },
        "sleep_estimator": latest_estimator_version,
        "sleep_estimator_versions": dict(estimator_versions),
        "sleep_provenance_complete": bool(samples) and sum(estimator_versions.values()) == len(samples),
        "sleep_evidence_version": SLEEP_EVIDENCE_VERSION,
        "sleep_baseline_version": ZEEP_SLEEP_BASELINE_VERSION,
        "sleep_transition_policy": ZEEP_SLEEP_TRANSITION_POLICY_VERSION,
        "sleep_g2_ontology": SLEEP_G2_ONTOLOGY_VERSION,
        "terminal_wake_policy": TERMINAL_WAKE_POLICY_VERSION,
        "counters": active["counters"],
    })
    # The final visible sequence must close the human episode as
    # ``... -> Wake -> occupancy/Session end``.  This is an operational
    # boundary from the explicit End action or a confirmed terminal bed exit,
    # not a manufactured AASM epoch, so it is kept out of all stage totals.
    terminal_occupancy = terminal_occupancy_timeline(
        samples,
        session_end=record["ended_at_utc"],
        sample_interval_s=_sample_interval_seconds(
            samples[-1].get("sample_interval_s") if samples else None,
            acquisition_interval_s,
        ),
    )
    terminal_wake = terminal_wake_transition(
        ({"state": sample.get("sleep")} for sample in samples),
        terminal_occupancy=terminal_occupancy,
        session_end=record["ended_at_utc"],
        end_reason=reason,
    )
    record["terminal_wake_transition"] = terminal_wake
    # SQLite เป็น source of truth แล้ว — ไม่เขียน sessions.jsonl อีก
    # (กัน migration ตอน boot นำเข้าซ้ำ); ข้อมูลส่วนที่ schema ไม่มีคอลัมน์
    # (bed/sleep counts + estimator version) เก็บเป็น event 'final_summary'
    bcg_storage.end_session(record["session_id"])
    # night summary (proxy จาก per-sample sleep state) — ป้อน baseline ส่วนบุคคล
    sleep_like = {"n1", "n2", "n3", "rem", "nrem_light", "nrem_deep"}
    onset_proxy_s = None
    awakenings = 0
    asleep = False
    sleep_started = False
    waso_samples = 0
    try:
        started_epoch = datetime.fromisoformat(record["started_at_utc"]).timestamp()
    except (TypeError, ValueError):
        started_epoch = None
    for smp in report_samples:
        st = smp.get("sleep")
        if st in sleep_like:
            if onset_proxy_s is None and started_epoch:
                onset_proxy_s = round(max(0.0, smp["t"] - started_epoch), 1)
            asleep = True
            sleep_started = True
        elif st in ("wake", "off_bed"):
            if sleep_started:
                waso_samples += 1
            if asleep:
                awakenings += 1
                asleep = False
    total_sleep_samples = sum(
        v for k, v in record["summary"]["sleep_state_counts"].items() if k in sleep_like)
    total_scored = total_sleep_samples + record["summary"]["sleep_state_counts"].get("wake", 0)
    night_summary = {
        "sleep_onset_proxy_s": onset_proxy_s,
        "awakenings": awakenings,
        "waso_proxy_s": round(waso_samples * sample_interval_s, 1),
        "estimated_sleep_s": round(min(duration, total_sleep_samples * sample_interval_s), 1),
        "sleep_efficiency": (round(total_sleep_samples / total_scored, 3)
                             if total_scored else None),
        "deep_ratio": (round((record["summary"]["sleep_state_counts"].get("n3", 0)
                              + record["summary"]["sleep_state_counts"].get("nrem_deep", 0))
                             / total_sleep_samples, 3) if total_sleep_samples else None),
        "rem_ratio": (round(record["summary"]["sleep_state_counts"].get("rem", 0)
                            / total_sleep_samples, 3) if total_sleep_samples else None),
    }
    # Sleep quality exists only after finalization and is persisted beside the
    # raw factors so history can reproduce and explain the same result later.
    sleep_quality = _sleep_quality_summary(
        record["duration_s"], night_summary,
        record["summary"]["sleep_state_counts"], completed=True,
        rest_mode=record.get("rest_mode") or "auto",
        stage_sequence=report_samples,
        sensor_samples=report_samples,
        sample_interval_s=sample_interval_s,
    )
    night_summary["sleep_quality"] = sleep_quality
    night_summary["wellness_score"] = sleep_quality.get("score")
    record["sleep_quality"] = sleep_quality
    session_report = build_session_report(
        record["duration_s"], report_samples, night_summary,
        record["summary"]["sleep_state_counts"], sleep_quality,
        rest_mode=record.get("rest_mode") or "auto",
        sample_interval_s=sample_interval_s,
        estimator_version=record.get("sleep_estimator"), completed=True,
        timeline_schema_version=SESSION_TIMELINE_SCHEMA_VERSION,
    )
    record["session_report"] = session_report
    if terminal_wake:
        database.enqueue("sessions", "event", {
            "session_id": record["session_id"],
            "timestamp": terminal_wake["start_time"],
            "type": "session_terminal_wake",
            "value": terminal_wake,
        })
    database.enqueue("sessions", "event", {
        "session_id": record["session_id"],
        "timestamp": record["ended_at_utc"],
        "type": "final_summary",
        "value": {
            "bed_status_counts": record["summary"]["bed_status_counts"],
            "sleep_state_counts": record["summary"]["sleep_state_counts"],
            "sleep_estimator": record.get("sleep_estimator"),
            "sleep_estimator_versions": record.get("sleep_estimator_versions") or {},
            "sleep_provenance_complete": record.get("sleep_provenance_complete", False),
            "sleep_evidence_version": record.get("sleep_evidence_version"),
            "sleep_baseline_version": record.get("sleep_baseline_version"),
            "sleep_transition_policy": record.get("sleep_transition_policy"),
            "sleep_g2_ontology": record.get("sleep_g2_ontology"),
            "terminal_wake_policy": record.get("terminal_wake_policy"),
            "rest_mode": record.get("rest_mode") or "auto",
            "sample_interval_s": sample_interval_s,
            "sensor_sample_interval_s": acquisition_interval_s,
            "timeline_schema_version": SESSION_TIMELINE_SCHEMA_VERSION,
            "sample_cadence_segments": record.get("sample_cadence_segments") or [],
            "sample_cadence_summary": cadence_summary,
            # Snapshot the non-diagnostic Profile context used during this
            # Session so later account edits do not rewrite historical reports.
            "health_reference": record.get("health_reference") or {},
            # Optional, consented lifestyle context is frozen separately from
            # physiology. It may explain/report a Session but cannot create or
            # modify W/N1/N2/N3/REM.
            "wellness_context": record.get("wellness_context"),
            "counters": record["counters"],
            "armed_at_utc": record.get("armed_at_utc"),
            "bed_start_s": BED_START_SECONDS,
            "night_summary": night_summary,
            "session_report": session_report,
            "terminal_wake_transition": terminal_wake,
        },
    })
    database.enqueue("sessions", "session_end", {
        "session_id": record["session_id"], "end_time": record["ended_at_utc"],
        "duration": record["duration_s"], "note": record.get("note"),
        "end_reason": reason,
    })
    if not database.flush(30):
        raise RuntimeError("database writer did not flush before session finalization")
    # Explicit User/Admin completion is the only point that clears restart
    # recovery. Service stop/restart deliberately leaves this file intact.
    _clear_active_session_checkpoint()
    log_event("session", "logout", session_id=record["session_id"],
              user=record["username"], duration_s=record["duration_s"],
              samples=len(samples), reason=reason)
    lease = active.get("occupancy_lease")
    if lease is not None:
        try:
            occupancy_client.release(lease)
            log_event("occupancy", "lease_released", session_id=record["session_id"],
                      pod_id=POD_ID)
        except (CoordinatorUnavailable, OccupancyConflict) as exc:
            # The lease expires automatically; never lose a completed sleep
            # record merely because the coordinator is temporarily offline.
            log_event("occupancy", "lease_release_deferred", session_id=record["session_id"],
                      pod_id=POD_ID, error=str(exc))
    # เพิกถอน refresh token family ฝั่ง ZEEP เพื่อไม่ให้ session ของตู้ค้างอยู่ใน
    # บัญชีผู้ใช้. best-effort: เน็ตหลุดตอน logout ต้องไม่ทำให้บันทึกผลไม่สำเร็จ
    # (DB flush ผ่านไปแล้วก่อนถึงจุดนี้)
    refresh_token = (active.get("auth") or {}).get("refresh_token")
    if refresh_token:
        try:
            _zeep_request("POST", "/v1/auth/logout",
                          json_body={"refreshToken": refresh_token})
        except (ZeepApiOffline, HTTPException) as exc:
            log_event("auth", "zeep_logout_failed", user=record["username"],
                      error=str(getattr(exc, "detail", exc)))
    # ส่งผลการนอนขึ้นบัญชีผู้ใช้ — best-effort เหมือน logout ด้านบน: ทำหลัง DB
    # flush เสมอ และถ้าเน็ตหลุดจะคิวไว้ใน outbox ให้ยิงซ้ำ (backend idempotent
    # ด้วย externalSessionId). ใช้ x-api-key จึงไม่พึ่ง token ของผู้ใช้ —
    # Session ที่กู้คืนหลัง restart (ไม่มี auth) ก็อัปโหลดได้ตามปกติ
    _enqueue_session_ingest(record, report_samples)
    # Adaptive learning: อัปเดต baseline ส่วนบุคคลจากคืนล่าสุด (≤7 คืน rolling)
    try:
        bl = baselines.update_user(record["username_key"])
        log_event("ai", "baseline_updated", user=record["username"],
                  status=bl.get("status"), nights=bl.get("nights_used"))
    except Exception as exc:
        log_event("ai", "baseline_update_failed", user=record["username"],
                  error=str(exc))
    with profile_lock:
        profiles = _load_profiles()
        profile = profiles.get(record["username_key"])
        if profile is not None:
            profile["sessions"] = int(profile.get("sessions", 0)) + 1
            profile["last_session_utc"] = record["ended_at_utc"]
            _save_profiles(profiles)
    with state_lock:
        state["session"].update({
            "active": False, "username": None, "account_key": None,
            "email": None, "display_name": None,
            "auth_source": None, "gender": None, "age": None, "age_group": None,
            "health_reference": None,
            "rest_mode": None,
            "session_id": None, "started_at": None, "samples": 0,
            "recording": False, "bed_wait_s": 0,
            "vital_gate": {
                "ready": False,
                "heart_rate_valid": False,
                "respiration_rate_valid": False,
                "confirmed_packets": 0,
                "required_packets": SESSION_VITAL_START_PACKETS,
                "reason": "no_session",
            },
        })
    _reset_live_sleep_inference(None)
    return record


def _restore_waiting_session(checkpoint: Dict[str, Any]) -> Optional[str]:
    """Restore a logged-in occupant before bed confirmation/DB Session start."""
    global _active_session
    record = dict(checkpoint["record"])
    session_id = record["session_id"]
    with profile_lock:
        profiles = _load_profiles()
        profile = profiles.get(record["username_key"], {})
    age = record.get("age") if record.get("age") is not None else profile.get("age")
    age_group = (
        record.get("age_group") or profile.get("age_group") or _age_group(age)
    )
    health_reference = record.get("health_reference")
    if not isinstance(health_reference, dict) or health_reference.get("schema_version") != 1:
        health_reference = _health_reference_from_profile(profile)
    identity_subject = record["identity_subject"]
    restored_lease: Optional[OccupancyLease] = None
    occupancy_error: Optional[str] = None
    try:
        restored_lease = occupancy_client.acquire(
            subject=identity_subject,
            pod_id=record.get("pod_id") or POD_ID,
            pod_session_id=session_id,
            username=record["username"],
        )
    except (CoordinatorUnavailable, OccupancyConflict) as exc:
        # A restart must not evict an already authenticated occupant merely
        # because the shared coordinator is temporarily unreachable.
        occupancy_error = getattr(exc, "reason", None) or str(exc)

    record.update({
        "age": age,
        "age_group": age_group,
        "health_reference": health_reference,
        "rest_mode": record.get("rest_mode") or "auto",
        "sample_interval_s": _sample_interval_seconds(
            record.get("sample_interval_s"), SESSION_SAMPLE_SECONDS),
        "started_at_utc": None,
        "started_monotonic": None,
    })
    with state_lock:
        vital_gate_start_packet_count = int(
            state["sensor"]["bcg"].get("packets") or 0
        )
    restored = {
        "record": record,
        "auth": None,
        "owner_auth_session_id": checkpoint.get("owner_auth_session_id"),
        "occupancy_lease": restored_lease,
        "occupancy_error": occupancy_error,
        "last_lease_renew": time.monotonic(),
        "samples": [], "counters": {},
        "last_sample": float("-inf"), "phase": "waiting_bed",
        # Re-check the complete BED_START_SECONDS after boot because the Pi
        # cannot verify whether the person stayed on the bed while offline.
        "onbed_since": None,
        "vital_gate_start_packet_count": vital_gate_start_packet_count,
    }
    with session_lock:
        if _active_session is not None:
            return None
        _active_session = restored
    _reset_live_sleep_inference(session_id)
    try:
        _save_active_session_checkpoint(restored)
    except Exception as exc:
        log_event("session", "restart_checkpoint_refresh_failed", error=str(exc))
    armed_at = record.get("armed_at_utc")
    try:
        armed_epoch = datetime.fromisoformat(armed_at).timestamp() if armed_at else time.time()
    except (TypeError, ValueError):
        armed_epoch = time.time()
    vital_gate = session_vital_gate_now(restored)
    with state_lock:
        state["session"].update({
            "active": True, "username": record["username"],
            "account_key": record["username_key"],
            "email": profile.get("email") or profile.get("zeep_email"),
            "gender": record.get("gender"),
            "display_name": profile.get("display_name") or record["username"],
            "auth_source": record.get("auth_source") or (
                "zeep" if record.get("zeep_public_id") else "local"
            ),
            "age": age, "age_group": age_group,
            "health_reference": health_reference, "session_id": session_id,
            "rest_mode": record.get("rest_mode") or "auto",
            "started_at": armed_epoch, "samples": 0,
            "recording": False, "bed_wait_s": 0,
            "vital_gate": vital_gate,
        })
    log_event(
        "session", "login_restored_after_restart",
        session_id=session_id, user=record["username"], phase="waiting_bed",
        owner_login_restored=bool(checkpoint.get("owner_auth_session_id")),
        occupancy_error=occupancy_error,
    )
    return session_id


def _restore_interrupted_session() -> Optional[str]:
    """Resume the newest session that has no explicit user logout.

    Supports both the new open-row shutdown behavior and one-time migration from
    the previous release, which closed a row with end_reason=server_shutdown.
    """
    global _active_session
    checkpoint = _load_active_session_checkpoint()
    rows: List[Dict[str, Any]] = []
    if checkpoint is not None:
        checkpoint_record = checkpoint["record"]
        checkpoint_rows = database.read_sessions(
            "SELECT * FROM sessions WHERE session_id=? LIMIT 1",
            (checkpoint_record["session_id"],),
        )
        checkpoint_row = checkpoint_rows[0] if checkpoint_rows else None
        explicitly_ended = bool(
            checkpoint_row
            and checkpoint_row.get("end_time") is not None
            and checkpoint_row.get("end_reason") != "server_shutdown"
        )
        if explicitly_ended:
            # A crash after final DB commit but before unlink must never reopen
            # a Session that the User/Admin explicitly completed.
            _clear_active_session_checkpoint()
            log_event(
                "session", "stale_restart_checkpoint_removed",
                session_id=checkpoint_record["session_id"],
                end_reason=checkpoint_row.get("end_reason"),
            )
            checkpoint = None
        elif checkpoint.get("phase") == "waiting_bed" and checkpoint_row is None:
            return _restore_waiting_session(checkpoint)
        elif checkpoint_row is not None:
            # Reconcile the narrow crash window after DB session_start commits
            # but before the checkpoint flips from waiting_bed to recording.
            checkpoint["phase"] = "recording"
            checkpoint_record["started_at_utc"] = checkpoint_row["start_time"]
            rows = [checkpoint_row]
        else:
            _clear_active_session_checkpoint()
            checkpoint = None
    if not rows:
        rows = database.read_sessions(
            """SELECT * FROM sessions
               WHERE end_time IS NULL OR end_reason='server_shutdown'
               ORDER BY start_time DESC LIMIT 1"""
        )
    if not rows:
        return None
    row = rows[0]
    session_id = row["session_id"]
    was_legacy_closed = row.get("end_reason") == "server_shutdown"
    timeline = database.read_sessions(
        """SELECT * FROM timeline WHERE session_id=? ORDER BY timestamp
           LIMIT ?""",
        (session_id, SESSION_SAMPLE_LIMIT),
    )
    checkpoint_record = checkpoint["record"] if checkpoint is not None else {}
    restored_sample_interval_s = _sample_interval_seconds(
        checkpoint_record.get("sample_interval_s"),
        _timeline_sample_interval(timeline, 5.0),
    )
    migration_at_utc = datetime.now(timezone.utc).isoformat()
    cadence_segments = _normalise_cadence_segments(
        checkpoint_record.get("sample_cadence_segments"),
        start_at_utc=row["start_time"],
        fallback_interval_s=restored_sample_interval_s,
    )
    previous_live_interval_s = (
        _sample_interval_seconds(
            cadence_segments[-1].get("sample_interval_s"),
            restored_sample_interval_s,
        )
        if cadence_segments else restored_sample_interval_s
    )
    cadence_upgraded = not math.isclose(
        previous_live_interval_s, SESSION_SAMPLE_SECONDS,
        rel_tol=0.0, abs_tol=0.001,
    )
    if cadence_upgraded:
        cadence_segments.append({
            "start_at_utc": migration_at_utc,
            "sample_interval_s": SESSION_SAMPLE_SECONDS,
        })
    samples = [{
        "t": datetime.fromisoformat(x["timestamp"]).timestamp(),
        "temp": x.get("temperature"), "hum": x.get("humidity"),
        "co2": x.get("co2"), "lux": x.get("lux"), "dba": x.get("sound"),
        "hr": x.get("heart_rate"), "rr": x.get("respiration_rate"),
        "bed": x.get("bed_status"), "sleep": None,
        "sample_interval_s": _cadence_interval_at(
            datetime.fromisoformat(x["timestamp"]).timestamp(),
            cadence_segments,
            restored_sample_interval_s,
        ),
    } for x in timeline]
    event_rows = database.read_sessions(
        "SELECT type,COUNT(*) AS n FROM events WHERE session_id=? AND type!='final_summary' GROUP BY type",
        (session_id,),
    )
    counters = {x["type"]: int(x["n"]) for x in event_rows}
    stage_events = database.read_sessions(
        "SELECT timestamp,value FROM events WHERE session_id=? AND type='sleep_stage' ORDER BY timestamp",
        (session_id,),
    )
    # Restore the already classified windows as well as their raw Sensor rows.
    # Without this mapping a service update would retain Timeline data but make
    # the pre-restart portion disappear from TST/stage percentages at Logout.
    for event in stage_events:
        try:
            value = (
                json.loads(event["value"])
                if isinstance(event.get("value"), str)
                else event.get("value", {})
            )
            stage = value.get("state")
            if stage not in {"wake", "n1", "n2", "n3", "rem"}:
                continue
            end_text = value.get("window_end") or event.get("timestamp")
            end_epoch = datetime.fromisoformat(str(end_text)).timestamp()
            try:
                start_epoch = datetime.fromisoformat(
                    str(value.get("window_start"))).timestamp()
            except (TypeError, ValueError):
                start_epoch = end_epoch - _sample_interval_seconds(
                    value.get("sample_interval_s"), SLEEP_EVIDENCE_EPOCH_SECONDS)
            for sample in samples:
                if start_epoch < float(sample["t"]) <= end_epoch + 0.001:
                    sample.update({
                        "sleep": stage,
                        "sleep_confirmed_state": stage,
                        "sleep_estimator_version": value.get("estimator_version"),
                        "sleep_evidence_version": value.get("evidence_version"),
                        "sleep_confidence": value.get("confidence"),
                        "sleep_probability": (value.get("probabilities") or {}).get(stage),
                    })
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
    with sleep_path_lock:
        _reset_sleep_stage_path(session_id)
        for event in stage_events:
            try:
                value = json.loads(event["value"]) if isinstance(event.get("value"), str) else event.get("value", {})
                stage = value.get("state")
                if stage in {"wake", "n1", "n2", "n3", "rem"}:
                    _apply_stage_to_path(stage)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
    started_dt = datetime.fromisoformat(row["start_time"])
    elapsed_s = max(0.0, time.time() - started_dt.timestamp())
    with profile_lock:
        profiles = _load_profiles()
        profile = profiles.get(row["username_key"], {})
        age = (checkpoint_record.get("age")
               if checkpoint_record.get("age") is not None else profile.get("age"))
        age_group = (checkpoint_record.get("age_group")
                     or profile.get("age_group") or _age_group(age))
        health_reference = checkpoint_record.get("health_reference")
        if not isinstance(health_reference, dict) or health_reference.get("schema_version") != 1:
            health_reference = _health_reference_from_profile(profile)
        if was_legacy_closed and profile:
            profile["sessions"] = max(0, int(profile.get("sessions", 0)) - 1)
            profiles[row["username_key"]] = profile
            _save_profiles(profiles)
    identity_subject = (
        checkpoint_record.get("identity_subject")
        or row.get("identity_subject")
        or (f"zeep:{row['zeep_public_id']}" if row.get("zeep_public_id") else f"legacy:{row['username_key']}")
    )
    restored_lease: Optional[OccupancyLease] = None
    occupancy_error: Optional[str] = None
    try:
        restored_lease = occupancy_client.acquire(
            subject=identity_subject,
            pod_id=row.get("pod_id") or POD_ID,
            pod_session_id=session_id,
            username=row["user"],
        )
    except (CoordinatorUnavailable, OccupancyConflict) as exc:
        # Recovery is occupant-first: keep local monitoring/recording alive and
        # surface a DEGRADED lease state for the administrator to resolve.
        occupancy_error = getattr(exc, "reason", None) or str(exc)

    _active_session = {
        "record": {
            "session_id": session_id, "username": row["user"],
            "username_key": row["username_key"], "gender": row.get("gender"),
            "age": age, "age_group": age_group,
            "health_reference": health_reference,
            "armed_at_utc": checkpoint_record.get("armed_at_utc") or row["created_at"],
            # Old/open rows predate explicit intent storage; auto is resolved
            # later from the amount of actual Sleep State data.
            "rest_mode": checkpoint_record.get("rest_mode") or "auto",
            "auth_source": checkpoint_record.get("auth_source") or (
                "zeep" if row.get("zeep_public_id") else "local"
            ),
            "started_at_utc": row["start_time"],
            "started_monotonic": time.monotonic() - elapsed_s,
            # New samples use the active 10-second contract. Historical rows
            # retain their segment-specific interval for the final report.
            "sample_interval_s": SESSION_SAMPLE_SECONDS,
            "sample_cadence_segments": cadence_segments,
            "identity_subject": identity_subject,
            "pod_id": row.get("pod_id") or POD_ID,
            "zeep_public_id": row.get("zeep_public_id"),
        },
        "auth": None,
        "owner_auth_session_id": (
            checkpoint.get("owner_auth_session_id") if checkpoint is not None else None
        ),
        "occupancy_lease": restored_lease,
        "occupancy_error": occupancy_error,
        "last_lease_renew": time.monotonic(),
        "samples": samples, "counters": counters,
        "last_sample": float("-inf"), "phase": "recording", "onbed_since": None,
    }
    if was_legacy_closed:
        database.enqueue("sessions", "session_resume", {"session_id": session_id})
        if not database.flush(30):
            raise RuntimeError("database writer did not flush session resume")
    bcg_storage.start_session(session_id)
    with state_lock:
        state["session"].update({
            "active": True, "username": row["user"],
            "account_key": row["username_key"],
            "email": profile.get("email") or profile.get("zeep_email"),
            "gender": row.get("gender"),
            "display_name": profile.get("display_name") or row["user"],
            "auth_source": checkpoint_record.get("auth_source") or (
                "zeep" if row.get("zeep_public_id") else "local"
            ),
            "age": age, "age_group": age_group,
            "health_reference": health_reference, "session_id": session_id,
            "rest_mode": checkpoint_record.get("rest_mode") or "auto",
            "started_at": started_dt.timestamp(), "samples": len(samples),
            "recording": True, "bed_wait_s": 0,
            "vital_gate": {
                "ready": True,
                "heart_rate_valid": None,
                "respiration_rate_valid": None,
                "confirmed_packets": SESSION_VITAL_START_PACKETS,
                "required_packets": SESSION_VITAL_START_PACKETS,
                "reason": "recording_resumed",
            },
        })
    log_event("session", "resumed_after_restart", session_id=session_id,
              user=row["user"], samples=len(samples), legacy_closed=was_legacy_closed,
              owner_login_restored=bool(
                  checkpoint and checkpoint.get("owner_auth_session_id")
              ), occupancy_error=occupancy_error)
    if cadence_upgraded:
        log_event(
            "session", "sample_cadence_upgraded",
            session_id=session_id,
            previous_sample_interval_s=previous_live_interval_s,
            sample_interval_s=SESSION_SAMPLE_SECONDS,
            historical_samples=len(samples),
            effective_at_utc=migration_at_utc,
        )
    try:
        _save_active_session_checkpoint(_active_session)
    except Exception as exc:
        log_event("session", "restart_checkpoint_refresh_failed", error=str(exc))
    return session_id


@asynccontextmanager
async def lifespan(_: FastAPI):
    log_event("system", "start", gpio=gpio.ready, player=player.backend)
    with state_lock:
        state["system"]["occupancy"] = occupancy_client.health()
    database.initialize()
    try:
        result = migrate_jsonl(database, SESSIONS_PATH)
        if result["status"] == "migrated":
            log_event("db", "migrated_jsonl", imported=result["imported"],
                      backup=str(result["backup"]))
    except Exception as exc:
        # Never rename or discard the legacy file on a failed migration.
        log_event("db", "migration_skipped", error=str(exc))
    try:
        account_mapping = _migrate_profiles_to_email_keys()
        if account_mapping:
            migrated_sessions = database.rekey_session_accounts(account_mapping)
            migrated_baselines = baselines.rekey_users(account_mapping)
            migrated_auth = auth_sessions.rekey_account_keys(account_mapping)
            log_event(
                "db", "account_keys_migrated_to_email",
                profiles=len(account_mapping), sessions=migrated_sessions,
                baselines=migrated_baselines, browser_sessions=migrated_auth,
            )
    except Exception as exc:
        # Identity migration is additive/re-keying only. Keep the original
        # records available if one local file is malformed and surface it to Admin.
        log_event("db", "account_key_migration_failed", error=str(exc))
    database.start()
    try:
        _restore_interrupted_session()
    except Exception as exc:
        log_event("session", "restart_resume_failed", error=str(exc))
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
    # Restart/power cycle is not a logout: keep the DB row open for recovery.
    with session_lock:
        active = _active_session
    if active is not None:
        try:
            _save_active_session_checkpoint(active)
        except Exception as exc:
            log_event("session", "restart_checkpoint_save_failed", error=str(exc))
        # waiting_bed deliberately has no sessions.db row yet, so an event
        # would violate its foreign key. The checkpoint alone restores Login.
        if active.get("phase") == "recording":
            database.enqueue("sessions", "event", {
                "session_id": active["record"]["session_id"],
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "type": "service_pause", "value": {"reason": "server_shutdown"},
            })
        database.flush(30)
    player.stop()
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
    # JavaScript reads only this random CSRF value; the authentication cookie
    # itself remains HttpOnly and is never accessible to frontend code.
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
app.include_router(create_history_router(database, require_admin=require_admin))
app.include_router(create_occupancy_router(occupancy_store, OCCUPANCY_COORDINATOR_TOKEN))
app.include_router(create_api_v1_router(
    require_pod_operator=require_pod_operator,
    require_admin=require_admin,
    snapshot_for=snapshot_for,
    public_status=lambda: public_status(),
    sensor_contract_snapshot=sensor_contract_snapshot,
    sleep_policy_snapshot=sleep_policy_snapshot,
    maintenance_contract_snapshot=maintenance_contract_snapshot,
))


def _require_username_access(username: str, principal: Principal) -> str:
    """Authorize one canonical account key (email for a ZEEP user)."""
    key = _normalize_account_key(username)
    if not principal.is_admin and key != principal.account_key:
        # Compatibility for a tablet that still has the pre-migration page in
        # memory. Resolve only aliases recorded on this same authenticated
        # Profile; arbitrary cross-account usernames remain forbidden.
        with profile_lock:
            profile = _load_profiles().get(principal.account_key) or {}
        aliases = {
            str(value).strip().casefold()
            for value in (profile.get("legacy_account_keys") or []) if value
        }
        aliases.add(str(profile.get("username") or "").strip().casefold())
        if key not in aliases:
            raise HTTPException(403, "ดูข้อมูลการนอนของบัญชีอื่นไม่ได้")
        key = principal.account_key
    return key


@app.get("/api/baseline/{username}")
def api_baseline(username: str, principal: Principal = Depends(require_user)):
    """Baseline ส่วนบุคคล + คำแนะนำ (advisory เท่านั้น — คนตัดสินใจ/กดปุ่มเอง)"""
    key = _require_username_access(username, principal)
    record = baselines.get(key) or {"status": "no_data", "nights_used": 0,
                                    "min_nights": 3}
    return {
        "username": username,
        "baseline": record,
        "recommendations": baselines.recommendations(key),
        "guardrail": ("ระบบเรียนรู้/แนะนำ/ปรับเกณฑ์การอ่านค่าเท่านั้น — "
                      "ไม่สั่งอุปกรณ์อัตโนมัติจาก sleep state ก่อนผ่าน G2 "
                      "(docs/closed-loop-spec.md)"),
    }


@app.get("/api/bcg/trend", dependencies=[Depends(require_user)])
async def bcg_trend(minutes: int = 10):
    """แนวโน้ม HR/RR/การขยับ/บนเตียง แบบ bucket ละ 5 วิ"""
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
            buckets.append({"t": start + i * bucket_s, "hr": None, "rr": None,
                            "move": None, "onbed": None})
            continue
        hrs = [f["hr"] for f in fs if f["hr"]]
        rrs = [f["rr"] for f in fs if f["rr"]]
        buckets.append({
            "t": start + i * bucket_s,
            "hr": round(sum(hrs) / len(hrs), 1) if hrs else None,
            "rr": round(sum(rrs) / len(rrs), 1) if rrs else None,
            "move": round(sum(1 for f in fs if f["status"] == 2) / len(fs), 2),
            "onbed": any(f["status"] in ON_BED_CODES for f in fs),
        })
    return {"bucket_s": bucket_s, "minutes": minutes, "buckets": buckets,
            "sleep": sleep_state_cached()}


@app.get("/api/bcg/raw", dependencies=[Depends(require_admin)])
async def bcg_raw(limit: int = 12):
    """Recent byte-exact LSM-800-T packets for the developer monitor."""
    limit = max(1, min(100, int(limit)))
    with history_lock:
        packets = list(bcg_raw_history)[-limit:]
    return {"frame_bytes": 66, "count": len(packets), "packets": packets}


class SensorBiasCommand(BaseModel):
    metric: str
    bias: float
    reference_value: Optional[float] = None


def sensor_calibration_inspector_snapshot() -> Dict[str, Any]:
    """Build the Admin-only Raw → Bias → Calibrated comparison table."""
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
        raw_value = (
            hub1.get(spec.get("raw_field"))
            if spec.get("raw_field") else raw_values.get(metric)
        )
        channel_meta = metadata.get(metric) or {}
        channels.append({
            "metric": metric,
            "device": spec["device"],
            "device_key": spec["device_key"],
            "label": spec["label"],
            "unit": spec["unit"],
            "raw_unit": spec.get("raw_unit", spec["unit"]),
            "raw": raw_value,
            "bias": sensor_bias_value(metric),
            "bias_label": spec.get("bias_label", "additive bias"),
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
        })

    # These algorithm-owned values are inspected beside the adjustable
    # channels, but are intentionally not offset in software. SGP40 learns its
    # own 24-hour baseline; BCG summary bytes feed the physiology estimator.
    sgp = devices.get("sgp40") or {}
    channels.extend([
        {
            "metric": "voc_index", "device": "SGP40", "device_key": "sgp40",
            "label": "VOC Index", "unit": "index", "raw": raw_values.get("voc_index"),
            "bias": 0.0, "calibrated": environment.get("voc_index"), "editable": False,
            "source": sgp.get("source_label"), "status": sgp.get("status", "offline"),
            "data_age_s": sgp.get("data_age_s"),
            "lock_reason": "Adaptive Baseline ของ SGP40 — ไม่ควรบวก offset ด้วยมือ",
        },
        {
            "metric": "sgp40_raw", "device": "SGP40", "device_key": "sgp40",
            "label": "SRAW VOC", "unit": "raw", "raw": raw_values.get("sgp40_raw"),
            "bias": 0.0, "calibrated": environment.get("sgp40_raw"), "editable": False,
            "source": sgp.get("source_label"), "status": sgp.get("status", "offline"),
            "data_age_s": sgp.get("data_age_s"),
            "lock_reason": "ค่าดิบสำหรับตรวจ Algorithm เท่านั้น",
        },
        {
            "metric": "bcg_heart_rate", "device": "LSM-800-T", "device_key": "bcg",
            "label": "Heart Rate", "unit": "BPM", "raw": bcg.get("heart_rate_bpm"),
            "bias": 0.0, "calibrated": bcg.get("heart_rate_bpm"), "editable": False,
            "source": "BCG · Serial", "status": "live" if bcg.get("connected") else "offline",
            "data_age_s": bcg.get("data_age_s"),
            "lock_reason": "Firmware physiology output — แสดงดิบเพื่อเทียบเครื่องอ้างอิง",
        },
        {
            "metric": "bcg_respiration_rate", "device": "LSM-800-T", "device_key": "bcg",
            "label": "Respiratory Rate", "unit": "ครั้ง/นาที",
            "raw": bcg.get("respiration_rate"), "bias": 0.0,
            "calibrated": bcg.get("respiration_rate"), "editable": False,
            "source": "BCG · Serial", "status": "live" if bcg.get("connected") else "offline",
            "data_age_s": bcg.get("data_age_s"),
            "lock_reason": "ใช้โดย Sleep Estimator — ห้ามปรับ bias โดยไม่มี validation",
        },
    ])
    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "session_active": bool((snap.get("session") or {}).get("active")),
        "channels": channels,
        "calibration_file": str(CALIBRATION_PATH),
        "formula": {
            "default": "calibrated = clamp(raw + bias)",
            "sound_dba_est": "estimate = clamp(abs(raw dBFS) + adjustment)",
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
            metric, cmd.bias, operator=principal.username,
            reference_value=cmd.reference_value,
        )
    except ValueError as exc:
        code = str(exc)
        if code == "metric_not_calibratable":
            raise HTTPException(422, "Sensor channel นี้ไม่อนุญาตให้ปรับ bias") from exc
        raise HTTPException(422, "ค่า bias/reference อยู่นอกช่วงที่อนุญาต") from exc
    log_event(
        "calibration", "sensor_bias_updated", operator=principal.username,
        metric=metric, bias=updated["bias"],
        reference_value=updated.get("reference_value"),
        active_session=bool(_active_session),
    )
    return {"ok": True, "update": updated,
            "calibration": sensor_calibration_inspector_snapshot()}


@app.get("/api/logs", dependencies=[Depends(require_admin)])
async def api_logs(limit: int = 100):
    """Event log ล่าสุด (ring buffer) — ใช้ไล่ตรวจ connect/disconnect/คำสั่ง"""
    limit = max(1, min(EVENT_RING_LIMIT, int(limit)))
    with event_log_lock:
        events = list(_event_ring)[-limit:]
    return {"events": events, "log_file": str(EVENT_LOG_PATH),
            "db_health": database.health()}


class SwitchCommand(BaseModel):
    on: bool


class VolumeCommand(BaseModel):
    volume: int


class TrackCommand(BaseModel):
    track: str
    loop: bool = False
    queue: bool = False
    user_initiated: bool = False


class LoginCommand(BaseModel):
    username: str
    gender: Optional[str] = None
    age: Optional[int] = None
    age_group: Optional[str] = None
    # Reserved for Local fallback and future Profile editing. Missing means
    # unknown; the service never fabricates body measurements or blood group.
    height_cm: Optional[float] = None
    weight_kg: Optional[float] = None
    blood_group: Optional[str] = None
    rest_mode: str = "auto"
    # One-time proof returned only after this Pi actually failed to reach ZEEP.
    # This closes the old unauthenticated local-login bypass.
    offline_ticket: str
    offline_identifier: str


class AuthLoginCommand(BaseModel):
    identifier: str          # username หรือ email — ตรงกับ contract ของ ZEEP API
    password: str
    # ส่งมาเฉพาะรอบที่สอง หลัง /api/auth/login ตอบ 422 age_group_required
    # (บัญชี ZEEP ที่ยังไม่ได้ตั้งวันเกิด → คำนวณ Baseline จากอายุไม่ได้)
    age_group: Optional[str] = None
    rest_mode: str = "auto"


class AdminLoginCommand(BaseModel):
    identifier: str
    password: str


class ForceLogoutCommand(BaseModel):
    reason: str = "admin_force_logout"


class ActiveSessionProfileCommand(BaseModel):
    session_id: str
    display_name: str
    gender: str
    reason: str = "admin_profile_correction"


class ProgressiveProfileConsentCommand(BaseModel):
    granted: bool


class ProgressiveProfileAnswerCommand(BaseModel):
    question_id: str
    value: Any


class ProgressiveProfileDeferCommand(BaseModel):
    question_id: Optional[str] = None


class LabelCommand(BaseModel):
    label: str


class AirconCommand(BaseModel):
    command: str
    # Admin Control Debug may bypass the user-facing -5 C comfort bias.  The
    # endpoint verifies the authenticated role again before accepting this.
    direct: bool = False


class AirconFanLevelReferenceCommand(BaseModel):
    # Administrative correction only. This updates the Pi reference without
    # transmitting an IR frame to the air conditioner.
    level: int
    note: Optional[str] = None


class BedControlCommand(BaseModel):
    command: str


def _normalize_aircon_command(raw: str) -> str:
    command = " ".join((raw or "").strip().lower().split())
    fixed = {
        "on", "off", "fan", "swing_on", "swing_off",
        "light_on", "light_off", "status",
    }
    if command in fixed:
        return command
    parts = command.split(" ")
    if len(parts) == 2 and parts[0] == "temp":
        try:
            temperature_c = int(parts[1])
        except ValueError:
            temperature_c = -1
        if 5 <= temperature_c <= 32:
            return f"temp {temperature_c}"
    raise HTTPException(
        422,
        "คำสั่ง Air Con ไม่ถูกต้อง: ใช้ on, off, temp 5-32, fan, "
        "swing_on/off, light_on/off หรือ status",
    )


def _apply_aircon_temperature_bias(command: str) -> Tuple[str, Optional[int], Optional[int]]:
    """Translate a user-facing temperature into the colder ESP32 IR setpoint.

    Example with the default -5 °C bias: ``temp 20`` becomes ``temp 15``.
    Non-temperature commands pass through unchanged.
    """
    if not command.startswith("temp "):
        return command, None, None
    desired_temperature = int(command.split(" ", 1)[1])
    if not AIRCON_DESIRED_TEMP_MIN_C <= desired_temperature <= AIRCON_DESIRED_TEMP_MAX_C:
        raise HTTPException(
            422,
            f"อุณหภูมิที่ผู้ใช้เลือกต้องอยู่ระหว่าง "
            f"{AIRCON_DESIRED_TEMP_MIN_C}-{AIRCON_DESIRED_TEMP_MAX_C} °C",
        )
    commanded_temperature = desired_temperature + AIRCON_TEMPERATURE_BIAS_C
    if not 5 <= commanded_temperature <= 32:
        raise HTTPException(500, "ค่า Air Con bias อยู่นอกช่วงคำสั่ง 5-32 °C")
    return f"temp {commanded_temperature}", desired_temperature, commanded_temperature


def _normalize_bed_command(raw: str) -> str:
    command = (raw or "").strip().lower()
    allowed = {
        "head_up", "head_down", "foot_up", "foot_down",
        "bed_stop", "flat", "center_all", "status",
    }
    if command not in allowed:
        raise HTTPException(
            422,
            "คำสั่ง Bed ไม่ถูกต้อง: ใช้ head_up, head_down, foot_up, "
            "foot_down, bed_stop, flat, center_all หรือ status",
        )
    return command


@app.post("/api/safety/arm", dependencies=[Depends(require_admin)])
def safety_arm():
    faults = _safety_faults()
    blocking = [f for f in faults if f["severity"] in ("blocking", "critical")]
    if blocking:
        raise HTTPException(409, {"message": "Safety Supervisor ยังไม่พร้อม Arm",
                                  "faults": blocking})
    with state_lock:
        state["safety"]["armed"] = True
    log_event("safety", "armed")
    return {"ok": True, "safety": snapshot()["safety"]}


@app.post("/api/safety/disarm", dependencies=[Depends(require_admin)])
def safety_disarm():
    with state_lock:
        state["safety"]["armed"] = False
    log_event("safety", "disarmed")
    return {"ok": True, "safety": snapshot()["safety"]}


@app.post("/api/safety/safe-mode", dependencies=[Depends(require_admin)])
def safety_safe_mode():
    action = apply_safety_profile("manual_dashboard")
    return {"ok": True, "action": action, "safety": snapshot()["safety"]}


@app.post("/api/safety/ack", dependencies=[Depends(require_admin)])
def safety_acknowledge():
    faults = _safety_faults()
    critical = [f for f in faults if f["severity"] == "critical"]
    if critical:
        raise HTTPException(409, {"message": "ยังมี critical fault จึง acknowledge ไม่ได้",
                                  "faults": critical})
    with state_lock:
        state["safety"]["latched"] = False
    log_event("safety", "acknowledged")
    return {"ok": True, "safety": snapshot()["safety"]}


def _require_safety_allows(action: str):
    with state_lock:
        latched = bool(state["safety"].get("latched"))
    if latched:
        raise HTTPException(423, f"Safety EMERGENCY latch: ไม่อนุญาต {action}")


@app.get("/")
async def root():
    """Use a stable public entry point instead of mixing role selectors."""
    return RedirectResponse(url="/login", status_code=307)


@app.get("/login")
@app.get("/admin/login")
async def login_view():
    """Serve the shared shell; the immutable URL selects the login audience."""
    return FileResponse(
        STATIC_DIR / "index.html",
        headers={"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache"},
    )


# The onboard UI is one lightweight application with role-focused views.
# Keeping one asset avoids duplicating the WebSocket and GPIO command logic,
# while stable URLs let operators and developers bookmark the page they need.
@app.get("/dashboard")
@app.get("/control")
@app.get("/control-debug")
@app.get("/monitor")
@app.get("/sessions")
@app.get("/admin")
async def ui_view():
    return FileResponse(
        STATIC_DIR / "index.html",
        headers={"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache"},
    )


@app.get("/api/state")
async def api_state(principal: Principal = Depends(require_pod_operator)):
    return snapshot_for(principal)


@app.get("/api/public/status")
def public_status():
    """Non-sensitive boot information used before a browser is authenticated."""
    with session_lock:
        occupied = _active_session is not None
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


@app.get("/api/smart-response")
async def api_smart_response(_: Principal = Depends(require_pod_operator)):
    """Read-only Smart Response decisions; Shadow Mode never actuates devices."""
    return snapshot()["smart_response"]


@app.post("/api/aircon/command")
def aircon_command(
    cmd: AirconCommand,
    principal: Principal = Depends(require_pod_operator),
):
    requested_command = _normalize_aircon_command(cmd.command)
    direct_temperature = bool(cmd.direct and requested_command.startswith("temp "))
    if cmd.direct and not getattr(principal, "is_admin", False):
        raise HTTPException(
            403,
            {"code": "admin_required", "message": "Direct Aircon command ใช้ได้เฉพาะผู้ดูแลระบบ"},
        )
    if direct_temperature:
        commanded_temperature = int(requested_command.split(" ", 1)[1])
        if not 5 <= commanded_temperature <= 30:
            raise HTTPException(422, "Control Debug ปรับอุณหภูมิได้ระหว่าง 5-30 °C")
        command = requested_command
        desired_temperature = None
    else:
        command, desired_temperature, commanded_temperature = _apply_aircon_temperature_bias(
            requested_command
        )
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
                fan_level = (
                    current_level % 5 + 1
                    if isinstance(current_level, int) and 1 <= current_level <= 5
                    else 1
                )
                fan_level_source = "acknowledged_ir_cycle"
            aircon_state["fan_level"] = fan_level
            aircon_state["fan_level_source"] = fan_level_source
            aircon_state["fan_level_updated_at"] = time.time()
            state["aircon"] = aircon_state
        # Advance durable state only after Control Hub 1 acknowledges the IR
        # transmit routine. A timeout/error therefore leaves the reference at
        # the last known level instead of guessing that the command worked.
        _persist_aircon_fan_level(fan_level, fan_level_source)
    note_session_activity("aircon_command", {
        "requested_command": requested_command,
        "command": command,
        "direct": direct_temperature,
        "fan_level": fan_level,
        "desired_temperature_c": desired_temperature,
        "commanded_temperature_c": commanded_temperature,
        "temperature_bias_c": AIRCON_TEMPERATURE_BIAS_C,
        "power_on_default_temperature_c": (
            AIRCON_POWER_ON_DEFAULT_TEMP_C if command == "on" else None
        ),
        "preflight_command": preflight_command,
        "followup_command": followup_command,
        "swing_command": swing_command,
        "tx_count": (swing_ack or followup_ack or acknowledgement).get("tx_count"),
    })
    return {
        "ok": True,
        "command": command,
        "requested_command": requested_command,
        "direct": direct_temperature,
        "fan_level": fan_level,
        "desired_temperature_c": desired_temperature,
        "commanded_temperature_c": commanded_temperature,
        "temperature_bias_c": AIRCON_TEMPERATURE_BIAS_C,
        "power_on_default_temperature_c": (
            AIRCON_POWER_ON_DEFAULT_TEMP_C if command == "on" else None
        ),
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
        "power_on_settle_seconds": (
            CONTROLHUB1_POWER_ON_SETTLE_SECONDS if command == "on" else None
        ),
        "fan_wake_settle_seconds": (
            CONTROLHUB1_FAN_WAKE_SETTLE_SECONDS if command == "fan" else None
        ),
        "aircon": snapshot().get("aircon", {}),
    }


@app.post("/api/admin/aircon/fan-level-reference")
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
    note_session_activity("aircon_fan_level_reference", {
        "level": int(cmd.level),
        "source": "admin_declared_reference",
        "ir_transmitted": False,
    })
    return {
        "ok": True,
        "fan_level": int(cmd.level),
        "fan_level_source": "admin_declared_reference",
        "persisted": True,
        "ir_transmitted": False,
        "physical_confirmation": False,
        "aircon": snapshot().get("aircon", {}),
    }


@app.post("/api/bed/command", dependencies=[Depends(require_pod_operator)])
def bed_control_command(cmd: BedControlCommand):
    requested_command = _normalize_bed_command(cmd.command)
    acknowledgement, command = controlhub2_bed_mqtt.publish_and_wait(
        requested_command, toggle_repeat=False)
    movement_commands = {
        "head_up", "head_down", "foot_up", "foot_down", "flat", "center_all",
    }
    auto_stop_after_s = None
    if command in movement_commands:
        _schedule_bed_auto_stop(command)
        auto_stop_after_s = BED_MOVE_SECONDS
    elif command == "bed_stop":
        _cancel_bed_auto_stop("explicit_stop")
    note_session_activity("bed_command", {
        "requested_command": requested_command,
        "command": command,
        "auto_stop_after_s": auto_stop_after_s,
    })
    return {
        "ok": True,
        "command": command,
        "requested_command": requested_command,
        "toggle_stop": False,
        "auto_stop_after_s": auto_stop_after_s,
        "ack": acknowledgement,
        "bed_control": snapshot().get("bed_control", {}),
    }


@app.post("/api/output/{name}", dependencies=[Depends(require_pod_operator)])
async def output(name: str, cmd: SwitchCommand):
    if name not in GPIO_PINS:
        raise HTTPException(404, "Unknown output")
    if name in ("door_open", "door_close"):
        raise HTTPException(400, "Use /api/door/open or /api/door/close for door")
    if name in PULSE_OUTPUTS:
        raise HTTPException(400, f"Use /api/pulse/{name} for momentary output")
    if not (name == "led" and cmd.on):
        _require_safety_allows(f"output {name}={cmd.on}")
    gpio.require_ready()
    try:
        gpio.set(name, cmd.on)
    except Exception as exc:
        log_event("gpio", "command_failed", target=name, error=str(exc))
        raise HTTPException(500, str(exc))
    note_session_activity("output", {"name": name, "on": cmd.on})
    log_event("gpio", "output", target=name, on=cmd.on)
    return {"ok": True, "name": name, "on": cmd.on}


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


door_lock = asyncio.Lock()


async def door_pulse(name: str):
    gpio.require_ready()
    # Serialize door commands: overlapping pulses would cut each other short.
    if door_lock.locked():
        raise HTTPException(429, "Door command already in progress")
    async with door_lock:
        other = "door_close" if name == "door_open" else "door_open"
        gpio.set(other, False)
        gpio.set(name, True)
        try:
            await asyncio.sleep(DOOR_PULSE_SECONDS)
        finally:
            # Must run even on cancellation — a HIGH door pin left behind
            # means the drive is commanded continuously.
            gpio.set(name, False)


@app.post("/api/door/open", dependencies=[Depends(require_pod_operator)])
async def door_open():
    await door_pulse("door_open")
    note_session_activity("door", {"action": "open"})
    log_event("door", "open_pulse", pulse_s=DOOR_PULSE_SECONDS)
    return {"ok": True, "action": "open", "pulse_s": DOOR_PULSE_SECONDS}


@app.post("/api/door/close", dependencies=[Depends(require_pod_operator)])
async def door_close():
    _require_safety_allows("ปิดประตู")
    await door_pulse("door_close")
    note_session_activity("door", {"action": "close"})
    log_event("door", "close_pulse", pulse_s=DOOR_PULSE_SECONDS)
    return {"ok": True, "action": "close", "pulse_s": DOOR_PULSE_SECONDS}


pulse_locks = {name: asyncio.Lock() for name in PULSE_OUTPUTS}
pulse_last_end = {name: 0.0 for name in PULSE_OUTPUTS}


async def accessory_pulse(name: str):
    if name not in PULSE_OUTPUTS:
        raise HTTPException(404, "Unknown pulse output")
    gpio.require_ready()
    lock = pulse_locks[name]
    if lock.locked():
        raise HTTPException(429, f"{name} pulse already active")
    async with lock:
        if time.monotonic() - pulse_last_end[name] < PULSE_COOLDOWN_SECONDS:
            raise HTTPException(429, f"{name} is cooling down")
        gpio.set(name, True)
        try:
            await asyncio.sleep(AROMA_STEAM_PULSE_SECONDS)
        finally:
            gpio.set(name, False)
            pulse_last_end[name] = time.monotonic()


@app.post("/api/pulse/{name}", dependencies=[Depends(require_pod_operator)])
async def pulse_output(name: str):
    _require_safety_allows(f"pulse {name}")
    await accessory_pulse(name)
    note_session_activity("pulse", {"name": name})
    log_event("gpio", "pulse", target=name, pulse_s=AROMA_STEAM_PULSE_SECONDS)
    return {"ok": True, "name": name, "pulse_s": AROMA_STEAM_PULSE_SECONDS}


# ---------- session login / logout / history ----------
def _start_pod_session(
    username: str,
    gender: Optional[str],
    age: Optional[int],
    age_group: Optional[str],
    *,
    owner: Principal,
    auth: Optional[Dict[str, Any]] = None,
    health_reference: Optional[Dict[str, Any]] = None,
    rest_mode: str = "auto",
) -> Dict[str, Any]:
    """ตรวจค่า, อัปเดต profile ในตู้ แล้วเปิด session ใหม่ (สถานะ "รอขึ้นเตียง").

    ใช้ร่วมกันสองทาง: login ด้วยบัญชี ZEEP (`/api/auth/login`) และโหมด local
    fallback ตอนต่อ ZEEP API ไม่ได้ (`/api/session/login`). ``owner`` คือ browser
    auth session ที่มีสิทธิ์จบ session นี้ ส่วน token ของ ZEEP อยู่ใน ``auth``
    เท่านั้น จึงไม่หลุดไป snapshot, WebSocket หรือฐานข้อมูล.
    """
    global _active_session
    with state_lock:
        safety = dict(state["safety"])
    # Session access and safety actuation are deliberately independent. A user
    # may authenticate and record a session in any supervisor state; READY,
    # ARMED and the emergency latch remain authoritative inside Smart Response
    # and every protected device-command endpoint.
    monitor_only = False
    username = _normalize_username(username)
    # Verified ZEEP sessions are stored under normalized email. Local fallback
    # has no verified email and therefore retains its local username key.
    key = owner.account_key
    email = owner.email
    if auth:
        email = _normalize_email(str(auth.get("email") or ""))
        if key != email:
            raise HTTPException(409, "Account identity ไม่ตรงกับ Email ที่ยืนยันแล้ว")
    gender = (gender or "").strip().lower() or None
    age_group = (age_group or "").strip() or None
    incoming_health = dict(health_reference or {})
    try:
        rest_mode = normalise_rest_mode(rest_mode)
    except ValueError as exc:
        raise HTTPException(422, "รูปแบบการพักไม่ถูกต้อง") from exc
    if age_group is not None and age_group not in AGE_SLEEP_BASELINES:
        raise HTTPException(422, "ช่วงอายุต้องเป็น 18-29, 30-44, 45-59 หรือ 60+")
    if age is None:
        age = AGE_GROUP_DEFAULT_AGE.get(age_group)
    if age is not None and not 18 <= age <= 100:
        raise HTTPException(422, "อายุต้องอยู่ระหว่าง 18–100 ปี")
    if gender is not None and gender not in GENDERS:
        raise HTTPException(422, f"gender ต้องเป็นหนึ่งใน {', '.join(GENDERS)}")

    with session_lock:
        if _active_session is not None:
            raise HTTPException(
                409,
                {"code": "pod_already_occupied", "message": "ตู้นี้กำลังมีผู้ใช้งาน"},
            )

    # A successful /users/me response is authoritative for this Login.  When
    # that endpoint is unavailable we keep the last verified profile instead
    # of replacing it with empty values, and mark the snapshot as cached.
    profile_refreshed = bool(auth and auth.get("profile_refreshed", True))
    health_reference_now = datetime.now(timezone.utc).isoformat()
    with profile_lock:
        profiles = _load_profiles()
        profile = profiles.get(key)
        if profile is None:
            if gender is None:
                raise HTTPException(422, "ผู้ใช้ใหม่ต้องเลือกเพศ (ชาย/หญิง/อื่น ๆ/ไม่ระบุ)")
            if age_group is None:
                raise HTTPException(422, "ผู้ใช้ใหม่ต้องเลือกช่วงอายุสำหรับ Baseline")
            profile = {
                "username": username,
                "account_key": key,
                "email": email,
                "gender": gender,
                "age": age,
                "age_is_estimated": incoming_health.get("age_years") is None,
                "age_group": age_group,
                "date_of_birth": _normalise_date_of_birth(
                    incoming_health.get("date_of_birth")),
                "height_cm": _normalise_body_measurement(
                    incoming_health.get("height_cm"), measurement="height_cm"),
                "weight_kg": _normalise_body_measurement(
                    incoming_health.get("weight_kg"), measurement="weight_kg"),
                "blood_group": _normalise_blood_group(
                    incoming_health.get("blood_group")),
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "sessions": 0,
                "last_session_utc": None,
            }
        else:
            profile["username"] = username
            profile["account_key"] = key
            if email:
                profile["email"] = email
            if age is None:
                age = profile.get("age")
            if age_group is None:
                age_group = profile.get("age_group") or _age_group(age)
            if gender and (not auth or profile_refreshed):
                profile["gender"] = gender
            if age is not None and (not auth or profile_refreshed):
                profile["age"] = age
                if incoming_health.get("age_years") is not None:
                    profile["age_is_estimated"] = False
            profile["age_group"] = age_group
            optional_health_fields = {
                "date_of_birth": _normalise_date_of_birth(
                    incoming_health.get("date_of_birth")),
                "height_cm": _normalise_body_measurement(
                    incoming_health.get("height_cm"), measurement="height_cm"),
                "weight_kg": _normalise_body_measurement(
                    incoming_health.get("weight_kg"), measurement="weight_kg"),
                "blood_group": _normalise_blood_group(
                    incoming_health.get("blood_group")),
            }
            if profile_refreshed:
                # Login refresh is a complete profile snapshot.  Explicitly
                # clear fields no longer returned by the account API so a
                # renamed/edited Profile never displays stale health facts.
                profile.update(optional_health_fields)
                profile["age_is_estimated"] = incoming_health.get("age_years") is None
            else:
                # /users/me failed after identity Login.  Preserve only the
                # last verified health facts and expose that they are cached.
                for field, value in optional_health_fields.items():
                    if value is not None:
                        profile[field] = value
        if auth and profile_refreshed:
            profile["health_reference_source"] = incoming_health.get("source") or "zeep_profile"
            profile["health_reference_refresh_status"] = "live_login"
            profile["health_reference_updated_at_utc"] = health_reference_now
        elif auth:
            profile.setdefault("health_reference_source", "zeep_login_identity")
            profile["health_reference_refresh_status"] = "cached"
            profile.setdefault("health_reference_updated_at_utc", None)
        else:
            profile["health_reference_source"] = incoming_health.get("source") or "local_profile"
            profile["health_reference_refresh_status"] = "local_login"
            profile["health_reference_updated_at_utc"] = health_reference_now
        if auth:
            # Email is the data key. publicId remains the immutable authorization
            # subject, while displayName/username are refreshed presentation data.
            profile["zeep_public_id"] = auth.get("public_id")
            profile["zeep_email"] = email
            profile["email"] = email
            profile["display_name"] = auth.get("display_name")
        session_health_reference = _health_reference_from_profile(profile)
        session_wellness_context = session_context_snapshot(profile)
        profiles[key] = profile
        _save_profiles(profiles)

    session_id = (
        f"s-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:6]}"
    )
    # This is the cross-pod atomic gate.  With a remote coordinator configured,
    # the same immutable ZEEP subject cannot acquire a second pod concurrently.
    try:
        lease = occupancy_client.acquire(
            subject=owner.subject,
            pod_id=POD_ID,
            pod_session_id=session_id,
            username=username,
        )
    except OccupancyConflict as exc:
        code = exc.reason
        message = (
            "บัญชีนี้กำลังใช้งานตู้อื่นอยู่"
            if code == "account_already_in_use"
            else "ตู้นี้กำลังมีผู้ใช้งาน"
        )
        raise HTTPException(409, {"code": code, "message": message, "pod_id": exc.pod_id}) from exc
    except CoordinatorUnavailable as exc:
        # Fail closed for a new occupant. Existing occupants continue locally
        # even if the coordinator/network later becomes unavailable.
        raise HTTPException(503, {
            "code": "occupancy_coordinator_unavailable",
            "message": "ยังตรวจสอบการใช้งานซ้ำระหว่างตู้ไม่ได้ จึงยังไม่เริ่ม Session ใหม่",
        }) from exc

    with state_lock:
        vital_gate_start_packet_count = int(
            state["sensor"]["bcg"].get("packets") or 0
        )
    new_session = {
        "record": {
            "session_id": session_id,
            "username": username,
            "username_key": key,
            "gender": profile["gender"],
            "age": profile.get("age"),
            "age_group": profile.get("age_group") or _age_group(profile.get("age")),
            "health_reference": session_health_reference,
            "wellness_context": session_wellness_context,
            "rest_mode": rest_mode,
            "auth_source": "zeep" if auth else "local",
            "zeep_public_id": (auth or {}).get("public_id"),
            "identity_subject": owner.subject,
            "pod_id": POD_ID,
            "armed_at_utc": datetime.now(timezone.utc).isoformat(),
            "started_at_utc": None,     # ตั้งค่าเมื่อยืนยันนอนครบ BED_START_SECONDS
            "started_monotonic": None,
            "sample_interval_s": SESSION_SAMPLE_SECONDS,
            "sample_cadence_segments": [],
        },
        # identity + token ของ ZEEP อยู่นอก "record" เพื่อไม่ให้ติดไปกับ record ที่
        # ลง DB / คืนให้ client ตอน logout
        "auth": auth,
        "owner_auth_session_id": owner.session_id,
        "occupancy_lease": lease,
        "last_lease_renew": time.monotonic(),
        "samples": [],
        "counters": {},
        "last_sample": float("-inf"),
        "phase": "waiting_bed",         # ยังไม่เริ่มนับจนกว่าจะนอนครบตามเกณฑ์
        "onbed_since": None,
        "vital_gate_start_packet_count": vital_gate_start_packet_count,
    }
    with session_lock:
        if _active_session is not None:
            occupancy_client.release(lease)
            raise HTTPException(409, "มี session อื่นเพิ่งเริ่มพร้อมกัน — ลองใหม่")
        _active_session = new_session
    try:
        # Persist before returning Login success so an update/reboot cannot
        # forget a user who is still in the waiting-for-bed phase.
        _save_active_session_checkpoint(new_session)
    except Exception as exc:
        with session_lock:
            if _active_session is new_session:
                _active_session = None
        try:
            occupancy_client.release(lease)
        except (CoordinatorUnavailable, OccupancyConflict):
            pass
        raise HTTPException(500, "บันทึกสถานะ Login สำหรับกู้คืนไม่สำเร็จ") from exc
    # A new sleeper/session must build its own independent 36-sample window.
    _reset_live_sleep_inference(session_id)
    # DB session_start + BCG storage จะเริ่มตอน _begin_recording (นอนครบ 20 วิ)
    log_event("session", "login_waiting_bed", session_id=session_id, user=username,
              bed_start_s=BED_START_SECONDS, monitor_only=monitor_only,
              safety_level=safety.get("level"),
              rest_mode=rest_mode,
              auth_source=new_session["record"]["auth_source"], pod_id=POD_ID)
    vital_gate = session_vital_gate_now(new_session)
    with state_lock:
        state["session"].update({
            "active": True, "username": username, "account_key": key,
            "email": email, "gender": profile["gender"],
            "display_name": (auth or {}).get("display_name") or username,
            "auth_source": new_session["record"]["auth_source"],
            "age": profile.get("age"),
            "age_group": profile.get("age_group") or _age_group(profile.get("age")),
            "health_reference": session_health_reference,
            "wellness_context_available": bool(session_wellness_context),
            "rest_mode": rest_mode,
            "session_id": session_id, "started_at": time.time(), "samples": 0,
            "recording": False, "bed_wait_s": 0,
            "vital_gate": vital_gate,
        })
    return {
        "ok": True,
        "session": snapshot()["session"],
        "pod_id": POD_ID,
        "occupancy": {"mode": occupancy_client.mode, "lease_expires_at": lease.expires_at},
        "monitor_only": monitor_only,
        "warning": (
            "Session เริ่มใน Monitor Mode — ระบบตอบสนองฉุกเฉินอัตโนมัติยังไม่ทำงาน"
            if monitor_only else None
        ),
    }


def _authenticate_zeep_account(identifier: str, password: str) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """Verify a ZEEP account and return public identity plus profile metadata."""
    data = _zeep_request(
        "POST", "/v1/auth/login", json_body={"identifier": identifier, "password": password}
    ).get("data") or {}
    tokens = data.get("tokens") or {}
    user = data.get("user") or {}
    access_token = tokens.get("accessToken")
    zeep_username = str(user.get("username") or "").strip()
    public_id = str(user.get("publicId") or "").strip()
    if not access_token or not zeep_username or not public_id:
        raise HTTPException(502, "ZEEP API ตอบข้อมูลตัวตนไม่ครบ")

    me: Dict[str, Any] = {}
    profile_refreshed = False
    try:
        me = _zeep_request("GET", "/v1/users/me", token=access_token).get("data") or {}
        if not isinstance(me, dict):
            me = {}
        profile_refreshed = True
    except (ZeepApiOffline, HTTPException) as exc:
        log_event("auth", "zeep_profile_failed", user=zeep_username,
                  error=str(getattr(exc, "detail", exc)))

    # Email is the canonical local data identity. Prefer the Login contract and
    # accept /users/me as a fallback, then reject incomplete accounts instead
    # of silently creating a second history under a mutable display name.
    try:
        account_email = _normalize_email(str(user.get("email") or me.get("email") or ""))
    except HTTPException as exc:
        raise HTTPException(502, "ZEEP API ตอบ Email สำหรับผูกประวัติไม่ครบ") from exc

    auth = {
        "public_id": public_id,
        "username": zeep_username,
        "email": account_email,
        "display_name": (user.get("displayName") or "").strip() or zeep_username,
        "role": user.get("role"),
        "plan": user.get("plan"),
        "access_token": access_token,
        "refresh_token": tokens.get("refreshToken"),
        # Internal freshness flag only; never returned by the public Login
        # response.  It prevents a failed profile fetch from looking current.
        "profile_refreshed": profile_refreshed,
    }
    return auth, me


@app.post("/api/auth/login")
def auth_login(cmd: AuthLoginCommand, response: Response):
    """Authenticate an occupant, acquire the pod lease, then start a pod session."""
    identifier = (cmd.identifier or "").strip()
    if not identifier or not cmd.password:
        raise HTTPException(422, "กรอก Username/Email และรหัสผ่านให้ครบ")
    with session_lock:
        if _active_session is not None:
            raise HTTPException(409, {
                "code": "pod_already_occupied", "message": "ตู้นี้กำลังมีผู้ใช้งาน"
            })
    try:
        auth, me = _authenticate_zeep_account(identifier, cmd.password)
    except ZeepApiOffline as exc:
        ticket = auth_sessions.issue_offline_ticket(identifier)
        log_event("auth", "zeep_offline", stage="login", error=str(exc))
        raise HTTPException(503, {
            "code": "offline",
            "message": "ต่อ ZEEP API ไม่ได้ — สามารถใช้ Local fallback ได้ภายใน 5 นาที",
            "offline_ticket": ticket,
            "identifier": identifier,
        }) from exc

    health_reference = _zeep_health_reference(me)
    age = health_reference.get("age_years")
    age_group = (cmd.age_group or "").strip() or (_age_group(age) if age is not None else None)
    account_key = auth["email"]
    # Local research aliases and verified demographic corrections are Pod-only
    # presentation/baseline overrides.  Email/publicId remain canonical and the
    # external ZEEP profile is never mutated from this appliance.
    with profile_lock:
        prior = _load_profiles().get(account_key) or {}
    if age_group is None:
        age_group = prior.get("age_group")
    if age_group is None:
        raise HTTPException(422, {
            "code": "age_group_required",
            "message": "โปรไฟล์ ZEEP ยังไม่ได้ตั้งวันเกิด — เลือกช่วงอายุเพื่อกำหนด "
            "Baseline ของ Session นี้",
        })

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
            auth["username"], health_reference.get("gender"), age, age_group,
            owner=principal, auth=auth, health_reference=health_reference,
            rest_mode=cmd.rest_mode,
        )
    except Exception:
        auth_sessions.revoke(cookie_token)
        raise
    _set_auth_cookies(response, cookie_token, principal)
    result["user"] = {k: auth[k] for k in
                      ("public_id", "username", "email", "display_name", "role", "plan")}
    result["principal"] = principal.public_dict()
    return result


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
            raise HTTPException(503, {
                "code": "admin_auth_offline",
                "message": "ZEEP API ใช้งานไม่ได้ และ Local Admin ไม่ผ่านการยืนยัน",
            }) from exc
        allowed_roles = {
            role.strip().casefold()
            for role in os.getenv("ZEEP_ADMIN_ROLES", "admin").split(",")
            if role.strip()
        }
        if str(auth.get("role") or "").casefold() not in allowed_roles:
            if auth.get("refresh_token"):
                try:
                    _zeep_request("POST", "/v1/auth/logout",
                                  json_body={"refreshToken": auth["refresh_token"]})
                except (ZeepApiOffline, HTTPException):
                    pass
            raise HTTPException(403, {
                "code": "admin_required", "message": "บัญชีนี้ไม่มีสิทธิ์ผู้ดูแลระบบ"
            })
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
                _zeep_request("POST", "/v1/auth/logout",
                              json_body={"refreshToken": auth["refresh_token"]})
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
        raise HTTPException(403, {
            "code": "user_profile_required",
            "message": "แบบสอบถามนี้เป็นสิทธิ์ของผู้ใช้งานแต่ละบัญชี",
        })
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
        "profile", "progressive_consent_updated", account_key=account_key,
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
            raise HTTPException(409, {
                "code": str(exc), "message": "กรุณาให้ความยินยอมก่อนตอบแบบสอบถาม",
            }) from exc
        except ValueError as exc:
            raise HTTPException(422, {
                "code": str(exc), "message": "คำตอบไม่อยู่ในรูปแบบที่กำหนด",
            }) from exc
        profiles[account_key] = profile
        _save_profiles(profiles)
        snapshot = progressive_profile_snapshot(profile)
    # Do not put the answer value in application logs. The audit trail records
    # only who changed which versioned question and when.
    log_event(
        "profile", "progressive_answer_updated",
        account_key=account_key, question_id=question_id,
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
            raise HTTPException(422, {
                "code": str(exc), "message": "ไม่พบคำถามที่ต้องการเลื่อน",
            }) from exc
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
            raise HTTPException(404, {
                "code": str(exc), "message": "ไม่พบคำตอบที่ต้องการลบ",
            }) from exc
        profiles[account_key] = profile
        _save_profiles(profiles)
        snapshot = progressive_profile_snapshot(profile)
    log_event(
        "profile", "progressive_answer_deleted",
        account_key=account_key, question_id=question_id,
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
        raise HTTPException(409, {
            "code": "pod_session_active",
            "message": "กรุณาจบและบันทึก Session การนอนก่อนออกจากระบบ",
        })
    auth_sessions.revoke(request.cookies.get(COOKIE_NAME))
    _clear_auth_cookies(response)
    log_event("auth", "browser_logout", user=principal.username, role=principal.role)
    return {"ok": True}


@app.post("/api/session/login")
def session_login(cmd: LoginCommand, response: Response):
    """Local fallback: เปิด session โดยไม่ใช้บัญชี ZEEP (ไม่มีรหัสผ่าน).

    มีไว้ให้ตู้ยังเก็บข้อมูลวิจัยต่อได้ตอนเน็ตหลุด/ZEEP API ล่ม — หน้าเว็บจะเสนอ
    Backend บังคับ one-time offline ticket จึงเรียก endpoint นี้ตรง ๆ ไม่ได้.
    """
    if not auth_sessions.consume_offline_ticket(cmd.offline_ticket, cmd.offline_identifier):
        raise HTTPException(403, {
            "code": "offline_ticket_invalid",
            "message": "Local fallback หมดอายุ กรุณาลองเชื่อมต่อ ZEEP ใหม่",
        })
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
            username, cmd.gender, cmd.age, cmd.age_group, owner=principal,
            health_reference={
                "gender": cmd.gender,
                "age_years": cmd.age,
                "height_cm": cmd.height_cm,
                "weight_kg": cmd.weight_kg,
                "blood_group": cmd.blood_group,
                "source": "local_profile",
            },
            rest_mode=cmd.rest_mode,
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
        "auth_retained": True,
    }


@app.post("/api/admin/session/force-logout")
def admin_force_logout(
    cmd: ForceLogoutCommand,
    principal: Principal = Depends(require_admin),
):
    # Backward-compatible alias.  Existing Admin clients that call
    # force-logout receive the same strong semantics as the new kick command.
    return _admin_finish_occupant_session(
        cmd, principal, action="kick", default_reason="admin_force_logout"
    )


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
        profile.update({
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
        })
        health_reference = _health_reference_from_profile(profile)
        profiles[account_key] = profile
        _save_profiles(profiles)

    with session_lock:
        active = _active_session
        if active is None or (active.get("record") or {}).get("session_id") != session_id:
            raise HTTPException(409, "Session สิ้นสุดระหว่างแก้ไข Profile")
        active["record"].update({
            "display_name": display_name,
            "gender": gender,
            "health_reference": health_reference,
        })
        if isinstance(active.get("auth"), dict):
            active["auth"]["display_name"] = display_name
        _save_active_session_checkpoint(active)

    browser_sessions = auth_sessions.update_user_display_name(account_key, display_name)
    with state_lock:
        state["session"].update({
            "display_name": display_name,
            "gender": gender,
            "health_reference": health_reference,
        })
    if recording_started:
        database.enqueue("sessions", "session_profile_update", {
            "session_id": session_id,
            "gender": gender,
        })
        database.enqueue("sessions", "event", {
            "session_id": session_id,
            "timestamp": corrected_at,
            "type": "profile_metadata_correction",
            "value": {
                "display_name": display_name,
                "gender": gender,
                "reason": reason,
                "operator": principal.username,
            },
        })
        if not database.flush(5.0):
            raise HTTPException(503, "บันทึก Profile correction ลงฐานข้อมูลยังไม่เสร็จ")
    _reset_live_sleep_inference(session_id)
    log_event(
        "admin", "active_profile_corrected", admin=principal.username,
        session_id=session_id, account_key=account_key,
        display_name=display_name, gender=gender, reason=reason,
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
        "admin", event, admin=principal.username,
        session_id=record["session_id"], user=record["username"],
        reason=reason, revoked_browser_sessions=revoked,
    )
    return {
        "ok": True,
        "action": action,
        "session_id": record["session_id"],
        "username": record["username"],
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
    return _admin_finish_occupant_session(
        cmd, principal, action="end", default_reason="admin_end_session"
    )


@app.post("/api/admin/session/kick")
def admin_kick_occupant(
    cmd: ForceLogoutCommand,
    principal: Principal = Depends(require_admin),
):
    """Finish the Session and revoke every local User login for its owner."""
    return _admin_finish_occupant_session(
        cmd, principal, action="kick", default_reason="admin_kick_occupant"
    )


def _history_user_activity_epoch(value: Any) -> float:
    """Return a comparable UTC epoch for a Profile activity timestamp."""
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError, OverflowError):
        return 0.0


def _users_ordered_by_latest_session(
    profiles: Dict[str, Any],
    active_record: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Build the Admin chooser with the most recently used account first.

    A running Session is newer than completed history.  Stable name ordering is
    retained only as a tie-breaker so the selector does not jump unpredictably.
    The ordering metadata is response-only and never mutates ``profiles.json``.
    """
    active_record = active_record or {}
    active_key = str(active_record.get("username_key") or "").strip().casefold()
    users: List[Dict[str, Any]] = []
    for stored_key, stored_profile in profiles.items():
        profile = dict(stored_profile or {})
        # The Admin user chooser needs completion status, not raw lifestyle
        # answers. Keep optional answers behind the dedicated self-service API
        # until a separately governed research export is designed.
        profile["progressive_profile_summary"] = admin_progress_summary(profile)
        profile.pop("progressive_profile", None)
        account_key = str(
            profile.get("account_key") or stored_key or profile.get("email") or ""
        ).strip().casefold()
        is_active = bool(active_key and account_key == active_key)
        latest_utc = (
            active_record.get("started_at_utc")
            or active_record.get("armed_at_utc")
        ) if is_active else None
        latest_utc = latest_utc or profile.get("last_session_utc")
        profile["history_order_utc"] = latest_utc
        profile["has_active_session"] = is_active
        users.append(profile)

    users.sort(
        key=lambda p: str(
            p.get("display_name") or p.get("username") or p.get("email") or ""
        ).casefold()
    )
    users.sort(
        key=lambda p: _history_user_activity_epoch(p.get("history_order_utc")),
        reverse=True,
    )
    users.sort(key=lambda p: bool(p.get("has_active_session")), reverse=True)
    return users


@app.get("/api/users", dependencies=[Depends(require_admin)])
def users_list():
    with profile_lock:
        profiles = _load_profiles()
    with session_lock:
        active_record = dict((_active_session or {}).get("record") or {})
    return {"users": _users_ordered_by_latest_session(profiles, active_record)}


@app.get("/api/sleep/baselines")
def sleep_baselines():
    """Single source of truth for the age-range selector and estimator UI."""
    return {"age_groups": AGE_SLEEP_BASELINES,
            "gender_adjustments": GENDER_BASELINE_ADJUSTMENTS,
            "order": ["18-29", "30-44", "45-59", "60+"]}


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
            "formula": "abs(sound_dbfs) + adjustment_db",
            "adjustment_db": SOUND_DBFS_MAGNITUDE_ADJUSTMENT_DB,
        },
        "sensor_biases": dict(SENSOR_BIASES),
    }
    return policy


@app.get("/api/history/{username}")
def history_list(
    username: str,
    limit: int = 20,
    principal: Principal = Depends(require_user),
):
    key = _require_username_access(username, principal)
    limit = max(1, min(200, int(limit)))
    with profile_lock:
        history_profile = _load_profiles().get(key, {})
    records = database.read_sessions(
        "SELECT * FROM sessions WHERE username_key=? ORDER BY start_time DESC LIMIT ?",
        (key, limit))
    total = database.read_sessions(
        "SELECT COUNT(*) AS n FROM sessions WHERE username_key=?", (key,))[0]["n"]
    sessions = []
    for record in records:
        agg = database.read_sessions(
            "SELECT COUNT(*) AS n, AVG(temperature) AS t, AVG(heart_rate) AS hr "
            "FROM timeline WHERE session_id=?", (record["session_id"],))[0]
        final_rows = database.read_sessions(
            "SELECT value FROM events WHERE session_id=? AND type='final_summary' "
            "ORDER BY timestamp DESC LIMIT 1", (record["session_id"],))
        final_summary: Dict[str, Any] = {}
        if final_rows:
            try:
                final_summary = json.loads(final_rows[0]["value"] or "{}")
            except (TypeError, json.JSONDecodeError):
                final_summary = {}
        night_summary = final_summary.get("night_summary") or {}
        sleep_quality = night_summary.get("sleep_quality")
        if not isinstance(sleep_quality, dict):
            sleep_quality = _sleep_quality_summary(
                record["duration"], night_summary,
                final_summary.get("sleep_state_counts") or {},
                completed=bool(record["end_time"]),
                rest_mode=final_summary.get("rest_mode") or "auto",
            )
        session_report = final_summary.get("session_report")
        health_reference = final_summary.get("health_reference")
        if not isinstance(health_reference, dict):
            health_reference = _health_reference_from_profile(history_profile)
        sessions.append({
            "session_id": record["session_id"], "username": record["user"],
            "display_name": history_profile.get("display_name") or record["user"],
            "gender": record["gender"], "started_at_utc": record["start_time"],
            "ended_at_utc": record["end_time"], "duration_s": record["duration"],
            "end_reason": record["end_reason"], "sample_count": agg["n"],
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
            "sleep_quality": sleep_quality,
            "session_report": session_report if isinstance(session_report, dict) else None,
            "health_reference": health_reference,
            "wellness_context_available": bool(final_summary.get("wellness_context")),
            "summary": {
                "temperature_c": {"avg": round(agg["t"], 1)} if agg["t"] is not None else None,
                "heart_rate_bpm": {"avg": round(agg["hr"], 1)} if agg["hr"] is not None else None,
            },
        })
    return {
        "username": username,
        "account_key": key,
        "display_name": history_profile.get("display_name") or username,
        "health_reference": _health_reference_from_profile(history_profile),
        "sessions": sessions,
        "total": total,
    }


def _compress_sleep_stage_points(
    stage_points: List[Dict[str, Any]],
    *,
    report_end: str,
    sample_interval_s: float = 5.0,
    fallback_estimator: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Compress versioned-cadence decisions into contiguous report periods.

    Raw rounds and their full metrics remain in SQLite. A gap approaching two
    decision intervals deliberately splits a period even when the label on both
    sides is the same, so a missing confirmed epoch can be exposed as WAIT/OFF
    instead of implying continuous Sensor coverage.
    """
    if not stage_points:
        return []
    interval = max(0.1, float(sample_interval_s or 5.0))

    def parsed(value: Any) -> Optional[datetime]:
        try:
            return datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None

    groups: List[List[Dict[str, Any]]] = []
    previous_time: Optional[datetime] = None
    previous_interval = interval
    for point in stage_points:
        current_time = parsed(point.get("window_end") or point.get("timestamp"))
        current_interval = _sample_interval_seconds(
            point.get("sample_interval_s"), interval)
        gap_s = (
            (current_time - previous_time).total_seconds()
            if current_time is not None and previous_time is not None else 0.0
        )
        if (not groups or groups[-1][-1].get("state") != point.get("state")
                or current_interval != previous_interval
                or gap_s > max(previous_interval, current_interval) * 1.8
                or gap_s <= 0.0):
            groups.append([point])
        else:
            groups[-1].append(point)
        previous_time = current_time
        previous_interval = current_interval

    periods: List[Dict[str, Any]] = []
    for points in groups:
        first, last = points[0], points[-1]
        point_intervals = [
            _sample_interval_seconds(point.get("sample_interval_s"), interval)
            for point in points
        ]
        first_end = parsed(first.get("window_end") or first.get("timestamp"))
        last_end = parsed(last.get("window_end") or last.get("timestamp") or report_end)
        first_interval = _sample_interval_seconds(
            first.get("sample_interval_s"), interval)
        start = first_end - timedelta(seconds=first_interval) if first_end else None
        end = last_end or parsed(report_end)
        probabilities: Dict[str, float] = {}
        for state_name in ("wake", "n1", "n2", "n3", "rem"):
            values = [
                float((point.get("probabilities") or {})[state_name])
                for point in points
                if isinstance((point.get("probabilities") or {}).get(state_name), (int, float))
            ]
            if values:
                probabilities[state_name] = round(sum(values) / len(values), 4)
        metrics: Dict[str, Any] = {}
        for key in ("mean_hr", "mean_rr", "movement_ratio"):
            values = [
                float((point.get("metrics") or {})[key])
                for point in points
                if isinstance((point.get("metrics") or {}).get(key), (int, float))
            ]
            if values:
                metrics[key] = round(sum(values) / len(values), 3)
        bed_statuses = [
            str((point.get("metrics") or {}).get("bed_status"))
            for point in points if (point.get("metrics") or {}).get("bed_status")
        ]
        if bed_statuses:
            metrics["bed_status"] = Counter(bed_statuses).most_common(1)[0][0]
        confidences = [point.get("confidence") for point in points if point.get("confidence")]
        confidence = Counter(confidences).most_common(1)[0][0] if confidences else None
        periods.append({
            "start_time": start.isoformat() if start else first.get("timestamp"),
            "end_time": end.isoformat() if end else last.get("timestamp"),
            "calculated_at": last.get("timestamp"),
            # Counted evidence time excludes missing wall-clock gaps.
            "duration_s": round(sum(point_intervals), 1),
            "round_count": len(points),
            "sample_interval_s": (
                point_intervals[0]
                if all(value == point_intervals[0] for value in point_intervals)
                else None
            ),
            "state": first.get("state"),
            "confidence": confidence,
            "probabilities": probabilities,
            "reason": last.get("reason"),
            "metrics": metrics,
            "analysis_window_samples": last.get("sample_count"),
            "state_changed": True,
            "estimator_version": last.get("estimator_version") or fallback_estimator,
            "stage_annotation": last.get("stage_annotation"),
        })
    return periods


@app.get("/api/history/{username}/{session_id}")
def history_detail(
    username: str,
    session_id: str,
    principal: Principal = Depends(require_user),
):
    key = _require_username_access(username, principal)
    rows = database.read_sessions(
        "SELECT * FROM sessions WHERE username_key=? AND session_id=?", (key, session_id))
    if not rows:
        raise HTTPException(404, "ไม่พบ session นี้")
    row = rows[0]
    timeline = database.read_sessions(
        "SELECT * FROM timeline WHERE session_id=? ORDER BY timestamp", (session_id,))
    timeline_interval_s = _timeline_sample_interval(timeline, 5.0)
    canonical_bed_labels = debounced_bed_status_labels(
        [x["bed_status"] for x in timeline])
    samples = []
    for x, canonical_bed in zip(timeline, canonical_bed_labels):
        sample = {
            "t": datetime.fromisoformat(x["timestamp"]).timestamp(),
            "temp": x["temperature"], "hum": x["humidity"], "co2": x["co2"],
            "pm2_5": x["pm2_5"], "voc": x["voc_index"],
            "lux": x["lux"], "dba": x["sound"], "hr": x["heart_rate"],
            "rr": x["respiration_rate"], "bed": canonical_bed,
            "sample_interval_s": timeline_interval_s,
        }
        if principal.is_admin:
            # Admin retains the byte-for-byte historical label for Sensor
            # integrity work; User reports receive the debounced canonical view.
            sample["raw_bed_status"] = x["bed_status"]
        samples.append(sample)
    events = database.read_sessions(
        "SELECT timestamp,type,value FROM events WHERE session_id=? ORDER BY timestamp", (session_id,))
    counters: Dict[str, int] = {}
    final_summary: Dict[str, Any] = {}
    for event in reversed(events):
        if event["type"] != "final_summary":
            continue
        try:
            final_summary = json.loads(event["value"] or "{}")
        except (TypeError, json.JSONDecodeError):
            final_summary = {}
        break
    history_interval_s = _sample_interval_seconds(
        final_summary.get("sample_interval_s"), timeline_interval_s)
    cadence_segments = _normalise_cadence_segments(
        final_summary.get("sample_cadence_segments"),
        start_at_utc=row["start_time"],
        fallback_interval_s=history_interval_s,
    )
    for sample in samples:
        sample["sample_interval_s"] = _cadence_interval_at(
            sample.get("t"), cadence_segments, history_interval_s)
    report_samples, history_interval_s, cadence_summary = (
        _normalise_samples_for_report(samples, history_interval_s)
    )
    stage_points = []
    terminal_wake_event: Optional[Dict[str, Any]] = None
    annotation_rows = [event for event in events
                       if event["type"] == "sleep_stage_annotation"]
    annotations = load_annotations(annotation_rows)
    for event in events:
        if event["type"] == "final_summary":
            continue
        if event["type"] == "sleep_stage":
            try:
                value = json.loads(event["value"] or "{}")
            except (TypeError, json.JSONDecodeError):
                value = {}
            decision_interval_s = _sample_interval_seconds(
                value.get("sample_interval_s"), history_interval_s)
            value, _ = apply_annotations(
                value, event["timestamp"], annotations,
                sample_interval_s=decision_interval_s,
            )
            value["sample_interval_s"] = decision_interval_s
            if value.get("state") in {"wake", "n1", "n2", "n3", "rem"}:
                stage_points.append({"timestamp": event["timestamp"], **value})
            continue
        if event["type"] == "session_terminal_wake":
            try:
                value = json.loads(event["value"] or "{}")
            except (TypeError, json.JSONDecodeError):
                value = {}
            if isinstance(value, dict) and value.get("state") == "wake":
                terminal_wake_event = value
            continue
        kind = event["type"].removeprefix("legacy_counter:")
        amount = int(event["value"]) if event["type"].startswith("legacy_counter:") else 1
        counters[kind] = counters.get(kind, 0) + amount
    # Rebuild the displayed counts from canonical labels every time. Persisted
    # raw Timeline rows remain unchanged and are exposed only to Admin above.
    bed_counts: Dict[str, int] = {}
    for sample in report_samples:
        if sample.get("bed"):
            bed_counts[sample["bed"]] = bed_counts.get(sample["bed"], 0) + 1
    if not bed_counts:
        bed_counts = final_summary.get("bed_status_counts") or {}
    report_end = row["end_time"] or datetime.now(timezone.utc).isoformat()
    # The database retains every versioned-cadence decision for audit/re-scoring. A
    # user report only needs contiguous stage periods; returning all metrics for
    # 3,000+ rounds made one overnight report several MB and overloaded tablets.
    sleep_timeline = _compress_sleep_stage_points(
        stage_points, report_end=report_end, sample_interval_s=history_interval_s,
        fallback_estimator=final_summary.get("sleep_estimator"),
    )
    # Keep terminal occupancy beside, never inside, the five-state Sleep
    # timeline. This closes the visible gap between the final Wake decision and
    # Logout without counting an empty Pod as human Wake or sleep.
    terminal_occupancy = terminal_occupancy_timeline(
        timeline,
        session_end=report_end,
        sample_interval_s=history_interval_s,
    )
    classification_end = (
        terminal_occupancy[0].get("start_time")
        if terminal_occupancy else report_end
    )
    classification_gaps = sleep_classification_gap_timeline(
        sleep_timeline,
        samples,
        session_start=row["start_time"],
        classification_end=classification_end,
        sensor_sample_interval_s=_sample_interval_seconds(
            final_summary.get("sensor_sample_interval_s"), history_interval_s),
    )
    if classification_gaps:
        sleep_timeline = sorted(
            [*sleep_timeline, *classification_gaps],
            key=lambda item: str(item.get("start_time") or ""),
        )
    terminal_wake = final_summary.get("terminal_wake_transition")
    if not isinstance(terminal_wake, dict):
        terminal_wake = terminal_wake_event
    if not isinstance(terminal_wake, dict) and row["end_time"]:
        # Display-only compatibility for Sessions completed before the
        # versioned terminal marker existed. Raw decisions and statistics are
        # untouched; the returned marker states this provenance explicitly.
        terminal_wake = terminal_wake_transition(
            sleep_timeline,
            terminal_occupancy=terminal_occupancy,
            session_end=report_end,
            end_reason=row["end_reason"],
        )
        if terminal_wake:
            terminal_wake["display_reconstructed"] = True
            terminal_wake["persisted_record_unchanged"] = True
    if (
        isinstance(terminal_wake, dict)
        and terminal_wake.get("state") == "wake"
        and sleep_timeline
        and sleep_timeline[-1].get("state") != "wake"
    ):
        sleep_timeline.append(terminal_wake)
    with profile_lock:
        profile = _load_profiles().get(row["username_key"], {})
    night_summary = final_summary.get("night_summary") or {}
    sleep_quality = night_summary.get("sleep_quality")
    if not isinstance(sleep_quality, dict):
        sleep_quality = _sleep_quality_summary(
            row["duration"], night_summary,
            final_summary.get("sleep_state_counts") or {},
            completed=bool(row["end_time"]),
            rest_mode=final_summary.get("rest_mode") or "auto",
            stage_sequence=[{
                "state": point["state"], "metrics": point.get("metrics") or {}
            } for point in stage_points],
            sensor_samples=report_samples,
            sample_interval_s=history_interval_s,
        )
    persisted_session_report = final_summary.get("session_report")
    persisted_report_version = (
        persisted_session_report.get("version")
        if isinstance(persisted_session_report, dict) else None
    )
    session_report = persisted_session_report
    if (
        not isinstance(session_report, dict)
        or persisted_report_version != SESSION_REPORT_VERSION
    ):
        # Backward-compatible display-only read path: old Sessions receive the
        # current Mode-aware report without rewriting their persisted health
        # record.  The prior version remains explicit for auditability.
        session_report = build_session_report(
            row["duration"], report_samples, night_summary,
            final_summary.get("sleep_state_counts") or {}, sleep_quality,
            rest_mode=final_summary.get("rest_mode") or "auto",
            sample_interval_s=history_interval_s,
            estimator_version=final_summary.get("sleep_estimator"),
            completed=bool(row["end_time"]),
            timeline_schema_version=int(
                final_summary.get("timeline_schema_version") or 3),
        )
        session_report["display_recomputed"] = True
        session_report["display_recomputed_from_version"] = persisted_report_version
        session_report["persisted_record_unchanged"] = True
    health_reference = final_summary.get("health_reference")
    if not isinstance(health_reference, dict):
        health_reference = _health_reference_from_profile(profile)
    return {
        "session_id": row["session_id"], "username": row["user"],
        "display_name": profile.get("display_name") or row["user"],
        "account_key": row["username_key"],
        # Legacy response alias retained for existing Admin tools.
        "username_key": row["username_key"], "gender": row["gender"],
        "age": profile.get("age"), "age_group": profile.get("age_group"),
        "health_reference": health_reference,
        "wellness_context": final_summary.get("wellness_context"),
        "started_at_utc": row["start_time"], "ended_at_utc": row["end_time"],
        "duration_s": row["duration"], "end_reason": row["end_reason"],
        "sample_interval_s": history_interval_s,
        "sensor_sample_interval_s": final_summary.get(
            "sensor_sample_interval_s", history_interval_s),
        "sample_cadence_segments": cadence_segments,
        "sample_cadence_summary": (
            final_summary.get("sample_cadence_summary") or cadence_summary),
        "samples": samples,
        "sleep_timeline": sleep_timeline,
        "sleep_timeline_rounds": len(stage_points),
        "sleep_classification_gap_count": len(classification_gaps),
        "sleep_classification_gap_seconds": round(sum(
            float(period.get("duration_s") or 0.0)
            for period in classification_gaps
        ), 1),
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
        "rest_mode": final_summary.get("rest_mode") or "auto",
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
            "sleep_state_counts": final_summary.get("sleep_state_counts") or {},
        },
        "counters": final_summary.get("counters") or counters,
    }


@app.delete("/api/users/{username}", dependencies=[Depends(require_admin)])
def user_delete(username: str):
    """PDPA erasure: remove the profile and every stored session of this user."""
    key = _normalize_account_key(username)
    with session_lock:
        if _active_session is not None and _active_session["record"]["username_key"] == key:
            raise HTTPException(409, "ผู้ใช้นี้กำลังอยู่ใน session — ออกจากระบบก่อนลบ")
    with profile_lock:
        profiles = _load_profiles()
        if key not in profiles:
            raise HTTPException(404, "ไม่พบผู้ใช้นี้")
        removed = profiles.pop(key)
        _save_profiles(profiles)
    records = database.read_sessions(
        "SELECT session_id FROM sessions WHERE username_key=?", (key,))
    for record in records:
        database.enqueue("bcg", "delete_bcg_session", {"session_id": record["session_id"]})
        database.enqueue("sessions", "delete_session", {"session_id": record["session_id"]})
    database.flush(30)
    log_event("session", "user_deleted", user=removed.get("username"),
              sessions_removed=len(records))
    return {"ok": True, "username": removed.get("username"),
            "sessions_removed": len(records)}


# ---------- music ----------
@app.get("/api/music", dependencies=[Depends(require_pod_operator)])
async def music_list():
    exts = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac"}
    tracks = sorted([p.name for p in MUSIC_DIR.iterdir()
                     if p.is_file() and p.suffix.lower() in exts])
    return {"tracks": tracks, "state": snapshot()["music"],
            "player": player.backend}


# Music endpoints are plain `def` on purpose: they call subprocess spawn/wait
# and blocking IPC, so FastAPI runs them in the threadpool instead of the
# event loop (which would freeze websocket updates for every client).
@app.post("/api/music/play", dependencies=[Depends(require_pod_operator)])
def music_play(cmd: TrackCommand):
    global music_stop_guard_until
    _require_safety_allows("เล่นเพลง")
    candidate = (MUSIC_DIR / cmd.track).resolve()
    if MUSIC_DIR.resolve() not in candidate.parents or not candidate.is_file():
        raise HTTPException(404, "Track not found")
    with music_command_lock:
        guard_remaining = music_stop_guard_until - time.monotonic()
        if guard_remaining > 0 and not cmd.user_initiated:
            raise HTTPException(
                409,
                "Music was stopped by the user; legacy automatic restart blocked",
            )
        try:
            player.play(candidate, loop=bool(cmd.loop), queue=bool(cmd.queue))
        except Exception as exc:
            raise HTTPException(500, str(exc))
    note_session_activity("music", {"action": "play", "track": candidate.name,
                                    "loop": bool(cmd.loop), "queue": bool(cmd.queue)})
    log_event("music", "play", track=candidate.name, loop=bool(cmd.loop),
              queue=bool(cmd.queue))
    return {"ok": True, "track": candidate.name, "loop": bool(cmd.loop),
            "queue": bool(cmd.queue), "player": player.backend,
            "state": snapshot()["music"]}


@app.post("/api/music/stop", dependencies=[Depends(require_pod_operator)])
def music_stop():
    global music_stop_guard_until
    with music_command_lock:
        player.stop()
        music_stop_guard_until = time.monotonic() + MUSIC_STOP_GUARD_SECONDS
    # Return the authoritative stopped state immediately. Waiting for the
    # next WebSocket frame left the touch toggle looking active and allowed
    # another browser to mistake Stop for a naturally ended queue item.
    return {"ok": True, "state": snapshot()["music"],
            "restart_guard_seconds": MUSIC_STOP_GUARD_SECONDS}


@app.post("/api/music/pause", dependencies=[Depends(require_pod_operator)])
def music_pause():
    _require_safety_allows("เล่นต่อ/พักเพลง")
    if not player.pause_toggle():
        if player.backend != "mpv":
            raise HTTPException(
                501,
                f"โหมด fallback ({player.backend}) ไม่รองรับ pause — ใช้ stop แล้วเล่นใหม่",
            )
        raise HTTPException(503, "Player IPC not ready — try again")
    return {"ok": True, "state": snapshot()["music"]}


@app.post("/api/music/volume", dependencies=[Depends(require_pod_operator)])
def music_volume(cmd: VolumeCommand):
    player.set_volume(cmd.volume)
    return {"ok": True, "volume": snapshot()["music"]["volume"]}


def _graceful_poweroff() -> None:
    """Drain research data before handing power-off to systemd."""
    time.sleep(1.0)  # allow the HTTP response to reach the tablet
    try:
        with session_lock:
            active = _active_session
        if active is not None:
            _save_active_session_checkpoint(active)
            if active.get("phase") == "recording":
                database.enqueue("sessions", "event", {
                    "session_id": active["record"]["session_id"],
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "type": "service_pause", "value": {"reason": "system_poweroff"},
                })
        bcg_storage.flush()
        database.flush(30)
        daily_backup.stop()
        database.stop(30)
        player.stop()
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


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    cookie_token = ws.cookies.get(COOKIE_NAME)
    principal = auth_sessions.resolve(cookie_token)
    if principal is None:
        await ws.close(code=4401, reason="login required")
        return
    if not principal.is_admin:
        with session_lock:
            active = _active_session
        if active is None or not _principal_owns_active(active, principal):
            await ws.close(code=4403, reason="not pod session owner")
            return
    await ws.accept()
    try:
        while True:
            if not principal.is_admin:
                with session_lock:
                    active = _active_session
                if not _principal_owns_active(active, principal):
                    await ws.close(code=4403, reason="pod session ended")
                    return
            await ws.send_json(snapshot_for(principal))
            await asyncio.sleep(0.5)
    except (WebSocketDisconnect, RuntimeError):
        pass


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
