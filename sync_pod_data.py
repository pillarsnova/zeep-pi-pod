"""CLI for a verified Pod-to-workstation data snapshot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from zeep_pod.operations.pod_data_sync import (
    DEFAULT_DESTINATION,
    DEFAULT_HOSTS,
    DEFAULT_MAX_AGE_HOURS,
    DEFAULT_POD_ID,
    DEFAULT_REMOTE_ROOT,
    DEFAULT_RETENTION,
    PodDataSyncError,
    latest_verified_snapshot,
    sync_pod_data,
)
from zeep_pod.operations.workstation_approval import (
    WorkstationApprovalError,
    require_workstation_approval,
)


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(
        description="Sync a verified, read-only ZEEP Pod data snapshot.",
    )
    command.add_argument(
        "--host",
        action="append",
        dest="hosts",
        help="SSH host; repeat to add fallback hosts.",
    )
    command.add_argument("--remote-root", default=DEFAULT_REMOTE_ROOT)
    command.add_argument("--pod-id", default=DEFAULT_POD_ID)
    command.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION)
    command.add_argument("--retention", type=int, default=DEFAULT_RETENTION)
    command.add_argument("--connect-timeout", type=int, default=8)
    command.add_argument("--command-timeout", type=int, default=300)
    action = command.add_mutually_exclusive_group()
    action.add_argument(
        "--check-latest",
        action="store_true",
        help="Verify a local snapshot without contacting the Pod.",
    )
    action.add_argument(
        "--check-approval",
        action="store_true",
        help="Verify workstation approval and disk encryption only.",
    )
    command.add_argument(
        "--max-age-hours",
        type=float,
        default=DEFAULT_MAX_AGE_HOURS,
    )
    return command


def main() -> int:
    args = parser().parse_args()
    try:
        if args.check_approval:
            result = require_workstation_approval(args.destination)
        elif args.check_latest:
            result = latest_verified_snapshot(
                args.destination,
                expected_pod_id=args.pod_id,
                max_age_hours=args.max_age_hours,
            )
        else:
            result = sync_pod_data(
                args.hosts or DEFAULT_HOSTS,
                remote_root=args.remote_root,
                destination=args.destination,
                expected_pod_id=args.pod_id,
                retention_count=args.retention,
                connect_timeout_seconds=args.connect_timeout,
                command_timeout_seconds=args.command_timeout,
            )
    except (PodDataSyncError, WorkstationApprovalError) as exc:
        print(f"[pod-sync] failed: {exc}")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
