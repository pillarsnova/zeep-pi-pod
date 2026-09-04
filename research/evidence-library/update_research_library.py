#!/usr/bin/env python3
"""Synchronize the reviewed ZEEP evidence cache without changing runtime policy.

The source register is deliberately locked with SHA-256 hashes.  An upstream
change must be reviewed and committed instead of silently becoming evidence
used by the project.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


LIBRARY_ROOT = Path(__file__).resolve().parent
REGISTER_PATH = LIBRARY_ROOT / "source-register.json"
MIN_PDF_BYTES = 10_000


def load_register() -> dict[str, Any]:
    with REGISTER_PATH.open("r", encoding="utf-8") as handle:
        register = json.load(handle)
    if not isinstance(register.get("sources"), list):
        raise ValueError("source-register.json must contain a sources list")
    return register


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_pdf(path: Path, expected_sha256: str) -> list[str]:
    errors: list[str] = []
    if not path.is_file():
        return ["missing"]
    size = path.stat().st_size
    if size < MIN_PDF_BYTES:
        errors.append(f"too small ({size} bytes)")
    with path.open("rb") as handle:
        if handle.read(5) != b"%PDF-":
            errors.append("not a PDF signature")
    actual = sha256_file(path)
    if actual != expected_sha256:
        errors.append(f"SHA-256 mismatch ({actual})")
    return errors


def downloadable_sources(register: dict[str, Any], selected: set[str]) -> list[dict[str, Any]]:
    records = []
    for source in register["sources"]:
        if selected and source["id"] not in selected:
            continue
        if source.get("access") == "downloadable":
            records.append(source)
    return records


def download_one(source: dict[str, Any], force: bool) -> None:
    destination = (LIBRARY_ROOT / source["local_file"]).resolve()
    if LIBRARY_ROOT not in destination.parents:
        raise ValueError(f"unsafe local_file for {source['id']}")
    if destination.exists() and not force and not validate_pdf(destination, source["sha256"]):
        print(f"OK    {source['id']} {source['local_file']}")
        return

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".part")
    request = Request(
        source["download_url"],
        headers={"User-Agent": "ZEEP-Evidence-Library/1.0 (+https://zeep.world)"},
    )
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            with urlopen(request, timeout=90) as response, temporary.open("wb") as output:
                while block := response.read(1024 * 1024):
                    output.write(block)
            errors = validate_pdf(temporary, source["sha256"])
            if errors:
                raise ValueError("; ".join(errors))
            os.replace(temporary, destination)
            print(f"FETCH {source['id']} {source['local_file']}")
            return
        except (HTTPError, URLError, TimeoutError, ValueError, OSError) as error:
            last_error = error
            temporary.unlink(missing_ok=True)
            if attempt < 3:
                time.sleep(2 ** (attempt - 1))
    raise RuntimeError(f"{source['id']} download failed: {last_error}")


def command_sync(register: dict[str, Any], selected: set[str], force: bool) -> int:
    failures = 0
    for source in downloadable_sources(register, selected):
        try:
            download_one(source, force)
        except Exception as error:  # Each source is reported; the batch continues.
            failures += 1
            print(f"ERROR {error}", file=sys.stderr)
    return 1 if failures else 0


def command_verify(register: dict[str, Any], selected: set[str]) -> int:
    failures = 0
    for source in downloadable_sources(register, selected):
        path = LIBRARY_ROOT / source["local_file"]
        errors = validate_pdf(path, source["sha256"])
        if errors:
            failures += 1
            print(f"FAIL  {source['id']} {', '.join(errors)}")
        else:
            print(f"OK    {source['id']} {source['local_file']}")
    return 1 if failures else 0


def command_status(register: dict[str, Any], selected: set[str]) -> int:
    for source in register["sources"]:
        if selected and source["id"] not in selected:
            continue
        if source.get("local_file"):
            state = "cached" if (LIBRARY_ROOT / source["local_file"]).is_file() else "not-downloaded"
        else:
            state = source["access"]
        print(f"{source['id']:<8} {state:<20} {source['title']}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("sync", "verify", "status"))
    parser.add_argument("--id", action="append", default=[], help="limit operation to a source ID")
    parser.add_argument("--force", action="store_true", help="redownload valid cached files during sync")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    register = load_register()
    selected = set(args.id)
    known = {source["id"] for source in register["sources"]}
    unknown = selected - known
    if unknown:
        print(f"Unknown source ID(s): {', '.join(sorted(unknown))}", file=sys.stderr)
        return 2
    if args.command == "sync":
        return command_sync(register, selected, args.force)
    if args.command == "verify":
        return command_verify(register, selected)
    return command_status(register, selected)


if __name__ == "__main__":
    raise SystemExit(main())
