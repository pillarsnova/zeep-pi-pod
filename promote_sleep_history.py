#!/usr/bin/env python3
"""Promote a reviewed Raw-BCG replay into derived ZEEP wellness results.

The command replaces only ``sleep_stage``, ``sleep_stage_evidence`` and
``sleep_stage_status`` events, plus the derived final report for completed
Sessions at or after the approved pilot cutover. It never updates Timeline rows
or ``bcg.db``. Run without ``--apply`` first; apply requires exact input hashes
from ``audit_sleep_history_shadow.py``.
"""

from __future__ import annotations

import argparse
import atexit
import hashlib
import json
import math
import os
import shutil
import sqlite3
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from audit_sleep_history_shadow import (
    epoch,
    private_write_bytes,
    raw_packet_quality,
    raw_packets,
)
from personal import BaselineStore
from rescore_session_reports import rescore
from sleep_history_policy import promotion_ready, quality_tier
from sleep_signal_features import (
    HR_SANITY_RANGE_BPM,
    RR_SANITY_RANGE_PER_MIN,
    filter_vital_values,
)
from sleep_stage_scoring import align_probabilities_to_emitted_stage
from sleep_system_policy import (
    PERSONAL_BASELINE_LEARNING_START_UTC,
    SLEEP_CONFIRMATION_SECONDS,
    SLEEP_CONTEXT_RESET_GAP_SECONDS,
    SLEEP_ESTIMATOR_VERSION,
    SLEEP_EVIDENCE_EPOCH_SECONDS,
    SLEEP_EVIDENCE_VERSION,
    SLEEP_G2_ONTOLOGY_VERSION,
    SLEEP_HISTORY_BACKFILL_VERSION,
    SLEEP_SENSOR_SAMPLE_SECONDS,
    SLEEP_STAGE_CONFIRMATION_SECONDS,
    ZEEP_SLEEP_BASELINE_VERSION,
    ZEEP_SLEEP_TRANSITION_POLICY_VERSION,
)

