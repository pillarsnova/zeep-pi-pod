"""Signal-derived features used by the exploratory ZEEP sleep estimator.

The Pod's BCG module stores 25 signed 16-bit waveform samples per approximately
one-second packet.  These helpers deliberately expose engineering proxies only:

* respiratory regularity is estimated from a low-pass BCG waveform;
* fast-amplitude stability describes the non-respiratory waveform envelope;
* HR/RR trends are calculated from versioned fixed-cadence summary buckets
  (10 seconds in ``stable-30s-epoch``).

None of these features is an EEG K-complex, sleep spindle, ECG R-R interval or
validated HRV measurement.  Keeping the names explicit prevents a convenient
proxy from silently becoming a clinical claim in the dashboard or exports.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
import math
import struct
from typing import Any, Iterable, Mapping, Optional

from sleep_system_policy import (
    SLEEP_CLASSIFICATION_GAP_VERSION,
    TERMINAL_WAKE_POLICY_VERSION,
)


BCG_SAMPLE_RATE_HZ = 25.0
MIN_WAVEFORM_SECONDS = 20.0
HR_SANITY_RANGE_BPM = (25.0, 220.0)
RR_SANITY_RANGE_PER_MIN = (2.0, 60.0)
TERMINAL_OCCUPANCY_POLICY_VERSION = "zeep-terminal-occupancy-v1.0"


def movement_window_metrics(
    statuses: Iterable[object],
    moving_code: int = 2,
) -> dict[str, int | float]:
    """Summarise movement bursts without inventing an anatomical label.

    A bed BCG/status sensor can detect load changes, but cannot prove whether
    the sleeper turned their torso, moved a limb, or adjusted a blanket.  The
    longest consecutive run is therefore retained as auditable context for the
    sleep-compatible movement guard instead of translating every Moving bucket
    directly to Wake.
    """
    values: list[int] = []
    for status in statuses:
        try:
            values.append(int(status))
        except (TypeError, ValueError, OverflowError):
            continue
    moving_frames = 0
    longest_run = 0
    current_run = 0
    burst_count = 0
    for status in values:
        if status == moving_code:
            moving_frames += 1
            current_run += 1
            longest_run = max(longest_run, current_run)
            if current_run == 1:
                burst_count += 1
        else:
            current_run = 0
    return {
        "analysis_frames": len(values),
        "moving_frames": moving_frames,
        "movement_ratio": round(moving_frames / len(values), 4) if values else 0.0,
        "max_moving_run_frames": longest_run,
        "movement_burst_count": burst_count,
    }


def bed_exit_window_evidence(
    statuses: Iterable[object],
    *,
    exit_code: int = 1,
    latest_raw_exit_frames: object = 0,
    latest_raw_total_frames: object = 0,
    minimum_consecutive_buckets: int = 3,
    minimum_raw_frames: int = 5,
    minimum_raw_ratio: float = 0.8,
    raw_packet_confirmation_enabled: bool = False,
    terminal_session_boundary: bool = False,
) -> dict[str, object]:
    """Debounce an LSM-800-T bed-exit indication as occupancy evidence.

    The module can briefly emit ``Get out of bed`` while load transfers during
    a turn, blanket adjustment, or edge-of-bed movement.  A true exit is
    accepted when three consecutive 10-second analysis buckets end out of
    bed. Raw packet counts remain diagnostic only because field data showed
    repeated 1–7 packet exit pulses while the person remained on the bed.
    During completed-session replay,
    one final raw exit at the terminal boundary is also accepted: a user often
    stands and immediately ends the Session before a second bucket is emitted.
    Raw status remains available for Admin diagnostics. A confirmed exit stops
    Sleep State classification and is stored on the occupancy timeline; it
    does not manufacture a Wake epoch.
    """
    values: list[int] = []
    for status in statuses:
        try:
            values.append(int(status))
        except (TypeError, ValueError, OverflowError):
            continue

    trailing = 0
    for status in reversed(values):
        if status != int(exit_code):
            break
        trailing += 1

    raw_exit_values = finite_values([latest_raw_exit_frames])
    raw_total_values = finite_values([latest_raw_total_frames])
    raw_exit = max(0, int(raw_exit_values[0])) if raw_exit_values else 0
    raw_total = max(0, int(raw_total_values[0])) if raw_total_values else 0
    raw_exit = min(raw_exit, raw_total) if raw_total else 0
    raw_ratio = raw_exit / raw_total if raw_total else 0.0
    by_buckets = trailing >= max(1, int(minimum_consecutive_buckets))
    by_packets = bool(
        raw_packet_confirmation_enabled
        and trailing >= 1
        and raw_exit >= max(1, int(minimum_raw_frames))
        and raw_ratio >= max(0.0, min(1.0, float(minimum_raw_ratio)))
    )
    by_terminal_boundary = bool(
        terminal_session_boundary and trailing >= 1 and raw_exit >= 1
    )
    return {
        "confirmed": bool(by_buckets or by_packets or by_terminal_boundary),
        "confirmed_by": (
            "consecutive_buckets" if by_buckets
            else "raw_packet_majority" if by_packets
            else "terminal_session_boundary" if by_terminal_boundary
            else None
        ),
        "trailing_exit_buckets": trailing,
        "minimum_consecutive_buckets": max(1, int(minimum_consecutive_buckets)),
        "latest_raw_exit_frames": raw_exit,
        "latest_raw_total_frames": raw_total,
        "latest_raw_exit_ratio": round(raw_ratio, 4),
        "minimum_raw_frames": max(1, int(minimum_raw_frames)),
        "minimum_raw_ratio": round(
            max(0.0, min(1.0, float(minimum_raw_ratio))), 4),
        "raw_packet_confirmation_enabled": bool(raw_packet_confirmation_enabled),
        "terminal_session_boundary": bool(terminal_session_boundary),
        "transient_rejected": bool(
            trailing and not (by_buckets or by_packets or by_terminal_boundary)
        ),
    }


def bed_exit_event_summary(
    labels: Iterable[object],
    *,
    minimum_consecutive_samples: int = 3,
    keep_terminal_single: bool = True,
) -> dict[str, int]:
    """Count confirmed exit *events*, not individual Sensor samples.

    Isolated mid-Session ``Get out of bed`` labels are treated as transient.
    A final single label is retained because a user commonly leaves the bed
    and immediately ends the Session before a second sensor sample.
    """
    values = [str(label or "") for label in labels]
    minimum = max(1, int(minimum_consecutive_samples))
    event_count = 0
    confirmed_samples = 0
    transient_samples = 0
    index = 0
    while index < len(values):
        if values[index].casefold() != "get out of bed":
            index += 1
            continue
        end = index + 1
        while (end < len(values)
               and values[end].casefold() == "get out of bed"):
            end += 1
        run = end - index
        terminal = end == len(values)
        confirmed = run >= minimum or (terminal and keep_terminal_single)
        if confirmed:
            event_count += 1
            confirmed_samples += run
        else:
            transient_samples += run
        index = end
    return {
        "event_count": event_count,
        "confirmed_samples": confirmed_samples,
        "transient_samples": transient_samples,
    }


def debounced_bed_status_labels(
    labels: Iterable[object],
    *,
    minimum_consecutive_samples: int = 3,
    keep_terminal_single: bool = True,
) -> list[str]:
    """Return the canonical report labels while preserving raw data elsewhere."""
    values = [str(label or "") for label in labels]
    canonical = list(values)
    minimum = max(1, int(minimum_consecutive_samples))
    index = 0
    while index < len(values):
        if values[index].casefold() != "get out of bed":
            index += 1
            continue
        end = index + 1
        while (end < len(values)
               and values[end].casefold() == "get out of bed"):
            end += 1
        run = end - index
        terminal = end == len(values)
        confirmed = run >= minimum or (terminal and keep_terminal_single)
        if not confirmed:
            previous = next(
                (canonical[position] for position in range(index - 1, -1, -1)
                 if canonical[position]
                 and canonical[position].casefold() != "get out of bed"),
                None,
            )
            following = next(
                (values[position] for position in range(end, len(values))
                 if values[position]
                 and values[position].casefold() != "get out of bed"),
                None,
            )
            replacement = previous or following or "On bed"
            for position in range(index, end):
                canonical[position] = replacement
        index = end
    return canonical


def terminal_occupancy_timeline(
    samples: Iterable[Mapping[str, Any]],
    *,
    session_end: Any,
    sample_interval_s: float = 5.0,
    minimum_exit_samples: int = 3,
) -> list[dict[str, Any]]:
    """Separate terminal occupancy from the five human Sleep States.

    Missing HR/RR alone can be a Sensor fault, so it must never be converted
    directly to Wake or an exit.  A completed Session receives an operational
    terminal sequence only when a debounced ``Get out of bed`` run occurs and
    no valid HR+RR pair returns afterwards.  The sequence is backdated to the
    first missing-vitals bucket that leads into that confirmed exit:

    ``no_user_on_bed`` -> ``exited_zeep`` -> Session end.

    These periods explain the gap after the final human Sleep State.  They are
    deliberately excluded from Wake/N1/N2/N3/REM percentages and personal
    physiology baselines.
    """
    rows = list(samples)
    if not rows:
        return []
    interval = max(0.1, float(sample_interval_s or 5.0))
    minimum = max(1, int(minimum_exit_samples))

    def field(row: Mapping[str, Any], key: str) -> Any:
        try:
            return row.get(key) if hasattr(row, "get") else row[key]
        # ``sqlite3.Row`` raises IndexError (not KeyError) for an unknown
        # column, while dictionaries expose ``get``. Supporting both keeps the
        # report helper independent of the storage adapter.
        except (IndexError, KeyError, TypeError):
            return None

    def epoch(value: Any) -> Optional[float]:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value) if math.isfinite(float(value)) else None
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.timestamp()
        except (TypeError, ValueError, OverflowError):
            return None

    def sample_epoch(row: Mapping[str, Any]) -> Optional[float]:
        return epoch(field(row, "timestamp") or field(row, "t"))

    def valid_pair(row: Mapping[str, Any]) -> bool:
        hr = filter_vital_values(
            [field(row, "heart_rate") if field(row, "heart_rate") is not None
             else field(row, "hr")],
            HR_SANITY_RANGE_BPM,
        )
        rr = filter_vital_values(
            [field(row, "respiration_rate")
             if field(row, "respiration_rate") is not None else field(row, "rr")],
            RR_SANITY_RANGE_PER_MIN,
        )
        return bool(hr and rr)

    labels = [
        str(field(row, "bed_status") or field(row, "bed") or "")
        for row in rows
    ]
    valid_pairs = [valid_pair(row) for row in rows]
    exit_index: Optional[int] = None
    confirmed_run = 0
    index = 0
    while index < len(rows):
        if labels[index].casefold() != "get out of bed":
            index += 1
            continue
        end = index + 1
        while end < len(rows) and labels[end].casefold() == "get out of bed":
            end += 1
        run = end - index
        terminal_single = run == 1 and end == len(rows)
        # An exit is terminal only if physiology never returns afterwards.
        if (run >= minimum or terminal_single) and not any(valid_pairs[index:]):
            exit_index = index
            confirmed_run = run
            break
        index = end
    if exit_index is None:
        return []

    last_vital_index = next(
        (position for position in range(exit_index - 1, -1, -1)
         if valid_pairs[position]),
        None,
    )
    missing_index = (
        last_vital_index + 1 if last_vital_index is not None else exit_index
    )
    missing_end_epoch = sample_epoch(rows[missing_index])
    exit_end_epoch = sample_epoch(rows[exit_index])
    end_epoch = epoch(session_end)
    if exit_end_epoch is None:
        return []
    no_user_start = (
        missing_end_epoch - interval
        if missing_end_epoch is not None else exit_end_epoch - interval
    )
    exit_start = exit_end_epoch - interval
    if end_epoch is None:
        last_epoch = sample_epoch(rows[-1])
        end_epoch = (last_epoch + interval) if last_epoch is not None else exit_end_epoch
    end_epoch = max(end_epoch, exit_start)

    def iso(value: float) -> str:
        return datetime.fromtimestamp(value, timezone.utc).isoformat()

    periods: list[dict[str, Any]] = []
    if no_user_start < exit_start:
        periods.append({
            "version": TERMINAL_OCCUPANCY_POLICY_VERSION,
            "state": "no_user_on_bed",
            "label": "ไม่มีผู้ใช้งานบนเตียง",
            "start_time": iso(no_user_start),
            "end_time": iso(exit_start),
            "duration_s": round(exit_start - no_user_start, 1),
            "reason": (
                "HR และ RR หายต่อเนื่องก่อน Bed Status ยืนยันการออกจากเตียง"
            ),
            "hr_available": False,
            "rr_available": False,
            "sleep_stage": False,
        })
    periods.append({
        "version": TERMINAL_OCCUPANCY_POLICY_VERSION,
        "state": "exited_zeep",
        "label": "ออกจาก ZEEP",
        "start_time": iso(exit_start),
        "end_time": iso(end_epoch),
        "duration_s": round(end_epoch - exit_start, 1),
        "reason": (
            "Bed Status ยืนยันการออกจากเตียง และ HR/RR ไม่กลับมาก่อนจบ Session"
        ),
        "hr_available": False,
        "rr_available": False,
        "sleep_stage": False,
        "confirmed_by": (
            "consecutive_samples" if confirmed_run >= minimum
            else "terminal_single_sample"
        ),
        "confirmed_exit_samples": confirmed_run,
    })
    return periods


def terminal_wake_transition(
    sleep_periods: Iterable[Mapping[str, Any]],
    *,
    terminal_occupancy: Iterable[Mapping[str, Any]] = (),
    session_end: Any,
    end_reason: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Create an auditable Wake boundary before exit or Session end.

    Pressing ``End Session`` (or an Admin ending the occupied Session) is an
    operational observation that the sleep episode has ended.  It is useful in
    the displayed sequence, but it is not an AASM/PSG-scored epoch and must not
    be added to Wake duration, architecture percentages, WASO, or a personal
    physiology baseline.

    The marker is inserted only when at least one valid human Sleep State was
    recorded and the last recorded state is not already Wake.  When a terminal
    bed exit exists, the marker is placed at the first occupancy boundary;
    otherwise it is placed at the explicit Session-end time.  Empty-bed data
    alone never becomes a human Wake epoch.
    """
    valid_states = {"wake", "n1", "n2", "n3", "rem"}
    stages = [
        period for period in sleep_periods
        if str(period.get("state") or "").casefold() in valid_states
    ]
    if not stages:
        return None
    previous_state = str(stages[-1].get("state") or "").casefold()
    if previous_state == "wake":
        return None

    occupancy = list(terminal_occupancy)
    boundary = (
        occupancy[0].get("start_time")
        if occupancy else session_end
    )
    if boundary is None:
        return None

    def iso(value: Any) -> Optional[str]:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if not math.isfinite(float(value)):
                return None
            return datetime.fromtimestamp(float(value), timezone.utc).isoformat()
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError, OverflowError):
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()

    boundary_iso = iso(boundary)
    if boundary_iso is None:
        return None
    source = "confirmed_terminal_bed_exit" if occupancy else "explicit_session_end"
    return {
        "version": TERMINAL_WAKE_POLICY_VERSION,
        "state": "wake",
        "label": "W · ตื่น",
        "start_time": boundary_iso,
        "end_time": boundary_iso,
        "duration_s": 0.0,
        "round_count": 0,
        "sample_interval_s": None,
        "confidence": "operational",
        "probabilities": {},
        "metrics": {},
        "reason": (
            "จุดเปลี่ยนจากสถานะการนอนเป็นตื่นก่อนออกจาก ZEEP"
            if occupancy else
            "จุดเปลี่ยนเป็นตื่นจากคำสั่งจบ Session"
        ),
        "previous_state": previous_state,
        "decision_kind": "terminal_wake_boundary",
        "confirmed_by": source,
        "end_reason": str(end_reason or "session_end"),
        "sleep_stage": False,
        "excluded_from_stage_statistics": True,
        "excluded_from_personal_baseline": True,
        "aasm_psg_equivalent": False,
    }


