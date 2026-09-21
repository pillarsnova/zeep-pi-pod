# ZEEP Sensor Hub 1 — Sound Meter และ DSP Shadow

> **PRODUCTION TEST CANDIDATE** · การ Flash คือส่วนหนึ่งของการตรวจบน Hardware
> จริง ต้องมี owner approval, Full-Flash backup และ rollback path ที่ตรวจแล้ว
> ผล CEM ใช้รับรอง calibration ภายหลัง ไม่ใช่เงื่อนไขก่อนเริ่ม Flash ทดสอบ

ทบทวน 19 กันยายน 2026: source นี้ยังใช้พัฒนาต่อ มีหลักฐานรุ่น
`sensorhub1-smart-ear-v0.5.3-debug` บน Pod 1 ใน
[Hardware Audit](../../docs/audits/pi5-esp-system-audit-2026-09-19.md)
ตรวจ version/checksum ของเครื่องเป้าหมายก่อน Flash ทุกครั้ง ไม่ใช้ชื่อไฟล์แทนหลักฐาน
ประวัติการเทียบ Firmware เดิมและแต่ละรอบทดลองอยู่ใน
[Compatibility / Experiment Record](ORIGINAL_FIRMWARE_COMPATIBILITY.md)
ไม่ใช่ขั้นตอนพัฒนาหรือ calibration policy ปัจจุบัน

Firmware นี้ใช้กับ Sensor Hub 1 ที่ต่อกับ Pi ผ่าน USB Serial เท่านั้น และไม่รวม
ระบบเล่นเพลงหรือ Control Deck

## Hardware contract under verification

| Device | Interface | Pin/address |
| --- | --- | --- |
| SPH0645LM4H-B | I²S Philips, LEFT | DATA GPIO 11, BCLK GPIO 12, WS GPIO 13 |
| SHT3x-DIS | I²C | SDA GPIO 8, SCL GPIO 9; ตรวจ `0x44/0x45` และยืนยันด้วย CRC |
| OPT3001 | I²C | SDA GPIO 8, SCL GPIO 9; ตรวจ `0x44–0x47` และยืนยัน TI ID |
| Pi transport | Native USB CDC JSONL | 115200 baud |

Target board ที่ตรวจจากอุปกรณ์จริงคือ ESP32-S3, Flash 16 MB, OPI PSRAM 8 MB
และ MAC `44:1b:f6:8c:0c:54` สคริปต์ Production จะปฏิเสธอุปกรณ์ที่ identity ไม่ตรง
เว้นแต่ผู้ดูแลระบุค่าที่คาดหมายใหม่โดยชัดแจ้ง

## Integrated runtime

- SHT3x-DIS และ OPT3001 poll แยกกันทุก 2 วินาที; cache สดไม่เกิน 6 วินาที
- SPH0645 Sound Meter สรุปหน้าต่าง 1 วินาทีใน FreeRTOS task แยก
- DSP สะสมหน้าต่าง 10 วินาทีโดยไม่ reset filter/หยุด Sound Meter
- Telemetry ส่งทุก 1 วินาที แม้ DSP หรือ Sensor บางตัวไม่พร้อม
- ทุก Sensor มี `status`, `reason`, `age_ms`, failure และ recovery counter แยกกัน
- Sensor หนึ่งตัวเสียแล้วอีกสองตัวต้องยังทำงาน; I²C bus reset เฉพาะเมื่ออุปกรณ์
  I²C ทั้งคู่ใช้งานไม่ได้
- Pi ถือ Hub stale หลัง 25 วินาที แต่ตัดสินค่าจริงตามสถานะราย Sensor

สัญญา field/range/validity ที่ใช้งานอยู่ดูที่
[`Sensor Interface Contract v1.2`](../../docs/zeep-sensor-interface-contract-v1.2.md)

## Sound pipeline

1. รับ SPH0645 ที่ 32 kHz/32-bit I²S slot และเลือก LEFT channel
2. ใช้ ESP-IDF Philips standard format สำหรับ one-bit delay และรับ transport
   word 24-bit ที่อยู่ใน DMA bits 31..8 ด้วย `>> 8`; แม้ SPH0645 มี acoustic
   precision 18-bit แต่ผล Production ยืนยันว่าห้ามตัดเพิ่มอีก 6 bit
