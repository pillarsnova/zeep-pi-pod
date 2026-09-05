# ZEEP Field Case Study CS-01 — การพักค้างคืนสองครั้ง

> **ประเภทเอกสาร:** Internal engineering case study · PDPA-minimized  
> **รหัสผู้ทดสอบ:** CS-01; ตารางเชื่อมรหัสกับบัญชีจริงไม่อยู่ใน Git repository  
> **ขอบเขต:** ZEEP Sleep Wellness — ไม่ใช่การวินิจฉัยหรือผลตรวจจาก PSG  
> **สถานะ:** ยืนยันปัญหาเชิง forensic แล้ว; แนวทางแก้ต้องผ่าน replay และ regression  
> **ปรับปรุงล่าสุด:** 2026-09-05

เอกสารนี้ไม่มีชื่อ อีเมล ชื่อบัญชี รหัส Session แบบถาวร Raw BCG หรือข้อความ
สัมภาษณ์แบบคำต่อคำ รายละเอียดระบุตัวบุคคลและ re-identification key ต้องเก็บใน
ระบบที่จำกัดสิทธิ์และอยู่นอก repository ตามหลัก data minimization

เอกสารที่เกี่ยวข้อง:

- [ระบบ Sleep/Recovery ปัจจุบัน](zeep-sleep-system-current.md)
- [หลัก Baseline ของ Sleep State](zeep-sleep-state-baseline-v1.0.md)
- [ขั้นตอน Pilot แบบสองโหมด](zeep-pilot-two-mode-protocol.md)

## TL;DR

- CS-01 ใช้ Overnight Recovery สองครั้ง คืน A ได้ Sleep Score 61 แต่รายงานว่า
  ตื่นหนึ่งครั้งและรู้สึกสดชื่น การตรวจ event/timeline พบ Wake ต่อเนื่อง 61 นาที
  ที่ไม่สอดคล้องกับ HR และการเคลื่อนไหว จึงจัดเป็น estimator artifact ที่ต้องแก้
- คืน B ได้ Sleep Score 88, จำนวนตื่นสองครั้งสอดคล้องกับคำบอกเล่า และ Sensor
  ยืนยันอุณหภูมิต่ำสุด 16.7°C ซึ่งต่ำกว่า ZEEP operating floor 18°C
- การแก้คืน A แบบ shadow estimate ให้การตื่นหนึ่งครั้ง, WASO ประมาณ 5 นาที และ
  Sleep Score ประมาณ 85+ ตัวเลขนี้เป็น **ค่าประมาณเพื่อพัฒนา** ไม่ใช่ผลที่แก้แล้ว
  หรือผล clinical validation
- เคสนี้ยืนยันความจำเป็นของสามระบบร่วมกัน: consistency guard ระหว่าง
  Cardio/Movement, feedback หลังตื่นแบบสั้น และ alert สภาพแวดล้อมตามเวลา

## 1. ผลสองครั้ง

| ตัวชี้วัด | คืน A | คืน B |
|---|---:|---:|
| Sleep Score ที่บันทึก | 61 | 88 |
| การตื่นที่ระบบนับ | 3 | 2 |
| การตื่นที่ผู้ทดสอบจำได้ | 1 | 2 |
| WASO ที่บันทึก | 62.5 นาที | 5 นาที |
| Estimated sleep | 4.15 ชม. | 5.94 ชม. |
| Sleep efficiency | 79% | 93% |
| Sleep-onset proxy | 6.5 นาที | 22 นาที |
| ความรู้สึกหลังตื่น | สดชื่นกว่าอีกคืน | สบาย แต่หนาวช่วงกลางคืนและสดชื่นน้อยกว่า |
| ผลตรวจไขว้ | พบ Wake artifact และการนับ awakening ซ้ำ | จำนวนตื่นและอุณหภูมิสอดคล้องกับคำบอกเล่า |

