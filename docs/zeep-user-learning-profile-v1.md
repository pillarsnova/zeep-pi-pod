# ZEEP User Learning Profile v1

สถานะ: ใช้งานบน Pi · Wellness only · Recommendation-first
Contract: `zeep.user-learning-profile.v1`
Policy: `zeep.user-learning-policy.v1`

## เป้าหมาย

ระบบรวม Session ของบัญชีเดียวกันด้วย normalized email/account key แล้วตอบได้ว่า
ผู้ใช้เคยพักแบบใดบ้าง โดยแยกผลของสองรูปแบบตลอดสาย:

- `sleep` — Overnight Recovery ใช้ Sleep Score
- `nap_recovery` — Nap & Refresh ใช้ Recovery Score

คะแนนสองชนิดไม่ถูกเฉลี่ยหรือเปรียบเทียบข้ามกัน Session ที่ไม่มีคะแนนหรือไม่มี
Sensor data ยังนับเป็นประวัติการใช้งาน แต่ไม่ถูกแทนด้วยศูนย์และไม่ถูกใช้เรียนรู้

## API

```http
GET /api/v1/usage-sessions/longitudinal
```

- User ไม่ต้องและไม่ควรส่ง email ระบบใช้บัญชีที่ Login อยู่
- Admin ต้องเลือกบัญชีด้วย header `X-Zeep-Account-Key`; ห้ามใส่อีเมลใน URL
- Response ใช้ `Cache-Control: private, no-store`
- ไม่ส่ง Raw Sensor, คำตอบแบบสอบถาม, token หรือข้อมูลวินิจฉัย
- `user` ใช้แสดงตัวตนให้เจ้าของบัญชี/Admin เท่านั้น

Context สำหรับ AI ใช้ endpoint แยก:

```http
GET /api/v1/usage-sessions/longitudinal/ai-context
```

AI context ตัด email, ชื่อ, Session ID, exact Session timestamp, คำตอบแบบสอบถาม
และ demographic value ออก แต่ยังเป็น **ข้อมูล Wellness ส่วนบุคคลที่เชื่อมโยงกลับ
เจ้าของบัญชีได้** ไม่ใช่ข้อมูลนิรนาม จึงห้ามส่งออกไปยังโมเดลภายนอกในรุ่นนี้
จนกว่าจะมี purpose-specific consent และนโยบาย retention/processor ที่อนุมัติแล้ว

ฟังก์ชัน egress ภายในจะคืนเฉพาะ object `data` ที่ผ่าน response model, enum และ
allowlist ของ version/status แล้ว ห้ามส่ง response envelope, Profile เต็ม, log หรือ
Session detail เข้า prompt โดยตรง แม้เป็นการทดลอง

ตัวอย่างย่อ:

```json
{
  "kind": "user_learning_profile",
  "data": {
    "contract_version": "zeep.user-learning-profile.v1",
    "observed_history": {
      "session_count": 8,
      "data_backed_session_count": 7,
      "without_sensor_data_count": 1,
      "modes_used": ["sleep", "nap_recovery"],
      "without_score_count": 1
    },
    "modes": {
      "sleep": {
        "label": "Overnight Recovery",
        "session_count": 3,
        "latest_score": 86,
        "score_title": "Sleep Score"
      },
      "nap_recovery": {
        "label": "Nap & Refresh",
        "session_count": 5,
        "latest_score": 82,
        "score_title": "Recovery Score"
      }
    },
    "learning_readiness": {
      "status": "growing",
      "personalization_data_ready": true,
      "personalization_inference_authorized": false,
      "recommendation_mode": "not_authorized",
      "automatic_device_control": false
    }
  }
}
```

## การแบ่งชั้นข้อมูล

### 1. Observed facts

เป็นสิ่งที่ฐานข้อมูลยืนยันได้โดยตรง เช่น จำนวน Session, รูปแบบที่เลือก, เวลา,
คะแนนที่เผยแพร่แล้ว และเป้าหมาย Nap 30/90 นาที

