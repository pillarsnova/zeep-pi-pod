# Source Register — ฉบับย่อสำหรับทีม ZEEP

วันที่ตรวจสอบลิงก์และฉบับ: **5 กันยายน 2026**

[`source-register.json`](source-register.json) เป็นทะเบียน **authoritative** สำหรับ ID,
ชื่อเรื่อง, URL, access tier, provenance และ checksum ส่วนเอกสารนี้เป็น human-readable
view สำหรับทีม หากข้อมูลต่างกันให้ยึด JSON และแก้ Markdown ให้ตรงใน pull request เดียวกัน

Canonical JSON SHA-256: `310e95990e64877efbd66e3d44376f59395bbabf0d6807944ec012beb17ab8ae`

## 1. Sleep และการประเมินสถานะการนอน

| ID | แหล่งข้อมูล | ใช้อ้างอิงใน ZEEP | ข้อจำกัด |
|---|---|---|---|
| SLP-001 | [AASM/SRS: Recommended Amount of Sleep for a Healthy Adult](https://doi.org/10.5665/sleep.4716) | ผู้ใหญ่ควรนอนอย่างสม่ำเสมออย่างน้อย 7 ชั่วโมง; ใช้เป็นกรอบ Overnight ไม่ใช่เป้าตายตัวของ Nap | ไม่ได้กำหนด sleep score หรือใช้แทนบริบทอายุ/โหมด |
| SLP-002 | [Sleep staging from ECG and respiration with deep learning](https://doi.org/10.1093/sleep/zsz306) | ยืนยันว่า heart rhythm และ respiration มีข้อมูลที่สัมพันธ์กับ stage และควรใช้ temporal context | ผลจาก ECG/respiratory effort และโมเดลเฉพาะ ไม่ใช่ validation ของ BCG ZEEP |
| SLP-003 | [Beddit BCG validation against PSG](https://doi.org/10.5664/jcsm.7682) | เตือนเรื่อง overestimate TST, underestimate WASO และความเสี่ยง stage ผิดจาก BCG | อุปกรณ์/อัลกอริทึมคนละชุดกับ ZEEP; กลุ่มตัวอย่างเล็ก |
| SLP-004 | [EMFIT BCG validation against PSG](https://doi.org/10.5664/jcsm.9754) | รองรับ data-quality gate, Unknown และการไม่กล่าวอ้างเทียบเท่า PSG | ไม่ใช่ผลทดสอบ ZEEP; พบ data loss และ stage agreement ต่ำในอุปกรณ์ที่ศึกษา |
| SLP-005 | [Consumer Sleep Technology: An American Academy of Sleep Medicine Position Statement](https://pmc.ncbi.nlm.nih.gov/articles/PMC5940440/) | กำหนดขอบเขตว่า consumer/wellness data ไม่ใช้วินิจฉัยหรือรักษาโรคโดยไม่มี validation/การรับรอง | Full text เปิดอ่านบน PMC และ cache เป็น NCBI XML ที่ล็อก checksum; ลิขสิทธิ์ยังเป็นของ AASM และห้ามเผยแพร่ซ้ำโดยพลการ |
| SLP-006 | [AASM Scoring Manual](https://aasm.org/clinical-resources/scoring-manual/) | นิยามมาตรฐาน W/N1/N2/N3/REM และ epoch scoring สำหรับ PSG | มีลิขสิทธิ์/สิทธิ์เข้าถึง; ไม่ดาวน์โหลดหรือคัดลอกเนื้อหาเข้า repo |

## 2. Health & Wellness Guardrails

| ID | แหล่งข้อมูล | ใช้อ้างอิงใน ZEEP | ข้อจำกัด |
|---|---|---|---|
| HLT-001 | [AASM Clinical Practice Guideline for Diagnostic Testing for Adult OSA](https://doi.org/10.5664/jcsm.6506) | แยก wellness estimation ออกจากการวินิจฉัย OSA; PSG/HSAT ที่เหมาะสมเป็นเส้นทางตรวจโรค | เป็นแนวทางสำหรับแพทย์ ไม่ใช่สูตร scoring ของ ZEEP |
| HLT-002 | [WHO Global Health Observatory](https://www.who.int/data/gho) | ตรวจชุดข้อมูลสุขภาพประชากรและ metadata ที่อัปเดต | ฐานข้อมูลเปลี่ยนได้; ต้องระบุวันที่ดึง ชุดข้อมูล และประเทศทุกครั้ง |
| HLT-003 | [WHO Data](https://data.who.int/) | จุดตรวจข้อมูลสุขภาพ WHO ปัจจุบัน | `link-only`; ห้ามนำค่ามาใช้กับบุคคลโดยไม่ตรวจนิยามและประชากรอ้างอิง |

## 3. WHO — สุขภาพ ที่อยู่อาศัย อากาศ และยาสูบ

| ID | แหล่งข้อมูล | ใช้อ้างอิงใน ZEEP | ข้อจำกัด |
|---|---|---|---|
| WHO-001 | [WHO Global Air Quality Guidelines 2021](https://iris.who.int/handle/10665/345329) | กรอบสุขภาพ PM2.5/PM10, O₃, NO₂, SO₂ และ CO | ค่าเฉลี่ยตามเวลาของอากาศทั่วไป ไม่ใช่ alarm threshold 10 วินาทีใน POD โดยตรง |
| WHO-002 | [WHO Housing and Health Guidelines 2018](https://iris.who.int/handle/10665/276001) | หลักสุขภาพที่อยู่อาศัย อุณหภูมิ ความปลอดภัย และสภาพแวดล้อม | ไม่ได้ออกแบบเฉพาะ sleep pod |
| WHO-003 | [WHO Indoor Air Quality: Selected Pollutants 2010](https://iris.who.int/handle/10665/260127) | คุณสมบัติและความเสี่ยงของ benzene, formaldehyde, CO ฯลฯ | SGP40 ไม่สามารถแยกสารเหล่านี้รายตัว |
| WHO-004 | [WHO Roadmap for Good Indoor Ventilation 2021](https://iris.who.int/handle/10665/339857) | หลักตรวจ ventilation และ operational response | จัดทำในบริบท COVID-19; ต้องปรับให้เข้ากับ POD และ hardware จริง |
| WHO-005 | [WHO Methods for Sampling Indoor Chemical Pollutants 2020](https://iris.who.int/handle/10665/334389) | ออกแบบแผนเก็บตัวอย่าง/เครื่องมือยืนยัน VOC | เน้นพื้นที่สาธารณะสำหรับเด็ก; ใช้เป็นวิธีวิทยา ไม่ใช่เกณฑ์ pass/fail |
| WHO-006 | [WHO Report on the Global Tobacco Epidemic 2025](https://www.who.int/publications/b/79987) | สถานการณ์และนโยบายยาสูบฉบับรายงานล่าสุดในทะเบียน | ข้อมูลประชากร ไม่ระบุว่า VOC event รายบุคคลมาจากบุหรี่ |
| WHO-007 | [WHO Tobacco Control Playbook 2025](https://iris.who.int/handle/10665/381594) | หลัก smoke-free environment และการจัดการความเสี่ยงจากควัน | เป็นแนวนโยบาย ไม่ใช่คู่มือสอบเทียบ SGP40 |
| WHO-008 | [WHO Tobacco and Nicotine Fact Sheet](https://www.who.int/news-room/fact-sheets/detail/tobacco) | หน้าอ้างอิงปัจจุบันเรื่องผลกระทบยาสูบ/ควันมือสอง; ณ วันที่ตรวจเป็นฉบับ 26 มิ.ย. 2026 | `link-only`; ต้องตรวจวันที่หน้าเว็บก่อนอ้างทุกครั้ง |

## 4. การควบคุม VOC และแหล่งที่มากับผู้ใช้งาน

| ID | แหล่งข้อมูล | ใช้อ้างอิงใน ZEEP | ข้อจำกัด |
|---|---|---|---|
| AIR-001 | [Human transport of thirdhand tobacco smoke](https://doi.org/10.1126/sciadv.aay4109) | หลักฐานโดยตรงว่าเสื้อผ้า/ร่างกายผู้สูบบุหรี่พา VOC ยาสูบเข้าเขตปลอดบุหรี่และ off-gas ได้; พื้นที่เล็ก/ระบายไม่ดีอาจมีความเข้มข้นสูงขึ้น | ไม่ได้ใช้ SGP40 และไม่ได้พิสูจน์เหตุการณ์เฉพาะใน ZEEP |
| AIR-002 | [Emission Rates of VOCs from Humans](https://doi.org/10.1021/acs.est.1c08764) | มนุษย์ปล่อย VOC จากลมหายใจและผิว; อุณหภูมิ RH เสื้อผ้า ozone และกิจกรรมมีผล | ค่า chamber/group ไม่ใช่ baseline รายบุคคลของ POD |
| AIR-003 | [Third-hand smoke VOCs from clothing fabrics](https://doi.org/10.1007/s40201-021-00755-1) | รองรับการคงอยู่/off-gassing ของสารจากเสื้อผ้าหลังสัมผัสควัน และความต่างตามชนิดผ้า | การทดลองควบคุมกับผ้า ไม่ใช่การตรวจผู้ใช้งานจริง |
| AIR-004 | [Breath VOC biomarkers for active/passive smoking](https://pubmed.ncbi.nlm.nih.gov/12117646/) | ชี้ว่าหลังสัมผัส/สูบบุหรี่ VOC ในลมหายใจอาจมีองค์ประกอบที่ลดเร็วและช้า | `link-only`; biomarker เฉพาะต้องใช้เครื่องมือจำแนกสาร |
| AIR-005 | [Breath benzene associated with active smoking](https://pubmed.ncbi.nlm.nih.gov/10856191/) | รองรับการเพิ่มของ benzene ในลมหายใจหลังสูบบุหรี่ | `link-only`; SGP40 ไม่วัด benzene แบบจำเพาะ |
| AIR-006 | [U.S. EPA Residential Air Cleaners: Technical Summary, 3rd Edition](https://www.epa.gov/indoor-air-quality-iaq/air-cleaners-and-air-filters-home) | รองรับลำดับ source control → clean-air ventilation → filtration; อธิบายว่า activated carbon ดูดซับสารก๊าซบางกลุ่มและมีความจุจำกัด | ไม่ใช่ผลทดสอบ ZEEP; ประสิทธิภาพขึ้นกับชนิดสาร ปริมาณ media อัตราการไหล ความชื้น และความอิ่มตัว และไม่กำจัดสารทุกชนิด |

## 5. Sensor/Vendor Evidence

| ID | แหล่งข้อมูล | ใช้อ้างอิงใน ZEEP | ข้อจำกัด |
|---|---|---|---|
| VEN-001 | [Sensirion SGP40 Datasheet](https://sensirion.com/resource/datasheet/sgp40) | electrical/measurement contract, SRAW_VOC และ humidity/temperature compensation | เอกสารผู้ผลิต ไม่ใช่หลักฐานผลลัพธ์สุขภาพ |
| VEN-002 | [SGP40 VOC Index for Experts v1.1](https://sensirion.com/en/media/documents/A6D12AD4/61644979/Sensirion_Gas_Sensors_Datasheet_GAS_AN_SGP40_VOC_Index_for_Experts_D.pdf) | adaptive baseline, ความหมายของ VOC Index และการตอบสนองต่อเหตุการณ์ VOC | VOC Index เป็นสัญญาณรวม/สัมพัทธ์ ไม่ระบุชนิดสารหรือผู้ก่อเหตุ |

## ข้อสรุปที่อนุญาตให้นำไปใช้

- เป้าหมายหลักคือประเมินว่า ZEEP ventilation + Carbon Filter ลดภาระ VOC และพาค่ากลับสู่ช่วงเป้าหมายได้หรือไม่ ไม่ใช่ตรวจหาผู้สูบบุหรี่
- กล่าวได้ว่า **มีความเป็นไปได้ทางวิทยาศาสตร์** ที่คนพา VOC เข้ามากับลมหายใจ เสื้อผ้า ผิว เส้นผม ผลิตภัณฑ์ส่วนตัว หรือสารตกค้างจากควัน แล้วทำให้ค่าในพื้นที่ปิดขนาดเล็กเพิ่มขึ้น
- ยังกล่าวไม่ได้ว่า “SGP40 ตรวจพบผู้สูบบุหรี่” หรือว่า VOC spike มาจากบุหรี่แน่นอน ต้องตัดแหล่งอื่นและใช้เครื่องมือจำแนกสารเพื่อยืนยัน
- การกล่าวว่า ZEEP “รักษา VOC อยู่ในช่วงเป้าหมาย” ต้องแสดง `percent_time_in_target`, `valid_coverage_percent`, protocol และเงื่อนไข Filter/airflow; การลดลงครั้งเดียวไม่พิสูจน์ว่าเกิดจาก Carbon Filter เพียงอย่างเดียว
- ค่า ZEEP sleep stage เป็นผลประมาณเชิง wellness จนกว่าจะมีการ validation แบบ time-aligned กับ PSG ในประชากรเป้าหมาย
