#!/usr/bin/env python3
"""Run the coded, read-only ZEEP Wake lock-in shadow audit."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sleep_system_policy import SLEEP_ESTIMATOR_VERSION
from zeep_pod.sessions.wake_lock_audit import (
    AUDIT_POLICY_VERSION,
    find_suspected_wake_lock_ins,
)


MAINTENANCE_TOOL_NAME = "audit_wake_lock_in.py"


def read_stage_rows(
    sessions_db: Path,
    *,
    since_utc: str,
) -> tuple[list[dict[str, Any]], int]:
    """Read completed Session decisions; raw Timeline/BCG remain untouched."""
    connection = sqlite3.connect(
        f"file:{sessions_db}?mode=ro",
        uri=True,
        timeout=10,
    )
    connection.row_factory = sqlite3.Row
    try:
        sessions_reviewed = int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM sessions
                WHERE end_time IS NOT NULL AND start_time>=?
                """,
                (since_utc,),
            ).fetchone()[0]
        )
        rows = connection.execute(
            """
            SELECT e.id,e.session_id,e.timestamp,e.value
            FROM events AS e
            JOIN sessions AS s ON s.session_id=e.session_id
            WHERE e.type='sleep_stage'
              AND s.end_time IS NOT NULL
              AND s.start_time>=?
            ORDER BY e.session_id,e.timestamp,e.id
            """,
            (since_utc,),
        ).fetchall()
    finally:
        connection.close()

    parsed: list[dict[str, Any]] = []
    for row in rows:
        try:
            payload = json.loads(row["value"] or "{}")
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        parsed.append(
            {
                "id": row["id"],
                "session_id": row["session_id"],
                "timestamp": row["timestamp"],
                "payload": payload,
            }
        )
    return parsed, sessions_reviewed


def atomic_private_json(path: Path, payload: dict[str, Any]) -> None:
    """Write owner-only audit output without exposing health records."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def default_since_utc(days: int) -> str:
    """Return a bounded UTC lookback suitable for the daily timer."""
    since = datetime.now(UTC) - timedelta(days=max(1, days))
    return since.isoformat()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--since-utc")
    parser.add_argument("--lookback-days", type=int, default=2)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/maintenance/wake-lock-audit-latest.json"),
    )
    parser.add_argument("--fail-on-findings", action="store_true")
    args = parser.parse_args()

    since_utc = args.since_utc or default_since_utc(args.lookback_days)
    rows, sessions_reviewed = read_stage_rows(
        args.data_dir / "sessions.db",
        since_utc=since_utc,
    )
    findings = find_suspected_wake_lock_ins(
        rows,
        estimator_version=SLEEP_ESTIMATOR_VERSION,
    )
    payload = {
        "policy_version": AUDIT_POLICY_VERSION,
        "estimator_version": SLEEP_ESTIMATOR_VERSION,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "scope": {
            "since_utc": since_utc,
            "completed_sessions_reviewed": sessions_reviewed,
            "stage_events_reviewed": len(rows),
        },
        "thresholds": {
            "minimum_duration_s": 600,
            "maximum_gap_s": 45,
            "maximum_movement_ratio": 0.10,
            "required_evidence_ratio": 0.90,
        },
        "finding_count": len(findings),
        "status": "review_required" if findings else "clear",
        "findings": findings,
        "governance": {
            "admin_qa_only": True,
            "automatic_relabel": False,
            "raw_data_modified": False,
            "score_modified": False,
        },
    }
    atomic_private_json(args.output, payload)
    print(
        json.dumps(
            {
                "status": payload["status"],
                "sessions_reviewed": sessions_reviewed,
                "finding_count": len(findings),
                "output": str(args.output),
            },
            separators=(",", ":"),
        )
    )
    return 1 if args.fail_on_findings and findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
