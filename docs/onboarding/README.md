# ZEEP v1 — Team Onboarding

สถานะ: **คู่มือเริ่มงานสำหรับ Internal Pilot**

ขอบเขต: Pi 5 runtime, Web UI, Sensor/Control Hubs, Session results และงานปฏิบัติการ

ปรับปรุงล่าสุด: 17 กันยายน 2026

> ชุด Onboarding นี้เป็น **ประตูหลักสำหรับค้นหาเอกสาร v1** แล้วจึงตามลิงก์ไปยัง
> contract/runtime source ที่มีอำนาจของแต่ละ domain; ไม่ได้แทนหลักฐานอนุมัติ release
> Production ปัจจุบัน v1 ยังเป็น **freeze candidate** และยังต้องปิดรายการ P0/
> ลงนามใน closure record ก่อนประกาศ Final Code Freeze

## เริ่มอ่านจากตรงไหน

อ่านเอกสารหลักตามลำดับนี้ในวันแรก:

1. [Product และ Session lifecycle](product-and-lifecycle.md) — ZEEP ทำอะไร,
   สองโหมดต่างกันอย่างไร และข้อมูลเดินจาก Login ไปถึงผลลัพธ์อย่างไร
2. [Technology Stack, Data และเครื่องมือ](technology-stack-and-tools.md) —
   Runtime, Frontend, Database, Protocol, QA และ Operations ที่ใช้งานจริง
3. [Hardware และ Hub map](hardware-hub-map.md) — อุปกรณ์, transport, owner และ
   fail-safe boundary ของแต่ละ Hub
4. [API, Data และ Privacy](api-data-and-privacy.md) — ใครอ่านอะไรได้,
   ข้อมูลใดอยู่บน Pod/ออกจาก Pod และขอบเขตการลบข้อมูล
5. [Operations และ First-week checklist](operations-and-first-week.md) —
   เตรียมเครื่อง, เลือก test, deploy อย่างปลอดภัย และเป้าหมายสัปดาห์แรก

สำหรับทีม Sensor, Firmware, Data/ML, Monitor หรือ Product ที่จะพัฒนาเสียง ให้อ่าน
[หูอัจฉริยะ · Acoustic Intelligence DSP Plan](smart-ear-dsp-plan.md) เพิ่ม เอกสารนี้
มี **P1 ADMIN SHADOW** สำหรับ level timeline และ optional Firmware DSP marker;
Pi/API/UI พร้อมแล้ว แต่ classifier ยังไม่ถือว่า LIVE/Production จน Firmware ผ่าน
physical validation และติดตั้งจริง

หากต้องตอบคำถามส่งมอบ v1 ให้เริ่มจาก
[v1 System Handover and Freeze Readiness](../zeep-v1-system-handover-and-freeze-readiness.md)
และตรวจสถานะล่าสุดที่ closure record ก่อนเสมอ

## สถานะที่ทุกคนต้องเข้าใจ

| ระดับ | ความหมายปัจจุบัน |
|---|---|
| **Internal Pilot** | ใช้กับทีม/ผู้ทดสอบในสภาพแวดล้อมควบคุมได้ ตาม two-mode protocol และ operations runbook |
| **Freeze candidate** | Behavior หลักและ contract มี regression รองรับ แต่ยังไม่ใช่ Final Code Freeze |
| **Production-ready** | **ยังห้ามอ้าง** จน P0, Production smoke, Safety/Product Owner sign-off, Git SHA/tag และ data-governance controls ครบ |

คำว่า “ผ่าน test” ไม่เท่ากับ “พร้อม Production” การอนุมัติต้องรวมเครื่องจริง,
อุปกรณ์จริง, privacy/retention, operator procedure และ owner sign-off ด้วย

## Tech Stack ฉบับย่อ

| ชั้น | ปัจจุบันใช้ |
|---|---|
| Pi runtime | Raspberry Pi 5, Linux, `systemd`, Python 3.11+; CI/Ruff target 3.11 |
| Backend/API | FastAPI, Uvicorn, Pydantic models, REST/WebSocket, `httpx` |
| Frontend | Vanilla HTML/CSS/JavaScript; template/partials ประกอบด้วย `ui_composer.py` |
| Storage | SQLite WAL (`sessions.db`, `bcg.db`, `auth.db`, `occupancy.db`) + JSON/JSONL/outbox |
| Device I/O | USB Serial JSONL/Binary, MQTT, BCM GPIO และ MPV IPC |
| QA/Ops | `unittest`, risk-based `quality_gate.py`, Ruff, JSON Schema, GitHub Actions, Git/Tailscale/SSH |

ไม่มี Node frontend runtime, ORM, Redis, PostgreSQL หรือ Raw audio database บน Pod
รายละเอียดและเส้นทาง debug อยู่ที่
[Technology Stack, Data และเครื่องมือ](technology-stack-and-tools.md)

### คำสถานะสำหรับเอกสารและการเผยแพร่

