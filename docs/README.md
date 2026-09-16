# ZEEP Pi 5 Documentation Index

สถานะ: **Current document map**

เจ้าของ: Pi 5 application team

อัปเดตล่าสุด: 17 กันยายน 2026

เริ่มจาก [ZEEP v1 Team Onboarding](onboarding/README.md) ซึ่งเป็นหน้าหลักสำหรับ
สมาชิกทีมทุกบทบาท เอกสารนี้เป็นทะเบียนเอกสารที่ยังใช้งาน ไม่ใช่การประกาศว่า
ทุกไฟล์มีอำนาจเท่ากัน เอกสารทดลองหรือ dry-run ที่ถูกแทนที่แล้วต้องอยู่ใต้
`docs/archive/`, Evidence library หรือ Git history พร้อมป้าย `ARCHIVED` ชัดเจน
และห้ามปะปนกับ Runtime contract

## ลำดับอำนาจเมื่อข้อมูลขัดกัน

1. Executable policy และ runtime contract: `sleep_system_policy.py`, Pydantic/
   OpenAPI, `sensors/contracts.py`, `calibration.json` และ effective Pod config
2. เอกสาร Current ของ domain: Sleep System, Sensor/API contract, Architecture และ
   Operations Runbook
3. Onboarding: แผนที่และคำอธิบายที่คนอ่านง่าย โดยต้องไม่คัดลอกค่าที่เปลี่ยนบ่อย
4. Handover/Closure: หลักฐานของ Git SHA และ release ที่ตรวจ ณ เวลาหนึ่ง
5. Pilot, Case study, Research และ Archive: หลักฐานประกอบ ไม่เปลี่ยน Runtime เอง

ถ้าข้อมูลสองชั้นไม่ตรงกัน ให้หยุดการเผยแพร่ผลและแก้ contract/narrative ใน release
เดียวกัน ห้ามเลือกข้อความที่ดูเหมาะกว่าเอง

## เอกสารหลัก

| เรื่อง | เอกสารที่มีอำนาจ | ใช้สำหรับ |
|---|---|---|
| เริ่มงานสมาชิกใหม่ | [ZEEP v1 Team Onboarding](onboarding/README.md) | จุดเริ่มหลัก: เส้นทางอ่านตามบทบาท, Lifecycle, Hardware, API/Data/Privacy และ First-week checklist |
| Tech stack และเครื่องมือ | [Technology Stack, Data และเครื่องมือ](onboarding/technology-stack-and-tools.md) | Orientation ของ Runtime, Frontend, Database, Protocol, QA และ Operations; package/config จริงยังเป็น source of truth |
| ส่งมอบและ Code Freeze | [v1 System Handover and Freeze Readiness](zeep-v1-system-handover-and-freeze-readiness.md) | Lifecycle ครบวงจร, invariant, test gate และรายการลงนามก่อน Freeze |
| ภาพรวมระบบ | [Pi 5 Software Architecture](pi5-software-architecture.md) | ขอบเขต module, dependency และลำดับ refactor |
| ปฏิบัติการเครื่อง | [Pi 5 Operations Runbook](pi5-operations-runbook.md) | Pull, verified Pod sync, test, deploy, backup, restart และ recovery |
| Sleep State และคะแนน | [Sleep System Current](zeep-sleep-system-current.md) | Runtime, replay, Sleep Score และ Recovery Score |
| หลักฐาน Baseline | [Sleep-State Baseline v1.8](zeep-sleep-state-baseline-v1.8.md) | Feature, gate, transition และขอบเขตการกล่าวอ้าง |
| Historical promotion | [Sleep History Promotion Policy v2](sleep-history-promotion-policy-v2.md) | Guard และ audit เมื่อเขียน derived result ย้อนหลัง |
| ผลลัพธ์ผู้ใช้ | [Session Result Presentation v1](zeep-session-result-presentation-v1.md) | ภาษากับลำดับข้อมูลบนหน้าผลลัพธ์ |
| Restore Summary | [Restore Summary v1](zeep-restore-summary-v1.md) | คำอธิบายคะแนนโดยไม่สร้างคะแนนที่สาม |
| User learning | [User Learning Profile v1](zeep-user-learning-profile-v1.md) | ประวัติรายบุคคล, Baseline และ AI context |
| Adaptive recommendation | [Adaptive Coach Plan v1](adaptive-control-recommendation-plan-v1.md) | Recommendation-first; ไม่สั่งอุปกรณ์อัตโนมัติ |
| Adaptive live data | [Adaptive Data Foundation v1](adaptive-control-data-foundation-v1.md) | ข้อมูล live สำหรับ Monitor และ shadow model |
| API | [ZEEP API v1](zeep-api-v1.md) | คู่มือ endpoint สำหรับทีมแอป |
| API schema | [API Schema Reference v1](zeep-api-schema-reference-v1.md) | Field, enum, privacy และ response contract |
| Sensor interface | [Sensor Interface Contract v1.2](zeep-sensor-interface-contract-v1.2.md) | ESP32/BCG field, validity และ provenance |
| Respiratory wellness | [Respiratory Wellness v1.2](zeep-respiratory-wellness-v1.md) | การสรุป HR/RR เชิง Wellness |
| Product language | [Product Language Guideline v1](zeep-product-language-guideline-v1.md) | คำสั้น กระชับ เป็นมิตร และไม่วินิจฉัย |
| Interface map และ UI | [Interface Map & UI Standard v1](zeep-interface-map-and-ui-standard-v1.md) | หน้าที่ทุกหน้า ลำดับข้อมูล Touch/Type/Icon และ viewport QA |
| Acoustic Intelligence | [หูอัจฉริยะ · DSP Plan](onboarding/smart-ear-dsp-plan.md) | P0.5 Admin level-only/capability contract อยู่ใน runtime; classifier, event และ user result ยังเป็น **ROADMAP/SHADOW** |
| Pilot สองโหมด | [Pilot Two-Mode Protocol](zeep-pilot-two-mode-protocol.md) | Overnight Recovery และ Nap & Refresh |
| Evidence library | [Research Evidence Library](../research/evidence-library/README.md) | แหล่งอ้างอิง, checksum และ verification |

## หลักฐาน Regression ที่ยังใช้งาน

- [Wake Lock-in Regression Register](zeep-wake-lock-regression-register.md)
- [Case Study CS-01](zeep-case-study-cs-01-two-overnight-sessions.md)
- [Brainwave Sound Lab](brainwave-sound-lab-v1.md)

[Documentation Archive](archive/README.md) เป็นข้อมูลประกอบ Audit เท่านั้น ไม่ใช่
Runtime contract และต้องไม่ถูกนำไปตั้ง Threshold หรืออธิบายพฤติกรรมปัจจุบันโดยตรง

Source HTML ของ `monitor.pillarsnova.com/zeep-project/` ไม่ได้อยู่ใน repository นี้
จึงไม่ใช่เอกสาร Runtime ที่แก้จาก repo นี้ได้ ก่อนเผยแพร่ Monitor ต้องตรวจสถานะ
`LIVE / SHADOW / PILOT EVIDENCE / SIMULATION / ROADMAP / ARCHIVED`, Git SHA,
version และ privacy/consent ตาม checklist ใน Onboarding
