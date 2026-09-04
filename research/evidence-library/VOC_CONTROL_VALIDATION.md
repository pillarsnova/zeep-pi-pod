# ZEEP VOC Control Validation Plan

สถานะ: **แผนตรวจสอบสำหรับ Pilot — ยังไม่ใช่ผลรับรองผลิตภัณฑ์**

เวอร์ชัน: **1.0.0** · ทบทวนล่าสุด: **5 กันยายน 2026**

## 1. คำถามหลัก

ZEEP สามารถใช้ระบบเติม/ระบายอากาศร่วมกับ Carbon Filter เพื่อลดภาระ VOC ที่เข้ามาในตู้ และพาค่ากลับสู่ช่วงเป้าหมายได้เร็วกว่า environment อ้างอิงหรือไม่ ภายใต้เงื่อนไขที่ไม่เปิดกลิ่นและไอน้ำ

เป้าหมายนี้ **ไม่ใช่การตรวจหาผู้สูบบุหรี่ ไม่ใช่การระบุชนิดสาร และไม่ใช่การพิสูจน์ว่าบุคคลใดเป็นแหล่งกำเนิด** สารระเหยจากลมหายใจ ผิว เสื้อผ้า เส้นผม ผลิตภัณฑ์ส่วนตัว และ thirdhand smoke เป็นเพียงแหล่งท้าทายที่เป็นไปได้ในชีวิตจริง

## 2. หลักการของระบบ

- การระบายอากาศช่วยเจือจางและนำมลพิษภายในออก ส่วน Carbon Filter ใช้การดูดซับสารก๊าซ/กลิ่นบางชนิด
- Pre-Filter และ HEPA มีหน้าที่หลักกับอนุภาค ไม่ควรนำมาอ้างว่าเป็นตัวกำจัด VOC
- Activated carbon มีความจุจำกัด ประสิทธิภาพแตกต่างตามสาร ปริมาณสื่อกรอง อัตราการไหล อุณหภูมิ ความชื้น และความอิ่มตัว จึงต้องมีรอบตรวจ/เปลี่ยน Filter
- SGP40 เป็นเซนเซอร์ VOC แบบกว้างและสัมพัทธ์ เหมาะกับการดูแนวโน้มและสั่งตอบสนอง แต่ไม่สามารถระบุชนิดสารหรือผู้ก่อเหตุ
- VOC Index ใกล้ 100 คือค่าเฉลี่ยพื้นหลังที่อัลกอริทึมเรียนรู้ ไม่ได้แปลว่าไม่มี VOC; เกณฑ์ `≤120` เป็น **ZEEP internal operating band** ปัจจุบัน ไม่ใช่ค่าความปลอดภัยสากลหรือความเข้มข้น ppm

## 3. สมมติฐานที่ต้องทดสอบ

ภายใต้ challenge และเงื่อนไขเดียวกัน ZEEP standard air treatment ควร:

1. ลด VOC peak ที่สูงกว่าพื้นหลัง
2. ลดภาระสะสมของ VOC ตลอด Session
3. ลดเวลาที่ VOC อยู่นอกช่วงเป้าหมาย
4. ทำให้ค่ากลับสู่ช่วงเป้าหมายเร็วขึ้น
5. รักษาผลดังกล่าวได้ต่อเนื่องก่อน Filter อิ่มตัว โดยไม่ทำให้ CO₂, อุณหภูมิ, เสียง หรือความปลอดภัยแย่ลง

## 4. ตัวชี้วัดหลัก

คำนวณจากข้อมูลทุก 10 วินาที เฉพาะช่วงที่ packet สด เซนเซอร์ผ่าน integrity gate และ SGP40 พ้น warm-up:

