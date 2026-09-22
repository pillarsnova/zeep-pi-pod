# ZEEP — สถานะระบบและรุ่นที่ตรวจล่าสุด

สถานะ: **Source release register · Internal Pilot**
ทบทวน: 22 กันยายน 2026 · ผู้รับผิดชอบ: Pi Backend / Product / Operations

## TL;DR

ระบบมีสองโหมด: **Overnight Recovery → Sleep Score** และ
**Nap & Refresh → Recovery Score** พร้อมคำแนะนำหลังพักหนึ่งข้อจากข้อมูลของ
Session นั้น ไม่ใช่คะแนนที่สามหรือการประเมินความพร้อมทั้งวัน

หน้านี้แยกสถานะ source ใน Git ออกจากหลักฐานการตรวจ Pod ที่บันทึกไว้
ไม่ได้ตรวจสถานะ Pod สดในรอบ 22 ก.ย. และไม่ได้ Restart, Deploy หรือ Flash
หน้านี้ไม่ใช่ telemetry สดหรือการอนุมัติ Final Code Freeze
ก่อน deploy ให้ตรวจ Git SHA, สถานะตู้ และ [Runbook](pi5-operations-runbook.md) อีกครั้ง

## รุ่นและหลักฐาน

| เรื่อง | รุ่น/หลักฐานที่ตรวจแล้ว | ขอบเขต |
|---|---|---|
| Pi application — หลักฐานการตรวจเดิม | `b2ce19b` บน Pod 1; Restart 19 ก.ย. 2026 06:41:14 +07 | บริการ active และ Safety ready ณ เวลาตรวจเดิม ไม่ใช้ยืนยัน SHA หรือสถานะ Pod ปัจจุบัน |
| เอกสารผล Rerun | `c75edcd` | เป็น documentation commit ไม่ต้อง restart เพื่อใช้เอกสาร |
| Adaptive Journey ใน Git | `eaccf32` | Timeline, ก่อน–หลังคำสั่ง, Comfort Profile และคำแนะนำพร้อม API; CI ผ่านสำหรับ SHA นี้ ยังไม่ Deploy ในรอบนี้ |
| Onboarding ใน Git | `fa7bd07` | สรุป Adaptive Journey และ BOM; เป็นฐานของรอบรวมงาน 22 ก.ย. |
| Smart Senses UI ใน Git | `1bc988e` | สรุปขอบเขต Monitor และชื่อรวม Adaptive Journey; ผ่าน local targeted tests/viewport QA ยังไม่ได้ Deploy ในรอบนี้ |
| Session report | `zeep-session-report-v10.12-minimum-only-score-release` | คะแนนและรายงาน Derived |
| Sleep Score | `zeep-sleep-score-v2.1-minimum-only-neutral-25-35-20-10-10` | เวลา 25, ต่อเนื่อง 35, โครงสร้าง 20, HR/RR 10, สิ่งแวดล้อม 10 |
| Recovery Score | `zeep-recovery-score-v3.1-minimum-only-neutral-25-35-30-10` | เวลา 25, HR/RR 35, ความนิ่ง/ต่อเนื่อง 30, สิ่งแวดล้อม 10 |
| คำแนะนำหลังพัก | `zeep-restore-recommendation-v1.2-after-rest` | API และ Pi result presenter ใช้นโยบายเดียวกัน |
| Product language ใน source | `zeep-product-language-v1.2` ใน `69bd298` และ `89d404f` | ปรับข้อความและแยกคำสั่งแอร์จากสถานะจริง; ขึ้น Git แล้ว ไม่ถือว่าติดตั้งบน Pod แล้ว |
| Sleep estimator | `bcg-audio-bed-5state-v1.29-complete-occupied-epochs` | รอบ Rerun ล่าสุดไม่เปลี่ยน Sleep State |
| Smart Senses | [ภาพรวมขอบเขต 22 ก.ย.](onboarding/smart-senses.md) | รวมข้อมูลหลายเซนเซอร์และ Adaptive Journey; Voice/thermal/radar/e-nose ยังเป็นแผน ไม่ได้ติดตั้งจากการปรับชื่อ |
| Smart Ear · โมดูลเสียง | Admin DSP shadow; มี telemetry features บน Pod 1 ใน audit `f570a68` | เป็น provisional label ไม่ใช่ผลจำแนกที่รับรองความแม่นยำ |

เวอร์ชันที่เปลี่ยนตาม release ยึด [`sleep_system_policy.py`](../sleep_system_policy.py),
Pydantic/OpenAPI และ effective configuration; ตารางนี้ต้องแก้เมื่อมี deployment ใหม่
ห้ามนำผล smoke หรือจำนวน tests ของ SHA เก่ามารับรอง SHA ใหม่

