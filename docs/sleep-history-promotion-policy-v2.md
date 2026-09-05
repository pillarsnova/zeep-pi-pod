# ZEEP Historical Derived-Result Promotion Policy v2

> **สถานะ:** Review candidate · ต้องได้รับคำยืนยันจาก Product Owner ก่อน Apply
>
> **ขอบเขต:** ZEEP Wellness estimate หลังวันที่ 1 ก.ย. 2569 สำหรับ Session ที่จบแล้ว
> และยาวกว่า 25 นาที · ไม่ใช่ AASM/PSG diagnosis
>
> **หลักสำคัญ:** Raw BCG และ Timeline เป็นข้อมูลต้นฉบับ ห้ามแก้ไขจากกระบวนการนี้

## 1. เหตุผลที่ปรับนโยบาย

นโยบายเดิมใช้คุณภาพข้อมูลทั้ง Session เป็น Gate เดียว: ต้องเป็น Tier A และไม่มี
`manual_review_flags` จึงเขียน Derived Sleep State/Report ได้ วิธีนี้ทำให้ช่วงเวลาที่มี
Bed + HR + RR + BCG ครบและประเมินได้จริงถูกทิ้งตาม Session ทั้งก้อน เมื่อส่วนอื่นของ
Session ขาดข้อมูล หรือมีเพียงคำเตือนด้านสัดส่วน/coverage

นโยบาย v2 แยกหน้าที่ของข้อมูลออกเป็นสามชั้น:

1. **Quality Tier:** ความครบถ้วนภาพรวมสำหรับ Admin QA เท่านั้น
2. **Review Warning:** ค่าผิดจากรูปแบบทั่วไปหรือ coverage ต่ำ ใช้ให้คนตรวจเพิ่ม
3. **Promotion Blocker:** ความผิดพลาดด้านความสมบูรณ์/invariant ที่ไม่ปลอดภัยต่อการเขียน

Product Owner เป็นผู้กำหนด cohort และเป็นผู้อนุมัติ Apply สุดท้าย ระบบไม่ได้ใช้ Tier
หรือคำเตือนมาแทนสิทธิ์ตัดสินใจของ Product Owner

## 2. การตัดสินเป็นราย Epoch

- Sensor/BCG ถูกจัดเป็น bucket 10 วินาที
- ทุก 30 วินาที ระบบพิจารณาหน้าต่างข้อมูลล่าสุด 60 วินาที
- ต้องมี bucket ที่ valid อย่างน้อย 80% ของหน้าต่าง จึงสร้าง evidence
- bucket ต้องมีจำนวน BCG packet, paired HR/RR และตัวอย่าง waveform ผ่านเกณฑ์กลาง
- Epoch ปัจจุบันทั้ง 30 วินาทีต้องมี Bed + HR + RR + Raw BCG ครบทุก bucket;
  coverage 80% ของหน้าต่าง 60 วินาทีใช้เพื่อบริบท/confirmation เท่านั้น ไม่ได้อนุญาต
  ให้เติม Stage ลงใน Epoch ปัจจุบันที่ข้อมูลขาด
- Off-bed ต่อเนื่องหรือข้อมูลขาดจะ reset context ตามนโยบายกลาง
- Evidence ที่ผ่านจึงเข้าสู่ Semi-Markov confirmation 60 วินาที หรือ N2 120 วินาที
- ช่วงที่ไม่ผ่านไม่มี W/N1/N2/N3/REM ใหม่ และไม่ถูกนำไปนับ Stage%, Score หรือ Baseline
- ทุก Epoch 30 วินาทีที่ไม่มี State ต้องมีสถานะปฏิบัติการอย่างใดอย่างหนึ่ง:
  `WAIT`, `NO DATA` หรือ `OFF BED` พร้อมเหตุผลและ coverage

ดังนั้น Session ระดับ B หรือ `below_B` ยังมี Derived State ได้เฉพาะช่วงที่หลักฐานจริง
ครบ โดยไม่เติมค่าในช่องว่างและไม่เดาจากสภาพแวดล้อม

