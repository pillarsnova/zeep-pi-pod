# ZEEP Pi 5 Documentation Index

สถานะ: **Current document map**

เจ้าของ: Pi 5 application team

อัปเดตล่าสุด: 16 กันยายน 2026

เอกสารในตารางนี้เป็นชุดที่ทีมใช้พัฒนา ตรวจสอบ และส่งมอบระบบปัจจุบัน
เอกสารทดลองหรือรายงาน dry-run ที่ถูกแทนที่แล้วไม่เก็บปะปนใน working tree;
ประวัติเดิมยังตรวจสอบได้จาก Git เมื่อจำเป็น

## เอกสารหลัก

| เรื่อง | เอกสารที่มีอำนาจ | ใช้สำหรับ |
|---|---|---|
| เริ่มงานสมาชิกใหม่ | [ZEEP v1 Team Onboarding](onboarding/README.md) | เส้นทางอ่านตามบทบาท, Lifecycle, Hardware map, API/Data/Privacy และ First-week checklist |
| ส่งมอบและ Code Freeze | [v1 System Handover and Freeze Readiness](zeep-v1-system-handover-and-freeze-readiness.md) | Lifecycle ครบวงจร, invariant, test gate และรายการลงนามก่อน Freeze |
| ภาพรวมระบบ | [Pi 5 Software Architecture](pi5-software-architecture.md) | ขอบเขต module, dependency และลำดับ refactor |
| ปฏิบัติการเครื่อง | [Pi 5 Operations Runbook](pi5-operations-runbook.md) | Pull, verified Pod sync, test, deploy, backup, restart และ recovery |
| Sleep State และคะแนน | [Sleep System Current](zeep-sleep-system-current.md) | Runtime, replay, Sleep Score และ Recovery Score |
| หลักฐาน Baseline | [Sleep-State Baseline v1.8](zeep-sleep-state-baseline-v1.0.md) | Feature, gate, transition และขอบเขตการกล่าวอ้าง |
| Historical promotion | [Sleep History Promotion Policy v2](sleep-history-promotion-policy-v2.md) | Guard และ audit เมื่อเขียน derived result ย้อนหลัง |
| ผลลัพธ์ผู้ใช้ | [Session Result Presentation v1](zeep-session-result-presentation-v1.md) | ภาษากับลำดับข้อมูลบนหน้าผลลัพธ์ |
| Restore Summary | [Restore Summary v1](zeep-restore-summary-v1.md) | คำอธิบายคะแนนโดยไม่สร้างคะแนนที่สาม |
| User learning | [User Learning Profile v1](zeep-user-learning-profile-v1.md) | ประวัติรายบุคคล, Baseline และ AI context |
| Adaptive recommendation | [Adaptive Coach Plan v1](adaptive-control-recommendation-plan-v1.md) | Recommendation-first; ไม่สั่งอุปกรณ์อัตโนมัติ |
| Adaptive live data | [Adaptive Data Foundation v1](adaptive-control-data-foundation-v1.md) | ข้อมูล live สำหรับ Monitor และ shadow model |
| API | [ZEEP API v1](zeep-api-v1.md) | คู่มือ endpoint สำหรับทีมแอป |
| API schema | [API Schema Reference v1](zeep-api-schema-reference-v1.md) | Field, enum, privacy และ response contract |
| Sensor interface | [Sensor Interface Contract v1.2](zeep-sensor-interface-contract-v1.2.md) | ESP32/BCG field, validity และ provenance |
| Respiratory wellness | [Respiratory Wellness v1.1](zeep-respiratory-wellness-v1.md) | การสรุป HR/RR เชิง Wellness |
| Product language | [Product Language Guideline v1](zeep-product-language-guideline-v1.md) | คำสั้น กระชับ เป็นมิตร และไม่วินิจฉัย |
| Pilot สองโหมด | [Pilot Two-Mode Protocol](zeep-pilot-two-mode-protocol.md) | Overnight Recovery และ Nap & Refresh |
| Evidence library | [Research Evidence Library](../research/evidence-library/README.md) | แหล่งอ้างอิง, checksum และ verification |

## หลักฐาน Regression ที่ยังใช้งาน

- [Wake Lock-in Regression Register](zeep-wake-lock-regression-register.md)
- [Case Study CS-01](zeep-case-study-cs-01-two-overnight-sessions.md)
- [Brainwave Sound Lab](brainwave-sound-lab-v1.md)

ไฟล์ใน `docs/archive/` เป็นข้อมูลประกอบ audit เท่านั้น ไม่ใช่ runtime contract
และต้องไม่ถูกนำไปตั้ง threshold หรืออธิบายพฤติกรรมปัจจุบันโดยตรง