ผู้ทดสอบรายงาน baseline ก่อนเข้า Pilot ว่าปกติตื่นประมาณ 4–5 ครั้งต่อคืน การลดลง
เหลือหนึ่งและสองครั้งเป็นสัญญาณเชิงประสบการณ์ที่ควรติดตามต่อ แต่ยังสรุป causal
effect ของ ZEEP ไม่ได้จากผู้ทดสอบหนึ่งรายและสองคืน

## 2. สถานะของหลักฐาน

| ระดับ | สิ่งที่ใช้ในเคสนี้ |
|---|---|
| บันทึกโดยระบบ | Sleep Score, Stage events, HR/RR, Bed Status, อุณหภูมิ และเวลาบันทึก |
| รายงานโดยผู้ทดสอบ | จำนวนครั้งที่จำได้ว่าตื่น ความสดชื่น ความสบาย และความหนาว |
| ข้ออนุมานจาก forensic | Wake 61 นาทีไม่สอดคล้องกับ Cardio/Movement และเป็น artifact ของ estimator path |
| ข้อเสนอเพื่อทดสอบ | ตรึง awake reference, รักษา onset state ผ่าน signal gap, รวม Wake bout รอบ bed exit |
| ยังไม่ยืนยัน | Sleep Score คืน A ประมาณ 85+ จนกว่าจะ replay ด้วยรุ่นแก้ไขและผ่าน acceptance criteria |

## 3. กลไกความผิดพลาด

### 3.1 Wake lock-in หลัง signal gap

ช่วงที่ระบบติดป้าย Wake ต่อเนื่อง 61 นาทีมี HR เฉลี่ย 66.5 bpm ใกล้กับช่วง N2
ข้างเคียง การเคลื่อนไหวต่ำ และไม่พบ Bed Exit ภายใน bout แต่ state context กลับ
สูญเสีย `sleep_onset_established` หลัง signal gap ขณะที่ `awake_hr_reference`
เลื่อนลงมาใกล้ HR ขณะหลับ ทำให้ re-onset gate ผ่านได้ยากและ Wake ค้างต่อเนื่อง

รูปแบบปัญหา:

`temporary signal gap → onset context lost → awake anchor drifts → re-onset blocked`

ข้อสรุปนี้สนับสนุนให้ fail-closed gate มี state continuity และ recovery path
ของตนเอง การ fail-closed โดยไม่มี recovery path สามารถเปลี่ยน missing evidence
เป็น Wake ที่มั่นใจเกินจริงได้

### 3.2 Awakening ถูกแบ่งด้วย Off-bed

การตื่นจริงหนึ่งเหตุการณ์มีช่วงลุกจากเตียงคั่นอยู่ ชั้นรายงานเดิมแบ่ง Wake ก่อนและ
หลัง Off-bed เป็นคนละเหตุการณ์ จึงนับเกินจริง การนับระดับ Session ควรรวม bout ที่
เชื่อมกันด้วย Bed Exit เดียวเป็น awakening เดียว และแสดง Off-bed duration แยก
โดยไม่สร้าง Sleep State ระหว่างไม่มีผู้ใช้อยู่บนเตียง

## 4. ข้อกำหนดการปรับปรุง

1. Freeze หรือจำกัดการเลื่อน `awake_hr_reference` หลังยืนยัน Sleep onset
2. รักษา `sleep_onset_established` เมื่อ signal gap เป็นเพียงช่วงสั้น และกำหนด
   timeout/re-onset path แบบมีเพดานชัดเจน
3. รวม Wake bouts ที่อยู่รอบ Bed Exit เดียวในชั้น Session report
4. หาก Wake มี HR ต่ำกว่าฐานร่วมกับ movement ต่ำต่อเนื่อง ให้ลด confidence และ
   ส่งเข้า review flag แทนการยืนยัน Wake จากหลักฐานด้านเดียว
