"""Per-user adaptive baselines — เรียนรู้ค่าเฉพาะบุคคลจากคืนแรก ๆ ของเขาเอง

ขอบเขต (ตาม KB governance):
- ใช้เพื่อ (1) ปรับเกณฑ์ sleep-state estimator รายบุคคล (2) วัดผลเทียบ baseline
  ตัวเอง (3) สร้างคำแนะนำเชิง advisory เท่านั้น
- 🔴 ห้ามนำผลไปสั่งอุปกรณ์แบบ real-time (closed-loop) ก่อนผ่าน G2 —
  ดู docs/closed-loop-spec.md; การปลุกใช้เวลานาฬิกาเท่านั้น ไม่ผูกกับ stage
- ทุกค่าเป็น proxy จาก BCG (ไม่มี EEG) — measure, not promise
"""
from __future__ import annotations

import json
import statistics
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from sleep_system_policy import (
    PERSONAL_BASELINE_MAX_NIGHTS,
    PERSONAL_BASELINE_MIN_DETECTED_SLEEP_SECONDS,
    PERSONAL_BASELINE_MIN_HR_SAMPLES,
    PERSONAL_BASELINE_MIN_NIGHTS,
    PERSONAL_BASELINE_MIN_SESSION_SECONDS,
    ZEEP_SLEEP_BASELINE_VERSION,
)

# เกณฑ์กลาง (population default) — ใช้จนกว่าจะเรียนรู้ครบขั้นต่ำ
DEFAULT_THRESHOLDS = {"cv_deep": 0.025, "cv_rem": 0.06}
MIN_NIGHTS = PERSONAL_BASELINE_MIN_NIGHTS
MAX_NIGHTS = PERSONAL_BASELINE_MAX_NIGHTS
MIN_SESSION_SECONDS = PERSONAL_BASELINE_MIN_SESSION_SECONDS
MIN_DETECTED_SLEEP_SECONDS = PERSONAL_BASELINE_MIN_DETECTED_SLEEP_SECONDS
MIN_HR_SAMPLES = PERSONAL_BASELINE_MIN_HR_SAMPLES


