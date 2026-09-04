# Case Note: VOC สูงขึ้นหลังผู้มีประวัติสูบบุหรี่เข้า ZEEP

สถานะข้อสรุป: **เป็นไปได้และมีหลักฐานรองรับ แต่ยังยืนยันสาเหตุจาก SGP40 เพียงตัวเดียวไม่ได้**

วันที่ทบทวน: **5 กันยายน 2026**

## เหตุผลที่เป็นไปได้

งานของ Sheu และคณะตรวจพบว่าคนสามารถพาสารตกค้างจากควันบุหรี่ (thirdhand smoke) เข้าสู่พื้นที่ปลอดบุหรี่ผ่านเสื้อผ้าและร่างกาย แล้วสารเหล่านั้นระเหยกลับสู่อากาศได้ เหตุการณ์ VOC สัมพันธ์กับเวลาที่ผู้ชมบางคนเข้ามาในโรงภาพยนตร์ และผู้วิจัยระบุว่าพื้นที่เล็กหรือระบายอากาศไม่ดีมีโอกาสทำให้ความเข้มข้นสูงขึ้น งานกับผ้าหลายชนิดยังพบสารจากบุหรี่หลายกลุ่มและการ off-gassing ต่อเนื่องหลังรับควัน ส่วนงาน emission chamber ยืนยันว่ามนุษย์ทั่วไปปล่อย VOC จากลมหายใจและผิวอยู่แล้ว

ดังนั้นใน ZEEP ซึ่งเป็นพื้นที่ขนาดเล็ก เหตุการณ์ต่อไปนี้สมเหตุผล:

1. ผู้ใช้สูบบุหรี่/บุหรี่ไฟฟ้า/ยาสูบร้อนก่อนเข้า แล้วพาสารติดเสื้อผ้า ผม ผิว หรือสัมภาระเข้ามา
2. VOC จากลมหายใจและร่างกายเพิ่มหลังมีผู้ใช้งาน โดยไม่จำเป็นต้องเกี่ยวกับบุหรี่ทั้งหมด
3. เมื่อการระบายอากาศต่ำ สารสะสมเร็วกว่าพื้นที่เปิด
4. SGP40 เห็นการเปลี่ยนแปลงรวม แต่แยกไม่ได้ว่าเป็น nicotine, benzene, ethanol, น้ำหอม หรือสารอื่น

## สิ่งที่ SGP40 บอกได้และบอกไม่ได้

| บอกได้ | บอกไม่ได้ |
|---|---|
| VOC burden เปลี่ยนจาก adaptive baseline | ระบุว่าสารคือ nicotine/benzene/น้ำหอม |
| เวลาเริ่ม spike, trend และการลดลงหลัง ventilation | ยืนยันว่าผู้ใช้สูบบุหรี่ |
| เปรียบเทียบ session ภายใต้ protocol เดียวกัน | ใช้เป็นผลตรวจทางการแพทย์หรือหลักฐานลงโทษผู้ใช้ |

VOC Index ใกล้ 100 หมายถึงระดับพื้นหลังที่อัลกอริทึมเรียนรู้ ไม่ได้หมายถึง “อากาศปลอด VOC” ค่าเกิน 100 หมายถึง VOC สูงกว่าพื้นหลังล่าสุด ส่วนค่าต่ำกว่า 100 หมายถึงต่ำกว่าพื้นหลังที่เรียนรู้ จึงต้องเก็บทั้ง `SRAW_VOC`, `VOC Index`, temperature, RH, uptime/warm-up และสถานะ baseline algorithm

## Protocol ยืนยันเหตุการณ์ใน ZEEP

1. **Blank run:** ปิดกลิ่น/ไอน้ำ ทำตู้ว่างอย่างน้อย 15 นาที บันทึก SRAW, VOC Index, CO₂, PM2.5, temperature, RH และ ventilation ทุก 10 วินาที
2. **ตรวจ actuator:** ยืนยันจาก command/acknowledgement log ว่าไม่มี diffuser, humidifier, cleaning หรือ maintenance event ในช่วงก่อนและระหว่าง spike
3. **กำหนดเวลาเข้า:** บันทึก `occupancy_entered_at`, `bed_occupied_at`, ประตู และ airflow เพื่อ time-align กับ sensor โดยไม่ใช้ชื่อในชุดวิเคราะห์
4. **แบบสอบถามสมัครใจแบบช่วงเวลา:** สูบ/สูดไอ/ยาสูบร้อนครั้งล่าสุด `<15 นาที`, `15–60 นาที`, `1–4 ชม.`, `>4 ชม.`, `ไม่ใช้/ไม่ประสงค์ตอบ`; บันทึกน้ำหอม alcohol sanitizer อาหาร/เครื่องดื่ม และการใช้ผลิตภัณฑ์ทำความสะอาดด้วย
5. **Matched comparison:** เทียบคนเดิมต่างวันภายใต้ airflow, temperature, RH และเสื้อผ้าใกล้เคียง หรือเทียบ cohort โดยใช้ coded ID; ห้ามสรุปจาก session เดียว
6. **Decay test:** หลังผู้ใช้ออก ให้คง sensor/airflow เดิมและวัดการลดลงอย่างน้อย 20–30 นาที แล้วทำ ventilation A/B test
7. **Reference confirmation:** หากต้องการระบุแหล่ง ให้ใช้ PID/TVOC ที่สอบเทียบเพื่อคัดกรอง และ sorbent tube + GC-MS/เครื่องมือจำแนกสาร โดยพิจารณา tobacco tracers เช่น acetonitrile, 2,5-dimethylfuran และ nicotine ตามวิธีวิจัย
8. **QA:** ทำ field blank, duplicate, ตรวจตำแหน่งเซนเซอร์, warm-up/restart, filter saturation และ RH/temperature compensation