ใช้คำชุดเดียวกันทั้งเอกสาร Dashboard และสื่อ Pilot เพื่อไม่ให้แผนอนาคตถูกอ่านเป็น
ความสามารถปัจจุบัน:

| สถานะ | ใช้เมื่อ |
|---|---|
| **LIVE** | ทำงานจริงใน release/Pod ที่ระบุและมีหลักฐานตาม contract |
| **SHADOW** | คำนวณหรือแนะนำได้ แต่ไม่มีสิทธิ์สั่งอุปกรณ์อัตโนมัติ |
| **PILOT EVIDENCE** | ข้อค้นพบจากผู้ทดสอบ; ต้องระบุจำนวนตัวอย่างและข้อจำกัด |
| **SIMULATION** | ผลจากข้อมูลจำลอง ไม่ใช่การยืนยันบน Pod หรือกับมนุษย์ |
| **ROADMAP** | แนวคิดหรือความสามารถที่ยังไม่อยู่ใน v1 |
| **ARCHIVED** | เก็บเพื่อ audit/อ้างอิงเท่านั้น ห้ามนำไป deploy หรืออ้างว่าใช้งานอยู่ |

สื่อ Pilot ที่เปิดต่อสาธารณะต้องใช้ coded ID หรือมี consent ที่ครอบคลุมชื่อ ภาพ เสียง
และวิดีโออย่างชัดเจน `noindex` ไม่ใช่ access control และไม่แทนการอนุญาตเผยแพร่

## แผนที่ Source of truth

Onboarding สรุปเส้นทาง ไม่ทำสำเนารายละเอียดที่เปลี่ยนบ่อย ให้ใช้แหล่งต่อไปนี้:

| เรื่อง | แหล่งที่มีอำนาจ |
|---|---|
| แผนที่เอกสารปัจจุบัน | [Documentation Index](../README.md) |
| มาตรฐานเขียนโค้ดและส่ง Review | [CONTRIBUTING.md](../../CONTRIBUTING.md) |
| Lifecycle, invariant และสถานะ Freeze | [v1 System Handover](../zeep-v1-system-handover-and-freeze-readiness.md) |
| ขอบเขต module และลำดับ refactor | [Pi 5 Software Architecture](../pi5-software-architecture.md) |
| Sleep State, score และ policy version | [Sleep System Current](../zeep-sleep-system-current.md) และ [`sleep_system_policy.py`](../../sleep_system_policy.py) |
| API สำหรับ App | [ZEEP API v1](../zeep-api-v1.md), [Schema Reference](../zeep-api-schema-reference-v1.md), Pydantic models และ `/openapi.json` ของ release ที่ deploy |
| Sensor field/range/provenance | [Sensor Interface Contract](../zeep-sensor-interface-contract-v1.2.md) และ [`sensors/contracts.py`](../../sensors/contracts.py) |
| Tech stack, database และเครื่องมือ | [Technology Stack, Data และเครื่องมือ](technology-stack-and-tools.md) เป็น orientation; runtime ยึด requirements/config/service จริง |
| แผนจำแนกเสียง/DSP | [หูอัจฉริยะ · Acoustic Intelligence DSP Plan](smart-ear-dsp-plan.md) และ [Validation Protocol](../../research/evidence-library/ACOUSTIC_INTELLIGENCE_VALIDATION.md); P1-shadow รองรับ marker ฝั่ง Pi แล้ว ส่วน Firmware ยังต้องผ่าน physical gate |
| Test/release gate | [TESTING.md](../../TESTING.md) |
| Pull, Sync, Deploy, Backup | [Pi 5 Operations Runbook](../pi5-operations-runbook.md) |
| คำที่แสดงต่อผู้ใช้ | [Product Language Guideline](../zeep-product-language-guideline-v1.md) |

ถ้าเอกสาร, runtime model, OpenAPI หรือ approved replay evidence ขัดกัน
ให้ **หยุดการเผยแพร่ผล** บันทึก version/SHA ที่พบ และส่งให้ owner แก้ความขัดแย้ง
ใน release เดียวกัน ห้ามเลือกคำตอบที่ดูสมเหตุผลกว่าเอง

## เส้นทางตามบทบาท

