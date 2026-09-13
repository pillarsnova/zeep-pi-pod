# ZEEP Respiratory Wellness v1.1

**สถานะ:** ข้อกำหนดสำหรับ Pilot / Wellness เท่านั้น
**เวอร์ชันผลลัพธ์:** `zeep-respiratory-wellness-v1.1`
**ตรวจทานแหล่งอ้างอิง:** 13 กันยายน 2026

## 1. วัตถุประสงค์และขอบเขต

ZEEP สรุป **ชีพจรและการหายใจระหว่างพัก** จาก HR และ RR คู่กันในช่วงหลักฐาน
BCG โดยตรง การ์ดผู้ใช้มีเพียงหนึ่งบรรทัดสรุปและหนึ่งบรรทัดคำแนะนำ ส่วนข้อมูล
เชิงเทคนิคและความครอบคลุมยังอยู่ในมุมมองผู้ดูแล

ผลนี้ตอบได้ว่า “รูปแบบการหายใจที่วัดได้ใน Session นี้สนับสนุนการพักหรือควร
ติดตามซ้ำหรือไม่” แต่ **ตอบไม่ได้ว่าปอดหรือร่างกายแข็งแรงกี่เปอร์เซ็นต์** เพราะ
ZEEP ยังไม่ได้วัด airflow, ปริมาตรปอด, การแลกเปลี่ยนก๊าซ, SpO₂ หรือสมรรถภาพ
ระหว่างกิจกรรม

| ระบบกล่าวได้ | ระบบต้องไม่กล่าว |
|---|---|
| HR และ RR โดยประมาณจากหน้าต่าง BCG เดียวกัน | ปอดแข็งแรง/อ่อนแอ ความฟิตของร่างกาย หรือมีความจุปอดเท่าใด |
| ใกล้หรือต่างจาก Personal Baseline ในโหมดเดียวกัน | ระดับออกซิเจนในเลือดโดยอนุมานจาก RR |
| ควรเก็บข้อมูลเพิ่ม หรือตรวจซ้ำเมื่อแนวโน้มผิดปกติชัด | คัดกรอง/วินิจฉัย sleep apnea หรือโรคหัวใจและปอด |
| คำแนะนำทั่วไปเชิง Wellness | คำวินิจฉัย การรักษา หรือความพร้อมของร่างกายทั้งวัน |

ผลลัพธ์นี้ไม่เปลี่ยน Sleep State, Sleep Score, Recovery Score และไม่สั่งอุปกรณ์
อัตโนมัติ หากต้องประเมินสมรรถภาพปอดให้ใช้ spirometry/PFT; หากต้องการค่า
oxygenation ให้ใช้ pulse oximeter ที่ผ่านการตรวจสอบ; และหากสงสัย sleep apnea
ต้องใช้การประเมินทางการแพทย์ตามแนวทาง AASM

## 2. Direct paired HR/RR evidence

ระบบคงเกณฑ์สถานะ RR เดิมไว้โดยไม่เปลี่ยน threshold และเพิ่มค่ากลาง HR เฉพาะ
จากหน้าต่างหลักฐานเดียวกันที่ไม่ถูก hold เพื่อสร้างข้อความ HR/RR ร่วมกัน:

1. ยืนยันว่ามีผู้ใช้อยู่บนเตียงจาก Bed Status; ห้ามอนุมาน occupancy จาก Sleep
   State และตัดช่วง `OFF BED` ออก
2. BCG analysis valid, RR เป็นค่าปัจจุบัน ไม่ใช่ค่าที่ hold/carry จากก่อน restart
3. ไม่อยู่ในช่วง movement, weak signal, synthetic gap หรือสถานะข้อมูลเสีย/ค้าง
4. มี paired vital อย่างน้อย 8 packets และ coverage อย่างน้อย 80% ในหน้าต่างสด
5. RR เป็นตัวเลข finite ใน sanity range 4–60 ครั้ง/นาที