### Baseline Fit ถูกใช้จริงอย่างไร

- ทุก State ได้ HR interval fit และ RR interval fit จาก Age + Gender baseline
- รวมเป็น physiological fit ด้วยน้ำหนัก HR `0.50` และ RR `0.40`
- เมื่อ gate ของ State เปิด Fit เป็นส่วนหนึ่งของ evidence budget: W `30%`,
  N1 `25%`, N2 `25%`, N3 `15%` และ REM `20%`
- เมื่อคิดกับ physiological fit ที่มีเพดาน `0.90` ผลต่อ evidence budget สูงสุดคือ
  W `27`, N1 `22.5`, N2 `22.5`, N3 `13.5` และ REM `18` จุดจาก 100
- รุ่น v1.26 ผสาน distribution ดังกล่าวกับ gated stage evidence อีกชั้นที่น้ำหนัก
  `20%`; เมื่อ Fit สูงสุดจริงตรงกับ State ที่ยืนยันก่อนหน้าและ State นั้นยังผ่าน
  gate ใช้น้ำหนัก `35%` เพื่อเพิ่ม continuity โดยไม่บังคับ State
- Baseline Fit ช่วยจัดอันดับเฉพาะ State ที่ physiology gate เปิดแล้ว ไม่สามารถสร้าง
  N2/N3/REM, ข้าม transition หรือเติม State ใน WAIT/NO DATA/OFF BED ได้
- Admin เห็น Baseline Fit, ระยะห่างจากช่วง HR/RR และน้ำหนักที่ใช้ได้โดยตรง
- Personal Baseline ยังใช้เป็นบริบท/ความมั่นใจเท่านั้น การให้ผลเดิมของโมเดลกลับมา
  ฝึกตัวเองเพื่อเลือก State ถูกปิดไว้จนกว่าจะมี independent reference labels

## 3. Quality Tier สำหรับ Admin QA

เกณฑ์เดิมถูกรักษาไว้เพื่อให้รายงานย้อนหลังเทียบกันได้ แต่ไม่ใช่ allowlist:

| Tier | Timeline HR/RR | Raw HR/RR | Raw acquisition | Maximum gap |
|---|---:|---:|---:|---:|
| A | ≥90% | ≥90% | ≥95% | <60 วินาที |
| B | ≥80% | ≥80% | ≥80% | ไม่ใช้เป็น Gate |
| below_B | ต่ำกว่า B อย่างน้อยหนึ่งแกน | | | |

## 4. Review Warning — ไม่ขวางการเขียน State

- คะแนน Wellness ยังไม่ผ่าน release coverage
- ไม่มี Epoch ที่มี physiological evidence ครบ
- ไม่มี State ที่ผ่าน confirmation โดย Session อาจมีแต่ WAIT/NO DATA/OFF BED
- N1/N2/N3/REM ของ Overnight ต่างจากกรอบตรวจทาน
- Overnight ไม่มี N3 หรือ confirmed coverage ต่ำกว่า 80%
- Nap ยาวกว่า 90 นาที
- พบการสลับ State กลับไปกลับมาภายใน 60 วินาที

คำเตือนเหล่านี้ต้องแสดงใน Admin และเก็บใน artifact แต่ไม่ได้พิสูจน์ว่าข้อมูลผิด
โดยเฉพาะสัดส่วน Stage ซึ่งยังไม่มี independent PSG label

## 5. Promotion Blocker — ห้ามเขียน Derived Result

- ไม่มี Raw BCG packet
- พบ transition ที่นโยบายกลางไม่อนุญาต
- มี State ถูกยืนยันทั้งที่ gate ของ State ปัจจุบันไม่ผ่าน
- Artifact, code, input hash, Session identity หรือ reviewed allowlist ไม่ตรง
- Session ยังไม่จบ, อยู่ก่อน cutover หรือสั้นไม่ถึง cohort ที่ Product Owner กำหนด
- SQLite/WAL lock, integrity, staging parity หรือ immutable-Raw hash ไม่ผ่าน

