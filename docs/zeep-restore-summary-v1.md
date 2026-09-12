# ZEEP Restore Summary v1

> **Purpose:** ข้อกำหนดชั้นสรุปผลที่อธิบายคะแนนหลักของแต่ละ Session
> โดยไม่สร้างคะแนนที่สาม
>
> **Positioning:** ZEEP Wellness & Longevity · ไม่ใช่การวินิจฉัย
> หรือการประเมินความพร้อมทั้งวัน
>
> **Status:** Implementation specification · 2026-09-11
> **Code:**
> [`restore_summary.py`](../zeep_pod/sessions/restore_summary.py) ·
> [`restore_summary_baseline.py`](../zeep_pod/sessions/restore_summary_baseline.py) ·
> [`sleep_session_report.py`](../sleep_session_report.py) ·
> [`restore_response_models.py`](../zeep_pod/sessions/restore_response_models.py)
>
> **API schema:**
> [Usage Session API Schema Reference v1](zeep-api-schema-reference-v1.md) ·
> `/openapi.json`

## TL;DR

- Overnight Recovery ใช้ **Sleep Score 0–100** เท่านั้น
- Nap & Refresh ใช้ **Recovery Score 0–100** เท่านั้น
- `ZEEP Restore Summary` ไม่คำนวณคะแนนใหม่ แต่คัดลอกคะแนนหลักพร้อม
  สถานะ จุดแข็ง จุดที่ควรปรับ Baseline ความมั่นใจ และคำแนะนำหนึ่งข้อ
- Personal Baseline แยกตามผู้ใช้และโหมด เริ่มเปรียบเทียบเมื่อมีอย่างน้อย
  7 Session และแสดงว่าเสถียรมากขึ้นตั้งแต่ 14 Session
- สิ่งแวดล้อมไม่สร้าง Sleep State; ใน Overnight เป็นบริบท ส่วน Nap &
  Refresh มีผลต่อ Recovery Score แบบจำกัดสูงสุด 10 คะแนน
- ห้ามใช้คำว่า Whole-day Readiness จนกว่าจะมีข้อมูลกิจกรรมระหว่างวัน
  training load, wearable และข้อมูลก่อน–หลัง Session ที่ผ่าน validation

## 1. แนวคิดที่นำมาประยุกต์

Apple อธิบาย Readiness ด้วยคะแนนเดียว สถานะที่นำไปใช้ได้ ตัวขับคะแนน
และข้อมูลที่เทียบกับช่วงปกติของบุคคล แนวคิดการสื่อสารดังกล่าวใช้เป็น
แรงบันดาลใจในการทำให้ผล ZEEP อ่านง่ายขึ้น:

