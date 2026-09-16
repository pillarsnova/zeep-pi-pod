"""Durable, retryable delivery of finished Session summaries.

The Pod writes an outbox marker before contacting the account API.  Delivery
is idempotent by external Session ID, so network loss cannot discard a result
or make Session finalization depend on an external service.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException


class IngestOutbox:
    """Own atomic persistence and retry policy for account-ingest messages."""

    def __init__(
        self,
        *,
        directory: Path,
        schema_version: int,
        lock: Any,
        ingest_path: str,
        api_key: Callable[[], str | None],
        device_id: Callable[[], str | None],
        payload_builder: Callable[
            [dict[str, Any], list[dict[str, Any]]],
            dict[str, Any] | None,
        ],
        request: Callable[..., dict[str, Any]],
        offline_error: type[Exception],
        logger: Callable[..., None],
        inline_timeout: float,
    ) -> None:
        self.directory = directory
        self.schema_version = schema_version
        self.lock = lock
        self.ingest_path = ingest_path
        self.api_key = api_key
        self.device_id = device_id
        self.payload_builder = payload_builder
        self.request = request
        self.offline_error = offline_error
        self.log = logger
        self.inline_timeout = inline_timeout

    def path(self, session_id: str) -> Path:
        """Map a generated Session ID to one contained path component."""
        return self.directory / f"{Path(str(session_id)).name}.json"

    def write(self, entry: Mapping[str, Any]) -> None:
        """Atomically persist one pending upload."""
        session_id = entry["payload"]["externalSessionId"]
        path = self.path(session_id)
        with self.lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".json.tmp")
            with temporary.open("w", encoding="utf-8") as handle:
                json.dump(entry, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)

    def clear(self, session_id: str) -> bool:
        """Remove a delivered marker and report whether it existed."""
        with self.lock:
            path = self.path(session_id)
            existed = path.is_file()
            path.unlink(missing_ok=True)
            return existed

    def post(self, entry: dict[str, Any], *, timeout: float | None = None) -> bool:
        """Attempt delivery; return false only when another retry is useful."""
        payload = entry["payload"]
        session_id = payload["externalSessionId"]
        entry["attempts"] = int(entry.get("attempts") or 0) + 1
        try:
            body = self.request(
                "POST",
                self.ingest_path,
                json_body=payload,
                api_key=self.api_key(),
                timeout=timeout,
            )
        except self.offline_error as exc:
            entry["last_error"] = str(exc)
            self._deferred(entry, session_id, error=str(exc))
            return False
        except HTTPException as exc:
            return self._http_failure(entry, session_id, exc)

        remote = body.get("data") or {}
        self.log(
            "ingest",
            "uploaded",
            session_id=session_id,
            attempts=entry["attempts"],
            remote_id=remote.get("id"),
            remote_type=remote.get("type"),
            message=body.get("message"),
        )
        return True

    def _http_failure(
        self,
        entry: dict[str, Any],
        session_id: str,
        exc: HTTPException,
    ) -> bool:
        detail = str(getattr(exc, "detail", exc))
        entry["last_error"] = detail
        status = int(getattr(exc, "status_code", 0) or 0)
        if 400 <= status < 500 and status not in (401, 403, 408, 429):
            entry["parked"] = True
            self.log(
                "ingest",
                "rejected",
                session_id=session_id,
                status=status,
                error=detail,
            )
            return True
        self._deferred(entry, session_id, status=status, error=detail)
        return False

    def _deferred(self, entry: Mapping[str, Any], session_id: str, **detail) -> None:
        self.log(
            "ingest",
            "deferred",
            session_id=session_id,
            attempts=entry["attempts"],
            **detail,
        )

    def enqueue(
        self,
        record: dict[str, Any],
        report_samples: list[dict[str, Any]],
    ) -> None:
        """Best-effort upload a finished Session without failing finalization."""
        payload = self.payload_builder(record, report_samples)
        if payload is None:
            self.log(
                "ingest",
                "skipped",
                session_id=record.get("session_id"),
                configured=bool(self.api_key() and self.device_id()),
                zeep_account=bool(record.get("zeep_public_id")),
            )
            return
        entry = self._new_entry(payload)
        try:
            self.write(entry)
        except OSError as exc:
            self.log(
                "ingest",
                "outbox_write_failed",
                session_id=record.get("session_id"),
                error=str(exc),
            )
        try:
            done = self.post(entry, timeout=self.inline_timeout)
            if done and not entry.get("parked"):
                self.clear(payload["externalSessionId"])
                return
            self.write(entry)
        except Exception as exc:
            self.log(
                "ingest",
                "upload_failed",
                session_id=record.get("session_id"),
                error=str(exc),
            )

    def _new_entry(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "queued_at_utc": datetime.now(UTC).isoformat(),
            "attempts": 0,
            "last_error": None,
            "parked": False,
            "payload": payload,
        }

    def sweep(self) -> None:
        """Retry queued uploads oldest first; the caller serializes each sweep."""
        if not (self.api_key() and self.device_id()):
            return
        try:
            pending = sorted(
                self.directory.glob("*.json"),
                key=lambda item: item.stat().st_mtime,
            )
        except OSError:
            return
        for path in pending:
            entry = self._read_entry(path)
            if entry is None or entry.get("parked"):
                continue
            try:
                done = self.post(entry)
            except Exception as exc:
                self.log("ingest", "upload_failed", file=path.name, error=str(exc))
                continue
            try:
                if done and not entry.get("parked"):
                    self.clear(entry["payload"]["externalSessionId"])
                else:
                    self.write(entry)
            except OSError as exc:
                self.log(
                    "ingest",
                    "outbox_write_failed",
                    file=path.name,
                    error=str(exc),
                )
            if not done:
                break

    def _read_entry(self, path: Path) -> dict[str, Any] | None:
        try:
            with path.open("r", encoding="utf-8") as handle:
                entry = json.load(handle)
            if not isinstance(entry, dict) or not isinstance(
                entry.get("payload"), dict
            ):
                raise ValueError("outbox entry is not a pending upload")
            return entry
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self.log(
                "ingest",
                "outbox_entry_invalid",
                file=path.name,
                error=str(exc),
            )
            return None
