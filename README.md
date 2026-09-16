# ZEEP Pod — Pi 5 Runtime

สถานะ: **Internal Pilot / v1 freeze candidate**

ระบบควบคุมและประเมินการพักเชิง Wellness ของ ZEEP Pod ทำงานบน Raspberry Pi 5
เชื่อม BCG, Sensor Hub, อุปกรณ์ควบคุม, Web UI และ API สำหรับแอป ZEEP

> สมาชิกทีมใหม่และผู้รับช่วงงานให้เริ่มที่
> [ZEEP v1 Team Onboarding](docs/onboarding/README.md) เสมอ เอกสารหน้านี้เป็นเพียง
> จุดเริ่มต้นและคำสั่ง Bootstrap ไม่ใช่สำเนาของข้อกำหนดทุกระบบ

## ขอบเขต v1

ZEEP v1 มีรูปแบบการพักที่ผู้ใช้เลือกสองแบบเท่านั้น:

| รูปแบบ | ผลหลัก | หลักการ |
|---|---|---|
| **Overnight Recovery** | Sleep Score | พักค้างคืน; เผยแพร่คะแนนเมื่อ Recording อย่างน้อย 5 ชั่วโมง และใช้ 7 ชั่วโมงเป็นกรอบ duration เต็มสำหรับผู้ใหญ่ |
| **Nap & Refresh** | Recovery Score | พัก 30 หรือ 90 นาที; ไม่บังคับว่าต้องหลับ และเผยแพร่คะแนนเมื่อ Recording อย่างน้อย 10 นาที |

ผลทั้งหมดเป็นการประเมินเชิง Wellness จาก Sensor ไม่ใช่ PSG การวินิจฉัย หรือ
คำสั่งรักษา Restore Summary อธิบายคะแนนหลักและไม่ใช่คะแนนที่สาม

## เริ่มใช้งาน

สำหรับ Source-only/local development:

```bash
./run.sh
```

สคริปต์สร้าง virtual environment, ติดตั้ง runtime dependencies และเปิดแอป
Hardware ที่ไม่มีบนเครื่องพัฒนาต้องแสดง `Unavailable/Disconnected` ตามจริง;
ผล local ไม่ใช่หลักฐานว่าเครื่องจริงผ่าน

สำหรับเครื่องทีมที่ได้รับอนุมัติและเปิด disk encryption แล้ว:

```bash
./start_work.sh
```

คำสั่งนี้ตรวจ workstation, fast-forward จาก `origin/develop` และดึง verified
read-only snapshot จาก Pod โดยไม่ตั้ง snapshot เป็น Runtime `DATA_DIR`
ดูข้อกำหนดทั้งหมดที่ [Pi 5 Operations Runbook](docs/pi5-operations-runbook.md)

## เข้าถึง Pod 1

- LAN ที่ควบคุม: `http://192.168.1.100:8000/`
- Tailscale: `http://pod1.starling-altered.ts.net:8000/`
- SSH: `ssh pod1@pod1.starling-altered.ts.net`
- Runtime path: `/home/pod1/pi5`
- Git deployment branch: `origin/develop`

ห้ามเปิด port `8000` ตรงสู่อินเทอร์เน็ต Public การเข้าจากภายนอกต้องผ่าน
Tailscale หรือ reverse proxy ที่ใช้ HTTPS, access policy และ secure cookie

## แผนที่ Source of truth

