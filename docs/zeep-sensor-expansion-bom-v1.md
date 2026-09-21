# ZEEP Sensor Expansion — BOM ต้นแบบและเตรียมผลิต

สถานะ: **Engineering candidate / RFQ draft — ยังไม่อนุมัติ Production BOM**

ตรวจแหล่งผู้ผลิต 22 กันยายน 2026 · จำนวนต่อ Pod 1 เครื่อง

## วัตถุประสงค์

ตรวจประตู ลมจริง และอุณหภูมิพื้นผิว แทนการเดาจาก ACK
ไม่มีการจัดซื้อ เดินสาย หรือ Flash ในรอบนี้

## Candidate BOM

| ID / จำนวน | รายการ | เงื่อนไขก่อนล็อกรุ่น |
| --- | --- | --- |
| D01 / 2 ชุด | Littelfuse 59140 series + actuator 57140-000 | ตรวจเปิดสุด/ปิดสุดคนละจุด; เลือก contact variant/suffix, ระยะจริงและขายึด |
| D02 / 1 ชุด | Protected/supervised digital input board | ESD/TVS, debounce, ตรวจสายขาด/ลัดวงจร; ห้าม 24 V เข้า GPIO 3.3 V ตรง |
| A01 / 2 ตัว | Sensirion SDP810-125Pa candidate | วัด ΔP ลมเข้า/ออก; ต้องวัด pressure envelope ก่อนเลือก ±125 หรือ ±500 Pa |
| A02 / 2 ชุด | Flow element + pressure taps + tubing | ΔP ไม่ใช่ m³/h ต้องมี transfer curve และสอบเทียบรวมท่อ/ตะแกรง/ไส้กรอง |
| A03 / 1 ตัวเสริม | Differential pressure ข้ามไส้กรอง | เลือก range จากสะอาดถึงปลายอายุ; ใช้ดูอุดตัน ไม่แทน airflow sensor |
| T01 / 2 ตัว | TI TMP117 บน sensor PCB | จุดพื้นผิวเย็นและทางลม/ใกล้คอยล์; ออกแบบ thermal contact, insulation, seal |
| H01 / 1 ชุด | Extension Sensor Hub — MCU ยังไม่ล็อก | watchdog, brownout, fused power; แยก failure domain จาก Hub หลัก |
| H02 / ตาม bus map | I²C isolation/multiplexer หรือ bus แยก | ตรวจ address conflict และ capacitance; Hub ใกล้ sensors ไม่เดิน I²C ไกลโดยไม่ประเมิน EMC |
| P01 / 1 ชุด | DC/DC, fuse, reverse-polarity, locking connectors | จาก power/peak budget; แยกสายจาก compressor/solenoid |
| M01 / 1 ชุด | Brackets, harness, labels, enclosure | เข้าถึงซ่อมได้ ทำความสะอาดได้ ไม่บังลมหรือทางออก |
| Q01 / ใช้ร่วมทีม | เครื่องมืออ้างอิง flow/ΔP/temperature | calibration record ผูก serial และ revision; ตรวจหลังประกอบทั้งระบบ |

ราคา Lead time MOQ และ supplier ยังรอ RFQ จริง ไม่ใส่ตัวเลขประมาณเป็นราคายืนยัน
ทะเบียนจัดซื้อต้องมี MPN, supplier, alternate, PCN/EOL policy, compliance ตามตลาด
และต้นทุน assembly/test ด้วย

## แหล่งผู้ผลิต / เหตุผล

