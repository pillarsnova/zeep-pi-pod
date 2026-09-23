# ZEEP — ตรวจและล้างโค้ดที่เลิกใช้งาน

วันที่: 23 กันยายน 2026 · ขอบเขต: Mac source / `develop`
ฐานก่อนเริ่ม: `5de1b2e` จาก `origin/develop`; Knowledge Hub/เอกสารแยก commit `7cdb173`

## TL;DR

ลบตัวช่วยที่ไม่มีผู้เรียก 9 ฟังก์ชัน พร้อม alias, import, lock และค่าคงที่ค้าง
จากการแยกโมดูล นำเครื่องมือ preview การปรับเสียงย้อนหลังที่เลิกใช้และ test
เฉพาะเครื่องมือนั้นออกจาก repository ปัจจุบัน ประวัติโค้ดยังค้นได้ใน Git

`app.py` ลดจาก 5,932 เป็น 5,878 บรรทัด ไม่เปลี่ยนสูตร Sleep/Recovery Score,
Sleep State, Sensor cadence, Session lifecycle หรือสิทธิ์เข้าถึงข้อมูล
โค้ด Python และ test ลดสุทธิ 453 บรรทัด เทียบ commit `7cdb173`
ไม่มีการแก้ฐานข้อมูล Raw, ประมวลผลย้อนหลัง, สั่งอุปกรณ์, Flash หรือ Restart
รอบนี้ลดภาระดูแลโค้ด; ยังไม่ได้วัดผลว่าระบบทำงานเร็วขึ้นเท่าใด

## รายการที่ลบและเหตุผล

| ส่วน | สิ่งที่ลบ | หลักฐานและส่วนที่ใช้แทน |
|---|---|---|
| `app.py` — JSONL | `_read_sessions`, `_append_session_record`, `_rewrite_sessions`, `sessions_file_lock` | ไม่มี caller; Session ปัจจุบันใช้ SQLite ผ่านชั้น Database ตัวนำเข้า `migration.migrate_jsonl` ยังอยู่ |
| `app.py` — Outbox | `_ingest_outbox_path`, `_write_ingest_outbox`, `_post_ingest_entry` | Wrapper ไม่ถูกเรียก; `sessions/ingest_outbox.py` ยังดูแล persistence/retry ตามเดิม |
| `app.py` — alias/import | Checkpoint lock/version alias, identity alias, import ที่เหลือจาก alias และ `OccupancyLease` import | Checkpoint store และ identity module ทำงานเองอยู่แล้ว; QR/password login, lease และ restart recovery ไม่ถูกลบ |
| Sensor calibration | `_first_finite_metric` | ไม่มี caller หลัง normalization ถูกแยกเป็นโมดูล; ไม่เปลี่ยน Bias หรือค่าจาก ESP32 |
| Session trim | `_stats` และ import `Optional` | ไม่มี caller; รายงานใช้ `project_report_samples` และ report builder ตามเดิม |
| Local snapshot | `require_regular_file`, `PRIVATE_FILE_MODE` | ไม่มี caller; ยังตรวจ descriptor, symlink, ownership และ permissions ด้วย helper ที่ใช้งานจริง |
| History / Baseline / Scorer | `USER_HISTORY_FILTER`, `DEFAULT_THRESHOLDS`, local `bed_status` ที่ไม่ถูกอ่าน | ไม่ใช่ filter/threshold ที่ runtime ใช้; คง SQL/account boundary และ scorer policy จริง |
| Sound maintenance | `recalibrate_sound_history.py`, `test_recalibrate_sound_history.py` และ registry entry | เป็น preview ของนโยบาย Pi-side delta ที่เลิกใช้ ไม่ถูกเรียกจาก runtime และ `--apply` ถูกปิดอยู่แล้ว |

## ผลต่อสัญญาการใช้งาน

- Maintenance registry เป็น `zeep-maintenance-tools-v1.6` และไม่โฆษณา
  `recalibrate_sound_history.py` เป็นเครื่องมือที่ใช้ได้อีก
