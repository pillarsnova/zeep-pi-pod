#!/usr/bin/env python3
"""Run the smallest useful ZEEP validation set for the current change.

The default ``changed`` mode maps Git changes to focused regression domains.
Use ``full`` only for cross-cutting changes, uncertain results, release
candidates, or when CI is unavailable. Production data and hardware are never
used by this runner.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DOMAIN_PACKAGES = (
    "acoustics",
    "adaptive",
    "api",
    "common",
    "hardware",
    "identity",
    "operations",
    "presentation",
    "safety",
    "sensors",
    "sessions",
)

PROFILE_TESTS: dict[str, tuple[str, ...]] = {
    "core": (
        "test_modular_architecture.py",
        "test_sensor_services.py",
        "test_session_lifecycle.py",
        "test_rbac_api.py",
    ),
    "ui": (
        "test_ui_composer.py",
        "test_product_language.py",
    ),
    "sensor": (
        "test_sensor_contract.py",
        "test_sensor_services.py",
        "test_sensorhub1_reader.py",
        "test_api_state_projection.py",
    ),
    "control": (
        "test_control_protocol.py",
        "test_aircon_reference.py",
        "test_gpio_lifecycle.py",
        "test_audio_api.py",
        "test_audio_defaults.py",
        "test_audio_lifecycle.py",
    ),
    "sleep": (
        "test_sleep_signal_features.py",
        "test_sleep_baseline_policy.py",
        "test_sleep_system_consistency.py",
        "test_sleep_restart_context.py",
    ),
    "score": (
        "test_sleep_session_report.py",
        "test_recovery_policy_guardrails.py",
        "test_restore_summary.py",
        "test_wellness_score_balance.py",
    ),
    "session": (
        "test_session_lifecycle.py",
        "test_recording_start.py",
        "test_session_restart.py",
        "test_finalization_summary.py",
        "test_session_finalization_commit.py",
        "test_session_cadence.py",
        "test_occupancy_lifecycle.py",
    ),
    "auth": (
        "test_rbac_api.py",
        "test_auth_session_lifecycle.py",
        "test_access_and_occupancy.py",
        "test_qr_login_api.py",
    ),
    "history": (
        "test_historical_replay_runtime.py",
        "test_historical_replay_storage.py",
        "test_history_sleep_timeline.py",
        "test_history_report_projection.py",
    ),
    "data": (
        "test_database_timeline.py",
        "test_backup.py",
        "test_maintenance_registry.py",
    ),
    "sync": (
        "test_pod_data_sync.py",
        "test_workstation_approval.py",
        "test_pod_snapshot_export_limits.py",
    ),
    "evidence": (
        "test_research_evidence_library.py",
        "test_documentation_alignment.py",
    ),
}

FULL_TRIGGER_FILES = {
    "requirements-dev.txt",
    "testing_support.py",
    ".github/workflows/python-quality.yml",
}

PROFILE_PATTERNS: dict[str, tuple[str, ...]] = {
    "ui": ("static/", "ui_composer.py"),
    "sensor": (
        "sensor",
        "calibration",
        "firmware/sensorhub1",
        "smart_response",
    ),
    "control": ("control", "aircon", "gpio", "audio", "brainwave", "music"),
    "sleep": (
        "sleep_stage",
        "sleep_signal",
        "sleep_system_policy",
        "baseline",
        "personal.py",
    ),
    "score": (
        "sleep_session_report",
        "recovery",
        "restore",
        "score",
        "result_contract",
    ),
    "session": ("session", "occupancy", "finalization"),
    "auth": ("auth", "rbac", "qr_login", "identity", "profile_completion"),
    "history": ("historical", "history", "reclassify", "rescore", "replay"),
    "data": ("database", "backup", "maintenance", "cleanup", "trim_session"),
    "sync": ("pod_data_sync", "snapshot_export"),
}


def git_lines(*args: str) -> list[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def changed_files(base: str) -> list[str]:
    paths = set(git_lines("diff", "--name-only", "--diff-filter=ACMR", "HEAD"))
    paths.update(
        git_lines(
            "diff",
            "--name-only",
            "--diff-filter=ACMR",
            f"{base}...HEAD",
        )
    )
    paths.update(git_lines("ls-files", "--others", "--exclude-standard"))
    return sorted(paths)


def classify(path: str) -> set[str]:
    name = Path(path).name
    lowered = path.lower()
    profiles: set[str] = set()

    if path in FULL_TRIGGER_FILES or path == "quality_gate.py":
        return {"full"}
    if lowered.startswith("firmware/sensorhub1-esp32s3/test/"):
        return {"sensor"}
    if name.startswith("test_") and name.endswith(".py"):
        return {f"test:{path}"}
    if lowered.startswith("docs/") or name in {"README.md", "CLAUDE.md"}:
        return set()
    for profile, patterns in PROFILE_PATTERNS.items():
        if any(pattern in lowered for pattern in patterns):
            profiles.add(profile)
    if lowered.startswith("research/evidence-library/"):
        profiles.add("evidence")
    if name == "app.py":
        profiles.add("core")
    if path.endswith(".py") and not profiles:
        candidate = ROOT / f"test_{Path(path).stem}.py"
        profiles.add(f"test:{candidate.name}" if candidate.exists() else "core")
    return profiles


def test_plan(profiles: set[str]) -> list[str]:
    tests: list[str] = []
    for profile in PROFILE_TESTS:
        if profile in profiles:
            tests.extend(PROFILE_TESTS[profile])
    tests.extend(
        profile.removeprefix("test:")
        for profile in sorted(profiles)
        if profile.startswith("test:")
    )
    return list(dict.fromkeys(tests))


def run(command: list[str], *, dry_run: bool) -> None:
    print("+", " ".join(command), flush=True)
    if not dry_run:
        subprocess.run(command, cwd=ROOT, check=True)


def run_full(*, dry_run: bool) -> None:
    python = sys.executable
    run([python, "-m", "unittest", "discover", "-q"], dry_run=dry_run)
    run([python, "ui_composer.py", "check"], dry_run=dry_run)
    run([python, "-m", "ruff", "check", *DOMAIN_PACKAGES], dry_run=dry_run)
    run(
        [python, "-m", "ruff", "format", "--check", *DOMAIN_PACKAGES],
        dry_run=dry_run,
    )
    root_python = sorted(
        path.name for path in ROOT.glob("*.py") if not path.name.startswith("test_")
    )
    run([python, "-m", "py_compile", *root_python], dry_run=dry_run)
    run(
        [python, "research/evidence-library/update_research_library.py", "check"],
        dry_run=dry_run,
    )
    run(["git", "diff", "--check"], dry_run=dry_run)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "scopes",
        nargs="*",
        default=["changed"],
        help="changed (default), full, or one/more named domains",
    )
    parser.add_argument("--base", default="origin/develop")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--list", action="store_true", dest="list_profiles")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.list_profiles:
        print("changed\nfull\n" + "\n".join(PROFILE_TESTS))
        return 0

    scopes = set(args.scopes)
    invalid = scopes - set(PROFILE_TESTS) - {"changed", "full"}
    if invalid:
        raise SystemExit(f"Unknown scope: {', '.join(sorted(invalid))}")

    files: list[str] = []
    profiles = scopes - {"changed", "full"}
    if "changed" in scopes:
        files = changed_files(args.base)
        for path in files:
            profiles.update(classify(path))
        print(f"Changed files: {len(files)}")
        for path in files:
            print(f"  - {path}")

    if "full" in scopes or "full" in profiles:
        reason = (
            "explicit request" if "full" in scopes else "test infrastructure changed"
        )
        print(f"Gate: full ({reason})")
        started = time.monotonic()
        run_full(dry_run=args.dry_run)
        print(f"Completed in {time.monotonic() - started:.1f}s")
        return 0

    if not profiles:
        print("Gate: none — no relevant change detected")
        return 0

    print(f"Gate: focused ({', '.join(sorted(profiles))})")
    tests = test_plan(profiles)
    started = time.monotonic()
    if tests:
        run(
            [sys.executable, "-m", "unittest", "-q", *tests],
            dry_run=args.dry_run,
        )
    if "ui" in profiles:
        run([sys.executable, "ui_composer.py", "check"], dry_run=args.dry_run)
    if "evidence" in profiles:
        run(
            [
                sys.executable,
                "research/evidence-library/update_research_library.py",
                "check",
            ],
            dry_run=args.dry_run,
        )
    changed_python = [
        path for path in files if path.endswith(".py") and (ROOT / path).is_file()
    ]
    if changed_python:
        run(
            [sys.executable, "-m", "ruff", "check", *changed_python],
            dry_run=args.dry_run,
        )
        run([sys.executable, "-m", "py_compile", *changed_python], dry_run=args.dry_run)
    run(["git", "diff", "--check"], dry_run=args.dry_run)
    print(f"Completed in {time.monotonic() - started:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