MAINTENANCE_TOOL_NAME = "promote_sleep_history.py"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def public_promotion_summary(
    result: dict[str, Any],
    *,
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    """Return CLI-safe aggregate without Session IDs or health details."""
    summary = {
        "applied": bool(result.get("applied")),
        "selected_sessions": int(result.get("selected_sessions") or 0),
        "derived_events": int(result.get("derived_events") or 0),
        "raw_timeline_modified": bool(result.get("raw_timeline_modified")),
        "raw_bcg_modified": bool(result.get("raw_bcg_modified")),
    }
    if result.get("applied"):
        summary.update({
            "reviewed_report_parity_count": len(
                result.get("reviewed_report_parity") or []
            ),
            "baselines_rebuilt": int(result.get("baselines_rebuilt") or 0),
            "sessions_integrity_check": result.get(
                "sessions_integrity_check"
            ),
            "raw_timeline_hash_unchanged": (
                result.get("raw_timeline_sha256_before")
                == result.get("raw_timeline_sha256_after")
            ),
            "raw_bcg_hash_unchanged": (
                result.get("raw_bcg_sha256_before")
                == result.get("raw_bcg_sha256_after")
            ),
        })
    if manifest_path is not None:
        summary["private_manifest"] = str(manifest_path)
    return summary


def timeline_sha256(
    path: Path,
    connection: sqlite3.Connection | None = None,
) -> str:
    """Hash every immutable Timeline value in primary-key order."""
    digest = hashlib.sha256()
    own_connection = connection is None
    connection = connection or sqlite3.connect(path)
    try:
        cursor = connection.execute(
            "SELECT id,session_id,timestamp,temperature,humidity,co2,lux,sound,"
            "heart_rate,respiration_rate,bed_status,pm2_5,voc_index "
            "FROM timeline ORDER BY id"
        )
        for row in cursor:
            digest.update(json.dumps(
                list(row), ensure_ascii=False, separators=(",", ":"),
            ).encode("utf-8"))
            digest.update(b"\n")
    finally:
        if own_connection:
            connection.close()
    return digest.hexdigest()


def object_sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def rebuild_affected_baselines(
    store: BaselineStore,
    account_keys: list[str],
) -> dict[str, Any]:
    """Rebuild only selected accounts and prove other records are unchanged.

    A targeted historical promotion must not turn into a global Personal
    Baseline migration.  ``BaselineStore.update_user`` already rebuilds one
    account from approved reports, so retain the loaded store and call it only
    for the account keys represented by the reviewed Session allowlist.

    The file is JSON and is serialised atomically by ``BaselineStore``.  Record
    preservation is therefore verified over canonical JSON bytes rather than
    whitespace in the container file.
    """
    normalized_keys = [str(value or "").strip() for value in account_keys]
    if any(not value for value in normalized_keys):
        raise RuntimeError("selected Session has no Personal Baseline account key")
    affected_keys = sorted(set(normalized_keys))
    original_keys = set(store.data)
    unrelated_keys = original_keys - set(affected_keys)
    unrelated_before = {
        key: store.data[key]
        for key in sorted(unrelated_keys)
    }
    unrelated_sha256_before = object_sha256(unrelated_before)

    for account_key in affected_keys:
        store.update_user(account_key)

    unrelated_after = {
        key: store.data[key]
        for key in sorted(unrelated_keys)
        if key in store.data
    }
    unexpected_new_keys = set(store.data) - original_keys - set(affected_keys)
    unexpected_removed_keys = unrelated_keys - set(store.data)
    unrelated_sha256_after = object_sha256(unrelated_after)
    if (
        unexpected_new_keys
        or unexpected_removed_keys
        or unrelated_sha256_after != unrelated_sha256_before
    ):
        raise RuntimeError(
            "Personal Baseline rebuild changed an unrelated account record"
        )

    return {
        "scope": "selected_session_account_keys_only",
        "affected_account_count": len(affected_keys),
        "rebuilt_account_count": len(affected_keys),
        "unrelated_account_count": len(unrelated_keys),
        "unrelated_records_preserved": True,
        "preservation_verification": "canonical_json_sha256",
        "unrelated_records_sha256_before": unrelated_sha256_before,
        "unrelated_records_sha256_after": unrelated_sha256_after,
    }


def validate_promotion_reconciliation(
    report: dict[str, Any],
    quality: dict[str, Any],
) -> dict[str, float]:
    """Fail closed unless one promoted report has coherent time accounting."""
    sleep = report.get("sleep") if isinstance(report, dict) else None
    accounting = (
        sleep.get("classification_accounting")
        if isinstance(sleep, dict) else None
    )
    if not isinstance(accounting, dict):
        raise RuntimeError("promotion report has no classification accounting")

    for key in (
        "display_stage_total_reconciles",
        "score_stage_total_reconciles",
    ):
        if accounting.get(key) is not True:
            raise RuntimeError(f"promotion report failed {key}")

    invariant = accounting.get("arithmetic_invariant")
    if not isinstance(invariant, dict) or invariant.get("holds") is not True:
        raise RuntimeError("promotion report failed arithmetic invariant")

    def finite_seconds(value: Any, label: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise RuntimeError(f"promotion result has invalid {label}")
        seconds = float(value)
        if not math.isfinite(seconds) or seconds < 0:
            raise RuntimeError(f"promotion result has invalid {label}")
        return seconds

    report_seconds = finite_seconds(
        sleep.get("actual_scored_s"), "report actual_scored_s"
    )
    quality_seconds = finite_seconds(
        quality.get("actual_scored_s"), "quality actual_scored_s"
    )
    delta_seconds = report_seconds - quality_seconds
    if abs(delta_seconds) > 0.11:
        raise RuntimeError(
            "promotion report/quality actual_scored_s mismatch: "
            f"report={report_seconds}, quality={quality_seconds}"
        )
    return {
        "report_actual_scored_s": report_seconds,
        "quality_actual_scored_s": quality_seconds,
        "actual_scored_delta_s": round(delta_seconds, 3),
    }


def reviewed_mode_group(item: dict[str, Any]) -> str:
    """Return explicit historical intent, never an ``auto`` score fallback.

    The shadow scorer may create an engineering-only mode suggestion from an
    unresolved legacy row.  That suggestion is useful for Admin review but it
    cannot decide whether a persisted result is Sleep Score or Recovery Score.
    Promotion therefore uses ``previous_mode`` as the authoritative intent and
    preserves the old report when that intent is still unresolved.
    """
    previous = item.get("previous_mode")
    if isinstance(previous, dict):
        group = str(previous.get("group") or "")
        if group in {"sleep", "nap_recovery"}:
            return group
        return "unresolved"
    # Backward compatibility for a reviewed artifact created before
    # ``previous_mode`` was recorded.
    mode = item.get("mode")
    group = str((mode or {}).get("group") or "") if isinstance(mode, dict) else ""
    return group if group in {"sleep", "nap_recovery"} else "unresolved"


def cohort_minimum_duration_seconds(artifact: dict[str, Any]) -> float:
    """Return the reviewed cohort duration floor pinned in the artifact.

    The audit command owns cohort selection. Promotion must reproduce that
    reviewed selection instead of silently reapplying the legacy 25-minute
    cutoff, because short recovery Sessions can still contain valid epochs.
    """
    value = (artifact.get("cohort") or {}).get(
        "minimum_minutes_exclusive", 25.0
    )
    try:
        minutes = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid cohort minimum duration") from exc
    if minutes < 0:
        raise ValueError("cohort minimum duration cannot be negative")
    return minutes * 60.0


def session_is_in_reviewed_cohort(
    *,
    start_time: Any,
    end_time: Any,
    duration: Any,
    minimum_duration_seconds: float,
) -> bool:
    """Validate immutable Session boundaries against the reviewed cohort."""
    try:
        duration_seconds = float(duration or 0.0)
    except (TypeError, ValueError):
        return False
    return bool(
        end_time is not None
        and str(start_time or "") >= PERSONAL_BASELINE_LEARNING_START_UTC
        and duration_seconds > minimum_duration_seconds
    )


def _quality_tier(
    sessions: sqlite3.Connection,
    bcg: sqlite3.Connection,
    session_id: str,
) -> tuple[str, dict[str, float]]:
    """Recompute Tier from immutable DB rows; never trust the artifact label."""
    row = sessions.execute(
        "SELECT start_time,end_time,duration FROM sessions WHERE session_id=?",
        (session_id,),
    ).fetchone()
    if row is None or row[1] is None:
        return "below_B", {}
    timeline = sessions.execute(
        "SELECT heart_rate,respiration_rate FROM timeline WHERE session_id=?",
        (session_id,),
    ).fetchall()
    paired = sum(bool(
        filter_vital_values([item[0]], HR_SANITY_RANGE_BPM)
        and filter_vital_values([item[1]], RR_SANITY_RANGE_PER_MIN)
    ) for item in timeline)
    timeline_ratio = paired / len(timeline) if timeline else 0.0
    packets = raw_packets(bcg, session_id)
    raw = raw_packet_quality(packets, epoch(row[0]), epoch(row[1]))
    tier = quality_tier(
        timeline_paired_hr_rr=timeline_ratio,
        raw_paired_hr_rr=raw["paired_vital_coverage"],
        raw_acquisition=raw["acquisition_coverage"],
        raw_maximum_gap_s=raw["maximum_packet_gap_s"],
        context_reset_gap_s=SLEEP_CONTEXT_RESET_GAP_SECONDS,
    )
    return tier, {
        "timeline_paired_hr_rr": timeline_ratio,
        "raw_paired_hr_rr": raw["paired_vital_coverage"],
        "raw_acquisition": raw["acquisition_coverage"],
        "raw_maximum_gap_s": raw["maximum_packet_gap_s"],
    }


def iso_utc(timestamp: float) -> str:
    return datetime.fromtimestamp(
        float(timestamp), timezone.utc,  # noqa: UP017 -- Python 3.9 support
    ).isoformat()


def confidence(evidence: dict[str, Any]) -> str:
    value = float((evidence.get("quality") or {}).get("winner_value") or 0.0)
    return "high" if value >= 0.72 else "medium" if value >= 0.48 else "low"


class _DatabaseReader:
    """Minimal adapter used by BaselineStore during an offline rebuild."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def read_sessions(self, query: str, params: tuple[Any, ...] = ()):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            return connection.execute(query, params).fetchall()
        finally:
            connection.close()


def _event_values(session: dict[str, Any]) -> list[tuple[str, str, str]]:
    evidence_by_time = {
        round(float(row["t"]), 3): row for row in session.get("evidence_rows") or []
    }
    values: list[tuple[str, str, str]] = []
    for evidence in session.get("evidence_rows") or []:
        when = float(evidence["t"])
        payload = {
            "candidate": evidence.get("candidate"),
            "probabilities": evidence.get("probabilities") or {},
            "pre_fusion_probabilities": (
                evidence.get("pre_fusion_probabilities") or {}
            ),
            "hr_rr_fit_fusion": (
                evidence.get("hr_rr_fit_fusion") or {}
            ),
            "confidence": confidence(evidence),
            "reason": "replayed_from_preserved_raw_bcg",
            "metrics": evidence.get("diagnostics") or {},
            "estimator_version": SLEEP_ESTIMATOR_VERSION,
            "evidence_version": SLEEP_EVIDENCE_VERSION,
            "baseline_version": ZEEP_SLEEP_BASELINE_VERSION,
            "transition_policy_version": ZEEP_SLEEP_TRANSITION_POLICY_VERSION,
            "g2_ontology_version": SLEEP_G2_ONTOLOGY_VERSION,
            "window_start": iso_utc(when - 60.0),
            "window_end": iso_utc(when),
            "attribution_start": iso_utc(
                when - SLEEP_EVIDENCE_EPOCH_SECONDS
            ),
            "attribution_end": iso_utc(when),
            "sample_count": 6,
            "sensor_sample_interval_s": SLEEP_SENSOR_SAMPLE_SECONDS,
            "evidence_epoch_s": SLEEP_EVIDENCE_EPOCH_SECONDS,
            "confirmation": evidence.get("transition") or {},
            "decision_kind": "historical_physiological_evidence",
            "historical_replay_version": SLEEP_HISTORY_BACKFILL_VERSION,
        }
        values.append((iso_utc(when), "sleep_stage_evidence", json.dumps(
            payload, ensure_ascii=False, separators=(",", ":"))))

    for status_row in session.get("status_rows") or []:
        when = float(status_row["t"])
        payload = {
            **status_row,
            "timestamp": iso_utc(when),
            "window_start": iso_utc(when - SLEEP_EVIDENCE_EPOCH_SECONDS),
            "window_end": iso_utc(when),
            "decision_kind": "historical_operational_status",
            "historical_replay_version": SLEEP_HISTORY_BACKFILL_VERSION,
            "raw_source_modified": False,
        }
        payload.pop("t", None)
        values.append((iso_utc(when), "sleep_stage_status", json.dumps(
            payload, ensure_ascii=False, separators=(",", ":"))))

    previous = None
    progression: list[str] = []
    for state_row in session.get("state_rows") or []:
        when = float(state_row["t"])
        stage = str(state_row["state"])
        evidence = evidence_by_time.get(round(when, 3), {})
        held_previous_state = bool(state_row.get("held_previous_state"))
        evidence_probabilities = evidence.get("probabilities") or {}
        probabilities = (
            dict(evidence_probabilities)
            if held_previous_state
            else align_probabilities_to_emitted_stage(
                evidence_probabilities, stage, winner_margin=0.01,
            )
        )
        changed = stage != previous
        if changed:
            if stage == "wake":
                progression = ["wake"]
            else:
                progression.append(stage)
                progression = progression[-8:]
        payload = {
            "state": stage,
            "probabilities": {key: round(value, 4) for key, value in probabilities.items()},
            "confidence": confidence(evidence),
            "reason": (
                "continuity_hold_from_preserved_raw_bcg_replay"
                if held_previous_state
                else "confirmed_from_preserved_raw_bcg_replay"
            ),
            "progression": progression,
            "metrics": state_row.get("metrics") or {},
            "estimator_version": SLEEP_ESTIMATOR_VERSION,
            "evidence_version": SLEEP_EVIDENCE_VERSION,
            "baseline_version": ZEEP_SLEEP_BASELINE_VERSION,
            "transition_policy_version": ZEEP_SLEEP_TRANSITION_POLICY_VERSION,
            "g2_ontology_version": SLEEP_G2_ONTOLOGY_VERSION,
            "window_start": iso_utc(when - 60.0),
            "window_end": iso_utc(when),
            # The rolling Evidence window is 60 seconds, but one State row
            # owns only its canonical 30-second attribution interval.  Persist
            # both explicitly so report rebuilds cannot shift the label into
            # the following Timeline bucket.
            "attribution_start": iso_utc(float(
                state_row.get(
                    "attribution_start",
                    when - SLEEP_EVIDENCE_EPOCH_SECONDS,
                )
            )),
            "attribution_end": iso_utc(float(
                state_row.get("attribution_end", when)
            )),
            "sample_count": 6,
            "sensor_sample_interval_s": SLEEP_SENSOR_SAMPLE_SECONDS,
            "sample_interval_s": SLEEP_EVIDENCE_EPOCH_SECONDS,
            "confirmation_seconds": SLEEP_STAGE_CONFIRMATION_SECONDS.get(
                stage, SLEEP_CONFIRMATION_SECONDS),
            "confirmation": (
                state_row.get("confirmation")
                or evidence.get("transition")
                or {}
            ),
            "decision_kind": (
                "historical_continuity_hold"
                if held_previous_state
                else "historical_confirmed_state"
            ),
            "held_previous_state": held_previous_state,
            "provisional": bool(state_row.get("provisional")),
            "pending_state": state_row.get("pending_state"),
            "score_attribution_state": (
                state_row.get("score_attribution_state") or stage
            ),
            "challenger_counted_as_new_state": bool(
                state_row.get("challenger_counted_as_new_state")
            ),
            "score_eligible": bool(
                state_row.get("score_eligible", True)
            ),
            "excluded_from_score": bool(
                state_row.get("excluded_from_score", False)
            ),
            "excluded_from_personal_baseline": bool(
                state_row.get(
                    "excluded_from_personal_baseline", False
                )
            ),
            "state_changed": changed,
            "historical_replay_version": SLEEP_HISTORY_BACKFILL_VERSION,
            "raw_source_modified": False,
        }
        values.append((iso_utc(when), "sleep_stage", json.dumps(
            payload, ensure_ascii=False, separators=(",", ":"))))
        previous = stage
    return values


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--artifact", required=True, type=Path)
    parser.add_argument(
        "--summary-manifest", type=Path,
        help="Summary manifest that cryptographically pins the details artifact",
    )
    parser.add_argument(
        "--offline-confirmed", action="store_true",
        help="Operator confirms the Pod service/writers are stopped",
    )
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    artifact = json.loads(args.artifact.read_text(encoding="utf-8"))
    if args.apply and not args.offline_confirmed:
        raise SystemExit(
            "--apply requires --offline-confirmed after stopping the Pod service"
        )
    summary_manifest = None
    summary_manifest_sha256 = None
    if args.summary_manifest:
        summary_manifest_sha256 = file_sha256(args.summary_manifest)
        summary_manifest = json.loads(args.summary_manifest.read_text(encoding="utf-8"))
        if summary_manifest.get("promotion_details_sha256") != file_sha256(args.artifact):
            raise SystemExit("details artifact SHA does not match the reviewed summary manifest")
        for key in ("analysis_run_id", "promotion_payload_sha256"):
            if summary_manifest.get(key) != artifact.get(key):
                raise SystemExit(f"details artifact {key} does not match summary manifest")
    elif args.apply:
        raise SystemExit("--apply requires --summary-manifest")
    if artifact.get("promotion_payload_sha256") != object_sha256(
        artifact.get("sessions") or {}
    ):
        raise SystemExit("details artifact promotion payload hash is invalid")
    sessions_db = args.data_dir / "sessions.db"
    bcg_db = args.data_dir / "bcg.db"
    session_guard = sqlite3.connect(sessions_db, timeout=2)
    bcg_guard = sqlite3.connect(bcg_db, timeout=2)
    session_guard.row_factory = sqlite3.Row
    bcg_guard.row_factory = sqlite3.Row

    def close_guards() -> None:
        for connection in (session_guard, bcg_guard):
            try:
                connection.rollback()
            except sqlite3.Error:
                pass
            try:
                connection.close()
            except sqlite3.Error:
                pass

    atexit.register(close_guards)
    if args.apply:
        # The operator stops the service first. SQLite then proves there is no
        # remaining writer, checkpoints both WALs, and holds exclusive locks
        # through the atomic swap so a stale sidecar cannot split generations.
        for label, connection in (
            ("sessions.db", session_guard), ("bcg.db", bcg_guard),
        ):
            checkpoint = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            if checkpoint and int(checkpoint[0]) != 0:
                raise SystemExit(f"{label} WAL is busy; a writer is still active")
            connection.execute("PRAGMA locking_mode=EXCLUSIVE")
            try:
                connection.execute("BEGIN EXCLUSIVE")
            except sqlite3.OperationalError as exc:
                raise SystemExit(f"{label} cannot obtain exclusive lock: {exc}") from exc
    expected = artifact.get("input_sha256") or {}
    actual = {"sessions_db": file_sha256(sessions_db), "bcg_db": file_sha256(bcg_db)}
    if expected.get("sessions_db") != actual["sessions_db"]:
        raise SystemExit("sessions.db changed after replay; create a fresh artifact")
    if expected.get("bcg_db") != actual["bcg_db"]:
        raise SystemExit("bcg.db changed after replay; create a fresh artifact")
    profiles_path = args.data_dir / "profiles.json"
    if expected.get("profiles_file"):
        if not profiles_path.exists():
            raise SystemExit("profiles.json missing after replay; create a fresh artifact")
        actual["profiles_file"] = file_sha256(profiles_path)
        if expected["profiles_file"] != actual["profiles_file"]:
            raise SystemExit("profiles.json changed after replay; create a fresh artifact")
    source_hashes = ((artifact.get("code_provenance") or {}).get("source_sha256") or {})
    source_root = Path(__file__).resolve().parent
    for source_name, expected_hash in source_hashes.items():
        source_path = source_root / source_name
        if not source_path.exists() or file_sha256(source_path) != expected_hash:
            raise SystemExit(
                f"replay source changed after audit ({source_name}); create a fresh artifact"
            )
    if (artifact.get("cohort") or {}).get("start_utc_inclusive") != PERSONAL_BASELINE_LEARNING_START_UTC:
        raise SystemExit("artifact cutover does not match current policy")
    versions = artifact.get("versions") or {}
    if versions.get("replay") != SLEEP_HISTORY_BACKFILL_VERSION:
        raise SystemExit("artifact replay version does not match current policy")
    if versions.get("estimator") != SLEEP_ESTIMATOR_VERSION:
        raise SystemExit("artifact estimator version does not match current policy")
    acceptance = artifact.get("acceptance") or {}
    if acceptance.get("wellness_derived_promotion_decision") != "PASS_WITH_LIMITATIONS":
        raise SystemExit("artifact is not approved for wellness-derived promotion")

    artifact_sessions = artifact.get("sessions") or {}
    if not isinstance(artifact_sessions, dict):
        raise SystemExit(
            "promotion requires the replay details artifact, not the summary"
        )
    reviewed_ids = (
        ((summary_manifest or {}).get("acceptance") or {}).get(
            "wellness_derived_promotion_eligible_session_ids"
        )
        if summary_manifest else
        (acceptance.get("wellness_derived_promotion_eligible_session_ids") or [])
    )
    reviewed_id_set = set(reviewed_ids or [])
    minimum_duration_seconds = cohort_minimum_duration_seconds(artifact)
    selected = []
    for session_id, item in artifact_sessions.items():
        if session_id not in reviewed_id_set:
            continue
        if not promotion_ready(item):
            raise SystemExit(
                f"reviewed Session has derived promotion blockers: {session_id} "
                f"{item.get('promotion_blockers') or []}"
            )
        if reviewed_mode_group(item) in {"sleep", "nap_recovery"}:
            try:
                validate_promotion_reconciliation(
                    item.get("report") or {}, item.get("quality") or {}
                )
            except RuntimeError as exc:
                raise SystemExit(
                    f"reviewed Session reconciliation failed for {session_id}: "
                    f"{exc}"
                ) from exc
        db_row = session_guard.execute(
            "SELECT username_key,start_time,end_time,duration FROM sessions "
            "WHERE session_id=?",
            (session_id,),
        ).fetchone()
        if db_row is None or not session_is_in_reviewed_cohort(
            start_time=db_row[1],
            end_time=db_row[2],
            duration=db_row[3],
            minimum_duration_seconds=minimum_duration_seconds,
        ):
            raise SystemExit(f"artifact selected ineligible Session: {session_id}")
        identity = {
            "email": db_row[0], "start_time": db_row[1],
            "end_time": db_row[2], "duration": db_row[3],
        }
        mismatched_identity = {
            key: {"artifact": item.get(key), "database": value}
            for key, value in identity.items() if item.get(key) != value
        }
        if mismatched_identity:
            raise SystemExit(
                f"artifact/DB Session identity mismatch for {session_id}: "
                f"{mismatched_identity}"
            )
        recomputed_tier, tier_evidence = _quality_tier(
            session_guard, bcg_guard, session_id,
        )
        if item.get("quality_tier") != recomputed_tier:
            raise SystemExit(
                f"recomputed quality tier differs for {session_id}: "
                f"{recomputed_tier} {tier_evidence}"
            )
        selected.append((session_id, item, _event_values(item)))

    selected_ids = [item[0] for item in selected]
    if sorted(selected_ids) != sorted(reviewed_ids or []):
        raise SystemExit(
            "selected Session allowlist does not match reviewed summary manifest"
        )

    timeline_before = timeline_sha256(sessions_db, session_guard)
    preview = {
        "applied": False,
        "analysis_run_id": artifact.get("analysis_run_id"),
        "cutover_utc": PERSONAL_BASELINE_LEARNING_START_UTC,
        "selected_sessions": len(selected),
        "selected_ids": selected_ids,
        "score_report_mode_unresolved_ids": [
            session_id for session_id, item, _events in selected
            if reviewed_mode_group(item) == "unresolved"
        ],
        "derived_events": sum(len(item[2]) for item in selected),
        "raw_timeline_modified": False,
        "raw_bcg_modified": False,
        "raw_timeline_sha256_before": timeline_before,
    }
    if not args.apply:
        print(json.dumps(
            public_promotion_summary(preview),
            ensure_ascii=False,
            indent=2,
        ))
        return 0

    backup_dir = args.data_dir.parent / "backup"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = backup_dir / f"sessions-pre-wellness-replay-{stamp}.db"
    # WAL has been checkpointed and an exclusive read transaction now freezes
    # the main DB file, so this filesystem copy is a consistent rollback image.
    shutil.copy2(sessions_db, backup_path)
    baseline_path = args.data_dir / "baselines.json"
    baseline_backup = None
    if baseline_path.exists():
        baseline_backup = backup_dir / f"baselines-pre-wellness-replay-{stamp}.json"
        shutil.copy2(baseline_path, baseline_backup)

    def restore_live_from_backup() -> None:
        """Restore derived DB/baseline if install or final audit persistence fails."""
        session_guard.rollback()
        restore_source = sqlite3.connect(backup_path)
        try:
            restore_source.backup(session_guard)
        finally:
            restore_source.close()
        if baseline_backup is not None:
            shutil.copy2(baseline_backup, baseline_path)
        elif baseline_path.exists():
            baseline_path.unlink()

    staging_dir = Path(tempfile.mkdtemp(
        prefix=f".wellness-replay-stage-{stamp}-",
        dir=args.data_dir.parent,
    ))
    staged_sessions_db = staging_dir / "sessions.db"
    staged_baseline_path = staging_dir / "baselines.json"
    shutil.copy2(backup_path, staged_sessions_db)
    if baseline_path.exists():
        shutil.copy2(baseline_path, staged_baseline_path)

    # All derived changes are built and checked on a private staging copy.
    # The live database is replaced only after reports, baselines, integrity
    # and immutable-Raw hashes have all passed.
    connection = sqlite3.connect(staged_sessions_db, timeout=30)
    connection.execute("PRAGMA busy_timeout=30000")
    now = datetime.now(
        timezone.utc,  # noqa: UP017 -- Python 3.9 support
    ).isoformat()
    try:
        connection.execute("BEGIN IMMEDIATE")
        for session_id, item, events in selected:
            row = connection.execute(
                "SELECT start_time,end_time,duration FROM sessions "
                "WHERE session_id=?",
                (session_id,),
            ).fetchone()
            if not row or not session_is_in_reviewed_cohort(
                start_time=row[0],
                end_time=row[1],
                duration=row[2],
                minimum_duration_seconds=minimum_duration_seconds,
            ):
                raise RuntimeError(f"ineligible Session: {session_id}")
            old_rows = connection.execute(
                "SELECT timestamp,type,value FROM events WHERE session_id=? "
                "AND type IN "
                "('sleep_stage','sleep_stage_evidence','sleep_stage_status') "
                "ORDER BY timestamp,id",
                (session_id,),
            ).fetchall()
            old_counts = dict(Counter(row[1] for row in old_rows))
            old_derived_sha256 = object_sha256([
                {
                    "timestamp": row[0],
                    "type": row[1],
                    "value": row[2],
                }
                for row in old_rows
            ])
            connection.execute(
                "DELETE FROM events WHERE session_id=? "
                "AND type IN "
                "('sleep_stage','sleep_stage_evidence','sleep_stage_status')",
                (session_id,),
            )
            connection.executemany(
                "INSERT INTO events(session_id,timestamp,type,value) VALUES (?,?,?,?)",
                [(session_id, timestamp, kind, value) for timestamp, kind, value in events],
            )
            audit = {
                "analysis_run_id": artifact.get("analysis_run_id"),
                "version": SLEEP_HISTORY_BACKFILL_VERSION,
                "promoted_at_utc": now,
                "quality_tier": item.get("quality_tier"),
                "old_derived_event_counts": old_counts,
                "old_derived_event_sha256": old_derived_sha256,
                "new_derived_event_count": len(events),
                "new_operational_status_count": len(
                    item.get("status_rows") or []
                ),
                "rollback_backup": str(backup_path),
                "old_result_recoverable": True,
                "raw_timeline_modified": False,
                "raw_bcg_modified": False,
            }
            connection.execute(
                "INSERT INTO events(session_id,timestamp,type,value) VALUES (?,?,?,?)",
                (session_id, now, "sleep_history_reprocessed", json.dumps(
                    audit, ensure_ascii=False, separators=(",", ":"))),
            )
        connection.commit()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"integrity_check failed: {integrity}")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    try:
        report_sessions = []
        mode_unresolved_sessions = []
        for session_id, item, _ in selected:
            reviewed_mode = reviewed_mode_group(item)
            if reviewed_mode not in {"sleep", "nap_recovery"}:
                # Mode identity determines Sleep Score vs Recovery Score, but
                # it does not invalidate per-Epoch W/N1/N2/N3/REM and
                # NO DATA/OFF BED derivation.  Promote those reviewed rows and
                # preserve the prior score/report until an operator assigns a
                # mode; never abort unrelated Sessions in the same batch.
                mode_unresolved_sessions.append(session_id)
                continue
            one_result = rescore(
                staging_dir, [session_id], requested_mode=reviewed_mode, apply=True,
            )
            report_sessions.extend(one_result.get("sessions") or [])
        report_result = {
            "applied": True,
            "sessions": report_sessions,
            "count": len(report_sessions),
            "mode_unresolved_score_preserved_ids": mode_unresolved_sessions,
        }
        # The promoted DB must reproduce the reviewed shadow artifact exactly
        # for score identity and stage-time accounting.  This guard catches
        # cadence regressions (for example treating a 30-second state as a
        # 10-second Sensor sample) before the live database is replaced.
        reviewed = {session_id: item for session_id, item, _ in selected}
        parity = []
        for rebuilt in report_result.get("sessions") or []:
            session_id = rebuilt["session_id"]
            expected_item = reviewed[session_id]
            expected_quality = expected_item.get("quality") or {}
            expected_report = expected_item.get("report") or {}
            reconciliation = validate_promotion_reconciliation(
                rebuilt.get("report") or {}, rebuilt.get("quality") or {}
            )
            expected_counts = Counter(
                str(row.get("state"))
                for row in (
                    expected_item.get("report_state_rows")
                    or expected_item.get("state_rows")
                    or []
                )
            )
            checks = {
                "quality": (expected_quality, rebuilt.get("quality") or {}),
                "report": (expected_report, rebuilt.get("report") or {}),
                "rest_mode": (
                    expected_item.get("mode") or {}, rebuilt.get("rest_mode") or {},
                ),
                "state_counts": (
                    {stage: int(expected_counts.get(stage, 0))
                     for stage in ("wake", "n1", "n2", "n3", "rem")},
                    rebuilt.get("counts") or {},
                ),
            }
            failures = {
                key: {"reviewed": pair[0], "rebuilt": pair[1]}
                for key, pair in checks.items()
                if pair[0] != pair[1]
            }
            if failures:
                raise RuntimeError(
                    f"reviewed/rebuilt report mismatch for {session_id}: {failures}"
                )
            parity.append({
                "session_id": session_id,
                "status": "exact_full_quality_mode_counts_report",
                "reconciliation": reconciliation,
            })
        parity.extend({
            "session_id": session_id,
            "status": "derived_epochs_only_mode_unresolved_score_preserved",
            "reconciliation": None,
        } for session_id in mode_unresolved_sessions)

        # Rebuild learned context only for accounts changed by this reviewed
        # promotion. Historical Raw Sensor/BCG files are not involved, and an
        # allowlisted rerun must preserve every unrelated baseline record.
        reader = _DatabaseReader(staged_sessions_db)
        store = BaselineStore(reader, staging_dir)
        baseline_rebuild = rebuild_affected_baselines(
            store,
            [item.get("email") for _session_id, item, _events in selected],
        )

        check = sqlite3.connect(staged_sessions_db)
        try:
            integrity = check.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            check.close()
        if integrity != "ok":
            raise RuntimeError(f"staged integrity_check failed: {integrity}")
        timeline_after = timeline_sha256(staged_sessions_db)
        bcg_after = file_sha256(bcg_db)
        if timeline_after != timeline_before:
            raise RuntimeError("immutable timeline changed during derived promotion")
        if bcg_after != actual["bcg_db"]:
            raise RuntimeError("immutable raw BCG changed during derived promotion")

        # Install through SQLite's online-backup API rather than replacing the
        # main DB inode. This keeps WAL/SHM generation coherent. The service is
        # already offline and the guard proved no writer survived checkpoint.
        try:
            session_guard.rollback()
            staged_source = sqlite3.connect(staged_sessions_db)
            try:
                staged_source.backup(session_guard)
            finally:
                staged_source.close()
            if staged_baseline_path.exists():
                os.replace(staged_baseline_path, baseline_path)
        except Exception:
            restore_live_from_backup()
            raise
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)

    # Verify the installed copy too. If any post-install invariant fails,
    # restore the rollback image before returning an error; the backup remains
    # available for a second, operator-led verification as well.
    try:
        if session_guard.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("installed sessions.db integrity_check failed")
        if timeline_sha256(sessions_db, session_guard) != timeline_before:
            raise RuntimeError("immutable timeline changed after derived promotion")
        if file_sha256(bcg_db) != actual["bcg_db"]:
            raise RuntimeError("immutable raw BCG changed after derived promotion")
    except Exception:
        restore_live_from_backup()
        raise

    result = {
        **preview,
        "applied": True,
        "sessions_backup": str(backup_path),
        "baselines_backup": str(baseline_backup) if baseline_backup else None,
        "report_rescore": report_result,
        "reviewed_report_parity": parity,
        "baselines_rebuilt": baseline_rebuild["rebuilt_account_count"],
        "baseline_rebuild": baseline_rebuild,
        "sessions_integrity_check": "ok",
        "raw_timeline_sha256_after": timeline_after,
        "raw_bcg_sha256_before": actual["bcg_db"],
        "raw_bcg_sha256_after": bcg_after,
        "reviewed_artifacts": {
            "summary_manifest_sha256": summary_manifest_sha256,
            "details_artifact_sha256": file_sha256(args.artifact),
            "promotion_payload_sha256": artifact.get("promotion_payload_sha256"),
            "input_sha256": expected,
            "code_provenance": artifact.get("code_provenance") or {},
        },
    }
    manifest_path = args.data_dir / "wellness-history-promotion-latest.json"
    try:
        private_write_bytes(
            manifest_path,
            json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8"),
        )
    except Exception:
        restore_live_from_backup()
        raise
    close_guards()
    atexit.unregister(close_guards)
    print(json.dumps(
        public_promotion_summary(result, manifest_path=manifest_path),
        ensure_ascii=False,
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