| Metric | นิยาม | ใช้ตอบอะไร |
|---|---|---|
| `baseline_delta_peak` | ค่าสูงสุดลบ baseline ก่อนเข้า | peak ถูกควบคุมได้เพียงใด |
| `auc_above_baseline` | พื้นที่ใต้กราฟเหนือ baseline ต่อชั่วโมง | ภาระ VOC สะสมตลอดช่วง |
| `percent_time_in_target` | เวลาที่ VOC Index `≤120` ÷ เวลาที่ข้อมูล valid | อยู่ใน ZEEP internal target กี่เปอร์เซ็นต์ |
| `time_above_target_min` | เวลารวมที่ VOC Index `>120` | อยู่นอกเป้าหมายนานเท่าไร |
| `clearance_time_min` | เวลาหลัง peak จนกลับ `≤120` และคงอยู่ ≥3 packet | ระบบพาค่ากลับได้เร็วเพียงใด |
| `T50` / `T90` | เวลาที่ส่วนเกินจาก baseline ลดลง 50% / 90% | เปรียบเทียบอัตราการกำจัดระหว่างเงื่อนไข |
| `valid_coverage_percent` | เวลาที่ข้อมูลผ่าน integrity ÷ เวลาที่คาดหวัง | ผลน่าเชื่อถือเพียงใด |

รายงาน `SRAW_VOC` ควบคู่กับ VOC Index และเก็บ temperature, RH, CO₂, PM2.5, airflow, door, occupancy, diffuser/humidifier, Filter age และ actuator acknowledgement เพื่ออธิบายตัวแปรร่วม

## 5. การออกแบบทดลองที่แนะนำ

### 5.1 Paired crossover ในคนเดิม

- เปรียบเทียบ **ZEEP standard operation** กับ **reference rest/sleep environment** ในคนเดิม ต่างวัน แต่ช่วงเวลา ระยะเวลา เสื้อผ้า กิจกรรมก่อนเข้า และผลิตภัณฑ์ส่วนตัวใกล้เคียงกัน
- ใช้เซนเซอร์อ้างอิงที่สอบเทียบและอยู่ตำแหน่งเทียบเคียง หรือสลับอุปกรณ์ระหว่างแขนการทดลองเพื่อลด unit bias
- ก่อนทุก Session ทำ blank run อย่างน้อย 15 นาที ปิดกลิ่น/ไอน้ำ และบันทึก cleaning/maintenance event
- เก็บประวัติแหล่ง VOC แบบสมัครใจและ coded เช่น บุหรี่/บุหรี่ไฟฟ้าครั้งล่าสุด น้ำหอม sanitizer อาหาร การออกกำลังกาย และเสื้อผ้า โดยไม่ใช้ข้อมูลนี้ตัดสินบุคคล
- ห้ามปิด ventilation ที่จำเป็นต่อความปลอดภัยขณะมีผู้ใช้งาน หากต้องทดสอบ treatment off ให้ทำในตู้ว่างด้วย challenge source ที่อนุมัติ หรือเทียบ standard กับ enhanced mode ที่ผ่าน safety review

### 5.2 แยกผลของ ventilation และ Carbon Filter

การเห็นกราฟลดลงหลังสั่งงานพิสูจน์ได้เพียง “สัมพันธ์ตามเวลา” เพื่อแยกกลไกควรทำ empty-pod test แบบควบคุมอย่างน้อย:

1. fan/ventilation ตามมาตรฐาน + Carbon Filter ใหม่
2. fan/ventilation เท่ากัน + media blank หรือ Filter ที่ทราบสถานะตาม protocol วิศวกรรม
3. ทำซ้ำหลายรอบและสลับลำดับ เพื่อลด carry-over
4. หากโครงสร้างรองรับ ให้ใช้ sensor ก่อนและหลัง Filter หรือเครื่องมือ TVOC/PID อ้างอิงที่สอบเทียบ

อย่าใช้ผู้ใช้งานเป็น challenge source ในการทดสอบที่ต้องปิดระบบความปลอดภัย

## 6. กติกาการวิเคราะห์

