# Smart Senses — สรุปการรวมข้อมูลและหน้าจอ

วันที่: 22 กันยายน 2026 · ขอบเขต: source/UI/เอกสาร ไม่ใช่ Deployment audit

## TL;DR

ยกระดับภาพรวมเป็น **Smart Senses** โดยมี **Smart Ear เป็นโมดูลเสียง**
ไม่เปลี่ยน API, firmware identifiers, สิทธิ์ข้อมูล, สูตรคะแนน หรือข้อมูลย้อนหลัง
หน้าจออยู่ใน commit `1bc988e`; เอกสารฉบับหลักคือ
[Smart Senses Onboarding](../onboarding/smart-senses.md)

## สิ่งที่ปรับ

- Monitor: เพิ่มสรุปขอบเขตห้าด้านแบบพับเก็บ แยกสิ่งที่อ่านได้จากแผนพัฒนา
  ไม่ทำสำเนาตัวเลขสดหรือใช้ไฟสีเขียวแทนสถานะ hardware
- ส่วนเสียง: ใช้ชื่อ `SMART SENSES · SMART EAR` คง Timeline/ป้ายเสียงเดิม
- Adaptive Journey: อยู่ใต้ Smart Senses ใช้ partial เดียวกับตัวอย่างจำลอง
  และอยู่ในหมวดสภาพแวดล้อมของ Monitor ก่อนรายละเอียดเชิงเทคนิค
- Sessions: ยังคงผลพักและคำแนะนำ ไม่เพิ่มรายการ R&D ของ Admin ให้ผู้ใช้
- Preview: แยก role Admin/User ให้ตรงกับ CSS และสิทธิ์การแสดงผลจริง
- Onboarding, Index, Hardware, API/Privacy, Tech Stack, Interface และ BOM
  เชื่อมไปขอบเขตหลักชุดเดียว ไม่สร้าง API หรือ module ซ้ำ
- เก็บข้อแตกต่างจาก [พิมพ์เขียวภายนอก](https://monitor.pillarsnova.com/zeep-project/zeep-pod-acoustic-design.html)
  เช่น DSP ที่มีแล้ว, ผลจำลองที่ยังไม่รับรองความแม่นยำ และ Voice ที่ยังไม่ทำงาน

## Verification

- Python แบบเลือกตามผลกระทบ **89 tests ผ่าน**: UI composer, documentation,
  Adaptive Journey, Acoustics และ frontend runtime wrapper
- JavaScript **66 tests ผ่าน** (รวมการ redaction, context reset และผลสองโหมด)
- Ruff สำหรับ Python ที่แก้, generated UI check และ `git diff --check` ผ่าน
- Chrome บนข้อมูลจำลอง **9 กรณีผ่าน**: Monitor, Nap, Overnight ×
  ความกว้าง 390/800/1440 px ไม่พบ JavaScript error หรือ horizontal overflow
- ตรวจภาพจริงของสรุป Smart Senses บน Desktop/Mobile; เปิด–ปิดรายละเอียดได้
  แสดงห้าด้านครบและไม่แสดงส่วน Admin ในตัวอย่าง Sessions ของ User

ข้อจำกัด: การตรวจนี้ไม่แทน telemetry หรือ smoke test บน Pod ไม่มีการ Restart,
Flash, Rerun หรือแก้เว็บไซต์ต้นทางภายนอก Git; ดู GitHub Actions ของแต่ละ SHA
เพื่อยืนยัน CI และตรวจ Pod แยกก่อนติดตั้ง
