# ZEEP Sleep History v21 — Dry-run Summary

> **สถานะ:** รอ Product Owner ตรวจสอบก่อน Apply
>
> **ขอบเขต:** Session ที่จบแล้ว ตั้งแต่ 1 กันยายน 2569 และยาวกว่า 25 นาที
>
> **ข้อมูลต้นฉบับ:** Production DB, Raw BCG และ Timeline ยังไม่ถูกแก้ไข

## ผลรวม Cohort

- 12 Session จาก 11 บัญชี
- Nap & Refresh 9 Session; Overnight Recovery 3 Session
- Quality QA: Tier A 6, Tier B 5 และ below B 1 Session
- Derived-result eligibility เดิม 4 Session; ตามนโยบายราย Epoch ใหม่ 12 Session
- ไม่มี Promotion Blocker

## Sleep State เดิมเทียบใหม่

| State | เดิม | ใหม่ | ผลต่าง |
|---|---:|---:|---:|
| W | 785 | 836 | +51 |
| N1 | 368 | 359 | -9 |
| N2 | 1,295 | 1,303 | +8 |
| N3 | 153 | 153 | 0 |
| REM | 469 | 456 | -13 |

รุ่นใหม่ประเมิน 4,288 Epoch และยืนยัน Sleep State 3,107 Epoch หรือ 72.5% ส่วน
1,181 Epoch ที่ไม่ควรฝืนสร้าง State ถูกเก็บอย่างชัดเจนเป็น WAIT 818, NO DATA 245
และ OFF BED 118 Epoch

State count เปลี่ยนใน 8 Session โดยเกิดจากการนำ Session ที่เคยถูก Tier กีดกันกลับมา
ประเมินเป็นราย Epoch และบังคับให้ Epoch ปัจจุบันมี Bed + HR + RR + Raw BCG ครบจริง

## Score

- Overnight Recovery คำนวณ Sleep Score
- Nap & Refresh คำนวณ Recovery Score และไม่บังคับว่าต้องหลับ
- 9 Session มีคะแนนที่ผ่าน release coverage
- 3 Session มี engineering shadow score สำหรับ Admin แต่คะแนนผู้ใช้ยังแสดงว่า
  “ข้อมูลยังไม่พอ”
- 9 Session ที่มีคะแนนเดิมและใหม่ให้เปรียบเทียบ ไม่มีคะแนนเปลี่ยน เพราะรอบนี้ไม่ได้
  เปลี่ยนสูตร Score

## Baseline Fit

Baseline Fit ถูกใช้ใน State evidence อยู่แล้ว โดยคำนวณ Age + Gender HR/RR fit ทุก
30 วินาที น้ำหนัก HR:RR คือ 0.50:0.40 และเมื่อ gate เปิด State-specific
contribution คือ W 30%, N1/N2 25%, N3 15% และ REM 20% ก่อนผ่าน transition guard

รอบนี้จึงไม่เพิ่มน้ำหนักซ้ำและไม่เปลี่ยนสูตร เพื่อป้องกันการ overfit กับผลที่โมเดลเคย
ทำนายเอง Admin สามารถตรวจ Baseline Fit, ΔHR, ΔRR และน้ำหนักได้บน Dashboard

## QA และ Apply Simulation

- Regression: 300 tests ผ่านทั้งหมด
- Promotion preview: 12 Session, 8,149 Derived events
- Apply simulation บนสำเนาฐานข้อมูล: ผ่าน 12/12 report parity
- SQLite integrity: `ok`
- Raw Timeline hash: ไม่เปลี่ยน
- Raw BCG hash: ไม่เปลี่ยน
- Audit trail: 12/12 Session เก็บ hash ของผลเดิม, rollback path และสถานะ
  `old_result_recoverable=true`

Derived events 8,149 รายการประกอบด้วย Sleep State 3,107, Evidence 3,861 และ
Operational Status 1,181 รายการ

## จุดที่ Product Owner ต้องตรวจ

1. ยืนยันการเปลี่ยน State รวมและรายการราย Session ในรายงาน owner-only
2. ยืนยันว่าจะคง release gate ของคะแนน 3 Session ที่ coverage ต่ำไว้ตามนี้
3. เมื่ออนุมัติ จึงหยุด service, สร้าง backup ใหม่ และ Apply กับ Production

รายงานละเอียดที่มีอีเมลและผลราย Session เก็บบน Pi ด้วยสิทธิ์ไฟล์ `0600` ที่
`/tmp/zeep-month-replay-20260905/policy-v21-original-vs-final.md`