- กำหนด primary endpoint และจำนวน Session ก่อนดูผล เพื่อลดการเลือกผลเฉพาะที่สวย
- วิเคราะห์แบบ paired และแสดง median, IQR, confidence interval รวมทั้งผลราย Session; ไม่สรุปจากภาพเดียว
- เก็บสถานะ Gas Index Algorithm ต่อเนื่องระหว่างแขนทดลองเมื่อทำได้ เพราะการ reset/adaptive baseline ทำให้ค่า VOC Index ข้ามสถานที่หรือข้ามการ reboot เทียบกันตรง ๆ ไม่ได้
- หาก coverage ต่ำกว่าเกณฑ์ที่ protocol กำหนด ให้ระบุ `insufficient_data` ไม่เติมค่าหรือสรุปว่าอากาศดี
- แยกช่วง occupied, temporary exit, unoccupied clearance และ cleaning ออกจากกัน
- การยืนยันชนิดสารต้องใช้เครื่องมือจำแนก เช่น sorbent tube + GC-MS ตามแผน sampling; SGP40 เพียงตัวเดียวไม่พอ

## 7. ภาษาที่ใช้สื่อสาร

### ใช้ได้เมื่อมีข้อมูลรองรับ

- “ระหว่าง Session ระบบรักษา VOC Index ให้อยู่ในช่วงเป้าหมายของ ZEEP ได้ **X% ของช่วงข้อมูลที่ใช้ได้**”
- “หลังพบ VOC เพิ่ม ระบบระบาย/กรองทำให้ค่ากลับสู่ช่วงเป้าหมายภายใน **Y นาที**”
- “ภายใต้ protocol นี้ ZEEP ลดภาระ VOC (`auc_above_baseline`) เมื่อเทียบกับ reference ได้ **Z%**”
- “ผลการลดลงสัมพันธ์กับการทำงานของ ventilation/filter แต่ SGP40 ไม่สามารถระบุชนิดสารหรือแหล่งกำเนิดได้”

### ยังใช้ไม่ได้จนกว่าจะผ่าน validation

- “ZEEP กำจัด VOC ทุกชนิด”
- “อากาศดีเยี่ยมตลอดทั้งคืน” โดยไม่แสดง `percent_time_in_target` และ `valid_coverage_percent`
- “ตรวจพบผู้สูบบุหรี่” หรือ “VOC นี้มาจากผู้ใช้คนนี้”
- “ล้างสารพิษ/ดีท็อกซ์” หรือคำกล่าวอ้างด้านผลลัพธ์สุขภาพที่ยังไม่ได้ศึกษา

## 8. เกณฑ์ผ่าน Pilot ที่ต้องอนุมัติก่อนเริ่ม

ทีม Research, Engineering และ Safety ต้องกำหนดล่วงหน้าอย่างน้อย:

- ค่า improvement ขั้นต่ำของ `auc_above_baseline` และ `clearance_time_min`
- coverage ขั้นต่ำของ sensor และจำนวน paired sessions
- ขอบเขต CO₂, PM2.5, อุณหภูมิ, RH และเสียงที่ห้ามแย่ลง
- อายุ Filter/เงื่อนไข breakthrough และรอบเปลี่ยน
- วิธีจัดการ missing data, reboot, diffuser carry-over และ Session ที่ protocol deviation

เมื่อผ่านจึงสรุปได้เฉพาะเงื่อนไข รุ่น Filter อัตราการไหล และประชากรที่ทดสอบ ไม่ขยายเป็นคำกล่าวอ้างครอบจักรวาล

## 9. หลักฐานที่เกี่ยวข้อง

- [U.S. EPA — Air Cleaners and Air Filters in the Home](https://www.epa.gov/indoor-air-quality-iaq/air-cleaners-and-air-filters-home)
- [U.S. EPA — Residential Air Cleaners: A Technical Summary, 3rd Edition](https://www.epa.gov/sites/default/files/2018-07/documents/residential_air_cleaners_-_a_technical_summary_3rd_edition.pdf)
- [WHO — Roadmap to improve and ensure good indoor ventilation](https://www.who.int/publications-detail-redirect/9789240021280)
- [Sensirion — SGP40 product and technical downloads](https://sensirion.com/products/catalog/SGP40)
- [หลักฐานกรณีสารตกค้างที่มากับผู้ใช้งาน](SMOKING_VOC_CASE.md)
- [ทะเบียนแหล่งข้อมูลและข้อจำกัด](SOURCE_REGISTER.md)
