# ZEEP Acoustic Intelligence Shadow Validation Plan

Protocol ID: **ZEEP-ACOUSTIC-SHADOW-001**

Version: **1.0.0**

Status: **Pending approval**

Owner: **ZEEP Acoustic Validation Lead**

Required gates: **G1 + G3**

## สรุปสำหรับทีม

ระบบปัจจุบันวัดระดับ `sound_dba` จาก ESP32 ได้ แต่ยังไม่มีข้อมูลที่เพียงพอสำหรับ
จำแนกรูปแบบหรือแหล่งเสียงอย่างน่าเชื่อถือ หน้า Admin จึงแสดง `snore_like`,
`speech_like` และ label อื่นเป็น **Research Candidate · กำลังพิสูจน์** ไม่ใช่ผลตรวจ
และไม่ใช้เปลี่ยน Sleep State, Sleep Score, Recovery Score หรือคำสั่งอุปกรณ์

ค่าปัจจุบันเป็นระดับเสียงและ packet-level energy aggregation ไม่ใช่ certified
LAeq(A) การพิสูจน์ระดับเสียงกับ CEM DT-8852 ไม่ได้พิสูจน์ classifier หรือชนิดเสียง

## 1. ขอบเขตความสามารถที่ต้องพิสูจน์

| กลุ่ม | Candidate | ข้อจำกัดการแสดงผล |
|---|---|---|
| Signal shape | `quiet_steady`, `steady`, `tonal`, `impulsive`, `intermittent`, `modulated` | อธิบายรูปสัญญาณ ไม่ฟันธงแหล่งกำเนิด |
| Equipment/context | `airflow_like`, `compressor_transition_like`, `ventilation_or_purifier_like`, `zeep_audio_likely`, `door_or_mechanical_like`, `movement_or_bedding_like` | ใช้คำว่า “คล้าย/น่าจะ” และรองรับ `other_or_unresolved`, `mixed`, `unknown` |
| Human-sound research | `speech_like`, `snore_like`, `cough_like`, `breathing_pattern_like` | ต้องมี purpose-specific consent; ไม่ถอดคำ ไม่ระบุตัวบุคคล ไม่วินิจฉัยโรค |

ห้ามสร้าง label `apnea` จากไมโครโฟนหรือ BCG flag ชุดนี้ BCG status 5 เป็นเพียง
ข้อมูลประกอบจากอุปกรณ์คนละเส้นทาง ไม่ใช่ ground truth ของ `snore_like`

## 2. ลำดับพิสูจน์

1. **P0 · Provenance** — ยืนยัน Production firmware source, version, checksum,
   GPIO, sample format และเส้นทาง `sound_dba` แบบทำซ้ำได้
2. **P1 · DSP feature telemetry** — เพิ่ม packet ที่มี schema/version, `boot_id`,
   sequence, monotonic time, coverage, clipping, spectral และ temporal features;
   Pi รับด้วย strict allowlist และ fail-soft โดยไม่ส่ง PCM
3. **P2 · Controlled equipment dataset** — บันทึก ambient, แอร์ fan 1–5,
   compressor start/run/stop, ventilation/purifier, เพลง 20/40/60%, ประตู,
   เตียงและเหตุการณ์ผสม หลายรอบ หลาย Pod และหลายตำแหน่ง
4. **P3 · Human-sound research** — เริ่มจากเสียงสังเคราะห์หรือไฟล์ที่มีสิทธิ์ใช้
   จากนั้นจึงใช้ข้อมูล coded ของอาสาสมัครที่มี notice/consent แยก
5. **P4 · Admin shadow pilot** — แสดงผลพร้อม confidence band, reason codes,
   unknown rejection และ provenance ให้ทีมตรวจ โดยไม่มี public claim
6. **P5–P6 · Graduation review** — เปิด aggregate หรือข้อความผู้ใช้เฉพาะ class
   ที่ผ่าน G1, G3, metric threshold และ Product/Privacy copy review

## 3. Ground truth และการแบ่งข้อมูล

