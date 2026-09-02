#!/usr/bin/env python3
"""Apply an auditable calibration delta to historical ZEEP sound estimates.

The SPH0645 raw stream is expressed as dBFS while Session ``timeline.sound``
stores the calibrated estimate that was active at capture time.  When an
operator approves a later additive correction, this tool applies that delta
only to rows before the new calibration became active.  Rows at/after the
cutoff are left untouched so the correction cannot be applied twice.

Negative recalculated values follow the live runtime policy: they are invalid
and therefore hold the preceding valid value within the same Session.  The
tool also adjusts the matching acoustic evidence and human-readable reason in
``sleep_stage`` events.  Sleep stages, physiology, raw BCG and all other Sensor
channels remain unchanged.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import sqlite3
from typing import Any


MAINTENANCE_TOOL_NAME = "recalibrate_sound_history.py"
SOUND_REASON = re.compile(r"(เสียงเฉลี่ย\s+)(-?\d+(?:\.\d+)?)(\s*dBA)")


def _finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"stored timestamp requires timezone: {value}")
    return parsed.astimezone(timezone.utc)


def _shift(value: Any, delta_db: float) -> Any:
    if not _finite_number(value):
        return value
    return round(max(0.0, float(value) + delta_db), 2)


def _shift_reason(reason: Any, delta_db: float) -> Any:
    if not isinstance(reason, str):
        return reason

    def replace(match: re.Match[str]) -> str:
        shifted = max(0.0, float(match.group(2)) + delta_db)
        return f"{match.group(1)}{shifted:.1f}{match.group(3)}"

    return SOUND_REASON.sub(replace, reason)


def _shift_sleep_event(value: str, delta_db: float) -> tuple[str, bool]:
    try:
        payload = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return value, False
    if not isinstance(payload, dict):
        return value, False

    changed = False
    reason = _shift_reason(payload.get("reason"), delta_db)
    if reason != payload.get("reason"):
        payload["reason"] = reason
        changed = True

    acoustic = (
        (((payload.get("metrics") or {}).get("auxiliary_evidence") or {})
         .get("acoustic") or {})
    )
    for key in ("mean_leq_dba", "max_leq_dba"):
        old = acoustic.get(key)
        new = _shift(old, delta_db)
        if new != old:
            acoustic[key] = new
            changed = True

    if not changed:
        return value, False
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")), True


def recalibrate_sound_history(
    database_path: Path,
    *,
    session_id: str,
    before: str,
    delta_db: float,
    apply: bool,
) -> dict[str, Any]:
    """Return a preview or atomically apply one historical sound correction."""
    if not math.isfinite(delta_db) or not -60.0 <= delta_db <= 60.0:
        raise ValueError("delta_db must be finite and between -60 and +60 dB")
    session_id = session_id.strip()
    if not session_id:
        raise ValueError("session_id is required")
    cutoff = datetime.fromisoformat(before.replace("Z", "+00:00"))
    if cutoff.tzinfo is None:
        raise ValueError("before timestamp must include a timezone")
    cutoff_iso = cutoff.astimezone(timezone.utc).isoformat()
    ledger_key = (
        "sound_recalibration:"
        f"{session_id}:{cutoff_iso}:{delta_db:+.2f}"
    )

    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("BEGIN IMMEDIATE" if apply else "BEGIN")
        existing = connection.execute(
            "SELECT value FROM schema_meta WHERE key=?", (ledger_key,)
        ).fetchone()
        if existing is not None:
            raise RuntimeError(f"correction already applied: {ledger_key}")

        rows = [
            row for row in connection.execute(
                "SELECT id,session_id,timestamp,sound FROM timeline "
                "WHERE session_id=? AND sound IS NOT NULL ORDER BY id",
                (session_id,),
            )
            if _timestamp(row["timestamp"]) < cutoff.astimezone(timezone.utc)
        ]
        rows.sort(key=lambda row: (_timestamp(row["timestamp"]), int(row["id"])))
        previous_valid: dict[str, float] = {}
        timeline_updates: list[tuple[float | None, int]] = []
        held_rows = 0
        before_values: list[float] = []
        after_values: list[float] = []
        sessions = set()
        for row in rows:
            old = float(row["sound"])
            candidate = old + delta_db
            session_id = str(row["session_id"])
            sessions.add(session_id)
            before_values.append(old)
            if math.isfinite(candidate) and candidate >= 0.0:
                corrected: float | None = round(min(120.0, candidate), 2)
                previous_valid[session_id] = corrected
            else:
                corrected = previous_valid.get(session_id)
                held_rows += 1
            timeline_updates.append((corrected, int(row["id"])))
            if corrected is not None:
                after_values.append(corrected)

        event_updates: list[tuple[str, int]] = []
        event_rows = [
            row for row in connection.execute(
                "SELECT id,timestamp,value FROM events WHERE type='sleep_stage' "
                "AND session_id=? ORDER BY id",
                (session_id,),
            )
            if _timestamp(row["timestamp"]) < cutoff.astimezone(timezone.utc)
        ]
        for row in event_rows:
            shifted, changed = _shift_sleep_event(row["value"], delta_db)
            if changed:
                event_updates.append((shifted, int(row["id"])))

        report = {
            "database": str(database_path),
            "session_id": session_id,
            "before": cutoff_iso,
            "delta_db": round(delta_db, 2),
            "timeline_rows": len(timeline_updates),
            "sessions": len(sessions),
            "held_invalid_rows": held_rows,
            "sleep_stage_events": len(event_updates),
            "old_average_dba": (
                round(sum(before_values) / len(before_values), 2)
                if before_values else None
            ),
            "new_average_dba": (
                round(sum(after_values) / len(after_values), 2)
                if after_values else None
            ),
            "applied": bool(apply),
            "ledger_key": ledger_key,
        }
        if apply:
            connection.executemany(
                "UPDATE timeline SET sound=? WHERE id=?", timeline_updates
            )
            connection.executemany(
                "UPDATE events SET value=? WHERE id=?", event_updates
            )
            audit = {
                **report,
                "applied_at_utc": datetime.now(timezone.utc).isoformat(),
                "policy": "additive_delta; negative_result_holds_previous_valid",
                "raw_bcg_changed": False,
                "sleep_stage_changed": False,
            }
            connection.execute(
                "INSERT INTO schema_meta(key,value) VALUES(?,?)",
                (ledger_key, json.dumps(audit, ensure_ascii=False)),
            )
            connection.commit()
        else:
            connection.rollback()
        return report
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("data/sessions.db"))
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--before", required=True, help="Timezone-aware cutoff")
    parser.add_argument("--delta-db", required=True, type=float)
    parser.add_argument("--apply", action="store_true", help="Commit the correction")
    args = parser.parse_args()
    report = recalibrate_sound_history(
        args.database, session_id=args.session_id, before=args.before,
        delta_db=args.delta_db, apply=args.apply
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