def sleep_classification_gap_timeline(
    sleep_periods: Iterable[Mapping[str, Any]],
    sensor_samples: Iterable[Mapping[str, Any]],
    *,
    session_start: Any,
    classification_end: Any,
    sensor_sample_interval_s: float = 10.0,
    minimum_gap_s: Optional[float] = None,
    service_pause_times: Iterable[Any] = (),
    service_resume_times: Iterable[Any] = (),
) -> list[dict[str, Any]]:
    """Expose unclassified wall-clock gaps without inventing Sleep Stages.

    Confirmed decisions are intentionally absent while the occupant is off the
    bed, current HR/RR is invalid, the Sensor stream is unavailable, or the
    estimator is rebuilding its confirmation window after a restart.  A report
    that returns only confirmed periods makes those intervals look deleted.
    This helper inserts explicit ``OFF``/``WAIT`` periods for display and audit;
    they stay outside W/N1/N2/N3/REM totals, score, WASO and personal baseline.
    """
    interval = max(0.1, float(sensor_sample_interval_s or 10.0))
    minimum = (
        max(15.0, interval * 1.5)
        if minimum_gap_s is None else max(0.1, float(minimum_gap_s))
    )

    def field(row: Mapping[str, Any], *keys: str) -> Any:
        for key in keys:
            try:
                value = row.get(key) if hasattr(row, "get") else row[key]
            except (IndexError, KeyError, TypeError):
                continue
            if value is not None:
                return value
        return None

    def epoch(value: Any) -> Optional[float]:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value) if math.isfinite(float(value)) else None
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError, OverflowError):
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()

    start_epoch = epoch(session_start)
    end_epoch = epoch(classification_end)
    if start_epoch is None or end_epoch is None or end_epoch <= start_epoch:
        return []

    periods: list[tuple[float, float, str]] = []
    for period in sleep_periods:
        period_state = str(field(period, "state") or "").casefold()
        if period_state not in {
            "wake", "n1", "n2", "n3", "rem",
        }:
            continue
        period_start = epoch(field(period, "start_time", "timestamp"))
        period_end = epoch(field(period, "end_time", "window_end", "timestamp"))
        if period_start is None or period_end is None:
            continue
        periods.append((
            max(start_epoch, period_start),
            min(end_epoch, period_end),
            period_state,
        ))
    periods.sort()

    pause_epochs = [
        value for item in service_pause_times
        if (value := epoch(item)) is not None
    ]
    resume_epochs = [
        value for item in service_resume_times
        if (value := epoch(item)) is not None
    ]

    gaps: list[tuple[float, float]] = []
    cursor = start_epoch
    for period_start, period_end, _ in periods:
        if period_end <= cursor:
            continue
        if period_start - cursor >= minimum:
            gaps.append((cursor, period_start))
        cursor = max(cursor, period_end)
    if end_epoch - cursor >= minimum:
        gaps.append((cursor, end_epoch))

    sample_rows: list[tuple[float, Mapping[str, Any]]] = []
    for sample in sensor_samples:
        sample_epoch = epoch(field(sample, "t", "timestamp"))
        if sample_epoch is not None:
            sample_rows.append((sample_epoch, sample))

    def iso(value: float) -> str:
        return datetime.fromtimestamp(value, timezone.utc).isoformat()

    results: list[dict[str, Any]] = []
    for gap_start, gap_end in gaps:
        restart_markers = [
            value for value in (*pause_epochs, *resume_epochs)
            if gap_start - interval <= value <= gap_end + interval
        ]
        previous_periods = [
            period for period in periods
            if period[1] <= gap_start + interval
        ]
        following_periods = [
            period for period in periods
            if period[0] >= gap_end - interval
        ]
        held_stage = previous_periods[-1][2] if previous_periods else None
        restart_hold = bool(
            restart_markers
            and held_stage in {"wake", "n1", "n2", "n3", "rem"}
            and following_periods
        )
        rows = [
            row for sample_epoch, row in sample_rows
            if gap_start <= sample_epoch < gap_end
        ]
        bed_labels = [
            str(field(row, "bed", "bed_status") or "") for row in rows
        ]
        valid_pairs = 0
        for row in rows:
            hr = filter_vital_values(
                [field(row, "hr", "heart_rate")], HR_SANITY_RANGE_BPM)
            rr = filter_vital_values(
                [field(row, "rr", "respiration_rate")],
                RR_SANITY_RANGE_PER_MIN,
            )
            valid_pairs += int(bool(hr and rr))
        off_bed = sum(
            label.casefold() == "get out of bed" for label in bed_labels)
        on_bed = sum(
            label.casefold() in {
                "on bed", "moving", "weak breathing", "snoring",
            }
            for label in bed_labels
        )
        if restart_hold:
            state = "restart_hold"
            label = {
                "wake": "W · ตื่น",
                "n1": "N1 · หลับตื้น / เคลิ้มหลับ",
                "n2": "N2 · หลับตื้นต่อเนื่อง",
                "n3": "N3 · หลับลึก",
                "rem": "REM · หลับฝัน",
            }[held_stage] + " · คงสถานะก่อน Restart"
            reason = (
                "พบเหตุการณ์หยุด/เริ่ม Service ในช่วงนี้ จึงแสดงสถานะที่"
                "ยืนยันล่าสุดเพื่อความต่อเนื่องเท่านั้น โดยไม่สร้างหลักฐาน"
                "Sleep Stage และไม่นำช่วงนี้ไปคิดคะแนนหรือ Baseline"
            )
            status = "service_restart_hold"
        elif not rows:
            state = "sensor_gap"
            label = "WAIT · ไม่มีข้อมูล Sensor"
            reason = "ไม่มี Timeline Sensor ในช่วงนี้"
            status = "sensor_unavailable"
        elif off_bed > on_bed:
            state = "off_bed"
            label = "OFF · ไม่มีผู้ใช้งานบนเตียง"
            reason = (
                "Bed Status ส่วนใหญ่เป็น Get out of bed; "
                "ช่วงนี้ไม่ใช่ Sleep Stage"
            )
            status = "confirmed_or_dominant_off_bed"
        elif valid_pairs == 0:
            state = "no_data"
            label = "WAIT · ไม่มี HR/RR ที่ใช้ได้"
            reason = "มี Timeline แต่ไม่มีคู่ HR และ RR ที่ผ่าน sanity gate"
            status = "missing_current_vitals"
        elif valid_pairs < max(2, math.ceil(len(rows) * 0.5)):
            state = "no_data"
            label = "WAIT · HR/RR ไม่ต่อเนื่อง"
            reason = (
                "HR/RR ที่ใช้ได้ไม่ต่อเนื่องพอสำหรับยืนยัน Sleep State"
            )
            status = "insufficient_vital_coverage"
        else:
            state = "no_data"
            label = "WAIT · กำลังยืนยันสถานะ"
            reason = (
                "Sensor มีข้อมูล แต่ยังไม่มี confirmed Sleep State "
                "ในช่วงเริ่มต้น/หลัง restart หรือรอยืนยัน 60 วินาที"
            )
            status = "unconfirmed_evidence"
        results.append({
            "version": SLEEP_CLASSIFICATION_GAP_VERSION,
            "state": state,
            "label": label,
            "start_time": iso(gap_start),
            "end_time": iso(gap_end),
            "duration_s": round(gap_end - gap_start, 1),
            "round_count": 0,
            "sample_interval_s": interval,
            "confidence": "unavailable",
            "probabilities": {},
            "metrics": {},
            "reason": reason,
            "decision_kind": "classification_gap",
            "data_status": status,
            "held_previous_state": restart_hold,
            "held_state": held_stage if restart_hold else None,
            "service_restart_marker_count": len(restart_markers),
            "sleep_stage": False,
            "excluded_from_stage_statistics": True,
            "excluded_from_score": True,
            "excluded_from_personal_baseline": True,
            "aasm_psg_equivalent": False,
            "coverage": {
                "sensor_rows": len(rows),
                "valid_hr_rr_pairs": valid_pairs,
                "off_bed_rows": off_bed,
                "on_bed_context_rows": on_bed,
            },
        })
    return results


