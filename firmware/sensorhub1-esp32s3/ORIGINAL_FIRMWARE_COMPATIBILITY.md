# Sensor Hub 1 original-firmware compatibility baseline

> Status: **Production baseline restored; replacement candidate blocked**  
> Captured: 2026-09-17 (Asia/Bangkok)  
> Scope: ESP32-S3 Sensor Hub 1 on ZEEP Pod 01

## Decision

การพัฒนา DSP ต้องเริ่มจากพฤติกรรมของ Firmware เดิมและเพิ่ม feature แบบ
**additive** เท่านั้น ห้ามเปลี่ยน bootloader, partition table, NVS, cadence,
สูตรเสียง หรือการอ่าน Sensor พร้อมกันในรอบเดียว

Firmware `sensorhub1-dsp-shadow-v0.2.0` ไม่ผ่าน Production parity และถูก rollback
เป็น Full Flash เดิมที่ตรวจ digest ตรงแล้ว รุ่นนี้ห้าม Flash ซ้ำจนกว่าจะผ่าน Gate
ในเอกสารนี้

## หลักฐานของ Firmware เดิม

หลักฐานมาจาก Full Flash แบบ read-only, string inventory, telemetry จริง 4 packet
และ Pi runtime หลัง restore ไม่ได้อนุมานจาก Candidate source

| หัวข้อ | Firmware เดิมที่ยืนยันได้ |
| --- | --- |
| Full Flash SHA-256 | `f1753c06f04d46276110a44cd49b84b21d7997424ed1b0dd367c7202d9644a83` |
| Build marker | `Nov 12 2025 10:16:32`, ESP-IDF `v5.5.1-710-g8410210c9a` |
| Profile | `3sensor_v3_4_1` |
| Transport | USB CDC JSONL, 115200 baud |
| Telemetry cadence | 1 packet/วินาที |
| SPH0645 | 32,000 Hz, 32,000 samples, window 1,000 ms |
| Sound output | signed dBFS + A-weighted dBFS + `sound_dba`/LAeq |
| Sound reference | `sound_dba = sound_dbfs_a + 111.93`; packet ระบุ calibrated |
| Sound QA | clip/read-error/zero/nonzero/raw-change counts และ stuck flags |
| Environment | SHT31 temperature/humidity ทำงาน; OPT3001 ระบุ unavailable ก่อนเริ่มงานนี้แล้ว |
| Safety after restore | `ready=true`, level `monitor`, ไม่มี fault |

ค่าตัวอย่างหลัง restore:

```text
temperature     27.30–27.33 °C
humidity        54.79–54.85 %RH
sound_dba       55.24–55.33 dBA est.
sound_dbfs_a   -56.69–-56.60 dBFS(A)
zero_ratio       0.000000
change_ratio     0.973562–0.974750
clip/read error  0 / 0
```

## Schema เดิมที่ต้องรักษา

Firmware รุ่นต่อไปต้องส่ง field เดิมโดยความหมายเดิมทุกตัวก่อนเพิ่ม DSP:

- identity: `schema_version`, `profile`, `event`, `seq`, `uptime_ms`
- environment: `lux`, `temperature_c`, `humidity_rh`
- sound: `sound_rms`, `sound_peak`, `sound_dbfs`, `sound_rms_a`,
  `sound_peak_a`, `sound_dbfs_a`, `sound_dba`, `sound_laeq_dba`
- calibration: `sound_dba_calibrated`, `sound_calibration_offset_db`
- acquisition: `sound_samples`, `sound_window_ms`, `sound_sample_rate_hz`
- microphone QA: `raw_clip_count`, `mic_read_errors`, `mic_zero_samples`,
  `mic_nonzero_samples`, `mic_raw_changes`, `mic_zero_ratio`,
  `mic_change_ratio`, `mic_capture_ok`, `mic_signal_valid`,
  `mic_stuck_zero`, `mic_stuck_constant`
- per-device state: `sensor_status.opt3001`, `sensor_status.sht31`,
  `sensor_status.sph0645`

DSP fields เช่น spectral flux, centroid, band ratios, modulation และ periodicity
ต้อง append เข้า packet เดิม ห้ามทำให้ field เดิมหาย เปลี่ยนหน่วย หรือช้าลง

## Flash layout เดิม

