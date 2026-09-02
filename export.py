"""Session-scoped CSV, JSON, SQLite and BCG export builders."""
from __future__ import annotations

import csv
import json
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from database import DatabaseManager


def temporary_path(suffix: str) -> Path:
    handle = tempfile.NamedTemporaryFile(prefix="zeep-export-", suffix=suffix, delete=False)
    path = Path(handle.name)
    handle.close()
    return path


def summary_csv(database: DatabaseManager, session_id: str) -> Path:
    rows = database.read_sessions("SELECT * FROM sessions WHERE session_id=?", (session_id,))
    path = temporary_path(".csv")
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return path


def timeline_csv(database: DatabaseManager, session_id: str) -> Path:
    rows = database.read_sessions(
        """SELECT timestamp,heart_rate AS HR,respiration_rate AS RR,
                  temperature AS Temp,humidity AS Humidity,lux AS Lux,sound AS Sound,
                  bed_status AS Bed,co2 AS CO2,pm2_5 AS PM2_5,voc_index AS VOC_Index
           FROM timeline WHERE session_id=? ORDER BY timestamp""", (session_id,))
    path = temporary_path(".csv")
    fields = [
        "timestamp", "HR", "RR", "Temp", "Humidity", "Lux", "Sound",
        "Bed", "CO2", "PM2_5", "VOC_Index",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return path


def session_json(database: DatabaseManager, session_id: str) -> Path:
    session = database.read_sessions("SELECT * FROM sessions WHERE session_id=?", (session_id,))[0]
    payload = {
        "session": session,
        "timeline": database.read_sessions(
            "SELECT * FROM timeline WHERE session_id=? ORDER BY timestamp", (session_id,)),
        "events": database.read_sessions(
            "SELECT * FROM events WHERE session_id=? ORDER BY timestamp", (session_id,)),
        "bcg_epochs": database.read_bcg(
            "SELECT * FROM bcg_epochs WHERE session_id=? ORDER BY epoch_index", (session_id,)),
    }
    path = temporary_path(".json")
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def bcg_zip(database: DatabaseManager, session_id: str, *, raw_only: bool = False) -> Path:
    epochs = database.read_bcg(
        "SELECT * FROM bcg_epochs WHERE session_id=? ORDER BY epoch_index", (session_id,))
    path = temporary_path(".zip")
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for epoch in epochs:
            packets = database.read_bcg(
                "SELECT * FROM bcg_packets WHERE epoch_id=? ORDER BY packet_index", (epoch["epoch_id"],))
            if raw_only:
                payload: Any = [{"timestamp": p["timestamp"], "packet_index": p["packet_index"],
                                 "raw_packet_base64": p["raw_packet_base64"]} for p in packets]
            else:
                payload = {"epoch": epoch, "packets": packets}
            archive.writestr(
                f"epoch_{epoch['epoch_index']:04d}.json",
                json.dumps(payload, ensure_ascii=False, indent=2),
            )
    return path


def session_sqlite(database: DatabaseManager, session_id: str) -> Path:
    """Create a portable SQLite file containing only the requested session."""
    path = temporary_path(".sqlite")
    target = sqlite3.connect(path)
    try:
        schema = (Path(__file__).resolve().parent / "schema.sql").read_text(encoding="utf-8")
        target.executescript(schema)
        target.execute("ATTACH DATABASE ? AS source", (str(database.sessions_path),))
        target.execute("INSERT INTO sessions SELECT * FROM source.sessions WHERE session_id=?", (session_id,))
        target.execute("INSERT INTO timeline SELECT * FROM source.timeline WHERE session_id=?", (session_id,))
        target.execute("INSERT INTO events SELECT * FROM source.events WHERE session_id=?", (session_id,))
        target.commit()
    finally:
        target.close()
    return path
