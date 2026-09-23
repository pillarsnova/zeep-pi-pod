"""Per-user adaptive baselines — เรียนรู้ค่าเฉพาะบุคคลจากคืนแรก ๆ ของเขาเอง

ขอบเขต (ตาม KB governance):
- v1 ใช้เป็น Admin candidate/context สำหรับเทียบ Baseline ตัวเองและ
  สร้างคำแนะนำเชิง advisory; ไม่เปลี่ยน Sleep State โดยตรง
- ห้ามนำผลไปสั่งอุปกรณ์แบบ real-time; ขอบเขต v1 อยู่ที่
  docs/adaptive-control-recommendation-plan-v1.md และการปลุกใช้เวลานาฬิกาเท่านั้น
- ทุกค่าเป็น proxy จาก BCG (ไม่มี EEG) — measure, not promise
"""

from __future__ import annotations

import json
import statistics
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sleep_system_policy import (
    NAP_RECOVERY_MINIMUM_SCORE_SECONDS,
    PERSONAL_BASELINE_DETAIL_SCAN_PER_COHORT,
    PERSONAL_BASELINE_LEARNING_START_LOCAL_DATE,
    PERSONAL_BASELINE_LEARNING_START_TIMEZONE,
    PERSONAL_BASELINE_LEARNING_START_UTC,
    PERSONAL_BASELINE_MAX_NIGHTS,
    PERSONAL_BASELINE_MIN_DETECTED_SLEEP_SECONDS,
    PERSONAL_BASELINE_MIN_HR_SAMPLES,
    PERSONAL_BASELINE_MIN_NIGHTS,
    PERSONAL_BASELINE_MIN_SESSION_SECONDS,
    PERSONAL_BEHAVIOUR_BASELINE_VERSION,
    PERSONAL_REST_WINDOW_BASELINE_VERSION,
    PRE_CONTINUITY_SESSION_REPORT_VERSION,
    PRE_CONTINUITY_SLEEP_QUALITY_VERSION,
    PRE_MINIMUM_ONLY_SESSION_REPORT_VERSION,
    PRE_MINIMUM_ONLY_SLEEP_QUALITY_VERSION,
    PRE_NAP_TIMING_SESSION_REPORT_VERSION,
    PRE_NAP_TIMING_SLEEP_QUALITY_VERSION,
    PRE_RESPIRATORY_SESSION_REPORT_VERSION,
    PRE_RESTORE_SESSION_REPORT_VERSION,
    RESTORE_BASELINE_MIN_COMPARISON_SESSIONS,
    RESTORE_TREND_MAX_SESSIONS,
    SESSION_REPORT_VERSION,
    SLEEP_QUALITY_VERSION,
    ZEEP_SLEEP_BASELINE_VERSION,
    is_approved_sleep_result_version,
    resolve_rest_target,
    rest_mode_group,
)
from identity.account_aliases import (
    account_boundary_keys,
    normalize_account_key,
    verified_legacy_account_keys,
)
from sessions.baseline_cache import BaselineCacheLifecycle
from sessions.personal_behaviour import (
    aggregate_behaviour_by_mode,
    empty_best_rest_window,
    empty_respiratory_reference,
    respiratory_session_values,
)
from sessions.score_identity import assess_score_identity
from sessions.target_provenance import assess_target_provenance

MIN_NIGHTS = PERSONAL_BASELINE_MIN_NIGHTS
MAX_NIGHTS = PERSONAL_BASELINE_MAX_NIGHTS
MIN_SESSION_SECONDS = PERSONAL_BASELINE_MIN_SESSION_SECONDS
MIN_DETECTED_SLEEP_SECONDS = PERSONAL_BASELINE_MIN_DETECTED_SLEEP_SECONDS
MIN_HR_SAMPLES = PERSONAL_BASELINE_MIN_HR_SAMPLES


def _row_value(row: Any, key: str) -> Any:
    """Read a sqlite Row or mapping without changing database adapters."""
    return row.get(key) if hasattr(row, "get") else row[key]


def _baseline_detail_cohort(row: Any) -> str | None:
    """Return the canonical Mode/Target bucket used before detail reads."""
    mode = _row_value(row, "rest_mode")
    group = rest_mode_group(mode)
    if group == "sleep":
        return "sleep"
    if group != "nap_recovery":
        # Older rows may have no canonical mode in Session metadata while the
        # reviewed final report carries it. Inspect a bounded unknown cohort;
        # _behaviour_metrics still performs the authoritative mode/score check.
        return "unresolved"
    target = resolve_rest_target(
        group,
        _row_value(row, "target_duration_s"),
    )
    target_key = (
        str(target.get("key"))
        if target.get("available") is True and target.get("valid") is True
        else "unverified"
    )
    return f"nap_recovery:{target_key}"


def _bounded_baseline_detail_rows(sessions: list[Any]) -> list[Any]:
    """Keep newest detail candidates per cohort with a deterministic bound."""
    selected = []
    counts: dict[str, int] = {}
    for row in sessions:
        cohort = _baseline_detail_cohort(row)
        if cohort is None:
            continue
        count = counts.get(cohort, 0)
        if count >= PERSONAL_BASELINE_DETAIL_SCAN_PER_COHORT:
            continue
        counts[cohort] = count + 1
        selected.append(row)
    return selected


