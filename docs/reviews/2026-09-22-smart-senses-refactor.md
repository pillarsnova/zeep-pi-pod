# Smart Senses — Refactor ตามหน้าที่

วันที่: 22 กันยายน 2026 · ฐานก่อนแก้: `7a85711` บน `develop`
สถานะ: **Source refactor — ไม่ Deploy/Restart/Flash หรือแก้ข้อมูล Session**

## TL;DR

แยกการประกอบผลออกจากการคำนวณ การตรวจคุณภาพ และการนำเสนอ โดยคงชื่อ API,
signature, schema และผลลัพธ์เดิม ไม่เปลี่ยนสูตรคะแนน เกณฑ์เสียง Baseline
หรือสิทธิ์ควบคุมอุปกรณ์ ใช้ PillarsMan บน Mac สำหรับ Commit/Push

## สิ่งที่แยก

| ตัวรวมผล | ก่อน | หลัง | งานที่ย้ายออก |
| --- | ---: | ---: | --- |
| `acoustics/timeline_projection.py` | 424 บรรทัด | 123 บรรทัด | `timeline_series.py`: สถิติ/กราฟ; `timeline_view.py`: เหตุการณ์/metadata/ข้อความ |
| `adaptive/learning.py` | 396 บรรทัด | 103 บรรทัด | `learning_quality.py`, `learning_context.py`, `learning_recommendations.py` |

โมดูลย่อยใหม่มี 93–199 บรรทัดต่อไฟล์ จำนวนนี้บอกขอบเขตหน้าที่ ไม่ใช่หลักฐาน
ว่า runtime เร็วขึ้นหรือโค้ดรวมสั้นลง เป้าหมายคือหาเจ้าของ logic และทดสอบแยกได้
ดู [แผนที่โมดูลใน Onboarding](../onboarding/smart-senses.md)

## ขอบเขตที่คงเดิม

- Public entry points ใน `acoustics` และ `adaptive.learning` ยังใช้ได้
- Timeline schema `1.1`, detector version และ Adaptive Learning `v1` ไม่เปลี่ยน
- ช่องข้อมูลขาดยังเป็นช่องว่าง; การเฉลี่ยเสียงใช้ energy average เดิม
- จำนวนเหตุการณ์รวมแยกจากการ์ดที่จำกัด 24 รายการ ไม่ลบหลักฐานเพราะแสดงไม่หมด
- คุณภาพข้อมูลแต่ละเซนเซอร์แยกกัน ข้อมูลชีพจรไม่ครบไม่ซ่อนข้อมูลสิ่งแวดล้อม
- คำแนะนำคงลำดับความสำคัญและต้องรอผู้ใช้/Admin ไม่มี executable command
- ไม่เพิ่มฐานข้อมูล dependency ภายนอก หรือ package ครอบชื่อ Smart Senses ซ้ำ
- ไม่มีการแก้ UI, route, Auth/RBAC, Firmware, Sleep State หรือคะแนนย้อนหลัง

## Verification

- ก่อนย้ายโมดูล: Acoustics, Adaptive Learning/Journey และ Architecture ผ่าน 61 tests
- หลังย้าย: `quality_gate.py acoustics adaptive` ผ่าน 84 tests
- `quality_gate.py changed` เลือก Full gate เพราะแก้ test infrastructure:
  ผ่าน **1,373 tests** ไม่มี failure/error/skip พร้อม UI composer, Ruff,
  compilation, source registry 35 รายการ และ `git diff --check`
- เทียบผลกับโค้ดฐานด้วยข้อมูลจำลอง: Timeline 600 ชุด และ Adaptive Learning
  600 ชุด **payload ตรงกันทุก field ทั้ง 1,200 ชุด** และไม่แก้ input
- ตัวอย่างครอบคลุมไม่มี Session, ยังไม่เริ่มบันทึก, sensor ขาด/ค้าง, dBA ผิดช่วง,
  cadence ผสม, เวลาซ้ำ, การย่อกราฟ, DSP labels และคำแนะนำหลายระดับ
- เพิ่ม `test_smart_senses_modules.py` สำหรับจุดเข้าเดิม, energy average,
  gap, event limit, privacy allowlist และขอบเขต read-only
- เพิ่ม profile `acoustics` ใน Quality Gate; การแก้โมดูลเสียงจึงเลือก test ของ
  domain โดยตรง ไม่ตกไปใช้เฉพาะชุด core ที่ไม่ครอบคลุมรายละเอียดเสียง
- ผล Full gate และ CI ต้องยืนยันจาก SHA ของ Commit รอบนี้ ไม่ใช้ผลเก่ารับรอง
  การติดตั้งบน Pod; ไม่มีการอ่านหรือเขียนข้อมูลผู้ทดสอบระหว่าง Refactor

คำสั่งตรวจที่ทีมใช้ต่อได้:

```bash
python quality_gate.py acoustics adaptive
python -m unittest -q test_smart_senses_modules test_quality_gate test_modular_architecture
```

Full gate ใช้ในรอบนี้เพราะมีการปรับตัวเลือกชุดทดสอบ ส่วนงาน domain ปกติ
ใช้ Focused gate ตาม [TESTING.md](../../TESTING.md)
