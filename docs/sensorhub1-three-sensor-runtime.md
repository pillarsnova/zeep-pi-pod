# ESP32 Sensor Hub 1 — Three-Sensor Runtime

สถานะ: Archived firmware candidate · 2026-09-10
งาน Firmware ทดแทนถูกยกเลิกและห้าม Flash; รายละเอียด DSP/CEM ด้านล่างเป็น
Audit history เท่านั้น Runtime ปัจจุบันของ Pi รับ `sound_dba` จาก ESP32 โดยตรง
ตาม [Sensor Interface Contract v1.2](zeep-sensor-interface-contract-v1.2.md)
ขอบเขต: ESP32-S3 หนึ่งบอร์ด, Sensor 3 ตัว, USB Serial ไปยัง Raspberry Pi 5

## หน้าที่ของระบบ

Sensor Hub 1 อ่านและตรวจสุขภาพอุปกรณ์สามตัวโดยอิสระ:

| Sensor | ค่าที่วัด | Bus | Released contract |
| --- | --- | --- | --- |
| SHT3x-DIS | อุณหภูมิ, ความชื้นสัมพัทธ์ | I²C | SDA GPIO 8, SCL GPIO 9, `0x45` |
| OPT3001 | ความสว่าง | I²C | SDA GPIO 8, SCL GPIO 9, `0x44` |
| SPH0645LM4H-B | ระดับเสียง `sound_dba` จาก ESP32 | I²S | BCLK 11, WS 12, DOUT 13, LEFT slot |

GPIO และ address เป็นสัญญาการประกอบ ไม่ใช่ระบบ auto-detect หาก SHT3x กับ
OPT3001 ถูกตั้ง address ชนกัน Firmware ต้องรายงานผิดพลาดและให้แก้ Harness
ห้ามสลับ address ให้อัตโนมัติจนดูเหมือนประกอบถูก

## สิ่งที่ต้องเตรียมบน Hardware

- จ่ายไฟ `3.3 V` และ Ground ร่วมให้ Sensor ทั้งสามตัว พร้อม capacitor
  decoupling `100 nF` ใกล้ขาไฟของแต่ละตัว
- I²C ใช้ pull-up เพียงหนึ่งชุดที่มีค่ารวมเหมาะกับสายจริง; ต้องตรวจ pull-up ที่ติดมา
  บน breakout ทั้งสองแผงเพื่อไม่ให้ค่ารวมต่ำเกินไป
- กำหนด SHT3x `ADDR=HIGH` เป็น `0x45` และ OPT3001 `ADDR=GND` เป็น `0x44`;
  ขาเลือก address ห้ามลอย
- กำหนด SPH0645 `SELECT=LOW` ให้ส่ง LEFT slot; BCLK, WS และ DOUT ต้องตรวจ
  continuity ตาม GPIO ที่ปล่อยใช้งาน และใส่ pull-down `100 kΩ` ที่ DOUT ฝั่งรับ
  เพื่อให้ idle state ไม่ลอย
- สาย I²S ต้องสั้น มีทาง Ground return ที่ดี และอยู่ห่างสายมอเตอร์/คอมเพรสเซอร์;
  การเห็นข้อมูลเปลี่ยนใน Serial อย่างเดียวไม่ถือว่าผ่าน ต้องเห็น signed PCM ตอบสนองต่อเสียง

## โครงสร้างซอฟต์แวร์

| Module | ความรับผิดชอบ |
| --- | --- |
| `src/main.cpp` | เริ่ม Serial/Sensor และเรียก scheduler เท่านั้น |
| `src/environment_sensors.cpp` | อ่าน ตรวจ CRC/identity เก็บ cache และกู้คืน SHT3x/OPT3001 |
| `src/audio_meter.cpp` | Candidate เก่าที่เคยรับ signed PCM และคำนวณ LAeq(A); ไม่ใช่ Production runtime |
| `src/telemetry_publisher.cpp` | รวม snapshot โดยไม่ผูกอายุของ Sensor เข้าด้วยกัน และส่ง JSON ทุก 10 วินาที |
| `zeep_pod/hardware/sensorhub1.py` | รับ JSONL บน Pi กรอง control packet รักษาค่าล่าสุด และส่งสถานะราย Sensor |
| `sensor_contracts.py` | สัญญา schema, ช่วงค่าที่รับได้ และ legacy migration |
| `sensor_runtime.py` | รับ `sound_dba` โดยตรงและสร้าง Environment view เดียวให้ทุกส่วนใช้ตรงกัน |

