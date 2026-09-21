# ZEEP Adaptive Journey v1

สถานะ: **Implementation candidate · ยังไม่ Deploy**

22 กันยายน 2026 · ฐานโค้ด `78e90fc` · ทั้ง Overnight และ Nap & Refresh

## สรุป

เพิ่ม Timeline รวม → เปรียบเทียบก่อน–หลัง → ข้อมูลอ้างอิงความสบาย → คำแนะนำหนึ่งข้อ
ไม่แก้สูตร Sleep Score/Recovery Score, Sleep State, Raw หรือ Firmware

**การรับคำแนะนำไม่ได้ส่งคำสั่งอุปกรณ์** ผู้ใช้รับคำแนะนำแล้วไปปรับผ่าน Control เดิม
รุ่นนี้ใช้กฎที่อธิบายได้บน Pi ไม่มี LLM ภายนอก ไม่มีการฝึกออนไลน์ ไม่ใช่ Auto Control

## 1. Timeline รวม

- อ่าน `timeline` และ `events` เดิม ไม่บันทึก Raw ซ้ำหรือแก้ย้อนหลัง
- ครอบคลุมอุณหภูมิ ความชื้น CO₂ PM2.5 VOC lux dBA HR RR และสถานะเตียง
- PMS7003 มี PM1/PM10 ใน Live แต่ประวัติเดิมเก็บเฉพาะ PM2.5 ไม่สร้างค่าที่ไม่มี
- รวม versioned DSP labels จาก Firmware ไม่สร้างกรน/พูดจาก dBA
- จับการเปลี่ยนระหว่าง samples ห่างไม่เกิน 30 วินาที; ห่างกว่านั้นแสดง gap
- sensitivity ใน `adaptive/journey.py` เป็น engineering event threshold ไม่ใช่เกณฑ์สุขภาพ
- คำสั่งเดิมมีแอร์ เตียง Output Pulse ประตู Music ตามที่ caller บันทึกจริง
- legacy command timestamp มักเป็นเวลาหลังสำเร็จ ไม่ใช่เวลานิ้วกด; actor ไม่ครบ
  จึงส่ง `actor=unknown`, `physical_confirmation=false`
- Audio volume/pause/stop เดิมบางเส้นทางไม่มี event จึงยังไม่ครอบคลุมทุกการกด
- อ่านล่าสุดสูงสุด 20,000 samples พร้อม `data_truncated`; กราฟสูงสุด 720 points,
  API events ล่าสุด 400 รายการ, UI 100 รายการพร้อมบอกขอบเขต

## 2. ก่อน–หลังคำสั่ง

หน้าต่าง: ก่อน 300 วินาที → เว้น 60 วินาที → หลัง 300 วินาที
เป็นการสังเกตเบื้องต้น ไม่ใช่เวลาตอบสนองที่รับรองของทุกอุปกรณ์ โดยเฉพาะแอร์
ต้องเพิ่มการติดตาม 10–15 นาทีเมื่อทดสอบจริงแล้ว

- metric ต้องมี unique 10-second bins ≥80% ทั้งสองหน้าต่างจึงแสดง delta
- เสียงใช้ energy average ของ valid dBA; ค่าอื่นใช้ median ไม่ใช่ certified LAeq
- `waiting`: เวลาหลังยังไม่ครบ; `confounded`: มีคำสั่งอื่นทับใน window
- แสดงค่าที่เปลี่ยน ไม่สรุปว่าลดลงคือดีขึ้น โดยเฉพาะอุณหภูมิ HR/RR
- หากมีความเห็นก่อนหน้ารองรับ แสดงว่าค่าเข้าใกล้/ห่างจากช่วงที่เคยสบาย
  โดยยังไม่ยืนยันว่าความสบายหรือสุขภาพดีขึ้นจริง และไม่แยกผลคำสั่งที่ซ้อนกัน
- ไม่คำนวณเปอร์เซ็นต์กำจัด VOC จาก Index; ไม่ยืนยันสาเหตุหรือ physical actuation

## 3. ความสบายเฉพาะบุคคล

ถาม **“ช่วง 5 นาทีท้ายที่บันทึก รู้สึกสบายเพียงใด?”**
สบายพอดี / เย็นเกินไป / อุ่นเกินไป / ยังไม่สบาย

ตอบหรือข้ามได้ ปุ่มระบุวัตถุประสงค์แนะนำครั้งถัดไป API ต้องส่ง consent
`use_for_personalization=true` ไม่ตอบไม่ได้แปลว่าสบาย

- `adaptive_comfort` เก็บ response, ขอบเขตเวลา, ค่ากลางและ coverage แยกจากคะแนน
- Admin เป็น `staff_observation` ไม่นำไปสอนความชอบแทนเจ้าของ
- ใช้ latest self-report ต่อ Session ที่จบก่อนครั้งปัจจุบันเริ่ม
- แยก Overnight / Nap ตาม target จริง; ไม่ fallback `auto` เป็น Nap
- ใช้ “สบายพอดี” และ coverage ≥80% ราย metric; ไม่ใช้ score เป็นความชอบ
- 1–2 ครั้งเป็น learning; ≥3 ครั้งเป็น personal reference
- low/high คือช่วงค่ากลางที่เคยพบ ไม่ใช่ขอบเขตทางการแพทย์
- ไม่เรียนรู้จาก Session ปัจจุบันใส่ตัวเอง; events อยู่ใต้ FK/การลบบัญชีเดิม

