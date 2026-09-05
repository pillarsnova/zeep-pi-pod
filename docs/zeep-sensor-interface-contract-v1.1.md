# ZEEP Sensor Interface Contract v1.1

สถานะ: Approved software contract · 2026-09-06
ขอบเขต: ESP32 Sensor Hub 1 → Pi5 ผ่าน USB Serial JSONL @ 115200 baud

## หลักการ

SPH0645 ส่ง PCM แบบ I2S และรายงานระดับเชิงดิจิทัลเป็น dBFS; ค่า dBFS ไม่ใช่
dBA และห้ามแปลงด้วย `abs()`, การบวก offset แบบไม่มี reference หรือการ clamp
เพื่อทำให้ดูเหมือนค่าจริง การคำนวณ Acoustic Level เป็นหน้าที่ของ ESP32
Sensor Hub 1 ส่วน Pi ทำหน้าที่ตรวจ Contract และ fail closed เท่านั้น

## Packet ที่ Pi ยอมรับ

```json
{
  "sound_dbfs": -65.2,
  "sound_laeq_dba": 39.8,
  "sound_valid": true,
  "sound_weighting": "A",
  "sound_metric": "LAeq",
  "sound_window_ms": 10000,
  "sound_firmware_version": "sph0645-laeq-a-v1.0"
}
```

เงื่อนไขต้องผ่านพร้อมกัน:

1. `sound_valid` ต้องเป็น JSON boolean `true`
2. `sound_weighting` ต้องเป็น `A`
3. `sound_metric` ต้องเป็น `LAeq`
4. `sound_window_ms` ต้องเป็นค่าบวกและ finite; Production target คือ 10,000 ms
5. `sound_laeq_dba` ต้อง finite และอยู่ในช่วงระบบ 0–120 dBA est.

ไม่ผ่านข้อใดข้อหนึ่ง: `sound_measurement_valid=false`, SPH0645 มีสถานะ
`invalid`, Dashboard ไม่แสดงตัวเลข, Session ไม่บันทึกเสียง และ Raw ยังคงอยู่
ใน Admin เพื่อหาสาเหตุ ค่า valid ก่อนหน้าอาจแสดงเป็น
`sound_last_valid_dba` ในข้อมูล Debug แต่ห้ามใช้เป็นค่าปัจจุบัน

## Firmware processing pipeline

Firmware ต้องทำตามลำดับนี้ก่อนสร้าง Packet:

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

## สาเหตุ Invalid มาตรฐาน

- `legacy_dbfs_only` — Firmware เก่าส่ง dBFS อย่างเดียว
- `i2s_alignment_unverified` — ยังไม่ยืนยัน bit/slot alignment
- `insufficient_samples` — sample coverage ไม่ครบ integration window
- `dma_overflow` / `short_read` — stream ไม่ต่อเนื่อง
- `clipping` — sample ชน full scale มากเกินเกณฑ์
- `below_noise_floor` — ต่ำกว่าขีดความสามารถที่ยืนยันของระบบ
- `laeq_out_of_range` — ผลนอกช่วงระบบ
- `firmware_invalid` — Firmware ปฏิเสธด้วย sanity check อื่น

## Verification ก่อนเปิดใช้ Production

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
