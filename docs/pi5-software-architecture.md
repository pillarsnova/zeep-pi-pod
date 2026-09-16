# ZEEP Pi5 Software Architecture

สถานะ: **Current implementation**
ขอบเขต: `/home/pod1/pi5` · branch `origin/develop`

เอกสารนี้เป็นแผนที่กลางสำหรับพัฒนาและตรวจสอบ Pi5 runtime ของ ZEEP ทุกตู้
เป้าหมายคือให้แก้แต่ละส่วนได้โดยไม่ทำให้ Sensor, Session, Safety และอุปกรณ์
ควบคุมกระทบกันโดยไม่ตั้งใจ

## 1. หลักการแบ่งระบบ

`app.py` เป็น **legacy composition root**: Sensor-frame sampler ถูกย้ายออกแล้วและ
เหลือเพียง compatibility facade แต่ Session/Sleep orchestration และ routes บางส่วน
ยังอยู่ เป้าหมายที่บังคับด้วย architecture ratchet คือให้เหลือเฉพาะการสร้าง FastAPI
app, ต่อ lifecycle, ประกอบ dependency และเรียก adapters เท่านั้น กฎ deterministic
ใหม่ต้องอยู่ใน pure module เพื่อให้ทดสอบได้โดยไม่เปิด GPIO, Serial, MQTT หรือเสียง

| Layer | Source of truth | หน้าที่ |
|---|---|---|
| HTTP contracts | `api_models.py`, `api_v1.py` | รูปแบบ request/response และ versioned envelope |
| Authentication | `access_control.py`, `admin_accounts.py` | Browser session, RBAC, CSRF และ Admin identity; Production เตรียม schema/config ใน lifespan และ direct caller มี guarded lazy fallback |
| ZEEP account binding | `zeep_pod/identity/zeep_account.py` | ผูก `{tokens, user}` จาก Password/QR login เข้ากับตัวตนในตู้ |
| QR login | `qr_login.py` | Pi ทำ handshake แทนแท็บเล็ต และถือ `pollSecret` ไว้เอง |
| Occupancy | `pod_occupancy.py` | หนึ่งผู้ใช้ต่อหนึ่งตู้และป้องกัน login ซ้ำหลายตู้; lease store initialize แบบ explicit/idempotent |
| Device protocol | `control_protocol.py` | validate/normalize คำสั่ง Aircon และ Bed |
| Hardware contracts | `sensor_contracts.py` | sensor model, alias, physical range, frame/telemetry contract |
| Calibration | `sensor_calibration.py` | calibration spec, validation และ atomic JSON persistence |
| Sensor runtime | `sensor_runtime.py` | normalize Hub 1, compose Hub 1/2, stale/hold และ packet-level sound aggregation |
| Sensor transports | `zeep_pod/hardware/sensorhub1.py`, `sensorhub2.py` | USB/MQTT readers ที่รับ state และ callback จาก composition root |
| BCG transport | `zeep_pod/hardware/bcg.py` | LSM-800-T framing/reconnect และ live-state publication; `app.bcg_reader()` เป็น compatibility facade |
| Sensor-frame sampling | `zeep_pod/sessions/sensor_frame_sampler.py` | รวม BCG + canonical environment ตาม cadence 10 วินาที; ไม่ตัดสิน Sleep Stage |
| Live API projection | `zeep_pod/api_state_projection.py` | ประกอบ freshness/stale/fallback ของ Hub, BCG และ Control จาก detached snapshot โดยไม่แก้ live reader state |
| Control transports | `zeep_pod/hardware/controlhub1.py`, `controlhub2.py` | MQTT command/ACK ของแอร์และเตียง แยกจาก HTTP routes |
| Audio controls | `zeep_pod/hardware/audio.py`, `audio_api.py` | MPV/fallback player และนโยบาย HTTP ของเพลง/Brainwave ที่ทดสอบได้โดยไม่เปิด audio hardware |
| Shadow guidance | `smart_response.py` | ประเมินคำแนะนำสภาพแวดล้อมโดยไม่สั่งอุปกรณ์ |
| Adaptive learning monitor | `zeep_pod/adaptive_learning.py` | เทียบ Live กับ Baseline และรวม version/device intent ใน Shadow mode |
| Sleep evidence | `sleep_signal_features.py` | Movement, Bed Exit, Arousal, HR/RR และ waveform features |
| Sleep scoring | `sleep_stage_scoring.py` | หลักฐานและ probability ของ W/N1/N2/N3/REM |
| Sleep policy | `sleep_system_policy.py` | version, gate, confirmation, transition และ environment context |
| Personal baseline | `personal.py`, `zeep_pod/sessions/baseline_cache.py` | Adaptive baseline รายบุคคลแบบ versioned; derived cache โหลดใน lifespan |
| Historical replay | `zeep_pod/sessions/historical_replay_runtime.py`, `historical_replay_storage.py`, `historical_replay_audit.py`, `reclassify_sleep_history.py` | ใช้ policy/version เดียวกับ Live, อ่าน SQLite แบบ read-only และ audit โดยไม่ import FastAPI composition root |
| User learning profile | `zeep_pod/sessions/user_learning_profile.py` | รวมประวัติรายบัญชี แยก Observed/Trend/AI readiness และแยก Overnight/Nap |
| Personal behavior cohorts | `zeep_pod/sessions/personal_behaviour.py`, `user_baseline_context.py`, `user_score_history.py` | แยกสูตรและเป้าหมาย Overnight/Nap 30/Nap 90 ก่อนเทียบ Baseline หรือ trend |
| Advisory AI projection | `zeep_pod/sessions/user_ai_context.py`, `user_profile_api.py` | Positive allowlist ที่ตัด direct identifiers; ยังคงเป็น Personal Wellness Data และไม่สั่งอุปกรณ์ |
| Identity erasure | `zeep_pod/identity/account_erasure.py`, `account_erasure_api.py` | ลบ local active store ของ canonical account/aliases, Session, BCG, Baseline, checkpoint และ capability ที่ค้าง |
| Final report | `sleep_session_report.py` | Mode-aware Sleep Score/Recovery Score และรายงานหลังจบ Session |
| Account ingest outbox | `zeep_pod/sessions/ingest_payload.py`, `ingest_outbox.py` | สร้าง payload แบบ allowlist, เขียนคิว atomic และ retry โดยไม่ทำให้ Session finalization ล้ม |
| Atomic Session finalization | `zeep_pod/sessions/finalization_commit.py` | commit ผลที่สร้างแล้วลง DB, กู้ live Session เมื่อ persistence ล้ม และลบ checkpoint หลัง durable flush เท่านั้น |
| Storage | `database.py`, `bcg_storage.py`, `backup.py` | SQLite writer, raw BCG และ Daily backup |
| UI source | `static/index.template.html`, `static/partials/control/*`, `static/partials/app/*` | App shell, Control cards, Base CSS และ ordered JavaScript fragments |
| UI bundle | `ui_composer.py`, `static/index.html` | ประกอบและตรวจ runtime HTML โดยไม่ fetch partial ตอนใช้งาน |
| User History availability | `zeep_pod/sessions/history.py` | นับ Session จาก SQLite ที่จบแล้วและมี Timeline ให้ตรงกับรายการที่เปิดดูได้ |
| Wake lock-in QA | `audit_wake_lock_in.py`, `zeep_pod/sessions/wake_lock_audit.py` | Shadow audit แบบ read-only; ไม่แก้ State, Score หรือ Raw data |

