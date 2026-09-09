# ZEEP Sensor Interface Contract v1.2

สถานะ: Approved runtime contract · 2026-09-10
ขอบเขต: ESP32 Sensor Hub 1 → Pi5 ผ่าน USB Serial JSONL @ 115200 baud

## หลักการ

ESP32 เป็นเจ้าของการอ่านและประมวลผล SPH0645LM4H-B แล้วส่งค่าปฏิบัติการใน
field `sound_dba` ส่วน Pi เชื่อค่าที่ส่งมาโดยตรงและคัดลอกเข้า field ภายใน
`sound_dba_est` โดยไม่ทำ `abs()`, bias, offset, recalibration หรือคำนวณซ้ำ
Pi ไม่มี CEM gate, LAeq metadata gate, firmware-profile gate หรือเงื่อนไขรอ
3 packet อีกต่อไป ผลเทียบ CEM และข้อมูล Firmware รุ่นก่อนเป็น QA history เท่านั้น

## Packet ที่ Pi ยอมรับ

```json
{
  "event": "environment",
  "source": "sensorhub1_firmware",
  "hub_id": "sensorhub1",
  "firmware_version": "sensorhub1-integrated-v2.0.0-rc1",
  "sequence": 42,
  "publish_period_ms": 10000,
  "hub_status": "live",
  "sensors": {
    "sht3x_dis": {
      "status": "live",
      "reason": "ok",
      "values": {"temperature_c": 24.3, "humidity_rh": 51.2}
    },
    "opt3001": {
      "status": "live",
      "reason": "ok",
      "values": {"lux": 0.3}
    },
    "sph0645": {
      "status": "live",
      "reason": "ok",
      "values": {
        "sound_dba": 39.8,
        "sound_dbfs": -65.2
      }
    }
  }
}
```

Pi จะรับเฉพาะ `event=environment` ที่ระบุ `hub_id=sensorhub1`; ข้อความ `boot`,
`INFO` และ `calibration_response` จะถูกบันทึกเป็น Control-plane event โดยไม่ทับ
ค่าปัจจุบันของ SHT3x-DIS, OPT3001 หรือ SPH0645 ส่วน packet ผิดรูปแบบจะถูกปฏิเสธ
เฉพาะ packet นั้นโดยไม่ตัดการเชื่อมต่อ USB Serial ที่ยังทำงานปกติ
สถานะของทั้งสาม Sensor แยกจากกัน ดังนั้น SPH0645 ผิดพลาดต้องไม่ทำให้ค่า
SHT3x-DIS หรือ OPT3001 หาย และในทางกลับกัน

ช่วง Rollback เท่านั้น Pi ยังรับ flat packet ที่ไม่มี `event` เมื่อพบ field ของ
Hub 1 ใน allowlist ชัดเจน เช่น `temperature_c`, `humidity_rh` หรือ `lux` ส่วน
เสียงต้องมี `sound_dba` จาก ESP32 เสมอ; packet ที่มี event อื่นยังถูกกันออก
ตามเดิม

`sound_dba` ใช้ได้เมื่อมี field นี้, เป็น JSON number แบบ finite และอยู่ในช่วง
30–130 dBA แบบรวมค่าขอบเท่านั้น เมื่อผ่าน Pi กำหนด
`sound_dba_est = sound_dba` โดยไม่เปลี่ยนค่า เมื่อไม่ผ่าน Pi ระบุ invalid,
ไม่ clamp และไม่ใช้ค่าก่อนหน้าเป็นค่าปัจจุบัน

`sound_dbfs` เป็น signed engineering telemetry สำหรับ Admin เท่านั้น ค่าติดลบ
เป็นเรื่องปกติและห้ามใช้ `abs(sound_dbfs)` หรือ `sound_laeq_dba` เป็น fallback
metadata รุ่นเก่า เช่น `sound_valid`, weighting, metric, window และ profile ไม่มี
อำนาจบล็อกหรืออนุมัติ `sound_dba`

## ภาคผนวกประวัติ Firmware ที่ยกเลิกแล้ว (ห้ามใช้กับ Production)

ส่วนนี้เป็นหลักฐานย้อนหลังของ Firmware candidate ที่ถูก hard-disable แล้วเท่านั้น
ห้าม Flash และห้ามนำขั้นตอนใดในส่วนนี้กลับมาเป็น Runtime gate ค่า Runtime ฝั่ง
Pi ยึด `sound_dba` ตามกติกาด้านบนเพียงเส้นทางเดียว

