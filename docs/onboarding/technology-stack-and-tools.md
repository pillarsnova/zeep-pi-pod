# ZEEP v1 — Technology Stack, Data และเครื่องมือ

สถานะ: **Current implementation · Internal Pilot / freeze candidate**

ขอบเขต: Pi 5 runtime, Web UI, local data, device integration, QA และ Operations

ปรับปรุงล่าสุด: 17 กันยายน 2026

เอกสารนี้ตอบคำถามว่า “ระบบปัจจุบันสร้างด้วยอะไร ข้อมูลอยู่ที่ไหน และควรใช้
เครื่องมือใดตรวจแต่ละชั้น” โดยสรุปจาก source ที่ทำงานจริง ไม่รวมเทคโนโลยีของ
Account backend ซึ่งอยู่นอก repository นี้

## สรุปหนึ่งหน้า

| ชั้นระบบ | เทคโนโลยีที่ใช้จริง | หน้าที่ |
|---|---|---|
| Edge computer | Raspberry Pi 5, Linux, `systemd` | รัน Backend, UI, Session, Sensor/Control workers และ local storage |
| Runtime | Python 3.11+; CI/Ruff target **3.11** | Logic, API, hardware adapter, report และ maintenance tools |
| Backend/API | FastAPI, Uvicorn, Pydantic บน typed domain APIs, HTTP/REST, WebSocket, `httpx` | Browser/API, validation, auth, live state และ ZEEP account integration |
| Frontend | Vanilla HTML/CSS/JavaScript, inline SVG, Canvas | Dashboard, Control, Monitor และประวัติการใช้งาน |
| UI build | `ui_composer.py` | รวม template/partials เป็น `static/index.html`; ไม่มี Node/npm bundler |
| Database | SQLite WAL; ไม่มี ORM | Session/Timeline/Event, Raw BCG, Auth และ Pod occupancy |
| Sidecar storage | JSON/JSONL และ durable filesystem outbox | Profile, Baseline, checkpoint, device state, audit และ retry |
| Hardware I/O | USB Serial JSONL/Binary, MQTT, BCM GPIO, MPV IPC | Sensor Hub, BCG, Control Hub, relay/driver และเสียงออกลำโพง |
| Acoustic DSP shadow | ESP32-S3 FFT/features + Pi contract/timeline | ส่งเฉพาะ provisional label/confidence/feature summary; ไม่ส่ง Raw audio |
| QA | `unittest`, `quality_gate.py`, Ruff, JSON Schema, `ui_composer.py check` | Focused regression, style, contract/evidence และ generated UI |
| Delivery/Ops | Git/GitHub `origin/develop`, GitHub Actions, SSH/Tailscale, `systemd` | Review, CI, deploy, remote operation และ recovery |

Python 3.11+ เป็น source compatibility standard และ CI/Ruff ใช้ 3.11 แต่ service
เรียก interpreter จาก `.venv` โดยไม่ได้ pin minor ใน unit file ก่อนวิเคราะห์ปัญหา
บน Pod จึงต้องตรวจ interpreter, Git SHA และ effective environment จริงเสมอ

## ภาพรวมการประกอบระบบ

```text
Sensors / Control devices
   │ USB Serial · MQTT · GPIO · MPV IPC
   ▼
Python adapters and device contracts
   ▼
Canonical in-process state ──> 10-second analysis frame
   │                              │
   ├──> FastAPI REST/WebSocket ───┼──> Browser UI / App API
   ├──> Session lifecycle         ├──> Sleep/Recovery derived result
   ├──> Safety and audit          └──> Shadow recommendation
   └──> SQLite / JSON / outbox
```

`app.py` ยังเป็น legacy composition root และ compatibility facade บางส่วน
โค้ดใหม่ควรอยู่ใน top-level domain packages ตาม
[Pi 5 Software Architecture](../pi5-software-architecture.md) แทนการขยายไฟล์กลาง

โครงสร้างหลักที่ใช้พัฒนาต่อคือ `api/` สำหรับ HTTP contract/router,
`sensors/` สำหรับ contract/calibration/normalization/environment,
`common/` สำหรับ pure helper ที่ใช้ซ้ำ, `hardware/` สำหรับ
transport และ `sessions/` สำหรับ lifecycle/result ของการพัก ไฟล์ API และ
Sensor ชื่อเดิมที่ root เป็น compatibility facade และห้ามใส่ business logic ใหม่

