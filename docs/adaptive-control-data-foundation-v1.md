# ZEEP Adaptive Control Data Foundation v1

สถานะ: **Live Shadow Monitor · ไม่มีการสั่งอุปกรณ์อัตโนมัติ**

Contract: `zeep.adaptive-learning-live.v1`

ขอบเขต: Pi5 `/monitor` และ `GET /api/v1/admin/adaptive/live`

## 1. เป้าหมาย

ระบบรุ่นนี้ทำให้ทีมเห็นข้อมูลสด, คุณภาพข้อมูล, Personal Baseline, สถานะ
Sleep Estimator, สถานะอุปกรณ์ และคำแนะนำจาก Smart Response ในมุมเดียวกัน
เพื่อเตรียมข้อมูลสำหรับสร้างและทดสอบ Adaptive Control Model ภายหลัง

รุ่นนี้ **ไม่ใช่ AI Control ที่เปิดใช้งานแล้ว** และไม่เปลี่ยน Sleep Score,
Recovery Score, Sleep State, Safety Logic หรือคำสั่งอุปกรณ์ใด ๆ

## 2. สิ่งที่แสดงแบบ Live

| กลุ่ม | ข้อมูล | ความถี่ต้นทาง |
|---|---|---:|
| Physiology | HR, RR, Movement, Bed/BCG quality | Sensor frame 10 วินาที |
| Environment | อุณหภูมิ, ความชื้น, CO₂, PM2.5, VOC Index, Lux, dBA | Sensor frame 10 วินาที |
| Sleep evidence | State, confirmed State, provisional, confidence | Evidence 30 วินาที; ยืนยัน 60/120 วินาที |
| Baseline | จำนวน Session, maturity, median/IQR และค่าประจำตัวตาม Mode | หลัง Session จบ |
| Device intent | แอร์,เพลง,เตียงและ GPIO ล่าสุด | เมื่อ State/ACK เปลี่ยน |
| Shadow recommendation | หลักฐาน, blocker และสิ่งที่เสนอ | เทียบจาก canonical frame เดียวกัน |
| Provenance | estimator, evidence, baseline, transition, Smart Response และ frame sequence | ทุก payload |

Environment ใน contract นี้มี **7 measurement metrics** ได้แก่ อุณหภูมิ,
ความชื้น, CO₂, PM2.5, VOC Index, Lux และ dBA ส่วน HR/RR เป็น Physiology
คนละกลุ่ม และ Sleep/Bed State เป็น derived state ไม่ถูกนับเป็น Environment Sensor
ขณะที่ `environment_live`/`environment_total` ใน `data_quality` นับ **อุปกรณ์
กายภาพ 6 ตัว** (SHT3x หนึ่งตัวให้ทั้งอุณหภูมิและความชื้น) จึงไม่ใช่จำนวน metric

ค่า Live และ Baseline ถูกแสดงคู่กันเป็น `ใกล้`, `สูงกว่า` หรือ `ต่ำกว่า
ค่าประจำตัว` เท่านั้น คำเหล่านี้ไม่เท่ากับปกติ/ผิดปกติทางการแพทย์
ค่าเฉลี่ยเสียงใน rolling window เป็นค่าเฉลี่ยเชิงพลังงานของ valid `sound_dba`
observations ไม่ใช่ค่าเฉลี่ยเลขคณิต และยังไม่อ้างว่าเป็น certified LAeq(A)
จนกว่า firmware contract จะยืนยัน weighting/window/calibration ส่วน Shadow
recommendation จะอ่านค่าได้ต่อเมื่อ Sensor ของ metric นั้นเป็น Live

## 3. Baseline ที่ใช้เปรียบเทียบ

1. Sleep State รุ่น Pilot ยังใช้ **Age + Gender Baseline** เป็นแหล่งที่มีผลจริง
2. Personal Baseline เป็น Candidate/บริบทเพื่อดูความต่างและความต่อเนื่อง
3. `personal_direct_stage_influence=false` จนกว่าจะผ่าน Validation Gate
4. Environment/RR เปรียบเทียบเฉพาะ Session ที่จบแล้วใน Mode เดียวกัน
5. HR/Movement ใช้ Qualified Overnight physiology reference; ใน Nap จะแสดง
   provenance ว่าเป็น `qualified_overnight_reference` ไม่อ้างว่าเป็น Nap Baseline
