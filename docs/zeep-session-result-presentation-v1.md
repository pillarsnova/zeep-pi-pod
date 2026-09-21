# ZEEP Session Result Presentation v1

> **Purpose:** กำหนดรูปแบบหน้า “สรุปผลการพัก” ให้ผู้ใช้เห็นคำตอบสำคัญ
> เพียงชุดเดียว และให้ทีมพัฒนาเข้าถึงหลักฐาน QA ที่จำเป็นโดยไม่รบกวน
> ประสบการณ์ของผู้ใช้
>
> **Product position:** ZEEP Wellness & Longevity · ผลเป็นการประเมิน
> เชิงสุขภาพจาก Sensor ไม่ใช่การวินิจฉัยหรือผล AASM/PSG
>
> **Status:** Implemented presentation contract · ทบทวน 2026-09-19 หลัง `c75edcd`
> ไม่ใช่การรับรอง visual/keyboard QA ใหม่ทุกหน้า
>
> **Related specification:**
> [ZEEP Restore Summary v1](zeep-restore-summary-v1.md) ·
> [Usage Session API Schema Reference v1](zeep-api-schema-reference-v1.md)

## TL;DR

- Overnight Recovery แสดง **Sleep Score** เพียงคะแนนเดียว
- Nap & Refresh แสดง **Recovery Score** เพียงคะแนนเดียว
- Restore Summary เป็นคำอธิบายคะแนนหลัก ไม่ใช่คะแนนที่สาม
- ผู้ใช้เห็นผลแบบสั้น เป็นมิตร และเปิดรายละเอียดเพิ่มได้เมื่อสนใจ
- Admin เห็น Coverage, Confidence, บัญชีเวลา, Version และ Review flags
  ในแผง “ข้อมูลสำหรับพัฒนาระบบ” ที่พับเก็บได้
- การปรับ Presentation อ่านข้อมูลเดิมแบบ read-only จึงไม่ต้อง Rerun คะแนน
  และไม่แก้ Raw data

## 1. ปัญหาที่แก้

หน้ารายงานเดิมนำข้อมูลเดียวกันมาเล่าหลายรูปแบบพร้อมกัน ได้แก่ คะแนน,
สถานะ, ระยะเวลา, Sleep State, HR/RR, สภาพแวดล้อม, Coverage และข้อความ
Wellness boundary ทำให้ผู้ใช้ต้องอ่านซ้ำและอาจเข้าใจว่ามีหลายผลลัพธ์

รุ่นนี้กำหนดแหล่งแสดงผลหลักเพียงหนึ่งจุดต่อข้อเท็จจริง:

| ข้อมูล | จุดแสดงหลักสำหรับผู้ใช้ | รายละเอียดสำหรับ Admin |
|---|---|---|
| คะแนนและสถานะ | Result Summary | Score release และ Formula version |
| จุดเด่น/จุดที่ลองปรับ | Result Summary | Component points และ Review flags |
| ระยะเวลาและตัวชี้วัดตามโหมด | ดูรายละเอียดการพัก | Classification accounting |
| Sleep State | Overnight detail เท่านั้น | Timeline และ Evidence quality |
| HR/RR | สรุปเชิงสุขภาพแบบสั้น | Coverage และค่าประกอบ |
| สภาพแวดล้อม | ปัจจัยสำคัญแบบสั้น | Metric, band และ coverage |
| Disclaimer | ท้าย Result Summary หนึ่งครั้ง | Claim boundary ใน API |

## 2. ลำดับข้อมูลบนหน้าผู้ใช้

1. รูปแบบการพัก วันที่ และระยะเวลาที่บันทึก
2. Sleep Score หรือ Recovery Score พร้อมสถานะและความหมาย
3. สิ่งที่ทำได้ดีไม่เกินสองข้อ
4. สิ่งที่ลองปรับได้ไม่เกินสองข้อ
5. คำแนะนำสำหรับคุณหนึ่งข้อ พร้อมช่วงเวลาที่นำไปใช้และเหตุผลแบบเปิดเพิ่ม
6. Personal Baseline และความชัดเจนของข้อมูลในภาษาที่เข้าใจง่าย
7. รายละเอียดการพักและ Timeline แบบพับเก็บ
8. ข้อความกำกับ Wellness หนึ่งบรรทัด