## 4. ข้อเสนอครั้งละหนึ่งอย่าง

เริ่มจากอุณหภูมิ เสียง แสงที่มี self-report รองรับ:

1. ตรวจ active recording, owner, freshness, device live, Safety ready/not latched
2. 5 นาที coverage ≥80% ของ domain ที่เกี่ยวข้อง
3. เทียบ same-mode comfort reference พร้อมบอกความพร้อมของ reference
4. พัก 10 นาทีหลัง command และ 30 นาทีหลังตอบข้อเสนอ
5. `accept` บันทึกแล้วเปิด Control ให้ผู้ใช้กดเอง; reject/snooze ไม่สั่งอุปกรณ์
6. ID ผูก Session/basis/time bucket หมดอายุภายใน 120 วินาที; Server คำนวณใหม่
   เมื่อรับ decision หากไม่ตรงให้ 409 และไม่มี Hardware command

ไม่มี one-click execution/Control Gateway ใหม่ ไม่มีการปรับจาก Sleep State
และไม่อ้างว่าคำแนะนำได้เพิ่มคุณภาพการพักแล้วจนมีผลทดสอบจริง

## API / Data contract

ใช้ Browser Auth เดิม; User เฉพาะตนเอง, Admin ทุก Session; ไม่รับ broad API token
POST ใช้ CSRF เดิม; response ข้อมูลสำเร็จเป็น `private, no-store`

| Method | Path | ผล |
| --- | --- | --- |
| GET | `/api/v1/adaptive/sessions/{session_id}` | journey, outcomes, comfort_reference, recommendation |
| POST | path ข้างต้น + `/comfort` | optional self-report + observed window |
| POST | path ข้างต้น + `/decisions` | intent เท่านั้น `command_executed=false` |

```json
{"response":"comfortable","use_for_personalization":true,"request_id":"81d72fda-5e86-4fab-8b18-ec6e742ac734"}
```

```json
{"recommendation_id":"ID จาก GET ล่าสุด","decision":"accept","request_id":"8cd0ff2c-0b70-4d38-a0a2-0f492aa14457"}
```

Types: ID/label/unit/status string; epoch number UTC; measurement/delta number|null;
coverage number 0–1; flags boolean; channels/events/metrics array; ranges object keyed
by metric; recommendation.item object|null. Request ID เป็น UUID ใช้เดิมเมื่อ retry
response envelope `zeep.api.response` เดิม; request models แสดงใน OpenAPI

## โครงสร้าง

| ไฟล์ | หน้าที่ |
| --- | --- |
| `adaptive/journey.py` | normalize, events, projection |
| `adaptive/outcomes.py` | window, coverage, overlap |
| `adaptive/comfort.py` | feedback, reference แยก mode |
| `adaptive/coach.py` | one advisory, pure/no hardware |
| `adaptive/journey_repository.py` | bounded reads, existing event writer |
| `adaptive/journey_service.py` | ownership, orchestration, decision/idempotency |
| `api/adaptive_journey.py` | strict inputs, RBAC/HTTP |
| `static/partials/app/adaptive-journey.html` | section แยกสำหรับ Monitor/Sessions |
| `static/partials/app/scripts/08-adaptive-journey.js` | render และ explicit choices |

## Verification / Rollout

ผลตรวจบน Mac 22 กันยายน 2026 (ข้อมูลจำลอง): Python regression 1,328 ผ่าน,
Frontend 60 ผ่าน; Ruff และ generated UI check ผ่าน; Chrome Desktop 1440 px
และ Mobile 390 px ไม่พบ JavaScript error หรือหน้าเกินความกว้างจอ
เป็นการตรวจ component จำลอง ยังไม่ใช่ full-page smoke บน Pi

ทดสอบ synthetic data: immutable raw, ordering, missing/invalid, coverage, sound
averaging, overlap, mode separation, feedback provenance, ownership/CSRF, expiry,
no actuation และ regression เดิม ไม่ใช้ข้อมูลจริงเป็น test fixture
ก่อน deploy ต้องตรวจตู้ว่าง/ไม่มี recording และทำ service/API/UI smoke หลัง restart
Rollback release ก่อนหน้าได้ ไม่มี schema migration หรือ Firmware เปลี่ยน

ข้อจำกัด: ยังต้องทดสอบ event sensitivity, settling time รายอุปกรณ์, false advice,
latency บน Pi และ feedback จริง ไม่อ้างความสำเร็จทางสุขภาพจาก software tests

ต่อเนื่อง: [Sensor Expansion BOM](zeep-sensor-expansion-bom-v1.md)