ข้อความสรุปร่วมจะแสดง `vital_summary.available = true` เมื่อมีค่ากลาง HR และ RR
จากหลักฐานคู่โดยตรง หาก HR ขาด ระบบไม่อนุมานจากสถานะ RR และจะแสดงเพียงว่า
ข้อมูลร่วมกันยังไม่ครบ สถานะ RR เดิมยังคงใช้เพื่อ QA และไม่ถูกตีความว่า HR
สม่ำเสมอ

ข้อมูลย้อนหลังที่ไม่มี provenance ว่า RR ผ่าน gate จะ fail closed: ยังเก็บ Timeline
เดิมไว้ได้ แต่ไม่นำมาสร้างคำกล่าวด้านการหายใจ รายงานจะอธิบายด้วย
`historical_provenance_unavailable` แทนการคาดเดา

การเผยแพร่ผลต้องมีข้อมูลใช้ได้อย่างน้อย 120 วินาที, อย่างน้อย 4 ตัวอย่าง
(รองรับทั้ง cadence 10 และ 30 วินาที),
ช่วงต่อเนื่องอย่างน้อย 30 วินาที และ coverage ของช่วง occupied อย่างน้อย 50%.
Confidence เป็น `high` เมื่อ coverage ≥80%, `medium` เมื่อ 50–79.9% และ `low`
เมื่อหลักฐานไม่พอ

ค่าที่สรุปประกอบด้วย weighted median, P10–P90 และ regularity factor ภายใน
Session. Regularity เป็นกติกา Wellness ภายในของ ZEEP ไม่ใช่ clinical cutoff
และความแปรปรวนอาจเปลี่ยนตาม Sleep Stage, ท่าทาง และการเคลื่อนไหวได้

## 3. บทบาทของช่วงอายุ

ระบบจัดบริบทผู้ใหญ่เป็น `18–29`, `30–44`, `45–59` และ `60+` จากข้อมูล Profile
ที่ผู้ใช้ให้ไว้ แต่ทุกช่วงใช้กติกาการแปลผลเดียวกัน:

- `role = context_only`
- `threshold_adjustment_applied = false`
- `age_specific_cutoff_applied = false`
- อายุไม่เพิ่ม/ลดสถานะ คะแนน หรือ Confidence

UI ให้คำแนะนำเชิงบริบทต่างกันตามวัย เช่น การเริ่มสะสม Baseline, การดูร่วมกับ
กิจกรรม/ภาระงาน หรือการให้ความสำคัญกับแนวโน้มและอาการร่วม แต่คำแนะนำนี้ไม่
เปลี่ยน threshold และไม่ถูกนำไปคำนวณสถานะหรือคะแนน

ช่วง 12–20 ครั้ง/นาทีเป็น **ช่วงอ้างอิงกว้างเชิงปฏิบัติการ** ของผู้ใหญ่ขณะพัก
ไม่ใช่เกณฑ์วินิจฉัยและไม่ใช่ “คะแนนตามวัย” (MedlinePlus ระบุค่าเฉลี่ยผู้ใหญ่
ขณะพัก 12–18 ครั้ง/นาที) งานประชากรแสดงว่า RR ระหว่างนอนสัมพันธ์กับอายุและ
ปัจจัยส่วนบุคคลได้ จึงควรใช้ช่วงอายุเพื่ออธิบาย/แบ่งกลุ่มตรวจสอบโมเดล ไม่ควร
สร้าง cutoff รายวัยจากข้อมูล Pilot ที่ยังมีจำนวนน้อย

## 4. Personal Baseline

Personal Baseline มีน้ำหนักในการอธิบายมากกว่าการเทียบประชากร แต่เปิดใช้เมื่อมี
**อย่างน้อย 7 Session ก่อนหน้า** ที่ครบทุกข้อ:

- เป็น Session ที่จบแล้วและเกิดก่อน Session ปัจจุบัน
- อยู่ในโหมดเดียวกัน (`overnight_sleep` แยกจาก `nap_or_rest`)
- respiratory result ใช้ direct measurements, Confidence ระดับสูง และสถานะ
  `supportive` หรือ `observe`
- มีค่ากลาง RR และ regularity ที่ตรวจสอบได้