def _clip(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _percentile(values: list, q: float) -> Optional[float]:
    vals = sorted(v for v in values if isinstance(v, (int, float)))
    if not vals:
        return None
    idx = (len(vals) - 1) * q
    lo, hi = int(idx), min(int(idx) + 1, len(vals) - 1)
    frac = idx - lo
    return vals[lo] * (1 - frac) + vals[hi] * frac


class BaselineStore:
    """เก็บ/คำนวณ baseline ต่อ account key ลง data/baselines.json.

    ZEEP accounts use normalized email; local fallback retains its local
    username key because it has no remotely verified email.
    """

    def __init__(self, database, data_dir: Path):
        self.database = database
        self.path = Path(data_dir) / "baselines.json"
        self.lock = threading.Lock()
        self.data: dict[str, Any] = {}
        try:
            with self.path.open("r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                self.data = loaded
        except FileNotFoundError:
            pass
        except Exception as exc:
            print(f"[BASELINE] ignoring invalid baselines.json: {exc}")

    # ---------- persistence ----------
    def _save_locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=1)
        tmp.replace(self.path)

    def rekey_users(self, mapping: dict[str, str]) -> int:
        """Move learned baselines to the same email key as Profile/Session data."""
        changed = 0
        with self.lock:
            for old_key, new_key in mapping.items():
                old = str(old_key or "").strip().casefold()
                new = str(new_key or "").strip().casefold()
                if not old or not new or old == new or old not in self.data:
                    continue
                old_record = self.data.pop(old)
                current = self.data.get(new)
                if current is None or str(old_record.get("updated_at_utc") or "") > str(
                    current.get("updated_at_utc") or ""
                ):
                    self.data[new] = old_record
                changed += 1
            if changed:
                self._save_locked()
        return changed

    # ---------- learning ----------
    def _night_metrics(self, session_id: str) -> Optional[dict]:
        """สกัดตัวชี้วัดของ 1 คืนจาก timeline + final_summary

        ครอบคลุมสิ่งที่ engine ต้องใช้: awake baseline, sleeping median,
        lowest stable, variability, movement baseline, เวลาหลับ/ตื่น, รอบการนอน
        """
        # Personal Sleep Baseline must learn from detected sleep only.  A long
        # meditation/general-rest Session can contain stable HR/RR and would
        # otherwise look deceptively suitable for training.  The final report
        # is the versioned source of truth that separates those use cases.
        events = self.database.read_sessions(
            "SELECT value FROM events WHERE session_id=? AND type='final_summary' "
            "ORDER BY timestamp DESC LIMIT 1", (session_id,))
        if not events:
            return None
        try:
            final_summary = json.loads(events[0]["value"] or "{}")
        except (TypeError, json.JSONDecodeError):
            return None
        if not isinstance(final_summary, dict):
            return None
        night = final_summary.get("night_summary") or {}
        report = final_summary.get("session_report") or {}
        quality = night.get("sleep_quality") or report.get("quality") or {}
        detected_sleep_s = quality.get("estimated_sleep_s", night.get("estimated_sleep_s"))
        try:
            detected_sleep_s = float(detected_sleep_s or 0.0)
        except (TypeError, ValueError, OverflowError):
            detected_sleep_s = 0.0
        if not (
            quality.get("quality_type") == "sleep"
            and quality.get("sleep_detected") is True
            and detected_sleep_s >= MIN_DETECTED_SLEEP_SECONDS
        ):
            return None

        timeline = self.database.read_sessions(
            "SELECT timestamp,temperature,humidity,heart_rate,respiration_rate,bed_status "
            "FROM timeline WHERE session_id=? ORDER BY timestamp", (session_id,))
        quiet_rows = [r for r in timeline if r["bed_status"] in
                      ("On bed", "Snoring", "Weak breathing")]
        moving_rows = [r for r in timeline if r["bed_status"] == "Moving"]
        quiet_hr = [r["heart_rate"] for r in quiet_rows if r["heart_rate"]]
        if len(quiet_hr) < MIN_HR_SAMPLES:
            return None
        # rolling CV (หน้าต่าง 6 จุด ≈ 3 นาที) — ความ "เรียบ" ของ HR ตอนนิ่ง
        cvs = []
        for i in range(len(quiet_hr) - 5):
            win = quiet_hr[i:i + 6]
            mean = sum(win) / len(win)
            if mean > 0:
                cvs.append(statistics.pstdev(win) / mean)
        rrs = [r["respiration_rate"] for r in quiet_rows if r["respiration_rate"]]
        temps = [r["temperature"] for r in timeline if r["temperature"] is not None]
        # Do not treat every Moving row as awake: physiological sleep movement,
        # position changes and blanket adjustment can all load the bed sensor.
        # Until a time-aligned Wake decision is queried here, use only the
        # initial settling samples as the conservative awake-baseline proxy.
        awake_hr = [r["heart_rate"] for r in timeline[:20] if r["heart_rate"]]
        # lowest stable: ค่าต่ำจริงแบบไม่เอา outlier (p10 ของช่วงนิ่ง)
        low_stable = _percentile(quiet_hr, 0.10)
        metrics = {
            "hr_quiet_median": round(statistics.median(quiet_hr), 1),
            "hr_awake_median": round(statistics.median(awake_hr), 1) if awake_hr else None,
            "hr_low_stable": round(low_stable, 1) if low_stable else None,
            "hr_sleep_p25": round(_percentile(quiet_hr, 0.25), 1),
            "cv_p25": round(_percentile(cvs, 0.25), 4) if cvs else None,
            "cv_median": round(statistics.median(cvs), 4) if cvs else None,
            "cv_p75": round(_percentile(cvs, 0.75), 4) if cvs else None,
            "rr_median": round(statistics.median(rrs), 1) if rrs else None,
            "rr_low_stable": round(_percentile(rrs, 0.10), 1) if rrs else None,
            "move_ratio": (round(len(moving_rows) / len(timeline), 3)
                           if timeline else None),
            "temp_median": round(statistics.median(temps), 1) if temps else None,
        }
        # เวลาที่มักหลับ/ตื่น (ชั่วโมงท้องถิ่นแบบทศนิยม) จาก timeline จริง
        try:
            first = datetime.fromisoformat(timeline[0]["timestamp"]).astimezone()
            last = datetime.fromisoformat(timeline[-1]["timestamp"]).astimezone()
            metrics["bed_hour"] = round(first.hour + first.minute / 60, 2)
            metrics["rise_hour"] = round(last.hour + last.minute / 60, 2)
        except Exception:
            pass
        # onset / disruptions จาก final_summary (บันทึกตอน finalize)
        metrics["onset_proxy_s"] = night.get("sleep_onset_proxy_s")
        metrics["disruptions"] = night.get("awakenings")
        metrics["efficiency"] = night.get("sleep_efficiency")
        metrics["deep_ratio"] = night.get("deep_ratio")
        metrics["rem_ratio"] = night.get("rem_ratio")
        metrics["wellness_score"] = night.get("wellness_score")
        metrics["detected_sleep_s"] = round(detected_sleep_s, 1)
        # รอบการนอน: ประมาณจากช่วงเวลาระหว่างจุดเริ่ม REM ที่ต่อเนื่องกัน
        cycles = night.get("cycle_seconds_observed")
        if cycles:
            metrics["cycle_seconds"] = cycles
        return metrics

    def update_user(self, username_key: str) -> dict:
        """คำนวณ baseline ใหม่จากคืนล่าสุด ≤ MAX_NIGHTS ที่ผ่านเกณฑ์ขั้นต่ำ"""
        sessions = self.database.read_sessions(
            "SELECT session_id, duration FROM sessions "
            "WHERE username_key=? AND duration>=? ORDER BY start_time DESC LIMIT ?",
            (username_key, MIN_SESSION_SECONDS, MAX_NIGHTS))
        nights = []
        for row in sessions:
            m = self._night_metrics(row["session_id"])
            if m:
                nights.append(m)
        record: dict[str, Any] = {
            "policy_version": ZEEP_SLEEP_BASELINE_VERSION,
            "intended_use": "personal_wellness_baseline_not_diagnosis",
            "updated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "nights_used": len(nights),
            "min_nights": MIN_NIGHTS,
            "status": "active" if len(nights) >= MIN_NIGHTS else "learning",
            "nights": nights[:MAX_NIGHTS],
        }
        if nights:
            agg = lambda key: [n[key] for n in nights if n.get(key) is not None]  # noqa: E731
            med = lambda key: (round(statistics.median(agg(key)), 4)  # noqa: E731
                               if agg(key) else None)
            record.update({
                # ค่าที่ engine ใช้ตัดสิน (ชื่อ field ตรงกับ SleepEngine)
                "hr_awake_median": med("hr_awake_median"),
                "hr_sleep_median": med("hr_quiet_median"),
                "hr_low_stable": med("hr_low_stable"),
                "rr_sleep_median": med("rr_median"),
                "rr_low_stable": med("rr_low_stable"),
                "cv_p25": med("cv_p25"),
                "cv_median": med("cv_median"),
                "cv_p75": med("cv_p75"),
                "move_ratio_median": med("move_ratio"),
                "cycle_seconds_median": med("cycle_seconds"),
                "bed_hour_median": med("bed_hour"),
                "rise_hour_median": med("rise_hour"),
                # ค่าเชิงผลลัพธ์ไว้เทียบความคืบหน้า
                "temp_median": med("temp_median"),
                "onset_proxy_median_s": med("onset_proxy_s"),
                "disruptions_median": med("disruptions"),
                "efficiency_median": med("efficiency"),
                "deep_ratio_median": med("deep_ratio"),
                "rem_ratio_median": med("rem_ratio"),
                "wellness_score_median": med("wellness_score"),
            })
        if record["status"] == "active" and record.get("cv_p25") and record.get("cv_p75"):
            # เกณฑ์ส่วนบุคคล: DEEP = เรียบกว่า "ช่วงเรียบสุดของตัวเอง" เล็กน้อย,
            # REM = แกว่งกว่าช่วงบนของตัวเองชัดเจน · clip กันหลุดโลก + กันชนกัน
            cv_deep = _clip(record["cv_p25"] * 0.9, 0.015, 0.040)
            cv_rem = _clip(record["cv_p75"] * 1.6, 0.050, 0.090)
            if cv_rem < cv_deep + 0.02:
                cv_rem = cv_deep + 0.02
            record["thresholds"] = {"cv_deep": round(cv_deep, 4),
                                    "cv_rem": round(cv_rem, 4)}
        with self.lock:
            self.data[username_key] = record
            self._save_locked()
        return record

    # ---------- read side ----------
    def get(self, username_key: str) -> Optional[dict]:
        with self.lock:
            return self.data.get(username_key)

    def thresholds_for(self, username_key: str) -> Optional[dict]:
        """คืนเกณฑ์ส่วนบุคคลเมื่อเรียนรู้ครบแล้วเท่านั้น (ไม่ครบ → None = ใช้ค่ากลาง)"""
        record = self.get(username_key)
        if record and record.get("status") == "active" and record.get("thresholds"):
            return dict(record["thresholds"])
        return None

    def personalize_baseline(self, username_key: str, age_baseline: dict) -> tuple[dict, dict]:
        """เลื่อนช่วง HR/RR ของ age/gender baseline ให้ตรงกับตัวผู้ใช้จริง

        คืน (baseline ที่ปรับแล้ว, meta อธิบายที่มา) — ถ้ายังเรียนรู้ไม่ครบ
        MIN_NIGHTS จะคืน age_baseline เดิมพร้อม meta status=learning
        เพื่อให้ engine เดินต่อด้วยค่ากลางได้เหมือนเดิม
        """
        record = self.get(username_key)
        meta = {
            "source": "age_gender_default",
            "status": (record or {}).get("status", "no_data"),
            "nights_used": (record or {}).get("nights_used", 0),
            "min_nights": MIN_NIGHTS,
        }
        if not record or record.get("status") != "active":
            return age_baseline, meta

        hr_sleep = record.get("hr_sleep_median")
        hr_awake = record.get("hr_awake_median")
        rr_sleep = record.get("rr_sleep_median")
        if not hr_sleep:
            return age_baseline, meta

        # จุดอ้างอิงกลางของ age baseline สำหรับ N2 (default sleep state)
        ref_hr = sum(age_baseline["n2"]["hr"]) / 2
        hr_shift = round(hr_sleep - ref_hr, 1)
        # จำกัดการเลื่อนไม่ให้หลุดจริง (คนหนึ่งคนไม่ควรต่างจาก population เกิน 15 bpm)
        hr_shift = _clip(hr_shift, -15.0, 15.0)
        rr_shift = 0.0
        if rr_sleep:
            ref_rr = sum(age_baseline["n2"]["rr"]) / 2
            rr_shift = _clip(round(rr_sleep - ref_rr, 1), -4.0, 4.0)

        adjusted = {
            stage: {
                "hr": tuple(round(x + hr_shift, 1) for x in ranges["hr"]),
                "rr": tuple(round(x + rr_shift, 1) for x in ranges["rr"]),
            }
            for stage, ranges in age_baseline.items()
        }
        meta.update({
            "source": "personal",
            "hr_shift": hr_shift,
            "rr_shift": rr_shift,
            "hr_sleep_median": hr_sleep,
            "hr_awake_median": hr_awake,
            "hr_low_stable": record.get("hr_low_stable"),
            "cv_p25": record.get("cv_p25"),
            "cv_p75": record.get("cv_p75"),
            "move_ratio_median": record.get("move_ratio_median"),
            "bed_hour_median": record.get("bed_hour_median"),
            "rise_hour_median": record.get("rise_hour_median"),
            "note": (f"ปรับจากค่าเฉลี่ยของคุณเอง {record['nights_used']} คืนล่าสุด "
                     f"(HR เลื่อน {hr_shift:+.1f} bpm)"),
        })
        return adjusted, meta

    def recommendations(self, username_key: str) -> list[str]:
        """คำแนะนำเชิง advisory (ภาษาไทย, measure-not-promise) — คนกดปุ่มเอง"""
        record = self.get(username_key)
        tips: list[str] = []
        if not record or record["nights_used"] == 0:
            return ["ยังไม่มีคืนที่เรียนรู้ได้ — นอนบันทึกครบอย่างน้อย 20 นาทีต่อคืน "
                    f"สัก {MIN_NIGHTS} คืน ระบบจะเริ่มปรับค่าตามตัวคุณ"]
        if record["status"] == "learning":
            tips.append(f"กำลังเรียนรู้ค่าของคุณ: {record['nights_used']}/{MIN_NIGHTS} คืน "
                        "— ระหว่างนี้ใช้เกณฑ์กลางไปก่อน")
        onset = record.get("onset_proxy_median_s")
        if onset and onset > 30 * 60:
            tips.append("ช่วงที่ผ่านมาใช้เวลากว่าจะนิ่ง ~"
                        f"{round(onset / 60)} นาที — ลองเปิด 'ก่อนนอน · Wind-down Mix' "
                        "ก่อนขึ้นเตียง แล้วดูว่าตัวเลขคืนถัดไปเปลี่ยนไหม")
        disruptions = record.get("disruptions_median")
        if disruptions and disruptions >= 2:
            tips.append(f"มีช่วงสะดุดกลางคืนเฉลี่ย ~{round(disruptions)} ครั้ง/คืน — "
                        "ลองเสียง 'ฝนพรำ' แบบวนซ้ำเพื่อกลบเสียงรบกวน แล้วเทียบผล")
        temp = record.get("temp_median")
        if temp:
            tips.append(f"คืนที่บันทึกได้ อุณหภูมิในตู้ของคุณอยู่ราว {temp}°C — "
                        "จดค่านี้ไว้เทียบเมื่อปรับสภาพแวดล้อม")
        if record.get("thresholds"):
            tips.append("เกณฑ์ sleep-state ถูกปรับตามจังหวะหัวใจของคุณแล้ว "
                        "(ไม่ใช้ตัวเลขกลางของทุกคน)")
        tips.append("คำแนะนำเป็น advisory จากข้อมูลของคุณเอง — ไม่ใช่คำสัญญาผล "
                    "และระบบไม่สั่งอุปกรณ์อัตโนมัติจาก sleep state (รอ G2)")
        return tips