- [Apple — health and fitness capabilities using Apple Intelligence](https://www.apple.com/newsroom/2026/09/apple-advances-health-and-fitness-capabilities-using-apple-intelligence/)
- [Apple Watch User Guide — Vitals](https://support.apple.com/guide/watch/vitals-apd15aa7ed96/26/watchos/26)

ZEEP ไม่คัดลอกสูตร น้ำหนัก หรือ UI ของ Apple น้ำหนักทั้งหมดในระบบเป็น
นโยบายวิศวกรรมของ ZEEP และต้องมี version/audit ของตนเอง

## 2. Invariant ของสองโหมด

| Session goal | คะแนนหลัก | คำถามที่ตอบ |
|---|---|---|
| Overnight Recovery | Sleep Score | การนอนครั้งนี้สนับสนุนการฟื้นตัวได้ดีเพียงใด |
| Nap & Refresh | Recovery Score | ช่วงพักนี้ร่างกายสงบและพักได้ตามเป้าหมายเพียงใด |

ข้อห้าม:

1. ห้ามนำ Recovery Score ไปแสดงเป็น Sleep Score
2. ห้ามบังคับ Nap ให้มี N2/N3/REM
3. ห้ามสร้าง `Restore Score` เป็นตัวเลขที่สาม
4. ห้าม fallback `auto/unknown_legacy` เป็น Nap จากระยะเวลา
5. ห้ามใช้ Summary เขียนกลับ Sleep State หรือสั่งอุปกรณ์

## 3. น้ำหนักคะแนนหลักที่ใช้จริง

### 3.1 Sleep Score — Overnight Recovery

| องค์ประกอบ | คะแนนเต็ม |
|---|---:|
| เวลาและการเข้าสู่การนอน | 20 |
| ความต่อเนื่องของการนอน | 30 |
| โครงสร้าง N2/N3/REM | 30 |
| รอบการนอนที่ตรวจพบ | 15 |
| ความครบของข้อมูล | 5 |

### 3.2 Recovery Score — Nap & Refresh

| องค์ประกอบ | คะแนนเต็ม |
|---|---:|
| เวลาพักตามเป้าหมาย | 25 |
| การตอบสนองและความนิ่งของ HR/RR | 35 |
| ความต่อเนื่องและความนิ่งของร่างกาย | 30 |
| สภาพแวดล้อมสนับสนุน | 10 |

Environment ไม่ได้สร้าง W/N1/N2/N3/REM แม้ใน Nap แต่ถูกนำมาคิดเป็น
องค์ประกอบแบบจำกัดของ Recovery Score เพราะคำถามของโหมดคือคุณภาพของ
“โอกาสพักใน ZEEP” ไม่ใช่การตรวจ Sleep Stage โดยคะแนนส่วนนี้ใช้เฉพาะค่าที่
วัดระหว่าง State-attributed rest และตัด confirmed OFF BED/Sensor gap ออก;
ค่าทั้ง Session ยังคงแสดงแยกใน Admin QA

Recovery Score เผยแพร่เมื่อมี eligible rest อย่างน้อย 10 นาทีและมี HR/RR คู่จริง
อย่างน้อย 6 จุด ช่วง State continuity carry นับเป็นเวลาพัก แต่ไม่สร้างหลักฐาน
HR/RR, Movement หรือ Environment เพิ่มขึ้นเอง

## 4. Five-driver taxonomy

Dashboard และ API จัดเหตุผลให้อยู่ในห้ากลุ่มเดียวกัน:

1. Duration / Opportunity
2. Continuity / Stillness
3. Sleep composition — ใช้เฉพาะเมื่อโหมดและหลักฐานเกี่ยวข้อง
4. HR/RR physiology
5. Sleep environment

Summary เลือกจุดแข็งสูงสุดไม่เกินสองข้อ และจุดที่ควรปรับสูงสุดไม่เกิน
สองข้อจากองค์ประกอบที่คำนวณจริง ข้อมูล Sensor ที่หายต้องเป็น Attention
หรือไม่แสดง ห้ามจัดเป็นจุดแข็ง ส่วน Coverage แสดงใน Confidence สำหรับ
Admin ไม่ใช้เป็นตัวขับหลักบน Dashboard ผู้ใช้งาน

## 5. Action bands

| คะแนน | Overnight Recovery | Nap & Refresh |
|---:|---|---|
| 85–100 | ฟื้นตัวจากการนอนดีมาก | พักได้เต็มเป้าหมาย |
| 70–84 | ฟื้นตัวจากการนอนดี | พักได้ดี |
| 50–69 | ควรผ่อนจังหวะ | ได้พักบางส่วน |
| 0–49 | ควรเน้นการพักเพิ่ม | ควรพักต่อหรือปรับปัจจัยรบกวน |

สถานะนี้อธิบาย Session ที่เพิ่งจบ ไม่ใช่คำรับรองว่าสามารถขับรถ แข่งขัน
ใช้เครื่องจักร หรือทำกิจกรรมเสี่ยงได้

## 6. Personal Baseline และแนวโน้ม

| จำนวน Session ที่ผ่านเกณฑ์ในโหมดเดียวกัน | สถานะ |
|---:|---|
| 0–2 | กำลังเรียนรู้ |
| 3–6 | Baseline เบื้องต้น; ยังไม่ใช้คำว่าเหนือ/ต่ำกว่าปกติ |
| 7–13 | Personal Baseline พร้อมเปรียบเทียบ |
| 14+ | Baseline ส่วนบุคคลเสถียรมากขึ้น |

กฎข้อมูล:

- เปรียบเทียบกับ Session ก่อนหน้าเท่านั้น ไม่ให้ Session ปัจจุบันสร้าง
  Baseline แล้วเปรียบเทียบกับตัวเอง
- แยก Overnight และ Nap & Refresh เสมอ
- ใช้ median เป็นค่ากลางและ IQR เป็น observed typical range
- แสดงแนวโน้ม 7/14/30 **Sessions** ไม่เรียกว่าแนวโน้มความพร้อมทั้งวัน
- Baseline ไม่เปลี่ยนคะแนนย้อนหลังโดยอัตโนมัติ และไม่เลือก Sleep State

## 7. กฎถ้อยคำเชิงเหตุและผล

ZEEP แสดงความสัมพันธ์ตามเวลาได้ แต่ Sensor เพียงอย่างเดียวยังพิสูจน์
สาเหตุไม่ได้

ถ้อยคำที่อนุญาต:

> พบเสียงเพิ่มใกล้ช่วง W จำนวน 2 เหตุการณ์

ถ้อยคำที่ห้ามใช้โดยไม่มี validation:

> เสียงทำให้ผู้ใช้ตื่น 2 ครั้ง

Environment driver ทุกตัวต้องมี `causal_claim=false` และ Sleep Stage ต้อง
คง `direct_stage_influence=false`

## 8. Confidence และข้อมูลที่ไม่ได้วัด

Coverage/Tier เป็นบริบท QA สำหรับ Admin ไม่ใช่คะแนนใหม่และไม่ใช่ veto
ที่ซ่อนอยู่ หากคะแนนหลักถูกปล่อยแล้ว Summary ต้องคงคะแนนเดิมพร้อมบอก
ความครบของหลักฐาน

หากยังไม่มีแบบสอบถาม ต้องแสดง:

- `ความรู้สึกหลังพัก · ไม่ได้วัด`
- `ความพร้อมทำกิจกรรม · ไม่ได้วัด`

ห้ามอนุมานความสดชื่นหรือความพร้อมทำกิจกรรมจาก HR/RR หรือ Sleep Score
เพียงอย่างเดียว

## 9. Contract ที่ส่งให้ UI/API

```json
{
  "version": "zeep-restore-summary-v1.0",
  "creates_independent_score": false,
  "source_score": {
    "type": "sleep_score",
    "title": "Sleep Score",
    "value": 76,
    "formula_version": "zeep-sleep-score-v1.1-20-30-30-15-5-evidence-coverage"
  },
  "status": {
    "key": "sleep_restore_good",
    "label": "ฟื้นตัวจากการนอนดี"
  },
  "drivers": {
    "positive": [],
    "attention": []
  },
  "personal_baseline": {},
  "trend": {},
  "recommendation": {},
  "confidence": {},
  "subjective_outcome": {
    "status": "not_measured"
  },
  "claim_boundary": {
    "whole_day_readiness": false,
    "medical_diagnosis": false
  }
}
```

Historical `auto/unknown_legacy` ต้องส่ง `unresolved_score` และ
`available=false` จนกว่าจะมีหลักฐานโหมด ห้ามอนุมานจากระยะเวลา

## 10. Versioning และ Audit

| ชั้น | Version |
|---|---|
| Session report | `zeep-session-report-v10.7-complete-occupied-epochs` |
| Restore Summary | `zeep-restore-summary-v1.0` |
| Action bands | `zeep-restore-action-bands-v1.0` |
| Driver policy | `zeep-restore-drivers-v1.0` |
| Baseline comparison | `zeep-restore-personal-baseline-v1.0` |
| Recommendation | `zeep-restore-recommendation-v1.0` |
| Sleep Score formula | `zeep-sleep-score-v1.1-20-30-30-15-5-evidence-coverage` |
| Recovery Score formula | `zeep-recovery-score-v2.1-complete-rest-25-35-30-10` |

การเพิ่ม Summary ทำให้ Session Report เปลี่ยน version แต่ไม่เปลี่ยนสูตร
หรือคะแนนเดิม จึงคงคู่ Report/Quality รุ่นก่อนหน้าไว้ใน approved history
สำหรับ Baseline และการเปิดรายงานเก่า

## 11. ขอบเขตการพัฒนาถัดไป

1. Finalization แช่แข็ง `personal_context` จาก Session ก่อนหน้าไว้ใน
   `final_summary`; รายงานย้อนหลังใช้ snapshot เดิม จึงไม่มีข้อมูลอนาคตไหลย้อน
2. เพิ่ม Pre/Post questionnaire API พร้อม provenance และ timestamp
3. ทดสอบ driver wording กับผู้ใช้และทีมสุขภาพ
4. ทดลองสูตรใหม่ได้เฉพาะ Shadow Model จน Product Owner อนุมัติ
5. Whole-day Readiness ต้องเป็นผลิตภัณฑ์อีกชั้นหนึ่งหลังเชื่อม wearable,
   activity/training load และ morning check-in ที่ผ่าน validation
