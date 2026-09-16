# ZEEP Interface Map & UI Standard v1

สถานะ: **Current**  
เจ้าของ: Pi 5 application team  
อัปเดตล่าสุด: 16 กันยายน 2026

เอกสารนี้เป็นแผนที่หน้าจอและเกณฑ์ตรวจ UX/UI ของ Pi 5 สำหรับผู้ใช้ ผู้ดูแล
และทีมทดสอบอุปกรณ์ โดยไม่เปลี่ยนสิทธิ์หรือ Logic ของ Session

## 1. แผนที่หน้า Interface

| URL / Surface | ผู้ใช้ | หน้าที่หลัก | สิ่งที่ต้องเห็นก่อน |
|---|---|---|---|
| `/` | ทุกคน | ส่งต่อไปหน้าเข้าสู่ระบบ | ช่องทางเข้าสู่ระบบที่ถูกต้อง |
| `/login` | ผู้ทดสอบ | เข้าสู่ระบบ เลือก Nap & Refresh หรือ Overnight Recovery และเวลาเป้าหมาย | บัญชี รูปแบบการพัก และคำแนะนำก่อนเริ่ม |
| `/login/qr` | ผู้ทดสอบ | เข้าสู่ระบบผ่าน QR จากแอป ZEEP | QR และสถานะการยืนยัน |
| `/admin/login` | ผู้ดูแล | เข้าสู่ระบบสำหรับทีมงาน | ขอบเขตสิทธิ์ผู้ดูแลและสถานะระบบ |
| `/dashboard` | ผู้ทดสอบ/ผู้ดูแล | ภาพรวม Session ปัจจุบัน | HR, RR, สถานะเตียง, Sleep State และสภาพแวดล้อมสด ก่อน Baseline/Profile |
| `/control` | ผู้ทดสอบ/ผู้ดูแล | ควบคุมอุปกรณ์ภายใน ZEEP | ประตู, แสง, แอร์, กลิ่น/ไอน้ำ, เตียง และเสียง พร้อม Sensor ที่เกี่ยวข้อง |
| `/control-debug` | ผู้ดูแล | Commissioning และทดสอบ Hardware จริง | Controller, คำสั่ง, Request/Payload/ACK/Response และ Safety warning |
| `/monitor` | ผู้ดูแล | ดูความปลอดภัย สุขภาพ Sensor ข้อมูลสด และ Personal Reference | Version/Provenance, Safety, Sensor integrity และ Live physiology |
| `/sessions` | ผู้ทดสอบ/ผู้ดูแล | ดูประวัติการใช้งานและผลราย Session | ตัวกรอง, Sleep/Recovery Score, รายการพัก และรายงานที่เลือก |
| `/admin` | ผู้ดูแล | Alias เข้าหน้า Control หลังยืนยันสิทธิ์ | Control deck เดียวกับผู้ใช้ พร้อมทางเข้า Debug |

### Surface ร่วม

| Surface | หน้าที่ |
|---|---|
| Boot | แจ้งว่าระบบกำลังเตรียม ZEEP |
| Profile completion | เก็บข้อมูลสุขภาพพื้นฐานที่ยังขาดก่อนเริ่ม Session |
| Session End | สรุปผลหลังจบ Session และแสดง QR ให้นำผลกลับ |
| Confirm modal | ยืนยันคำสั่งที่มีผลต่อ Session หรืออุปกรณ์ |
| Safety alert / Toast | แจ้งเตือนแบบสั้นโดยไม่แย่งบริบทของหน้าหลัก |

## 2. โครงสร้างข้อมูลของแต่ละหน้า

### Dashboard

1. ข้อมูลสดด้านสุขภาพและสภาพแวดล้อม
2. Baseline ช่วงเวลาพักส่วนบุคคล
3. Profile ที่ใช้ประกอบคำแนะนำ

Profile ไม่ควรอยู่เหนือ HR/RR หรือสภาพแวดล้อม เพราะไม่ใช่ข้อมูลที่เปลี่ยนระหว่าง
Session

### Control

ลำดับภาพและลำดับ Tab ต้องตรงกันเสมอ:

1. ประตู
2. แสงภายใน ZEEP
3. อากาศและอุณหภูมิ
4. กลิ่นและไอน้ำ
5. เตียงและผู้ใช้งาน
6. เสียงใน ZEEP

User และ Admin ใช้ Control deck เดียวกัน Admin เพิ่มทางเข้า Control Debug เท่านั้น

### Monitor

1. Version & Provenance
2. Safety และ Sensor integrity
3. Live physiology และคำอธิบายเฉพาะข้อสังเกต
4. Personal Reference/Adaptive recommendation
5. สภาพแวดล้อม
6. Advanced Diagnostics เมื่อผู้ดูแลเปิดดู

Live strip เป็นแหล่งค่าปัจจุบันหลัก ส่วนคำอธิบายและ Reference ต้องไม่ทวนค่าชุดเดิม
โดยไม่มีบริบทเพิ่ม

### Sessions

1. เลือกช่วงเวลา/ผู้ใช้งานตามสิทธิ์
2. สรุป Sleep Score และ Recovery Score แยกตาม Mode
3. รายการการพัก
4. แนวโน้มรายบุคคล
5. ผลของ Session ที่เลือก โดยรายละเอียดเทคนิคอยู่ในส่วนพับได้

