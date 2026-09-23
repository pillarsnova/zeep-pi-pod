# ทบทวนเอกสารและ Knowledge Hub · 22 กันยายน 2026

สถานะ: **Documentation review · Working tree บน Mac · ยังไม่ Deploy**

ฐานโค้ด: `5de1b2e260ac4c4b39c805d8f6f7e85054525294` บน `develop`
หลัง `git pull --ff-only origin develop` ซึ่งตอบ Already up to date
งาน Knowledge Hub ที่เตรียมไว้ก่อนหน้านี้ยังไม่ Commit; รอบนี้ไม่ทับหรือลบงานนั้น

## TL;DR

ปรับเอกสารให้แยก **Git / งานบน Mac / เครื่อง Pod / แผนพัฒนา** ชัดเจน
เพิ่มเติมแผนผังโมดูลหลัง Refactor และวิธี Build หน้าคู่มือ ไม่มีการเปลี่ยนสูตร
คะแนน, Sleep State, Sensor, API payload หรือข้อมูลย้อนหลัง

ข้อสำคัญ: Pod ที่ตรวจยังเป็น `78e90fc` ไม่ใช่ `5de1b2e`; `/handbook`
และ candidate N3 v1.30 ยังไม่ติดตั้งบน Pod ที่ตรวจ จึงยังต้องใช้หน้าคู่มือ Local/Offline

## หลักฐานจาก Pod แบบอ่านอย่างเดียว

ตรวจวันที่ 22 กันยายน 2026 เวลา 20:57 +07:

| รายการ | ผลที่อ่านได้ |
|---|---|
| Git SHA | `78e90fce216c81f8a72951fe113728763f3f5619` |
| Branch | `develop` |
| Working tree | สะอาด (`git status --short` ไม่มีรายการ) |
| Service | `zeep-pod.service` · active/running |
| Working directory | `/home/pod1/pi5` |
| Process เริ่มล่าสุด | 21 กันยายน 2026 12:33:29 +07 |
| Estimator ในไฟล์ policy | `bcg-audio-bed-5state-v1.29-complete-occupied-epochs` |
| Evidence ในไฟล์ policy | `zeep-sleep-state-evidence-v3.7-complete-occupied-epochs` |
| Baseline ในไฟล์ policy | `zeep-sleep-state-baseline-v1.8-sep1-cutover` |

หลักฐานนี้เป็น Git, systemd และไฟล์ policy ไม่ใช่การตรวจ Sensor, occupancy,
active Session, ความแม่นยำของโมเดล หรือค่าที่อ่านจากหน่วยความจำ Process
ไม่มีคำสั่ง Restart, Pull บน Pod, Flash หรือเขียนข้อมูลผู้พัก

## สิ่งที่แก้

| ส่วน | ก่อนทบทวน | หลังทบทวน |
|---|---|---|
| Current Status | Verification ยังอ้างฐาน `fa7bd07`; Refactor ระบุเฉพาะฐานก่อนแก้ | ระบุ Git `5de1b2e`, งานบน Mac และผลตรวจ Pod 20:57 แยกกัน |
| Onboarding / Index / README | มีลิงก์ `/handbook` แต่ไม่ได้ย้ำว่ายังไม่ Deploy | ระบุ Local/Offline ก่อน และทางเข้า Admin หลัง Deploy พร้อมลิงก์สถานะ |
| Architecture | ตาราง Adaptive ยังรวมหน้าที่ไว้ที่ composer; ไม่มี N3 modules | เพิ่ม Timeline series/view, learning quality/context/recommendations และ N3 policy/evidence |
| Technology Stack | ไม่รวมเครื่องมือสร้าง Knowledge Hub | เพิ่ม `markdown-it-py` เฉพาะ Dev/Build, catalog, renderer และ offline bundle |
| Operations | ยังไม่มีขั้นตอน rebuild คู่มือเมื่อเอกสารเปลี่ยน | เพิ่ม Build/Check, Commit ต้นทางพร้อม Bundle และแยกการติดตั้ง Route ครั้งแรก |
| Interface Map / Roadmap | Source range เก่า และ Route ใหม่ดูเหมือนติดตั้งแล้ว | แยก Working tree และขอบเขตการตรวจหน้าคู่มือจากหน้า Session/Control |
| API Schema / Result Presentation | หัวเอกสารทบทวน 19 ก.ย. แม้มีงาน Source เพิ่ม | ตรวจตัวอย่างกับ models/นโยบายปัจจุบัน ยืนยันว่าสัญญาผลลัพธ์เดิมไม่เปลี่ยน |
| Baseline references | ชื่อแสดง v1.8 ทั้งที่เนื้อหา Source เป็น v1.9 | แสดง v1.9 และอธิบายการคงชื่อไฟล์เดิม; Pod v1.8 แยกชัด |
| Continuity wording | ข้อความย่ออาจสับสนระหว่าง “สร้าง State ใหม่” กับ “คง State เดิม” | ระบุ occupied continuity พร้อม provenance ไม่ถือว่าการคง State เป็นหลักฐาน Sensor ใหม่ |
| Knowledge Hub | Bundle เก็บเนื้อหาก่อนทบทวน | สร้างใหม่จากต้นทางและเพิ่มรายงานฉบับนี้ในหมวดผลตรวจ |