### 2.1 Shared visual summary — 19 กันยายน 2026

หน้า `/sessions` และผลหลังจบ Session ใช้ presenter เดียวกัน:
[`11-result-summary.js`](../static/partials/app/scripts/11-result-summary.js)
กับ [`result-summary.css`](../static/styles/result-summary.css)
โดยคงธีม Javis และไม่เพิ่ม frontend framework

- แสดงวงแหวนคะแนนเดียว พร้อมสัญลักษณ์ระดับผลการพักและข้อความสั้น
  สัญลักษณ์เป็นภาษาภาพของผลประเมิน ไม่ใช่การตรวจอารมณ์จริงของผู้ใช้
- Nap ใช้สี mint และไอคอนแสงอาทิตย์; Overnight ใช้สีม่วงอ่อนและพระจันทร์
  ชื่อโหมดและชื่อคะแนนต้องอยู่ด้วยเสมอ ไม่ใช้สีเพียงอย่างเดียว
- แถบคะแนนย่อยอ่าน `component_points` / `component_max_points` จาก Server
  ไม่คำนวณคะแนนใหม่และไม่กำหนดน้ำหนักสูตรซ้ำใน frontend แสดงเฉพาะส่วนที่
  ใช้ได้กับโหมดนั้น และไม่แสดงค่าทดแทนใน `imputed_component_points` เป็นกราฟ
- ความยาวแถบเทียบคะแนนเต็มของแต่ละด้าน ไม่ใช่เปอร์เซ็นต์การฟื้นตัวของร่างกาย
- Safety review อยู่เหนือผลหลัก; ข้อมูลไม่ครบไม่ใช้หน้ายิ้มสื่อความมั่นใจสูง
- ความรู้สึกก่อน–หลังแสดงเฉพาะ `subjective_outcome.status=measured`
  และค่าที่ใช้ได้จริง ค่า 0 มีความหมาย ส่วน null/ข้อความว่าง/ค่าผิดชนิดไม่ใช่ 0
- จอใหญ่แบ่งผลหลักและกราฟเป็นสองส่วน มือถือเรียงลงล่าง; การ์ดปัจจัยและ
  คำแนะนำใช้พื้นที่เต็มเมื่อไม่มีการ์ดคู่ ไม่มี animation ตกแต่งสัญญาณ

Shared visual summary เริ่มที่ `9516413`; ต่อมา `94bb0e0`/`b2ce19b` เพิ่ม
คำแนะนำหลังพักและ optional API fields โดยไม่เปลี่ยนสูตรหรือ Sleep State
ภาพ PNG/QR export ยังใช้ Canvas เดิม
ทีม App ใช้ presentation API เดิมได้ แต่กราฟคะแนนย่อยใน Pi UI รอบนี้อ่านจาก
quality payload เดิม ไม่ได้เพิ่ม numeric component contract ใน presentation API

### 2.2 คำแนะนำหลังพัก — ใช้แล้วในรุ่น v1.2

การ์ด **คำแนะนำสำหรับคุณ** แสดง `title`, `primary`, `when_label` และปุ่มเปิด
**เหตุผลที่แนะนำ** จาก `restore_summary.recommendation` ไม่ทวนข้อเดียวกันใน
การ์ด drivers ไม่สุ่มคำแนะนำให้ดูต่างคน และไม่อนุมานความสดชื่นจาก HR/RR

