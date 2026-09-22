# N3 — ทบทวน Baseline และเงื่อนไขเข้า State

วันที่: 22 กันยายน 2026 · ขอบเขต: Sleep Wellness

สถานะ: **Source candidate สำหรับ Commit/Push — ยังไม่ Deploy/Restart หรือเขียนผลย้อนหลัง**

## TL;DR

พบช่องโหว่ที่ตรวจซ้ำได้: N3 gate เดิมตรวจความต่างระหว่าง N2/N3 Fit แต่ไม่ตรวจ
ความใกล้ช่วงอ้างอิงแบบแยกแกน จึงอาจผ่านเมื่อ RR Fit ของทั้งสอง State ต่ำมาก
ส่วน HR และความนิ่งสนับสนุน N3 ข้อค้นพบนี้ไม่ใช่หลักฐานว่าผู้ใช้ไม่ได้หลับลึกจริง

รุ่น candidate เพิ่ม `HR fit >= 0.25 AND RR fit >= 0.25` ก่อนใช้ N3 gate เดิม
ตัวเลขเป็นเกณฑ์วิศวกรรมที่ต้องติดตามผล ไม่ใช่ค่าปกติทางการแพทย์หรือโอกาส N3
25% ไม่แก้ตารางประชากรทุก State จากผู้ใช้คนเดียว ไม่บังคับ RR ลดลง และไม่ห้าม
N3 ในการงีบ ไม่แก้สูตร Sleep Score/Recovery Score หรือ Raw

## 1. Baseline ที่ต้องแยกให้ชัด

| ชั้นอ้างอิง | ใช้ข้อมูลใด | ใช้ทำอะไร / ไม่ใช้ทำอะไร |
|---|---|---|
| ผู้ใหญ่ขณะพักทั่วไป | MedlinePlus: HR 60–100 และ RR 12–18 ครั้ง/นาที | อธิบายบริบทสุขภาพทั่วไป ไม่ใช่ช่วงขณะหลับหรือเกณฑ์เข้า N3 |
| ช่วงอ้างอิงของโมเดล | `AGE_SLEEP_BASELINES` ใน policy; ช่วงซ้อนทับกันตามวัย | จัดลำดับความใกล้เคียง ไม่ใช้แทน PSG และไม่ถือว่าเป็น normative dataset ที่ผ่าน validation |
| ผู้ใช้ใน Session นี้ | ช่วงตั้งต้นประมาณ 5 นาที; awake reference ที่ตรึงหลัง onset | เทียบการเปลี่ยนจากช่วงตั้งต้น ร่วมกับ waveform/การขยับ ไม่กำหนดว่าทุกคนต้องลด RR |
| ประวัติเฉพาะบุคคล | Session ก่อนหน้าที่มี HR/RR คู่กันและคุณภาพพอ แยกตามโหมด | ใช้อธิบายแนวโน้มและความมั่นใจ; direct stage influence ยังปิด ไม่ใช้ label ที่โมเดลสร้างเองเป็น N3 ground truth |

ช่วงตั้งต้น N3 ที่ยังคงไว้ใน policy (ไม่ใช่ขอบเขตปกติทางการแพทย์):

| อายุ | HR ครั้ง/นาที | RR ครั้ง/นาที |
|---|---:|---:|
| ไม่ระบุ | 50–72 | 10–17 |
| 18–29 | 50–67 | 10–16 |
| 30–44 | 51–68 | 10–16 |
| 45–59 | 52–70 | 10–17 |
| 60+ | 53–72 | 10–17 |

ระบบเดิมมี HR offset +2 เมื่อ profile ระบุหญิง; รอบนี้ไม่ได้เปลี่ยนหรือรับรอง
ความแม่นยำของ age/sex adjustment ดังกล่าว ช่วงของ W/N1/N2/REM ไม่เปลี่ยน
และไม่มีการตั้งค่าตามเชื้อชาติขึ้นใหม่

`baseline_interval_proximity` ให้ค่า Fit ตามระยะห่างจากช่วงและจุดกึ่งกลาง
เมื่ออยู่ในช่วง Fit ≥0.863; floor 0.25 จงใจยอมให้เลยขอบได้บางส่วนเพื่อไม่ทำเป็น
hard physiological cutoff อย่างไรก็ตามยังเสี่ยงพลาดผู้ที่มี HR/RR ต่างจาก prior
จึงต้องตรวจทั้ง false-positive และ false-negative ไม่ถือว่าการลดจำนวน N3 คือความแม่นยำที่ดีขึ้น

## 2. เคสที่ตรวจพบ

พบการเสนอ N3 ระหว่างการพักช่วงสั้น โดย HR และความนิ่งสนับสนุน แต่ RR
อยู่นอกช่วงอ้างอิง N3 ที่โมเดลใช้ การเพิ่มของ RR เพียงอย่างเดียวไม่ได้พิสูจน์
ว่าไม่ใช่ N3 ปัญหาที่ตรวจได้คือความไม่สอดคล้องกับ prior ของระบบเอง