## 2. Data flow ที่อนุญาต

```text
ESP32 Hub 1 (USB) ─┐
ESP32 Hub 2 (MQTT) ├─> transport reader ─> sensor_runtime ─> canonical state
LSM-800-T (USB) ───┘                                      │
                                                          ├─> Dashboard / API
                                                          ├─> Session samples
                                                          ├─> Safety Supervisor
                                                          └─> Shadow guidance

Browser command ─> Auth/RBAC/CSRF ─> control_protocol ─> hardware adapter
                                                     └─> ACK/event/session audit

Browser audio ───> Auth/RBAC/CSRF ─> audio_api ─> AudioPlayer ─> MPV/fallback

BCG + HR/RR + Bed ─> sleep_signal_features ─> sleep_stage_scoring
                   ─> sleep_system_policy ─> confirmed stage ─> final report
```

Dashboard, Session และ Safety ต้องอ่านค่าจาก **canonical environment snapshot**
เดียวกัน ห้ามแต่ละหน้าเลือก field alias หรือใส่ bias ของตนเอง

## 3. Invariants ที่ห้ามทำลาย

1. Raw Sensor/BCG ไม่ถูกแก้ย้อนหลังโดย calibration; เก็บ derived value แยกและมี provenance
2. ค่า Offline, Stale, Invalid หรือไม่มีคนบนเตียง ห้ามแทนเป็นศูนย์แล้วนำไปตัดสินใจ
3. ไม่มี HR/RR และไม่มีผู้ใช้งานบนเตียง ห้ามตอบ N1/N2/N3/REM
4. Sleep Stage เป็น health telemetry ไม่ใช่คำสั่ง Aircon, Bed, Door, Light, Aroma หรือ Audio
5. Shadow Response ไม่มีสิทธิ์เรียก GPIO/MQTT/device controller
6. คำสั่งอุปกรณ์ทุกคำสั่งต้องผ่าน Auth/RBAC/CSRF, validation, timeout และ event audit
7. Bed movement เป็น bounded one-shot และ Pi ต้องส่ง Stop แม้ browser หลุด
8. การ Restart/Deploy ห้ามสร้าง Logout หรือจบ Session; ต้อง restore atomic checkpoint
9. Public endpoint และ JSON key เดิมยังคงใช้ได้จนมี versioned migration plan
10. หนึ่งค่าจริงต่อ metric: UI ห้ามคำนวณ Sensor/Sleep score ซ้ำจาก Backend
11. Adaptive Learning ต้องคง `automatic_actuation=false` จนผ่าน Gate และ Safety review
12. User learning ห้ามตีความความถี่เป็นความชอบ หรือสภาพแวดล้อมที่พบเป็นค่าที่ผู้ใช้เลือก
13. Baseline/trend ต้องตรงทั้ง mode, target, behavior policy และ score formula
14. AI รับได้เฉพาะ validated `user_ai_context.data` หลังมี purpose-specific
    authorization; ห้ามรับ Profile, event-level data หรือถือว่าข้อมูลนี้ anonymous