- คำสั่งเดิมที่เรียกไฟล์ดังกล่าวจะหาไฟล์ไม่พบ ไม่มีการนำค่าชดเชยไปเขียนข้อมูล
- เสียงยังรับ `sound_dba` จาก ESP32 โดยตรงตาม contract เดิม ไม่บวก/ลบ Bias บน Pi
- เพิ่ม regression ใน `test_maintenance_registry.py` กันการนำเครื่องมือที่เลิกใช้
  กลับเข้าชุดโดยไม่ตั้งใจ ลบเฉพาะ test ของ feature ที่ลบ ไม่ลดชุดตรวจ Sensor/Score
- ลดเพดานขนาด `app.py` ใน architecture test ตามขนาดจริง เพื่อไม่ให้โค้ดกลับไปกองรวม

## ส่วนที่ยังเก็บไว้

1. `SESSIONS_PATH` และ JSONL migration: ยังถูกเรียกตอนเริ่มระบบเพื่อรับข้อมูลเดิม
2. Root compatibility facades และ legacy API: ยังมี caller/test/สัญญากับ client
3. Imports ของ Sleep Estimator: หลายตัวถูกส่งผ่าน `LiveSleepRuntime.from_namespace`
   จึงไม่ใช่โค้ดตาย แม้เครื่องมือ lint แบบทั่วไปอาจรายงานว่าไม่ใช้
4. Raw, database, backups และ `docs/archive/sound-processing-history-2026-09-10.json`:
   เป็นข้อมูล/หลักฐาน ไม่ใช่ runtime ที่ควรลบจากการค้นชื่อเพียงอย่างเดียว
5. Preview tools: ใช้ตรวจ UI ด้วยข้อมูลจำลองโดยไม่ต่อ Pod ยังมีประโยชน์ในการพัฒนา
6. รายงาน Audit ตามวันที่: คงข้อความเดิมที่บอกว่าเป็น Working tree ณ เวลานั้น
   อัปเดตสถานะปัจจุบันเฉพาะ Current Status, Onboarding และคู่มือหลัก

## วิธีตรวจ

ตรวจ definition/reference จากไฟล์ที่ติดตามใน Git ทั้ง Python, JavaScript,
HTML, shell, workflow และเอกสาร จากนั้นอ่านจุดประกอบ runtime และ module
ที่ใช้แทนก่อนลบ ไม่ใช้ผล unused-import หรืออายุไฟล์เป็นเหตุผลเดียว

## Verification

ชุดตรวจที่ใช้สำหรับการเปลี่ยนหลายโดเมนและการนำเครื่องมือเก่าออก:

```sh
python quality_gate.py full
python -m documentation check
python ui_composer.py check
git diff --check
```

ผลตรวจบน Mac / Python 3.13 ก่อน Commit ชุดล้างโค้ด:

- Full regression **1,387 tests ผ่าน, 0 failed/error, 0 skipped**
- Ruff check/format ผ่านทั้ง 191 ไฟล์ใน extracted packages
- Root Python compilation และ UI composer ผ่าน
- ทะเบียนงานวิจัย 35 รายการ, Markdown/JSON consistency และ protocol register ผ่าน
- Knowledge Hub ตรงกับต้นทาง 60 บท; `git diff --check` ผ่าน
- Import ที่ลบไม่อยู่ใน field contract ของ `LiveSleepRuntime`

การทดสอบทั้งหมดใช้ fixture/temporary data ไม่มีการใช้ข้อมูลผู้พักจริง
และผลนี้ไม่ใช่การทดสอบอุปกรณ์หรือหลักฐาน Deploy

## งานต่อไปที่ไม่รวมในรอบล้างโค้ด

`app.py` และ live estimator ยังเป็นส่วนขนาดใหญ่ ต้องแยกความรับผิดชอบพร้อม
characterization tests ต่อ ไม่ควรลบเพียงเพราะไฟล์ยาวหรือชื่อเป็น legacy
การตัด API/facade ที่ยังใช้ต้องมี client migration แยกจากงานนี้
