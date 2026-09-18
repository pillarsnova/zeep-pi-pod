# Runtime audit — 19 September 2026

สถานะ: **Verified change record — Internal Pilot**

ขอบเขต: Pi5 runtime บน `origin/develop` ต่อจาก `b74905f`; ตรวจโดยสาม Agent
แยกด้าน Session lifecycle, Hardware control และ Adaptive/API quality gate
พร้อมผู้พัฒนาหลักตรวจรวมและตรวจเอกสาร ไม่ใช่การรับรองทางการแพทย์หรือ Hardware

## สรุป

การแยก module ทำให้เพิ่ม failure-injection ได้ตรงจุดและพบข้อผิดพลาดเดิมที่ชุด
happy-path ไม่ครอบคลุม รอบนี้แก้การคืน Session เมื่อสร้างรายงานล้ม, deadline ของ
เตียงเมื่อ ACK หาย, Safety ที่เปลี่ยนระหว่างคำสั่ง และลำดับคำแนะนำที่ Admin เห็น
โดยไม่เปลี่ยนสูตร Sleep State/Sleep Score/Recovery Score, Raw, schema หรือ Firmware

## ข้อค้นพบและการแก้ไข

| เรื่อง | อาการเดิม | การแก้และผลที่ตรวจได้ |
|---|---|---|
| จบ Session ก่อน commit | Read/project/report exception อาจทำให้ active owner หลุดและลองจบใหม่ไม่ได้ | คืน active object และ record/cadence เดิม; คืน BCG เฉพาะเมื่อเคยพยายามปิดและยังไม่ถูกกู้ |
| จบ Session หลัง commit | ลบ checkpoint ล้มอาจถูกตีความว่า commit ล้ม; Profile error ขวาง idle | แยก committed cleanup error; ไม่เปิดผลที่จบแล้วกลับมา; optional cleanup แยกจากกันและคืน idle |
| Audit sink ขัดข้อง | Logging exception อาจบังสาเหตุจริง | Fallback journal โดยไม่ใส่ token/profile หรือข้อความ error อ่อนไหว; รักษา exception เดิม |
| Bed ACK timeout | ส่ง movement ได้แล้วแต่ยังไม่มี auto-stop เพราะรอ ACK | `BedMotionService` ตั้ง deadline เมื่อ MQTT publish สำเร็จ ก่อนรอ ACK |
| Timer เก่ากับ movement ใหม่ | ตรวจ generation แล้วปล่อย lock ก่อน stop ทำให้แทรกคำสั่งได้ | ใช้ lock เดียวครอบ movement publish และ timed-stop publish |
| Safety ระหว่าง AC sequence | ตรวจครั้งเดียวก่อน on/temp/swing | ตรวจซ้ำหลัง IR delay ก่อน publish ทุก step; off/status ไม่ถูกบล็อก |
| Safety Profile ordering | ส่งหยุดเตียงก่อน latch เปิดช่องให้คำสั่งใหม่แทรก | ตั้ง latch ก่อน side effects และปล่อย state lock ก่อน hardware I/O |
| คำแนะนำสำคัญถูกซ่อน | Personal reference ดัน CO₂ critical พ้น 6 การ์ดแรก | เรียงตาม priority ก่อน client จำกัดจำนวน; ไม่เพิ่ม automatic actuation |
| RR provenance | Nap fallback จาก sleep history แต่แสดงว่า same-mode | ระบุ reference policy/source ตามจริง ไม่เปลี่ยนตัวเลขหรือสูตร |
| เลือกชุดทดสอบ | บาง module ใหม่ไม่เรียก sleep/AI tests และไม่เห็นไฟล์ที่ถูกลบ | เพิ่ม domain mapping และ matching test; รวม deletion; deleted test ใช้ full gate |

## วิธีตรวจ

1. แต่ละ Agent สร้างกรณีจำลองที่แสดงข้อผิดพลาดกับโค้ดเดิม ก่อนแก้
2. ทดสอบเฉพาะ domain หลังแก้ แล้วให้ Agent อีกคนอ่าน diff และตรวจ boundary
3. ผู้พัฒนาหลักรัน full release gate ครั้งเดียวหลังรวม เนื่องจากแก้หลายระบบและ
   test infrastructure; ไม่ใช้การวนชุดเดิมแทนกรณีล้มเหลวที่ขาด
4. Pi ทดสอบด้วย temporary/synthetic data แล้วตรวจ API/WebSocket/Sensor แบบอ่าน
   หลัง restart; ไม่มีการกดแอร์ ขยับเตียง หรือสร้าง Session ทดสอบในฐาน Production

ชุดหลัก: `test_session_finalization.py`, `test_session_finalization_commit.py`,
`test_control_failsafe.py`, `test_adaptive_learning.py`, `test_quality_gate.py`
และ `test_session_start.py` ซึ่งเตรียม characterization สำหรับ Login extraction

## Verification

- Local full gate: **1,279 tests ผ่าน ไม่มี skip**; UI composition, Ruff check/format,
  compile, Evidence registry 30 records และ `git diff --check` ผ่าน