6. หากข้อมูลยังไม่พอ จะแสดง `กำลังเรียนรู้` ไม่แทน Reference เป็นศูนย์

การแยก Active Baseline ออกจาก Personal Candidate ป้องกัน feedback loop ซึ่ง
Model รุ่นหนึ่งสร้าง State แล้วนำ State ของตัวเองกลับไปฝึกจนค่าค่อย ๆ drift

## 4. Data flow ปัจจุบัน

```text
Sensor Hub 1/2 + BCG
        │
        ▼
Canonical Sensor Frame (10 s) ──► Safety Supervisor
        │
        ├──► Session Timeline + Raw BCG + Sleep Evidence
        │
        ├──► Personal Baseline (อัปเดตหลัง Session จบ)
        │
        └──► Adaptive Learning Live
                 ├── Live vs Baseline
                 ├── Data quality / missingness
                 ├── Device intent
                 ├── Shadow recommendation
                 └── Version provenance
                         │
                         └── X ไม่มี Command/Actuation
```

หน้า Monitor รับ payload ผ่าน WebSocket เดิม ส่วน API สำหรับทีมพัฒนาใช้:

```http
GET /api/v1/admin/adaptive/live
Cache-Control: private, no-store
```

ใช้ได้เฉพาะ Browser Session ของ Admin ผลลัพธ์ไม่มี Raw waveform, password,
token หรือคำตอบแบบสอบถาม และไม่เปิดให้บัญชี User อ่านข้าม Session

## 5. โครงสร้างข้อมูลหลัก

```json
{
  "schema_version": "zeep.adaptive-learning-live.v1",
  "observation_id": "session-id:canonical-frame-sequence",
  "mode": "shadow",
  "control_policy": {
    "automatic_actuation": false,
    "recommendation_only": true,
    "sleep_state_as_actuator_input": false,
    "command_endpoint": null,
    "safety_supervisor_authoritative": true
  },
  "data_quality": {
    "environment_live": 6,
    "environment_total": 6,
    "vital_pair_live": true,
    "window_coverage_pct": 100.0
  },
  "baseline": {
    "status": "active",
    "sessions_used": 4,
    "mode_group": "sleep",
    "behaviour_reference_same_mode_only": true,
    "physiology_reference_scope": "prior_completed_same_mode_sessions",
    "prior_completed_sessions_only": true,
    "active_stage_source": "age_gender",
    "personal_direct_stage_influence": false
  },
  "live_features": [
    {
      "key": "heart_rate",
      "value": 61.0,
      "reference": 60.0,
      "delta": 1.0,
      "comparison": "near_reference",
      "reference_scope": "prior_completed_same_mode_sessions",
      "medical_interpretation": false
    }
  ],
  "candidate_recommendations": [
    {
      "domain": "sound",
      "decision_id": "session-id:frame:sound",
      "candidate": "เสนอให้ลดระดับเสียง",
      "executable": false
    }
  ],
  "versions": {}
}
```

หมายเหตุด้าน provenance: ตัวอย่างข้างต้นใช้ `mode_group: sleep` สำหรับ
Overnight เท่านั้น Behavior/score Baseline ของ Nap แยก `nap_30` และ `nap_90`
ใน implementation แล้ว แต่ HR/Movement ยังอ้าง
`qualified_overnight_reference`; ต้องส่ง scope จริงใน payload และห้ามเรียกว่า
Nap physiology baseline จนกว่าจะมีการ validate reference แยกตามเป้าหมาย

## 6. ข้อมูลที่มีแล้วสำหรับ Replay/Model Development