5. แจ้งเตือน Admin เมื่ออุณหภูมิหลุด ZEEP operating band ระหว่าง Session พร้อม
   timestamp และ actuator context สำหรับตรวจ AC pull-down
6. เก็บ feedback หลังตื่นแบบสั้นเพื่อเปรียบเทียบ objective กับ subjective data
7. ห้ามแก้ Raw data; การ reclassify/rescore ต้องเก็บ model version และ audit trail

## 5. Regression acceptance criteria

ชุด replay ที่ได้รับอนุมัติต้องยืนยันว่า:

- Wake artifact 61 นาทีของคืน A หายไปหรือถูกลด confidence เป็นหลักฐานไม่พอ
- การตื่นจริงที่เชื่อมกับ Bed Exit ยังคงอยู่หนึ่งเหตุการณ์ ไม่ถูกลบตาม artifact
- Off-bed ไม่ถูกนับเป็น W/N1/N2/N3/REM แต่เชื่อมกับ occupancy timeline ได้
- คืน B ยังรักษาการตื่นสองเหตุการณ์และลำดับ Sleep State เดิมที่ผ่านการตรวจ
- Session ที่มีรูปแบบคล้ายกันอีกสองชุดไม่เกิด Wake lock-in เดิม
- ผลใหม่ระบุ estimator/policy/report version และเก็บผลเดิมไว้ใน audit trail
- อุณหภูมิ 16.7°C สร้าง Admin alert โดยไม่เปลี่ยน Sleep State โดยตรง

Regression fixture ที่เข้า Git ต้องเป็นข้อมูลสังเคราะห์หรือ feature aggregate ที่
ย้อนกลับไปยังบัญชีจริงไม่ได้ Raw BCG และ mapping key ของ CS-01 ไม่อนุญาตให้ commit

## 6. ผลกวาดตรวจเชิงระบบ

การตรวจย้อนหลังพบรูปแบบ Wake หลัง onset ที่มี movement ต่ำและไม่มี Bed Exit ใน
ผู้ทดสอบ coded สามราย โดย bout ยาวประมาณ 16.5, 24.5 และ 61 นาที ทุก bout มี
`sleep_onset_established=False` ต่อเนื่อง รูปแบบที่เกิดซ้ำข้ามผู้ใช้สนับสนุนว่าเป็น
systemic estimator failure mode ไม่ใช่ข้อยกเว้นของ CS-01 เพียงรายเดียว

ผลนี้ยังไม่อนุญาตให้เปลี่ยนทุก long Wake เป็น Sleep โดยอัตโนมัติ แต่กำหนดให้ระบบ
ต้องตรวจ Cardio, Movement, occupancy, signal integrity และ transition context
ร่วมกันก่อนยืนยัน Wake หรือเปลี่ยนย้อนหลัง

## 7. ข้อจำกัดและการใช้ผล

- ZEEP ใช้ BCG และ Sensor เพื่อทำ Wellness estimate ไม่ใช่ AASM/PSG scoring
- คำบอกเล่าหลังตื่นมี recall bias และอาจไม่นับ micro-awakening
- Shadow score 85+ เป็น engineering estimate จนกว่าจะ replay ด้วยรุ่นที่แก้แล้ว
- สองคืนของคนเดียวเป็น case evidence สำหรับแก้ระบบ ไม่ใช่หลักฐานประสิทธิผลทั่วไป
- การสื่อสารภายนอกใช้ผลรวมแบบไม่ระบุตัวบุคคลและต้องผ่านผู้รับผิดชอบ Pilot/PDPA

**ข้อสรุป:** CS-01 แสดงให้เห็นว่าการนำ subjective feedback, physiology,
movement, occupancy และ environment มาตรวจไขว้กันสามารถค้นพบทั้ง estimator bug,
reporting bug และ comfort breach ได้ในเคสเดียว จึงควรเก็บเป็น regression case
ถาวรของ ZEEP โดยไม่เก็บตัวระบุบุคคลไว้ใน source code repository
