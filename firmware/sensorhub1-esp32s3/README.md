# ZEEP Sensor Hub 1 — ESP32-S3 replacement firmware

Firmware นี้ใช้กับ Sensor Hub 1 ที่ต่อกับ Pi ผ่าน USB Serial เท่านั้น และไม่รวม
ระบบเล่นเพลงหรือ Control Deck

## Hardware contract

| Device | Interface | Pin/address |
| --- | --- | --- |
| SPH0645LM4H-B | I²S Philips, LEFT (`SEL=GND`) | BCLK GPIO 11, WS GPIO 12, DOUT GPIO 13 |
| SHT3x-DIS | I²C | SDA GPIO 8, SCL GPIO 9, address `0x45` |
| OPT3001 | I²C | SDA GPIO 8, SCL GPIO 9, address `0x44` |
| Pi transport | Native USB CDC JSONL | 115200 baud |

Target board ที่ตรวจจากอุปกรณ์จริงคือ ESP32-S3, Flash 16 MB, OPI PSRAM 8 MB
และ MAC `44:1b:f6:8c:0c:54` สคริปต์ Production จะปฏิเสธอุปกรณ์ที่ identity ไม่ตรง
เว้นแต่ผู้ดูแลระบุค่าที่คาดหมายใหม่โดยชัดแจ้ง

## Sound pipeline

1. รับ SPH0645 ที่ 48 kHz/32-bit I²S slot และเลือก LEFT channel
2. ใช้ ESP-IDF Philips standard format เพื่อจัด one-bit I²S delay แล้วเลื่อน
   `>> 8` เพื่อนำ 24-bit word ที่ MSB-aligned ออกจาก DMA slot
3. ตัด DC และผ่าน A-weighting IIR ที่สร้างจาก analogue pole/zero definition
   ด้วย bilinear transform จากนั้น normalize ที่ 1 kHz
4. สะสมพลังงาน 480,000 samples เป็น LAeq(A) 10 วินาที
5. แปลงจาก SPH0645 sensitivity `-26 dBFS @ 94 dB SPL` และเก็บ field
   calibration offset แยกใน NVS
6. ส่ง `sound_valid=true` เฉพาะเมื่อไม่มี clipping/digital silence และค่าอยู่ใน
   reference range ของ CEM 30–130 dBA ค่า signed `sound_dbfs` คงไว้เป็น
   diagnostics และไม่ถูก `abs()` หรือใช้แทน dBA

ค่าหลักที่ Pi ยอมรับคือ `sound_laeq_dba`, `sound_weighting=A`,
`sound_metric=LAeq`, `sound_window_ms=10000` และ `sound_valid=true`

## Build โดยยังไม่ติดตั้ง

```bash
cd firmware/sensorhub1-esp32s3
pio run -e release
./tools/export_artifacts.sh release
python3 -m unittest discover -s test -v
```

การ build ไม่ได้ให้สิทธิ์ติดตั้ง Production โดยอัตโนมัติ

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

## CEM DT-8852 acceptance test ก่อน Production install

ใช้บอร์ด/ไมค์ชุดทดสอบที่ wiring เดียวกับ Production และ Firmware binary เดียวกัน:

1. ตั้ง CEM เป็น A-weighting, SLOW และ range 30–130 dBA โดยหน้าจอต้องไม่ขึ้น
   `UNDER` หรือ `OVER`
2. วาง capsule ของ CEM และ SPH0645 ห่างกัน 2–5 ซม. ทิศเดียวกัน ห่างผนัง,
   ช่องแอร์, tablet และผู้ปฏิบัติงาน
3. ใช้ broadband/pink noise ที่นิ่งใกล้ 35, 45, 55 และ 65 dBA
4. เก็บอย่างน้อย 3 คู่ต่อระดับ โดยแต่ละค่า Firmware เป็น LAeq(A) 10 วินาที
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

## Production gate

`flash_candidate.sh` จะติดตั้งได้ต่อเมื่อ:

- Pod ว่างและ API ยืนยันได้
- chip และ MAC ตรงกับเครื่องเป้าหมาย
- artifact checksum ผ่าน
- CEM result เป็น PASS และอ้าง SHA-256 ของ `firmware.bin` เดียวกัน
- ผู้ดูแลตั้ง `CONFIRM_FLASH` เป็น MAC ของอุปกรณ์

```bash
CONFIRM_FLASH=44:1b:f6:8c:0c:54 \
  ./tools/flash_candidate.sh dist/release calibration-results/cem-result.json
```

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
