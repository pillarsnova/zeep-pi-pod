# ZEEP Pilot · Two-Mode Test Protocol v1.3

สถานะ: เอกสารใช้งานปัจจุบัน  
ขอบเขต: ZEEP Sleep Wellness Pilot; ไม่ใช่การวินิจฉัยหรือการรักษา

Runtime: `zeep-session-report-v10.12-minimum-only-score-release` /
`zeep-rest-quality-v8.10-minimum-only-score-release`; สูตรคะแนน
`zeep-sleep-score-v2.1-minimum-only-neutral-25-35-20-10-10` และ
`zeep-recovery-score-v3.1-minimum-only-neutral-25-35-30-10`

## ยินดีต้อนรับสู่การทดสอบใช้งาน ZEEP

การทดสอบมี 2 รูปแบบ

1. **Nap & Refresh** — การพักผ่อนระหว่างวันตามเป้าหมาย 30 หรือ 90 นาที ผู้ทดสอบอาจหลับ
   พักสายตา หรือทำสมาธิก็ได้ ไม่จำเป็นต้องหลับลึก
2. **Overnight Recovery** — การพักผ่อนแบบค้างคืน แนะนำให้นอนตามปกติและ
   ทำตัวให้สบายที่สุด

หลักจำง่าย: **Overnight Recovery แสดง Sleep Score** ส่วน **Nap & Refresh แสดง
Recovery Score** ทั้งสองคะแนนตอบคนละคำถามและไม่ควรนำมาเปรียบเทียบตรง ๆ

## ขั้นตอนสำหรับผู้ทดสอบ

1. ดาวน์โหลดแอปพลิเคชัน ZEEP ลงบนโทรศัพท์มือถือ เพื่อเชื่อมต่อกับระบบและดู
   ผลการทดสอบหลังใช้งาน
2. จัดการภารกิจส่วนตัวให้เรียบร้อยก่อนเริ่ม สำหรับ Overnight Recovery ให้
   เปลี่ยนเป็นชุดที่ทีมงานจัดเตรียมไว้ในห้องส่วนตัว
3. มาที่จุด ZEEP เพื่อทำแบบประเมินก่อนใช้งาน และรับคำแนะนำเกี่ยวกับวิธีใช้
   ฟังก์ชันและคุณสมบัติของเครื่องจากทีมงาน
4. เริ่มการทดสอบตามรูปแบบที่เลือก ทำจิตใจให้สบาย พักอย่างเป็นธรรมชาติ และงด
   ใช้โทรศัพท์ระหว่างทดสอบ
5. เมื่อสิ้นสุดการทดสอบ ทำแบบประเมินหลังใช้งาน พร้อมรีวิวความรู้สึกและ
   ประสบการณ์เบื้องต้น ผลที่ Sensor รองรับจะแสดงผ่านแอป ZEEP

ข้อมูลและความคิดเห็นจากผู้ทดสอบใช้เพื่อพัฒนา ZEEP ให้ตอบโจทย์การพักผ่อนดีขึ้น

## Contract การประเมิน

| หัวข้อ | Nap & Refresh | Overnight Recovery |
|---|---|---|
| Intent | พักระหว่างวัน | นอนค้างคืน |
| เวลา | เลือกเป้าหมายก่อนเริ่ม: 30 นาที (แนะนำ 25–35) หรือ 90 นาที (แนะนำ 75–105) | ขั้นต่ำ protocol 5 ชม.; คะแนนเวลาเต็มที่ 7 ชม.สำหรับผู้ใหญ่ |
| จำเป็นต้องหลับ | ไม่จำเป็น | เป็นเป้าหมายของโหมด; หาก Timeline ที่มีหลักฐานยืนยันว่าไม่พบช่วงหลับจะได้ Sleep Score 0 แต่ไม่เปลี่ยนเป็น Nap |
| N3 / REM | ไม่บังคับและไม่หักเพราะไม่มี | ใช้ใน architecture score ตาม policy |
| ถ้าไม่หลับ | ยังเป็น Recovery Score เมื่อ Session ครบ 10 นาที; หลักฐานที่ขาดใช้ neutral และลด confidence | แสดงว่าไม่พบการหลับและให้ Sleep Score 0 เมื่อครบ 5 ชั่วโมง; confidence สะท้อนความครบของหลักฐาน และไม่เปลี่ยนเป็น Nap อัตโนมัติ |
| ผลจาก Sensor | เวลา, HR/RR stability/settling, Bed Status, continuity, environment, coverage; Sleep State เมื่อมีหลักฐานครบ | TST proxy, latency proxy, continuity, W/N1/N2/N3/REM, cycle proxy, environment, coverage |
| ผลจากแบบประเมิน | ความสดชื่น/ง่วง/ผ่อนคลายหลังพัก | ความสดชื่นและประสบการณ์หลังตื่น |