def sleep_movement_evidence(
    metrics: dict[str, object],
    movement_threshold: float = 0.15,
) -> dict[str, object]:
    """Classify on-bed movement as context, not as Wake by itself.

    Brief load changes are compatible with physiological sleep movement such
    as a position change or blanket adjustment.  A strong Wake override is
    allowed only for bed exit, or sustained movement with a same-window rise
    in HR/RR.  These are engineering proxies and are not an anatomical or EEG
    determination.
    """
    movement_values = finite_values([metrics.get("movement_ratio")])
    movement_ratio = min(1.0, max(0.0, movement_values[0])) if movement_values else 0.0
    run_values = finite_values([metrics.get("max_moving_run_frames")])
    max_run = max(0, int(run_values[0])) if run_values else 0
    burst_values = finite_values([metrics.get("movement_burst_count")])
    burst_count = max(0, int(burst_values[0])) if burst_values else 0
    hr_slope_values = finite_values([metrics.get("hr_slope_bpm_per_min")])
    rr_slope_values = finite_values([metrics.get("rr_slope_per_min")])
    hr_slope = hr_slope_values[0] if hr_slope_values else 0.0
    rr_slope = rr_slope_values[0] if rr_slope_values else 0.0
    shift_values = finite_values([metrics.get("bcg_amplitude_shift_ratio")])
    shift_ratio = max(0.0, shift_values[0]) if shift_values else None
    bed_status = str(metrics.get("bed_status") or "").strip().casefold()
    bed_exit = bed_status == "get out of bed"

    brief_on_bed = bool(
        not bed_exit
        and movement_ratio > 0.0
        and movement_ratio <= 0.25
        and (max_run == 0 or max_run <= 2)
    )
    sustained_on_bed = bool(
        not bed_exit
        and (movement_ratio >= 0.35 or max_run >= 3)
    )
    vital_rise = bool(hr_slope >= 2.0 or rr_slope >= 1.2)
    waveform_corroboration = bool(shift_ratio is not None and shift_ratio >= 0.12)
    wake_compatible = bool(
        bed_exit
        or (sustained_on_bed and vital_rise and waveform_corroboration)
    )
    if bed_exit:
        category = "bed_exit"
    elif wake_compatible:
        category = "wake_compatible_motion"
    elif sustained_on_bed:
        category = "sustained_on_bed_motion"
    elif brief_on_bed:
        category = "position_change_or_blanket_adjustment_candidate"
    elif movement_ratio >= movement_threshold:
        category = "on_bed_motion"
    else:
        category = "quiet_or_below_threshold"

    # Bounded support replaces the previous large, duplicate Wake boost.  A
    # sustained on-bed movement window can reduce stage confidence, but cannot
    # declare Wake without physiological corroboration.
    wake_score_support = (
        2.0 if bed_exit else
        1.6 if wake_compatible else
        0.35 if sustained_on_bed else
        0.0
    )
    return {
        "category": category,
        "movement_ratio": round(movement_ratio, 4),
        "max_moving_run_frames": max_run,
        "movement_burst_count": burst_count,
        "brief_on_bed": brief_on_bed,
        "sustained_on_bed": sustained_on_bed,
        "vital_rise": vital_rise,
        "waveform_corroboration": waveform_corroboration,
        "wake_compatible": wake_compatible,
        "strong_wake": wake_compatible,
        "sleep_compatible": bool(not bed_exit and not wake_compatible),
        "wake_score_support": wake_score_support,
        "anatomy_determined": False,
        "blanket_motion_determined": False,
        "sensor_limit": (
            "single bed BCG/status cannot identify body part or distinguish "
            "blanket adjustment from a position change"
        ),
    }