## สิ่งที่ตรวจแล้วไม่ต้องเปลี่ยน

- Overnight Recovery → Sleep Score; Nap & Refresh → Recovery Score
- Sleep Score v2.1: เวลา 25 / ต่อเนื่อง 35 / โครงสร้าง 20 / HR/RR 10 / สิ่งแวดล้อม 10
- Recovery Score v3.1: เวลา 25 / HR/RR 35 / ความนิ่งและต่อเนื่อง 30 / สิ่งแวดล้อม 10
- Estimator Source v1.30 และ Baseline v1.9; N3 ต้องผ่าน Fit ของ HR และ RR
  แต่ละแกนอย่างน้อย 0.25 ร่วมกับ gate เดิม ค่านี้เป็น engineering guard ไม่ใช่เกณฑ์แพทย์
- Smart Senses เป็นภาพรวม; Smart Ear เป็นโมดูลเสียงแบบ Admin shadow
- Adaptive ยังแนะนำก่อน ไม่สั่งอุปกรณ์อัตโนมัติ
- API ตัวอย่าง Recommendation/Score และ version ที่ยืนยันกับ Source ยังตรงกัน

## Verification

ตรวจด้วยชุด focused สำหรับเอกสารและหน้าคู่มือ:

```bash
python -m documentation build
python -m documentation check
python -m unittest -q test_documentation_alignment test_handbook test_modular_architecture
python ui_composer.py check
git diff --check
```

ตรวจลิงก์ภายใน, ชนิดข้อมูลตัวอย่าง API, policy version, หน้าที่ของโมดูล และ
ความตรงกันของ Bundle กับ Markdown; รอบนี้ไม่เปลี่ยน CSS/JavaScript ของหน้าคู่มือ
และไม่ใช้ผลทดสอบเก่ารับรอง Deployment ใหม่
รายงาน Audit/Case study เดิมคงวันที่และผลเดิม ไม่แก้ย้อนหลังให้ดูเป็นผลตรวจรอบนี้

ผลตรวจรอบนี้: focused tests **43 รายการผ่าน**; ตรวจลิงก์ Markdown **65 ไฟล์**,
Knowledge Hub **59 บท / 10 หมวด** และไม่พบลิงก์หัวข้อภายในที่ไม่ตรงกับ Heading
`documentation check`, `ui_composer.py check` และ `git diff --check` ผ่าน
ตรวจ Browser หลัง Build อีกครั้งที่ 1440 และ 390 px: หน้าแรกแสดง 59 บท,
เปิด 5 บทหลักที่แก้และค้นหารายงานใหม่นี้ได้ ไม่พบข้อความล้นแนวนอนหรือ JavaScript error

เอกสารหลัก: [Current Status](../current-status.md) · [Onboarding](../onboarding/README.md) ·
[Architecture](../pi5-software-architecture.md) · [การดูแล Knowledge Hub](../../documentation/README.md)