| ต้องการทราบ | เปิดเอกสาร/แหล่งนี้ |
|---|---|
| เริ่มงานและเลือกเส้นทางตามบทบาท | [Team Onboarding](docs/onboarding/README.md) |
| Product, Mode และ Session lifecycle | [Product and Lifecycle](docs/onboarding/product-and-lifecycle.md) |
| Tech stack, database และเครื่องมือ | [Technology Stack, Data และเครื่องมือ](docs/onboarding/technology-stack-and-tools.md) |
| Hardware, transport และ failure boundary | [Hardware and Hub Map](docs/onboarding/hardware-hub-map.md) |
| API, Data และ Privacy | [API, Data and Privacy](docs/onboarding/api-data-and-privacy.md) |
| แผนจำแนกเสียง DSP | [หูอัจฉริยะ · Acoustic Intelligence DSP Plan](docs/onboarding/smart-ear-dsp-plan.md) — ROADMAP/SHADOW |
| Pull, test, deploy, backup และ recovery | [Operations and First Week](docs/onboarding/operations-and-first-week.md) |
| Sleep State, score และ version ปัจจุบัน | [Sleep System Current](docs/zeep-sleep-system-current.md) และ [`sleep_system_policy.py`](sleep_system_policy.py) |
| API field/enum | [API Schema Reference](docs/zeep-api-schema-reference-v1.md), Pydantic models และ `/openapi.json` ของ release ที่ deploy |
| Sensor field/calibration | [Sensor Interface Contract](docs/zeep-sensor-interface-contract-v1.2.md), [`sensor_contracts.py`](sensor_contracts.py) และ [`calibration.json`](calibration.json) |
| Test และ release gate | [TESTING.md](TESTING.md) |
| Code ownership/refactor | [Pi 5 Software Architecture](docs/pi5-software-architecture.md) และ [CONTRIBUTING.md](CONTRIBUTING.md) |
| Freeze/P0/P1/sign-off | [v1 Handover and Freeze Readiness](docs/zeep-v1-system-handover-and-freeze-readiness.md) |
| งานวิจัยและ provenance | [Research Evidence Library](research/evidence-library/README.md) |

Onboarding เป็นหน้าหลักสำหรับมนุษย์ แต่ค่าที่เปลี่ยนตาม release ต้องยึด executable
policy, Pydantic/OpenAPI, Sensor contract, effective configuration และ Git SHA
ตามลำดับ ห้ามคัดตัวเลขจากรายงาน Pilot หรือหน้า Monitor มาเปลี่ยน Runtime โดยตรง

## โครงสร้างสำคัญ

```text
app.py                       legacy composition root ที่กำลังลดเหลือ wiring/lifecycle
zeep_pod/hardware/           Serial, MQTT, GPIO และ Audio adapters
zeep_pod/sessions/           Session, report, history, baseline และ replay services
zeep_pod/identity/           ZEEP account, profile, occupancy และ erasure
sleep_signal_features.py     engineering evidence จาก BCG/Bed/HR/RR/Movement
sleep_stage_scoring.py       shared five-state evidence scorer
sleep_system_policy.py       version, gate, transition, mode และ score manifest
sleep_session_report.py      mode-aware Sleep/Recovery result
static/index.template.html   UI source
static/partials/             UI sections
static/index.html            generated runtime bundle
```

Dashboard, Session, Safety และ Report ต้องอ่าน canonical Sensor values ชุดเดียวกัน
และ UI ห้ามคำนวณ Sensor, Sleep State หรือคะแนนซ้ำจากค่าดิบ

## Invariants ที่ห้ามทำลาย

1. Raw Sensor/BCG/Timeline ไม่ถูกแก้เพื่อทำให้ Derived result ดูดีขึ้น
2. ไม่มีผู้ใช้อยู่บนเตียงหรือไม่มี HR/RR ตาม gate ห้ามสร้าง N1/N2/N3/REM
3. ทุก occupied Recording interval ต้องเป็น W/N1/N2/N3/REM; OFF BED แยกออก
4. Overnight มี Sleep Score และ Nap มี Recovery Score; เวลาที่ผ่านไปห้ามสลับ Mode
5. Environment ไม่สร้าง Sleep State แต่เป็น bounded support 10 คะแนนในทั้งสองสูตร
6. Restart/deploy ไม่ใช่ Logout และไม่จบ Active Session
7. Sleep State และ Shadow recommendation ห้ามสั่งอุปกรณ์อัตโนมัติใน v1
8. User เห็นข้อมูลตนเอง; Admin/raw/control route ต้องตรวจสิทธิ์ที่ Backend
9. ห้าม Restart, deploy, shutdown หรือ maintenance ขณะมีผู้ใช้งาน/Recording
10. Public result ต้องคง `clinical_validated=false`

## ตรวจงานก่อนส่ง Review

ใช้ `python quality_gate.py changed` เพื่อรันเฉพาะส่วนที่แก้ตาม
[TESTING.md](TESTING.md) แล้วให้ CI ทำ Full Gate หนึ่งครั้งต่อ Git SHA ไม่ต้องรัน
ชุดเต็มซ้ำบน Mac และ Pi ยกเว้นงานข้ามระบบ ผลไม่แน่นอน หรือ Code Freeze

แก้ UI ที่ `static/index.template.html` หรือ `static/partials/` แล้วตรวจด้วย:

```bash
python ui_composer.py check
```

อย่าแก้ generated `static/index.html` เพียงไฟล์เดียว