ระบบใช้ median และ IQR (P25–P75) ของ Session เหล่านั้นเป็น typical range แล้ว
รายงาน `below`, `within` หรือ `above`. Baseline นี้มีไว้แสดงแนวโน้มเท่านั้น:
`affects_score = false` และไม่มีอิทธิพลโดยตรงต่อ Sleep State

ก่อนครบ 7 Session UI แสดงความคืบหน้า เช่น `กำลังเรียนรู้ 4/7 Session`
โดยไม่เติมค่าที่หายหรือรวม Nap กับ Overnight

## 5. สถานะที่เผยแพร่

| `status.key` | ข้อความผู้ใช้ | หลักการ |
|---|---|---|
| `insufficient` | กำลังเรียนรู้รูปแบบของคุณ | ไม่ผ่านเวลาขั้นต่ำ จำนวนตัวอย่าง ความต่อเนื่อง หรือ coverage |
| `needs_recheck` | แนะนำให้เช็กอีกครั้ง | มีข้อมูลใช้ได้ ≥5 นาที, coverage ≥70% และ median RR ≤8 หรือ ≥25; เป็น trigger ให้ยืนยัน ไม่ใช่การวินิจฉัย |
| `supportive` | จังหวะการหายใจค่อนข้างสม่ำเสมอ | median อยู่ในช่วงอ้างอิงกว้าง 12–20, coverage ≥70% และ regularity เพียงพอ |
| `observe` | มีการเปลี่ยนแปลงบางช่วง | มีหลักฐานพอสรุป แต่ยังไม่เข้าเงื่อนไข `supportive` หรือ `needs_recheck` |

`needs_recheck` ต้องมีลำดับความสำคัญเหนือการบอกว่าใกล้ Personal Baseline เพื่อ
ไม่ให้ baseline ที่เบี่ยงเบนกลบค่าที่ควรยืนยันซ้ำ หากผู้ใช้มีอาการหายใจลำบาก
เจ็บหน้าอก ปาก/ปลายมือเขียว สะดุ้งหายใจ หรือมีผู้สังเกตว่าหยุดหายใจ ควรขอ
ความช่วยเหลือทางการแพทย์โดยไม่รอคะแนนจาก ZEEP

## 6. API contract

รายงาน Session เผยแพร่ object `respiratory_wellness` ผ่าน
`GET /api/v1/usage-sessions/{session_id}` โดยเป็น positive allowlist;
ไม่ส่ง Profile ดิบหรือ RR ราย packet ออกสู่ Public API

```json
{
  "respiratory_wellness": {
    "version": "zeep-respiratory-wellness-v1.1",
    "available": true,
    "intended_use": "age_contextual_wellness_pattern_not_lung_function",
    "context": "overnight_sleep",
    "status": {
      "key": "supportive",
      "label": "จังหวะการหายใจค่อนข้างสม่ำเสมอ"
    },
    "reason_codes": [],
    "interpretation": "จังหวะหายใจค่อนข้างสม่ำเสมอระหว่างพัก",
    "observations": {
      "median_hr_bpm": 58.4,
      "median_paired_rr_brpm": 16.2,
      "median_rr_brpm": 16.2,
      "p10_rr_brpm": 14.8,
      "p90_rr_brpm": 18.1,
      "regularity_factor": 0.74,
      "regularity_key": "stable",
      "valid_samples": 1800,
      "paired_hr_rr_samples": 1800,
      "paired_hr_rr_minutes": 300.0,
      "paired_hr_rr_coverage_pct": 83.3,
      "longest_paired_hr_rr_run_seconds": 1260.0,
      "paired_hr_rr_evidence_sufficient": true,
      "longest_valid_run_seconds": 1260.0,
      "valid_minutes": 300.0,
      "occupied_minutes": 360.0,
      "coverage_pct": 83.3
    },
    "vital_summary": {
      "available": true,
      "status": "available",
      "status_label": "พร้อมดูแนวโน้ม",
      "heart_rate_bpm": 58.4,
      "respiration_rate_brpm": 16.2,
      "summary": "จังหวะหายใจค่อนข้างสม่ำเสมอระหว่างพัก",
      "recommendation": "รักษารูปแบบการพักที่สบายนี้ไว้",
      "basis": "direct_paired_hr_rr",
      "aggregation": "weighted_median",
      "wellness_only": true,
      "medical_diagnosis": false
    },
    "confidence": {
      "level": "high",
      "direct_measurements_only": true,
      "carried_state_excluded": true
    },
    "age_context": {
      "age_band": "30-44",
      "guidance": "ดูแนวโน้มร่วมกับการนอน ภาระงาน และกิจกรรมในแต่ละวัน",
      "role": "context_only",
      "threshold_adjustment_applied": false
    },
    "personal_baseline": {
      "available": true,
      "sessions_used": 8,
      "status": "within",
      "typical_range_rr_brpm": [15.4, 17.2],
      "same_mode_only": true,
      "prior_sessions_only": true,
      "affects_score": false
    },
    "claim_boundary": {
      "lung_strength_assessed": false,
      "oxygen_saturation_measured": false,
      "sleep_apnea_screening": false,
      "medical_diagnosis": false,
      "changes_sleep_score": false,
      "changes_recovery_score": false
    }
  }
}
```