## รูปแบบสัญญาณที่ช่วยตั้งสมมติฐาน

| รูปแบบ | สมมติฐานที่ควรตรวจ | ยังสรุปไม่ได้ว่า |
|---|---|---|
| VOC และ CO₂ เพิ่มหลังคนเข้า, PM2.5 คงเดิม | breath/skin bioeffluent, personal care หรือ smoke residue แบบ gas phase | เป็นบุหรี่แน่นอน |
| VOC และ PM2.5 เพิ่มพร้อมกันหลังเข้า | ควัน/ละออง, spray, aerosol หรือฝุ่นถูกรบกวน | ชนิดแหล่งกำเนิด |
| VOC เพิ่มก่อนผู้ใช้เข้า | วัสดุ POD, cleaning, diffuser carry-over, filter/ventilation | เกิดจากผู้ใช้ |
| VOC spike พร้อม RH เปลี่ยนเร็ว | humidity compensation, ไอน้ำ, condensation หรือกิจกรรมผู้ใช้ | เป็นสารพิษเพิ่มขึ้นจริง |
| VOC ลดเร็วเมื่อเร่งระบาย | แหล่งกำเนิด airborne ภายใน POD | ระบุชนิดสาร |

## แหล่งอื่นที่ต้องเก็บเป็น confounder

- บุหรี่ไฟฟ้า/ยาสูบร้อนและสารตกค้างจากคนใกล้ชิดหรือสถานที่ก่อนหน้า
- น้ำหอม deodorant hair spray เครื่องสำอาง โลชั่น และน้ำมันหอมระเหย
- alcohol hand sanitizer เครื่องดื่มแอลกอฮอล์ ยา/สเปรย์ และอาหารกลิ่นแรง
- น้ำยาทำความสะอาด ฆ่าเชื้อ กาว epoxy สี โฟม พลาสติก ที่นอน/ผ้าใหม่
- diffuser/สายกลิ่นรั่ว กลิ่นค้าง cartridge และไอน้ำ
- เหงื่อ การออกกำลังกาย อุณหภูมิผิว เสื้อผ้าเปียก และจำนวนคน
- filter อิ่มตัว, airflow ต่ำ, recirculation, ประตูเปิด/ปิด และตำแหน่ง SGP40
- warm-up ไม่ครบ, baseline reset หลัง reboot, firmware/compensation ผิด และ packet ค้าง

## ข้อเสนอด้านระบบและข้อมูลส่วนบุคคล

- Dashboard แสดง “VOC สูงกว่าพื้นหลัง” และการตอบสนองที่แนะนำ ไม่แสดง “ตรวจพบผู้สูบบุหรี่”
- ป้ายเหตุการณ์ควรเป็น `possible_external_voc_source` จนกว่าจะมี reference measurement
- ข้อมูลการสูบบุหรี่เป็นข้อมูลสุขภาพ/พฤติกรรมที่ละเอียดอ่อนในบริบทการวิจัย: ขอความยินยอม เก็บเท่าที่จำเป็น ใช้ coded ID จำกัดสิทธิ์ และกำหนด retention/deletion
- Safety response ควรอิงเกณฑ์ที่อนุมัติร่วมกับ CO₂/PM2.5/ควัน/CO และความพร้อมระบบ ไม่ใช้ VOC Index เพียงตัวเดียวสั่ง emergency

## เอกสารหลัก

- [Sheu et al., Human transport of thirdhand tobacco smoke (2020)](https://doi.org/10.1126/sciadv.aay4109)
- [Tondro Borujeni et al., VOCs of third-hand smoke from clothing fabrics (2022)](https://doi.org/10.1007/s40201-021-00755-1)
- [Wang et al., Emission Rates of VOCs from Humans (2022)](https://doi.org/10.1021/acs.est.1c08764)
- [WHO Tobacco and Nicotine Fact Sheet, checked 2026-09-05](https://www.who.int/news-room/fact-sheets/detail/tobacco)
- [Sensirion SGP40 VOC Index for Experts](https://sensirion.com/en/media/documents/A6D12AD4/61644979/Sensirion_Gas_Sensors_Datasheet_GAS_AN_SGP40_VOC_Index_for_Experts_D.pdf)
