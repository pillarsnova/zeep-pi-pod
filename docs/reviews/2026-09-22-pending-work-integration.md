# ZEEP — รายงานรวมงานค้างและส่งขึ้น Git

วันที่: 22 กันยายน 2026

ขอบเขต: Source บน Mac → `origin/develop` โดยใช้บัญชี PillarsMan

## สรุป

นำงานค้างใน workspace เดิมมารวมกับ `origin/develop` ล่าสุดอย่างเป็นขั้นตอน
คงงาน Adaptive Journey, Onboarding, Smart Ear และหน้าสรุปผลที่เผยแพร่แล้ว
แยก commit ตามหน้าที่ โดยไม่เปลี่ยนสูตร Sleep Score, Recovery Score หรือ Sleep State

**ไม่มี Deploy, Restart, Flash, Rerun หรือการแก้ข้อมูลผู้ทดสอบในรอบนี้**
ผลตรวจด้านล่างเป็น software regression ไม่ใช่การตรวจตู้จริงหรือรับรองหน้าตาทุกขนาดจอ

## การรวมงาน

1. Workspace เดิมอยู่ที่ `c75edcd` มีงานค้าง 78 ไฟล์
2. เก็บสำเนางานไว้ใน Git stash ก่อนดึง code ล่าสุดแบบ fast-forward ถึง `fa7bd07`
3. รวมงานเดิมกลับมาและแก้ conflict 16 ไฟล์ โดยยึดข้อความ/พฤติกรรมที่เผยแพร่ล่าสุด
4. งานที่ซ้ำกับ release แล้วไม่สร้างการเปลี่ยนแปลงซ้ำ; คงเฉพาะ diff ที่ยังจำเป็น
5. ประกอบ `static/index.html` ใหม่จาก template และ partial ไม่แก้ generated file แยกเอง

สำเนาก่อนรวมงานเก็บไว้ในเครื่อง:
`4d86353e05dc0ff0541b5db8ff83a49933610b25`
เป็น stash สำหรับกู้คืน ไม่ใช่ release และไม่ได้ push สำเนานี้ขึ้น remote

## ชุด Commit

| ชุด | Commit | สิ่งที่เปลี่ยน |
| --- | --- | --- |
| Backend / Product copy | `69bd298` | ข้อความข้อมูลไม่พร้อม/ข้อมูลจำกัด และข้อผิดพลาดเริ่มการพัก; เพิ่ม regression ของคำแนะนำแบบมีเงื่อนไข |
| Interface / Control copy | `89d404f` | ภาษา Dashboard, Login, Monitor และ Control; ระบุสถานะแอร์เป็นคำสั่งล่าสุด ไม่ใช่ผลยืนยันจากเครื่อง; แยก unknown และ offline; ทดสอบเล่นซ้ำ/ตามคิว |
| เอกสาร / Onboarding | Commit ที่เพิ่มบันทึกนี้ | ทะเบียนสถานะ, API examples, แนวทางภาษา, Interface Roadmap, Sensor/Firmware provenance และแผนเซนเซอร์สำรอง |

งานก่อนหน้าที่รักษาไว้: `eaccf32` (Adaptive Journey) และ `fa7bd07` (Onboarding)
ตรวจ SHA ของ Pod อีกครั้งก่อน deploy; สถานะใน Git ไม่เท่ากับสถานะที่ติดตั้งจริง

## จุดที่แก้ระหว่างรวมงาน

- ตัวอย่าง JSON ใน API Schema สามกรณีใช้ข้อความเก่า จึงปรับให้ตรงกับ
  `build_post_rest_advice` สำหรับ `sleep`, `nap_recovery` และ `unknown`
- เพิ่มการตรวจเอกสารเทียบ Pydantic model, ฟิลด์คำแนะนำ, เวอร์ชัน runtime,
  ลิงก์ภายใน และความสอดคล้องของตาราง
- แยกผล audit เครื่องจริงวันที่ 19 ก.ย. ออกจากสถานะ source วันที่ 22 ก.ย.
- เชื่อมแผนเซนเซอร์สำรองกับ BOM ประตู/ลม/อุณหภูมิพื้นผิวล่าสุด
  ทั้งคู่ยังเป็นแผน ไม่ใช่หลักฐานติดตั้งหรือคำสั่งซื้อ
- คงข้อมูลความคิดเห็นเป็นคำตอบจริงของผู้ใช้ ไม่สร้างค่าความสดชื่นจาก Sensor
- ไม่เปลี่ยนเส้นทางสั่งอุปกรณ์ สิทธิ์ผู้ใช้ Safety Policy หรือเกณฑ์การให้คะแนน

## Verification

ผลตรวจรวมบน source ที่รวมแล้ว:

- `pi5/.venv/bin/python quality_gate.py full`: **1,338 tests ผ่าน**
- `node --test tests/frontend/*.test.cjs`: **63 tests ผ่าน**
- UI composer, Ruff check/format, Python compile, evidence registry และ
  `git diff --check`: ผ่าน
- หลังปรับเอกสาร API และทะเบียนสถานะ ตรวจซ้ำเฉพาะ documentation/advice:
  **25 tests ผ่าน**
- ไม่เรียกอุปกรณ์จริง ไม่อ่าน Raw ของผู้ทดสอบเพื่อทดสอบ และไม่แก้ฐานข้อมูลจริง

GitHub Actions ตรวจราย commit เพิ่มจากผล local:
[รายการ CI ของ develop](https://github.com/pillarsnova/zeep-pi-pod/actions?query=branch%3Adevelop)
ให้ตรวจชื่อ workflow และ SHA ให้ตรงกับ release ที่จะนำขึ้น Pod
ผล software test ไม่แทน browser/keyboard/viewport และ hardware smoke หลัง deploy

## เส้นทางส่งต่องาน

- [Onboarding](../onboarding/README.md) — เริ่มอ่านตามบทบาท
- [Current Status](../current-status.md) — รุ่น source และหลักฐาน Pod แยกกัน
- [API Schema](../zeep-api-schema-reference-v1.md) — ข้อมูลสำหรับทีมแอป
- [Product Language](../zeep-product-language-guideline-v1.md) — คำกลางของระบบ
- [Operations Runbook](../pi5-operations-runbook.md) — ขั้นตอน deploy เมื่อได้รับคำสั่ง