- Control stress: 13 test cases × 25 รอบ = **325 executions ผ่าน** ไม่ใช่ 325 tests ใหม่
- Independent cross-review: control/finalization/commit **41 tests ผ่าน**
- เพิ่ม characterization ก่อน Login extraction 8 cases; ไม่ใช้บัญชีจริงหรือฐานจริง
- รอบแรก deploy `42e0324` (รวม `156d37a`, `c861d00`, `6a0a720`) ผ่าน
  `origin/develop` ด้วย PillarsMan; Pi focused **194 tests ผ่าน**
- Restart รอบแรก 19 September 2026 **03:30:25 +07**; service active/running,
  Pod ว่าง, Safety ready และไม่ latched
- API state, Fleet Health, Adaptive Live ตอบ 200; WebSocket ได้ frame;
  Hub 1/Hub 2/BCG connected และข้อมูลสด, Control links connected,
  sensor-frame cadence 10 วินาทีไม่ stale; ไม่พบ ERROR/Traceback/CancelledError
- ยืนยัน Adaptive `automatic_actuation=false`; ไม่ทดสอบสั่งอุปกรณ์จริง

## ขั้นต่อเนื่อง — Login/start Session

เมื่อรอบแรกผ่านบน Pi จึงเริ่มแยก `_start_pod_session` ตาม roadmap โดยใช้
characterization ก่อนย้าย 8 cases และเพิ่มเป็น 13 permanent cases หลังย้าย.

- แยก `sessions/start.py` (283 บรรทัด), `start_contracts.py` (107) และ
  `start_profile.py` (134); `app.py` เหลือ **5,932 บรรทัด** จากต้นรอบ 6,206
- Public facade 28 บรรทัด; per-call composition 47 บรรทัด; module ไม่ import app
  หรือ FastAPI และไม่เปลี่ยน signature/HTTP response, lock, lease หรือ checkpoint
- Exact trace harness **24/24 สถานการณ์ตรงกับ `42e0324`** ทั้งผล, error,
  active record, Profile และ side-effect order; UTC/UUID กำหนดแน่นอนใน test เท่านั้น
- Independent review: **133 API/Auth/Start/Profile tests ผ่าน**
- Full gate หลังรวมขั้นนี้: **1,286 tests ผ่าน ไม่มี skip**, UI/Ruff/compile/
  Evidence registry/diff-check ผ่าน; Full gate รอบนี้รันใหม่เพราะมี code revision
  ใหม่และแก้ test infrastructure ไม่ใช่การรันชุดเดิมซ้ำเพื่อเพิ่มตัวเลข
- ปรับ focused style scope ให้ตรง Full/CI: ตรวจ extracted packages ด้วย Ruff;
  root legacy ยัง compile + regression + architecture ratchet ตามเดิม ไม่แก้
  legacy style หลายร้อยจุดปะปนใน Login extraction
- ตรวจ Git SHA ที่ติดตั้งและเวลา restart จริงด้วย Operations runbook; ผล smoke
  ระดับเครื่องจริงแยกจาก local test และไม่ถือว่าเป็น physical actuator validation

## ขอบเขตที่ยังไม่ยืนยันและขั้นต่อไป

- ACK ของแอร์/เตียงยังเป็น bridge acknowledgement ไม่ใช่ feedback กายภาพ
- Auto-stop เป็น best-effort เมื่อ MQTT ขาด ไม่สามารถรับประกันเตียงหยุดจริงได้;
  ต้องคง independent Hardware fail-safe และทดสอบเครื่องจริงกับทีม
- หาก BCG recovery หรือ outbox disk persistence ล้ม ระบบมี audit แต่ไม่อ้างว่า
  อุปกรณ์กลับมาหรือรายงานถูกส่งถึงปลายทางแล้ว
- Async writer timeout ยังอาจมี transaction commit ตามมาภายหลัง; เป็นความเสี่ยง
  เดิมที่ต้องแยกพัฒนา durable receipt/reconciliation ไม่ถือว่าปิดด้วย refactor นี้
- Adaptive ยังคง `automatic_actuation=false`; จัดลำดับคำแนะนำให้ถูกต้อง ไม่ได้สร้าง
  AI ที่ควบคุมอุปกรณ์เองหรือพิสูจน์ความแม่นยำของโมเดลสุขภาพ
- Login/start-session extraction ต้องรักษา owner, durable checkpoint, lease และ
  account binding; ใช้ characterization เดิมเป็น gate ก่อนย้าย boundary
- Aircon sequence policy และ typed estimator context เป็นลำดับถัดไปตาม
  [Architecture roadmap](../pi5-software-architecture.md#63-ลำดับถัดไป)

## เอกสารอ้างอิงในระบบ

- [Software architecture](../pi5-software-architecture.md)
- [Session lifecycle](../onboarding/product-and-lifecycle.md)
- [Hardware and Hub map](../onboarding/hardware-hub-map.md)
- [Test selection and release gates](../../TESTING.md)
- [Operations runbook](../pi5-operations-runbook.md)