| Partition | Offset | Size |
| --- | ---: | ---: |
| NVS | `0x009000` | `0x005000` |
| OTA data | `0x00e000` | `0x002000` |
| app0 | `0x010000` | `0x300000` |
| app1 | `0x310000` | `0x300000` |
| FFat | `0x610000` | `0x9e0000` |
| coredump | `0xff0000` | `0x010000` |

Candidate เคยใช้ `default_16MB.csv` ซึ่งกำหนด app/FS คนละขนาด จึงไม่ใช่
drop-in replacement การทดลองถัดไปต้องใช้ layout เดิม และห้ามเขียน NVS/FFat
หรือ partition table โดยไม่จำเป็น

## สิ่งที่ Candidate v0.2 เปลี่ยนพร้อมกันและทำให้ไม่ผ่าน

| ด้าน | เดิม | Candidate v0.2 | ผลที่พบ |
| --- | --- | --- | --- |
| Mic rate/window | 32 kHz / 1 s | 48 kHz / 10 s | ค่าและ timing ไม่เทียบตรง |
| Calibration | reference 111.93 dB | sensitivity-derived + NVS offset | แสดง ~88 dBA และ invalid |
| PCM QA | zero/change QA ผ่าน | repeated/zero สูงผิดธรรมชาติ | `pcm_out_of_range` |
| I²C | SHT31 ทำงาน | address/probe assumption ใหม่ | SHT และ OPT ไม่ตอบทั้งคู่ |
| Serial | JSONL สะอาด | core debug เปิด | Wire error ปะปนใน JSONL |
| Partition | OTA 3 MB + FFat | default 16 MB layout | ไม่เข้ากับ Production layout |

## Compatibility-first development plan

1. เก็บ Production Firmware เดิมเป็น Golden Oracle และห้ามแก้ Raw backup
2. สร้าง Legacy Core ให้ reproduce packet เดิมที่ 32 kHz/1 วินาที
3. ยืนยัน GPIO, I²C address และ startup order จาก source เดิมหรือ bench scan;
   ห้ามใช้ datasheet default เป็นข้อสรุปแทนบอร์ดจริง
4. เทียบ signed PCM, dBFS, A-weighted dBFS, dBA และ QA counters กับ Golden
   ด้วยสัญญาณเดียวกัน
5. เพิ่ม DSP Tap แบบ read-only หลัง Legacy Core โดยไม่เปลี่ยน accumulator เดิม
6. ส่ง feature เป็น nullable additive fields; ถ้าคำนวณไม่ทันให้ packet เดิมมาก่อน
7. ปิด SDK debug บน USB JSONL (`CORE_DEBUG_LEVEL=0`)
8. Flash เฉพาะ app slot หลังผ่าน bench; ไม่เขียน partition/NVS/FFat
9. Canary บนบอร์ดทดสอบ แล้วเทียบ CEM และ Sensor ทั้งสามก่อน Production

## Promotion gates

ต้องผ่านทุกข้อก่อนเปิด Production Flash:

- Legacy packet 100%: field, type, unit และ 1-second cadence ตรง
- SHT31 parity: อุณหภูมิ/ความชื้นต่อเนื่องและ recovery ตรง
- OPT3001: fault เดิมต้องไม่ทำให้ SHT31 หรือ SPH0645 ล้ม
- SPH0645 parity: dBA ต่างจาก Golden/CEM ไม่เกินเกณฑ์ที่อนุมัติ
- PCM health: zero/change/clip/read-error ผ่านแบบเดิม
- DSP load: ไม่ทำ packet ขาด, ไม่มี watchdog/reset, ไม่มี non-JSON output
- Flash safety: partition เดิม, NVS/FFat คงเดิม, rollback digest ผ่าน
- Soak test: อย่างน้อย 2 ชั่วโมงบน bench และ 1 session จำลอง
- Admin UI: แสดง heartbeat จาก packet จริง; feature ไม่มีให้ขึ้น “กำลังรอข้อมูล”
  ไม่สร้าง animation ที่ทำให้เข้าใจว่ามี event ปลอม

## Production state หลัง rollback

- Full Flash restore: verified digest matched
- Pi service: active
- Safety Supervisor: ready / monitor
- Original SHT31 and SPH0645 telemetry: restored
- OPT3001: unavailable เหมือนก่อน Flash; แยกเป็นงานตรวจ hardware ไม่ใช่ผล DSP

