"""One explainable advisory, with no actuator or external AI dependency."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from adaptive.outcomes import window_summary
from common.numbers import as_finite_number

VERSION = "zeep.adaptive-coach.v1"


def one_recommendation(
    session_id: str,
    snapshot: dict[str, Any],
    reference: dict[str, Any],
    samples: list[dict[str, Any]],
    commands: list[dict[str, Any]],
    *,
    now: float,
) -> dict[str, Any]:
    """Offer one reviewable adjustment; acceptance never executes hardware."""
    session, frame = snapshot.get("session") or {}, snapshot.get("sensor_frame") or {}
    safety = snapshot.get("safety") or {}
    response = {
        "version": VERSION,
        "engine": "explainable_rules",
        "item": None,
        "automatic_actuation": False,
        "score_modified": False,
        "message": "ยังไม่มีคำแนะนำเพิ่มเติม",
    }
    age = as_finite_number(frame.get("data_age_s"))
    if not session.get("recording") or session.get("session_id") != session_id:
        response["message"] = "คำแนะนำปรับอุปกรณ์แสดงขณะใช้งานตู้เท่านั้น"
        return response
    if (
        frame.get("stale")
        or age is None
        or age > 30
        or not safety.get("ready")
        or safety.get("latched")
    ):
        response["message"] = "รอข้อมูลปัจจุบันและความพร้อมของระบบ"
        return response
    if any(now - 600 < command["t"] <= now for command in commands):
        response["message"] = "กำลังติดตามผลหลังคำสั่งล่าสุด"
        return response
    environment = (snapshot.get("sensor") or {}).get("environment") or {}
    specs = (
        ("temperature", "sht3x_dis", "aircon", "อุณหภูมิ", "°C", 1.0),
        ("sound", "sph0645", "audio", "ระดับเสียง", "dBA", 3.0),
        ("lux", "opt3001", "lighting", "ความสว่าง", "lux", 5.0),
    )
    for key, device, control, label, unit, tolerance in specs:
        target = (reference.get("ranges") or {}).get(key)
        live = (environment.get("devices") or {}).get(device) or {}
        if not target or live.get("status") != "live":
            continue
        observed = window_summary(samples, key, now - 300, now)
        if observed["coverage"] < 0.8 or observed["value"] is None:
            continue
        delta = observed["value"] - target["typical"]
        if abs(delta) <= tolerance or (key != "temperature" and delta < 0):
            continue
        direction = "ลด" if delta > 0 else "เพิ่ม"
        reason = (
            f"{label}ช่วง 5 นาทีล่าสุด {observed['value']:g} {unit} "
            f"เทียบกับค่าอ้างอิงจากช่วงที่พักสบาย {target['typical']:g} {unit}"
        )
        basis = {
            "session": session_id,
            "metric": key,
            "direction": direction,
            "reference": target,
            "bucket": int(now // 120),
        }
        identifier = hashlib.sha256(
            json.dumps(basis, sort_keys=True).encode()
        ).hexdigest()[:24]
        response["item"] = {
            "id": identifier,
            "device": control,
            "metric": key,
            "title": f"แนะนำให้{direction}{label}",
            "reason": reason,
            "reference_status": reference["status"],
            "requires_confirmation": True,
            "execution": "manual_control_only",
            "expires_at": (int(now // 120) + 1) * 120,
            "confirmation_label": "ไปหน้าควบคุม",
        }
        break
    return response
