# ZEEP v1.23 Wellness Longitudinal Replay Report

> **หมายเหตุสถานะ:** เอกสารนี้เป็นผลรอบเดิมก่อน Historical Promotion Policy v2
> และเก็บไว้เป็นหลักฐานเปรียบเทียบเท่านั้น กติกา Tier A/manual-review allowlist ใน
> เอกสารนี้ถูกแทนที่โดย [Historical Promotion Policy v2](sleep-history-promotion-policy-v2.md)

> **สถานะ:** ผ่านการตรวจวิศวกรรมแบบมีข้อจำกัด (`PASS_WITH_LIMITATIONS`)
>
> **ขอบเขต:** ZEEP Wellness & Longevity; ไม่ใช่ PSG, AASM scoring, การวินิจฉัย หรือคำแนะนำการรักษา
>
> **Cutover:** 1 ก.ย. 2569 เวลา 00:00 น. Asia/Bangkok (รวมวันดังกล่าว)
> **เกณฑ์ Cohort:** Session จบแล้ว, ยาวกว่า 25 นาที, มี Raw BCG และมี HR/RR สำหรับประเมินคุณภาพสัญญาณ

## 1. ข้อสรุปสำหรับใช้งาน

- Product มีสองรูปแบบเท่านั้น: `Overnight Recovery → Sleep Score` และ
  `Nap & Refresh → Recovery Score`
- ข้อมูลก่อน cutover ถูกตัดออกจาก Product history, Baseline, Replay และ Score รุ่นนี้
  แต่ Raw BCG/Timeline เดิมยังคงอยู่แบบ immutable เพื่อ Audit
- พฤติกรรมย้อนหลังถูกแบ่งตามบัญชีอีเมลและโหมด ใช้เป็นบริบทคาดการณ์/คำแนะนำเท่านั้น
  (`direct_stage_influence=false`) ไม่ใช้ output เก่าฝึกให้ Sleep State ยืนยันตัวเอง
- Sensor เก็บทุก 10 วินาที, Evidence ทุก 30 วินาที, ยืนยัน W/N1/N3/REM ที่
  60 วินาที และ N2 ที่ 120 วินาที; รายงานย้อนหลังแยก cadence ทั้งสองชั้นออกจากกัน
- Nap & Refresh ไม่จำเป็นต้องหลับ ไม่มี N3/REM ก็ไม่ถูกหักเพราะเหตุนี้โดยตรง
- Overnight Recovery ต้องมี confirmed Sleep State coverage อย่างน้อย 80% จึงเผยแพร่
  Sleep Score; Session ที่ไม่ผ่านแสดงว่า “ข้อมูลยังไม่พอ”

## 2. Version และหลักฐานการทำซ้ำ

| รายการ | ค่า |
|---|---|
| Estimator | `bcg-audio-bed-5state-v1.23-wellness-longitudinal` |
| Evidence | `zeep-sleep-state-evidence-v3.2-respiratory-onset` |
| Baseline | `zeep-sleep-state-baseline-v1.8-sep1-cutover` |
| Historical replay | `zeep-sleep-history-reclass-v18-sep1-derived` |
| Quality | `zeep-rest-quality-v8.0-wellness-longevity` |
| Report | `zeep-session-report-v10.0-wellness-longevity` |
| Analysis run | สร้างใหม่จากฐาน Production หลังหยุด service |
| Deterministic result SHA-256 | บันทึกใน owner-only summary manifest ของรอบจริง |
| Promotion payload SHA-256 | บันทึกใน summary และ details manifest |
| Details artifact SHA-256 | summary manifest ต้อง pin ค่าเดียวกับไฟล์ details |
| Code provenance SHA-256 | บันทึก hash ราย source และ Git commit ใน manifest |

รันจาก input เดียวกันสองครั้งต้องได้ details artifact เหมือนกันแบบ byte-for-byte
และได้ deterministic hash เดียวกัน; Artifact ที่มีข้อมูลอีเมล/สุขภาพต้องเป็น permission
`0600` และเก็บร่วมกับ promotion result/rollback backup ของรอบนั้น

## 3. Cohort หลัง cutover

- Session เข้าเกณฑ์เวลา: 12
- บัญชีอีเมลไม่ซ้ำ: 11
- Nap & Refresh: 9 Session
- Overnight Recovery: 3 Session
- คุณภาพข้อมูล: Tier A = 6, Tier B = 5, Exclude = 1
- ผ่าน Gate สำหรับเขียน Derived result: 4 Session (Tier A, ไม่มี review flag,
  คะแนนเผยแพร่ได้)
- ไม่พบ independent PSG/AASM labels จึง **ห้าม** อ้าง clinical accuracy หรือใช้แทน
  clinical stage replacement

