# ZEEP Research Evidence Library

เวอร์ชันทะเบียน: **1.0.0**

ตรวจแหล่งข้อมูลล่าสุด: **5 กันยายน 2026**

ขอบเขต: Sleep Wellness, สุขภาพที่เกี่ยวข้องกับการนอน, คุณภาพอากาศภายในอาคาร, VOC/ควันบุหรี่ และข้อจำกัดของเซนเซอร์

คลังนี้ทำหน้าที่เป็นหลักฐานสำหรับออกแบบ ตรวจทาน และ audit ระบบ ZEEP ไม่ใช่ฐานความรู้ที่ runtime นำข้อความจาก PDF ไปเปลี่ยนเกณฑ์หรือวินิจฉัยผู้ใช้เอง ทุกการเปลี่ยน sleep scoring, safety threshold หรือคำแนะนำสุขภาพต้องผ่านการทบทวน แล้วบันทึกเป็น policy/config ที่มีเวอร์ชันและ regression test แยกต่างหาก

## โครงสร้าง

```text
research/evidence-library/
├── papers/
│   ├── sleep/             งานด้านเวลานอน การแบ่ง sleep stage และ validation
│   ├── health-wellness/   แนวทางสุขภาพและขอบเขตระหว่าง wellness/clinical
│   ├── indoor-air-voc/    VOC จากมนุษย์ บุหรี่ เสื้อผ้า และอากาศภายใน
│   └── who/               คู่มือ/แนวทางฉบับทางการของ WHO
├── vendor/                เอกสารผู้ผลิตเซนเซอร์ที่จำเป็นต่อการตีความค่า
├── source-register.json   ทะเบียนที่เครื่องอ่านได้และ SHA-256 ของฉบับที่อนุมัติ
├── SOURCE_REGISTER.md     สรุปว่าเอกสารแต่ละฉบับใช้รองรับเรื่องใด
├── SMOKING_VOC_CASE.md    ข้อสรุปและแผนทดสอบเคส VOC หลังผู้สูบบุหรี่เข้าตู้
└── update_research_library.py
```

ไฟล์ PDF ถูกเก็บเป็น local cache และถูกกันออกจาก Git เพื่อไม่ทำให้ repository โต รวมทั้งลดความเสี่ยงเรื่องสิทธิ์เผยแพร่ซ้ำ ส่วน metadata, ลิงก์ต้นทาง และ checksum ถูกเก็บใน Git เพื่อให้ตรวจสอบย้อนกลับได้

## การดาวน์โหลดและตรวจสอบ

```bash
python3 research/evidence-library/update_research_library.py sync
python3 research/evidence-library/update_research_library.py verify
python3 research/evidence-library/update_research_library.py status
```

- `sync` ดาวน์โหลดเฉพาะรายการ `downloadable` จาก URL ที่อนุมัติ ใช้ไฟล์ชั่วคราวและย้ายแบบ atomic
- ทุกไฟล์ต้องขึ้นต้นด้วย `%PDF-` มีขนาดสมเหตุผล และ SHA-256 ตรงกับทะเบียน
- ถ้าเจ้าของแหล่งข้อมูลเปลี่ยนไฟล์ upstream จน checksum ไม่ตรง ระบบจะหยุด ไม่ยอมรับฉบับใหม่อัตโนมัติ ต้องตรวจเนื้อหา/เวอร์ชันและแก้ทะเบียนผ่าน code review
- เอกสารที่มีข้อจำกัดด้านลิขสิทธิ์ เช่น AASM Scoring Manual บันทึกเป็น `link-only` เท่านั้น

## หลักการเลือกหลักฐาน

1. ใช้มาตรฐาน/แนวทางจากหน่วยงานเจ้าของเรื่องก่อน เช่น WHO และ AASM
2. ใช้งานวิจัย peer-reviewed ที่มี DOI/PMID/PMCID และดาวน์โหลดจากคลังทางการหรือ Open Access
3. ใช้เอกสารผู้ผลิตเพื่ออธิบายพฤติกรรมทางเทคนิคของเซนเซอร์เท่านั้น ไม่ใช้แทนหลักฐานสุขภาพ
4. แยก “ข้อเท็จจริงจากหลักฐาน” ออกจาก “ข้ออนุมานเฉพาะ ZEEP” และระบุข้อจำกัดทุกครั้ง
5. ZEEP แสดงผลเป็นการประเมินเชิง wellness/research ไม่ใช่ผล PSG และไม่ใช้วินิจฉัยหรือรักษาโรค

## รอบทบทวน

- หน้าเว็บที่เปลี่ยนตามเวลา เช่น WHO Tobacco, WHO Data และ AASM Emerging Technology: ตรวจทุก **3 เดือน**
- แนวทาง/มาตรฐาน: ตรวจปีละครั้งและเมื่อผู้เผยแพร่ประกาศฉบับใหม่
- งานวิจัยหลักและ vendor datasheet: ตรวจเมื่อเปลี่ยน hardware, firmware, algorithm หรือก่อน pilot/release สำคัญ
- ทุกครั้งที่ทบทวนให้แก้ `checked_on`, สรุปการเปลี่ยนแปลง และ tests ที่ได้รับผลกระทบใน pull request เดียวกัน

## ข้อจำกัดสำคัญ

- AASM sleep stage แบบ W/N1/N2/N3/REM อาศัย PSG/EEG/EOG/EMG; BCG + HR + RR ของ ZEEP เป็น estimator ที่ต้องผ่าน validation กับ PSG จึงจะกล่าวอ้างความแม่นยำเชิงคลินิกได้
- SGP40 เป็นเซนเซอร์ VOC แบบกว้างพร้อม adaptive baseline จึงบอกทิศทาง/เหตุการณ์ VOC ได้ แต่ระบุชนิดสารหรือแหล่งกำเนิด เช่น บุหรี่ น้ำหอม หรือแอลกอฮอล์ โดยลำพังไม่ได้
- WHO guideline ระยะยาวบางฉบับไม่ใช่ alarm threshold แบบ real-time ภายในตู้ การนำไปตั้ง safety policy ต้องมีการทบทวนทางวิศวกรรมและสุขภาพโดยเฉพาะ
