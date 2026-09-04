#!/usr/bin/env python3
"""Synchronize and audit the reviewed ZEEP evidence cache.

The JSON register is the authoritative source for evidence metadata. Downloaded
artifacts are review-only cache files: they never change runtime policy. Every
redirect must remain on HTTPS, every local path stays inside this library, and
an upstream integrity change is quarantined for review instead of retried away.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, BinaryIO
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
import xml.etree.ElementTree as ET


LIBRARY_ROOT = Path(__file__).resolve().parent
REGISTER_PATH = LIBRARY_ROOT / "source-register.json"
PROTOCOL_REGISTER_PATH = LIBRARY_ROOT / "protocol-register.json"
SOURCE_REGISTER_MD_PATH = LIBRARY_ROOT / "SOURCE_REGISTER.md"
MIN_PDF_BYTES = 10_000
MIN_XML_BYTES = 1_000


class IntegrityError(RuntimeError):
    """Downloaded evidence differs from the reviewed artifact."""


def ensure_https_url(url: str, *, field: str) -> str:
    """Return a validated HTTPS URL or reject the registry/redirect value."""

    parsed = urlparse(str(url))
    if parsed.scheme.lower() != "https" or not parsed.netloc:
        raise ValueError(f"{field} must be an absolute HTTPS URL: {url!r}")
    return str(url)


class HTTPSOnlyRedirectHandler(HTTPRedirectHandler):
    """Reject every redirect hop that attempts to leave HTTPS."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        ensure_https_url(newurl, field="redirect URL")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


HTTPS_OPENER = build_opener(HTTPSOnlyRedirectHandler())


def open_https(request: Request, *, timeout: int = 90) -> BinaryIO:
    """Open an HTTPS request and verify the final URL as defense in depth."""

    ensure_https_url(request.full_url, field="download_url")
    response = HTTPS_OPENER.open(request, timeout=timeout)
    try:
        ensure_https_url(response.geturl(), field="final response URL")
    except Exception:
        response.close()
        raise
    return response


def resolve_library_path(local_file: str) -> Path:
    """Resolve one registry path and guarantee containment in the library."""

    if not isinstance(local_file, str) or not local_file.strip():
        raise ValueError("local_file must be a non-empty relative path")
    candidate = (LIBRARY_ROOT / local_file).resolve()
    root = LIBRARY_ROOT.resolve()
    if candidate == root or root not in candidate.parents:
        raise ValueError(f"unsafe local_file outside evidence library: {local_file!r}")
    return candidate


def load_register() -> dict[str, Any]:
    with REGISTER_PATH.open("r", encoding="utf-8") as handle:
        register = json.load(handle)
    errors = validate_register(register)
    if errors:
        raise ValueError("invalid source-register.json: " + "; ".join(errors))
    return register


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_artifact(path: Path, expected_sha256: str, media_type: str) -> list[str]:
    """Validate type, minimum size and reviewed hash of a cached artifact."""

    errors: list[str] = []
    if not path.is_file():
        return ["missing"]
    size = path.stat().st_size
    if media_type == "application/pdf":
        if size < MIN_PDF_BYTES:
            errors.append(f"too small ({size} bytes)")
        with path.open("rb") as handle:
            if handle.read(5) != b"%PDF-":
                errors.append("not a PDF signature")
    elif media_type in {"application/xml", "text/xml"}:
        if size < MIN_XML_BYTES:
            errors.append(f"too small ({size} bytes)")
        try:
            root_tag = ET.parse(path).getroot().tag.rsplit("}", 1)[-1]
            if root_tag not in {"pmc-articleset", "article"}:
                errors.append(f"unexpected XML root ({root_tag})")
        except ET.ParseError as error:
            errors.append(f"invalid XML ({error})")
    else:
        errors.append(f"unsupported media_type ({media_type})")
    actual = sha256_file(path)
    if actual != expected_sha256:
        errors.append(f"SHA-256 mismatch (expected {expected_sha256}, got {actual})")
    return errors


def validate_pdf(path: Path, expected_sha256: str) -> list[str]:
    """Backward-compatible wrapper retained for callers and focused tests."""

    return validate_artifact(path, expected_sha256, "application/pdf")


def validate_register(register: dict[str, Any]) -> list[str]:
    """Fast stdlib validation; full JSON Schema validation also runs in CI."""

    errors: list[str] = []
    sources = register.get("sources")
    if not isinstance(sources, list):
        return ["sources must be a list"]
    if not register.get("authority", {}).get("authoritative"):
        errors.append("authority.authoritative must be true")
    seen: set[str] = set()
    for index, source in enumerate(sources):
        label = str(source.get("id") or f"sources[{index}]")
        if label in seen:
            errors.append(f"duplicate source id {label}")
        seen.add(label)
        for key in (
            "id", "category", "title", "source_url", "access",
            "use_in_zeep", "limitations", "provenance",
        ):
            if not source.get(key):
                errors.append(f"{label}.{key} is required")
        try:
            ensure_https_url(source.get("source_url", ""), field=f"{label}.source_url")
        except ValueError as error:
            errors.append(str(error))
        provenance = source.get("provenance") or {}
        for key in ("checked_on", "checked_by_role", "method"):
            if not provenance.get(key):
                errors.append(f"{label}.provenance.{key} is required")
        if source.get("access") == "downloadable":
            for key in ("download_url", "local_file", "sha256"):
                if not source.get(key):
                    errors.append(f"{label}.{key} is required for downloadable evidence")
            try:
                ensure_https_url(source.get("download_url", ""), field=f"{label}.download_url")
                resolve_library_path(source.get("local_file", ""))
            except ValueError as error:
                errors.append(str(error))
            checksum = str(source.get("sha256") or "")
            if len(checksum) != 64 or any(char not in "0123456789abcdef" for char in checksum):
                errors.append(f"{label}.sha256 must be 64 lowercase hexadecimal characters")
    return errors