บัญชีที่พบ: `sp.noey218@gmail.com`, `pornthip.pi@thkholding.com`,
`thaveephompikul@gmail.com`, `sutthipat.ta@thkholding.com`,
`jjd.wipharat@gmail.com`, `mustmick000@gmail.com`, `nisakorn2937@gmail.com`,
`skakito82@gmail.com`, `090maxcat@gmail.com`, `jutti.cc@gmail.com` และ
`zenza10875@hotmail.com`

## 4. ผล Replay ราย Session

เปอร์เซ็นต์ N1/N2/N3/REM คิดจากเวลาที่ประเมินว่าเป็นการนอนเท่านั้น ไม่รวม W หรือ
WAIT/OFF เครื่องหมาย `—` หมายถึงไม่เผยแพร่คะแนนหรือไม่พบการหลับ ไม่ใช่คะแนนศูนย์

| วันที่ | บัญชี | นาที | รูปแบบ | Tier | คะแนน | N1/N2/N3/REM (%) | การตัดสิน |
|---|---|---:|---|:---:|---:|---|---|
| 1 ก.ย. | sp.noey218@gmail.com | 51.7 | Nap | Exclude | — | — | HR/RR coverage ไม่ถึงเกณฑ์ |
| 1 ก.ย. | pornthip.pi@thkholding.com | 63.2 | Nap | B | 57 | — | Recovery Score; พักขณะตื่น |
| 1 ก.ย. | thaveephompikul@gmail.com | 456.6 | Overnight | A | 81 | 4.5/69.5/2.4/23.5 | เผยแพร่ Sleep Score ได้ |
| 2 ก.ย. | pornthip.pi@thkholding.com | 89.3 | Nap | B | 58 | 60.0/40.0/0/0 | Review-only |
| 2 ก.ย. | sutthipat.ta@thkholding.com | 56.4 | Nap | B | 64 | 60.8/39.2/0/0 | Review-only |
| 2 ก.ย. | jjd.wipharat@gmail.com | 80.3 | Nap | A | 62 | — | เผยแพร่ Recovery Score ได้ |
| 2 ก.ย. | mustmick000@gmail.com | 585.1 | Overnight | A | — | 6.1/60.5/9.9/23.6 | คะแนนไม่ผ่าน release gate |
| 3 ก.ย. | nisakorn2937@gmail.com | 63.3 | Nap | B | 55 | 100/0/0/0 | Review-only; N1 สูง |
| 3 ก.ย. | skakito82@gmail.com | 31.6 | Nap | A | 77 | — | เผยแพร่ Recovery Score ได้ |
| 3 ก.ย. | 090maxcat@gmail.com | 531.8 | Overnight | A | — | 28.3/40.9/8.5/22.3 | coverage 69.4%; ไม่เผยแพร่คะแนน |
| 4 ก.ย. | jutti.cc@gmail.com | 75.6 | Nap | B | 50 | 61.9/11.9/26.2/0 | Review-only; ไม่ใช้เป็นตัวแทน clinical N3 |
| 4 ก.ย. | zenza10875@hotmail.com | 61.3 | Nap | A | 60 | 13.7/86.3/0/0 | เผยแพร่ Recovery Score ได้ |

## 5. ข้อกำหนดการเขียนย้อนหลัง

ตัว Promote ต้องหยุด service/ยืนยัน offline, checkpoint WAL และถือ SQLite exclusive
lock ระหว่างตรวจและเขียน โดยทำงานบนสำเนา private staging ก่อนเสมอ และแทนที่เฉพาะ
`sleep_stage`, `sleep_stage_evidence`, `final_summary` และ personal derived baseline
ของ Session ที่ผ่าน Gate ไม่แก้ Timeline หรือ `bcg.db`

ก่อนเขียนกลับด้วย SQLite backup API ต้องผ่านทั้งหมด:

1. input DB/Profile hash ตรงกับ Replay artifact
2. summary manifest pin details artifact, promotion payload และ source-code hash
   ตรงกับตอน Review
3. Session อยู่หลัง cutover และจบแล้ว
4. Tier A, ไม่มี manual review flag, มี derived evidence/state
5. Quality/report/mode/state counts, score, ชื่อคะแนน, estimated sleep และ actual
   scored time ที่สร้างจาก DB ต้องตรงกับ reviewed artifact ทุกค่า
6. SQLite integrity = `ok`
7. Timeline SHA-256 และ Raw BCG SHA-256 ก่อน/หลังตรงกัน

การทดสอบบนสำเนาข้อมูลผ่านทั้ง 4 Session, exact parity ผ่าน และ Raw hashes ไม่เปลี่ยน
การ Promote รอบทดสอบที่พบ cadence/report mismatch ถูกยกเลิกก่อนแตะฐานจริง จึงยืนยัน
ว่า fail-closed guard ทำงานตามวัตถุประสงค์

## 6. การเรียนรู้พฤติกรรมรายบุคคล

