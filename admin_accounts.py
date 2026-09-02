#!/usr/bin/env python3
"""Manage additional local ZEEP administrators without storing plaintext.

The primary break-glass account remains in ``LOCAL_ADMIN_USERNAME`` and
``LOCAL_ADMIN_PASSWORD_HASH``. This tool manages only the optional hashed JSON
file consumed by :class:`access_control.AuthSessionManager`.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from access_control import hash_password


def default_accounts_file() -> Path:
    data_dir = Path(os.getenv("DATA_DIR", Path(__file__).resolve().parent / "data"))
    return Path(os.getenv("LOCAL_ADMIN_ACCOUNTS_FILE", data_dir / "local_admins.json"))


def load_accounts(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    accounts = payload.get("accounts") if isinstance(payload, dict) else None
    if not isinstance(accounts, list):
        raise ValueError("admin account file must contain an accounts list")
    return [dict(item) for item in accounts if isinstance(item, dict)]


def save_accounts(path: Path, accounts: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": 1, "accounts": accounts}
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def set_account(path: Path, username: str, password: str) -> None:
    name = username.strip()
    if not name:
        raise ValueError("username is required")
    accounts = load_accounts(path)
    replacement = {
        "username": name,
        "password_hash": hash_password(password),
        "enabled": True,
    }
    key = name.casefold()
    updated = False
    for index, account in enumerate(accounts):
        if str(account.get("username") or "").strip().casefold() == key:
            accounts[index] = replacement
            updated = True
            break
    if not updated:
        accounts.append(replacement)
    accounts.sort(key=lambda item: str(item.get("username") or "").casefold())
    save_accounts(path, accounts)


def remove_account(path: Path, username: str) -> bool:
    key = username.strip().casefold()
    accounts = load_accounts(path)
    retained = [
        item for item in accounts
        if str(item.get("username") or "").strip().casefold() != key
    ]
    if len(retained) == len(accounts):
        return False
    save_accounts(path, retained)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage hashed local ZEEP admins")
    parser.add_argument("--file", type=Path, default=default_accounts_file())
    subparsers = parser.add_subparsers(dest="command", required=True)
    set_parser = subparsers.add_parser("set", help="add or replace an account")
    set_parser.add_argument("username")
    remove_parser = subparsers.add_parser("remove", help="remove an account")
    remove_parser.add_argument("username")
    subparsers.add_parser("list", help="list usernames without hashes")
    args = parser.parse_args()

    if args.command == "set":
        password = getpass.getpass("Password: ")
        confirmation = getpass.getpass("Confirm password: ")
        if not password or password != confirmation:
            raise SystemExit("passwords do not match or are empty")
        set_account(args.file, args.username, password)
        print(f"updated local admin: {args.username}")
    elif args.command == "remove":
        removed = remove_account(args.file, args.username)
        print("removed" if removed else "account not found")
    else:
        for account in load_accounts(args.file):
            if account.get("enabled", True) is not False:
                print(str(account.get("username") or "").strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