## Backend และ Frontend

### Backend

- FastAPI เป็น HTTP/WebSocket application และ Uvicorn เป็น ASGI server
- Pydantic models เป็น schema boundary ของ typed Usage/Profile/Erasure routes;
  control-plane v1 บาง route ยังคืน manual envelope และอาศัย OpenAPI inference
- Hardware readers และงาน background บางส่วนใช้ thread, lock และ bounded queue
- `httpx` ใช้เชื่อม ZEEP account API; default ปัจจุบันคือ
  `https://api.zeep.world/api`
- `segno` ใช้สร้าง QR สำหรับ report share; QR login แสดง `qrCode` ที่ ZEEP account
  API ส่งกลับมา
- ไม่มี ORM, Redis หรือ Celery/job queue ใน Pi runtime; local MQTT broker ใช้เป็น
  device transport ไม่ใช่ application work queue

Python runtime dependency ให้ยึดช่วง version จาก
[`requirements.txt`](../../requirements.txt); Dev/CI ใช้
[`requirements-dev.txt`](../../requirements-dev.txt) ส่วน Mosquitto/MQTT broker,
MPV, ALSA และ `lgpio` เป็น OS/deployment dependency ที่ต้องตรวจบน Pod แยกต่างหาก
ปัจจุบันไม่มี lockfile จึงต้องบันทึก package set ของ release จริง ห้ามเดา version
จากเครื่องพัฒนา

### Frontend

- ใช้ HTML/CSS/JavaScript แบบ browser-native; ไม่มี React, Vue หรือ Node runtime
- แก้ source ที่ `static/index.template.html` และ `static/partials/`
- `ui_composer.py build` สร้าง `static/index.html` สำหรับ runtime
- ห้ามแก้ generated `static/index.html` เพียงไฟล์เดียว เพราะ build ครั้งถัดไปจะทับ
- Fetch ใช้กับ REST และ WebSocket ใช้รับ live state; UI ต้องแสดง canonical value
  จาก Backend และไม่คำนวณ Sensor, Sleep State หรือคะแนนขึ้นใหม่เอง

## Database และ Storage

### SQLite ที่ทำงานจริงบน Pod

| ไฟล์ | เนื้อหา | ข้อควรจำ |
|---|---|---|
| `data/sessions.db` | Session, Timeline และ Event | ใช้ foreign key, WAL, busy timeout และ background writer queue |
| `data/bcg.db` | Raw BCG epochs/packets ระหว่าง Recording | อยู่ใน Admin/research boundary; ไม่ออก Usage API |
| `data/auth.db` | Browser auth session แบบเก็บ token hash | แยกจาก Pod Session และ occupancy |
| `data/occupancy.db` | Pod/account lease พร้อม TTL | ป้องกันการครอบครองซ้ำ; ไม่ใช่ประวัติการนอน |

ระบบไม่มี PostgreSQL หรือ Cloud database ใน Pi runtime การเชื่อม Account backend
เป็น API flow แยกต่างหาก และไม่เปลี่ยน SQLite บน Pod ให้เป็น cache ของ Cloud

### JSON, JSONL และ filesystem state

| ตำแหน่ง | ใช้สำหรับ |
|---|---|
| `data/profiles.json` | Profile และ identity compatibility cache |
| `data/baselines.json` | Personal baseline ที่แยกตามผู้ใช้/โหมด/สูตร |
| `data/active_session_checkpoint.json` | คืน Active Session หลัง process restart |
| `data/last_sensor_frame.json` | แสดงค่าล่าสุดเป็น stale ระหว่างรอ packet ใหม่หลัง restart |
| `data/output_labels.json` | label ของ output/control |
| `data/aircon_control_state.json` | command/reference state ของแอร์ |
| `data/ingest_outbox/` | durable retry ของ finalized-session ingest |
| `logs/events.jsonl` | operational/event audit |
| `calibration.json` | contract/provenance การแปลง Sensor; ไม่ใช้แก้ Raw ย้อนหลัง |

`data/sessions.jsonl` เป็น legacy migration input ไม่ใช่ฐานหลักของ Session ใหม่
ข้อมูลจริง, backup, snapshot, token และ `.env` อยู่นอก Git และห้ามนำไปใช้เป็น
test fixture

### ข้อมูลใน memory