ฟิลด์สำคัญอื่น ได้แก่ `reference_context`, `recommendation`,
`measurement_requirements` และ `capabilities`. Client ต้องรองรับ
`available = false`, ค่า observation เป็น `null` และ `reason_codes` โดยไม่สร้าง
ข้อความด้านสุขภาพขึ้นเอง

| กลุ่มฟิลด์ | ฟิลด์ที่เผยแพร่ |
|---|---|
| Root | `version`, `available`, `label`, `intended_use`, `context`, `status`, `reason_codes`, `interpretation`, `vital_summary` |
| Observations | `median_hr_bpm`, `median_paired_rr_brpm`, `median_rr_brpm`, `paired_hr_rr_samples`, `paired_hr_rr_minutes`, `paired_hr_rr_coverage_pct`, `longest_paired_hr_rr_run_seconds`, `paired_hr_rr_evidence_sufficient`, `p10_rr_brpm`, `p90_rr_brpm`, `regularity_factor`, `regularity_key`, `valid_samples`, `longest_valid_run_samples`, `longest_valid_run_seconds`, `valid_minutes`, `occupied_minutes`, `coverage_pct`, เวลาที่ถูกตัดออกสองประเภท |
| Context | `confidence`, `age_context`, `personal_baseline`, `reference_context` |
| Action and boundary | `recommendation`, `measurement_requirements`, `capabilities`, `claim_boundary` |

## 7. การแสดงผลบน UI

หน้า **ประวัติการใช้งาน** แสดงการ์ด “ชีพจรและการหายใจระหว่างพัก” เพียงจุดเดียว:

- ผู้ใช้เห็น `vital_summary.summary` หนึ่งบรรทัด และ
  `vital_summary.recommendation` หนึ่งบรรทัด ทั้ง Overnight และ Nap
- ห้ามให้ Client สรุปว่า HR สม่ำเสมอจาก `status` เพราะสถานะดังกล่าวยังเป็น
  การจัดกลุ่ม RR; ให้ใช้ `vital_summary.status` สำหรับความพร้อมของข้อมูลคู่
- ผู้ดูแลกางรายละเอียดดู valid minutes, coverage, จำนวนตัวอย่าง, longest run,
  regularity factor, เวลาที่ตัดเพราะ movement/weak/invalid/held และ version ได้
- ทุกมุมมองแสดงข้อความสั้นว่าเป็นข้อมูล Wellness จากช่วงพัก ไม่ใช่ผลตรวจ
  สมรรถภาพปอด, SpO₂ หรือ sleep apnea
- เมื่อข้อมูลกำลังสะสม ให้บอกว่าระบบกำลังเรียนรู้รูปแบบของผู้ใช้ โดยไม่แปลงเป็น
  คำว่า “ปอดไม่แข็งแรง”

หลีกเลี่ยงการแสดง RR ซ้ำในหลายการ์ดแก่ผู้ใช้ ส่วน Raw/provenance และเหตุผลจาก
gate เก็บไว้ใน Admin Monitor และ Audit

## 8. Validation roadmap ก่อนขยายคำกล่าว

