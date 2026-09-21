# คำแนะนำหลังพัก · ZEEP

สถานะ: Implementation v1.2 · 19 กันยายน 2026

ถ้อยคำใช้ [Product Language v1.2](zeep-product-language-guideline-v1.md)
ใน source ล่าสุด การเปลี่ยนภาษาไม่เปลี่ยนลำดับเลือกคำแนะนำหรือสูตรคะแนน

## TL;DR

หนึ่ง Session มีคำแนะนำหลักหนึ่งข้อ พร้อมหัวข้อ ช่วงเวลาที่เหมาะสม และเหตุผล
หน้า Session และ API ใช้นโยบายเดียวกัน ไม่สร้างคะแนนใหม่ ไม่เปลี่ยน Sleep State
และไม่สั่งอุปกรณ์อัตโนมัติ คำแนะนำย้อนหลังอ้างอิงการพักครั้งนั้น ไม่ใช่สถานะวันนี้

## การเลือกคำแนะนำ

1. ประเด็นความปลอดภัย → ให้ทีมตรวจสภาพแวดล้อมก่อนใช้ครั้งถัดไป
2. คำตอบจริงหลังพักที่แสดงว่าความสดชื่นลดลง/ความพร้อมเป็นศูนย์ → ให้เวลาตัวเอง
3. ไม่มีคะแนนหรือหลักฐานจำกัด → เช็กความรู้สึก ไม่แต่งผลการฟื้นตัว
4. สิ่งแวดล้อมที่วัดได้ → เสนอสิ่งที่นำไปลองปรับในห้องพักของตนเอง
5. เวลา/ความต่อเนื่อง → จัดตารางพัก ลดการขัดจังหวะ
6. Nap ที่ไม่พบช่วงหลับ → พักเงียบได้ ไม่ต้องบังคับให้หลับลึก
7. หากไม่มีประเด็นเฉพาะ → รักษากิจวัตร และใช้ Baseline ที่ผ่านการตรวจโหมด
   เป้าหมาย และรุ่นสูตรแล้วประกอบเหตุผลเมื่อมีข้อมูลเพียงพอ

หลักฐานเหมือนกันอาจได้คำแนะนำเดียวกัน ไม่สุ่มประโยคเพื่อสร้างภาพว่าเฉพาะบุคคล
คะแนนต่ำเพียงอย่างเดียวไม่ใช่ข้อสรุปว่าไม่แข็งแรงหรือฟื้นตัวไม่ดี

## โหมดและข้อความ

- Overnight ใช้ Sleep Score และเน้นกิจวัตรก่อนนอนครั้งถัดไป
- Nap & Refresh ใช้ Recovery Score และเน้นช่วงพักระหว่างวัน/กิจกรรมถัดไป
- HR/RR ไม่ใช้อนุมานความสดชื่น ความฟิต สุขภาพปอด หรือความพร้อมขับรถ
- รุ่นนี้ยังไม่เพิ่มคำถามเรื่องกิจกรรมถัดไปหรือปุ่ม feedback ใหม่
  จึงไม่อ้างว่าได้ข้อมูลเหล่านั้นจาก Session เก่า
- Self-report ต้องมี source ที่อนุญาต, status=measured และ sensor_inferred=false
- รักษาค่าตอบจริงขณะ Rerun; ไม่มีคำตอบก่อน–หลัง ไม่สร้าง freshness_delta

## Contract สำหรับทีมแอป

ใช้ `restore_summary.recommendation` ของผล Session เดิม:

```json
{
  "primary": "ลองวางหน้าจอและพักในมุมเงียบ ๆ โดยไม่ต้องฝืนให้ตัวเองหลับ",
  "source_driver_key": "estimated_sleep_s",
  "version": "zeep-restore-recommendation-v1.2-after-rest",
  "one_action_only": true,
  "automatic_actuation": false,
  "medical_advice": false,
  "tip_id": "quiet_awake_break",
  "title": "พักสายตาระหว่างวัน",
  "when_label": "ก่อนพักครั้งถัดไป",
  "reason": "ระบบยังไม่พบช่วงหลับที่ชัดเจนในครั้งนี้ แต่การพักระหว่างวันไม่จำเป็นต้องหลับ",
  "basis": "session_sensor",
  "historical_session_context": true,
  "whole_day_readiness_claim": false
}
```

