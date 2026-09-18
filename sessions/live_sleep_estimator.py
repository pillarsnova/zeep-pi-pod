"""Live Sleep estimator orchestration with explicit runtime dependencies.

The existing formula is preserved during the incremental module migration.
"""

from __future__ import annotations

import math
import time
from datetime import UTC, datetime
from typing import Any

from sessions.live_sleep_runtime import LiveSleepRuntime


def estimate_sleep_state(runtime: LiveSleepRuntime) -> dict[str, Any]:
    """Five-state wellness estimate with explainable probabilities."""
    now = time.time()
    with runtime.history_lock:
        # Current stage morphology uses 60 s; onset/transition direction uses
        # up to 270 s so a single noisy 10-second frame cannot manufacture N1.
        long_frame_count = max(
            runtime.SLEEP_MIN_FRAMES,
            int(
                math.ceil(
                    runtime.SLEEP_LONG_CONTEXT_SECONDS / runtime.SLEEP_SAMPLE_SECONDS
                )
            ),
        )
        context_frames = list(runtime.sleep_feature_history)[-long_frame_count:]
        # Never mix physiology from opposite sides of a Sensor interruption.
        # Keeping old deque entries is useful for audit, but a new 60-second
        # scoring window must be built entirely from contiguous fresh frames.
        latest_gap_index = -1
        for index in range(1, len(context_frames)):
            before = context_frames[index - 1].get("t")
            after = context_frames[index].get("t")
            if (
                isinstance(before, int | float)
                and isinstance(after, int | float)
                and float(after) - float(before)
                >= runtime.SLEEP_CONTEXT_RESET_GAP_SECONDS
            ):
                latest_gap_index = index
        if latest_gap_index >= 0:
            context_frames = context_frames[latest_gap_index:]
        frames = context_frames[-runtime.SLEEP_MIN_FRAMES :]
    with runtime.state_lock:
        age = runtime.state["session"].get("age")
        selected_age_group = runtime.state["session"].get("age_group")
        gender = runtime.state["session"].get("gender")
        session_started = runtime.state["session"].get("started_at")
        active_session_id = runtime.state["session"].get("session_id")
        session_active = bool(runtime.state["session"].get("active"))
        session_recording = bool(runtime.state["session"].get("recording"))
        rest_mode = runtime.state["session"].get("rest_mode") or "auto"
        target_duration_s = runtime.state["session"].get("target_duration_s")
    age_group = (
        selected_age_group
        if selected_age_group in runtime.AGE_SLEEP_BASELINES
        else runtime._age_group(age)
    )
    age_baseline = runtime.AGE_SLEEP_BASELINES[age_group]
    baseline, gender_adjustment = runtime._gender_adjusted_baseline(age_group, gender)
    # Build a reviewable HR/RR candidate after the minimum history. In v1 it is
    # Admin context and is not a Stage source while direct influence is disabled.
    with runtime.state_lock:
        _account_key = runtime.state["session"].get("account_key")
    personal_meta = {"source": "age_gender_default", "status": "no_session"}
    proposed_personal_baseline = None
    if _account_key:
        proposed_personal_baseline, personal_meta = (
            runtime.baselines.personalize_baseline(_account_key, baseline)
        )
        personal_meta = {
            **personal_meta,
            "direct_stage_influence": runtime.PERSONAL_BASELINE_STAGE_INFLUENCE_ENABLED,
            "candidate_available": proposed_personal_baseline != baseline,
        }
    baseline_candidate_source = personal_meta.get("source", "age_gender_default")
    classification_source = "age_gender_default"
    if (
        runtime.PERSONAL_BASELINE_STAGE_INFLUENCE_ENABLED
        and baseline_candidate_source == "personal"
        and proposed_personal_baseline is not None
    ):
        baseline = proposed_personal_baseline
        classification_source = "personal"
    personal_behaviour = (
        runtime.baselines.behaviour_context(_account_key, rest_mode, target_duration_s)
        if _account_key
        else {
            "status": "no_session",
            "sessions_used": 0,
            "direct_stage_influence": False,
        }
    )
    personal_thresholds = (
        runtime.baselines.thresholds_for(_account_key)
        if _account_key and runtime.PERSONAL_BASELINE_STAGE_INFLUENCE_ENABLED
        else None
    )
    cv_deep_threshold = float(
        (personal_thresholds or {}).get("cv_deep", runtime.SLEEP_HR_CV_DEEP)
    )
    cv_rem_threshold = float(
        (personal_thresholds or {}).get("cv_rem", runtime.SLEEP_HR_CV_REM)
    )
    with runtime.sleep_path_lock:
        if (
            session_active
            and runtime._sleep_stage_path.get("session_id") != active_session_id
        ):
            runtime._reset_sleep_stage_path(active_session_id)
        previous_valid_stage = runtime._sleep_stage_path.get("last")
    had_previous_stage = previous_valid_stage in {"wake", "n1", "n2", "n3", "rem"}
    if not had_previous_stage:
        previous_valid_stage = "wake"
    result: dict[str, Any] = {
        "state": "no_data",
        "version": runtime.SLEEP_ESTIMATOR_VERSION,
        "evidence_version": runtime.SLEEP_EVIDENCE_VERSION,
        "window_s": runtime.SLEEP_WINDOW_SECONDS,
        "frames": len(frames),
        "sample_s": runtime.SLEEP_SAMPLE_SECONDS,
        "required_samples": runtime.SLEEP_MIN_FRAMES,
        "evidence_epoch_s": runtime.SLEEP_EVIDENCE_EPOCH_SECONDS,
        "confirmation_s": runtime.SLEEP_CONFIRMATION_SECONDS,
        "evidence_frames_per_epoch": runtime.SLEEP_SENSOR_FRAMES_PER_EPOCH,
        "coverage_s": round(frames[-1]["t"] - frames[0]["t"], 1)
        if len(frames) > 1
        else 0,
        "age": age,
        "age_group": age_group,
        "gender": gender,
        "age_baseline": age_baseline,
        "gender_adjustment": gender_adjustment,
        "baseline": baseline,
        "personal_baseline": personal_meta,
        "personal_baseline_candidate": proposed_personal_baseline,
        "personal_behaviour": personal_behaviour,
        "variability_thresholds": {
            "cv_deep": cv_deep_threshold,
            "cv_rem": cv_rem_threshold,
            "source": "personal" if personal_thresholds else "population_default",
        },
        "baseline_definition": {
            "version": runtime.ZEEP_SLEEP_BASELINE_VERSION,
            "transition_policy": runtime.ZEEP_SLEEP_TRANSITION_POLICY_VERSION,
            "display_ontology": list(runtime.ZEEP_SLEEP_STATES),
            "g2_ontology_version": runtime.SLEEP_G2_ONTOLOGY_VERSION,
            "g2_ontology": ["W", "N1", "N2", "N3", "REM"],
            "g2_psg_crosswalk": {
                "wake": "W",
                "n1": "N1",
                "n2": "N2",
                "n3": "N3",
                "rem": "REM",
            },
            "primary_inputs": [
                "bed_status",
                "movement",
                "heart_rate",
                "respiration_rate",
                "heart_rate_summary_cv",
                "respiration_rate_cv",
                "hr_rr_trend",
                "bcg_respiratory_regularity",
                "bcg_fast_amplitude_stability",
                "elapsed_time",
                "transition_path",
                "age_gender_baseline",
            ],
            "corroborating_inputs": [
                "sph0645_acoustic_disturbance",
                "bed_status_weak_breathing",
                "bed_status_snoring",
            ],
            "scoring_weights": {
                "hr_baseline": runtime.SLEEP_BASELINE_HR_WEIGHT,
                "rr_baseline": runtime.SLEEP_BASELINE_RR_WEIGHT,
                "n3_rr_conflict_penalty": runtime.SLEEP_N3_RR_CONFLICT_PENALTY,
                "n2_rr_conflict_support": runtime.SLEEP_N2_RR_CONFLICT_SUPPORT,
            },
            "context_inputs": [
                "temperature",
                "humidity",
                "co2",
                "light",
                "sound",
                "pm2_5",
                "voc_index",
            ],
            "environment_direct_stage_influence": False,
            "personal_history_direct_stage_influence": (
                runtime.PERSONAL_BASELINE_STAGE_INFLUENCE_ENABLED
            ),
            "acoustic_requires_bcg_or_motion_corroboration": True,
            "intended_use": "exploratory_wellness_telemetry",
            "actuator_trigger": False,
            "aasm_aligned_labels": True,
            "aasm_psg_equivalent": False,
            "validated_ibi_hrv": False,
            "eeg_k_complex_or_spindle": False,
        },
        "classification_source": classification_source,
        "baseline_candidate_source": baseline_candidate_source,
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
    ) -> dict[str, Any]:
        """Return an operational status only outside occupied recording."""
        if (
            session_active
            and session_recording
            and data_status
            not in {
                "empty_bed",
                "confirmed_off_bed",
                "no_session",
                "waiting_for_vitals",
            }
        ):
            return carry_occupied_epoch(reason, data_status=data_status)
        with runtime.sleep_path_lock:
            if runtime._sleep_stage_path.get("session_id") == active_session_id:
                runtime._sleep_stage_path["candidate"] = None
                runtime._sleep_stage_path["candidate_ticks"] = 0
                runtime._sleep_stage_path["continuity_hold_ticks"] = 0
                runtime._sleep_stage_path["probability_ema"] = None
        result.update(
            {
                "state": display_state,
                "probabilities": {
                    key: 0.0 for key in ("wake", "n1", "n2", "n3", "rem")
                },
                "classification_active": False,
                "evidence_active": False,
                "confirmed_state": None,
                "confidence": "low",
                "provisional": False,
                "data_status": data_status,
                "reason": reason,
                "last_valid_state": previous_valid_stage
                if had_previous_stage
                else None,
                "held_previous_state": False,
                "score_eligible": False,
                "excluded_from_score": True,
                "excluded_from_personal_baseline": True,
            }
        )
        return result

    def carry_occupied_epoch(
        reason: str,
        *,
        data_status: str,
        current_epoch: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Assign every occupied Epoch to W or the last confirmed State."""
        epoch_frames = list(
            current_epoch
            if current_epoch is not None
            else frames[-runtime.SLEEP_SENSOR_FRAMES_PER_EPOCH :]
        )
        frame_times = [
            float(frame["t"])
            for frame in epoch_frames
            if isinstance(frame.get("t"), int | float)
        ]
        epoch_end_s = max(frame_times) if frame_times else now
        with runtime.sleep_path_lock:
            if runtime._sleep_stage_path.get("session_id") != active_session_id:
                runtime._reset_sleep_stage_path(active_session_id)
            prior = runtime._sleep_stage_path.get("last")
            previous = prior if prior in runtime.ZEEP_SLEEP_STATES else None
            runtime._sleep_stage_path["candidate"] = None
            runtime._sleep_stage_path["candidate_ticks"] = 0
            runtime._sleep_stage_path["probability_ema"] = None
            hold_epochs = (
                int(runtime._sleep_stage_path.get("continuity_hold_ticks") or 0) + 1
                if previous is not None
                else 1
            )
            runtime._sleep_stage_path["continuity_hold_ticks"] = hold_epochs

        confirmation = runtime.continuity_hold_contract(
            previous,
            decision="occupied_evidence_gap_hold",
            hold_epochs=hold_epochs,
        )
        confirmation.update(
            {
                "candidate_epochs": 0,
                "required_epochs": 0,
                "confirmation_seconds": 0.0,
                "confirmation_complete": True,
                "evidence_data_status": data_status,
            }
        )
        stage = str(confirmation["confirmed_state"])
        display_probabilities = {
            name: 1.0 if name == stage else 0.0 for name in runtime.ZEEP_SLEEP_STATES
        }
        current_hrs = runtime.filter_vital_values(
            [frame.get("hr") for frame in epoch_frames],
            runtime.HR_SANITY_RANGE_BPM,
        )
        current_rrs = runtime.filter_vital_values(
            [frame.get("rr") for frame in epoch_frames],
            runtime.RR_SANITY_RANGE_PER_MIN,
        )
        mean_epoch_hr = sum(current_hrs) / len(current_hrs) if current_hrs else None
        mean_epoch_rr = sum(current_rrs) / len(current_rrs) if current_rrs else None
        window_start = datetime.fromtimestamp(
            epoch_end_s - runtime.SLEEP_EVIDENCE_EPOCH_SECONDS,
            UTC,
        ).isoformat()
        window_end = datetime.fromtimestamp(epoch_end_s, UTC).isoformat()
        latest_frame = epoch_frames[-1] if epoch_frames else {}
        decision_metrics = {
            "mean_hr": (round(mean_epoch_hr, 1) if mean_epoch_hr is not None else None),
            "mean_rr": (round(mean_epoch_rr, 1) if mean_epoch_rr is not None else None),
            "bed_status": runtime.STATUS_TEXT.get(
                latest_frame.get("confirmed_status", latest_frame.get("status")),
                "Unknown",
            ),
            "evidence_data_status": data_status,
            "continuity_carry": True,
        }
        result.update(
            {
                "state": stage,
                "confirmed_state": stage,
                "classification_active": True,
                "evidence_active": False,
                "probabilities": display_probabilities,
                "evidence_probabilities": {
                    stage: 0.0 for stage in runtime.ZEEP_SLEEP_STATES
                },
                "confirmed_probabilities": display_probabilities,
                "confidence": "low",
                "provisional": False,
                "held_previous_state": bool(confirmation["held_previous_state"]),
                "continuity_hold_epochs": int(confirmation["continuity_hold_epochs"]),
                "score_attribution_state": stage,
                "challenger_counted_as_new_state": False,
                "score_eligible": True,
                "excluded_from_score": False,
                "excluded_from_personal_baseline": True,
                "data_status": confirmation["data_status"],
                "current_data_status": data_status,
                "current_data_reason": reason,
                "reason": reason,
                "mean_hr": decision_metrics["mean_hr"],
                "mean_rr": decision_metrics["mean_rr"],
                "confirmation": confirmation,
                "evidence": {
                    "candidate": None,
                    "probabilities": {
                        stage: 0.0 for stage in runtime.ZEEP_SLEEP_STATES
                    },
                    "confidence": "low",
                    "epoch_seconds": runtime.SLEEP_EVIDENCE_EPOCH_SECONDS,
                    "sensor_frames": runtime.SLEEP_SENSOR_FRAMES_PER_EPOCH,
                    "window_seconds": runtime.SLEEP_WINDOW_SECONDS,
                    "window_start": window_start,
                    "window_end": window_end,
                    "status": data_status,
                },
                "transition_policy": confirmation,
                "previous_state": previous,
                "display_probability_basis": "previous_confirmed_state",
            }
        )
        result["stage_progression"] = runtime._commit_sleep_stage(
            stage,
            display_probabilities,
            reason,
            confidence="low",
            metrics=decision_metrics,
            confirmation=confirmation,
            window_start=window_start,
            window_end=window_end,
            sample_count=len(epoch_frames),
        )
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
    latest_frame = frames[-1] if frames else {}
    latest_bcg_t = max(
        (frame.get("bcg_latest_t") or 0 for frame in frames),
        default=0,
    )
    latest_hr = runtime.filter_vital_values(
        [latest_frame.get("hr")], runtime.HR_SANITY_RANGE_BPM
    )
    latest_rr = runtime.filter_vital_values(
        [latest_frame.get("rr")], runtime.RR_SANITY_RANGE_PER_MIN
    )
    fresh_on_bed_vitals = bool(
        latest_bcg_t
        and now - latest_bcg_t <= max(15, runtime.SLEEP_SAMPLE_SECONDS * 3)
        and latest_frame.get("bcg_valid")
        and latest_hr
        and latest_rr
    )
    if runtime._off_bed_remains_latched(
        status_code=latest_frame.get("confirmed_status", latest_frame.get("status")),
        current_vitals_valid=fresh_on_bed_vitals,
    ):
        return suspend_classification(
            "ยังไม่มี Bed Status พร้อม HR/RR สดยืนยันว่ากลับขึ้นเตียง",
            "empty_bed",
            display_state="off_bed",
        )
    if not frames:
        return suspend_classification("ยังไม่มีรอบข้อมูล BCG ใหม่", "no_frame")
    if not latest_bcg_t or now - latest_bcg_t > max(
        15, runtime.SLEEP_SAMPLE_SECONDS * 3
    ):
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
        runtime._latch_confirmed_bed_exit(active_session_id, now=now)
        result["bed_exit_evidence"] = latest_exit
        return suspend_classification(
            "Bed Status ยืนยันว่าไม่มีผู้ใช้งานบนเตียง · ไม่ประเมิน Sleep State",
            "empty_bed",
            display_state="off_bed",
        )
    if not latest_frame.get("bcg_valid") or not latest_hr or not latest_rr:
        return suspend_classification(
            "รอบปัจจุบันไม่มี HR/RR สดที่ใช้ได้ · ไม่ประเมิน Sleep State",
            "invalid_or_missing_current_vitals",
        )
    movement_window = runtime.movement_window_metrics(statuses)
    move_ratio = float(movement_window["movement_ratio"])
    result["movement_ratio"] = round(move_ratio, 3)
    valid_bcg = [f for f in frames if f.get("bcg_valid")]
    raw_hrs = [f.get("hr") for f in valid_bcg]
    raw_rrs = [f.get("rr") for f in valid_bcg]
    hrs = runtime.filter_vital_values(raw_hrs, runtime.HR_SANITY_RANGE_BPM)
    rrs = runtime.filter_vital_values(raw_rrs, runtime.RR_SANITY_RANGE_PER_MIN)
    missing_ratio = 1.0 - len(valid_bcg) / len(frames)
    clip_values = [
        f["clip_ratio"] for f in frames if isinstance(f.get("clip_ratio"), int | float)
    ]
    result["signal_quality"] = {
        "valid_buckets": len(valid_bcg),
        "total_buckets": len(frames),
        "valid_percent": round((1 - missing_ratio) * 100, 1),
        "invalid_hr_buckets": len([value for value in raw_hrs if value is not None])
        - len(hrs),
        "invalid_rr_buckets": len([value for value in raw_rrs if value is not None])
        - len(rrs),
        "average_clip_percent": round(sum(clip_values) / len(clip_values) * 100, 2)
        if clip_values
        else None,
        "minimum_paired_vital_coverage": runtime.SLEEP_MIN_PAIRED_VITAL_COVERAGE,
    }
    current_epoch = frames[-runtime.SLEEP_SENSOR_FRAMES_PER_EPOCH :]

    def frames_are_contiguous(sequence: list[dict[str, Any]]) -> bool:
        if len(sequence) < 2:
            return True
        times = [frame.get("t") for frame in sequence]
        if not all(isinstance(value, int | float) for value in times):
            return False
        return all(
            0.0 < float(after) - float(before) <= runtime.SLEEP_SAMPLE_SECONDS * 1.8
            for before, after in zip(times, times[1:], strict=False)
        )

    current_epoch_complete = bool(
        len(current_epoch) == runtime.SLEEP_SENSOR_FRAMES_PER_EPOCH
        and frames_are_contiguous(current_epoch)
        and all(
            frame.get("bcg_valid")
            and runtime.filter_vital_values(
                [frame.get("hr")], runtime.HR_SANITY_RANGE_BPM
            )
            and runtime.filter_vital_values(
                [frame.get("rr")], runtime.RR_SANITY_RANGE_PER_MIN
            )
            and frame.get("confirmed_status", frame.get("status"))
            in runtime.ON_BED_CODES
            for frame in current_epoch
        )
    )
    paired_window_coverage = 1.0 - missing_ratio
    rolling_window_contiguous = bool(
        len(frames) >= runtime.SLEEP_MIN_FRAMES and frames_are_contiguous(frames)
    )
    if not current_epoch_complete:
        # A canonical 30-second decision requires all three current 10-second
        # frames to carry occupied-bed + valid HR + valid RR + valid BCG.  A
        # good older half of the rolling 60-second window must not hide a bad
        # current epoch or create evidence the historical replay will reject.
        return suspend_classification(
            ("Evidence epoch 30 วินาทีปัจจุบันมี Bed/HR/RR/BCG ไม่ครบ · ไม่สร้าง Sleep State"),
            "incomplete_current_evidence_epoch",
        )
    if had_previous_stage and (
        len(frames) < runtime.SLEEP_MIN_FRAMES
        or paired_window_coverage < runtime.SLEEP_MIN_PAIRED_VITAL_COVERAGE
        or not rolling_window_contiguous
    ):
        return carry_occupied_epoch(
            ("ยึด State ที่ยืนยันก่อนหน้าไว้ชั่วคราว · กำลังสร้างหน้าต่าง HR/RR + BCG สด 60 วินาทีใหม่"),
            data_status="rebuilding_confirmation_window",
            current_epoch=current_epoch,
        )
    if not hrs or not rrs:
        return suspend_classification(
            "HR/RR อยู่นอกช่วงตรวจสอบหรือไม่มีข้อมูล · ไม่ประเมิน Sleep State",
            "invalid_or_missing_vitals",
        )
    if paired_window_coverage < runtime.SLEEP_MIN_PAIRED_VITAL_COVERAGE:
        return suspend_classification(
            "คู่ HR/RR ในหน้าต่างปัจจุบันไม่ต่อเนื่องพอ · ไม่ประเมิน Sleep State",
            "insufficient_paired_vital_coverage",
        )
    mean_hr = sum(hrs) / len(hrs)
    mean_rr = sum(rrs) / len(rrs)
    session_context = runtime._update_sleep_session_context(
        context_frames,
        now=now,
        session_started=session_started,
    )
    with runtime.sleep_path_lock:
        previous_valid_stage = runtime._sleep_stage_path.get("last")
    current_stage_for_scoring = (
        previous_valid_stage
        if previous_valid_stage in runtime.ZEEP_SLEEP_STATES
        else "wake"
    )
    summary_signal = runtime.summary_features(hrs, rrs, runtime.SLEEP_SAMPLE_SECONDS)
    long_valid_bcg = [frame for frame in context_frames if frame.get("bcg_valid")]
    long_summary_signal = runtime.summary_features(
        [frame.get("hr") for frame in long_valid_bcg],
        [frame.get("rr") for frame in long_valid_bcg],
        runtime.SLEEP_SAMPLE_SECONDS,
    )
    hr_cv = float(summary_signal.get("hr_cv") or 0.0)
    rr_cv = float(summary_signal.get("rr_cv") or 0.0)
    raw_window = [
        sample for frame in valid_bcg for sample in (frame.get("bcg_samples") or [])
    ]
    waveform_signal = runtime.waveform_features(raw_window)
    expected_waveform_samples = max(
        1.0, runtime.BCG_SAMPLE_RATE_HZ * runtime.SLEEP_WINDOW_SECONDS
    )
    waveform_coverage = min(1.0, len(raw_window) / expected_waveform_samples)
    waveform_signal["waveform_sample_coverage"] = round(waveform_coverage, 4)
    waveform_signal["minimum_waveform_sample_coverage"] = (
        runtime.SLEEP_MIN_WAVEFORM_COVERAGE
    )
    if waveform_coverage < runtime.SLEEP_MIN_WAVEFORM_COVERAGE:
        waveform_signal["waveform_available"] = False
        waveform_signal["waveform_rejection_reason"] = "insufficient_sample_coverage"
    result["signal_quality"].update(
        {
            "bcg_baseline_drift_ratio": waveform_signal.get("bcg_baseline_drift_ratio"),
            "bcg_baseline_drift_flag": waveform_signal.get(
                "bcg_baseline_drift_flag", False
            ),
        }
    )
    elapsed_min = max(0.0, (now - session_started) / 60) if session_started else 0.0

    def avg_field(name: str):
        values = [f[name] for f in frames if isinstance(f.get(name), int | float)]
        return round(sum(values) / len(values), 1) if values else None

    environment = {
        "temperature_c": avg_field("temperature"),
        "humidity_rh": avg_field("humidity"),
        "co2_ppm": avg_field("co2"),
        "lux": avg_field("lux"),
        "sound_dba": avg_field("sound_dba"),
        "pm2_5_ug_m3": avg_field("pm2_5"),
        "voc_index": avg_field("voc"),
        "coverage_percent": round(
            sum(1 for f in frames if f.get("esp_fresh")) / len(frames) * 100, 1
        ),
    }
    latest_sensor_status = next(
        (
            f.get("sensor_status")
            for f in reversed(frames)
            if isinstance(f.get("sensor_status"), dict)
        ),
        {},
    )
    environment["unavailable_sensors"] = [
        k for k, available in latest_sensor_status.items() if available is False
    ]
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
    environment_context = runtime._sleep_environment_context(environment, rest_mode)
    environment["zeep_context"] = environment_context
    result["environment"] = environment
    auxiliary_evidence = runtime._sleep_auxiliary_evidence(
        frames, statuses, move_ratio, waveform_signal
    )
    result["auxiliary_evidence"] = auxiliary_evidence

    base_scores: dict[str, float] = {}
    baseline_proximity: dict[str, Any] = {}
    hr_stage_fits: dict[str, float] = {}
    rr_stage_fits: dict[str, float] = {}
    for name in ("wake", "n1", "n2", "n3", "rem"):
        hr_fit, hr_distance = runtime._baseline_interval_proximity(
            mean_hr, baseline[name]["hr"]
        )
        rr_fit, rr_distance = runtime._baseline_interval_proximity(
            mean_rr, baseline[name]["rr"]
        )
        physiological_fit = runtime._physiological_baseline_fit(hr_fit, rr_fit)
        base_scores[name] = physiological_fit
        hr_stage_fits[name] = hr_fit
        rr_stage_fits[name] = rr_fit
        baseline_proximity[name] = {
            "hr": hr_distance,
            "rr": rr_distance,
            "weighted_percent": round(
                physiological_fit
                / (runtime.SLEEP_BASELINE_HR_WEIGHT + runtime.SLEEP_BASELINE_RR_WEIGHT)
                * 100.0,
                1,
            ),
        }
    scoring_metrics = {
        "mean_hr": mean_hr,
        "mean_rr": mean_rr,
        "awake_hr_reference": session_context["awake_hr_reference"],
        "awake_rr_reference": session_context["awake_rr_reference"],
        "awake_reference_pairs": session_context["awake_reference_pairs"],
        "sleep_onset_established": session_context["sleep_onset_established"],
        "sleep_elapsed_min": session_context["sleep_elapsed_min"],
        "current_stage": current_stage_for_scoring,
        "hr_cv": hr_cv,
        "rr_cv": rr_cv,
        "movement_ratio": move_ratio,
        "bed_status": runtime.STATUS_TEXT.get(statuses[-1], "Unknown"),
        "max_moving_run_frames": movement_window["max_moving_run_frames"],
        "movement_burst_count": movement_window["movement_burst_count"],
        "corroborated_acoustic_wake_support": auxiliary_evidence[
            "corroborated_acoustic_wake_support"
        ],
        **summary_signal,
        **waveform_signal,
        "hr_slope_bpm_per_min": long_summary_signal.get("hr_slope_bpm_per_min"),
        "rr_slope_per_min": long_summary_signal.get("rr_slope_per_min"),
    }
    arousal_proxy = runtime.arousal_proxy_evidence(
        scoring_metrics, runtime.SLEEP_MOVE_WAKE_RATIO
    )
    scores, sleep_evidence = runtime.score_sleep_evidence(
        base_scores=base_scores,
        hr_fits=hr_stage_fits,
        rr_fits=rr_stage_fits,
        metrics=scoring_metrics,
        elapsed_min=elapsed_min,
        rem_variability_weight=float(gender_adjustment["rem_variability_weight"]),
        n3_rr_conflict_penalty=runtime.SLEEP_N3_RR_CONFLICT_PENALTY,
        n2_rr_conflict_support=runtime.SLEEP_N2_RR_CONFLICT_SUPPORT,
        move_wake_ratio=runtime.SLEEP_MOVE_WAKE_RATIO,
        move_deep_ratio=runtime.SLEEP_MOVE_DEEP_RATIO,
        onset_min_observation_minutes=runtime.SLEEP_ONSET_MIN_OBSERVATION_SECONDS
        / 60.0,
        onset_max_movement_ratio=runtime.SLEEP_ONSET_MAX_MOVEMENT_RATIO,
        onset_min_downward_transition=runtime.SLEEP_ONSET_MIN_DOWNWARD_TRANSITION,
        onset_min_relative_sleep_support=runtime.SLEEP_ONSET_MIN_RELATIVE_SLEEP_SUPPORT,
        onset_max_hr_rise_bpm_per_min=runtime.SLEEP_ONSET_MAX_HR_RISE_BPM_PER_MIN,
        onset_max_rr_rise_per_min=runtime.SLEEP_ONSET_MAX_RR_RISE_PER_MIN,
        onset_initial_wake_support=runtime.SLEEP_ONSET_INITIAL_WAKE_SUPPORT,
        deep_cv_threshold=cv_deep_threshold,
        rem_cv_threshold=cv_rem_threshold,
    )
    rr_stage_guard = {
        "conflict": sleep_evidence["n3_rr_conflict"],
        "n3_penalty": sleep_evidence["n3_rr_conflict"]
        * runtime.SLEEP_N3_RR_CONFLICT_PENALTY,
        "n2_support": sleep_evidence["n3_rr_conflict"]
        * runtime.SLEEP_N2_RR_CONFLICT_SUPPORT,
    }

    eligible_states = {
        stage: sleep_evidence[f"{stage}_gate"] for stage in runtime.ZEEP_SLEEP_STATES
    }
    stage_evidence_probabilities = runtime.softmax_stage_evidence(
        scores,
        temperature=runtime.SLEEP_SCORE_SOFTMAX_TEMPERATURE,
        eligible_states=eligible_states,
    )
    raw_probabilities, fit_fusion = runtime.fuse_hr_rr_fit_with_stage_probabilities(
        stage_evidence_probabilities,
        base_scores,
        eligible_states=eligible_states,
        confirmed_state=current_stage_for_scoring,
        fit_weight=runtime.SLEEP_HR_RR_FIT_FUSION_WEIGHT,
        agreement_weight=runtime.SLEEP_HR_RR_FIT_FUSION_AGREEMENT_WEIGHT,
    )
    sleep_evidence["hr_rr_fit_fusion"] = fit_fusion
    instant_candidate = max(raw_probabilities, key=raw_probabilities.get)
    accepted_instant_candidate, evidence_quality = (
        runtime.evidence_candidate_with_abstention(
            raw_probabilities,
            minimum_winner=runtime.SLEEP_EVIDENCE_MIN_WINNER,
            minimum_margin=runtime.SLEEP_EVIDENCE_MIN_MARGIN,
            gated_stage_thresholds=(
                {
                    "n3": (
                        runtime.SLEEP_N3_GATED_MIN_WINNER,
                        runtime.SLEEP_N3_GATED_MIN_MARGIN,
                    )
                }
                if sleep_evidence["n3_gate"]
                else None
            ),
        )
    )
    with runtime.sleep_path_lock:
        smoothed_probabilities = runtime.smooth_stage_probabilities(
            runtime._sleep_stage_path.get("probability_ema"),
            raw_probabilities,
            alpha=runtime.SLEEP_PROBABILITY_EMA_ALPHA,
        )
        runtime._sleep_stage_path["probability_ema"] = dict(smoothed_probabilities)
        probability_current_stage = runtime._sleep_stage_path.get("last")
    # EMA remains the default continuity source. Gated N1 -> N2 progression and
    # a current N3 winner may use the fresh 30-second evidence before EMA; the
    # semi-Markov resolver still requires the target's configured confirmation
    # (N2: 120 seconds; N3: 60 seconds). This prevents a stale display EMA from
    # trapping genuine sleep in N1/N2 without accepting one noisy epoch.
    evidence_candidate = None
    probability_transition: dict[str, Any] = {
        "candidate_source": "abstain",
        "evidence_quality": evidence_quality,
    }
    if accepted_instant_candidate is not None:
        evidence_candidate, probability_transition = (
            runtime.candidate_from_stage_evidence(
                raw_probabilities,
                smoothed_probabilities,
                probability_current_stage,
                switch_margin=runtime.SLEEP_PROBABILITY_SWITCH_MARGIN,
                n3_gate=bool(sleep_evidence["n3_gate"]),
                sleep_onset_gate_passed=bool(
                    sleep_evidence["sleep_onset_gate"]["passed"]
                    or sleep_evidence["sleep_onset_established"]
                ),
                eligible_states=eligible_states,
            )
        )
        probability_transition["evidence_quality"] = evidence_quality
    # A position change or blanket adjustment is sleep-compatible movement.
    # Only the shared, physiology-corroborated movement rule may bypass the
    # normal N2/N3/REM -> N1 -> Wake progression.
    strong_wake = bool(
        instant_candidate == "wake" and sleep_evidence["movement"]["strong_wake"]
    )
    decision_candidate = "wake" if strong_wake else evidence_candidate
    # The Session starts only after a conscious Login plus occupied-bed and
    # fresh HR/RR gates. The first complete occupied 30-second Epoch anchors W
    # immediately; only a transition away from W needs 60/120-second evidence.
    if probability_current_stage is None and decision_candidate != "wake":
        decision_candidate = "wake"
        probability_transition.update(
            {
                "candidate_source": "initial_awake_anchor",
                "initial_awake_anchor": True,
                "initial_evidence_candidate": evidence_candidate,
            }
        )
    if decision_candidate is None:
        with runtime.sleep_path_lock:
            runtime._sleep_stage_path["candidate"] = None
            runtime._sleep_stage_path["candidate_ticks"] = 0
            hold_ticks = (
                int(runtime._sleep_stage_path.get("continuity_hold_ticks") or 0) + 1
            )
            runtime._sleep_stage_path["continuity_hold_ticks"] = hold_ticks
        selected = None
        transition_meta = {
            "raw_candidate": None,
            "previous_state": probability_current_stage,
            "confirmation_complete": False,
            "policy": runtime.ZEEP_SLEEP_TRANSITION_POLICY_VERSION,
        }
        transition_meta.update(
            runtime.continuity_hold_contract(
                probability_current_stage,
                decision="ambiguous_evidence_hold",
                hold_epochs=hold_ticks,
            )
        )
    else:
        selected, transition_meta = runtime._stabilize_sleep_stage(
            decision_candidate, now=now, strong_wake=strong_wake
        )

    # Evidence probabilities deliberately remain independent from the
    # confirmed state. A pending challenger can therefore be inspected without
    # rewriting the probability distribution to make the held state win.
    probabilities = {k: round(v, 4) for k, v in smoothed_probabilities.items()}
    rounding_delta = round(1.0 - sum(probabilities.values()), 4)
    probabilities[instant_candidate] = round(
        probabilities[instant_candidate] + rounding_delta, 4
    )
    confirmed_state = transition_meta.get("confirmed_state")
    if confirmed_state not in runtime.ZEEP_SLEEP_STATES:
        confirmed_state = None
    confirmed_probabilities = (
        runtime.align_probabilities_to_emitted_stage(
            smoothed_probabilities,
            confirmed_state,
            winner_margin=runtime.SLEEP_DISPLAY_WINNER_MARGIN,
        )
        if confirmed_state
        else {key: 0.0 for key in runtime.ZEEP_SLEEP_STATES}
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
        source = transition_meta.get("raw_candidate") or decision_candidate
        target = bridge or selected or previous_state
        if source and target:
            transition_guard = f"{str(source).upper()} → {str(target).upper()} ตามลำดับธรรมชาติ; ยืนยัน {pending}/{required} รอบ"
    top = probabilities[instant_candidate]
    confidence = "high" if top >= 0.72 else "medium" if top >= 0.48 else "low"
    if transition_guard:
        # A bridge label preserves continuity but is not direct physiological
        # evidence for that stage, so never present it with high confidence.
        confidence = "low"
    if decision_candidate is None:
        confidence = "low"
    held_previous_state = bool(transition_meta.get("held_previous_state"))
    provisional = bool(confirmed_state is None or transition_meta.get("provisional"))
    if provisional or transition_meta.get("state_source") == ("initial_awake_anchor"):
        confidence = "low"
    if (
        missing_ratio > 0.25
        or environment["coverage_percent"] < 50
        or environment_context["coverage_percent"] < 50
    ):
        confidence = "low"
    if clip_values and sum(clip_values) / len(clip_values) >= 0.20:
        confidence = "low"
    if waveform_signal.get("bcg_baseline_drift_flag"):
        confidence = "low"
    if (
        isinstance(environment_context.get("disruption_index"), int | float)
        and environment_context["disruption_index"] >= 0.5
        and confidence == "high"
    ):
        # Air/light/comfort can make the physiology less representative of an
        # undisturbed sleep window, but cannot select another stage.
        confidence = "medium"
    baseline_fit_summary = runtime.interpret_baseline_fit(
        base_scores,
        confirmed_state=confirmed_state,
        evidence_candidate=decision_candidate,
        n3_gate=bool(sleep_evidence.get("n3_gate")),
        transition_meta=transition_meta,
        hr_weight=runtime.SLEEP_BASELINE_HR_WEIGHT,
        rr_weight=runtime.SLEEP_BASELINE_RR_WEIGHT,
    )
    reason_bits = [
        f"HR เฉลี่ย {mean_hr:.1f}",
        f"RR เฉลี่ย {mean_rr:.1f}",
        f"movement {move_ratio * 100:.0f}%",
    ]
    movement_category = sleep_evidence["movement"]["category"]
    if movement_category == "position_change_or_blanket_adjustment_candidate":
        reason_bits.append("ขยับสั้นขณะอยู่บนเตียง · ไม่ถือเป็น Wake โดยลำพัง")
    elif movement_category == "sustained_on_bed_motion":
        reason_bits.append("ขยับต่อเนื่องบนเตียง · ลดความมั่นใจแต่ยังไม่ยืนยัน Wake")
    elif movement_category == "wake_compatible_motion":
        reason_bits.append("การขยับต่อเนื่องสอดคล้องกับ HR/RR และ BCG")
    if rr_stage_guard["conflict"] >= 0.05:
        reason_bits.append(
            f"RR ใกล้ N2 มากกว่า N3 {rr_stage_guard['conflict'] * 100:.0f}%"
        )
    if transition_guard:
        reason_bits.append(transition_guard)
    if decision_candidate is None:
        reason_bits.append("หลักฐานยังใกล้กันเกินไป · คง State ที่ยืนยันก่อนหน้า")
    if transition_meta.get("decision") == "blocked_transition_hold":
        reason_bits.append("State ผู้ท้าชิงยังไม่ผ่าน Transition Gate · คง State ก่อนหน้า")
    if probability_transition.get("sleep_onset_guard_held"):
        onset = sleep_evidence["sleep_onset_gate"]
        if not onset["observation_complete"]:
            reason_bits.append("คง W ระหว่างเก็บ Awake baseline 5 นาทีแรก")
        elif not onset["quiet_bed"]:
            reason_bits.append("คง W เพราะยังมีการเคลื่อนไหวบนเตียง")
        else:
            reason_bits.append("คง W เพราะ HR/RR ยังไม่ลดลงต่อเนื่องพอสำหรับ Sleep onset")
    if environment_context["sleep_support_score"] is not None:
        reason_bits.append(
            f"environment context {environment_context['sleep_support_score']}/100"
        )
    if auxiliary_evidence["acoustic"]["bcg_or_motion_corroborated"]:
        reason_bits.append("เสียงรบกวนสอดคล้องกับ BCG/การเคลื่อนไหว")
    if auxiliary_evidence["bed_status"]["weak_breathing_frames"]:
        reason_bits.append("Bed Status พบ weak-breathing context")
    if auxiliary_evidence["bed_status"]["snoring_frames"]:
        reason_bits.append("Bed Status พบ snoring context")
    if decision_candidate == "wake":
        reason_bits.append("หลักฐานใกล้ Awake baseline เด่นที่สุด")
    elif decision_candidate == "n1":
        reason_bits.append("หลักฐานกำลังลดจาก Awake baseline และอยู่ในช่วงเปลี่ยนผ่าน")
    elif decision_candidate == "n2":
        reason_bits.append("หลักฐาน HR/RR และ BCG คงที่ต่อเนื่อง")
    elif decision_candidate == "n3":
        reason_bits.append("หลักฐาน HR/RR ต่ำ การหายใจสม่ำเสมอ และ N3 gate ผ่าน")
    elif decision_candidate == "rem":
        reason_bits.append("RR แปรปรวนบนเตียงที่นิ่งและ REM gate ผ่าน")
    if environment["lux"] is not None:
        reason_bits.append(f"แสงเฉลี่ย {environment['lux']:.0f} lux")
    if environment["sound_dba"] is not None:
        reason_bits.append(f"เสียงเฉลี่ย {environment['sound_dba']:.1f} dBA")
    result.update(
        {
            "state": confirmed_state or "no_data",
            "confirmed_state": confirmed_state,
            "probabilities": probabilities,
            "evidence_probabilities": probabilities,
            "confirmed_probabilities": confirmed_probabilities,
            "confidence": confidence,
            "classification_active": confirmed_state is not None,
            "evidence_active": True,
            "raw_probabilities": {k: round(v, 4) for k, v in raw_probabilities.items()},
            "pre_fusion_probabilities": {
                k: round(v, 4) for k, v in stage_evidence_probabilities.items()
            },
            "smoothed_probabilities": {
                k: round(v, 4) for k, v in smoothed_probabilities.items()
            },
            "instant_candidate": instant_candidate,
            "raw_candidate": decision_candidate,
            "probability_winner": instant_candidate,
            "winner_percent": round(probabilities[instant_candidate] * 100, 1),
            "evidence_quality": evidence_quality,
            "provisional": provisional,
            "held_previous_state": held_previous_state,
            "continuity_hold_epochs": int(
                transition_meta.get("continuity_hold_epochs") or 0
            ),
            "score_attribution_state": (
                transition_meta.get("score_attribution_state") or confirmed_state
            ),
            "challenger_counted_as_new_state": bool(
                transition_meta.get("challenger_counted_as_new_state")
            ),
            "score_eligible": bool(
                confirmed_state is not None
                and transition_meta.get("score_eligible", True)
            ),
            "excluded_from_score": bool(
                confirmed_state is None
                or transition_meta.get("excluded_from_score", False)
            ),
            "data_status": (
                transition_meta.get("data_status")
                if transition_meta.get("held") or confirmed_state is None
                else "live"
            ),
            "reason": " · ".join(reason_bits),
            "mean_hr": round(mean_hr, 1),
            "mean_rr": round(mean_rr, 1),
            "hr_cv": round(hr_cv, 4),
            "rr_cv": round(rr_cv, 4),
            "elapsed_min": round(elapsed_min, 1),
            "baseline_proximity": baseline_proximity,
            "baseline_fit_summary": baseline_fit_summary,
            "scoring_weights": {
                "hr_baseline": runtime.SLEEP_BASELINE_HR_WEIGHT,
                "rr_baseline": runtime.SLEEP_BASELINE_RR_WEIGHT,
                "hr_rr_fit_fusion": runtime.SLEEP_HR_RR_FIT_FUSION_WEIGHT,
                "hr_rr_fit_fusion_when_confirmed_agrees": (
                    runtime.SLEEP_HR_RR_FIT_FUSION_AGREEMENT_WEIGHT
                ),
            },
            "probability_filter": {
                "method": "ema_after_60s_rolling_features",
                "alpha": runtime.SLEEP_PROBABILITY_EMA_ALPHA,
                "candidate_switch_margin": runtime.SLEEP_PROBABILITY_SWITCH_MARGIN,
                "candidate_source": "ema_with_gated_n3_current_evidence_override",
                "ema_role": "default_candidate_stability_and_display",
                "display_winner_margin": runtime.SLEEP_DISPLAY_WINNER_MARGIN,
                **probability_transition,
            },
            "rr_stage_guard": {k: round(v, 4) for k, v in rr_stage_guard.items()},
            "signal_features": {**summary_signal, **waveform_signal},
            "long_context_features": {
                **long_summary_signal,
                "window_seconds": runtime.SLEEP_LONG_CONTEXT_SECONDS,
                "valid_frames": len(long_valid_bcg),
            },
            "sleep_evidence": sleep_evidence,
            "timing_priors": {
                "rem_gate": sleep_evidence["rem_gate"],
                "rem_time_support": sleep_evidence["rem_time_support"],
                "sleep_onset_gate": sleep_evidence["sleep_onset_gate"],
            },
            "evidence": {
                "candidate": decision_candidate,
                "probabilities": probabilities,
                "confidence": confidence,
                "epoch_seconds": runtime.SLEEP_EVIDENCE_EPOCH_SECONDS,
                "sensor_frames": runtime.SLEEP_SENSOR_FRAMES_PER_EPOCH,
                "window_seconds": runtime.SLEEP_WINDOW_SECONDS,
            },
            "confirmation": {
                "confirmed_state": confirmed_state,
                "pending_state": (
                    transition_meta.get("pending_state")
                    if transition_meta.get("held")
                    else None
                ),
                "candidate_epochs": transition_meta.get("candidate_epochs", 0),
                "required_epochs": transition_meta.get(
                    "required_epochs", runtime.SLEEP_CONFIRM_EPOCHS
                ),
                "required_seconds": float(
                    transition_meta.get("confirmation_seconds")
                    or runtime.SLEEP_CONFIRMATION_SECONDS
                ),
                "complete": bool(transition_meta.get("confirmation_complete")),
                "decision": transition_meta.get("decision"),
                "decision_kind": transition_meta.get("decision_kind"),
                "held_previous_state": held_previous_state,
                "continuity_hold_epochs": int(
                    transition_meta.get("continuity_hold_epochs") or 0
                ),
                "provisional": provisional,
                "provisional_hold_max_epochs": runtime.SLEEP_PROVISIONAL_HOLD_EPOCHS,
                "challenger_counted_as_new_state": bool(
                    transition_meta.get("challenger_counted_as_new_state")
                ),
                "score_eligible": bool(
                    confirmed_state is not None
                    and transition_meta.get("score_eligible", True)
                ),
                "excluded_from_score": bool(
                    confirmed_state is None
                    or transition_meta.get("excluded_from_score", False)
                ),
                "excluded_from_personal_baseline": bool(
                    transition_meta.get("excluded_from_personal_baseline", False)
                ),
            },
        }
    )
    result["transition_guard"] = transition_guard
    result["transition_policy"] = transition_meta
    result["previous_state"] = previous_state
    decision_metrics = {
        "mean_hr": round(mean_hr, 1),
        "mean_rr": round(mean_rr, 1),
        "hr_cv": round(hr_cv, 4),
        "rr_cv": round(rr_cv, 4),
        "movement_ratio": round(move_ratio, 3),
        "max_moving_run_frames": movement_window["max_moving_run_frames"],
        "movement_burst_count": movement_window["movement_burst_count"],
        "rr_n2_fit": round(rr_stage_fits["n2"], 4),
        "rr_n3_fit": round(rr_stage_fits["n3"], 4),
        "rr_n3_conflict": round(rr_stage_guard["conflict"], 4),
        "rr_n3_penalty": round(rr_stage_guard["n3_penalty"], 4),
        "awake_hr_reference": session_context["awake_hr_reference"],
        "awake_rr_reference": session_context["awake_rr_reference"],
        "sleep_onset_established": session_context["sleep_onset_established"],
        **summary_signal,
        **waveform_signal,
        "arousal_proxy": arousal_proxy,
        "auxiliary_evidence": auxiliary_evidence,
        "corroborated_acoustic_wake_support": auxiliary_evidence[
            "corroborated_acoustic_wake_support"
        ],
        "sleep_evidence": sleep_evidence,
        "bed_status": runtime.STATUS_TEXT.get(statuses[-1], "Unknown"),
        "environment_support_score": environment_context["sleep_support_score"],
        "environment_coverage_percent": environment_context["coverage_percent"],
    }
    window_start = datetime.fromtimestamp(
        frames[0]["t"] - runtime.SLEEP_SAMPLE_SECONDS, UTC
    ).isoformat()
    window_end = datetime.fromtimestamp(frames[-1]["t"], UTC).isoformat()
    result["evidence"]["window_start"] = window_start
    result["evidence"]["window_end"] = window_end
    runtime._persist_sleep_stage_evidence(
        decision_candidate,
        probabilities,
        result["reason"],
        confidence=confidence,
        metrics=decision_metrics,
        window_start=window_start,
        window_end=window_end,
        sample_count=len(frames),
        confirmation=result["confirmation"],
    )
    if confirmed_state:
        result["stage_progression"] = runtime._commit_sleep_stage(
            confirmed_state,
            confirmed_probabilities,
            result["reason"],
            confidence=confidence,
            metrics=decision_metrics,
            confirmation=result["confirmation"],
            window_start=window_start,
            window_end=window_end,
            sample_count=len(frames),
        )
    else:
        with runtime.sleep_path_lock:
            result["stage_progression"] = list(runtime._sleep_stage_path["seen"])
    return result
