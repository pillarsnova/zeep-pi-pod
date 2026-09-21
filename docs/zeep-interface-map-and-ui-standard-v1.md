# ZEEP Interface Map & UI Standard v1

สถานะ: **Current**  
เจ้าของ: Pi 5 application team  
อัปเดตล่าสุด: 19 กันยายน 2026

เอกสารนี้เป็นแผนที่หน้าจอและเกณฑ์ตรวจ UX/UI ของ Pi 5 สำหรับผู้ใช้ ผู้ดูแล
และทีมทดสอบอุปกรณ์ โดยไม่เปลี่ยนสิทธิ์หรือ Logic ของ Session

ลำดับข้อมูลด้านล่างเป็นมาตรฐานเป้าหมาย ไม่ใช่คำรับรองว่า DOM/keyboard ของทุกหน้า
ผ่านแล้ว ข้อจำกัดที่ตรวจจาก `9516413` และเกณฑ์รุ่นถัดไปอยู่ใน
[Interface Roadmap](zeep-interface-development-roadmap.md)
การอัปเดตหลังจากนั้น เช่นคำแนะนำ v1.2 ให้ดู [Current Status](current-status.md)
และ [Result Presentation](zeep-session-result-presentation-v1.md)

ข้อความรอบ 19 ก.ย. ปรับใน source ตั้งแต่ Login, Dashboard, Control, Monitor,
Sessions และ Session End แล้ว ดู [ผลตรวจเนื้อหา](reviews/2026-09-19-interface-content-review.md)
ยังไม่ใช่การรับรอง deploy หรือการตรวจทุกขนาดหน้าจอ

## 1. แผนที่หน้า Interface

| URL / Surface | ผู้ใช้ | หน้าที่หลัก | สิ่งที่ต้องเห็นก่อน |
|---|---|---|---|
| `/` | ทุกคน | ส่งต่อไปหน้าเข้าสู่ระบบ | ช่องทางเข้าสู่ระบบที่ถูกต้อง |
| `/login` | ผู้ทดสอบ | เข้าสู่ระบบ เลือก Nap & Refresh หรือ Overnight Recovery และเวลาเป้าหมาย | บัญชี รูปแบบการพัก และคำแนะนำก่อนเริ่ม |
| `/login/qr` | ผู้ทดสอบ | เข้าสู่ระบบผ่าน QR จากแอป ZEEP | QR และสถานะการยืนยัน |
| `/admin/login` | ผู้ดูแล | เข้าสู่ระบบสำหรับทีมงาน | ขอบเขตสิทธิ์ผู้ดูแลและสถานะระบบ |
| `/dashboard` | ผู้ทดสอบ/ผู้ดูแล | ภาพรวมการพัก | HR, RR, สถานะเตียง, Sleep State และสภาพแวดล้อมสด ก่อน Baseline/Profile |
| `/control` | ผู้ทดสอบ/ผู้ดูแล | ควบคุมอุปกรณ์ภายใน ZEEP | ประตู, แสง, แอร์, กลิ่น/ไอน้ำ, เตียง และเสียง พร้อม Sensor ที่เกี่ยวข้อง |
| `/control-debug` | ผู้ดูแล | Commissioning และทดสอบ Hardware จริง | Controller, คำสั่ง, Request/Payload/ACK/Response และ Safety warning |
| `/monitor` | ผู้ดูแล | ติดตามระบบและการพัก | Version/Provenance, Safety, Sensor integrity และ Live physiology |
| `/sessions` | ผู้ทดสอบ/ผู้ดูแล | ดูประวัติการใช้งานและผลราย Session | User เห็นของตนเอง; Admin เห็นผู้ใช้ทั้งหมด จำนวนครั้ง แยกโหมด ตัวกรอง รายการพัก และรายงานที่เลือก |
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
6. Smart Ear · Level Timeline และ DSP markers แบบชั่วคราวสำหรับผู้ดูแล
7. ข้อมูลเชิงเทคนิค (Advanced Diagnostics) เมื่อผู้ดูแลเปิดดู

Live strip เป็นแหล่งค่าปัจจุบันหลัก ส่วนคำอธิบายและ Reference ต้องไม่ทวนค่าชุดเดิม
โดยไม่มีบริบทเพิ่ม

“หูอัจฉริยะ” ตาม [Acoustic Intelligence DSP Plan](onboarding/smart-ear-dsp-plan.md)
มี Level Timeline และ optional DSP marker แบบ **P1 ADMIN SHADOW** แล้ว
นอก Session แสดงสดแต่ไม่บันทึก เมื่อไม่มี features กลับเป็น level-only;
ป้ายเสียงยังไม่ใช่ผลจำแนกที่รับรองความแม่นยำหรือผลสุขภาพในหน้า User