### 2. Derived patterns

เป็นการคำนวณที่ย้อนตรวจได้ เช่น ค่าเฉลี่ยใน cohort เดียวกันและความต่างระหว่าง
คะแนนล่าสุดกับครั้งก่อน โดย trend จะเทียบเฉพาะ score formula version เดียวกัน
Overnight ใช้ cohort `overnight_7h`; Nap แยก `nap_30` และ `nap_90` เสมอ

คำว่า environment baseline หมายถึง “สภาพแวดล้อมที่เคยบันทึกได้” ไม่ใช่
“ค่าที่ผู้ใช้ชอบ” จนกว่าจะมีการเลือกหรือ feedback ยืนยัน

Personal comparison เปิดใช้ต่อเมื่อ provenance ตรงกันครบ 4 จุด: behavior policy
`zeep-personal-behaviour-baseline-v1.1-formula-target-specific`, mode, target และ
score formula version หากข้อใดไม่ตรง ระบบยังแสดงประวัติจริง แต่ไม่แสดงการเทียบ
Baseline หรือ trend ข้ามรุ่น

สำหรับผลที่สร้างด้วยสูตรปัจจุบันต้องมี `duration_target` ในผลคะแนน และเมื่อ Session
มี `target_duration_s` ค่าทั้งสองต้องตรงกัน: Overnight ต้องเป็น 7 ชั่วโมง ส่วน Nap
ต้องเป็น 30 หรือ 90 นาทีตามที่เลือก หากข้อมูลขัดกันหรือ metadata ของผลคะแนนหาย
ระบบจะคง Session ไว้ในประวัติ แต่ระงับคะแนนและติดธงให้ Admin ตรวจสอบ ข้อมูล Nap
รุ่นเก่าที่ไม่มี target ฝั่ง Session ยังอ่านย้อนหลังได้ แต่จะไม่ถูกเดาว่าเป็น 30/90
นาทีและไม่เข้า Personal Baseline ของ target ใด

### 3. Recommendations

รุ่นนี้เตรียมข้อมูลและบอก `personalization_data_ready` เท่านั้น ส่วน
`personalization_inference_authorized` เป็น `false` แบบ fail-closed จนกว่าจะมี
ความยินยอมเฉพาะวัตถุประสงค์ AI Personalisation หากเปิดในอนาคต AI มีหน้าที่เสนอ
คำแนะนำที่อธิบายเหตุผลได้ ผู้ใช้หรือ Admin ต้องยืนยันก่อนส่งคำสั่งจริง Safety
Supervisor ตรวจซ้ำทุกครั้ง และ Sleep State ไม่ใช่คำสั่งควบคุมอุปกรณ์โดยตรง

## ระดับการเรียนรู้

ระดับคำนวณจาก cohort ที่ใหญ่ที่สุด โดยไม่รวม Overnight กับ Nap และไม่รวม Nap 30
กับ Nap 90:

| ระดับ | ข้อมูลในโหมดเดียวกัน | สิ่งที่ระบบทำได้ |
|---|---:|---|
| `no_data` | 0 | ใช้ค่าเริ่มต้นของ ZEEP |
| `learning` | 1–2 | แสดงข้อเท็จจริงของผู้ใช้ |
| `growing` | 3–6 | เริ่มเทียบ Personal Baseline และเสนอ candidate |
| `established` | 7+ | แนวโน้มชัดขึ้น แต่ยังไม่อนุญาต Auto Control |

Baseline จะใช้เฉพาะ Session ที่ผ่านเกณฑ์ของโมเดล จึงอาจใช้ Session น้อยกว่า
จำนวนที่แสดงในประวัติได้ นี่เป็น QA ที่ตั้งใจไว้ ไม่ใช่ข้อมูลหาย

