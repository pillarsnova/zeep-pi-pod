"""Single audit registry for offline data-maintenance commands.

The registry is intentionally declarative.  Tests and the Admin API use it to
prove that every supported tool documents its write boundary and guardrail.
The tools themselves remain ordinary command-line programs so production data
cannot be changed accidentally through a browser route.
"""

from __future__ import annotations

from typing import Any

from sleep_system_policy import (
    SESSION_REPORT_VERSION,
    SLEEP_HISTORY_BACKFILL_VERSION,
    SLEEP_QUALITY_VERSION,
)


MAINTENANCE_CONTRACT_VERSION = "zeep-maintenance-tools-v1.3"

MAINTENANCE_TOOLS: dict[str, dict[str, Any]] = {
    "reclassify_sleep_history.py": {
        "group": "sleep_replay",
        "purpose": "Legacy event-level comparison only; historical apply is disabled",
        "writes": [],
        "preserves": ["timeline", "raw_bcg"],
        "default_mode": "audit_only",
        "guard": "--apply refuses and directs operators to raw shadow replay",
        "policy_version": SLEEP_HISTORY_BACKFILL_VERSION,
    },
    "audit_sleep_history_shadow.py": {
        "group": "sleep_replay",
        "purpose": (
            "Deterministically replay raw BCG into 10-second frames, 30-second "
            "evidence and confirmed five-state shadow results"
        ),
        "writes": ["explicit_output_manifest_only"],
        "preserves": ["sessions.db", "bcg.db", "events", "timeline", "raw_bcg"],
        "default_mode": "read_only",
        "guard": (
            "SQLite mode=ro + input hashes + no historical writeback without "
            "explicit Product Owner approval; no clinical claim without "
            "independent reference labels"
        ),
        "policy_version": SLEEP_HISTORY_BACKFILL_VERSION,
    },
    "promote_sleep_history.py": {
        "group": "derived_sleep_promotion",
        "purpose": (
            "Promote a hash-verified Raw-BCG replay after the pilot cutover "
            "into versioned ZEEP wellness estimates"
        ),
        "writes": [
            "events.sleep_stage", "events.sleep_stage_evidence",
            "events.sleep_stage_status",
            "events.final_summary", "baselines.json",
        ],
        "preserves": ["timeline", "bcg.db", "raw_bcg", "profiles.json"],
        "default_mode": "dry_run",
        "guard": (
            "exact sessions/bcg SHA-256 + completed post-cutover Session + "
            "reviewed allowlist + per-Session integrity blockers + "
            "SQLite/baseline backup before --apply; QA Tier and warnings do not block"
        ),
        "policy_version": SLEEP_HISTORY_BACKFILL_VERSION,
    },
    "compare_sleep_history_replay.py": {
        "group": "sleep_replay",
        "purpose": (
            "Compare two read-only replay manifests and produce owner-only "
            "JSON/Markdown review artifacts"
        ),
        "writes": ["explicit_comparison_artifacts_only"],
        "preserves": ["sessions.db", "bcg.db", "events", "timeline", "raw_bcg"],
        "default_mode": "read_only",
        "guard": "accepts replay manifests only; output files are mode 0600",
        "policy_version": SLEEP_HISTORY_BACKFILL_VERSION,
    },
    "rescore_session_reports.py": {
        "group": "derived_reports",
        "purpose": "Rebuild final reports without changing stage or raw evidence",
        "writes": ["events.final_summary", "events.report_rescore_audit"],
        "preserves": ["timeline", "events.sleep_stage", "raw_bcg"],
        "default_mode": "dry_run",
        "guard": "online SQLite backup before --apply",
        "policy_version": SLEEP_QUALITY_VERSION,
        "report_version": SESSION_REPORT_VERSION,
    },
    "recalibrate_sound_history.py": {
        "group": "sensor_calibration",
        "purpose": "Apply an approved additive sound delta inside one bounded Session/cutoff",
        "writes": ["timeline.sound", "sleep_stage.acoustic_metadata"],
        "preserves": ["sleep_stage.state", "physiology", "raw_bcg"],
        "default_mode": "dry_run",
        "guard": "session id + UTC cutoff + audit event + backup",
    },
    "cleanup_short_sessions.py": {
        "group": "data_retention",
        "purpose": "One-time guarded deletion of completed Sessions below a threshold",
        "writes": ["sessions", "timeline", "events", "bcg", "profiles", "baselines"],
        "preserves": ["active_session"],
        "default_mode": "dry_run",
        "guard": "one-time marker + service-stopped check + backup",
    },
    "trim_session.py": {
        "group": "data_correction",
        "purpose": "Fulfil a verified correction/deletion cutoff for one completed Session",
        "writes": ["session.end", "timeline", "events", "bcg", "final_summary"],
        "preserves": ["rows before cutoff"],
        "default_mode": "dry_run",
        "guard": "explicit session id, timezone-aware cutoff and reason",
    },
    "reset_sleep_dataset.py": {
        "group": "destructive_reset",
        "purpose": "Lab-only dataset reset while retaining one explicitly selected open run",
        "writes": ["sessions.db", "bcg.db", "profiles", "baselines"],
        "preserves": ["hardware calibration", "authentication configuration"],
        "default_mode": "refuse_without_confirmation",
        "guard": "exact confirmation phrase + service must be stopped",
    },
    "annotate_sleep_stage.py": {
        "group": "human_annotation",
        "purpose": "Add separate time-bounded annotation without rewriting raw decision",
        "writes": ["events.sleep_stage_annotation", "events.final_summary"],
        "preserves": ["events.sleep_stage", "timeline", "raw_bcg"],
        "default_mode": "dry_run",
        "guard": "completed Session + bounded interval + source/reason/author + backup",
    },
}


def maintenance_contract_snapshot() -> dict[str, Any]:
    return {
        "contract_version": MAINTENANCE_CONTRACT_VERSION,
        "browser_execution_enabled": False,
        "tools": {name: dict(spec) for name, spec in MAINTENANCE_TOOLS.items()},
    }
