"""Approve or verify a workstation before it stores ZEEP Pod snapshots."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from operations.developer_workstation import approve_development_mac
from operations.workstation_approval import (
    WorkstationApprovalError,
    approve_workstation,
    require_workstation_approval,
)


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(
        description="OS-admin approval for an encrypted ZEEP team workstation.",
    )
    action = command.add_mutually_exclusive_group(required=True)
    action.add_argument("--approved-by", help="Team member approving this workstation.")
    action.add_argument(
        "--check", action="store_true", help="Verify existing approval."
    )
    command.add_argument(
        "--developer-mac-exception",
        action="store_true",
        help="Explicit owner approval: waive encryption only on this development Mac/destination.",
    )
    command.add_argument(
        "--destination",
        type=Path,
        default=Path("private-data/pod-sync"),
        help="Snapshot destination whose volume must be encrypted.",
    )
    return command


def main() -> int:
    args = parser().parse_args()
    if args.developer_mac_exception and not args.approved_by:
        parser().error("--developer-mac-exception requires --approved-by")
    try:
        result = (
            require_workstation_approval(args.destination)
            if args.check
            else (
                approve_development_mac(args.approved_by, args.destination)
                if args.developer_mac_exception
                else approve_workstation(args.approved_by, destination=args.destination)
            )
        )
    except WorkstationApprovalError as exc:
        print(f"[workstation-approval] failed: {exc}")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
