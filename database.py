"""SQLite storage and the application's single background writer thread."""
from __future__ import annotations

import json
import queue
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional


@dataclass(frozen=True)
class WriteJob:
    database: str
    operation: str
    payload: Any


class DatabaseManager:
    """Own both databases and serialize all mutations through one thread."""

    def __init__(self, data_dir: Path, queue_size: int = 10000) -> None:
        self.data_dir = data_dir
        self.sessions_path = data_dir / "sessions.db"
        self.bcg_path = data_dir / "bcg.db"
        self._queue: queue.Queue[Optional[WriteJob]] = queue.Queue(maxsize=queue_size)
        self._thread: Optional[threading.Thread] = None
        self._stopping = threading.Event()
        self._error_lock = threading.Lock()
        self._last_error: Optional[str] = None
        self._written = 0

    @staticmethod
    def _connect(path: Path, *, readonly: bool = False) -> sqlite3.Connection:
        if readonly:
            connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
        else:
            connection = sqlite3.connect(path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        if not readonly:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
        return connection

    def initialize(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        base = Path(__file__).resolve().parent
        for db_path, schema_name in (
            (self.sessions_path, "schema.sql"),
            (self.bcg_path, "bcg_schema.sql"),
        ):
            connection = self._connect(db_path)
            try:
                connection.executescript((base / schema_name).read_text(encoding="utf-8"))
                if schema_name == "schema.sql":
                    # CREATE TABLE does not add columns to an existing Pi.  Keep
                    # this additive migration idempotent so a field unit can be
                    # upgraded without exporting or recreating health records.
                    existing = {
                        row[1] for row in connection.execute("PRAGMA table_info(sessions)")
                    }
                    for name in ("identity_subject", "pod_id", "zeep_public_id"):
                        if name not in existing:
                            connection.execute(f"ALTER TABLE sessions ADD COLUMN {name} TEXT")
                    connection.execute(
                        "CREATE INDEX IF NOT EXISTS idx_sessions_subject_start "
                        "ON sessions(identity_subject, start_time DESC)"
                    )
                    # Schema v4 persists the two ESP32 Air Sensor values that
                    # were previously available on Live/Monitor only.  Without
                    # these additive columns a completed Session incorrectly
                    # reported PMS7003 and SGP40 as "ไม่มีข้อมูล" even though
                    # both devices had been live during acquisition.
                    timeline_columns = {
                        row[1] for row in connection.execute("PRAGMA table_info(timeline)")
                    }
                    for name in ("pm2_5", "voc_index"):
                        if name not in timeline_columns:
                            connection.execute(
                                f"ALTER TABLE timeline ADD COLUMN {name} REAL"
                            )
                else:
                    # Existing Pod databases predate the explicit tx label.
                    # Keep epoch_index authoritative and backfill tx1, tx2, ...
                    # without touching raw packet data.
                    existing = {
                        row[1] for row in connection.execute("PRAGMA table_info(bcg_epochs)")
                    }
                    if "tx_label" not in existing:
                        connection.execute("ALTER TABLE bcg_epochs ADD COLUMN tx_label TEXT")
                    connection.execute(
                        "UPDATE bcg_epochs SET tx_label='tx' || epoch_index "
                        "WHERE tx_label IS NULL OR tx_label=''"
                    )
                connection.commit()
            finally:
                connection.close()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stopping.clear()
        self._thread = threading.Thread(target=self._run, name="sqlite-writer", daemon=True)
        self._thread.start()

    def rekey_session_accounts(self, mapping: dict[str, str]) -> int:
        """Atomically migrate legacy username keys to canonical email keys.

        This runs during application startup before the writer thread starts,
        so historical Session/Timeline relationships remain untouched while
        every Session becomes discoverable through the user's email identity.
        """
        changed = 0
        connection = self._connect(self.sessions_path)
        try:
            with connection:
                for old_key, new_key in mapping.items():
                    old = str(old_key or "").strip().casefold()
                    new = str(new_key or "").strip().casefold()
                    if not old or not new or old == new:
                        continue
                    cursor = connection.execute(
                        "UPDATE sessions SET username_key=? WHERE lower(username_key)=?",
                        (new, old),
                    )
                    changed += max(0, int(cursor.rowcount or 0))
        finally:
            connection.close()
        return changed

    def enqueue(self, database: str, operation: str, payload: Any, timeout: float = 5.0) -> None:
        if self._stopping.is_set():
            raise RuntimeError("database writer is stopping")
        self._queue.put(WriteJob(database, operation, payload), timeout=timeout)

    def flush(self, timeout: float = 30.0) -> bool:
        deadline = time.monotonic() + timeout
        while self._queue.unfinished_tasks and time.monotonic() < deadline:
            time.sleep(0.02)
        return self._queue.unfinished_tasks == 0

    def stop(self, timeout: float = 30.0) -> None:
        self._stopping.set()
        self.flush(timeout)
        if self._thread and self._thread.is_alive():
            self._queue.put(None)
            self._thread.join(timeout)

    def health(self) -> dict[str, Any]:
        with self._error_lock:
            error = self._last_error
        return {
            "queue_depth": self._queue.qsize(),
            "written_jobs": self._written,
            "last_error": error,
            "running": bool(self._thread and self._thread.is_alive()),
        }

    def _run(self) -> None:
        sessions = self._connect(self.sessions_path)
        bcg = self._connect(self.bcg_path)
        try:
            while True:
                job = self._queue.get()
                if job is None:
                    self._queue.task_done()
                    break
                try:
                    connection = sessions if job.database == "sessions" else bcg
                    self._apply(connection, job)
                    connection.commit()
                    self._written += 1
                except Exception as exc:
                    connection.rollback()
                    with self._error_lock:
                        self._last_error = f"{type(exc).__name__}: {exc}"
                    print(f"[DB] writer error ({job.operation}): {exc}")
                finally:
                    self._queue.task_done()
        finally:
            sessions.close()
            bcg.close()

    @staticmethod
    def _apply(connection: sqlite3.Connection, job: WriteJob) -> None:
        p = job.payload
        if job.operation == "session_start":
            connection.execute(
                """INSERT INTO sessions
                   (session_id,user,username_key,identity_subject,pod_id,zeep_public_id,
                    gender,start_time,created_at,schema_version)
                   VALUES (?,?,?,?,?,?,?,?,?,3)""",
                (p["session_id"], p["user"], p["username_key"],
                 p.get("identity_subject"), p.get("pod_id"), p.get("zeep_public_id"),
                 p.get("gender"), p["start_time"], p["created_at"]),
            )
        elif job.operation == "session_end":
            connection.execute(
                """UPDATE sessions SET end_time=?,duration=?,note=?,end_reason=?
                   WHERE session_id=?""",
                (p["end_time"], p["duration"], p.get("note"), p.get("end_reason"),
                p["session_id"]),
            )
        elif job.operation == "session_resume":
            # A service restart is a pause in acquisition, not a user logout.
            connection.execute(
                """UPDATE sessions SET end_time=NULL,duration=NULL,note=NULL,end_reason=NULL
                   WHERE session_id=?""",
                (p["session_id"],),
            )
            connection.execute(
                "DELETE FROM events WHERE session_id=? AND type='final_summary'",
                (p["session_id"],),
            )
        elif job.operation == "session_profile_update":
            # Presentation name stays in profiles.json; the Session table keeps
            # only the physiological gender used by the versioned baseline.
            connection.execute(
                "UPDATE sessions SET gender=? WHERE session_id=?",
                (p.get("gender"), p["session_id"]),
            )
        elif job.operation == "timeline":
            connection.execute(
                """INSERT INTO timeline
                   (session_id,timestamp,temperature,humidity,co2,pm2_5,voc_index,
                    lux,sound,heart_rate,respiration_rate,bed_status)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (p["session_id"], p["timestamp"], p.get("temperature"), p.get("humidity"),
                 p.get("co2"), p.get("pm2_5"), p.get("voc_index"), p.get("lux"),
                 p.get("sound"), p.get("heart_rate"), p.get("respiration_rate"),
                 p.get("bed_status")),
            )
        elif job.operation == "event":
            value = p.get("value")
            if value is not None and not isinstance(value, str):
                value = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            connection.execute(
                "INSERT INTO events(session_id,timestamp,type,value) VALUES (?,?,?,?)",
                (p["session_id"], p["timestamp"], p["type"], value),
            )
        elif job.operation == "bcg_epoch":
            cursor = connection.execute(
                """INSERT INTO bcg_epochs
                   (session_id,epoch_index,tx_label,start_time,end_time,packet_count,sample_count,
                    average_hr,average_rr) VALUES (?,?,?,?,?,?,?,?,?)""",
                (p["session_id"], p["epoch_index"],
                 p.get("tx_label") or f"tx{p['epoch_index']}", p["start_time"], p["end_time"],
                 p["packet_count"], p["sample_count"], p.get("average_hr"), p.get("average_rr")),
            )
            epoch_id = cursor.lastrowid
            connection.executemany(
                """INSERT INTO bcg_packets
                   (epoch_id,packet_index,timestamp,sensor_packet_id,status_code,heart_rate,
                    respiration_rate,bcg_base64,raw_packet_base64) VALUES (?,?,?,?,?,?,?,?,?)""",
                [(epoch_id, packet["packet_index"], packet["timestamp"],
                  packet.get("sensor_packet_id"), packet["status_code"], packet.get("heart_rate"),
                  packet.get("respiration_rate"), packet["bcg_base64"],
                  packet["raw_packet_base64"]) for packet in p["packets"]],
            )
        elif job.operation == "delete_bcg_session":
            epoch_ids = [row[0] for row in connection.execute(
                "SELECT epoch_id FROM bcg_epochs WHERE session_id=?", (p["session_id"],)
            )]
            if epoch_ids:
                connection.executemany("DELETE FROM bcg_packets WHERE epoch_id=?", [(x,) for x in epoch_ids])
            connection.execute("DELETE FROM bcg_epochs WHERE session_id=?", (p["session_id"],))
        elif job.operation == "delete_session":
            connection.execute("DELETE FROM sessions WHERE session_id=?", (p["session_id"],))
        else:
            raise ValueError(f"unknown write operation: {job.operation}")

    def read_sessions(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        connection = self._connect(self.sessions_path, readonly=True)
        try:
            return [dict(row) for row in connection.execute(sql, tuple(params)).fetchall()]
        finally:
            connection.close()

    def read_bcg(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        connection = self._connect(self.bcg_path, readonly=True)
        try:
            return [dict(row) for row in connection.execute(sql, tuple(params)).fetchall()]
        finally:
            connection.close()