def finite_values(values: Iterable[object]) -> list[float]:
    """Return finite numeric values without letting malformed sensor data raise."""
    result: list[float] = []
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            continue
        if math.isfinite(number):
            result.append(number)
    return result


def filter_vital_values(
    values: Iterable[object],
    valid_range: tuple[float, float],
) -> list[float]:
    """Keep only physiologically plausible device summary values.

    The bounds are an input-sanity layer, not diagnostic limits. Values outside
    them are labelled invalid before entering the sleep-state scorer.
    """
    lower, upper = sorted((float(valid_range[0]), float(valid_range[1])))
    return [value for value in finite_values(values) if lower <= value <= upper]


def arousal_proxy_evidence(
    metrics: dict[str, object],
    movement_threshold: float = 0.15,
    amplitude_shift_threshold: float = 0.12,
) -> dict[str, object]:
    """Describe same-window non-EEG evidence compatible with an awakening.

    This is intentionally called a proxy. A cortical arousal is an EEG-scored
    event under AASM rules; a BCG amplitude shift must never be relabelled as
    one without simultaneous PSG validation.
    """
    shift_values = finite_values([metrics.get("bcg_amplitude_shift_ratio")])
    shift_ratio = max(0.0, shift_values[0]) if shift_values else None
    movement = sleep_movement_evidence(metrics, movement_threshold)
    movement_ratio = float(movement["movement_ratio"])
    evidence: list[str] = []
    # A non-zero ratio is normal numerical variation.  Keep this threshold in
    # sync with the independent BCG corroboration gate in app.py so tiny shifts
    # are not mislabelled as disturbance evidence.
    if shift_ratio is not None and shift_ratio >= amplitude_shift_threshold:
        evidence.append("bcg_amplitude_shift")
    if movement["wake_compatible"] and movement["category"] != "bed_exit":
        evidence.append("wake_compatible_motion")
    if movement["category"] == "bed_exit":
        evidence.append("bed_exit")
    return {
        "present": bool(evidence),
        "evidence": evidence,
        "bcg_amplitude_shift_ratio": (
            round(shift_ratio, 4) if shift_ratio is not None else None
        ),
        "movement_ratio": round(movement_ratio, 4),
        "movement": movement,
        "thresholds": {
            "bcg_amplitude_shift_ratio": amplitude_shift_threshold,
            "movement_ratio": movement_threshold,
        },
        "time_alignment": "same_rolling_window",
        "validated_cortical_arousal": False,
    }