- ใช้นาฬิกาที่ sync, operator annotation แบบ controlled vocabulary และ device event
  log; command ACK เพียงอย่างเดียวไม่ถือว่าอุปกรณ์กายภาพสร้างเสียงจริง
- CEM DT-8852 ใช้ตรวจ path ระดับเสียง ส่วน golden PCM/synthetic vectors ที่ทราบ
  frequency, amplitude, impulse และ modulation ใช้ตรวจ DSP features
- แบ่ง train/validation/test ตาม Pod, run, date และ participant ห้ามสุ่มหน้าต่าง
  10 วินาทีจาก Session เดียวกันข้ามชุด
- ต้องมี unseen Pod, unseen source และ mixed-source holdout
- Threshold และจำนวนตัวอย่างขั้นต่ำราย class ต้อง pre-register ก่อนเปิดดูผล validation

## 4. Metric และรายงานที่ต้องมี

- valid feature coverage, packet loss, clipping, latency, CPU/RAM
- precision, recall, F1 และ confusion matrix **ราย class**
- false alerts/hour ในช่วง quiet/stable
- unknown/rejection rate และผลต่อ source ที่ไม่เคยเห็น
- event onset/end error, restart continuity และ packet-gap behavior
- calibration/reliability ก่อนแสดง confidence เป็นเปอร์เซ็นต์; ระหว่างนี้ใช้เพียง
  `low`, `medium`, `high`, `unavailable`
- public redaction, retention, erasure และ no-score/no-actuation regression

ผลรวม accuracy เพียงค่าเดียวไม่เพียงพอ การอนุมัติทำแยกราย class เช่น
`airflow_like` อาจผ่านก่อน `speech_like` หรือ `snore_like`

## 5. Privacy และ Data Governance

- ค่าเริ่มต้นคือไม่ส่งและไม่เก็บ Raw PCM, ไม่ประมวลผลเนื้อหาคำพูด และไม่ทำ
  speaker identity
- Derived feature ที่ผูกเวลา/Session ยังเป็นข้อมูลที่ link กลับได้ จึงต้องมี notice,
  purpose, access, retention, backup และ account-erasure contract
- หากจำเป็นต้องเก็บ snippet เพื่อวิจัย ต้องเป็น protocol แยก: consent เฉพาะ,
  coded identity, encryption, access log, retention limit และ erasure owner
- Annotation ห้ามใช้ free text เมื่อ controlled vocabulary เพียงพอ เพื่อลด PII

## 6. Gate และเกณฑ์ปล่อย

### G1 · Hardware / Safety — Pending

ผู้อนุมัติ: **ZEEP Safety Lead**

- firmware/feature provenance ครบและ fail-soft เมื่อไมค์หรือ feature หาย
- acoustic pipeline ไม่ทำให้ Environment, Session หรือ Safety หยุด
- ไม่มี classifier output ใดส่งคำสั่งอุปกรณ์อัตโนมัติ

### G3 · Research / Privacy / Claims — Pending

ผู้อนุมัติ: **ZEEP Research Governance Lead**

- protocol, dataset register, consent/notice และ metric threshold อนุมัติแล้ว
- รายงาน holdout และข้อจำกัดราย class พร้อมตรวจซ้ำได้
- API/UI ใช้ positive allowlist และไม่มี Raw PCM/คำพูด/ตัวระบุบุคคลหลุดออก

ก่อน G1 และ G3 ผ่าน UI ต้องใช้สถานะ `not_evaluated` และคำว่า “กำลังพิสูจน์”
เท่านั้น หลังผ่านทั้งสอง Gate ยังต้องอนุมัติ class-specific metrics ก่อนเลื่อนเป็น
`admin_validated`; การเปิดให้ผู้ใช้เห็นหรือสั่งงานอัตโนมัติต้องมี release แยก

## 7. Audit record ที่ต้องเก็บ

บันทึก protocol/model/firmware/feature schema version, Pod ID, test split,
dataset checksum, threshold revision, approver และวันที่อนุมัติทุกครั้ง ผลเก่าต้อง
ย้อนดูได้เมื่อ classifier เปลี่ยน แต่ห้ามแก้ Raw/ground truth เพื่อทำให้ผลดีขึ้น