ค่าดิบยังแยกจากค่าที่ผ่าน calibration เสมอ Firmware ไม่แก้ bias ของ
อุณหภูมิ/ความชื้น/แสงเอง ส่วน Pi เป็นเจ้าของ calibration ที่มี version และ
provenance เพื่อให้ย้อนตรวจได้

## ลำดับการทำงาน

1. เปิด USB Serial ที่ 115200 baud และสร้าง `boot_id` ใหม่ทุกครั้งที่บูต
2. เริ่ม I²C แล้วตรวจ SHT3x ที่ `0x45`; ค่าจะใช้ได้ต่อเมื่ออ่านครบ 6 bytes และ
   CRC ของอุณหภูมิ/ความชื้นผ่านทั้งคู่
3. ตรวจ OPT3001 ที่ `0x44` ด้วย Manufacturer ID `0x5449`, Device ID `0x3001`
   และอ่าน configuration กลับมายืนยัน
4. เริ่ม I²S ที่ 48 kHz, 32-bit slot และ task ประมวลผล SPH0645
5. ส่ง `boot` inventory หนึ่งครั้ง แล้วส่ง `environment` snapshot แรกทันที
6. SHT3x และ OPT3001 ถูกอ่านทุก 2 วินาทีเพื่อสร้าง cache สด โดยไม่รอเสียง
7. SPH0645 สะสม 480,000 samples เป็นหน้าต่าง LAeq(A) 10 วินาที
8. ส่ง Telemetry รวมทุก 10 วินาที พร้อม `sequence`, `monotonic_ms`, ค่า,
   อายุข้อมูล, สถานะ และเหตุผลแยกราย Sensor
9. Pi รับเฉพาะ `event=environment` จาก `hub_id=sensorhub1`; `boot`, `info`
   และ `calibration_response` ไม่ทับค่าปัจจุบัน
10. Pi รับทุก packet ที่มี `sound_dba` ถูกชนิด เป็น finite และอยู่ในช่วง
    30–130 dBA โดยตรง ไม่ใช้ `boot_id`, sequence, profile, weighting, metric,
    CEM approval หรือจำนวน packet เป็น gate ของค่าระดับเสียง
11. Pi ถือ Hub ว่า stale หลัง 25 วินาที เพื่อเผื่อสอง packet ที่หายและ USB jitter

## Fault isolation และ recovery

- Sensor ตัวหนึ่งเสีย: ค่าของตัวนั้นเป็น `null`, `status=invalid/recovering`
  และมี `reason`; อีกสองตัวยังส่งค่าตามปกติ
- SHT3x หรือ OPT3001 ผิดพลาด 3 ครั้งติดกัน: หยุดใช้ค่าเดิมและ re-probe ตัวนั้น
  ทุก 10 วินาที
- Reset I²C bus เฉพาะเมื่ออุปกรณ์ I²C ทั้งสองตัวใช้งานไม่ได้ และจำกัดไม่เกิน
  หนึ่งครั้งต่อ 30 วินาที เพื่อไม่รบกวน Sensor ที่ยังดี
- ค่า Environment เก่ากว่า 6 วินาทีเป็น stale และไม่ถูกส่งเป็นค่าปัจจุบัน
- Pi รับ `sound_dba` เมื่อเป็น finite และอยู่ในช่วง 30–130 dBA; validation
  ภายใน Firmware ด้านบนไม่มีอำนาจเป็น Runtime gate ฝั่ง Pi
- ค่า dBFS เป็นข้อมูลวิศวกรรมแบบ signed เท่านั้น ห้าม `abs()`, clamp หรือแสดง
  เป็น dBA

สถานะรวมของ Hub:

- `live`: Sensor ใช้งานได้ครบ 3/3
- `degraded`: ยังมีอย่างน้อย 1 ตัวใช้งานได้
- `fault`: ไม่มี Sensor ตัวใดให้ค่าที่ใช้ได้

สถานะรวมมีไว้สรุปเท่านั้น การตัดสินใช้งานค่าต้องดูสถานะราย Sensor เสมอ

## Telemetry contract

รูปแบบหลักคือ `zeep.sensor.telemetry` v1.0:

```json
{
  "schema": "zeep.sensor.telemetry",
  "version": "1.0",
  "event": "environment",
  "hub_id": "sensorhub1",
  "sequence": 42,
  "publish_period_ms": 10000,
  "hub_status": "degraded",
  "sensors": {
    "sht3x_dis": {
      "status": "live",
      "reason": "ok",
      "age_ms": 120,
      "values": {"temperature_c": 24.3, "humidity_rh": 51.2}
    },
    "opt3001": {
      "status": "live",
      "reason": "ok",
      "age_ms": 95,
      "values": {"lux": 0.3}
    },
    "sph0645": {
      "status": "invalid",
      "reason": "digital_silence",
      "age_ms": 20,
      "values": {"sound_dba": null, "sound_dbfs": -68.0}
    }
  }
}
```

Firmware ยังส่ง flat fields เดิมควบคู่ระหว่างช่วง migration แต่ nested
`sensors` คือแหล่งข้อมูล authoritative ของ packet canonical

## Historical candidate acceptance (ยกเลิกแล้ว)

รายการด้านล่างเก็บเป็น Audit history ของ Candidate เท่านั้น สคริปต์ Flash ถูก
ปิดถาวรและห้ามนำรายการนี้ไปใช้เป็นสิทธิ์ติดตั้ง Production:

1. ตรวจไฟ 3.3 V, common ground, decoupling 100 nF และ continuity ของ GPIO
2. ยืนยัน I²C address สองตัวไม่ชนกัน และ identity/config ของ OPT3001 ถูกต้อง
3. SHT3x อ่านค่าได้ต่อเนื่องพร้อม CRC ผ่าน
4. OPT3001 ตอบสนองต่อ dark/light test และไม่ overflow
5. SPH0645 มี BCLK/WS/DOUT ถูกต้อง, SEL ไม่ลอย และ signed PCM ตอบสนองต่อเสียง
6. ทดสอบทั้ง 8 กรณีของ Sensor 3 ตัว (ดี/เสียทุก combination) แล้วตัวที่เหลือ
   ต้องยังรายงานได้
7. Burn-in พร้อมกัน 30 นาที ไม่มี reboot, task stall หรือ bus lock
8. เทียบ SHT3x/OPT3001 กับเครื่องอ้างอิงตาม protocol ที่อนุมัติ
9. เคยกำหนดให้เทียบเสียงกับ CEM DT-8852 หลายระดับ; ขั้นตอน offset นี้ถูกยกเลิก
10. สำรอง Flash เดิมและยืนยันว่า Pod ไม่มีผู้ใช้งานก่อนติดตั้ง

ขณะจัดทำเอกสารนี้ Software build และ fault-combination contract tests ผ่านแล้ว
Candidate นี้ไม่ใช่ Production release และจะไม่ถูก Flash; Runtime ของ Pi ใช้
`sound_dba` ที่ Firmware ปัจจุบันส่งมาโดยตรงตาม validation ขั้นต่ำข้างต้น

## แหล่งข้อมูลหลัก

- [SHT3x-DIS datasheet](https://sensirion.com/media/documents/213E6A3B/63A5A569/Datasheet_SHT3x_DIS.pdf)
- [OPT3001 datasheet](https://www.ti.com/lit/ds/symlink/opt3001.pdf)
- [SPH0645LM4H-B datasheet](https://www.knowles.com/docs/default-source/model-downloads/sph0645lm4h-b-datasheet-rev-c.pdf)
- [ESP32-S3 I²C](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-reference/peripherals/i2c.html)
- [ESP32-S3 I²S](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-reference/peripherals/i2s.html)
