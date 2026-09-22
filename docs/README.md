# ZEEP Pi 5 Documentation Index

สรุปงานล่าสุดสำหรับทีม:
[Adaptive Journey และแผนขยายเซนเซอร์](onboarding/adaptive-journey-and-sensor-expansion.md)
(22 กันยายน 2026 · `eaccf32` ขึ้น Git และ CI ผ่านแล้ว; ยังไม่มี Deploy ในรอบนี้)
รายละเอียดหลัก: [Adaptive Journey 4 ขั้น](zeep-adaptive-journey-v1.md) ·
[Sensor Expansion BOM](zeep-sensor-expansion-bom-v1.md)

รอบรวมงานที่ค้าง: [22 กันยายน — Backend, Interface และเอกสาร](reviews/2026-09-22-pending-work-integration.md)
คงงาน Adaptive ที่เผยแพร่แล้ว พร้อมปรับภาษาและตัวอย่าง API ให้ตรงกับ source

สถานะ: **Current document map**

เจ้าของ: Pi 5 application team

อัปเดตล่าสุด: 22 กันยายน 2026

เริ่มจาก [ZEEP v1 Team Onboarding](onboarding/README.md) ซึ่งเป็นหน้าหลักสำหรับ
สมาชิกทีมทุกบทบาท เอกสารนี้เป็นทะเบียนเอกสารที่ยังใช้งาน ไม่ใช่การประกาศว่า
ทุกไฟล์มีอำนาจเท่ากัน เริ่มต่อที่ [สถานะระบบล่าสุด](current-status.md)
คู่มือ/ข้อเสนอที่ถูกแทนที่แล้วให้ลบจากชุดอ่านปัจจุบันและย้อนดูจาก Git history
ส่วน Audit, Case study และ calibration provenance ที่ยังมีผู้ใช้อ้างอิงต้องแยก
เป็นหลักฐานตามวันที่ ไม่ใช่ Runtime contract

## ลำดับอำนาจเมื่อข้อมูลขัดกัน

1. Executable policy และ runtime contract: `sleep_system_policy.py`, Pydantic/
   OpenAPI, `sensors/contracts.py`, `calibration.json` และ effective Pod config
2. เอกสาร Current ของ domain: Sleep System, Sensor/API contract, Architecture และ
   Operations Runbook
3. Onboarding: แผนที่และคำอธิบายที่คนอ่านง่าย โดยต้องไม่คัดลอกค่าที่เปลี่ยนบ่อย
4. Handover/Closure: หลักฐานของ Git SHA และ release ที่ตรวจ ณ เวลาหนึ่ง
5. Pilot, Case study, Research และ Archive: หลักฐานประกอบ ไม่เปลี่ยน Runtime เอง

ลำดับนี้บอกวิธีตรวจพฤติกรรมที่ใช้อยู่ ไม่ได้ให้เอกสารลบล้างคำสั่งเปลี่ยนระบบของ
เจ้าของ เมื่อพบความขัดกันให้ระบุ SHA และแก้เอกสาร/contract ส่วนที่ได้รับผลก่อน
เผยแพร่ใหม่ ไม่หยุดบริการหรือซ่อนคะแนนเดิมเพียงเพราะข้อความเก่าไม่ตรงกัน

## เอกสารหลัก