### Nap & Refresh ที่ไม่หลับ

ใช้ `Recovery Score` 100 คะแนน:

- เวลาพักตามเป้าหมาย 25
- การตอบสนอง HR/RR 35
- ความต่อเนื่อง/ความนิ่ง 30
- สภาพแวดล้อมสนับสนุน 10

สูตรรุ่น v3.1 ใช้เส้นโค้งรากที่สองกับเวลาพัก, ให้ HR/RR ที่มีหลักฐานจริง
เริ่มจาก Wellness neutral floor, และลดผลของการขยับธรรมดาเหลือครึ่งหนึ่งของ
movement ratio การลุกจากเตียงยังหักแยกแบบจำกัดและคูณด้วยสัดส่วนเวลาอยู่บนเตียง
จริง ตัวหารคงที่ 100; Bed/Environment ที่หายใช้ neutral 75% และลด confidence
แทนการ normalize ให้คะแนนสูงขึ้น Safety excursion cap ส่วน Environment ที่ 30%
พร้อมสถานะให้ทีมตรวจสอบ

ความครบของ Sensor และ paired HR/RR แสดงเป็น Coverage/Confidence แยกจาก
คะแนน ไม่ได้รับแต้มและไม่หักซ้ำ Session ต้องบันทึกอย่างน้อย 10 นาทีจึงเผยแพร่
Recovery Score รุ่นปัจจุบันได้ ส่วน Target 30/90 นาที, HR/RR, Bed/State และ
Environment ที่ขาดใช้ค่า neutral 75% ในองค์ประกอบนั้นและลด confidence โดยห้าม
อธิบายค่า neutral ว่าเป็นสิ่งที่ Sensor วัดได้

หากไม่มีหลักฐาน Sensor หลักเลย ระบบใช้คะแนนกลาง 50 ที่แจกแจงกลับลงใน
`imputed_component_points` ให้ผลรวมตรงกับคะแนน และแสดงข้อความสั้นว่า
“เวลาบันทึกครบขั้นต่ำ แต่ข้อมูล Sensor ครั้งนี้มีจำกัด” โดยไม่เสนอให้ปรับค่าที่ไม่ได้วัด

ระยะเวลาที่ต่างจากเป้าหมาย รวมถึง Nap ที่ยาวเกิน 120 นาที เป็นธงให้ Admin ตรวจ
Mode/Session lifecycle เท่านั้น ไม่ใช่ hard maximum และไม่ปิด Recovery Score เมื่อ
ผ่านขั้นต่ำ 10 นาทีแล้ว

คะแนนนี้ไม่สร้าง Sleep Stage และไม่กล่าวว่าผู้ใช้ “หลับดี” หาก Sensor ไม่พบ
การหลับ ความสดชื่นและความผ่อนคลายเป็นผลเชิงอัตวิสัย ต้องอ่านร่วมกับแบบประเมิน
หลังใช้

### Nap & Refresh ที่พบการหลับ

ยังคงใช้ `Recovery Score` เดียวกัน ไม่เปลี่ยนเป็น Sleep Score และไม่ให้โบนัสบังคับ
จาก N3/REM สถานะที่ตรวจพบแสดงเป็นบริบทประกอบได้เมื่อหลักฐานครบ การงีบสั้นอาจมีประโยชน์
โดยไม่มี slow-wave sleep และการงีบราว 30 นาทีอาจเกิด sleep inertia ได้ จึงควร
เก็บแบบประเมินหลังใช้และเว้นช่วงก่อนทำกิจกรรมที่ต้องใช้ความตื่นตัวสูง