3. ตัด DC และผ่าน A-weighting IIR ที่สร้างจาก analogue pole/zero definition
   ด้วย bilinear transform จากนั้น normalize ที่ 1 kHz
4. Sound Meter สะสม 32,000 samples เป็น LAeq(A) 1 วินาที
5. แปลงจาก SPH0645 sensitivity `-26 dBFS @ 94 dB SPL` ด้วยค่าชดเชย
   `94 - (-26) = +120 dB` ดังนั้น `dBA estimate = dBFS(A) + 120 +
   CEM residual offset` โดยไม่บวก peak/RMS correction `+3.0103 dB` ซ้ำ;
   ระบุผลเป็น datasheet estimate จนกว่าจะเทียบ CEM และเก็บเฉพาะ residual
   offset/สถานะใน NVS
6. DSP Tap สะสม 320,000 samples แยก 10 วินาทีแล้วคำนวณ feature โดยไม่
   เปลี่ยนหรือหน่วง Sound Meter
7. ส่ง `sound_valid=true` เฉพาะเมื่อไม่มี clipping/digital silence และค่าอยู่ใน
   reference range ของ CEM 30–130 dBA ค่า signed `sound_dbfs` คงไว้เป็น
   diagnostics และไม่ถูก `abs()` หรือใช้แทน dBA

Pi ใช้ `sound_dba` เป็นค่าระดับเสียง และรับ window metadata เป็น diagnostics
ไม่ได้ใช้ metadata เป็นเงื่อนไขแทนค่าดังกล่าว Offset ที่เก็บใน NVS เป็นการสอบเทียบ
ฝั่ง Firmware; Pi ไม่หัก Bias หรือคำนวณ dBFS ซ้ำ อ่าน validity ฝั่ง Pi จาก Contract

## DSP shadow label candidate v0.3

โมดูล `acoustic_classifier` คำนวณจากหน้าต่าง DSP แยก 10 วินาที ได้แก่
band-energy ratio, spectral centroid/flatness/flux, crest factor,
syllabic modulation 3–8 Hz และ breathing periodicity 2–6 วินาที แล้วส่งเฉพาะ:

- `sound_class` — `quiet`, `steady_equipment_like`, `speech_like`,
  `snore_like`, `impact_like` หรือ `unknown`
- `sound_class_state=provisional` และ `sound_class_confidence`
- feature เชิงตัวเลข, classifier version และ window sequence

ไม่ส่ง PCM, ไม่ถอดคำพูด, ไม่ระบุตัวบุคคล และทุก label เป็น Admin shadow เท่านั้น
ไม่เปลี่ยน Sleep State, Sleep Score, Recovery Score หรือ Control

## Build และทดสอบก่อนติดตั้ง

```bash
cd firmware/sensorhub1-esp32s3
pio run -e release
./tools/export_artifacts.sh release
python3 -m unittest discover -s test -v
```

การ build ผ่านไม่ใช่ผล validation ของป้ายเสียง ต้องตรวจ packet จริงและเก็บ
controlled dataset แยกภายหลัง

## Backup/restore ที่ตู้

ก่อนแตะ Flash ให้ Pod ว่างและ API ต้องตอบ `occupied=false`:

```bash
./tools/backup_flash.sh
```

สคริปต์จะหยุด `zeep-pod.service`, ตรวจ chip/MAC, อ่าน Flash 16 MB,
สร้าง SHA-256, รัน `verify-flash` แล้วเปิด service คืนผ่าน exit trap

Golden backup วันที่เริ่มงานนี้อยู่ที่:

```text
/home/pod1/firmware-backups/sensorhub1/20260909-pre-sph0645-laeq/
SHA256 e05a7f648d5873467d55f88518824db8baa9eb86f0e862d1e13c8085604c68a1
```

ห้ามนำ full-Flash image เข้า Git เพราะอาจมี credential จาก Firmware เดิม