Issue code ใหม่ที่ยังไม่ได้จำแนกจะ fail closed เป็น blocker จนกว่าจะได้รับการทบทวน

การไม่มี Evidence หรือไม่มี W/N1/N2/N3/REM ไม่ใช่ฐานข้อมูลเสียโดยอัตโนมัติ ระบบ
สามารถเขียนสถานะ WAIT/NO DATA/OFF BED และคำเตือนได้โดยไม่สร้าง Sleep Stage ปลอม

## 6. State Promotion และ Score Release เป็นคนละเรื่อง

Derived Sleep State ที่มีหลักฐานสามารถเขียนได้แม้คะแนนยังไม่พร้อมเผยแพร่ คะแนนมี
release gate ของตนเองตาม Rest Mode และ coverage:

- `Overnight Recovery` ใช้ `Sleep Score`
- `Nap & Refresh` ใช้ `Recovery Score`; ไม่บังคับว่าต้องหลับ
- หากคะแนนไม่ผ่าน release gate จะเก็บ engineering shadow score สำหรับ Admin
  แต่ค่าที่ผู้ใช้เห็นเป็น “ข้อมูลยังไม่พอ” ไม่ใช่ศูนย์
- รายงานต้องแสดง Recording, BCG, HR/RR และ Sleep State coverage พร้อมสัดส่วน
  Confidence สูง/ปานกลาง/ต่ำ เพื่อแยก “ผลที่คำนวณได้” จาก “ความมั่นใจของหลักฐาน”

ก่อน Apply ผู้อนุมัติต้องตรวจ Session ที่คะแนนเดิมเคยมี แต่คะแนนรุ่นใหม่ถูกระงับ เพราะ
การเขียนรายงานใหม่อาจเปลี่ยนค่าที่เผยแพร่แล้วเป็น “ข้อมูลยังไม่พอ”

## 7. Workflow ที่บังคับใช้

1. ดึง code version ที่จะใช้และสร้าง read-only replay artifact
2. สร้าง summary/details พร้อม input hash, source hash และ allowlist
3. ใช้ `compare_sleep_history_replay.py` สร้างค่าเดิม–ค่าใหม่
4. Product Owner ตรวจ Stage, Score, warnings, blockers และยืนยันราย Session/cohort
5. หยุด service และยืนยันไม่มี writer ก่อน Apply
6. สร้าง rollback backup และทำงานบน private staging copy
7. ตรวจ exact report parity, SQLite integrity และ Raw/Timeline hash
8. เขียน Derived Result ผ่าน SQLite backup API แล้วสร้าง promotion audit manifest

## 8. ข้อกำหนดที่ Product Owner อนุมัติ

1. ประมวลผลทุก Session ในขอบเขตวันที่และระยะเวลาที่กำหนด
2. ตัดสินหลักฐานราย Epoch ไม่ตัดทั้ง Session จาก Tier
3. คำนวณ W/N1/N2/N3/REM เฉพาะ Epoch ที่ Bed + HR + RR + BCG ครบ
4. Epoch อื่นต้องเป็น WAIT, NO DATA หรือ OFF BED
5. Tier A/B เป็น Admin QA เท่านั้น
6. Review Warning ไม่ปิดกั้นการเขียนโดยอัตโนมัติ
7. Hard Block ใช้กับฐานเสีย, Raw หาย, Session ไม่จบ หรือ invariant ผิด
8. Overnight ใช้ Sleep Score; Nap & Refresh ใช้ Recovery Score
9. แสดง coverage และ confidence ประกอบทุกผล
10. Raw ไม่เปลี่ยน และต้องเก็บผลเดิม/backup/audit สำหรับย้อนกลับ

การเปลี่ยนนโยบายนี้ไม่ใช่การยืนยัน clinical accuracy; G2 paired PSG/AASM validation
ยังเป็นงานแยกและยังคงสถานะ `NO_GO` สำหรับคำกล่าวอ้างระดับ clinical