### Overnight Recovery

ใช้ Sleep Score 100 คะแนน:

- เวลาและการเข้าสู่การนอน 25
- ความต่อเนื่องของการนอน 35
- รูปแบบ Sleep Stage จาก BCG แบบจำกัดผล 20
- การตอบสนอง HR/RR 10
- สภาพแวดล้อมสนับสนุน 10

Cycle และ Coverage แสดงเป็นบริบท/ความมั่นใจ แต่ไม่ให้หรือหักคะแนน การไม่พบ
N3/REM จาก BCG จึงไม่ทำให้คะแนนทั้งคืนต่ำเกินจริง และ Wake มีผลผ่าน efficiency
เพียงครั้งเดียว ไม่ถูกหักซ้ำใน continuity

Sleep Score รุ่น v2.1 เผยแพร่เมื่อ Overnight Recovery บันทึกครบอย่างน้อย 5 ชั่วโมง
หาก Timeline ที่มีหลักฐานยืนยันว่าไม่พบช่วงหลับ คะแนนเป็น 0; หากไม่มี State
evidence เลย คะแนนกลางถูกจำกัดไม่เกิน 50 ส่วน HR/RR หรือ Environment component
ที่ขาดใช้ neutral 75% พร้อมลด confidence ไม่ใช่เหตุให้ซ่อนคะแนน

เป้าหมาย 7 ชั่วโมงเป็นเกณฑ์ duration สำหรับผู้ใหญ่ตาม AASM/SRS ไม่ใช่ข้อวินิจฉัย
รายบุคคล และ “ความสดชื่นหลังตื่น” ต้องใช้แบบประเมินหลัง Session ประกอบ

รายละเอียดสูตร release gate และข้อจำกัดของหลักฐานดูที่
[ZEEP Two-Mode Score Framework](../research/evidence-library/TWO_MODE_SCORE_EVIDENCE.md)

## Compatibility และข้อห้าม

- UI ใหม่รับเฉพาะ `nap_recovery` และ `sleep`
- ค่าเก่า `relax_meditation`, `recovery_readiness`, `performance_prep` และ
  `physical_comfort` อ่านเป็น Nap & Refresh โดยไม่แก้ Raw record เดิม
- `auto` และ sub-mode เช่น `short_nap`, `cycle_nap`, `overnight` คงไว้ภายใน
  สำหรับประวัติ/replay เท่านั้น
- การเลือกรูปแบบไม่แก้ผล W/N1/N2/N3/REM และ Sensor อากาศไม่กำหนด Sleep Stage
- ผล ZEEP เป็น wellness estimate จาก BCG/Sensor ไม่เทียบเท่า PSG/AASM scoring

## แหล่งอ้างอิงหลัก

- [SLP-001 · AASM/SRS Adult Sleep Duration Consensus](https://doi.org/10.5665/sleep.4716) — ผู้ใหญ่ควรนอนอย่างน้อย 7 ชั่วโมงต่อคืนเป็นประจำ
- [SLP-007 · Daytime Nap Meta-analysis](https://pmc.ncbi.nlm.nih.gov/articles/PMC8507757/) — nap อาจสนับสนุน cognition/alertness แต่ผลช่วง sleep inertia ยังไม่สม่ำเสมอ
- [SLP-009 · Wakeful Rest Meta-analysis](https://pmc.ncbi.nlm.nih.gov/articles/PMC12808189/) — quiet wakeful rest เป็นผลที่ควรศึกษาได้โดยไม่อ้างว่าเป็นการนอน
- [SLP-010 · Brooks & Lack, 2006](https://pubmed.ncbi.nlm.nih.gov/16796222/) — เปรียบเทียบงีบ 5/10/20/30 นาทีและผลทันทีหลังตื่น
- [SLP-011 · Hilditch et al., 2017](https://pubmed.ncbi.nlm.nih.gov/28366332/) — sleep inertia จากงีบสั้นขึ้นกับบริบท จึงไม่ใช้ duration เดียวเป็นกฎตายตัว