1. **Technical validation:** เทียบ RR จาก BCG กับ respiratory belt หรือ reference
   ที่มี timestamp ตรงกัน รายงาน bias, MAE, RMSE, Bland–Altman limits of
   agreement และ coverage; แยกท่านอน การเคลื่อนไหว โหมด และช่วงอายุ
2. **Gate regression:** replay เคส off-bed, movement, weak signal, sensor gap,
   restart/held, packet loss และ legacy provenance; ต้องไม่มี carried/synthetic RR
   หลุดเข้าผล และ Timeline ดิบต้องไม่ถูกแก้
3. **Longitudinal validation:** ตรวจว่า median/IQR จาก ≥7 Session มีเสถียรภาพ
   และไม่ปนข้อมูลระหว่าง Nap กับ Overnight; ประเมิน false recheck เป็นรายกลุ่ม
4. **Clinical-reference study:** หากต้องการกล่าวถึง oxygenation ให้เก็บ SpO₂ จาก
   อุปกรณ์ที่ผ่านการตรวจสอบ; หากต้องการกล่าวถึงปอดให้ทำ spirometry/PFT; หาก
   ต้องการคัดกรอง apnea ให้ทำ protocol ภายใต้ผู้เชี่ยวชาญและเทียบ PSG/HSAT ตาม
   AASM ก่อนเปลี่ยน intended use
5. **Human factors:** ทดสอบว่าผู้ใช้เข้าใจ `supportive`/`observe`/`recheck` และ
   ไม่ตีความเป็นการวินิจฉัยหรือคะแนนความแข็งแรงของปอด

การเปลี่ยน threshold, intended use หรือข้อความ claim ต้องเพิ่ม policy version,
บันทึกแหล่งหลักฐาน, ผ่าน regression และได้รับการอนุมัติก่อน deploy/rerun

## 9. แหล่งอ้างอิงและสิ่งที่ใช้อ้างอิง

- [AASM Clinical Practice Guideline for Diagnostic Testing for Adult Obstructive Sleep Apnea](https://aasm.org/resources/clinicalguidelines/diagnostic-testing-osa.pdf) — ยืนยันว่าการวินิจฉัย OSA ต้องอยู่ในกระบวนการประเมินทางการแพทย์และใช้ PSG/HSAT ตามข้อบ่งชี้; RR จาก ZEEP เพียงค่าเดียวไม่ใช่การตรวจวินิจฉัย
- [American Thoracic Society — Pulmonary Function Tests](https://site.thoracic.org/advocacy-patients/patient-resources/pulmonary-function-tests) — อธิบายเครื่องมือวัดการทำงานของปอด เช่น spirometry และ lung-volume/gas-transfer testing ซึ่ง ZEEP ยังไม่ได้วัด
- [FDA — Pulse Oximeter Basics](https://www.fda.gov/consumers/consumer-updates/pulse-oximeter-basics) — อธิบายว่า pulse oximeter ใช้วัด oxygen saturation และมีข้อจำกัด; ห้ามอนุมาน SpO₂ จาก RR
- [MedlinePlus — Vital Signs](https://medlineplus.gov/ency/article/002341.htm) — บริบทค่าเฉลี่ย RR ของผู้ใหญ่ขณะพัก; ใช้เป็น orientation ไม่ใช่ diagnostic cutoff หรือเกณฑ์รายวัย
- [Development and preliminary validation of heart rate and breathing rate detection using a passive, ballistocardiography-based sleep monitoring system (PMID 19129030)](https://pubmed.ncbi.nlm.nih.gov/19129030/) — หลักฐานความเป็นไปได้ของการประมาณ RR แบบ passive BCG โดยเทียบกับ respiratory inductance plethysmography; ไม่ได้ตรวจสมรรถภาพปอด
- [Measurement of respiratory rate using wearable devices and applications to COVID-19 detection](https://www.nature.com/articles/s41746-021-00493-6) — ข้อมูลประชากรจาก wearable PPG สนับสนุนการอ่าน nocturnal RR เป็นแนวโน้มหลายคืนและพิจารณาอายุ/เพศ/BMI; ใช้เป็น population context เท่านั้น ไม่ใช่หลักฐานความแม่นของ BCG ใน ZEEP
