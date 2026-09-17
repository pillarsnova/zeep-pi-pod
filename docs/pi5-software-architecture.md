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
| HTTP contracts | `api/models.py`, `responses.py`, `v1.py`, `history.py` | รูปแบบ request/response, versioned envelope และ route factories; ไฟล์ชื่อเดิมที่ root เป็น compatibility facade เท่านั้น |
| Shared pure values | `common/mappings.py`, `numbers.py` | แปลง Mapping/ตัวเลขด้วย semantics เดียว ลด helper ซ้ำโดยไม่ parse string หรือเปิด I/O |
| Authentication | `access_control.py`, `admin_accounts.py` | Browser session, RBAC, CSRF และ Admin identity; Production เตรียม schema/config ใน lifespan และ direct caller มี guarded lazy fallback |
| ZEEP account binding | `identity/zeep_account.py` | ผูก `{tokens, user}` จาก Password/QR login เข้ากับตัวตนในตู้ |
| QR login | `qr_login.py` | Pi ทำ handshake แทนแท็บเล็ต และถือ `pollSecret` ไว้เอง |
| Occupancy | `pod_occupancy.py` | หนึ่งผู้ใช้ต่อหนึ่งตู้และป้องกัน login ซ้ำหลายตู้; lease store initialize แบบ explicit/idempotent |
| Device protocol | `control_protocol.py` | validate/normalize คำสั่ง Aircon และ Bed |
| Hardware contracts | `sensors/contracts.py`, `catalog.py`, `constants.py`, `bcg.py` | แยก wire contract, device catalog/range, shared constants และ byte parser |
| Calibration | `sensors/calibration.py` | calibration spec, validation และ atomic JSON persistence |
| Sensor runtime | `sensors/environment.py`, `normalization.py`, `sound.py` | แยก compose Hub 1/2, normalize direct sound และ packet-level sound aggregation; `runtime.py` เป็น stable package facade |
| Sensor transports | `hardware/sensorhub1.py`, `sensorhub2.py` | USB/MQTT readers ที่รับ state และ callback จาก composition root |
| BCG transport | `hardware/bcg.py`, `sensors/bcg.py` | LSM-800-T framing/reconnect, byte parser และ live-state publication; `app.bcg_reader()` เป็น compatibility facade |
| Sensor-frame sampling | `sessions/sensor_frame_sampler.py` | รวม BCG + canonical environment ตาม cadence 10 วินาที; ไม่ตัดสิน Sleep Stage |
| Live Session projection | `sessions/live_projection.py` | Contract และ pure builders ของสถานะ Session 20 fields; Login, Restart และ Finalize ใช้ shape เดียวกัน |
| Live API projection | `api/state_projection.py` | ประกอบ freshness/stale/fallback ของ Hub, BCG และ Control จาก detached snapshot โดยไม่แก้ live reader state |
| Control transports | `hardware/controlhub1.py`, `controlhub2.py` | MQTT command/ACK ของแอร์และเตียง แยกจาก HTTP routes |
| Control intent persistence | `hardware/aircon_reference.py` | Repository เก็บค่าอ้างอิงพัดลม 1–5 แบบ atomic; constructor ไม่เปิดไฟล์และ initialize ใน lifespan |
| Audio controls | `hardware/audio_library.py`, `audio_runtime.py`, `audio_process.py`, `audio_watchers.py`, `audio.py`, `audio_api.py` | Pure defaults/listing, runtime contract, subprocess/IPC adapter, watcher registry, player facade และ HTTP policy โดยไม่มี I/O ตอน import |
| Shadow guidance | `smart_response.py` | ประเมินคำแนะนำสภาพแวดล้อมโดยไม่สั่งอุปกรณ์ |
| Adaptive learning monitor | `adaptive/learning.py`, `adaptive/features.py` | เทียบ Live กับ Baseline และรวม version/device intent ใน Shadow mode |
| Sleep evidence | `sleep_signal_features.py` | Movement, Bed Exit, Arousal, HR/RR และ waveform features |
| Sleep scoring | `sleep_stage_scoring.py` | หลักฐานและ probability ของ W/N1/N2/N3/REM |
| Sleep policy | `sleep_system_policy.py` | version, gate, confirmation, transition และ environment context |
| Personal baseline | `personal.py`, `sessions/baseline_cache.py` | Adaptive baseline รายบุคคลแบบ versioned; derived cache โหลดใน lifespan |
| Historical replay | `sessions/historical_replay_runtime.py`, `historical_replay_storage.py`, `historical_replay_audit.py`, `reclassify_sleep_history.py` | ใช้ policy/version เดียวกับ Live, อ่าน SQLite แบบ read-only และ audit โดยไม่ import FastAPI composition root |
| User learning profile | `sessions/user_learning_profile.py` | รวมประวัติรายบัญชี แยก Observed/Trend/AI readiness และแยก Overnight/Nap |
| Personal behavior cohorts | `sessions/personal_behaviour.py`, `user_baseline_context.py`, `user_score_history.py` | แยกสูตรและเป้าหมาย Overnight/Nap 30/Nap 90 ก่อนเทียบ Baseline หรือ trend |
| Advisory AI projection | `sessions/user_ai_context.py`, `user_profile_api.py` | Positive allowlist ที่ตัด direct identifiers; ยังคงเป็น Personal Wellness Data และไม่สั่งอุปกรณ์ |
| Identity erasure | `identity/account_erasure.py`, `account_erasure_api.py` | ลบ local active store ของ canonical account/aliases, Session, BCG, Baseline, checkpoint และ capability ที่ค้าง |
| Final report | `sleep_session_report.py` | Mode-aware Sleep Score/Recovery Score และรายงานหลังจบ Session |
| Account ingest outbox | `sessions/ingest_payload.py`, `ingest_outbox.py` | สร้าง payload แบบ allowlist, เขียนคิว atomic และ retry โดยไม่ทำให้ Session finalization ล้ม |
| Atomic Session finalization | `sessions/finalization_commit.py` | commit ผลที่สร้างแล้วลง DB, กู้ live Session เมื่อ persistence ล้ม และลบ checkpoint หลัง durable flush เท่านั้น |
| Storage | `database.py`, `bcg_storage.py`, `backup.py` | SQLite writer, raw BCG และ Daily backup |
| UI source | `static/index.template.html`, `static/partials/control/*`, `static/partials/app/*` | App shell, Control cards, Base CSS และ ordered JavaScript fragments |
| UI bundle | `ui_composer.py`, `static/index.html` | ประกอบและตรวจ runtime HTML โดยไม่ fetch partial ตอนใช้งาน |
| User History availability | `sessions/history.py` | นับ Session จาก SQLite ที่จบแล้วและมี Timeline ให้ตรงกับรายการที่เปิดดูได้ |
| Wake lock-in QA | `audit_wake_lock_in.py`, `sessions/wake_lock_audit.py` | Shadow audit แบบ read-only; ไม่แก้ State, Score หรือ Raw data |

