# ZEEP v1 Refactor Roadmap

สถานะ: **แผนงานแบบ behavior-preserving สำหรับ Internal Pilot**

เอกสารนี้กำหนดวิธีลดความซับซ้อนของ Pi 5 โดยไม่เปลี่ยนสูตร Sleep State,
Sleep Score, Recovery Score, Safety policy หรือพฤติกรรมอุปกรณ์ใน Commit เดียวกับ
การย้ายโค้ด รายละเอียดระบบปัจจุบันให้อ่านจาก
[Pi 5 Software Architecture](../pi5-software-architecture.md) และ
[v1 System Handover](../zeep-v1-system-handover-and-freeze-readiness.md)

## 1. เป้าหมายโครงสร้าง

```text
app.py                         ประกอบ dependency, lifespan และติดตั้ง routers
zeep_pod/api/                  HTTP routers และ response projection
zeep_pod/sessions/             Session/Sleep/Score use cases และ policy
zeep_pod/hardware/             Serial, MQTT, GPIO และ Audio adapters
zeep_pod/identity/             Account, profile, occupancy และ erasure
zeep_pod/operations/           Deploy, snapshot, workstation และ maintenance
```

ขอบเขตต้องแยกกันชัดเจน:

- Feature service อธิบายว่า “ระบบต้องทำอะไร” แต่ไม่เปิด Serial/MQTT/GPIO เอง
- Hardware adapter อธิบายว่า “คุยกับอุปกรณ์อย่างไร” แต่ไม่ตัดสิน Sleep State
  หรือคะแนน
- API route ตรวจ Auth/RBAC/CSRF, validate input แล้วเรียก service; ไม่เขียนคำสั่ง
  protocol ซ้ำ
- `app.py` เป็น composition root เท่านั้น และเป็นฝ่ายส่ง dependency ให้ module
- Dashboard, Session และ Report อ่าน canonical values จาก Backend ชุดเดียวกัน

## 2. ลำดับการ Refactor

สถานะ ณ 16 กันยายน 2026: **R0–R3 และ R4a เสร็จใน working candidate นี้**
โดยย้าย live projection, LSM-800-T reader และ canonical Sensor-frame sampler ออกจาก
`app.py` แล้ว ส่วน R4a แยกเฉพาะ atomic Session-finalization commit boundary ซึ่งมี
ขอบเขตชัดและทดสอบ failure/recovery ได้ งาน Session lifecycle ส่วนที่เหลือยังต้องทำ
เป็นชิ้นเล็กต่อไป จึงยังไม่ถือว่า `app.py` เป็น composition root ที่สมบูรณ์

| ระยะ | ขอบเขต | ผลลัพธ์ที่ต้องได้ | Gate ก่อน Merge |
|---|---|---|---|
| R0 — เสร็จแล้ว | Characterization | ตรึง behavior ปัจจุบันด้วย regression และ fixture ที่ไม่แตะ Production | Full suite ผ่านก่อนเริ่ม |
| R1 — เสร็จแล้ว | Live state projection | ย้ายการประกอบ freshness/connected/stale metadata ออกจาก `snapshot()` | Response เดิมทุก field |
| R2 — เสร็จแล้ว | BCG transport | ย้าย framing/reader/publisher ไป `hardware/bcg.py`; inject state/callback/stop token และคง facade บางใน `app.py` | Fake-serial + reconnect + state/storage tests |
| R3 — เสร็จแล้ว | Sensor sampling | รวม 10-second canonical frame เป็น service; 30-second evidence ยังคง owner เดิม | Cadence/clock/window/bed-exit tests |
| R4a — เสร็จแล้ว | Atomic finalization commit | แยก payload, enqueue, flush, recovery และ checkpoint-clear order | Exact payload + failure/retry tests |
| R4b | Session lifecycle | แยก waiting-bed, vital gate, begin/resume/finalize orchestration และ checkpoint เป็น services | Restart ไม่ logout; lifecycle parity |
| R5 | Sleep engine facade | ให้ `estimate_sleep_state()` เหลือ orchestration โดยเรียก feature/scorer/policy modules | Golden replay ไม่เปลี่ยน State/Score |
| R6 | API routers | แยก auth, control, session, admin/monitor และ calibration routers | OpenAPI/RBAC/CSRF compatibility |
| R7 | Composition root | `app.py` เหลือ configuration, dependency wiring, lifespan และ router registration | Production smoke ทุก Hub |

แต่ละระยะต้องเป็น Commit เล็กที่ย้อนกลับได้ ห้ามรวมการจูน threshold, เปลี่ยน
ข้อความผลิตภัณฑ์, schema migration หรือ Firmware flash เข้าใน Commit Refactor

หลักฐานของ working candidate ปัจจุบัน:

- `app.py` ลดจาก 8,270 เหลือ 8,025 บรรทัด
- `snapshot()` ลดจาก 169 เหลือ 118 บรรทัด และมี architecture ratchet
- BCG byte-framing/reconnect ย้ายไป module 334 บรรทัด; facade ใน `app.py`
  ไม่เกิน 31 บรรทัด
- Sensor-frame sampler อยู่ใน module 301 บรรทัด; facade 27 บรรทัด และมี regression
  ครอบคลุม cadence 10 วินาที, paired HR/RR, sound window และ Bed Exit debounce
- Atomic finalization อยู่ใน module 83 บรรทัด; facade 19 บรรทัด และรักษาลำดับ
  enqueue → flush → remove retry origin → clear checkpoint
- เพิ่ม characterization 27 เคสสำหรับ live projection, BCG, Sensor frame และ
  finalization พร้อม architecture ratchet ป้องกันโค้ด Legacy โตกลับ
