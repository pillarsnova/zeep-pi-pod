"""Pod occupancy leases used to prevent duplicate login across many pods.

Each Pi still enforces one occupant locally.  For a multi-pod deployment all
pods must point ``OCCUPANCY_COORDINATOR_URL`` at the same coordinator service.
The coordinator grants a short lease per immutable ZEEP subject and per pod.
New logins fail closed if the coordinator is unavailable; an existing sleeper
is never logged out merely because the network disappears.
"""
from __future__ import annotations

import os
import secrets
import socket
import sqlite3
import threading
import time
from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional, Protocol

try:
    import httpx
except ImportError:  # local-only unit tests can still exercise the SQLite lease store
    httpx = None
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field


def pod_id_from_env() -> str:
    raw = os.getenv("POD_ID", socket.gethostname()).strip().lower()
    clean = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in raw)
    return clean.strip("-") or "pod-unknown"


@dataclass(frozen=True)
class OccupancyLease:
    lease_id: str
    subject: str
    pod_id: str
    pod_session_id: str
    username: str
    expires_at: float


class OccupancyConflict(RuntimeError):
    def __init__(self, reason: str, pod_id: Optional[str] = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.pod_id = pod_id


class CoordinatorUnavailable(RuntimeError):
    pass


class OccupancyClient(Protocol):
    mode: str

    def acquire(
        self, *, subject: str, pod_id: str, pod_session_id: str, username: str
    ) -> OccupancyLease: ...

    def renew(self, lease: OccupancyLease) -> OccupancyLease: ...

    def release(self, lease: OccupancyLease) -> None: ...

    def health(self) -> dict[str, Any]: ...


class OccupancyStore:
    """Atomic SQLite lease registry; deploy one shared instance for many pods."""

    def __init__(self, data_dir: Path, ttl_seconds: int = 45) -> None:
        self.path = data_dir / "occupancy.db"
        self.ttl_seconds = max(15, ttl_seconds)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def _initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS occupancy_leases (
                    lease_id TEXT PRIMARY KEY,
                    subject TEXT NOT NULL UNIQUE,
                    pod_id TEXT NOT NULL UNIQUE,
                    pod_session_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    acquired_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    expires_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_occupancy_expiry
                    ON occupancy_leases(expires_at);
                """
            )

    @staticmethod
    def _row(row: sqlite3.Row) -> OccupancyLease:
        return OccupancyLease(
            lease_id=row["lease_id"],
            subject=row["subject"],
            pod_id=row["pod_id"],
            pod_session_id=row["pod_session_id"],
            username=row["username"],
            expires_at=float(row["expires_at"]),
        )

    def acquire(
        self, *, subject: str, pod_id: str, pod_session_id: str, username: str
    ) -> OccupancyLease:
        now = time.time()
        expires_at = now + self.ttl_seconds
        with self._lock, closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute("DELETE FROM occupancy_leases WHERE expires_at<=?", (now,))
                same_subject = connection.execute(
                    "SELECT * FROM occupancy_leases WHERE subject=?", (subject,)
                ).fetchone()
                if same_subject:
                    # Renew is idempotent only for the exact physical session.
                    if (
                        same_subject["pod_id"] == pod_id
                        and same_subject["pod_session_id"] == pod_session_id
                    ):
                        connection.execute(
                            "UPDATE occupancy_leases SET updated_at=?,expires_at=? WHERE lease_id=?",
                            (now, expires_at, same_subject["lease_id"]),
                        )
                        connection.commit()
                        return OccupancyLease(
                            lease_id=same_subject["lease_id"],
                            subject=subject,
                            pod_id=pod_id,
                            pod_session_id=pod_session_id,
                            username=username,
                            expires_at=expires_at,
                        )
                    raise OccupancyConflict("account_already_in_use", same_subject["pod_id"])
                same_pod = connection.execute(
                    "SELECT * FROM occupancy_leases WHERE pod_id=?", (pod_id,)
                ).fetchone()
                if same_pod:
                    raise OccupancyConflict("pod_already_occupied", pod_id)
                lease = OccupancyLease(
                    lease_id=f"lease-{secrets.token_hex(16)}",
                    subject=subject,
                    pod_id=pod_id,
                    pod_session_id=pod_session_id,
                    username=username,
                    expires_at=expires_at,
                )
                connection.execute(
                    """INSERT INTO occupancy_leases
                       (lease_id,subject,pod_id,pod_session_id,username,
                        acquired_at,updated_at,expires_at)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (
                        lease.lease_id,
                        lease.subject,
                        lease.pod_id,
                        lease.pod_session_id,
                        lease.username,
                        now,
                        now,
                        expires_at,
                    ),
                )
                connection.commit()
                return lease
            except Exception:
                connection.rollback()
                raise

    def renew(self, lease: OccupancyLease) -> OccupancyLease:
        now = time.time()
        expires_at = now + self.ttl_seconds
        with self._lock, closing(self._connect()) as connection:
            result = connection.execute(
                """UPDATE occupancy_leases SET updated_at=?,expires_at=?
                   WHERE lease_id=? AND subject=? AND pod_id=? AND pod_session_id=?""",
                (
                    now,
                    expires_at,
                    lease.lease_id,
                    lease.subject,
                    lease.pod_id,
                    lease.pod_session_id,
                ),
            )
            if result.rowcount != 1:
                raise OccupancyConflict("lease_lost", lease.pod_id)
        return OccupancyLease(**{**asdict(lease), "expires_at": expires_at})

    def release(self, lease: OccupancyLease) -> None:
        with self._lock, closing(self._connect()) as connection:
            connection.execute(
                "DELETE FROM occupancy_leases WHERE lease_id=? AND pod_session_id=?",
                (lease.lease_id, lease.pod_session_id),
            )

    def list_active(self) -> list[dict[str, Any]]:
        now = time.time()
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM occupancy_leases WHERE expires_at>? ORDER BY pod_id", (now,)
            ).fetchall()
        return [dict(row) for row in rows]