## 2. Data flow ที่อนุญาต

```text
ESP32 Hub 1 (USB) ─┐
ESP32 Hub 2 (MQTT) ├─> transport reader ─> sensors ─> canonical state
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

- `app.py` import domain/hardware modules ได้ แต่ module ภายใต้ top-level domain packages
  ห้าม import `app.py`
- Pure helper ห้ามเปิดไฟล์, Serial, MQTT, GPIO หรือ database ตอน import
- Resource ที่ย้ายแล้ว ได้แก่ Database, Auth, Occupancy, Personal Baseline และ GPIO
  ใช้ constructor ที่ไม่เปิด I/O แล้ว initialize ใน Production lifespan ตามลำดับ
  Database → Auth → Occupancy → Baseline → Aircon reference → GPIO → Audio
- Module ใหม่ภายใต้ top-level domain packages ไม่เกิน 500 บรรทัด
- Function/method ใหม่ไม่เกิน 90 บรรทัด
- Public boundary และ safety decision ต้องมี type hints และ docstring
- การย้าย behavior ต้องคง compatibility facade จน caller และเครื่องมือย้อนหลัง
  ย้ายครบ

ข้อจำกัดเหล่านี้ตรวจโดย `test_modular_architecture.py` และ CI

## 4. วิธีเพิ่มหรือแก้ความสามารถ

### Sensor/calibration

1. เพิ่ม device metadata/datasheet/range ใน `sensors/catalog.py`; แก้ wire schema ใน `contracts.py` เฉพาะเมื่อ transport contract เปลี่ยน
2. เพิ่ม parameter ใน `sensors/calibration.py` เฉพาะเมื่อมีวิธีอ้างอิง
3. normalize ใน `normalization.py`, compose ใน `environment.py` และสรุปเสียงใน `sound.py`
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
จาก `git rev-parse HEAD` บน Pod และ closure record ของ release นั้น:

| ระยะ | สถานะ | Boundary ที่แยกแล้ว |
|---|---|---|
| R0 | เสร็จแล้ว | Characterization และ architecture ratchet |
| R1 | เสร็จแล้ว | Live state projection |
| R2 | เสร็จแล้ว | BCG framing, reconnect และ publication |
| R3 | เสร็จแล้ว | Canonical Sensor frame ทุก 10 วินาที |
| R4a | เสร็จแล้ว | Atomic finalization commit และ recovery order |
| R5 | เสร็จแล้ว | API package, response envelope และ thin compatibility facades |
| R6 | เสร็จแล้ว | Sensor package แยก contract/catalog/constants/BCG/calibration/environment/normalization/sound และ shared value library |
| R7a | เสร็จแล้ว | Aircon fan-reference ใช้ Repository + explicit lifespan initialization; import `app.py` ไม่อ่านหรือเขียนไฟล์ reference |
| R7b | เสร็จแล้ว | Live Session ใช้ typed Contract + pure projection module + app Adapter/Facade; Restart รักษา Wellness context และ Logout ล้าง Personal context ครบ |
| R7c | เสร็จแล้ว | Audio ใช้ pure Library + typed runtime Contract + system/process Adapter + lifecycle Facade; import ไม่ค้นหา player/ALSA หรือสร้าง music directory และ shutdown drain watcher แบบ bounded |

`app.py` คงอยู่ที่ไม่เกิน 7,995 บรรทัด และเป็น composition root ต่อไป ส่วน API,
Sensor contract/calibration/normalization/environment/sound และ value helpers อยู่ใน
package ตามโดเมนแล้ว ไฟล์ชื่อเดิมที่ root เหลือเป็น facade บางเพื่อรักษา script/test
เดิม การย้ายนี้ไม่เปลี่ยน Sleep/Score formula, Sensor cadence, ชื่อ public JSON key
หรือคำสั่ง Hardware แต่ทำให้ Live Session shape ครบ 20 fields ในทุก phase

Live Session boundary ใช้รูปแบบเดียวกันตลอดระบบ:

- **Contract** — `LiveSessionProjection`, `VitalGateProjection` และ
  `SessionPublicIdentity` กำหนดข้อมูลที่อนุญาต
- **Module/Library** — pure builders สร้าง active/inactive state โดยไม่อ่าน Database,
  Profile, Clock หรือ Hardware
- **Adapter** — composition root แปลง Profile, Checkpoint และ Personal Baseline เป็น
  input ของ builder
- **Facade** — `_replace_session_projection_locked()` และ
  `_patch_session_projection_locked()` เป็นทางเขียน live state เพียงจุดเดียว โดยรักษา
  object identity และลำดับ lock เดิม

Audio boundary ใช้รูปแบบเดียวกันโดยไม่เปลี่ยนนโยบายเล่นเพลงเดิม:

- **Contract** — `AudioRuntimeSelection` และ `AudioRuntimeDiscovery` ระบุผล discovery
  ที่ player ยอมรับ
- **Module/Library** — `select_audio_runtime()`, music defaults และ contained listing
  แยกจาก subprocess และ FastAPI
- **Adapter** — `SystemAudioRuntimeAdapter` อ่าน executable, environment และ ALSA
  เฉพาะเมื่อ lifespan เริ่ม; `AudioProcessAdapter` แปลง intent เป็น MPV/fallback
  subprocess และ Unix-socket IPC
- **Facade** — `AudioPlayer` serialize play กับ shutdown และใช้ watcher registry
  เพื่อ teardown แบบมีเวลาสิ้นสุด

### 6.2 Working candidate ที่ยังไม่ใช่ Release fact

- Constructor ของ Database, Auth, Occupancy, Personal Baseline, GPIO และ Audio ไม่เปิด
  I/O ตอน import; Production initialize ตามลำดับที่ระบุใน §3.1
- Historical replay อ่าน SQLite แบบ read-only ผ่าน storage boundary และไม่ import
  FastAPI composition root
- Guarded lazy initialization มีไว้เพื่อ compatibility ของ direct caller/test เดิม;
  Production ใช้ explicit lifespan initialization
- Candidate ต้องผ่าน Review และ Release gate ก่อนจึงเขียนสถานะเป็น “เสร็จแล้ว”

### 6.3 ลำดับถัดไป

1. แยก Session lifecycle orchestration แบบทีละช่วง โดยเริ่ม waiting-bed → recording
   start; คง DB durability, gate recheck และ checkpoint ordering เดิม
2. จากนั้นจึงแยก resume และ finalize ออกจาก composition root โดยใช้ Live Session
   contract ที่แยกแล้วและรักษา Restart continuity
3. ทำ Sleep estimator facade ให้รับ typed input แล้ว delegate ไปยัง feature,
   scorer และ policy เดิม พร้อม golden replay; ห้ามเปลี่ยน threshold ใน change นี้
4. รวม report pipeline ที่ซ้ำระหว่าง Live, Replay, Rescore และ Trim ให้ใช้ contract เดียว
5. แบ่ง FastAPI router ที่ยังอยู่ใน `app.py` ตาม auth, control, session และ admin/monitor
6. ลด `app.py` ให้เหลือ configuration, dependency wiring, lifespan และ router wiring

Acoustic Intelligence ที่เสนอใน
[DSP Plan](onboarding/smart-ear-dsp-plan.md) มี `acoustics/` รุ่น P0.6
contract และ Admin level-only projection แล้ว ส่วน feature parser, classifier,
event tracker และ persistence ยังเป็น ROADMAP และห้ามเพิ่มก่อนผ่าน Gate ที่กำหนด

แต่ละขั้นต้องเป็น behavior-preserving commit ขนาดเล็กที่ย้อนกลับได้ ห้ามรวมการจูน
Health threshold, เปลี่ยน Schema หรือ Flash Firmware ไว้ใน Refactor commit เดียวกัน
และต้องผ่าน focused test ก่อน Full release gate ตาม [TESTING.md](../TESTING.md)

Transport, ownership และ failure behavior ของอุปกรณ์อยู่ที่
[Hardware and Hub Map](onboarding/hardware-hub-map.md)