Latest device state, bounded Sensor windows, short-lived capability และ live
analysis อยู่ใน process memory บางส่วน สิ่งเหล่านี้ไม่ใช่ข้อมูลถาวร เว้นแต่มี
checkpoint/store ระบุไว้ชัด การ debug จึงต้องแยก “state ที่เห็นตอนนี้” ออกจาก
“หลักฐานที่บันทึกแล้ว” เสมอ

## Protocol และอุปกรณ์

| เส้นทาง | Protocol ปัจจุบัน | จุดเริ่มตรวจ |
|---|---|---|
| Sensor Hub 1 | USB Serial JSONL, default `/dev/ttyACM0`, 115200 | `hardware/sensorhub1.py` |
| Sensor Hub 2 | MQTT JSON ผ่าน local broker | `hardware/sensorhub2.py` |
| BCG LSM-800-T | USB Serial binary 66-byte frame, default 115200 | `hardware/bcg.py` |
| Control Hub 1 | MQTT command/status/event → IR แอร์ | `hardware/controlhub1.py` |
| Control Hub 2 | MQTT command/status/event → servo รีโมตเตียง | `hardware/controlhub2.py` |
| Door/light/aroma/steam | BCM GPIO ผ่าน `gpiozero`/`lgpio` | `hardware/gpio.py` |
| Audio output | MPV IPC ผ่าน Unix socket; fallback สำหรับ development | `hardware/audio.py` |

รายละเอียด field, ownership, freshness และ failure behavior อยู่ที่
[Hardware และ Hub map](hardware-hub-map.md) และ
[Sensor Interface Contract](../zeep-sensor-interface-contract-v1.2.md)

ACK จาก Control Hub ยืนยันว่า bridge รับ/ส่งคำสั่งแล้ว ไม่ได้พิสูจน์ว่าโหลดจริง
เปลี่ยนสถานะ การออกแบบ Monitoring ต้องไม่แปลง commanded state เป็น measured state

## เสียง: ความสามารถปัจจุบัน

SPH0645LM4H-B ส่งข้อมูลผ่าน Sensor Hub 1 โดย Production contract ปัจจุบันให้ Pi
รับ `sound_dba` โดยตรงในช่วง 30–130 dBA และคัดลอกเป็น `sound_dba_est` โดยไม่ทำ
`abs`, bias, A-weighting หรือ recalibration ซ้ำ ส่วน `sound_dbfs` เป็น diagnostic
แบบ signed สำหรับ Admin เท่านั้น

Pi รวม valid observations ในช่วง Sensor frame ด้วยค่าเฉลี่ยเชิงพลังงาน พร้อม
min/max/span และธงการเปลี่ยนระดับมาก นี่คือ **level aggregation** ไม่ใช่การทำ DSP
บน PCM และยังไม่ใช่หลักฐานว่าเป็น LAeq(A) ตามมาตรฐาน เพราะ Production firmware
source/weighting/window metadata ยังไม่ได้อยู่ใน repository

ระบบปัจจุบันจึงตอบได้ว่า “ระดับเสียงเป็นอย่างไร” แต่ยังตอบไม่ได้อย่างน่าเชื่อถือว่า
เป็นเสียงคอมเพรสเซอร์ พัดลม ประตู เพลง หรือเสียงจากภายนอก แผนเพิ่มความสามารถอยู่ที่
[หูอัจฉริยะ · Acoustic Intelligence DSP Plan](smart-ear-dsp-plan.md)

P1-shadow มี `acoustics/` สำหรับ versioned capability contract, Admin level/DSP
projection และ Session Timeline ผ่าน `/api/v1/admin/contracts/acoustics`,
`/api/v1/admin/acoustics/live` และ `/api/v1/admin/acoustics/timeline` Pi รองรับ
feature parser, persistence และ marker ของ `snore_like`, `speech_like`,
`impact_like` และ `steady_equipment_like` แล้ว แต่จะแสดง `not_evaluated` จน
Sensor Hub ส่งผลจาก Firmware candidate ที่ผ่าน physical validation และติดตั้งจริง

## เครื่องมือพัฒนา ทดสอบ และส่งมอบ