ฟิลด์เดิมคงเดิม ส่วนฟิลด์เพิ่มเป็น optional/nullable ใน OpenAPI เพื่ออ่านรายงานเก่าได้
`basis`: session_sensor / personal_baseline / self_report / limited_data / safety
`primary`, `version`: required string; `tip_id`, `title`, `when_label`, `reason`:
optional string หรือ null; builder ปัจจุบันส่งครบตามตัวอย่าง
`source_driver_key`: string หรือ null; flags เป็น boolean ตามตัวอย่าง
Compact presentation API ยังส่ง recommendation เป็นข้อความเดียวตาม contract เดิม
รายงาน legacy ใช้ primary เดียวกัน ไม่มีคำแนะนำจากสูตรคะแนนอีกชุดหนึ่ง

## Rerun ที่ได้รับอนุมัติ

เลือก Session จบแล้ว ตั้งแต่ `2026-09-01T00:00:00+07:00` เท่านั้น
เจ้าของยืนยันไม่รวมข้อมูลก่อน 1 ก.ย. ในรอบนี้ ไม่ใช่คำสั่งลบข้อมูลเดือนสิงหาคม
ใช้ `rescore_session_reports.py --all --since ...` เพื่อคำนวณคะแนนและรายงานใหม่
ไม่ใช่ reclassify Sleep State; ไม่แก้ Raw BCG, Timeline, annotation หรือ stage events
ผลเดิมทั้งหมดอยู่ใน `session_report_rescored.previous_final_summary` เพื่อ rollback
ก่อน apply ทำ SQLite backup และตรวจ hash ของข้อมูลที่ต้องคงเดิม

รอบนี้ทำเสร็จแล้ว ดู [รายงานก่อน–หลังและ Sync](reviews/2026-09-19-after-rest-rerun.md)
การอนุมัติรอบนั้นไม่ใช่คำสั่งให้เครื่องมือรันซ้ำทุกครั้งที่แก้ข้อความ/เอกสาร

## หลักฐานอ้างอิง

- [NHLBI — Healthy Sleep Habits](https://www.nhlbi.nih.gov/health/sleep-deprivation/healthy-sleep-habits):
  กิจวัตรการนอนสม่ำเสมอและพื้นที่พักเงียบ มืด เย็นสบาย เป็นฐานของข้อความทั่วไป
  ไม่ได้ตรวจรับรองสูตร ZEEP หรือเวลางีบของทุกคน
- [CDC/NIOSH — Sleep Inertia](https://www.cdc.gov/niosh/work-hour-training-for-nurses/longhours/mod7/03.html):
  หลังตื่นอาจงัวเงีย ให้เวลาก่อนงานที่ต้องระมัดระวัง ไม่ใช้คะแนนแทนความพร้อมจริง

กฎเลือกและน้ำหนักการจัดลำดับเป็นการออกแบบผลิตภัณฑ์ ZEEP ไม่ใช่อัลกอริทึมที่
ผ่านการทดลองยืนยันประสิทธิผลทางคลินิก การพบเสียงใกล้ช่วงตื่นไม่พิสูจน์สาเหตุ

## Verification

ตรวจคำแนะนำสองโหมด, หลักฐานขาด, provenance แบบสอบถาม, สถานะ Safety,
API/legacy parity, HTML escaping, audit rollback และความคงเดิมของคะแนน/Raw
ผลรัน Production และจำนวน Session ต้องอ่านจากรายงานรอบ Rerun ไม่ใช้ตัวอย่างนี้