- `sessions.db/timeline`: Environment, HR, RR และ Bed ทุก 10 วินาที
- `sessions.db/events`: Sleep evidence, confirmed State และคำสั่งที่เกิดใน Session
- `bcg.db`: Raw BCG แยกจาก derived result
- `data/baselines.json`: Personal physiology และ behavior แยกตาม Mode
- Final report: Sleep Score หรือ Recovery Score พร้อม formula version

ชุดข้อมูลเหล่านี้สร้าง Offline replay ได้โดยไม่แก้ Raw file อย่างไรก็ตาม ก่อนทำ
causal Adaptive Model ต้องเพิ่ม join ต่อไปนี้ให้ครบ:

```text
Sensor frame
→ frozen baseline/config manifest
→ shadow decision ID
→ command ID + actor
→ ACK/timeout
→ physical confirmation
→ outcome window
```

ACK ของแอร์ปัจจุบันยืนยันเพียงว่าส่ง IR แล้ว ไม่ได้ยืนยันว่าเครื่องแอร์ทำงานจริง
จึงห้ามใช้เป็น label สถานะกายภาพโดยตรง

## 7. ลำดับการพัฒนา Adaptive Control

แผน Recommendation-first รายอุปกรณ์, Baseline maturity, API และ Safety gate
ฉบับถัดไปอยู่ที่
[ZEEP Adaptive Coach v1.0](adaptive-control-recommendation-plan-v1.md)

| Gate | การทำงาน | อนุญาตสั่งอุปกรณ์ |
|---|---|---|
| G0 · Observe | Live monitor, version, baseline delta, missingness | ไม่อนุญาต |
| G1 · Offline Replay | Replay ย้อนหลังและวัด false recommendation | ไม่อนุญาต |
| G2 · Recommendation | แสดงคำแนะนำให้ Admin/User ยืนยัน | ผู้ใช้กดเอง |
| G3 · Bounded Auto | ปรับเฉพาะ target ที่ผ่าน validation พร้อม rate limit/rollback | จำกัดตาม approval |

Target ที่เหมาะทดลองก่อนคือแสง,ระดับเสียง และอุณหภูมิทีละน้อย เพราะติดตามผลจาก
Lux/dBA/อุณหภูมิได้ Target ที่ยังห้าม Auto คือประตู,เตียง,Aroma/Steam และคำสั่ง
ที่ไม่มี physical feedback หรืออาจกระทบความปลอดภัย

ทุก Gate ต้องรักษากฎต่อไปนี้:

- Safety Supervisor และปุ่มหยุดมีสิทธิ์สูงสุด
- ค่า Offline/Stale/Invalid ไม่ถูกแทนเป็นศูนย์
- ค่า Offline/Stale/Invalid ถูกตัดออกจาก Live comparison และ rolling statistics
- Shadow Decision จากค่าค้างถูกแทนด้วยสถานะ Blocked/รอ Sensor
- Sleep State รอบเดียวไม่ทำให้เกิดคำสั่ง
- จำกัดความถี่และขนาดการเปลี่ยน พร้อม cooldown และ rollback
- แยก Manual, Admin, Safety, Shadow และ Adaptive actor ใน Audit
- Consent, retention และสิทธิ์ลบข้อมูลต้องผ่าน PDPA review ก่อนฝึก Model

## 8. Definition of Done ของ G0

- Admin เห็น Live vs Baseline และความครบของข้อมูลบน `/monitor`
- API ตอบ contract version และ `Cache-Control: private, no-store`
- User payload ไม่มี `adaptive_learning`
- ทุก recommendation มี `executable=false`
- ไม่มี Adaptive code import hardware/controller
- ทดสอบ missing/stale แล้วไม่แสดงเป็นศูนย์
- ตรวจ version ของ estimator/evidence/baseline/transition ได้ใน payload เดียว

เมื่อ G0 เก็บหลักฐานได้พอ ขั้นถัดไปคือสร้าง append-only Shadow observation
store แบบ pseudonymous โดยบันทึกหนึ่ง record ต่อ canonical sequence ไม่ใช่ทุก
WebSocket refresh และเพิ่ม command/outcome correlation ก่อนเริ่ม G1