Firmware candidate เดิมทำงานตามลำดับนี้ก่อนสร้าง Packet:

1. อ่าน I2S ด้วย sample rate คงที่ (แนะนำ 48 kHz) และตรวจจำนวน sample จริง
2. แก้ word alignment ของ SPH0645 ตาม ESP32/ESP-IDF รุ่นที่ใช้งานจริง
3. sign-extend PCM 24-bit อย่างถูกต้อง; ห้ามใช้ absolute value กับ sample
4. ตรวจ stuck-at-zero, clipping, short read, DMA overflow และ discontinuity
5. ตัด DC component / high-pass ต่ำกว่าย่านเสียงที่วัด
6. ใช้ digital A-weighting filter ที่ตรวจ frequency response แล้ว
7. สะสม mean-square energy ของสัญญาณหลัง filter ตลอด integration window
8. แปลงเป็น LAeq ด้วย sensitivity/reference calibration ของไมโครโฟน
9. ตรวจ noise floor, acoustic overload, finite value และ sample coverage
10. ส่ง `sound_valid=true` เฉพาะเมื่อทุกข้อผ่าน; ไม่เช่นนั้นส่ง false พร้อม
    `sound_invalid_reason`

สมการแกนกลางคือ

```text
mean_square = sum(a_weighted_sample²) / valid_sample_count
LAeq = calibration_reference_dba + 10 × log10(mean_square / reference_energy)
```

ค่าคงที่อ้างอิงต้องมาจาก sensitivity ของ SPH0645 และการสอบเทียบกับแหล่งเสียง
ที่ทราบระดับ ไม่ใช่การใช้ `abs(dBFS)` ค่าชดเชย enclosure/port ให้ version และ
เก็บ provenance แยกต่อบอร์ด

## สาเหตุ Invalid ของ Pi Runtime

- `missing_sound_dba` — ไม่มี field `sound_dba`
- `legacy_dbfs_only` — มีเฉพาะ dBFS ซึ่งใช้แทน dBA ไม่ได้
- `invalid_sound_dba_type` — field ไม่ใช่ JSON number
- `non_finite_sound_dba` — ค่าเป็น NaN หรือ infinity
- `sound_dba_out_of_range` — ค่านอกช่วง 30–130 dBA

## ภาคผนวก Offline QA เดิม (ยกเลิกจาก Production flow)

รายการนี้เก็บเพื่อ Audit เท่านั้น ไม่ใช่เงื่อนไขอนุมัติ/บล็อกค่าของ Pi:

1. ทดสอบ digital silence และ quiet room: ไม่มี sign/overflow spike
2. ป้อน sine/pink noise หลายระดับและยืนยัน response เพิ่มตามระดับแบบ monotonic
3. ตรวจ A-weighting response ที่อย่างน้อย 125 Hz, 1 kHz และ 4 kHz
4. เทียบ CEM DT-8852 แบบ A/SLOW หรือ datalogging ที่ช่วง 30–80 dBA โดยวาง
   microphone ใกล้กันและเทียบหน้าต่างเวลาเดียวกัน
5. ใช้อย่างน้อย 5 ระดับ ครอบคลุม 35–70 dBA; ห้ามใช้ค่าที่ Meter ขึ้น UNDER/OVER
6. ยอมรับค่า Production หลังมี regression test, firmware version และผล field
   calibration ที่ย้อนตรวจได้

## Reference

- Knowles SPH0645LM4H-B datasheet: digital sensitivity และ I2S format
  <https://www.knowles.com/docs/default-source/model-downloads/sph0645lm4h-b-datasheet-rev-c.pdf>
- Espressif I2S Programming Guide: driver/slot configurationของ ESP32
  <https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-reference/peripherals/i2s.html>
- CEM DT-8852 field protocol and historical observations:
  [sph0645-cem-dt8852-field-calibration-2026-08-26.md](sph0645-cem-dt8852-field-calibration-2026-08-26.md)
- `ikostoski/esp32-i2s-slm` ใช้ศึกษา architecture A/C weighting และ Leq เท่านั้น;
  เป็น GPL-3.0 จึงห้ามคัดลอกเข้า Firmware ปิดของ ZEEP โดยไม่ผ่าน license review
  <https://github.com/ikostoski/esp32-i2s-slm>