def decode_bcg_samples(encoded: Optional[str]) -> list[int]:
    """Decode one persisted packet of 25 little-endian int16 BCG samples."""
    if not encoded:
        return []
    try:
        payload = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError):
        return []
    if len(payload) != 50:
        return []
    return list(struct.unpack("<25h", payload))


def coefficient_of_variation(values: Iterable[float]) -> Optional[float]:
    data = finite_values(values)
    if not data:
        return None
    mean = sum(data) / len(data)
    if mean == 0:
        return None
    variance = sum((value - mean) ** 2 for value in data) / len(data)
    return math.sqrt(variance) / abs(mean)


def linear_slope_per_minute(values: Iterable[float], sample_seconds: float = 5.0) -> Optional[float]:
    """Least-squares slope for equally spaced summary values."""
    data = finite_values(values)
    if len(data) < 3 or sample_seconds <= 0:
        return None
    times = [index * sample_seconds / 60.0 for index in range(len(data))]
    mean_t = sum(times) / len(times)
    mean_y = sum(data) / len(data)
    denominator = sum((value - mean_t) ** 2 for value in times)
    if denominator == 0:
        return None
    return sum((time_value - mean_t) * (value - mean_y)
               for time_value, value in zip(times, data)) / denominator


def _moving_average(values: list[float], window: int) -> list[float]:
    if not values or window <= 1:
        return list(values)
    result: list[float] = []
    running = 0.0
    for index, value in enumerate(values):
        running += value
        if index >= window:
            running -= values[index - window]
        if index >= window - 1:
            result.append(running / window)
    return result