รายงานสาธารณะนี้ไม่เผยแพร่ชื่อ อีเมล รหัส Session เวลาจริง หรือค่าชีวสัญญาณ
รายบุคคล ชุดทดสอบใช้ **ตัวอย่างจำลอง** HR 60, RR 21 ครั้ง/นาที เทียบฐานตื่น
65 และ 19 ตามลำดับ ร่วมกับความแปรปรวนต่ำและไม่มีการขยับ เพื่อจำลองกลไก
HR สนับสนุนแต่ RR Fit ต่ำ ตัวเลขจำลองไม่ใช่ข้อมูลของผู้ทดสอบ
**candidate ใหม่ไม่อนุญาตให้ตัวอย่างนี้เริ่ม N3** แต่ไม่อ้างว่ารู้ State จริงของผู้ใช้

ข้อความเดิม “หลักฐาน HR/RR ต่ำ” จึงไม่ตรงกับข้อมูลทุกครั้ง เปลี่ยนเป็น
“ชีพจรและการหายใจสอดคล้องกับช่วงอ้างอิง N3 พร้อมหลักฐานความนิ่งและการหายใจสม่ำเสมอ”
เฉพาะทางเดินที่หลักฐาน N3 ผ่านเกณฑ์

## 3. ตรวจข้อมูลย้อนหลังแบบอ่านอย่างเดียว

อ่าน `sessions.db` ด้วย `mode=ro` และ `PRAGMA query_only=ON` จาก Pod 1
ไม่คัดลอกชื่อ/อีเมล เวลาจริงรายบุคคล หรือ raw waveform เข้า Git
เลือก Session จบแล้วตั้งแต่ 1 ก.ย. 2026 เวลาไทย และระยะเวลา ≥25 นาที
อ่านเฉพาะ `sleep_stage` events ที่ mean HR/RR เป็นค่าบวกและ finite
นี่เป็น feature-event audit ไม่ใช่การยืนยันคุณภาพ BCG ใหม่จาก Raw

| rest_mode ใน DB | Sessions | หน้าต่างที่มี HR/RR | ช่วงค่ากลาง HR ต่อ Session | ช่วงค่ากลาง RR ต่อ Session |
|---|---:|---:|---:|---:|
| Nap (`nap_recovery`) | 13 | 1,319 | 62.8–87.9 | 14.3–19.2 |
| Overnight (`sleep`) | 9 | 8,313 | 57.91–70.95 | 13.8–18.1 |
| แถว DB ไม่ระบุโหมด | 22 | 7,246 | 51.5–90.0 | 13.53–21.0 |
| รวม | 44 | 16,878 | — | — |

ไม่ได้ใช้ historical mode resolver ใน audit นี้ จึงไม่เหมารวม 22 รายการเป็น Nap
และไม่ย้ายประเภท Session ค่าในตารางเป็น observed session medians รวมหลาย State
ไม่ใช่ healthy population reference หรือ N3 baseline

ใน 9 Overnight พบ N3 gate เดิมผ่าน 567 หน้าต่าง โดย RR Fit ต่ำกว่า 0.25 จำนวน
109 หน้าต่าง (ประมาณ 19.2%) เกณฑ์แยกแกนใหม่จะไม่รับหน้าต่างเหล่านี้เป็นหลักฐาน
เริ่ม N3 ส่วน Nap จบแล้ว 13 รายการไม่มีหน้าต่าง N3 gate ผ่านใน audit นี้
Session ที่กำลังใช้งานไม่รวมในตาราง completed cohort หรือผลรวมข้างต้น

เป็นการตรวจเงื่อนไข RR ย้อนหลัง ไม่ใช่ full sequential replay ของ candidate
จึงไม่แปลง 109 หน้าต่างเป็นนาทีหลับลึกที่ผิด ไม่ประกาศคะแนนใหม่ หรืออัตราความแม่นยำ
และไม่สรุปว่าการตื่นจริง/การหลับจริงถูกแก้ครบแล้ว

## 4. การแก้ใน source

- `sessions/sleep_baseline_support.py`: pure helper ตรวจ HR/RR fit แยกกัน
  รวม invalid/missing/non-finite และ reason codes
- `sleep_stage_scoring.py`: live และ historical scorer ใช้ helper เดียวกัน
  ก่อน N3 gate เดิม เพิ่ม `sleep_evidence.n3_baseline_support` สำหรับ audit
- `sleep_system_policy.py`: floor 0.25 และ policy snapshot; estimator v1.30,
  evidence v3.8, baseline v1.9, replay v29, pipeline v1.13
- `sessions/live_sleep_estimator.py`: แก้คำอธิบายที่เหมารวมว่า RR ต่ำ
- ไม่เปลี่ยน 35% fit-continuity, confirmation 60 วินาทีของ N3, N2 confirmation
  120 วินาที, 10/30 วินาที cadence, State graph, occupancy หรือคะแนน

## 5. ข้อจำกัดที่ยังต้องติดตาม