| เรื่อง | เอกสารที่มีอำนาจ | ใช้สำหรับ |
|---|---|---|
| เริ่มงานสมาชิกใหม่ | [ZEEP v1 Team Onboarding](onboarding/README.md) | จุดเริ่มหลัก: เส้นทางอ่านตามบทบาท, Lifecycle, Hardware, API/Data/Privacy และ First-week checklist |
| สถานะรุ่นล่าสุด | [Current Status](current-status.md) | SHA ที่ตรวจ, ความสามารถปัจจุบัน, Baseline แต่ละชนิด และขอบเขตผล Rerun |
| Tech stack และเครื่องมือ | [Technology Stack, Data และเครื่องมือ](onboarding/technology-stack-and-tools.md) | Orientation ของ Runtime, Frontend, Database, Protocol, QA และ Operations; package/config จริงยังเป็น source of truth |
| ส่งมอบและ Code Freeze | [v1 System Handover and Freeze Readiness](zeep-v1-system-handover-and-freeze-readiness.md) | Lifecycle ครบวงจร, invariant, test gate และรายการลงนามก่อน Freeze |
| ภาพรวมระบบ | [Pi 5 Software Architecture](pi5-software-architecture.md) | ขอบเขต module, dependency และลำดับ refactor |
| ปฏิบัติการเครื่อง | [Pi 5 Operations Runbook](pi5-operations-runbook.md) | Pull, verified Pod sync, test, deploy, backup, restart และ recovery |
| Sleep State และคะแนน | [Sleep System Current](zeep-sleep-system-current.md) | Runtime, replay, Sleep Score และ Recovery Score |
| หลักฐาน Baseline | [Sleep-State Baseline v1.8](zeep-sleep-state-baseline-v1.8.md) | Feature, gate, transition และขอบเขตการกล่าวอ้าง |
| Historical promotion | [Sleep History Promotion Policy v2](sleep-history-promotion-policy-v2.md) | Guard และ audit เมื่อเขียน derived result ย้อนหลัง |
| ผลลัพธ์ผู้ใช้ | [Session Result Presentation v1](zeep-session-result-presentation-v1.md) | ภาษากับลำดับข้อมูลบนหน้าผลลัพธ์ |
| Restore Summary | [Restore Summary v1](zeep-restore-summary-v1.md) | คำอธิบายคะแนนโดยไม่สร้างคะแนนที่สาม |
| คำแนะนำหลังพัก | [Post-rest Advice](zeep-post-rest-advice.md) | หลักฐาน → คำแนะนำหนึ่งข้อ, เหตุผล, ช่วงเวลา และ additive API fields |
| User learning | [User Learning Profile v1](zeep-user-learning-profile-v1.md) | ประวัติรายบุคคล, Baseline และ AI context |
| Adaptive recommendation | [Adaptive Coach Plan v1](adaptive-control-recommendation-plan-v1.md) | Recommendation-first; ไม่สั่งอุปกรณ์อัตโนมัติ |
| Adaptive live data | [Adaptive Data Foundation v1](adaptive-control-data-foundation-v1.md) | ข้อมูล live สำหรับ Monitor และ shadow model |
| API | [ZEEP API v1](zeep-api-v1.md) | คู่มือ endpoint สำหรับทีมแอป |
| API schema | [API Schema Reference v1](zeep-api-schema-reference-v1.md) | Field, enum, privacy และ response contract |
| Sensor interface | [Sensor Interface Contract v1.2](zeep-sensor-interface-contract-v1.2.md) | ESP32/BCG field, validity และ provenance |
| Device/Fleet health | [Device Contract และ Fleet Health v1](device-contract-and-fleet-health-v1.md) | Identity, Firmware provenance, freshness, quality และ AI control boundary |
| แผนอุปกรณ์รุ่นถัดไป | [Redundant Sensors และ Device Expansion v1](zeep-redundant-sensors-and-device-expansion-v1.md) | **DESIGN PROPOSAL**: เซนเซอร์หลัก/สำรอง, Hub, Power, Air, Film, Ion/Ozone, Foot Warmer และระบบน้ำ; ยังไม่ใช่รายการติดตั้งจริง |
| Respiratory wellness | [Respiratory Wellness v1.2](zeep-respiratory-wellness-v1.md) | การสรุป HR/RR เชิง Wellness |
| Product language | [Product Language Guideline v1.2](zeep-product-language-guideline-v1.md) | คำสั้น กระชับ เป็นมิตร และไม่วินิจฉัย; [ผลตรวจเนื้อหา 19 ก.ย.](reviews/2026-09-19-interface-content-review.md) |
| Interface map และ UI | [Interface Map & UI Standard v1](zeep-interface-map-and-ui-standard-v1.md) | หน้าที่ทุกหน้า ลำดับข้อมูล Touch/Type/Icon และ viewport QA |
| Interface development | [UI Development Roadmap](zeep-interface-development-roadmap.md) | แผนร่วมเทคนิค/UX/ข้อมูล/ศิลปะ, สถานะจริง, คำไทย และงาน P0–P2 พร้อมเกณฑ์รับงาน |
| Smart Senses | [ภาพรวมหลายเซนเซอร์](onboarding/smart-senses.md) | ขอบเขตปัจจุบัน ห้าด้าน แผน R&D และข้อแตกต่างจากพิมพ์เขียวภายนอก |
| Smart Ear / Acoustic Intelligence | [โมดูลเสียง · DSP Plan](onboarding/smart-ear-dsp-plan.md) | ส่วนหนึ่งของ Smart Senses; Level timeline และ Firmware DSP markers เป็น **ADMIN SHADOW** |
| Firmware | [Firmware Index](../firmware/README.md) | Sensor Hub 1 source, DSP, calibration และขั้นตอน Flash/rollback |
| Pilot สองโหมด | [Pilot Two-Mode Protocol](zeep-pilot-two-mode-protocol.md) | Overnight Recovery และ Nap & Refresh |
| Evidence library | [Research Evidence Library](../research/evidence-library/README.md) | แหล่งอ้างอิง, checksum และ verification |

## หลักฐาน Regression ที่ยังใช้งาน

- [N3 Baseline Review · 22 September 2026](reviews/2026-09-22-n3-baseline-review.md) · source candidate, read-only cohort audit, ยังไม่ Deploy
- [Smart Senses Integration · 22 September 2026](reviews/2026-09-22-smart-senses-integration.md)
- [Interface Roadmap Review · 19 September 2026](reviews/2026-09-19-interface-roadmap-review.md)
- [Runtime Multi-agent Audit · 19 September 2026](reviews/2026-09-19-runtime-audit.md)
- [ผล Rerun และ Sync · 19 September 2026](reviews/2026-09-19-after-rest-rerun.md)
- [Pi 5 / ESP Hardware Audit · 19 September 2026](audits/pi5-esp-system-audit-2026-09-19.md)
- [Wake Lock-in Regression Register](zeep-wake-lock-regression-register.md)
- [Case Study CS-01](zeep-case-study-cs-01-two-overnight-sessions.md)
- [Brainwave Sound Lab](brainwave-sound-lab-v1.md)

[Documentation Archive](archive/README.md) เป็นข้อมูลประกอบ Audit เท่านั้น ไม่ใช่
Runtime contract และต้องไม่ถูกนำไปตั้ง Threshold หรืออธิบายพฤติกรรมปัจจุบันโดยตรง

Audit และ review ต้องคงวันที่/SHA เดิม ไม่แก้ผลตรวจเก่าให้ดูเหมือนผ่านรุ่นใหม่
ค่าที่เปลี่ยนบ่อยไม่คัดลอกซ้ำใน Onboarding; เชื่อมไปยังเอกสารเจ้าของเรื่องแทน

Source HTML ของ `monitor.pillarsnova.com/zeep-project/` ไม่ได้อยู่ใน repository นี้
จึงไม่ใช่เอกสาร Runtime ที่แก้จาก repo นี้ได้ ก่อนเผยแพร่ Monitor ต้องตรวจสถานะ
`LIVE / SHADOW / PILOT EVIDENCE / SIMULATION / ROADMAP / ARCHIVED`, Git SHA,
version และ privacy/consent ตาม checklist ใน Onboarding