- ไม่เปลี่ยน Sleep/Score formula, Sensor cadence, public key หรือ Hardware command

## 3. ลำดับความสำคัญของอุปกรณ์

1. **BCG LSM-800-T / USB Serial — เสร็จแล้ว** — framing, reconnect และ publication
   อยู่ใน hardware adapter พร้อม fake-serial regression
2. **Canonical Sensor Frame — เสร็จแล้ว** — รวม Hub 1, Hub 2 และ BCG โดยคง
   cadence 10 วินาที
3. **Session lifecycle/checkpoint — กำลังทยอยแยก** — atomic commit เสร็จแล้ว;
   waiting/start/resume/report orchestration ยังอาศัย Bed,
   HR/RR และ freshness
4. **Control Hub 1/2** — adapters แยกแล้ว; ขั้นต่อไปคือเลิก module-global
   configuration และ inject instance/stop token
5. **GPIO/Audio** — adapters แยกแล้ว ให้คง API facade จน route migration เสร็จ

แผนอุปกรณ์และ failure behavior แบบละเอียดอยู่ใน
[Hardware and Hub Map](hardware-hub-map.md)

## 4. กฎขนาดและ Dependency

- Module ใหม่ภายใต้ `zeep_pod/` ไม่เกิน 500 บรรทัด
- Function/method ไม่เกิน 90 บรรทัด
- `app.py` ลดได้เท่านั้น; ปรับเพดาน regression ลงหลังแต่ละ extraction
- `zeep_pod/` ห้าม import `app.py`
- Pure policy ห้ามเปิดไฟล์, network หรือ hardware ตอน import
- Thread/reader ใหม่ต้องรับ stop token และปิด resource ได้จาก lifespan
- Compatibility facade ลบได้เมื่อ caller, tests และเอกสารย้ายครบแล้วเท่านั้น

## 5. Definition of Done ต่อหนึ่งระยะ

1. ระบุ behavior ที่ต้องคงไว้และเพิ่ม characterization test ก่อนย้าย
2. Source of truth มีเพียงแห่งเดียว; wrapper เดิมทำหน้าที่ delegate ชั่วคราว
3. ไม่มี Raw data, formula version, public JSON key หรือ command timing เปลี่ยน
4. Focused tests, architecture guard, UI composer และ Full Regression ผ่าน
5. อัปเดต architecture/hardware map และบันทึกจำนวนบรรทัดก่อน–หลัง
6. ตรวจ Production smoke เฉพาะเมื่อ Pod ว่าง และไม่จบ Active Session

คำสั่งตรวจมาตรฐานอยู่ใน [Testing and Release Gates](../../TESTING.md)

## 6. สิ่งที่ไม่ทำใน Refactor v1

- ไม่ใช้ Personal Baseline เปลี่ยน Sleep State โดยตรง
- ไม่เพิ่ม automatic actuation จาก Sleep State
- ไม่สร้าง True HRV, SpO₂, ความดัน หรือข้อสรุปทางการแพทย์จากข้อมูลที่ไม่มี
- ไม่แก้ Raw file หรือเขียนผลย้อนหลังเพื่อให้คะแนนดูดีขึ้น
- ไม่ Flash replacement Sensor Hub firmware ที่ถูกระบุ `ARCHIVED / DO NOT FLASH`

## 7. ตัวชี้วัดความสำเร็จ

- พนักงานใหม่หา owner/module ของปัญหาได้ภายใน 10 นาที
- การจำลอง Sensor หรืออุปกรณ์หนึ่งตัวไม่ต้อง start FastAPI ทั้งระบบ
- Route test ไม่ต้องเปิด GPIO, MQTT, Serial หรือ Audio จริง
- Reader ทุกตัว stop/restart ได้โดยไม่ทิ้ง thread หรือ file descriptor
- `app.py` ลดลงต่อเนื่องจนเหลือเฉพาะ composition โดย Full Regression ไม่เปลี่ยนผล

## 8. ลำดับถัดไปจาก Standards Audit

รายการต่อไปนี้ยัง **ไม่ได้แก้ใน working candidate นี้** และต้องแยกเป็น change
ที่ review/ย้อนกลับได้:

1. **P0 — Import-safe runtime:** ย้ายการสร้าง directory, SQLite store, GPIO และ
   resource ที่มี I/O ออกจาก module import ไป explicit lifespan/factory พร้อม
   subprocess regression; แยก offline reclassification ออกจาก `import app`.
2. **P0 — Sleep estimator facade:** แยก `estimate_sleep_state()` เป็น typed input,
   pure decision และ effect boundary โดยใช้ golden parity ครบ Missing vital,
   Restart hold, Off-bed และทุก transition; ห้ามเปลี่ยน threshold ใน change นี้.
3. **P1 — Session lifecycle:** แยก waiting/start/resume/finalize orchestration และ
   worker registry โดยรักษา atomic commit order จาก R4a.
4. **P1 — Report pipeline:** รวมการสร้าง report/night summary ที่ซ้ำใน Live,
   Audit, Rescore และ Trim ให้ใช้ contract เดียว พร้อม parity/rollback tests.
5. **P1 — Dependency direction:** ย้าย policy กลางเข้า package ทีละตัวและคง
   compatibility re-export จน caller ย้ายครบ เพื่อลด `zeep_pod -> root`.
6. **P2 — Legacy style:** เปิด Ruff/format/type contract ทีละไฟล์พร้อม regression;
   ห้ามใช้ auto-fix หลายร้อยรายการรวมกับการย้าย behavior.