| งาน | เครื่องมือหลัก | หลักการ |
|---|---|---|
| เริ่มงานเครื่องทีม | `./start_work.sh` | ตรวจเครื่องที่อนุมัติ, fast-forward code และดึง snapshot แบบ read-only |
| รัน local | `./run.sh` | เปิด adapter จริงเมื่อมีอุปกรณ์; hardware ที่ไม่มีต้องแสดง unavailable ส่วน mock อยู่ใน tests |
| เลือก regression | `python quality_gate.py changed` | ใช้ risk-based profile จากไฟล์ที่เปลี่ยน |
| ทดสอบ domain | `python quality_gate.py <domain>` | เช่น `sensor`, `ui`, `session`, `sleep` |
| Full application gate | `python quality_gate.py full` | ใช้เมื่อข้ามระบบ, ไม่มั่นใจ, migration หรือก่อน Freeze |
| Style | Ruff ตาม `pyproject.toml` | ตรวจ top-level domain packages ทั้งหมด |
| UI bundle | `python ui_composer.py check` | ยืนยัน generated bundle ตรงกับ source partials |
| Evidence | JSON Schema/checksum updater | ตรวจทะเบียนงานวิจัยและ provenance |
| Production process | `systemd` service/watchdog | restart-on-failure; deploy เฉพาะ maintenance window |

คำสั่งล่าสุดและเงื่อนไข Full gate ให้ยึด [TESTING.md](../../TESTING.md) ส่วน Pull,
backup, deploy, restart และ recovery ให้ยึด
[Pi 5 Operations Runbook](../pi5-operations-runbook.md)

## สิ่งที่ **ยังไม่มี** ใน Current stack

- ไม่มี React/Vue/Node frontend build ใน Pi runtime
- ไม่มี ORM, Redis, PostgreSQL, Docker หรือ Kubernetes ใน deployment ปัจจุบัน
- ไม่มี Raw audio/PCM database และไม่มีระบบถอดคำพูด
- ไม่มี ML model, MFCC หรือระบบยืนยันแหล่งเสียงระดับ Production; มีเพียง
  interpretable FFT/rule-based DSP shadow candidate ที่ยังไม่ผ่าน field validation
- มี Firmware DSP candidate ของ Sensor Hub 1 ที่ build ได้ใน repository แต่ยังเป็น
  `NOT INSTALLED / DO NOT FLASH WITHOUT HARDWARE GATE`
- ไม่มี automatic actuation จาก Sleep State, Adaptive recommendation หรือเสียง
- ไม่มี clinical diagnosis, PSG equivalence, SpO2 หรือ whole-day readiness

## เส้นทางตรวจปัญหาที่สั้นที่สุด

| อาการ | ตรวจตามลำดับ |
|---|---|
| ค่าหน้าจอไม่ตรง Sensor | wire packet → Sensor contract → canonical snapshot → `/api/v1/state` → UI projection |
| Session/คะแนนผิด | Recorded Timeline → policy/formula version → derived report → Usage API → UI |
| คำสั่งอุปกรณ์ไม่ทำงาน | RBAC/CSRF → command policy → transport publish → ACK/audit → ตรวจโหลดจริงหน้างาน |
| Restart แล้วข้อมูลหาย | `systemd` log → active checkpoint → SQLite writer/outbox → resume event |
| ผู้ใช้เห็นข้อมูลเกินสิทธิ์ | principal → Backend dependency → allowlist projection → cache/log redaction |
| เสียงผิดปกติ | Hub 1 packet → validity/freshness → direct dBA ไป Recording Timeline/Session; 10-second aggregate ไป live/evidence/Monitor; ห้ามใช้ dBFS แทน dBA |

## Source of truth

- Architecture/module boundary: [Pi 5 Software Architecture](../pi5-software-architecture.md)
- API: [ZEEP API v1](../zeep-api-v1.md), typed models/manual envelopes และ
  `/openapi.json` ของ release ที่ deploy
- Sensor: [`sensors/contracts.py`](../../sensors/contracts.py),
  [`catalog.py`](../../sensors/catalog.py),
  [`calibration.json`](../../calibration.json) และ effective Pod config
- Sleep/Score: [`sleep_system_policy.py`](../../sleep_system_policy.py)
- Test: [TESTING.md](../../TESTING.md)
- Deploy/Ops: [Pi 5 Operations Runbook](../pi5-operations-runbook.md)
- Release fact: deployed health/version response และ signed closure record

เมื่อ narrative ขัดกับ executable contract ให้หยุดการเผยแพร่ผลและแก้เอกสารกับ
contract ใน release เดียวกัน ไม่เลือกข้อความที่ดูสมเหตุผลกว่าเอง