## 3.1 Dependency และขนาด Code

- `app.py` import domain/hardware modules ได้ แต่ module ภายใต้ `zeep_pod/`
  ห้าม import `app.py`
- Pure helper ห้ามเปิดไฟล์, Serial, MQTT, GPIO หรือ database ตอน import
- Resource ที่ย้ายแล้ว ได้แก่ Database, Auth, Occupancy, Personal Baseline และ GPIO
  ใช้ constructor ที่ไม่เปิด I/O แล้ว initialize ใน Production lifespan ตามลำดับ
  Database → Auth → Occupancy → Baseline → GPIO; Music/Aircon/Audio ยังเป็นงานถัดไป
- Module ใหม่ภายใต้ `zeep_pod/` ไม่เกิน 500 บรรทัด
- Function/method ใหม่ไม่เกิน 90 บรรทัด
- Public boundary และ safety decision ต้องมี type hints และ docstring
- การย้าย behavior ต้องคง compatibility facade จน caller และเครื่องมือย้อนหลัง
  ย้ายครบ

ข้อจำกัดเหล่านี้ตรวจโดย `test_modular_architecture.py` และ CI

## 4. วิธีเพิ่มหรือแก้ความสามารถ

### Sensor/calibration

1. เพิ่ม datasheet/range/alias ใน `sensor_contracts.py`
2. เพิ่ม parameter ที่ปรับได้ใน `sensor_calibration.py` เฉพาะเมื่อมีวิธีอ้างอิง
3. normalize/compose ใน `sensor_runtime.py`
4. เพิ่ม pure unit test ก่อน wire transport ใน `app.py`
5. แสดง Raw → Parameter → Derived พร้อม unit/provenance ใน Admin เท่านั้น

### คำสั่งอุปกรณ์

1. เพิ่ม allowlist/normalization ใน `control_protocol.py`
2. transport adapter รับเฉพาะ normalized command
3. ระบุ ACK ว่าคือ “ส่งคำสั่งแล้ว” หรือ “ยืนยันสถานะกายภาพแล้ว” ให้ชัด
4. เพิ่ม timeout, safe state และ regression test
5. User เห็นเฉพาะ control ที่เชื่อถือได้; diagnostic/reference อยู่ Admin

### Sleep/Wellness

1. สกัด feature ใน `sleep_signal_features.py`
2. ให้คะแนนหลักฐานใน `sleep_stage_scoring.py`
3. gate/transition/confirmation อยู่ใน `sleep_system_policy.py` แห่งเดียว
4. Live และ replay ต้องใช้ scorer/policy เดียวกัน
5. เปลี่ยนเวอร์ชันทุกครั้งที่นิยาม derived result เปลี่ยน
6. คะแนนเป็น Sleep Wellness estimate ไม่ใช่ AASM/PSG diagnosis

### Control UI

แก้ source ที่ `static/index.template.html`, `static/partials/control/*.html` หรือ
`static/partials/app/*` แล้วรัน `python ui_composer.py build` ห้ามแก้เฉพาะ
`static/index.html` เพราะ runtime bundle จะไม่ตรงกับ source ลำดับ JavaScript ใน
`ui_composer.SCRIPT_PARTIALS` และลำดับ CSS cascade เป็น runtime contract

## 5. Definition of done

```bash
git pull --ff-only origin develop
python quality_gate.py changed
git diff --check
```

