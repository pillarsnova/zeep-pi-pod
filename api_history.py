"""SQLite-backed session history, research detail and download API routes."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.background import BackgroundTasks
from fastapi.responses import FileResponse

import export
from database import DatabaseManager


def create_history_router(
    database: DatabaseManager,
    *,
    require_admin: Callable[..., Any],
) -> APIRouter:
    """Create raw/research history routes protected at the router boundary.

    These endpoints expose all users, raw BCG packets and database exports.
    Keeping the dependency on the router prevents a future endpoint from being
    accidentally added without administrator authorization.
    """
    router = APIRouter(dependencies=[Depends(require_admin)])

    def require_session(session_id: str) -> dict[str, Any]:
        rows = database.read_sessions("SELECT * FROM sessions WHERE session_id=?", (session_id,))
        if not rows:
            raise HTTPException(404, "Session not found")
        return rows[0]

    @router.get("/api/sessions")
    def sessions(limit: int = Query(20, ge=1, le=200), offset: int = Query(0, ge=0)):
        rows = database.read_sessions(
            "SELECT * FROM sessions ORDER BY start_time DESC LIMIT ? OFFSET ?", (limit, offset))
        total = database.read_sessions("SELECT COUNT(*) AS n FROM sessions")[0]["n"]
        return {"sessions": rows, "total": total, "limit": limit, "offset": offset}

    @router.get("/api/session/{session_id}")
    def session_detail(session_id: str):
        session = require_session(session_id)
        timeline_count = database.read_sessions(
            "SELECT COUNT(*) AS n FROM timeline WHERE session_id=?", (session_id,))[0]["n"]
        event_count = database.read_sessions(
            "SELECT COUNT(*) AS n FROM events WHERE session_id=?", (session_id,))[0]["n"]
        stats = database.read_bcg(
            """SELECT COUNT(*) AS epoch_count,COALESCE(SUM(packet_count),0) AS packet_count,
                      COALESCE(SUM(sample_count),0) AS sample_count,AVG(average_hr) AS average_hr,
                      AVG(average_rr) AS average_rr FROM bcg_epochs WHERE session_id=?""", (session_id,))[0]
        return {"session": session, "timeline_count": timeline_count,
                "event_count": event_count, "bcg": stats}

    @router.get("/api/session/{session_id}/timeline")
    def timeline(session_id: str, limit: int = Query(1000, ge=1, le=5000), offset: int = Query(0, ge=0)):
        require_session(session_id)
        rows = database.read_sessions(
            "SELECT * FROM timeline WHERE session_id=? ORDER BY timestamp LIMIT ? OFFSET ?",
            (session_id, limit, offset))
        return {"session_id": session_id, "timeline": rows, "limit": limit, "offset": offset}

    @router.get("/api/session/{session_id}/events")
    def events(session_id: str, limit: int = Query(1000, ge=1, le=5000), offset: int = Query(0, ge=0)):
        require_session(session_id)
        rows = database.read_sessions(
            "SELECT * FROM events WHERE session_id=? ORDER BY timestamp LIMIT ? OFFSET ?",
            (session_id, limit, offset))
        return {"session_id": session_id, "events": rows, "limit": limit, "offset": offset}

    @router.get("/api/session/{session_id}/bcg")
    def bcg(session_id: str, limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0)):
        require_session(session_id)
        rows = database.read_bcg(
            "SELECT * FROM bcg_epochs WHERE session_id=? ORDER BY epoch_index LIMIT ? OFFSET ?",
            (session_id, limit, offset))
        return {"session_id": session_id, "epochs": rows, "limit": limit, "offset": offset}

    @router.get("/api/session/{session_id}/bcg/replay")
    def replay(session_id: str, limit: int = Query(1000, ge=1, le=5000), offset: int = Query(0, ge=0)):
        require_session(session_id)
        rows = database.read_bcg(
            """SELECT e.epoch_index,p.packet_index,p.timestamp,p.status_code,p.heart_rate,
                      p.respiration_rate,p.bcg_base64
               FROM bcg_packets p JOIN bcg_epochs e ON e.epoch_id=p.epoch_id
               WHERE e.session_id=? ORDER BY e.epoch_index,p.packet_index LIMIT ? OFFSET ?""",
            (session_id, limit, offset))
        return {"session_id": session_id, "packets": rows, "limit": limit, "offset": offset}

    builders: dict[str, tuple[Callable[..., Path], str, str]] = {
        "summary_csv": (export.summary_csv, "text/csv", "summary.csv"),
        "timeline_csv": (export.timeline_csv, "text/csv", "timeline.csv"),
        "json": (export.session_json, "application/json", "session.json"),
        "sqlite": (export.session_sqlite, "application/vnd.sqlite3", "session.sqlite"),
        "bcg_zip": (export.bcg_zip, "application/zip", "bcg.zip"),
    }

    @router.get("/api/session/{session_id}/download")
    def download(background_tasks: BackgroundTasks, session_id: str,
                 format: str = Query("json")):
        require_session(session_id)
        if format == "raw":
            path = export.bcg_zip(database, session_id, raw_only=True)
            media_type, filename = "application/zip", "raw-packets.zip"
        else:
            spec = builders.get(format)
            if not spec:
                raise HTTPException(422, f"Unknown export format: {format}")
            builder, media_type, filename = spec
            path = builder(database, session_id)
        background_tasks.add_task(path.unlink, missing_ok=True)
        return FileResponse(path, media_type=media_type,
                            filename=f"{session_id}-{filename}", background=background_tasks)

    return router
