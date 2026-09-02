# ZEEP Pi5 Software Architecture

สถานะ: **Current implementation**  
ขอบเขต: `/home/pod1/pi5` · branch `origin/develop`

เอกสารนี้เป็นแผนที่กลางสำหรับพัฒนาและตรวจสอบ Pi5 runtime ของ ZEEP ทุกตู้
เป้าหมายคือให้แก้แต่ละส่วนได้โดยไม่ทำให้ Sensor, Session, Safety และอุปกรณ์
ควบคุมกระทบกันโดยไม่ตั้งใจ

## 1. หลักการแบ่งระบบ

`app.py` เป็น **composition root**: สร้าง FastAPI app, ต่อ lifecycle thread,
ประกอบ state และเรียก hardware adapters เท่านั้น กฎที่คำนวณได้แบบ deterministic
ต้องแยกเป็น pure module เพื่อให้ทดสอบได้โดยไม่เปิด GPIO, Serial, MQTT หรือเสียง

| Layer | Source of truth | หน้าที่ |
|---|---|---|
| HTTP contracts | `api_models.py`, `api_v1.py` | รูปแบบ request/response และ versioned envelope |
| Authentication | `access_control.py`, `admin_accounts.py` | Browser session, RBAC, CSRF และ Admin identity |
| Occupancy | `pod_occupancy.py` | หนึ่งผู้ใช้ต่อหนึ่งตู้และป้องกัน login ซ้ำหลายตู้ |
| Device protocol | `control_protocol.py` | validate/normalize คำสั่ง Aircon และ Bed |
| Hardware contracts | `sensor_contracts.py` | sensor model, alias, physical range, frame/telemetry contract |
| Calibration | `sensor_calibration.py` | calibration spec, validation และ atomic JSON persistence |
| Sensor runtime | `sensor_runtime.py` | normalize Hub 1, compose Hub 1/2, stale/hold และ Sound Leq |
| Shadow guidance | `smart_response.py` | ประเมินคำแนะนำสภาพแวดล้อมโดยไม่สั่งอุปกรณ์ |
| Sleep evidence | `sleep_signal_features.py` | Movement, Bed Exit, Arousal, HR/RR และ waveform features |
| Sleep scoring | `sleep_stage_scoring.py` | หลักฐานและ probability ของ W/N1/N2/N3/REM |
| Sleep policy | `sleep_system_policy.py` | version, gate, confirmation, transition และ environment context |
| Personal baseline | `personal.py` | Adaptive baseline รายบุคคลแบบ versioned |
| Final report | `sleep_session_report.py` | Mode-aware Sleep/Rest score และรายงานหลังจบ Session |
| Storage | `database.py`, `bcg_storage.py`, `backup.py` | SQLite writer, raw BCG และ Daily backup |
| UI source | `static/index.template.html`, `static/partials/control/*` | App shell และการ์ดควบคุมที่แก้ไขได้ |
| UI bundle | `ui_composer.py`, `static/index.html` | ประกอบและตรวจ runtime HTML โดยไม่ fetch partial ตอนใช้งาน |

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

แก้ source ที่ `static/index.template.html` และ
`static/partials/control/*.html` แล้วรัน `python ui_composer.py build` ห้ามแก้เฉพาะ
`static/index.html` เพราะ runtime bundle จะไม่ตรงกับ source

## 5. Definition of done

```bash
git pull --ff-only origin develop
python -m unittest discover -p 'test_*.py'
python ui_composer.py check
python -m py_compile app.py *.py
git diff --check
```

ก่อน restart production ให้บันทึกสถานะ service และ Active Session หลัง restart ต้อง
ตรวจ `systemctl`, `/api/public/status`, Sensor/Hub/BCG connectivity, Safety faults
และ event `SESSION resumed_after_restart` หากมี Session ค้างอยู่

## 6. งานแยกต่อไปแบบลดความเสี่ยง

ลำดับ refactor ถัดไปควรเป็น:

1. แยก GPIO, Audio, Serial และ MQTT เป็น hardware adapters
2. แยก Session lifecycle/checkpoint/sampler เป็น `SessionCoordinator`
3. แบ่ง FastAPI routes ตาม domain: auth, control, session, admin/monitor
4. แยก browser JavaScript/CSS ตาม feature โดยคง bundle เดียวสำหรับ offline runtime

แต่ละขั้นต้องเป็น behavior-preserving commit ขนาดเล็กและผ่าน regression ก่อนเริ่ม
ขั้นถัดไป ห้ามรวมการเปลี่ยนสูตรสุขภาพหรือ hardware behavior ไว้ใน refactor commit