ผู้ใช้เห็นเฉพาะข้อมูลของตน ผู้ดูแลจึงเห็นตัวกรองชื่อ/อีเมลและคำสั่งจัดการข้อมูล

## 3. UI Standard กลาง

- Touch target สำหรับคำสั่งหลักไม่น้อยกว่า `44 × 44 px`
- ข้อความประกอบผู้ใช้ทั่วไปไม่น้อยกว่า `11 px`; label `12 px`; หัวข้อย่อย
  `16 px` โดยข้อมูลดิบ Admin อาจหนาแน่นกว่าแต่ห้ามต่ำกว่า `10 px`
- ใช้ SVG line icon จาก sprite กลาง ขนาดพื้นฐาน 24 px, stroke 1.8 และใช้สีเพื่อ
  เสริมสถานะ ไม่ใช้สีเป็นหลักฐานเดียว
- Card ใช้มุมโค้ง 14–20 px, เส้นกรอบบาง และระยะห่างฐาน 8/12/16/24 px
- Primary text, secondary text และ metadata ต้องมี contrast/lำดับน้ำหนักชัด
- Navigation ต้องแสดงหน้าปัจจุบันทั้งภาพ (`active`) และ accessibility
  (`aria-current="page"` หรือ `location` สำหรับหน้าลูกอย่าง Control Debug)
- รองรับ pinch zoom และ keyboard submit/focus; placeholder ไม่ใช้แทน label
- จอมือถือ Control ใช้หนึ่งคอลัมน์, Tablet สองคอลัมน์ และ Desktop landscape
  สามคอลัมน์ เพื่อคงขนาดปุ่มและชื่อการ์ด
- เมื่อ `prefers-reduced-motion` ทำงาน Animation ต้องไม่ขัดการอ่านหรือควบคุม

## 4. Viewport ที่ใช้ตรวจ

| Viewport | ตัวแทนการใช้งาน | เกณฑ์ |
|---|---|---|
| 1440 × 900 | Notebook/Desktop Monitor | ไม่มี horizontal overflow; ข้อมูลสดและ Safety เห็นง่าย |
| 1280 × 720 | Touch landscape/fullscreen | Control 3 × 2; ปุ่มหลักไม่ถูกบีบ |
| 800 × 1280 | Redmi Pad 2 portrait | Control 2 คอลัมน์; menu และ input แตะได้ |
| 390 × 844 | Mobile fallback | Control 1 คอลัมน์; ไม่มีข้อความ/ปุ่มซ้อนกัน |

ทุก Route ต้องตรวจทั้ง User/Admin ที่เกี่ยวข้อง รวมถึง Login และ Session End

ผลตรวจรอบวันที่ 16 กันยายน 2026: ตรวจ 9 surface ที่เกี่ยวข้องกับสิทธิ์ผู้ใช้และ
ผู้ดูแล ครบทั้ง 4 viewport รวม 36 รูปแบบ ไม่พบ horizontal overflow หรือคำสั่งที่
มีพื้นที่แตะต่ำกว่าเกณฑ์ ข้อความที่มีความหมายต่อผู้ใช้ไม่น้อยกว่า 10 px
(ไม่นับจุดสีตกแต่งระดับสถานะ)

## 5. ผล Audit รอบนี้

แก้ไขแล้ว:

- เพิ่ม final consistency stylesheet เพื่อลดผลกระทบจาก legacy override
- Control มือถือกลับเป็นหนึ่งคอลัมน์ และ Desktop landscape เป็นสามคอลัมน์
- ลำดับ DOM/Tab ของ Control ตรงกับลำดับที่มองเห็น
- Dashboard แสดงข้อมูลสดก่อน Personal Baseline/Profile
- Control Debug และ Advanced Monitor เพิ่มขนาดข้อความ/ปุ่มที่เล็กเกินไป
- Sessions ลดหัวข้อ/กรอบซ้ำและใช้ตัวกรองสูง 44 px ทุก viewport
- Login มี label ถาวร ส่งด้วย Enter ได้ และเปิดให้ผู้ใช้ซูมหน้าเว็บ
- Icon ระบบ, Safety และ Debug ใช้ภาษาภาพเดียวกันมากขึ้น
- Navigation ประกาศ `aria-current` และ Control Debug รองรับ Focus/fullscreen
- Session End ใช้ Card language เดียวกับระบบ และวาง QR ก่อนรายละเอียดบนจอแคบ
- Regression/Safety test ผ่าน `1,103` รายการ และ UI bundle ตรงกับ source partial

งานลดหนี้โครงสร้างหลัง v1 ที่ต้องทำแบบแยก Release:

1. ย้าย heading ของ Monitor ให้อยู่กับ section ใน DOM แทนการกระจายด้วย CSS order
2. ลบ Control cards รุ่นเก่าที่ซ่อนอยู่หลังยืนยันว่าไม่มี runtime consumer
3. แยก `theme-modern.css` เป็น `shell`, `dashboard`, `control`, `reports` และ
   `overlays` แล้วลบ override รุ่นเก่า
4. เพิ่ม visual regression ที่ตรวจ computed geometry, touch target และ overflow
   อัตโนมัติใน CI

การแยกงานเหล่านี้ออกจากรอบปรับภาพช่วยไม่ให้การลบ CSS/DOM เก่ากระทบคำสั่งอุปกรณ์
จริงก่อน Code Freeze