หลักฐาน CI ของ Adaptive Journey: [Python](https://github.com/pillarsnova/zeep-pi-pod/actions/runs/35656326011)
และ [Frontend](https://github.com/pillarsnova/zeep-pi-pod/actions/runs/35656325987)
ใช้รับรองเฉพาะ `eaccf32` ไม่แทนผลตรวจของรอบรวมงานใหม่

รายละเอียดข้อความและข้อคลาดเคลื่อนที่พบในรอบก่อนอยู่ใน
[Interface Content Review](reviews/2026-09-19-interface-content-review.md)
ไม่เปลี่ยนสูตรคะแนน ข้อมูลย้อนหลัง หรือคำสั่งควบคุมอุปกรณ์

รอบรวมงานใหม่อ่าน [รายงาน 22 กันยายน](reviews/2026-09-22-pending-work-integration.md)
ซึ่งแยกผลตรวจ source จากผลตรวจเครื่องจริง

รอบ Smart Senses อ่าน [ผลตรวจ UI และการเทียบเอกสารต้นทาง](reviews/2026-09-22-smart-senses-integration.md)
แยกความสามารถปัจจุบันออกจากแผนเซนเซอร์ใหม่และ Voice ไม่เปลี่ยนสูตรคะแนน

## สิ่งที่ใช้ได้กับผู้ใช้และทีมแอป

- `/sessions`: ผลหลักหนึ่งคะแนน, องค์ประกอบคะแนน, ปัจจัยสำคัญ และการ์ด
  **คำแนะนำสำหรับคุณ** พร้อมหัวข้อ ช่วงเวลา และเหตุผลที่เปิดอ่านเพิ่มได้
- `/summary` และ detail API: `restore_summary.recommendation` เป็น object
  ที่มี `primary`, `tip_id`, `title`, `when_label`, `reason`, `basis` และ flags
- `/presentation`: `recommendation` ยังเป็น string เพื่อคง compatibility;
  ไม่ใช่ schema เดียวกับ object ข้างต้น
- แบบสอบถามก่อน–หลังไม่ถูกสร้างย้อนหลัง หากไม่มีคำตอบจริงจะไม่สร้างค่าความสดชื่น
- รุ่นนี้ยังไม่เพิ่มคำถามกิจกรรมถัดไปหรือเปลี่ยน PNG/QR Canvas ให้เหมือน HTML presenter
  ทั้งหมด ส่วนคำถามความสบายและการยืนยันคำแนะนำมีแล้วใน source ของ
  [Adaptive Journey](zeep-adaptive-journey-v1.md) ไม่ใช่แบบสอบถามความพร้อมทั้งวัน

## Baseline แต่ละชนิดไม่ใช่เกณฑ์เดียวกัน

| สิ่งที่เทียบ | จุดเริ่มใช้ | ใช้ทำอะไร |
|---|---|---|
| Best rest window | มี Session ก่อนหน้าที่เข้าเกณฑ์อย่างน้อย 1 ครั้ง | แสดงช่วงพักอ้างอิงได้ตั้งแต่การกลับมาครั้งที่ 2 |
| HR/RR personal reference | ข้อมูลที่เข้าเกณฑ์ 3 ครั้ง | สรุปช่วงชีพจรและการหายใจประจำตัว |
| Restore score comparison | 7 Session ที่เข้าเกณฑ์; ตั้งแต่ 14 แสดงระดับเสถียรกว่า | เทียบคะแนนโหมด/เป้าหมาย/สูตรเดียวกัน |
| Sleep-state baseline/fit | gate และ version ตาม Sleep System | หลักฐานของ estimator ไม่ใช่แบบสอบถามหรือ score comparison |

ไม่ลดทุกเกณฑ์เหลือเลขเดียว และไม่ใช้ Session ปัจจุบันสร้างฐานเพื่อเทียบกับตัวเอง
รายละเอียดอยู่ใน [User Learning](zeep-user-learning-profile-v1.md),
[HR/RR Wellness](zeep-respiratory-wellness-v1.md) และ [Restore Summary](zeep-restore-summary-v1.md)

## ผล Rerun และ Sync ล่าสุด

รอบวันที่ 19 ก.ย. ประมวลผล 43 Session ช่วง 1–18 ก.ย.:
Sleep Score 15/15, Recovery Score 24/28; อีก 4 Session ต่ำกว่า 10 นาที
มีคำแนะนำครบ 43/43 ไม่แก้ Raw, Timeline, Sleep State หรือ 13 Session ก่อน 1 ก.ย.
นี่คือผล ณ รอบนั้น ไม่ใช่จำนวน Session สดตลอดเวลา

สำเนาหลัง Rerun ลง Mac และตรวจแล้ว ข้อยกเว้น FileVault ใช้เฉพาะ Mac เครื่องพัฒนา
ที่เจ้าของอนุมัติ ไม่ครอบคลุมเครื่องทีมอื่น ไม่ได้แปลว่าดิสก์ถูกเข้ารหัสแล้ว
อ่าน [รายงานก่อน–หลัง](reviews/2026-09-19-after-rest-rerun.md) และ
[Operations Runbook](pi5-operations-runbook.md) สำหรับวิธีปฏิบัติ

## Verification

เอกสารรอบนี้เทียบกับ source บน `develop` ที่ฐาน `fa7bd07` และงานรวมวันที่
22 ก.ย., models, routes, นโยบายเวอร์ชัน และรายงานการตรวจที่ระบุ SHA
ไม่สั่งอุปกรณ์ ไม่ restart และไม่
Rerun เพิ่ม ผล browser/keyboard/viewport ใหม่ยังต้องตรวจใน UI release ถัดไป
ใช้ `python -m unittest -q test_documentation_alignment.py` ตรวจลิงก์และ contract
เอกสาร; ผลนี้ไม่แทน hardware หรือ visual acceptance