def _detrend(values: list[float]) -> list[float]:
    if len(values) < 2:
        return list(values)
    mean_x = (len(values) - 1) / 2.0
    mean_y = sum(values) / len(values)
    denominator = sum((index - mean_x) ** 2 for index in range(len(values)))
    slope = (sum((index - mean_x) * (value - mean_y)
                 for index, value in enumerate(values)) / denominator
             if denominator else 0.0)
    intercept = mean_y - slope * mean_x
    return [value - (intercept + slope * index) for index, value in enumerate(values)]


def _goertzel_power(values: list[float], frequency_hz: float, sample_rate_hz: float) -> float:
    omega = 2.0 * math.pi * frequency_hz / sample_rate_hz
    coefficient = 2.0 * math.cos(omega)
    previous = 0.0
    previous_two = 0.0
    for value in values:
        current = value + coefficient * previous - previous_two
        previous_two = previous
        previous = current
    return max(0.0, previous_two * previous_two + previous * previous
               - coefficient * previous * previous_two)


def _lag_correlation(values: list[float], lag: int) -> Optional[float]:
    if lag <= 0 or len(values) < lag * 3:
        return None
    left = values[:-lag]
    right = values[lag:]
    mean_left = sum(left) / len(left)
    mean_right = sum(right) / len(right)
    numerator = sum((a - mean_left) * (b - mean_right) for a, b in zip(left, right))
    left_power = sum((value - mean_left) ** 2 for value in left)
    right_power = sum((value - mean_right) ** 2 for value in right)
    denominator = math.sqrt(left_power * right_power)
    return numerator / denominator if denominator else None