ใช้ `python quality_gate.py full` เฉพาะงานข้ามระบบ ผลไม่แน่นอน Release candidate
หรือเมื่อ CI ของ Git SHA ที่จะ Deploy ไม่พร้อมใช้งาน

ก่อน restart production ให้บันทึกสถานะ service และ Active Session หลัง restart ต้อง
ตรวจ `systemctl`, `/api/public/status`, Sensor/Hub/BCG connectivity, Safety faults
และ event `SESSION resumed_after_restart` หากมี Session ค้างอยู่

## 6. สถานะ Refactor และลำดับถัดไป

Onboarding ใช้เอกสารนี้เป็น Roadmap ทางเทคนิคเพียงฉบับเดียว เพื่อลดเอกสารซ้ำและ
ไม่ให้สถานะ Release กับ Working candidate ปะปนกัน

### 6.1 สิ่งที่อยู่บน `origin/develop`

สถานะในตารางนี้ตรวจจาก source ใน `origin/develop`; Git SHA ที่ deploy จริงให้ตรวจ
จาก health/version response และ closure record ของ release นั้น:

| ระยะ | สถานะ | Boundary ที่แยกแล้ว |
|---|---|---|
| R0 | เสร็จแล้ว | Characterization และ architecture ratchet |
| R1 | เสร็จแล้ว | Live state projection |
| R2 | เสร็จแล้ว | BCG framing, reconnect และ publication |
| R3 | เสร็จแล้ว | Canonical Sensor frame ทุก 10 วินาที |
| R4a | เสร็จแล้ว | Atomic finalization commit และ recovery order |

รอบนี้ลด `app.py` จาก 8,270 เหลือ 8,025 บรรทัด, ลด `snapshot()` จาก 169
เหลือ 118 บรรทัด และย้าย BCG reader, Sensor sampler กับ finalization ไปยัง module
ที่ทดสอบแยกได้ โดยยังคง facade เดิมไว้ชั่วคราว ไม่เปลี่ยน Sleep/Score formula,
Sensor cadence, public JSON key หรือคำสั่ง Hardware

### 6.2 Working candidate ที่ยังไม่ใช่ Release fact

- Constructor ของ Database, Auth, Occupancy, Personal Baseline และ GPIO ไม่ควรเปิด
  I/O ตอน import; Production initialize ตามลำดับ
  Database → Auth → Occupancy → Baseline → GPIO
- Historical replay อ่าน SQLite แบบ read-only ผ่าน storage boundary และไม่ import
  FastAPI composition root
- Guarded lazy initialization มีไว้เพื่อ compatibility ของ direct caller/test เดิม;
  Production ใช้ explicit lifespan initialization
- Candidate ต้องผ่าน Review และ Release gate ก่อนจึงเขียนสถานะเป็น “เสร็จแล้ว”

### 6.3 ลำดับถัดไป

1. ปิด import side effects ของ Music, Aircon reference และ Audio discovery พร้อม
   lifecycle rollback/thread registry ที่ deterministic
2. แยก Session lifecycle: waiting-bed, vital gate, start, resume, finalize และ
   checkpoint orchestration โดยรักษา Restart continuity
3. ทำ Sleep estimator facade ให้รับ typed input แล้ว delegate ไปยัง feature,
   scorer และ policy เดิม พร้อม golden replay; ห้ามเปลี่ยน threshold ใน change นี้
4. รวม report pipeline ที่ซ้ำระหว่าง Live, Replay, Rescore และ Trim ให้ใช้ contract เดียว
5. แบ่ง FastAPI router ตาม auth, control, session และ admin/monitor
6. ลด `app.py` ให้เหลือ configuration, dependency wiring, lifespan และ router wiring

Acoustic Intelligence ที่เสนอใน
[DSP Plan](onboarding/smart-ear-dsp-plan.md) มี `zeep_pod/acoustics/` เฉพาะ P0.5
contract และ Admin level-only projection แล้ว ส่วน feature parser, classifier,
event tracker และ persistence ยังเป็น ROADMAP และห้ามเพิ่มก่อนผ่าน Gate ที่กำหนด

แต่ละขั้นต้องเป็น behavior-preserving commit ขนาดเล็กที่ย้อนกลับได้ ห้ามรวมการจูน
Health threshold, เปลี่ยน Schema หรือ Flash Firmware ไว้ใน Refactor commit เดียวกัน
และต้องผ่าน focused test ก่อน Full release gate ตาม [TESTING.md](../TESTING.md)

Transport, ownership และ failure behavior ของอุปกรณ์อยู่ที่
[Hardware and Hub Map](onboarding/hardware-hub-map.md)