หัวข้อ/เหตุผลเป็น optional สำหรับข้อมูลเก่า: ถ้าไม่มีให้แสดง `primary` ได้ตามเดิม
ส่วน `/presentation.recommendation` ยังคงเป็น string ไม่ใช่ object
รายละเอียดการตัดสินใจและตัวอย่างครบอยู่ใน [คำแนะนำหลังพัก](zeep-post-rest-advice.md)
ฟิลด์/ชนิดข้อมูลอยู่ใน [API Schema §8.5](zeep-api-schema-reference-v1.md#85-recommendation-confidence-และ-subjective-outcome)

Session สั้นจนไม่มีคะแนนยังมีคำแนะนำที่เหมาะกับข้อมูลจำกัด; ไม่สร้างคะแนนหรือ
คำตอบแบบสอบถามย้อนหลัง การวัดรอบนั้นไม่ยืนยันสภาพร่างกายในวันนี้

Session ที่จบแล้วแต่คะแนนไม่ผ่านเงื่อนไขเผยแพร่ต้องใช้ข้อความ
“ครั้งนี้ยังไม่มีคะแนน” พร้อมเหตุผลที่ทำให้ผู้ใช้เข้าใจได้ ห้ามใช้
“กำลังเตรียมผล” เพราะสื่อผิดว่าระบบยังประมวลผลอยู่

## 3. การแสดงผลตามโหมด

### 3.1 Overnight Recovery

- คะแนนหลัก: Sleep Score 0–100
- รายละเอียด: เวลานอนโดยประมาณ, ความต่อเนื่อง, การเข้าสู่ช่วงตื่น,
  HR/RR และสภาพแวดล้อม
- แสดง W, N1, N2, N3 และ REM เป็นค่าประเมิน Wellness
- Sleep State และสัดส่วนแสดงเพียงชุดเดียวในรายละเอียด

### 3.2 Nap & Refresh

- คะแนนหลัก: Recovery Score 0–100
- รายละเอียด: เวลาที่บันทึก, เวลาพักตามเป้าหมาย, การตอบสนอง HR/RR,
  ความนิ่งของร่างกาย และสภาพแวดล้อม
- ผู้ใช้เห็นสามกลุ่มที่เหมาะกับการพักระยะสั้น:
  `พักขณะตื่น`, `เคลิ้ม` และ `ช่วงหลับที่ประเมินได้`
- ไม่บังคับว่าผู้ใช้ต้องหลับ และไม่ใช้ N2/N3/REM เป็นเป้าหมายของ Nap
- Admin ยังตรวจ State ย่อยได้เมื่อจำเป็นต่อ QA

## 4. หน้า Admin สำหรับพัฒนาระบบ

แผงพับเก็บสำหรับผู้ดูแลตอบคำถามต่อไปนี้โดยไม่เปิดเผย Raw payload:

- Sensor บันทึกครบเพียงใด: Recording, BCG, Sleep State และ Environment
- ผลแต่ละช่วงมี Confidence ระดับใด
- เวลาทั้ง Session ถูกจัดบัญชีครบหรือไม่
- คะแนนถูกเผยแพร่หรือถูกระงับด้วยเหตุผลใด
- คะแนนย่อยแต่ละองค์ประกอบได้เท่าใด
- ใช้ Personal Baseline กี่ Session และพร้อมเปรียบเทียบหรือยัง
- Report, Formula, Policy และ Estimator เป็น Version ใด
- มี Review flag หรือ Safety review ใดที่ทีมต้องตรวจต่อ

ข้อมูลนี้ใช้สำหรับตรวจ Sensor, ตรวจ Regression, วิเคราะห์ความสัมพันธ์ใกล้เวลา
และวางแผนพัฒนาระบบ ห้ามนำ Review flag หรือ Coverage เพียงค่าเดียวไปสรุป
สุขภาพของผู้ใช้

## 5. API สำหรับ App และทีมพัฒนา

| Method/Path | Audience | วัตถุประสงค์ |
|---|---|---|
| `GET /api/v1/usage-sessions/{id}/presentation` | User/Admin | ผลแบบลำดับเดียวสำหรับแสดงใน App |
| `GET /api/v1/usage-sessions/{id}/development` | Admin only | QA aggregate และข้อมูลสำหรับพัฒนา |
| `GET /api/v1/usage-sessions/{id}` | User/Admin | Detail contract เดิมเพื่อ compatibility |

ข้อกำหนด:

- User อ่านได้เฉพาะ Session ของตนเอง
- Development endpoint ต้องเป็น Admin-only
- ทั้งสอง endpoint เป็น read-time adapter ไม่คำนวณคะแนนใหม่
- Presentation ต้องคัดลอกคะแนนที่ Server อนุมัติแล้วเท่านั้น
- วันที่ ระยะเวลาที่บันทึก และเป้าหมายเวลาอ่านจาก `timing` เท่านั้น ไม่ทำซ้ำใน
  `overview_metrics`
- Presentation ส่ง `rest_profile` สามกลุ่มสำหรับ Nap โดยตรง ส่วน
  `sleep_stages` เป็น `null`; Overnight ทำกลับกัน
- Driver เป็นคำอธิบายเท่านั้น ส่วนคำแนะนำที่ผู้ใช้ควรทำมีหนึ่งตำแหน่งใน
  `recommendation`
- Development endpoint ไม่ส่ง Raw BCG, Raw packet หรือ Timeline samples
- Response ใช้ typed schema และปรากฏใน `/openapi.json`

## 6. Rerun policy และผลรอบล่าสุด

ไม่ Rerun เพียงเพราะเปลี่ยนถ้อยคำ การจัดวาง หรือเพิ่ม Presentation API
เนื่องจากการทำเช่นนั้นไม่ควรเปลี่ยน Sleep State หรือคะแนนที่อนุมัติแล้ว

Rerun เฉพาะเมื่อ:

1. Session ยังไม่มีรายงาน Derived รุ่นที่ Product Owner อนุมัติ
2. Formula/Estimator เปลี่ยนและมี Replay plan, Audit trail และ Backup
3. พบ invariant ผิดจริงและมีขอบเขต Session ที่ตรวจสอบแล้ว

ทุกกรณีต้องไม่แก้ Raw file และต้องเก็บผลเดิมไว้ย้อนกลับได้

เจ้าของอนุมัติรอบ 19 ก.ย. ให้สร้างคะแนน/คำแนะนำย้อนหลังตั้งแต่ 1 ก.ย.
จึง Rescore 43 Session แล้ว โดยไม่ Reclassify State และไม่แตะข้อมูลก่อนขอบเขต
ดู [ผลก่อน–หลังและการตรวจ](reviews/2026-09-19-after-rest-rerun.md)
จำนวนดังกล่าวไม่ใช่ตัวเลขสดหรือคำสั่งให้ Rerun ทุกครั้งที่แก้เอกสาร

## 7. Acceptance criteria

- ผู้ใช้เห็นคะแนนหลักไม่เกินหนึ่งจุดต่อ Session
- ไม่มีคำว่า “กำลังเตรียมผล” ใน Session ที่จบและถูกระงับคะแนนแล้ว
- Nap ไม่แสดง Sleep Stage ห้าสถานะซ้ำในหน้าหลัก
- Coverage, Confidence %, Tier, Formula และ Raw terminology ไม่อยู่บน
  หน้าหลักของผู้ใช้
- Admin ยังตรวจค่าทั้งหมดข้างต้นได้จากแผงเดียว
- Classification accounting แสดงว่าเรียบร้อยได้เฉพาะเมื่อ
  `arithmetic_invariant.holds === true`
- หน้าจอขนาด Tablet และ Mobile ไม่มีข้อความหรือการ์ดล้นกรอบ
- Legacy endpoints และข้อมูลคะแนนเดิมยังทำงานย้อนหลังได้

## 8. Verification

- `python ui_composer.py check`: bundle ต้องตรงกับ source partials
- `python quality_gate.py ui`: build, product-language และ UI contracts
- `node --test tests/frontend/*.test.cjs`: synthetic behavioral tests รวม
  invalid/zero score, mode, subjective feedback, Safety, XSS และ null principal
- `python tests/frontend/preview_results.py`: localhost preview ด้วยข้อมูลจำลอง
  สำหรับ visual QA เท่านั้น ห้ามใช้ภาพตัวอย่างเป็นหลักฐานผลของผู้ทดสอบจริง
- หลัง deploy ตรวจ `/sessions` และการส่งข้อมูลตามปกติ โดยไม่สร้าง Session
  หรือสั่งอุปกรณ์จริงเพื่อทดสอบหน้าตา