def waveform_features(
    samples: Iterable[int | float],
    sample_rate_hz: float = BCG_SAMPLE_RATE_HZ,
) -> dict[str, float | int | bool | None]:
    """Extract conservative regularity and envelope features from raw BCG.

    The respiratory proxy is a one-second moving average downsampled to 5 Hz.
    Spectral entropy/purity is calculated only in 0.10-0.50 Hz.  The fast
    amplitude metric uses first differences per second and therefore must not
    be presented as J-wave amplitude until validated against reference ECG/BCG.
    """
    data = finite_values(samples)
    minimum_samples = int(MIN_WAVEFORM_SECONDS * sample_rate_hz)
    base: dict[str, float | int | bool | None] = {
        "waveform_available": len(data) >= minimum_samples,
        "waveform_sample_count": len(data),
        "waveform_sample_rate_hz": round(sample_rate_hz, 2),
        "resp_dominant_hz": None,
        "resp_spectral_purity": None,
        "resp_spectral_entropy": None,
        "resp_autocorrelation": None,
        "resp_regularity": None,
        "bcg_fast_amplitude_cv": None,
        "bcg_amplitude_shift_ratio": None,
        "bcg_baseline_drift_ratio": None,
        "bcg_baseline_drift_flag": False,
    }
    if len(data) < minimum_samples or sample_rate_hz <= 0:
        return base

    one_second = max(3, int(round(sample_rate_hz)))
    smoothed = _moving_average(data, one_second)
    downsample_step = max(1, int(round(sample_rate_hz / 5.0)))
    respiratory = _detrend(smoothed[::downsample_step])
    respiratory_rate_hz = sample_rate_hz / downsample_step
    if len(respiratory) < 20:
        return base

    # A Hann window reduces leakage between adjacent respiratory bins.
    windowed = [
        value * (0.5 - 0.5 * math.cos(2.0 * math.pi * index / (len(respiratory) - 1)))
        for index, value in enumerate(respiratory)
    ]
    duration = len(windowed) / respiratory_rate_hz
    first_bin = max(1, math.ceil(0.10 * duration))
    last_bin = max(first_bin, math.floor(0.50 * duration))
    frequencies = [index / duration for index in range(first_bin, last_bin + 1)]
    powers = [_goertzel_power(windowed, frequency, respiratory_rate_hz)
              for frequency in frequencies]
    total_power = sum(powers)
    if total_power > 0:
        dominant_index = max(range(len(powers)), key=powers.__getitem__)
        dominant_hz = frequencies[dominant_index]
        probabilities = [power / total_power for power in powers if power > 0]
        entropy = (-sum(probability * math.log(probability) for probability in probabilities)
                   / math.log(len(powers)) if len(powers) > 1 else 0.0)
        purity = powers[dominant_index] / total_power
        lag = max(1, round(respiratory_rate_hz / dominant_hz))
        autocorrelation = _lag_correlation(respiratory, lag)
        regularity = (
            0.55 * max(0.0, autocorrelation or 0.0)
            + 0.45 * max(0.0, 1.0 - entropy)
        )
        base.update({
            "resp_dominant_hz": round(dominant_hz, 4),
            "resp_spectral_purity": round(purity, 4),
            "resp_spectral_entropy": round(entropy, 4),
            "resp_autocorrelation": round(autocorrelation, 4)
                                    if autocorrelation is not None else None,
            "resp_regularity": round(min(1.0, regularity), 4),
        })

    amplitudes: list[float] = []
    for start in range(0, len(data) - one_second + 1, one_second):
        packet = data[start:start + one_second]
        differences = [packet[index] - packet[index - 1] for index in range(1, len(packet))]
        if differences:
            amplitudes.append(math.sqrt(sum(value * value for value in differences)
                                        / len(differences)))
    amplitude_cv = coefficient_of_variation(amplitudes)
    shifts = 0
    pairs = 0
    for previous, current in zip(amplitudes, amplitudes[1:]):
        if previous <= 0 or current <= 0:
            continue
        pairs += 1
        if max(previous, current) / min(previous, current) >= 2.0:
            shifts += 1
    base.update({
        "bcg_fast_amplitude_cv": round(amplitude_cv, 4) if amplitude_cv is not None else None,
        "bcg_amplitude_shift_ratio": round(shifts / pairs, 4) if pairs else None,
    })

    # Normalize the fitted start-to-end baseline change by the robust waveform
    # span. The scorer does not use this proxy to create a stage; it only marks
    # a window whose sensor baseline may have shifted because of contact,
    # posture, saturation recovery or hardware drift.
    ordered = sorted(data)
    low = ordered[max(0, int(len(ordered) * 0.05) - 1)]
    high = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
    mean_x = (len(data) - 1) / 2.0
    mean_y = sum(data) / len(data)
    denominator = sum((index - mean_x) ** 2 for index in range(len(data)))
    slope = (sum((index - mean_x) * (value - mean_y)
                 for index, value in enumerate(data)) / denominator
             if denominator else 0.0)
    robust_span = max(abs(high - low), 1.0)
    drift_ratio = abs(slope) * max(0, len(data) - 1) / robust_span
    base.update({
        "bcg_baseline_drift_ratio": round(drift_ratio, 4),
        # Engineering data-quality threshold pending sensor/PSG validation.
        "bcg_baseline_drift_flag": drift_ratio > 1.0,
    })
    return base


def summary_features(
    heart_rates: Iterable[float],
    respiration_rates: Iterable[float],
    sample_seconds: float = 10.0,
) -> dict[str, float | None]:
    """Trend/stability features from fixed-cadence HR/RR summaries."""
    hrs = finite_values(heart_rates)
    rrs = finite_values(respiration_rates)
    hr_cv = coefficient_of_variation(hrs)
    rr_cv = coefficient_of_variation(rrs)
    return {
        "hr_cv": round(hr_cv, 4) if hr_cv is not None else None,
        "rr_cv": round(rr_cv, 4) if rr_cv is not None else None,
        "hr_slope_bpm_per_min": (
            round(value, 4) if (value := linear_slope_per_minute(hrs, sample_seconds)) is not None
            else None
        ),
        "rr_slope_per_min": (
            round(value, 4) if (value := linear_slope_per_minute(rrs, sample_seconds)) is not None
            else None
        ),
    }
