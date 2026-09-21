# ZEEP Sensor Interface Contract v1.2

สถานะ: Approved runtime contract · ทบทวน 2026-09-19
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
        "sound_dbfs": -65.2,
        "sound_class": "steady_equipment_like",
        "sound_class_state": "provisional",
        "sound_class_confidence": 0.81,
        "sound_event_detected": true,
        "sound_classifier_version": "zeep-dsp-rule-v0.1-shadow",
        "sound_window_sequence": 42,
        "sound_features": {
          "low_ratio": 0.61,
          "mid_ratio": 0.31,
          "high_ratio": 0.08,
          "spectral_centroid_hz": 412.0,
          "spectral_flatness": 0.12,
          "spectral_flux": 0.04,
          "crest_factor": 3.1,
          "syllabic_modulation": 0.08,
          "breathing_periodicity": 0.11,
          "breathing_period_s": null
        }
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

`temperature_c` และ `humidity_rh` ใน Packet เป็นค่าต้นทางจาก SHT3x-DIS
Pi เก็บไว้ใน `raw_values` ก่อนสร้าง canonical environment นโยบายปัจจุบันใน
[`calibration.json`](../calibration.json) คือ direct passthrough: อุณหภูมิและ
ความชื้นใช้ Bias `0.0` จึงแสดงค่าจาก SHT3x-DIS โดยตรง การเทียบหนึ่งจุดเมื่อ
4 กันยายน 2569 เก็บเป็นประวัติ QA เท่านั้นและไม่ถูกนำมาใช้ ห้ามเขียนค่าใดกลับไป
ทับ Raw; deployment อาจกำหนด `HUMIDITY_RH_BIAS` เฉพาะ Pod ได้ต่อเมื่อมีการ
สอบเทียบใหม่ที่อนุมัติและบันทึก provenance โดย env มี precedence

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

## Optional Acoustic DSP Shadow Extension

Firmware ที่เปิดใช้ DSP shadow อาจส่ง `sound_class`, state, confidence, event flag,
classifier version, window sequence และ feature scalars ตามตัวอย่างด้านบนได้ โดย
Pi รับเฉพาะ positive allowlist และตัด field อื่นทิ้ง ป้ายที่ยอมรับใน candidate นี้คือ
`quiet`, `steady_equipment_like`, `speech_like`, `snore_like`, `impact_like` และ
`unknown`; ค่าเหล่านี้เป็น **ป้ายชั่วคราวสำหรับ Admin** ไม่ใช่การยืนยันแหล่งเสียง
หรือการวินิจฉัยสุขภาพ

ระบบไม่ส่งหรือเก็บ PCM/Raw audio, ไม่ถอดคำพูด และ DSP shadow ต้องไม่เปลี่ยน
Sleep State, Sleep Score, Recovery Score หรือสั่ง Control อัตโนมัติ หาก feature
หรือ classifier หาย ค่า temperature/humidity/lux และ `sound_dba` ต้องทำงานต่อได้
ตามปกติ ป้ายจะเปลี่ยนเป็น `not_evaluated` โดยไม่สร้าง label จาก dBA เพียงค่าเดียว

มีหลักฐาน DSP telemetry บน Pod 1 ตาม [Current Status](current-status.md)
และ Hardware Audit แต่ build ผ่านเพียงอย่างเดียวไม่ยืนยันการติดตั้งทุกเครื่อง
การ Flash เป็นขั้นตอนของ physical validation ได้เมื่อมี owner
approval, Pod ว่าง, backup/rollback และ board identity ส่วน privacy/consent,
field comparison และ CEM ใช้ตัดสินการรับรองหลังเก็บผลจริง

## Firmware และการสอบเทียบ

ขั้นตอน I²S, A-weighting, 32 kHz, reference `94 - (-26) = 120 dB`,
CEM residual offset และ backup/Flash อยู่ใน
[Firmware Guide](../firmware/sensorhub1-esp32s3/README.md) เพียงแหล่งเดียว
เอกสารนี้กำหนดขอบเขต packet ที่ Pi รับ ไม่ทำสำเนาสูตร/QA ของ candidate ที่ยกเลิก

## สาเหตุ Invalid ของ Pi Runtime

- `missing_sound_dba` — ไม่มี field `sound_dba`
- `legacy_dbfs_only` — มีเฉพาะ dBFS ซึ่งใช้แทน dBA ไม่ได้
- `invalid_sound_dba_type` — field ไม่ใช่ JSON number
- `non_finite_sound_dba` — ค่าเป็น NaN หรือ infinity
- `sound_dba_out_of_range` — ค่านอกช่วง 30–130 dBA

## Reference

- Knowles SPH0645LM4H-B datasheet: digital sensitivity และ I2S format
  <https://www.knowles.com/docs/default-source/model-downloads/sph0645lm4h-b-datasheet-rev-c.pdf>
- Espressif I2S Programming Guide: driver/slot configurationของ ESP32
  <https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-reference/peripherals/i2s.html>
- CEM DT-8852 field protocol ใช้ A/SLOW และช่วง 30–130 dBA ตาม Firmware Guide;
  observation รุ่นเก่าตรวจสอบได้จาก Git history และไม่ใช่ runtime input
- `ikostoski/esp32-i2s-slm` ใช้ศึกษา architecture A/C weighting และ Leq เท่านั้น;
  เป็น GPL-3.0 จึงห้ามคัดลอกเข้า Firmware ปิดของ ZEEP โดยไม่ผ่าน license review
  <https://github.com/ikostoski/esp32-i2s-slm>