Nap 30 และ Nap 90 แสดงจำนวนครั้ง คะแนนล่าสุด ค่าเฉลี่ย/มัธยฐาน แนวโน้ม และ
Personal Baseline แยกใน `targets` คะแนนรวมระดับ `nap_recovery` จึงจงใจไม่แสดง
ค่าเฉลี่ยหรือแนวโน้มรวม การมีประวัติบ่อยยังไม่ใช่หลักฐานว่าผู้ใช้ชอบเป้าหมายนั้น

## ข้อมูล Profile และ Consent

Contract บอกเพียงว่ามีข้อมูล Profile ช่องใดและแบบสอบถามคืบหน้าเท่าไร โดยไม่ส่ง
ค่าคำตอบออกมาให้ AI รุ่นนี้ Generic progressive-profile consent ปัจจุบันใช้เพื่อ
แสดงบริบทในบัญชีเดียวกันเท่านั้น และ **ไม่ใช่** consent สำหรับ AI inference,
external AI egress หรือ cross-user model training

ข้อมูลต่อไปนี้ไม่ใช้สร้างข้อสรุปสุขภาพหรือสั่งอุปกรณ์:

- กรุ๊ปเลือดและเชื้อชาติ
- exact DOB
- โรคหรือการวินิจฉัย
- การคาดเดาว่าสูบบุหรี่ ตั้งครรภ์ มีภาวะหยุดหายใจ หรือมีปัญหาสุขภาพ

หากถอน consent ระบบต้องไม่ใช้ optional answers ในผลใหม่ และการลบบัญชีบน Pi จะลบ
Profile, Session, BCG, derived Personal Baseline, Browser Session และ pending
upload/share/profile ของ canonical account และ legacy aliases จาก active store
โดยตรวจ database flush และ dormant Session checkpoint ก่อนรายงานสำเร็จ การลบ
บัญชีจะเพิกถอน Offline Login ticket ที่ยังค้างทั้งหมดเพื่อไม่ให้ capability เดิม
สร้างบัญชีที่ลบกลับมาได้

Daily backup เป็น recovery boundary แยกต่างหาก เก็บแบบหมุนเวียนไม่เกิน 3
archive รายวันและไม่ถูกใช้สร้าง Baseline หรือคำแนะนำ สำเนาใน backup จึงอาจคงอยู่
จนหมดรอบเก็บรักษา และห้าม restore เข้า Production โดยไม่ผ่านขั้นตอนทบทวนคำขอลบ
ข้อมูล ส่วน operational log อยู่ภายใต้ retention ของระบบและไม่ใช่ข้อมูลนำเข้า AI

ขอบเขตนี้คือ `local_active_store` ไม่ใช่การยืนยันว่าข้อมูลถูกลบจาก ZEEP Backend
หรือ object ที่อัปโหลด/แชร์สำเร็จแล้ว การลบส่วนกลางและการเพิกถอน artifact ต้องใช้
Backend delete/revoke API และ durable remote-artifact ledger ซึ่งยังไม่เปิดในรุ่นนี้

## Single-Pod และ Multi-Pod

Profile นี้รวม Session ที่จบแล้วทั้งหมดบน Pi เครื่องปัจจุบันตั้งแต่ Product cutover
`2026-09-01` รวมถึง Session ที่ไม่มี Timeline โดยแยกจำนวนให้เห็นชัด การรวมหลาย ZEEP Pod ต้องทำที่
ZEEP Backend ด้วย immutable `userPublicId`; ไม่ควรส่ง email เพิ่มใน ingest payload
เพียงเพื่อทำ cross-Pod aggregation

## ขั้นถัดไป

1. เพิ่ม purpose-specific consent สำหรับ Personalisation, Research และ Model Training
2. เก็บ feedback ต่อคำแนะนำ: ยอมรับ แก้ไข ปฏิเสธ และผลหลังปรับ
3. เพิ่ม immutable baseline ID, input hash และ calibration/model manifest
4. รวมประวัติหลาย Pod ที่ Backend ด้วย immutable `userPublicId`
5. เปิด Adaptive Control เฉพาะหลังผ่าน G2 พร้อม physical acknowledgement