1. [Littelfuse 59140/57140 datasheet](https://www.littelfuse.com/assetdocs/littelfuse-reed-sensors-59140-datasheet?assetguid=d7192df8-e5c4-47cd-8950-059adf7392c9)
   — flange-mount reed sensor มี contact หลายแบบและแม่เหล็กคู่กัน ใช้ end position
   ไม่ใช่อุปกรณ์กันหนีบหรือ safety-rated lock
2. [Sensirion SDP810-125Pa](https://sensirion.com/products/catalog/SDP810-125Pa)
   — digital differential pressure แบบต่อท่อสำหรับ HVAC; ต้องออกแบบ flow element
   และยืนยันช่วงวัดก่อนแปลงเป็นอัตราลม
3. [TI TMP117 datasheet](https://www.ti.com/lit/ds/symlink/tmp117.pdf)
   — digital local temperature; ความแม่นยำชิปไม่เท่าระบบวัดพื้นผิวหลังประกอบ
   ต้องตรวจ thermal coupling/lag และ self-heating
4. [Sensirion SFM3003 datasheet](https://sensirion.com/resource/datasheet/sfm3003)
   — ศึกษาสำหรับ flow path เล็ก ไม่เลือกเป็น default ของท่อ Pod:
   300 standard L/min = 18 standard m³/h อาจไม่พอกับ flow เป้าหมาย

ตรวจ ordering code และ revision อีกครั้งก่อน PO ไม่ถือ datasheet เป็นผลทดสอบตู้

## Contract สำหรับ Hub ใหม่

คง `pod_id`, `device_id`, board revision, firmware version/checksum, boot ID,
sequence, measurement time, quality/reason, calibration ID และตำแหน่งติดตั้ง

| ข้อมูล | Type / หน่วย | Failure semantics |
| --- | --- | --- |
| `door_position` | open/closed/between/unknown | limit สองด้าน active, wire fault, stale → unknown/fault |
| `differential_pressure_pa` | number/null Pa | out-of-range/disconnect ไม่แทนด้วย 0 |
| `airflow_m3_h` | number/null + calibration_id | ไม่มี calibration → null แม้มี ΔP; ระบุ standard/actual basis |
| `surface_temperature_c` | number/null + location | ต้องประเมิน contact หลุด ไม่ใช้ค่าอากาศแทน |

Door event ส่งหลัง debounce พร้อม heartbeat; environment รวมในรอบ 10 วินาทีเดิม
แต่ acquisition/algorithm ภายในต้องคงรอบตาม datasheet ไม่ช้าลงทั้งระบบ
ตัวสำรองต้องมี ID/location แยก และพิจารณาแยก power/bus ไม่ให้พังพร้อมกัน
สอง sensor ไม่ตรงกันยังไม่ยืนยันว่าตัวไหนเสีย ต้องใช้ quality/hysteresis/reference

## ข้อมูลที่ต้องได้ก่อน Production BOM

- Door: วัสดุ ช่วงชัก end-stop tolerance, mounting gap, สายเคลื่อนที่
- Air: หน้าตัดท่อ ปริมาตรตู้ flow min/nominal/max, fan curve, filter ΔP, noise budget
- Surface: จุดเสี่ยง dew point, วัสดุ/ความหนา ช่วงอุณหภูมิ วิธีติดตั้ง
- Electrical: rail/budget, สาย, isolation, EMC และ service access
- Manufacturing: จำนวน EVT/DVT/PVT/ผลิตจริง ตลาดปลายทาง อายุใช้งาน
- ผู้รับผิดชอบ Mechanical/Electrical/Firmware/QA และผู้อนุมัติ BOM revision

## ลำดับทดสอบ

1. EVT bench และตู้ว่าง: เทียบเครื่องมืออ้างอิงทุก operating point
2. DVT: ประตูผิดตำแหน่ง/สายขาด, ท่อตัน/ลมกลับ, disconnect, compressor EMI,
   condensate, power cycle และผลต่อเสียง
3. Pilot Monitor-only: เทียบ command กับ physical state และ false alarms
4. PVT: test fixture, acceptance bands, checksum/serial mapping, traceability
5. Release: sign-off BOM revision และ change control ก่อนเชื่อมวงจรสั่งงานใหม่

ทางออกฉุกเฉินเดิมต้องทำงานแม้ Pi/Hub ใหม่เสีย Prototype sensor ไม่ลดสิทธิ์หยุด
หรือเปิดประตูของผู้ใช้ และยังไม่ใช้รับรองประสิทธิภาพระบบเพื่อสุขภาพ

## Verification

รอบนี้ตรวจเอกสารผู้ผลิตและออกแบบ interface เท่านั้น A01/A02/H01 ยังรอ design inputs
จึงเป็น candidate ไม่ใช่รายการสำหรับสั่งผลิตทันที