class LocalOccupancyClient:
    mode = "local"

    def __init__(self, store: OccupancyStore) -> None:
        self.store = store

    def acquire(self, **kwargs: Any) -> OccupancyLease:
        return self.store.acquire(**kwargs)

    def renew(self, lease: OccupancyLease) -> OccupancyLease:
        return self.store.renew(lease)

    def release(self, lease: OccupancyLease) -> None:
        self.store.release(lease)

    def health(self) -> dict[str, Any]:
        return {"mode": self.mode, "available": True, "multi_pod": False}


class RemoteOccupancyClient:
    mode = "remote"

    def __init__(self, base_url: str, token: str, ttl_seconds: int = 45) -> None:
        if httpx is None:
            raise RuntimeError("httpx is required for a remote occupancy coordinator")
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.ttl_seconds = ttl_seconds
        self.timeout = float(os.getenv("OCCUPANCY_COORDINATOR_TIMEOUT", "4"))
        self._last_ok_at: Optional[float] = None
        self._last_error: Optional[str] = None

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            response = httpx.post(
                f"{self.base_url}{path}",
                json=body,
                headers={"X-Pod-Coordinator-Token": self.token},
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            self._last_error = type(exc).__name__
            raise CoordinatorUnavailable("occupancy coordinator unavailable") from exc
        if response.status_code == 409:
            detail = response.json().get("detail") or {}
            raise OccupancyConflict(detail.get("code", "occupancy_conflict"), detail.get("pod_id"))
        if response.status_code >= 400:
            self._last_error = f"HTTP {response.status_code}"
            raise CoordinatorUnavailable("occupancy coordinator rejected request")
        self._last_ok_at = time.time()
        self._last_error = None
        return response.json()

    @staticmethod
    def _lease(data: dict[str, Any]) -> OccupancyLease:
        return OccupancyLease(**data["lease"])

    def acquire(self, **kwargs: Any) -> OccupancyLease:
        return self._lease(self._post("/api/internal/occupancy/acquire", kwargs))

    def renew(self, lease: OccupancyLease) -> OccupancyLease:
        return self._lease(
            self._post("/api/internal/occupancy/renew", {"lease": asdict(lease)})
        )

    def release(self, lease: OccupancyLease) -> None:
        self._post("/api/internal/occupancy/release", {"lease": asdict(lease)})

    def health(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "available": self._last_error is None,
            "multi_pod": True,
            "last_ok_at": self._last_ok_at,
            "last_error": self._last_error,
        }


class AcquireCommand(BaseModel):
    subject: str = Field(min_length=3, max_length=200)
    pod_id: str = Field(min_length=1, max_length=80)
    pod_session_id: str = Field(min_length=3, max_length=120)
    username: str = Field(min_length=1, max_length=120)


class LeaseCommand(BaseModel):
    lease: dict[str, Any]


def create_occupancy_router(store: OccupancyStore, shared_token: str) -> APIRouter:
    """Internal coordinator API; expose only on a trusted management network."""
    router = APIRouter(prefix="/api/internal/occupancy", tags=["occupancy-internal"])

    def authorize(x_pod_coordinator_token: Optional[str] = Header(default=None)) -> None:
        if not shared_token:
            raise HTTPException(503, "occupancy coordinator server is disabled")
        if not secrets.compare_digest(x_pod_coordinator_token or "", shared_token):
            raise HTTPException(401, "invalid coordinator token")

    @router.post("/acquire")
    def acquire(
        cmd: AcquireCommand,
        x_pod_coordinator_token: Optional[str] = Header(default=None),
    ):
        authorize(x_pod_coordinator_token)
        try:
            payload = cmd.model_dump() if hasattr(cmd, "model_dump") else cmd.dict()
            lease = store.acquire(**payload)
        except OccupancyConflict as exc:
            raise HTTPException(
                409, {"code": exc.reason, "pod_id": exc.pod_id}
            ) from exc
        return {"lease": asdict(lease)}

    @router.post("/renew")
    def renew(
        cmd: LeaseCommand,
        x_pod_coordinator_token: Optional[str] = Header(default=None),
    ):
        authorize(x_pod_coordinator_token)
        try:
            lease = store.renew(OccupancyLease(**cmd.lease))
        except (TypeError, OccupancyConflict) as exc:
            raise HTTPException(409, {"code": "lease_lost"}) from exc
        return {"lease": asdict(lease)}

    @router.post("/release")
    def release(
        cmd: LeaseCommand,
        x_pod_coordinator_token: Optional[str] = Header(default=None),
    ):
        authorize(x_pod_coordinator_token)
        try:
            store.release(OccupancyLease(**cmd.lease))
        except TypeError as exc:
            raise HTTPException(422, "invalid lease") from exc
        return {"ok": True}

    return router


def build_occupancy_client(store: OccupancyStore) -> OccupancyClient:
    url = os.getenv("OCCUPANCY_COORDINATOR_URL", "").strip()
    token = os.getenv("OCCUPANCY_COORDINATOR_TOKEN", "").strip()
    if url:
        if not token:
            raise RuntimeError(
                "OCCUPANCY_COORDINATOR_TOKEN is required when coordinator URL is set"
            )
        return RemoteOccupancyClient(url, token, store.ttl_seconds)
    return LocalOccupancyClient(store)
