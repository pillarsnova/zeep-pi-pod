"""Read-only ZEEP environment recommendations (Shadow Mode).

The evaluator is deliberately pure: it cannot reach GPIO, MQTT or device
controllers.  Sleep State remains telemetry and is never an actuator input.
This separation lets the team review wellness guidance independently from
hardware command safety.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import time
from typing import Any, Optional


@dataclass(frozen=True)
class SmartResponsePolicy:
    """Versioned thresholds injected by the Pi deployment configuration."""

    version: str
    temperature_min_c: float
    temperature_max_c: float
    co2_warn_ppm: float
    co2_critical_ppm: float
    sound_sleep_target_dba: float
    cadence_s: float = 1.0


def evaluate_smart_response(
    snapshot: dict[str, Any],
    policy: SmartResponsePolicy,
    *,
    now: Optional[float] = None,
) -> dict[str, Any]:
    """Evaluate recommendations without actuating any Pod device."""
    evaluated_at = time.time() if now is None else now
    environment = ((snapshot.get("sensor") or {}).get("environment") or {})
    devices = environment.get("devices") or {}
    safety = snapshot.get("safety") or {}
    session = snapshot.get("session") or {}
    aircon = snapshot.get("aircon") or {}

    if session.get("active") and session.get("recording"):
        phase, phase_label = "sleep_session", "กำลังบันทึกการนอน"
    elif session.get("active"):
        phase, phase_label = "wind_down", "เตรียมเข้านอน"
    else:
        phase, phase_label = "standby", "Standby"

    recommendations: list[dict[str, Any]] = []
    blockers: list[dict[str, str]] = []

    def recommend(
        domain: str,
        level: str,
        title: str,
        detail: str,
        suggestion: Optional[str] = None,
    ) -> None:
        item: dict[str, Any] = {
            "domain": domain,
            "level": level,
            "title": title,
            "detail": detail,
        }
        if suggestion:
            item["suggestion"] = suggestion
        recommendations.append(item)

    def numeric(name: str) -> Optional[float]:
        value = environment.get(name)
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(float(value))
        ):
            return None
        return float(value)

    if not safety.get("ready"):
        blockers.append({"code": "safety_not_ready", "message": "Safety Supervisor ยังไม่ READY"})
    if not safety.get("armed"):
        blockers.append({"code": "safety_not_armed", "message": "ระบบยังไม่ได้ ARM"})
    for key in ("mhz19c", "pms7003", "sgp40"):
        device = devices.get(key) or {}
        if device.get("status") != "live":
            blockers.append({
                "code": f"{key}_not_live",
                "message": f"{device.get('model', key)} ไม่ได้ส่งข้อมูล Live",
            })
    if not aircon.get("connected") or aircon.get("stale"):
        blockers.append({"code": "aircon_offline", "message": "Control Hub 1 ของแอร์ Offline"})

    temperature = numeric("temperature_c")
    if temperature is None:
        recommend("temperature", "blocked", "ไม่มีข้อมูลอุณหภูมิสด", "คงสถานะเดิมและรอ SHT3x-DIS กลับมา")
    elif temperature > policy.temperature_max_c:
        recommend(
            "temperature", "attention", "อุณหภูมิสูงกว่าช่วงเป้าหมาย",
            f"วัดได้ {temperature:.1f}°C; ตรวจความสบายก่อนลด setpoint แบบทีละ 1°C",
            "เสนอให้ลด setpoint 1°C (ยังไม่สั่งจริง)",
        )
    elif temperature < policy.temperature_min_c:
        recommend(
            "temperature", "attention", "อุณหภูมิต่ำกว่าช่วงเป้าหมาย",
            f"วัดได้ {temperature:.1f}°C; ตรวจความสบายก่อนเพิ่ม setpoint แบบทีละ 1°C",
            "เสนอให้เพิ่ม setpoint 1°C (ยังไม่สั่งจริง)",
        )
    else:
        recommend("temperature", "stable", "อุณหภูมิอยู่ในช่วงยอดเยี่ยม", f"{temperature:.1f}°C · คงค่าปัจจุบันและติดตามแนวโน้ม")

    humidity = numeric("humidity_rh")
    if humidity is None:
        recommend("humidity", "blocked", "ไม่มีข้อมูลความชื้นสด", "คงสถานะเดิมและรอ SHT3x-DIS กลับมา")
    elif humidity > 60.0:
        recommend("humidity", "attention", "ความชื้นเริ่มสูง", f"วัดได้ {humidity:.1f}%RH; ตรวจ condensation และการระบายอากาศ")
    elif humidity < 40.0:
        recommend("humidity", "attention", "ความชื้นค่อนข้างต่ำ", f"วัดได้ {humidity:.1f}%RH; หลีกเลี่ยงการพ่นไอน้ำอัตโนมัติจนผ่าน safety review")
    else:
        recommend("humidity", "stable", "ความชื้นอยู่ในช่วงเฝ้าดู", f"{humidity:.1f}%RH · คงค่าปัจจุบัน")

    co2 = numeric("co2_ppm")
    if co2 is None or (devices.get("mhz19c") or {}).get("status") != "live":
        recommend("air", "blocked", "ยังประเมินอากาศสดไม่ได้", "MH-Z19C Offline — ห้ามสั่ง ventilation อัตโนมัติจากค่าค้าง")
    elif co2 >= policy.co2_critical_ppm:
        recommend("air", "critical", "CO₂ ถึงระดับฉุกเฉิน", f"{co2:.0f} ppm · ใช้ Safety SOP และเพิ่มอากาศสดทันทีเมื่อระบบระบายพร้อม")
    elif co2 >= policy.co2_warn_ppm:
        recommend("air", "attention", "CO₂ เริ่มสูง", f"{co2:.0f} ppm · เสนอเพิ่มอากาศสดและติดตามค่าเฉลี่ยเคลื่อนที่")
    elif co2 >= 800:
        recommend("air", "watch", "CO₂ กำลังไต่ขึ้น", f"{co2:.0f} ppm · เตรียมเพิ่มอากาศสดก่อนถึง 1,000 ppm")
    else:
        recommend("air", "stable", "CO₂ อยู่ในช่วงเฝ้าดู", f"{co2:.0f} ppm · คง ventilation ปัจจุบัน")

    pm25 = numeric("pm2_5_ug_m3")
    if pm25 is None or (devices.get("pms7003") or {}).get("status") != "live":
        recommend("particles", "blocked", "ยังประเมิน PM2.5 ไม่ได้", "PMS7003 Offline — ไม่อนุมานว่าฝุ่นเป็นศูนย์")
    elif pm25 >= 35:
        recommend("particles", "attention", "PM2.5 สูงกว่าช่วง Pilot", f"{pm25:.1f} µg/m³ · เสนอเพิ่ม HEPA recirculation")
    elif pm25 >= 15:
        recommend("particles", "watch", "PM2.5 ควรติดตาม", f"{pm25:.1f} µg/m³ · ตรวจ filter และแนวโน้มต่อเนื่อง")
    else:
        recommend("particles", "stable", "PM2.5 อยู่ในช่วงเฝ้าดู", f"{pm25:.1f} µg/m³ · คงการกรองปัจจุบัน")

    voc = numeric("voc_index")
    if voc is None or (devices.get("sgp40") or {}).get("status") != "live":
        recommend("voc", "blocked", "ยังประเมิน VOC Index ไม่ได้", "SGP40 Offline — รอ Adaptive Baseline กลับมาทำงาน")
    elif voc >= 200:
        recommend("voc", "attention", "VOC เพิ่มสูงจาก Baseline", f"VOC Index {voc:.0f} · เสนอเพิ่ม carbon filtration/อากาศสด")
    elif voc >= 150:
        recommend("voc", "watch", "VOC สูงกว่าค่ากลางของห้อง", f"VOC Index {voc:.0f} · ติดตามแนวโน้มก่อนสั่งงาน")
    else:
        recommend("voc", "stable", "VOC ใกล้ Adaptive Baseline", f"VOC Index {voc:.0f} · ค่า 100 คือ Baseline ที่ SGP40 เรียนรู้")

    sound = numeric("sound_dba_est")
    if sound is None:
        recommend("sound", "blocked", "ไม่มีข้อมูลเสียงสด", "คงระดับเสียงเดิมและรอ SPH0645 กลับมา")
    elif sound > policy.sound_sleep_target_dba:
        recommend(
            "sound", "attention", "เสียงสูงกว่าเป้าหมายกลางคืน",
            f"ประเมินได้ {sound:.1f} dBA est.; เป้าหมายไม่เกิน {policy.sound_sleep_target_dba:.0f} — ตรวจเทียบ LAeq ที่ตำแหน่งหมอนและลดเสียงอย่างนุ่มนวล",
            "เสนอให้ลดระดับเสียง (ยังไม่สั่งจริง)",
        )
    else:
        recommend("sound", "stable", "ระดับเสียงอยู่ในเป้าหมาย", f"{sound:.1f} dBA est. · เป้าหมาย ≤{policy.sound_sleep_target_dba:.0f} · คงระดับปัจจุบัน")

    lux = numeric("lux")
    lux_limit = 1.0 if phase == "sleep_session" else 10.0
    if lux is not None and phase != "standby" and lux > lux_limit:
        recommend("light", "attention", "แสงสูงกว่าช่วงของ Session", f"Photopic {lux:.2f} lux; เสนอหรี่ไฟ แต่ยังยืนยัน mEDI ไม่ได้หากไม่มี spectral sensor")
    elif lux is not None:
        recommend("light", "stable", "แสงอยู่ในช่วงเฝ้าดู", f"Photopic {lux:.2f} lux · ไม่อ้าง mEDI จาก lux เพียงค่าเดียว")

    severe_levels = {"critical", "attention", "blocked"}
    attention_count = sum(1 for item in recommendations if item["level"] in severe_levels)
    status = "blocked" if blockers else "attention" if attention_count else "stable"
    summary = "ยังไม่พร้อมทดสอบ Auto Response" if blockers else "พร้อมเก็บผล Shadow เพื่อทวนกฎควบคุม"
    return {
        "enabled": True,
        "mode": "shadow",
        "status": status,
        "policy_version": policy.version,
        "cadence_s": policy.cadence_s,
        "evaluated_at": evaluated_at,
        "phase": phase,
        "phase_label": phase_label,
        "summary": summary,
        "recommendations": recommendations,
        "blockers": blockers,
        "attention_count": attention_count,
        "automatic_actuation": False,
        "sleep_stage_used": False,
        "bed_auto_move": False,
        "guardrails": [
            "Sleep Stage เป็น telemetry เท่านั้นและไม่ใช้สั่งอุปกรณ์",
            "เตียงควบคุมด้วยผู้ใช้และปุ่มหยุดเท่านั้น",
            "ค่าที่ Offline/Stale ไม่ถูกแทนเป็นศูนย์หรือใช้สั่งงาน",
        ],
    }