def _clip(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _percentile(values: list, q: float) -> Optional[float]:
    vals = sorted(v for v in values if isinstance(v, (int, float)))
    if not vals:
        return None
    idx = (len(vals) - 1) * q
    lo, hi = int(idx), min(int(idx) + 1, len(vals) - 1)
    frac = idx - lo
    return vals[lo] * (1 - frac) + vals[hi] * frac


def _normalized_baseline_records(value: Any) -> dict[str, Any]:
    """Normalize cache keys and fail closed on conflicting case variants."""
    if not isinstance(value, Mapping):
        return {}
    normalized: dict[str, Any] = {}
    ambiguous: set[str] = set()
    for raw_key, record in value.items():
        key = normalize_account_key(raw_key)
        if not key or key in ambiguous:
            continue
        if key in normalized and normalized[key] != record:
            normalized.pop(key, None)
            ambiguous.add(key)
            continue
        normalized[key] = record
    return normalized


class BaselineStore(BaselineCacheLifecycle):
    """เก็บ/คำนวณ baseline ต่อ account key ลง data/baselines.json.

    ZEEP accounts use normalized email; local fallback retains its local
    username key because it has no remotely verified email.
    """

    def __init__(self, database, data_dir: Path):
        self.database = database
        super().__init__(
            Path(data_dir) / "baselines.json",
            _normalized_baseline_records,
        )
        self.profiles_path = Path(data_dir) / "profiles.json"

    def _profiles_snapshot(self) -> dict[str, Any]:
        """Read one atomic Profile snapshot; malformed data yields no aliases."""
        try:
            with self.profiles_path.open("r", encoding="utf-8") as file:
                profiles = json.load(file)
        except FileNotFoundError:
            return {}
        except (OSError, TypeError, json.JSONDecodeError) as exc:
            print(f"[BASELINE] ignoring invalid profiles.json: {exc}")
            return {}
        return profiles if isinstance(profiles, dict) else {}

    def profile_for(self, username_key: str) -> dict[str, Any]:
        """Return a Profile with only ownership-verified legacy aliases."""
        key = normalize_account_key(username_key)
        profiles = self._profiles_snapshot()
        value = profiles.get(key)
        profile = dict(value) if isinstance(value, Mapping) else {}
        profile["verified_legacy_account_keys"] = list(
            verified_legacy_account_keys(key, profile, profiles)
        )
        return profile

    def _account_keys_for(self, username_key: str) -> tuple[str, ...]:
        key = normalize_account_key(username_key)
        profiles = self._profiles_snapshot()
        value = profiles.get(key)
        profile = dict(value) if isinstance(value, Mapping) else {}
        return account_boundary_keys(key, profile, profiles)

    # ---------- persistence ----------
    def _save_locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=1)
        tmp.replace(self.path)

    def rekey_users(self, mapping: dict[str, str]) -> int:
        """Invalidate alias caches so unified Sessions can be rebuilt safely."""
        changed = 0
        profiles = self._profiles_snapshot()
        with self.lock:
            for old_key, new_key in mapping.items():
                old = normalize_account_key(old_key)
                new = normalize_account_key(new_key)
                if not old or not new or old == new:
                    continue
                value = profiles.get(new)
                profile = dict(value) if isinstance(value, Mapping) else {}
                if old not in account_boundary_keys(new, profile, profiles):
                    continue
                changed += int(self.data.pop(old, None) is not None)
                changed += int(self.data.pop(new, None) is not None)
            if changed:
                self._save_locked()
        return changed

    def rebuild_rekeyed_users(self, mapping: dict[str, str]) -> dict[str, Any]:
        """Rebuild every affected canonical Baseline from unified Sessions."""
        invalidated = self.rekey_users(mapping)
        rebuilt = 0
        errors: dict[str, str] = {}
        for key in sorted({normalize_account_key(value) for value in mapping.values()}):
            if not key:
                continue
            try:
                self.update_user(key)
                rebuilt += 1
            except Exception as exc:
                errors[key] = str(exc)
        return {
            "invalidated": invalidated,
            "rebuilt": rebuilt,
            "errors": errors,
        }

    def delete_user(self, username_key: str) -> bool:
        """Delete one derived Baseline as part of account erasure."""
        key = normalize_account_key(username_key)
        with self.lock:
            record = self.data.pop(key, None)
            if record is None:
                return False
            try:
                self._save_locked()
            except Exception:
                self.data[key] = record
                raise
        return True

    # ---------- learning ----------
    def _night_metrics(
        self,
        session_id: str,
        session_mode: Any = None,
    ) -> Optional[dict]:
        """สกัดตัวชี้วัดของ 1 คืนจาก timeline + final_summary

        ครอบคลุมสิ่งที่ engine ต้องใช้: awake baseline, sleeping median,
        lowest stable, variability, movement baseline, เวลาหลับ/ตื่น, รอบการนอน
        """
        # Personal Sleep Baseline must learn from detected sleep only.  A long
        # meditation/general-rest Session can contain stable HR/RR and would
        # otherwise look deceptively suitable for training.  The final report
        # is the versioned source of truth that separates those use cases.
        events = self.database.read_sessions(
            "SELECT value FROM events WHERE session_id=? AND type='final_summary' "
            "ORDER BY timestamp DESC LIMIT 1",
            (session_id,),
        )
        if not events:
            return None
        try:
            final_summary = json.loads(events[0]["value"] or "{}")
        except (TypeError, json.JSONDecodeError):
            return None
        if not isinstance(final_summary, dict):
            return None
        night = final_summary.get("night_summary") or {}
        report = final_summary.get("session_report") or {}
        quality = night.get("sleep_quality") or report.get("quality") or {}
        explicit_mode = final_summary.get("rest_mode")
        report_mode = report.get("rest_mode")
        session_mode_present = session_mode is not None and bool(
            str(session_mode).strip()
        )
        explicit_mode_present = explicit_mode is not None and bool(
            str(explicit_mode).strip()
        )
        mode = (
            session_mode
            if session_mode_present
            else explicit_mode
            if explicit_mode_present
            else report_mode or "auto"
        )
        related_modes = []
        if session_mode_present:
            related_modes.append(("final_summary.rest_mode", explicit_mode))
            related_modes.append(("session_report.rest_mode", report_mode))
        elif explicit_mode_present:
            related_modes.append(("session_report.rest_mode", report_mode))
        score_identity = assess_score_identity(
            quality,
            mode,
            related_modes=related_modes,
        )
        resolved_mode = (
            mode.get("group") or mode.get("requested") or mode.get("resolved")
            if isinstance(mode, dict)
            else mode
        )
        approved_versions = is_approved_sleep_result_version(
            report.get("version"), quality.get("version")
        )
        if not (
            rest_mode_group(resolved_mode) == "sleep"
            and score_identity["valid"]
            and approved_versions
            and quality.get("available") is True
        ):
            return None
        detected_sleep_s = quality.get(
            "estimated_sleep_s", night.get("estimated_sleep_s")
        )
        try:
            detected_sleep_s = float(detected_sleep_s or 0.0)
        except (TypeError, ValueError, OverflowError):
            detected_sleep_s = 0.0
        if not (
            quality.get("quality_type") == "sleep"
            and quality.get("sleep_detected") is True
            and detected_sleep_s >= MIN_DETECTED_SLEEP_SECONDS
        ):
            return None
        timeline = self.database.read_sessions(
            "SELECT timestamp,temperature,humidity,co2,lux,sound,pm2_5,voc_index,"
            "heart_rate,respiration_rate,bed_status "
            "FROM timeline WHERE session_id=? ORDER BY timestamp",
            (session_id,),
        )
        stage_events = self.database.read_sessions(
            "SELECT timestamp,value FROM events WHERE session_id=? "
            "AND type='sleep_stage' ORDER BY timestamp,id",
            (session_id,),
        )

        def event_epoch(value: Any) -> Optional[float]:
            if isinstance(value, (int, float)):
                return float(value)
            try:
                return datetime.fromisoformat(
                    str(value).replace("Z", "+00:00")
                ).timestamp()
            except (TypeError, ValueError, OverflowError):
                return None

        eligible_intervals: list[tuple[float, float, str]] = []
        for event in stage_events:
            try:
                value = json.loads(event["value"] or "{}")
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(value, dict):
                continue
            stage = str(value.get("state") or "").lower()
            if stage not in {"wake", "n1", "n2", "n3", "rem"}:
                continue
            if (
                value.get("provisional") is True
                or value.get("score_eligible") is False
                or value.get("excluded_from_personal_baseline") is True
            ):
                continue
            end = event_epoch(value.get("attribution_end"))
            if end is None:
                end = event_epoch(value.get("window_end"))
            if end is None:
                try:
                    event_timestamp = event["timestamp"]
                except (KeyError, TypeError):
                    event_timestamp = None
                end = event_epoch(event_timestamp)
            interval = value.get("sample_interval_s", 30.0)
            try:
                interval = max(1.0, float(interval))
            except (TypeError, ValueError, OverflowError):
                interval = 30.0
            start = event_epoch(value.get("attribution_start"))
            if start is None and end is not None:
                start = end - interval
            if start is not None and end is not None and end > start:
                eligible_intervals.append((start, end, stage))

        def eligible_stage(row: Any) -> Optional[str]:
            position = event_epoch(row["timestamp"])
            if position is None:
                return None
            return next(
                (
                    stage
                    for start, end, stage in eligible_intervals
                    if start < position <= end + 0.001
                ),
                None,
            )

        if stage_events:
            # Current-version Sessions explicitly carry baseline eligibility.
            # Honour it: provisional and continuity-carried rows never teach
            # the personal physiology model even when their display State is
            # retained for timeline completeness.
            staged_timeline = [(row, eligible_stage(row)) for row in timeline]
            quiet_rows = [
                row
                for row, stage in staged_timeline
                if stage in {"n1", "n2", "n3", "rem"}
                and row["bed_status"] in ("On bed", "Snoring", "Weak breathing")
            ]
            wake_rows = [row for row, stage in staged_timeline if stage == "wake"]
            eligible_rows = [row for row, stage in staged_timeline if stage is not None]
            moving_rows = [
                row for row in eligible_rows if row["bed_status"] == "Moving"
            ]
            baseline_stage_filter = "direct_score_eligible_stage_intervals"
        else:
            # Compatibility for an older approved Session whose event schema
            # predates explicit eligibility metadata.
            quiet_rows = [
                row
                for row in timeline
                if row["bed_status"] in ("On bed", "Snoring", "Weak breathing")
            ]
            wake_rows = list(timeline[:20])
            eligible_rows = list(timeline)
            moving_rows = [row for row in timeline if row["bed_status"] == "Moving"]
            baseline_stage_filter = "legacy_approved_timeline_fallback"
        quiet_hr = [r["heart_rate"] for r in quiet_rows if r["heart_rate"]]
        if len(quiet_hr) < MIN_HR_SAMPLES:
            return None
        # rolling CV (6 จุด × 10 วินาที ≈ 1 นาที) — ความ "เรียบ" ของ HR ตอนนิ่ง
        cvs = []
        for i in range(len(quiet_hr) - 5):
            win = quiet_hr[i : i + 6]
            mean = sum(win) / len(win)
            if mean > 0:
                cvs.append(statistics.pstdev(win) / mean)
        rrs = [r["respiration_rate"] for r in quiet_rows if r["respiration_rate"]]
        temps = [r["temperature"] for r in timeline if r["temperature"] is not None]
        humidity = [r["humidity"] for r in timeline if r["humidity"] is not None]
        co2 = [r["co2"] for r in timeline if r["co2"] is not None]
        lux = [r["lux"] for r in timeline if r["lux"] is not None]
        sound = [r["sound"] for r in timeline if r["sound"] is not None]
        # Do not treat every Moving row as awake: physiological sleep movement,
        # position changes and blanket adjustment can all load the bed sensor.
        # Until a time-aligned Wake decision is queried here, use only the
        # initial settling samples as the conservative awake-baseline proxy.
        awake_hr = [r["heart_rate"] for r in wake_rows if r["heart_rate"]]
        # lowest stable: ค่าต่ำจริงแบบไม่เอา outlier (p10 ของช่วงนิ่ง)
        low_stable = _percentile(quiet_hr, 0.10)
        metrics = {
            "hr_quiet_median": round(statistics.median(quiet_hr), 1),
            "hr_awake_median": round(statistics.median(awake_hr), 1)
            if awake_hr
            else None,
            "hr_low_stable": round(low_stable, 1) if low_stable else None,
            "hr_sleep_p25": round(_percentile(quiet_hr, 0.25), 1),
            "cv_p25": round(_percentile(cvs, 0.25), 4) if cvs else None,
            "cv_median": round(statistics.median(cvs), 4) if cvs else None,
            "cv_p75": round(_percentile(cvs, 0.75), 4) if cvs else None,
            "rr_median": round(statistics.median(rrs), 1) if rrs else None,
            "rr_low_stable": round(_percentile(rrs, 0.10), 1) if rrs else None,
            "move_ratio": (
                round(len(moving_rows) / len(eligible_rows), 3)
                if eligible_rows
                else None
            ),
            "temp_median": round(statistics.median(temps), 1) if temps else None,
            "humidity_median": round(statistics.median(humidity), 1)
            if humidity
            else None,
            "co2_median": round(statistics.median(co2), 1) if co2 else None,
            "lux_median": round(statistics.median(lux), 1) if lux else None,
            "sound_median": round(statistics.median(sound), 1) if sound else None,
        }
        # เวลาที่มักหลับ/ตื่น (ชั่วโมงท้องถิ่นแบบทศนิยม) จาก timeline จริง
        try:
            local_zone = ZoneInfo(PERSONAL_BASELINE_LEARNING_START_TIMEZONE)
            first = datetime.fromisoformat(timeline[0]["timestamp"]).astimezone(
                local_zone
            )
            last = datetime.fromisoformat(timeline[-1]["timestamp"]).astimezone(
                local_zone
            )
            metrics["bed_hour"] = round(first.hour + first.minute / 60, 2)
            metrics["rise_hour"] = round(last.hour + last.minute / 60, 2)
        except Exception:
            pass
        # onset / disruptions จาก final_summary (บันทึกตอน finalize)
        metrics["onset_proxy_s"] = night.get("sleep_onset_proxy_s")
        metrics["disruptions"] = night.get("awakenings")
        metrics["efficiency"] = night.get("sleep_efficiency")
        metrics["deep_ratio"] = night.get("deep_ratio")
        metrics["rem_ratio"] = night.get("rem_ratio")
        metrics["wellness_score"] = night.get("wellness_score")
        metrics["detected_sleep_s"] = round(detected_sleep_s, 1)
        metrics["baseline_stage_filter"] = baseline_stage_filter
        resolved_mode = (
            str(mode.get("resolved") or mode.get("requested") or "auto")
            if isinstance(mode, dict)
            else str(mode or "auto")
        )
        metrics["rest_mode"] = resolved_mode
        metrics["mode_group"] = rest_mode_group(
            mode.get("group")
            if isinstance(mode, dict) and mode.get("group")
            else resolved_mode
        )
        # รอบการนอน: ประมาณจากช่วงเวลาระหว่างจุดเริ่ม REM ที่ต่อเนื่องกัน
        cycles = night.get("cycle_seconds_observed")
        if cycles:
            metrics["cycle_seconds"] = cycles
        return metrics

    def _behaviour_metrics(
        self,
        session_id: str,
        duration_s: float,
        session_mode: Any = None,
        target_duration_s: Any = None,
        start_time: Any = None,
    ) -> Optional[dict]:
        """Extract mode-aware behaviour without requiring detected sleep.

        Nap & Refresh may be useful while the participant remains awake.  Its
        timing and preferred environment belong in the longitudinal wellness
        pattern, but must never enter the physiology baseline or select a
        W/N1/N2/N3/REM state.
        """
        events = self.database.read_sessions(
            "SELECT value FROM events WHERE session_id=? AND type='final_summary' "
            "ORDER BY timestamp DESC LIMIT 1",
            (session_id,),
        )
        if not events:
            return None
        try:
            final_summary = json.loads(events[0]["value"] or "{}")
        except (TypeError, json.JSONDecodeError):
            return None
        if not isinstance(final_summary, dict):
            return None
        night = final_summary.get("night_summary") or {}
        report = final_summary.get("session_report") or {}
        quality = night.get("sleep_quality") or report.get("quality") or {}
        protocol_status = (quality.get("rest_mode") or {}).get("protocol_status") or {}
        # A result can remain useful to the participant while its Mode/lifecycle
        # timing still needs Admin review. Do not let that outlier teach the
        # target-specific Personal Baseline until a reviewed workflow exists.
        if protocol_status.get("review_required") is True:
            return None
        environment_assessment = report.get("environment_assessment") or {}
        if (
            quality.get("safety_review_required") is True
            or environment_assessment.get("safety_review_required") is True
        ):
            return None
        score_confidence_level = str(
            (quality.get("score_confidence") or {}).get("level") or "unknown"
        )
        explicit_mode = final_summary.get("rest_mode")
        report_mode = report.get("rest_mode")
        session_mode_present = session_mode is not None and bool(
            str(session_mode).strip()
        )
        explicit_mode_present = explicit_mode is not None and bool(
            str(explicit_mode).strip()
        )
        mode = (
            session_mode
            if session_mode_present
            else explicit_mode
            if explicit_mode_present
            else report_mode or "auto"
        )
        related_modes = []
        if session_mode_present:
            related_modes.append(("final_summary.rest_mode", explicit_mode))
            related_modes.append(("session_report.rest_mode", report_mode))
        elif explicit_mode_present:
            related_modes.append(("session_report.rest_mode", report_mode))
        score_identity = assess_score_identity(
            quality,
            mode,
            related_modes=related_modes,
        )
        resolved = (
            str(mode.get("resolved") or mode.get("requested") or "auto")
            if isinstance(mode, dict)
            else str(mode or "auto")
        )
        group = rest_mode_group(
            mode.get("group")
            if isinstance(mode, dict) and mode.get("group")
            else resolved
        )
        current_versions = (
            report.get("version") == SESSION_REPORT_VERSION
            and quality.get("version") == SLEEP_QUALITY_VERSION
        )
        compatible_pre_nap_timing_versions = (
            report.get("version") == PRE_NAP_TIMING_SESSION_REPORT_VERSION
            and quality.get("version") == PRE_NAP_TIMING_SLEEP_QUALITY_VERSION
        )
        compatible_pre_minimum_only_versions = (
            report.get("version") == PRE_MINIMUM_ONLY_SESSION_REPORT_VERSION
            and quality.get("version") == PRE_MINIMUM_ONLY_SLEEP_QUALITY_VERSION
        )
        compatible_current_quality_versions = (
            report.get("version") == PRE_RESPIRATORY_SESSION_REPORT_VERSION
            and quality.get("version") == SLEEP_QUALITY_VERSION
        )
        compatible_previous_versions = (
            report.get("version")
            in {
                PRE_CONTINUITY_SESSION_REPORT_VERSION,
                PRE_RESTORE_SESSION_REPORT_VERSION,
            }
            and quality.get("version") == PRE_CONTINUITY_SLEEP_QUALITY_VERSION
        )
        approved_untouched_sleep = (
            group == "sleep"
            and is_approved_sleep_result_version(
                report.get("version"), quality.get("version")
            )
        )
        if not (
            group is not None
            and score_identity["valid"]
            and quality.get("available") is True
            and (
                current_versions
                or compatible_pre_minimum_only_versions
                or compatible_pre_nap_timing_versions
                or compatible_current_quality_versions
                or compatible_previous_versions
                or approved_untouched_sleep
            )
        ):
            return None
        target_provenance = assess_target_provenance(
            group,
            target_duration_s,
            quality.get("duration_target"),
            quality.get("formula_version"),
        )
        if target_provenance.get("valid_for_score") is False:
            return None
        timeline = self.database.read_sessions(
            "SELECT timestamp,temperature,humidity,co2,lux,sound "
            "FROM timeline WHERE session_id=? ORDER BY timestamp",
            (session_id,),
        )

        def median_field(name: str) -> Optional[float]:
            values = [float(row[name]) for row in timeline if row[name] is not None]
            return round(statistics.median(values), 2) if values else None

        local_zone = ZoneInfo(PERSONAL_BASELINE_LEARNING_START_TIMEZONE)
        timestamp = timeline[0]["timestamp"] if timeline else start_time
        try:
            first = datetime.fromisoformat(str(timestamp)).astimezone(local_zone)
        except (TypeError, ValueError):
            return None
        detected_sleep_s = quality.get(
            "estimated_sleep_s", night.get("estimated_sleep_s")
        )
        try:
            detected_sleep_s = max(0.0, float(detected_sleep_s or 0.0))
        except (TypeError, ValueError, OverflowError):
            detected_sleep_s = 0.0
        respiratory_values = respiratory_session_values(
            report.get("respiratory_wellness")
        )
        target = target_provenance.get("target") or resolve_rest_target(
            group or resolved,
            target_duration_s,
        )
        target_verified = target_provenance.get("verified") is True
        return {
            "session_id": session_id,
            "rest_mode": resolved,
            "mode_group": group,
            "target_key": (
                target.get("key")
                if target_verified and target.get("available")
                else None
            ),
            "duration_s": round(max(0.0, float(duration_s or 0.0)), 1),
            "onset_proxy_s": night.get("sleep_onset_proxy_s"),
            "start_local_hour": round(first.hour + first.minute / 60.0, 2),
            "sleep_detected": bool(detected_sleep_s > 0),
            "detected_sleep_s": round(detected_sleep_s, 1),
            "wellness_score": quality.get("score"),
            "score_formula_version": str(quality.get("formula_version") or "").strip(),
            "score_confidence_level": score_confidence_level,
            "baseline_reference_eligible": score_confidence_level != "low",
            "outcome_reference_eligible": score_confidence_level in {"medium", "high"},
            "environment_reference_eligible": score_confidence_level
            in {"medium", "high"},
            "temp_median": median_field("temperature"),
            "humidity_median": median_field("humidity"),
            "co2_median": median_field("co2"),
            "lux_median": median_field("lux"),
            "sound_median": median_field("sound"),
            **respiratory_values,
        }

    def update_user(self, username_key: str) -> dict:
        """Rebuild physiology and behaviour from the approved cutover onward."""
        canonical_key = normalize_account_key(username_key)
        if not canonical_key:
            raise ValueError("username_key is required for Baseline rebuild")
        account_keys = self._account_keys_for(canonical_key)
        placeholders = ",".join("?" for _key in account_keys)
        # Read lightweight metadata once, partition it by canonical Mode and
        # Nap target, then cap expensive report/timeline reads per cohort. A
        # busy Overnight history cannot hide Nap 30/90, and rebuild cost no
        # longer grows without bound as an account accumulates Sessions.
        sessions = self.database.read_sessions(
            "SELECT session_id,duration,start_time,rest_mode,target_duration_s "
            "FROM sessions "
            f"WHERE lower(trim(username_key)) IN ({placeholders}) "
            "AND end_time IS NOT NULL AND duration>=? "
            "AND julianday(start_time)>=julianday(?) "
            "ORDER BY julianday(start_time) DESC",
            (
                *account_keys,
                min(
                    MIN_SESSION_SECONDS,
                    NAP_RECOVERY_MINIMUM_SCORE_SECONDS,
                ),
                PERSONAL_BASELINE_LEARNING_START_UTC,
            ),
        )
        detail_sessions = _bounded_baseline_detail_rows(list(sessions))
        nights = []
        behaviour_sessions = []
        for row in detail_sessions:
            row_mode = _row_value(row, "rest_mode")
            behaviour = self._behaviour_metrics(
                row["session_id"],
                row["duration"],
                row_mode,
                _row_value(row, "target_duration_s"),
                _row_value(row, "start_time"),
            )
            if behaviour:
                behaviour_sessions.append(behaviour)
            duration = max(0.0, float(row["duration"] or 0.0))
            m = (
                self._night_metrics(row["session_id"], row_mode)
                if duration >= MIN_SESSION_SECONDS and len(nights) < MAX_NIGHTS
                else None
            )
            if m:
                m["session_id"] = row["session_id"]
                m["duration_s"] = round(duration, 1)
                nights.append(m)
        physiology_nights = nights
        record: dict[str, Any] = {
            "policy_version": ZEEP_SLEEP_BASELINE_VERSION,
            "behaviour_policy_version": PERSONAL_BEHAVIOUR_BASELINE_VERSION,
            "rest_window_policy_version": PERSONAL_REST_WINDOW_BASELINE_VERSION,
            "intended_use": "personal_wellness_baseline_not_diagnosis",
            "updated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "learning_cutoff": {
                "local_date": PERSONAL_BASELINE_LEARNING_START_LOCAL_DATE,
                "timezone": PERSONAL_BASELINE_LEARNING_START_TIMEZONE,
                "utc": PERSONAL_BASELINE_LEARNING_START_UTC,
                "older_sessions_excluded": True,
                "raw_sensor_deleted": False,
            },
            "nights_used": len(physiology_nights),
            "min_nights": MIN_NIGHTS,
            "status": "active" if len(physiology_nights) >= MIN_NIGHTS else "learning",
            "nights": physiology_nights,
        }
        if physiology_nights:
            agg = lambda key: [
                n[key] for n in physiology_nights if n.get(key) is not None
            ]  # noqa: E731
            med = lambda key: (
                round(statistics.median(agg(key)), 4)  # noqa: E731
                if agg(key)
                else None
            )
            record.update(
                {
                    # ค่าที่ engine ใช้ตัดสิน (ชื่อ field ตรงกับ SleepEngine)
                    "hr_awake_median": med("hr_awake_median"),
                    "hr_sleep_median": med("hr_quiet_median"),
                    "hr_low_stable": med("hr_low_stable"),
                    "rr_sleep_median": med("rr_median"),
                    "rr_low_stable": med("rr_low_stable"),
                    "cv_p25": med("cv_p25"),
                    "cv_median": med("cv_median"),
                    "cv_p75": med("cv_p75"),
                    "move_ratio_median": med("move_ratio"),
                    "cycle_seconds_median": med("cycle_seconds"),
                    "bed_hour_median": med("bed_hour"),
                    "rise_hour_median": med("rise_hour"),
                    # ค่าเชิงผลลัพธ์ไว้เทียบความคืบหน้า
                    "temp_median": med("temp_median"),
                    "onset_proxy_median_s": med("onset_proxy_s"),
                    "disruptions_median": med("disruptions"),
                    "efficiency_median": med("efficiency"),
                    "deep_ratio_median": med("deep_ratio"),
                    "rem_ratio_median": med("rem_ratio"),
                }
            )
        # Behaviour is partitioned by mode and is descriptive only.  Mixing a
        # 30-minute nap with an overnight Session would make expected latency,
        # duration and environment meaningless.  At least three prior Sessions
        # in the same mode are required before the profile is active.
        record["behaviour_by_mode"] = aggregate_behaviour_by_mode(
            behaviour_sessions,
            minimum_sessions=MIN_NIGHTS,
            score_minimum_sessions=RESTORE_BASELINE_MIN_COMPARISON_SESSIONS,
            max_sessions=RESTORE_TREND_MAX_SESSIONS,
        )
        if (
            record["status"] == "active"
            and record.get("cv_p25")
            and record.get("cv_p75")
        ):
            # เกณฑ์ส่วนบุคคล: DEEP = เรียบกว่า "ช่วงเรียบสุดของตัวเอง" เล็กน้อย,
            # REM = แกว่งกว่าช่วงบนของตัวเองชัดเจน · clip กันหลุดโลก + กันชนกัน
            cv_deep = _clip(record["cv_p25"] * 0.9, 0.015, 0.040)
            cv_rem = _clip(record["cv_p75"] * 1.6, 0.050, 0.090)
            if cv_rem < cv_deep + 0.02:
                cv_rem = cv_deep + 0.02
            record["thresholds"] = {
                "cv_deep": round(cv_deep, 4),
                "cv_rem": round(cv_rem, 4),
            }
        with self.lock:
            self.data[canonical_key] = record
            self._save_locked()
        return record

    # ---------- read side ----------
    def get(self, username_key: str) -> Optional[dict]:
        key = normalize_account_key(username_key)
        account_keys = self._account_keys_for(key)
        candidate_keys = (key, *(item for item in account_keys if item != key))
        with self.lock:
            for candidate in candidate_keys:
                record = self.data.get(candidate)
                if not isinstance(record, dict):
                    continue
                cutoff = record.get("learning_cutoff") or {}
                # Never let a pre-cutover baseline silently influence a new
                # pilot Session while asynchronous rebuild is pending.
                if (
                    record.get("policy_version") != ZEEP_SLEEP_BASELINE_VERSION
                    or record.get("behaviour_policy_version")
                    != PERSONAL_BEHAVIOUR_BASELINE_VERSION
                    or record.get("rest_window_policy_version")
                    != PERSONAL_REST_WINDOW_BASELINE_VERSION
                    or cutoff.get("utc") != PERSONAL_BASELINE_LEARNING_START_UTC
                ):
                    continue
                return record
            return None

    def thresholds_for(self, username_key: str) -> Optional[dict]:
        """คืนเกณฑ์ส่วนบุคคลเมื่อเรียนรู้ครบแล้วเท่านั้น (ไม่ครบ → None = ใช้ค่ากลาง)"""
        record = self.get(username_key)
        if record and record.get("status") == "active" and record.get("thresholds"):
            return dict(record["thresholds"])
        return None

    def behaviour_context(
        self,
        username_key: str,
        rest_mode: str,
        target_duration_s: Any = None,
    ) -> dict:
        """Return prior-only, same-mode behaviour without selecting a stage."""
        record = self.get(username_key) or {}
        requested = str(rest_mode or "auto").strip().lower()
        group = rest_mode_group(requested) or requested
        grouped = record.get("behaviour_by_mode")
        stored = grouped.get(group) if isinstance(grouped, dict) else None
        context = dict(stored) if isinstance(stored, dict) else {}
        same_mode_respiratory = context.get("respiratory_reference")
        target = resolve_rest_target(rest_mode, target_duration_s)
        if group == "nap_recovery":
            by_target = context.get("by_target")
            target_context = (
                by_target.get(target.get("key"))
                if isinstance(by_target, dict) and target.get("available")
                else None
            )
            context = dict(target_context) if isinstance(target_context, dict) else {}
        if not context:
            context = {
                "status": "no_data",
                "sessions_used": 0,
                "minimum_sessions": MIN_NIGHTS,
                "expected_onset_minutes": None,
                "typical_duration_minutes": None,
                "typical_start_local_hour": None,
                "typical_environment": {},
                "respiratory_reference": empty_respiratory_reference("no_data"),
                "scores": [],
                "score_median": None,
                "score_typical_range": None,
                "score_reference": {
                    "status": "learning",
                    "sessions_used": 0,
                    "minimum_sessions": (RESTORE_BASELINE_MIN_COMPARISON_SESSIONS),
                    "median": None,
                    "typical_range": None,
                    "method": "median_and_interquartile_range",
                    "same_mode_only": True,
                    "same_target_only": group == "nap_recovery",
                    "prior_completed_sessions_only": True,
                    "formula_version": None,
                },
                "score_formula_versions": [],
                "best_rest_window": empty_best_rest_window(
                    group,
                    target.get("key") if target.get("available") else None,
                ),
                "direct_stage_influence": False,
                "role": "expectation_report_and_confidence_context_only",
            }
        if group == "nap_recovery" and isinstance(same_mode_respiratory, dict):
            context["respiratory_reference"] = dict(same_mode_respiratory)
        context["baseline_policy_version"] = record.get("behaviour_policy_version")
        context.setdefault(
            "best_rest_window",
            empty_best_rest_window(
                group,
                target.get("key") if target.get("available") else None,
            ),
        )
        context["target_specific"] = bool(context.get("target_specific"))
        context["mode_group"] = group
        context["source"] = (
            "prior_completed_same_mode_and_target_sessions_only"
            if context["target_specific"]
            else "prior_completed_same_mode_sessions_only"
        )
        return context

    def ensure_rest_window_current(self, username_key: str) -> dict:
        """Lazily rebuild one account after the rest-window schema changes."""
        record = self.get(username_key)
        if (
            isinstance(record, dict)
            and record.get("rest_window_policy_version")
            == PERSONAL_REST_WINDOW_BASELINE_VERSION
        ):
            return record
        try:
            return self.update_user(username_key)
        except Exception:
            # Read paths remain available if a one-time derived-data refresh
            # cannot complete; the bounded projection will fail closed.
            return record or {}

    def personalize_baseline(
        self, username_key: str, age_baseline: dict
    ) -> tuple[dict, dict]:
        """Build a reviewable personal HR/RR baseline candidate.

        The caller must honour ``PERSONAL_BASELINE_STAGE_INFLUENCE_ENABLED``.
        During this pilot the adjusted value is Admin/context telemetry only;
        stage selection continues to use the age/gender starting prior.
        """
        record = self.get(username_key)
        meta = {
            "source": "age_gender_default",
            "status": (record or {}).get("status", "no_data"),
            "nights_used": (record or {}).get("nights_used", 0),
            "min_nights": MIN_NIGHTS,
        }
        if not record or record.get("status") != "active":
            return age_baseline, meta

        hr_sleep = record.get("hr_sleep_median")
        hr_awake = record.get("hr_awake_median")
        rr_sleep = record.get("rr_sleep_median")
        if not hr_sleep:
            return age_baseline, meta

        # จุดอ้างอิงกลางของ age baseline สำหรับ N2 (default sleep state)
        ref_hr = sum(age_baseline["n2"]["hr"]) / 2
        hr_shift = round(hr_sleep - ref_hr, 1)
        # จำกัดการเลื่อนไม่ให้หลุดจริง (คนหนึ่งคนไม่ควรต่างจาก population เกิน 15 bpm)
        hr_shift = _clip(hr_shift, -15.0, 15.0)
        rr_shift = 0.0
        if rr_sleep:
            ref_rr = sum(age_baseline["n2"]["rr"]) / 2
            rr_shift = _clip(round(rr_sleep - ref_rr, 1), -4.0, 4.0)

        adjusted = {
            stage: {
                "hr": tuple(round(x + hr_shift, 1) for x in ranges["hr"]),
                "rr": tuple(round(x + rr_shift, 1) for x in ranges["rr"]),
            }
            for stage, ranges in age_baseline.items()
        }
        meta.update(
            {
                "source": "personal",
                "hr_shift": hr_shift,
                "rr_shift": rr_shift,
                "hr_sleep_median": hr_sleep,
                "hr_awake_median": hr_awake,
                "hr_low_stable": record.get("hr_low_stable"),
                "cv_p25": record.get("cv_p25"),
                "cv_p75": record.get("cv_p75"),
                "move_ratio_median": record.get("move_ratio_median"),
                "bed_hour_median": record.get("bed_hour_median"),
                "rise_hour_median": record.get("rise_hour_median"),
                "note": (
                    f"ปรับจากค่าเฉลี่ยของคุณเอง {record['nights_used']} คืนล่าสุด "
                    f"(HR เลื่อน {hr_shift:+.1f} bpm)"
                ),
            }
        )
        return adjusted, meta

    def recommendations(self, username_key: str) -> list[str]:
        """คำแนะนำเชิง advisory (ภาษาไทย, measure-not-promise) — คนกดปุ่มเอง"""
        record = self.get(username_key)
        tips: list[str] = []
        if not record or record["nights_used"] == 0:
            return [
                "ยังไม่มี Session ที่เรียนรู้ได้ — ต้องบันทึกมากกว่า 25 นาทีและมี HR/RR ครบตามเกณฑ์ "
                f"สัก {MIN_NIGHTS} คืน ระบบจะเริ่มปรับค่าตามตัวคุณ"
            ]
        if record["status"] == "learning":
            tips.append(
                f"กำลังเรียนรู้ค่าของคุณ: {record['nights_used']}/{MIN_NIGHTS} คืน "
                "— ระหว่างนี้ใช้เกณฑ์กลางไปก่อน"
            )
        onset = record.get("onset_proxy_median_s")
        if onset and onset > 30 * 60:
            tips.append(
                "ช่วงที่ผ่านมาใช้เวลากว่าจะนิ่ง ~"
                f"{round(onset / 60)} นาที — ลองเปิด 'ก่อนนอน · Wind-down Mix' "
                "ก่อนขึ้นเตียง แล้วดูว่าตัวเลขคืนถัดไปเปลี่ยนไหม"
            )
        disruptions = record.get("disruptions_median")
        if disruptions and disruptions >= 2:
            tips.append(
                f"มีช่วงสะดุดกลางคืนเฉลี่ย ~{round(disruptions)} ครั้ง/คืน — "
                "ลองเสียง 'ฝนพรำ' แบบวนซ้ำเพื่อกลบเสียงรบกวน แล้วเทียบผล"
            )
        temp = record.get("temp_median")
        if temp:
            tips.append(
                f"คืนที่บันทึกได้ อุณหภูมิในตู้ของคุณอยู่ราว {temp}°C — จดค่านี้ไว้เทียบเมื่อปรับสภาพแวดล้อม"
            )
        if record.get("thresholds"):
            tips.append(
                "ระบบมี baseline ส่วนบุคคลไว้ประกอบรายงานและความเชื่อมั่นแล้ว "
                "แต่ยังไม่ใช้เลือก Sleep State โดยตรง"
            )
        tips.append(
            "คำแนะนำเป็น advisory จากข้อมูลของคุณเอง — ไม่ใช่คำสัญญาผล "
            "และระบบไม่สั่งอุปกรณ์อัตโนมัติจาก sleep state (รอ G2)"
        )
        return tips