| บทบาท | อ่านเพิ่ม | จุดเริ่มในโค้ด |
|---|---|---|
| Product / UX | [Two-Mode Protocol](../zeep-pilot-two-mode-protocol.md), [Session Result Presentation](../zeep-session-result-presentation-v1.md) | [`presentation/language.py`](../../presentation/language.py), `static/partials/` |
| Pi / Backend | [Software Architecture](../pi5-software-architecture.md), [API v1](../zeep-api-v1.md) | [`app.py`](../../app.py), [`api/`](../../api/), [`sessions/`](../../sessions/), [`hardware/`](../../hardware/) |
| Mobile / Web integration | [API Schema Reference](../zeep-api-schema-reference-v1.md) | [`sessions/usage_api.py`](../../sessions/usage_api.py), response models |
| Hardware / Firmware | [Hardware และ Hub map](hardware-hub-map.md), [Sensor Interface Contract](../zeep-sensor-interface-contract-v1.2.md) | `sensor_*`, `control_protocol.py`, `hardware/` |
| Acoustics / Data / Monitor | [หูอัจฉริยะ · DSP Plan](smart-ear-dsp-plan.md), [API/Data/Privacy](api-data-and-privacy.md) | Current: `sensors/`, `sessions/sensor_frame_sampler.py`, `acoustics/`; Planned: feature parser/classifier/event tracker |
| QA / Data | [TESTING.md](../../TESTING.md), [Sleep History Promotion Policy](../sleep-history-promotion-policy-v2.md) | `test_*.py`, [`maintenance_registry.py`](../../maintenance_registry.py) |
| Operations / Safety | [Operations Runbook](../pi5-operations-runbook.md), [TESTING.md](../../TESTING.md) | [`start_work.sh`](../../start_work.sh), service units, `operations/` |

## กฎหยุดงานทันที

- ห้าม restart/deploy/shutdown ขณะมีผู้ใช้งานหรือ Session กำลังบันทึก
- ห้ามแก้ Raw BCG, Raw Sensor หรือ Timeline เพื่อทำให้ Derived result ดูดีขึ้น
- ห้ามเปิด port `8000` ตรงสู่ Public Internet หรือใส่ credential ใน URL,
  source, log, client bundle หรือไฟล์ที่ส่งให้ลูกค้า
- ห้ามใช้ Pod snapshot เป็น `DATA_DIR`, ส่งต่อ snapshot หรือเก็บบนเครื่องส่วนตัว/
  เครื่องที่ไม่ได้เข้ารหัสดิสก์
- ห้าม Flash `firmware/sensorhub1-esp32s3/`; เป็น replacement candidate ที่
  archive แล้วและไม่ใช่ v1 Production firmware
- ห้ามให้ Sleep State หรือ Shadow recommendation สั่งอุปกรณ์อัตโนมัติ;
  v1 ต้องคง `automatic_actuation=false`
- ห้ามสื่อว่า ZEEP วินิจฉัยโรค, เทียบเท่า PSG, วัด SpO2/True HRV หรือบอก
  whole-day readiness

## คำศัพท์ย่อ

| คำ | ความหมายในระบบ |
|---|---|
| Auth Session | สิทธิ์ของ Browser ผ่าน cookie; ไม่ใช่การครอบครองตู้ |
| Pod Session | การครอบครองตู้จริงของผู้ใช้หนึ่งคน |
| `waiting_bed` | Login/จอง Pod แล้ว แต่ยังไม่ผ่าน start gate และยังไม่สร้าง Recorded Session |
| Recording | Session ที่ผ่าน Bed + fresh HR/RR gate และเริ่มเก็บ Timeline/BCG |
| Canonical snapshot | ค่าสภาพแวดล้อมชุดเดียวที่ Dashboard, Session, Safety และ report ใช้ร่วมกัน |
| Derived result | Sleep State, score, report หรือ baseline ที่สร้างจาก Raw พร้อม version/provenance |
| Restore Summary | คำอธิบายคะแนนหลัก ไม่ใช่คะแนนที่สาม |
| OFF BED | Occupancy exception แยกจาก Wake และไม่เข้า Sleep Stage ratio |
| Shadow | คำแนะนำ/การประเมินที่ไม่มีสิทธิ์สั่ง Hardware |
| Acoustic Intelligence | P1-shadow แสดงระดับเสียงและ optional Firmware DSP marker ให้ Admin; ไม่ส่ง Raw audio ไม่ฟัง/ถอดเนื้อหาคำพูด และไม่กระทบ State/Score/Control |
| Email-first identity | ใช้ email ที่ยืนยันได้ก่อน; ข้อมูลเก่าอาจยังใช้ normalized legacy account key โดยมี alias ที่ตรวจสอบแล้ว |

## พร้อมรับงานชิ้นแรกเมื่อ

- [ ] อ่านเอกสารหลัก 5 หน้าและ canonical docs ของ domain ที่จะรับผิดชอบ
- [ ] ใช้ workstation ที่ทีมอนุมัติและเปิด FileVault หรือ LUKS/dm-crypt
- [ ] เข้าใจว่า Local/Mock pass ไม่ใช่ Hardware/Production smoke pass
- [ ] แยกความสามารถ `LIVE` ออกจาก `SHADOW/ROADMAP` ได้ โดยเฉพาะ Adaptive และ Acoustic Intelligence
- [ ] รัน focused suite ของ domain ได้โดยไม่อ่าน/เขียน Production data
- [ ] ระบุ owner, invariant, privacy impact และ deployment impact ของงานได้
- [ ] รู้ว่าจะหยุดและส่งต่อให้ Product, Safety, Privacy หรือ Hardware owner เมื่อใด

ขั้นตอนปฏิบัติจริงและแบบตรวจสัปดาห์แรกอยู่ที่
[Operations และ First-week checklist](operations-and-first-week.md)