ระบบแยก `sleep` กับ `nap_recovery` และใช้เฉพาะ prior completed Session ของบัญชี
อีเมลเดียวกันหลัง cutover ที่ยาวกว่า 25 นาทีและรายงานเป็น version ปัจจุบัน เมื่อมีอย่าง
น้อย 3 Session ในโหมดเดียวกันจึงแสดง context ว่า active ได้แก่ onset โดยทั่วไป,
ช่วงเวลาเริ่ม, ระยะพัก และสภาพแวดล้อมที่มักพบ

ใน Pilot นี้ personal physiology ที่คำนวณได้เป็น **candidate สำหรับ Admin เท่านั้น**
ไม่เลื่อนเกณฑ์ W/N1/N2/N3/REM จนกว่าจะมี frozen estimator และ independent labels
เพื่อป้องกันวงจร self-training จาก prediction เดิม

## 7. คะแนนและคำแนะนำหลัง Session

### Overnight Recovery — Sleep Score

- หลับไวและเวลาพัก 20
- หลับดีและต่อเนื่อง 30
- โครงสร้าง N2/N3/REM 30 (Signal estimate ไม่ใช่การวัดการฟื้นฟูโดยตรง)
- รอบการนอนที่ตรวจพบ 15
- ความครบของข้อมูล 5

เป้าหมายเวลาเต็มสำหรับผู้ใหญ่คือ 7 ชั่วโมงตาม AASM/SRS; ขั้นต่ำ protocol ของ ZEEP
คือ 5 ชั่วโมง N3 ตั้งแต่ 10% ได้คะแนนส่วน N3 เต็มและไม่หักเมื่อเกิน 20%

### Nap & Refresh — Recovery Score

- เวลาพักตามเป้าหมาย 20
- การตอบสนอง HR/RR 30
- ความนิ่ง/ความต่อเนื่อง 20
- สภาพแวดล้อมสนับสนุน 20
- ความครบของข้อมูล 10

เมื่อออกจาก ZEEP ระบบให้คำแนะนำสั้นตามโหมด คะแนนที่เผยแพร่ได้ และสิ่งแวดล้อม เช่น
ค่อย ๆ ตื่นตัว ดื่มน้ำ รับแสง/ขยับเบา ๆ หรือปรับค่าที่รบกวนในครั้งถัดไป พร้อมเตือนว่า
ก่อนขับรถ ใช้เครื่องจักร หรือทำกิจกรรมเสี่ยงต้องยึดความตื่นตัวจริง ไม่ใช้คะแนนแทน
การตัดสินใจ และต้องอ่านร่วมกับ self-report หลังพัก

## 8. ข้อจำกัดและงานถัดไป

- BCG ใต้ที่นอนไม่วัด EEG/EOG/chin EMG จึงยืนยัน N1/N2/N3/REM แบบ AASM ไม่ได้
- HR-CV ปัจจุบันไม่ใช่ beat-to-beat RMSSD/SDNN
- ห้ามตีความ N3 ว่าเป็นการซ่อมแซมที่วัดโดยตรง หรือ REM ว่าเป็นความฝันที่ตรวจพบโดยตรง
- Tier B/Exclude ไม่ถูก Promote เป็นผลผู้ใช้รุ่นนี้ ให้ใช้เพื่อ Review คุณภาพสัญญาณ
- ต้องเก็บ paired PSG/ผู้เชี่ยวชาญที่ blind ต่อผล ZEEP เพื่อสร้าง confusion matrix,
  sensitivity/specificity, agreement และ subgroup review ก่อน claim ทางคลินิก

## 9. แหล่งอ้างอิงตรวจสอบได้

- [AASM/SRS Adult Sleep Duration Consensus](https://www.aasm.org/resources/pdf/adultsleepdurationconsensus.pdf) — เป้าหมาย 7 ชั่วโมงขึ้นไปสำหรับผู้ใหญ่
- [AASM Position Statement: Consumer Sleep Technology](https://aasm.org/advocacy/position-statements/consumer-sleep-technology/) — อุปกรณ์ผู้บริโภคไม่ใช้แทนการวินิจฉัยหรือการรักษาโดยไม่มี validation
- [Kortelainen et al., 2010](https://pubmed.ncbi.nlm.nih.gov/20403790/) — งาน bed sensor สำหรับ Wake/NREM/REM และข้อจำกัดของ agreement
- [Tuominen et al., 2019](https://pubmed.ncbi.nlm.nih.gov/30853052/) — Beddit ไม่สามารถแยก NREM stages และตรวจ REM ได้เพียงพอในการ validation
- [CReSS cardiorespiratory sleep staging study](https://pubmed.ncbi.nlm.nih.gov/33660612/) — หลักฐานว่าการทำ staging จาก cardiorespiratory signals ต้องพัฒนาและ validate กับ reference standard