def validate_markdown_consistency(register: dict[str, Any], markdown: str) -> list[str]:
    """Ensure the human register exposes every authoritative ID and URL."""

    errors: list[str] = []
    if "source-register.json" not in markdown or "authoritative" not in markdown.lower():
        errors.append("SOURCE_REGISTER.md must declare source-register.json authoritative")
    canonical = json.dumps(
        register, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    expected_lock = f"Canonical JSON SHA-256: `{hashlib.sha256(canonical).hexdigest()}`"
    if expected_lock not in markdown:
        errors.append("SOURCE_REGISTER.md canonical JSON SHA-256 lock is stale")
    for source in register["sources"]:
        row_marker = f"| {source['id']} |"
        if markdown.count(row_marker) != 1:
            errors.append(f"{source['id']} must appear in exactly one Markdown table row")
        if source["source_url"] not in markdown:
            errors.append(f"{source['id']} source_url differs between JSON and Markdown")
    return errors


def downloadable_sources(register: dict[str, Any], selected: set[str]) -> list[dict[str, Any]]:
    records = []
    for source in register["sources"]:
        if selected and source["id"] not in selected:
            continue
        if source.get("access") == "downloadable":
            records.append(source)
    return records


def _rejected_path(destination: Path) -> Path:
    return destination.with_name(destination.name + ".rejected")


def download_one(source: dict[str, Any], force: bool) -> None:
    destination = resolve_library_path(source["local_file"])
    media_type = source.get("media_type", "application/pdf")
    if destination.exists() and not force and not validate_artifact(
        destination, source["sha256"], media_type
    ):
        print(f"OK    {source['id']} {source['local_file']}")
        return

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".part")
    rejected = _rejected_path(destination)
    request = Request(
        ensure_https_url(source["download_url"], field=f"{source['id']}.download_url"),
        headers={"User-Agent": "ZEEP-Evidence-Library/1.1 (+https://zeep.world)"},
    )
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            with open_https(request, timeout=90) as response, temporary.open("wb") as output:
                while block := response.read(1024 * 1024):
                    output.write(block)
            errors = validate_artifact(temporary, source["sha256"], media_type)
            if errors:
                os.replace(temporary, rejected)
                raise IntegrityError(
                    f"{source['id']} rejected without retry: {'; '.join(errors)}; "
                    f"review artifact at {rejected}"
                )
            os.replace(temporary, destination)
            rejected.unlink(missing_ok=True)
            print(f"FETCH {source['id']} {source['local_file']}")
            return
        except IntegrityError:
            raise
        except (HTTPError, URLError, TimeoutError, OSError) as error:
            last_error = error
            temporary.unlink(missing_ok=True)
            if attempt < 3:
                time.sleep(2 ** (attempt - 1))
    raise RuntimeError(f"{source['id']} download failed after 3 transport attempts: {last_error}")


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
        try:
            path = resolve_library_path(source["local_file"])
            errors = validate_artifact(
                path, source["sha256"], source.get("media_type", "application/pdf")
            )
        except ValueError as error:
            errors = [str(error)]
        if errors:
            failures += 1
            print(f"FAIL  {source['id']} {', '.join(errors)}")
        else:
            print(f"OK    {source['id']} {source['local_file']}")
    return 1 if failures else 0


def command_status(register: dict[str, Any], selected: set[str]) -> int:
    failures = 0
    for source in register["sources"]:
        if selected and source["id"] not in selected:
            continue
        if source.get("local_file"):
            try:
                state = "cached" if resolve_library_path(source["local_file"]).is_file() else "not-downloaded"
            except ValueError:
                state = "unsafe-path"
                failures += 1
        else:
            state = source["access"]
        print(f"{source['id']:<8} {state:<20} {source['title']}")
    return 1 if failures else 0


def command_check(register: dict[str, Any]) -> int:
    errors = validate_register(register)
    markdown = SOURCE_REGISTER_MD_PATH.read_text(encoding="utf-8")
    errors.extend(validate_markdown_consistency(register, markdown))
    try:
        protocol_register = json.loads(PROTOCOL_REGISTER_PATH.read_text(encoding="utf-8"))
        if not protocol_register.get("authority", {}).get("authoritative"):
            errors.append("protocol-register.json must declare itself authoritative")
        if not protocol_register.get("protocols"):
            errors.append("protocol-register.json must contain protocols")
    except (OSError, json.JSONDecodeError) as error:
        errors.append(f"invalid protocol-register.json: {error}")
    if errors:
        for error in errors:
            print(f"FAIL  {error}")
        return 1
    print(f"OK    source registry: {len(register['sources'])} records")
    print("OK    Markdown/JSON source register consistency")
    print("OK    validation protocol register")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("sync", "verify", "status", "check"))
    parser.add_argument("--id", action="append", default=[], help="limit operation to a source ID")
    parser.add_argument("--force", action="store_true", help="redownload valid cached files during sync")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        register = load_register()
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"ERROR {error}", file=sys.stderr)
        return 2
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
    if args.command == "status":
        return command_status(register, selected)
    return command_check(register)


if __name__ == "__main__":
    raise SystemExit(main())