## CEM bench protocol

`tools/cem_calibrate.py` รวม LAeq(A) 1 วินาทีจำนวน 10 ค่าแบบ energy average
ต่อหนึ่งคู่ CEM และผูกผลกับ SHA-256 ของ Firmware binary

ใช้บอร์ด/ไมค์ชุดทดสอบที่ wiring เดียวกับ Production และ Firmware binary เดียวกัน:

1. ตั้ง CEM เป็น A-weighting, SLOW และ range 30–130 dBA โดยหน้าจอต้องไม่ขึ้น
   `UNDER` หรือ `OVER`
2. วาง capsule ของ CEM และ SPH0645 ห่างกัน 2–5 ซม. ทิศเดียวกัน ห่างผนัง,
   ช่องแอร์, tablet และผู้ปฏิบัติงาน
3. ใช้ broadband/pink noise ที่นิ่งใกล้ 35, 45, 55 และ 65 dBA
4. เก็บอย่างน้อย 3 คู่ต่อระดับ โดยแต่ละค่า Firmware รวมจากหน้าต่าง 1 วินาที
   ต่อเนื่อง 10 ค่า
5. รันเครื่องมือ:

```bash
python3 tools/cem_calibrate.py \
  --port /dev/ttyACM0 \
  --firmware dist/release/firmware.bin \
  --output calibration-results/cem-result.json
```

เกณฑ์ PASS: reference span ≥20 dB, R² ≥0.95, slope 0.90–1.10,
median absolute error หลัง offset ≤1.5 dB และ max ≤3 dB หาก FAIL ต้องแก้
bit alignment/filter/placement ห้ามแก้ด้วย offset อย่างเดียว

เมื่อ PASS แล้วใช้ `recommended_offset_db` กับบอร์ด Production ผ่าน Serial:

```text
CAL SOUND OFFSET <ค่า>
```

แล้วทำ CEM validation ซ้ำเพื่อสร้างผล PASS ที่ผูกกับ SHA-256 ของ binary

## Production Flash workflow

ขั้นตอนและผล rollback ของ candidate รุ่นที่ยกเลิกให้ย้อนดู Git history
ไม่ใช้เป็นสถานะอุปกรณ์ปัจจุบัน การทดสอบรุ่นถัดไปต้องมี owner approval
และใช้สคริปต์ Flash/restore ในโฟลเดอร์ `tools/` ตาม artifact ที่เลือก
CEM result เป็นหลักฐานรับรอง calibration หลัง Flash ไม่ใช่เงื่อนไขก่อนทดลอง

สคริปต์ตรวจ:

- Pod ว่างและ API ยืนยันได้
- chip และ MAC ตรงกับเครื่องเป้าหมาย
- artifact checksum ผ่าน
- ผู้ดูแลตั้ง `CONFIRM_FLASH` เป็น MAC ของอุปกรณ์

ห้ามใช้ตัวอย่างคำสั่ง Flash จาก revision ก่อนหน้า เพราะ Candidate นั้นไม่ใช่
drop-in replacement ของ Firmware Production

หากต้อง rollback ให้ใช้ full-Flash backup ที่ checksum ผ่านเท่านั้น:

```bash
CONFIRM_RESTORE=44:1b:f6:8c:0c:54 \
  ./tools/restore_flash.sh /path/to/verified-backup
```

## Evidence boundary

การออกแบบเทียบแนวคิดกับ `ikostoski/esp32-i2s-slm` แต่ไม่ได้คัดลอก source
GPL-3.0 เข้ามาใน Firmware นี้ Coefficients ในระบบถูกสร้างและตรวจตอบสนองด้วย
host regression test ของโครงการเอง แหล่งข้อมูลหลักคือ
[Knowles SPH0645LM4H-B datasheet](https://www.knowles.com/docs/default-source/model-downloads/sph0645lm4h-b-datasheet-rev-c.pdf),
[Espressif ESP32-S3 I²S documentation](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-reference/peripherals/i2s.html)
และ [CEM DT-8852 product specification](https://www.cem-instruments.com/en/product-id-1294)