### Sessions

1. เลือกช่วงเวลา/ผู้ใช้งานตามสิทธิ์
2. สรุป Sleep Score และ Recovery Score แยกตาม Mode
3. รายการการพัก
4. ผลของ Session ที่เลือก โดยรายละเอียดเทคนิคอยู่ในส่วนพับได้
5. แนวโน้มรายบุคคลแบบพับ โดยแยก Sleep Score และ Recovery Score

ภาษาและลำดับภาพของ Monitor กับ Sessions ใช้หลักเดียวกัน: แสดงภาพรวมที่ตัดสินใจ
ได้ก่อน ใช้คำไทยเป็นหัวข้อหลัก และเก็บคำวิศวกรรมหรือภาษาอังกฤษไว้เป็นคำรองหรือ
ในส่วนที่เปิดดูเพิ่มเติม หน้า Sessions ไม่สร้างหัวข้อ “ประวัติการใช้งาน” ซ้ำภายใน
Card เพราะ Page heading ของ Shell ทำหน้าที่นี้อยู่แล้ว

ผู้ใช้เห็นเฉพาะข้อมูลของตน ผู้ดูแลจึงเห็นตัวกรองชื่อ/อีเมลและคำสั่งจัดการข้อมูล
ผลที่เลือกแสดง **คำแนะนำสำหรับคุณ** หนึ่งข้อจาก Session พร้อมเหตุผลแบบพับเก็บ
ไม่รวมคำแนะนำสดจาก Monitor เข้าไปในผลย้อนหลัง และไม่แสดงว่าเป็นสภาพร่างกายวันนี้

## 3. UI Standard กลาง

รายการนี้เป็นเกณฑ์ฐานเดิมของ v1; เป้าหมาย typography/token รอบใหม่ใน Roadmap
ต้องทยอยตรวจและปรับ component ก่อนประกาศว่าใช้ครบทั้งระบบ

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
- จอมือถือ Control ใช้หนึ่งคอลัมน์ ส่วน Tablet และ Desktop landscape ใช้สอง
  คอลัมน์ × สามแถว เพื่อให้การ์ดทั้งหกมีพื้นที่กดและอ่านข้อความเท่ากัน
- เมื่อ `prefers-reduced-motion` ทำงาน Animation ต้องไม่ขัดการอ่านหรือควบคุม

## 4. Viewport ที่ใช้ตรวจ

| Viewport | ตัวแทนการใช้งาน | เกณฑ์ |
|---|---|---|
| 1440 × 900 | Notebook/Desktop Monitor | ไม่มี horizontal overflow; ข้อมูลสดและ Safety เห็นง่าย |
| 1280 × 720 | Touch landscape/fullscreen | Control 2 คอลัมน์ × 3 แถว; ปุ่มหลักไม่ถูกบีบ |
| 800 × 1280 | Redmi Pad 2 portrait | Control 2 คอลัมน์; menu และ input แตะได้ |
| 390 × 844 | Mobile fallback | Control 1 คอลัมน์; ไม่มีข้อความ/ปุ่มซ้อนกัน |

ทุก Route ต้องตรวจทั้ง User/Admin ที่เกี่ยวข้อง รวมถึง Login และ Session End

## 5. Verification และงานคงค้าง

ยกเลิกการนำตารางผ่าน Audit วันที่ 16–17 ก.ย. มาแสดงเป็นผลรับรองปัจจุบัน
ประวัติเดิมย้อนดูได้จาก Git; เกณฑ์ขนาดขั้นต่ำใน §3 ยังใช้ตรวจรอบใหม่
ต้องแนบ SHA, บทบาท, viewport และ computed geometry ของ release ที่ตรวจจริง

[Interface Review ที่ `9516413`](reviews/2026-09-19-interface-roadmap-review.md)
เป็นหลักฐานเฉพาะ source/test รอบนั้น ไม่ใช่ browser/keyboard/ทุก viewport acceptance
ส่วน [Rerun Review](reviews/2026-09-19-after-rest-rerun.md) ยืนยันข้อมูลและ API
ไม่ได้แทน visual QA หลังเพิ่มคำแนะนำ

งานคงค้าง UI/DOM/CSS, export parity และ accessibility ให้ติดตามที่
[Roadmap](zeep-interface-development-roadmap.md) เพียงแหล่งเดียว ไม่ทำรายการซ้ำที่นี่