1. Continuity เดิมยังคง State ก่อนหน้าเมื่อหลักฐานใหม่ไม่ชัด การเพิ่ม entry guard
   **ไม่ได้แก้ N3 ที่ค้างจากการ carry ไปแล้วโดยอัตโนมัติ** และไม่ได้ตัดเวลาออกจากคะแนน
2. ยังไม่มี PSG จึงไม่มี label อิสระสำหรับพิสูจน์ N3 จริง ข้อมูลผู้ทดสอบช่วยระบุ
   ข้อสงสัยและเวลา Wake ได้ แต่ไม่เท่ากับการวัดคลื่นสมอง
3. RR ที่สม่ำเสมอแต่เร็วกว่าประชากรอาจถูก guard ปฏิเสธ ควรศึกษา personal
   respiratory reference ที่ไม่เรียนรู้วนจาก label ผิด ก่อนเปิด direct influence
4. การนำขึ้นตู้ต้องตรวจ Git SHA อีกครั้ง: Mac เริ่มจาก `96d19f8`, Pod `78e90fc`;
   core scorer/policy/live estimator/context ตรงกันก่อนแก้ แต่ commit ของ UI ต่างกัน

## Verification

- ทดสอบ helper, synthetic HR/RR-conflict case, constant-RR control, ทุกกลุ่มอายุ,
  invalid values และ waveform/movement gates ร่วมกับ regression เดิม
- ผ่าน **292 tests**: baseline support, signal features, baseline policy,
  system consistency, restart context, historical runtime/storage/reclassification,
  session reports, Recovery guardrails, evidence registry และ documentation
- Ruff check/format ผ่านสำหรับ helper และ live estimator; registry check ผ่าน
  33 sources พร้อม Markdown↔JSON lock และ protocol register; `git diff --check` ผ่าน
- `quality_gate.py changed` ผ่านเพิ่มเติม: 260 tests รวม Session lifecycle,
  start/finalization/cadence/occupancy และ compilation (มีรายการซ้ำกับชุด 292;
  ไม่ให้นำสองจำนวนมาบวกเป็นจำนวน test ที่ไม่ซ้ำ)
- ไม่ได้รัน full application suite หรือ full sequential Raw replay ในรอบนี้
- ไม่ Restart, ไม่เปลี่ยน Raw, ไม่เขียนฐานข้อมูลหรือผลคะแนนบน Pod

## หลักฐานอ้างอิง

ส่วนต่อเนื่องตามคำขอเจ้าของระบบ: เพิ่ม **เพศ × ช่วงอายุ × BMI** เป็น
`health_reference.baseline_context` และแสดงใน Admin จาก snapshot ของ Session
ดูรายละเอียดและตารางแยกชาย/หญิงที่ [Baseline](../zeep-sleep-state-baseline-v1.8.md)
ไม่เปลี่ยน HR/RR ranges เดิมจาก BMI; ยังไม่ Deploy และไม่ Rerun ผลจริง
ทะเบียนหลังเพิ่ม HLT-005/006 มี 35 รายการ ส่วนผลตรวจ 33 รายการข้างต้นเป็น
หลักฐานรอบก่อนเพิ่ม demographic context ไม่ใช่จำนวนปัจจุบัน
หลังเพิ่มส่วนนี้ `quality_gate.py changed` ผ่าน **408 tests** พร้อม lint/format,
UI composer, registry และ compilation; frontend suite แยกผ่าน **68 tests**
(มีการรันซ้ำผ่าน wrapper ใน focused gate ไม่ให้นับบวกรวมเป็นจำนวนที่ไม่ซ้ำ)
การตรวจนี้เป็น synthetic/code verification ไม่ใช่ browser viewport QA หรือ
การทดสอบความแม่นยำ N3 กับมนุษย์จริง

ทะเบียนและข้อจำกัดรายแหล่ง: [Source Register](../../research/evidence-library/SOURCE_REGISTER.md)

- **SLP-012:** งาน PSG การงีบในผู้ใหญ่สุขภาพดีวัยหนุ่มสาว พบ N3 และการเปลี่ยน
  ของ cardiac autonomic activity; EDR ไม่ต่างอย่างมีนัยสำคัญระหว่าง State
  จึงไม่ใช้ข้อกำหนด “RR ต้องลดเสมอ” งานนี้ไม่รองรับเลข Fit 0.25 ของ ZEEP
- **SLP-013 / SLP-006:** ระยะการนอนอาศัยหลักฐานกิจกรรมสมอง การใช้ HR/RR/BCG
  ของเราเป็นการประมาณ ไม่ใช่นิยาม N3 ใหม่
- **HLT-004:** กรอบ vital signs ผู้ใหญ่ขณะพักทั่วไป แยกจากการหลับ
- **SLP-002–005:** Cardiorespiratory staging และข้อจำกัดการเทียบ consumer BCG
  กับ PSG; ไม่ใช้ความใกล้ baseline เพียงตัวเดียวรับรองผล
