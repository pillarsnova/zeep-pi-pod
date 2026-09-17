# Sensor Hub 1 original-firmware compatibility baseline

> Status: **Production baseline restored; replacement candidate under iterative test**
> Captured: 2026-09-17 (Asia/Bangkok)  
> Scope: ESP32-S3 Sensor Hub 1 on ZEEP Pod 01

## Decision

การพัฒนาต้องยึด Datasheet, Technical Reference Manual, errata และ application
note ของผู้ผลิตเป็นหลัก Firmware เดิมใช้เป็นหลักฐานของการต่อบอร์ดและพฤติกรรม
Production เท่านั้น ไม่ใช่มาตรฐานที่ต้องคัดลอกทั้งหมด

## Evidence hierarchy

1. **Authoritative specification:** Datasheet/TRM/errata จากผู้ผลิต
2. **Board-specific truth:** schematic, BOM, strap/address wiring และการวัดบนบอร์ดจริง
3. **Compatibility evidence:** packet และพฤติกรรมของ Firmware เดิม
4. **Implementation:** source/test ของ ZEEP รุ่นใหม่ ต้องอธิบายความสอดคล้องกับข้อ 1–3

หากข้อมูลขัดกัน ให้ Datasheet ตัดสิน electrical/protocol limits ส่วน address และ
GPIO ที่เลือกได้ต้องตัดสินจาก schematic/การวัดบอร์ดจริง ค่า calibration ภาคสนาม
ใช้ได้เมื่อมีเครื่องมือ วิธีทดสอบ วันที่ และ artifact checksum ตรวจย้อนกลับได้เท่านั้น

Official sources ที่ใช้กับชุดนี้:

- [ESP32-S3 Series Datasheet](https://documentation.espressif.com/esp32_s3_datasheet_en.pdf)
- [ESP32-S3 Hardware Design Guidelines](https://docs.espressif.com/projects/esp-hardware-design-guidelines/en/latest/esp32s3/)
- [Knowles SPH0645LM4H-B Datasheet](https://www.knowles.com/docs/default-source/model-downloads/sph0645lm4h-b-datasheet-rev-c.pdf)
- [Sensirion SHT3x-DIS Datasheet](https://sensirion.com/media/documents/213E6A3B/63A5A569/Datasheet_SHT3x_DIS.pdf)
- [TI OPT3001 Datasheet and product documentation](https://www.ti.com/product/OPT3001)

การเพิ่ม DSP ต้องเป็นแบบ **additive** ต่อ measurement pipeline ที่พิสูจน์แล้ว
และต้องเปลี่ยนทีละชั้นเพื่อระบุผลกระทบได้ ห้ามเปลี่ยน bootloader, partition,
sensor driver, sound formula และ DSP พร้อมกันในรอบเดียว

Firmware `sensorhub1-dsp-shadow-v0.2.0` และ v0.3.0–v0.3.4 ไม่ผ่าน Production
parity และถูก rollback เป็น Full Flash เดิมที่ตรวจ digest ตรงแล้ว การ Flash
ทดสอบเป็นส่วนหนึ่งของ workflow ได้เมื่อ owner อนุมัติและมี rollback พร้อม

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
| Embedded sound offset | Firmware เดิมส่ง `111.93 dB` และคำนวณ `sound_dba = sound_dbfs_a + 111.93`; ที่มาของเลขนี้ยังไม่มี calibration record ยืนยัน |
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
| Calibration | embedded offset 111.93 dB (provenance ยังไม่ยืนยัน) | datasheet offset `94 - (-26) = 120 dB` + CEM residual ใน NVS | แสดง ~88 dBA และ invalid |
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
8. ระหว่าง iterative test ให้เขียนเฉพาะส่วนที่จำเป็น; ถ้าเปลี่ยน bootloader หรือ
   partition ต้องบันทึกเหตุผลและมี Full-Flash rollback โดยไม่เขียน NVS/FFat ทับ
9. Flash บนบอร์ดที่ owner อนุมัติ แล้วเทียบ CEM และ Sensor ทั้งสามจากผลจริง

## ลำดับตรวจเพื่อพัฒนาและรับรองผล

Production Flash ใช้เก็บหลักฐานจริงได้ก่อน CEM เมื่อ owner อนุมัติ ส่วนรายการ
ต่อไปนี้ต้องครบก่อนประกาศเป็น Firmware ใช้งานถาวรหรืออ้างว่า dBA calibrated:

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

## Production state ล่าสุด

- ติดตั้ง `sensorhub1-smart-ear-v0.5.3-debug` เฉพาะ app partition และ verify
  digest สำเร็จ; NVS, partition table และ FFat ไม่ถูกเขียนทับ
- Pi service: active และ Sensor ทั้งสามส่งสถานะแยกกันตาม contract
- SPH0645: `sound_valid=true`, zero ratio `0`, repeated ratio ประมาณ `1.2–1.3%`,
  raw change ประมาณ `98.7%`, clip/read error `0/0`
- ตัวอย่างหลังแก้ A-weighting 32 kHz: `sound_dba=63.55–63.76 dBA est.` ตามสูตร
  datasheet `dBFS(A) + 120`; ยังต้องเทียบ CEM ในสภาพเดียวกันเพื่อหา residual
  calibration และห้ามเรียกค่าปัจจุบันว่า calibrated
- Full Flash เดิมยังเก็บเป็น Golden rollback และ digest ไม่เปลี่ยน

## Production experiment log · 2026-09-17

| รุ่น | สิ่งที่ทดลอง | ผล Hardware |
| --- | --- | --- |
| v0.3.0 | 18-bit extraction `>>14` | invalid; alignment error ทุก sample |
| v0.3.1 | full 24-bit transport `>>8` | invalid; zero ~48%, repeated ~99% |
| v0.3.2 | RIGHT slot | ไม่มีสัญญาณ; non-finite |
| v0.3.3 | LEFT word จาก explicit stereo frame | invalid; zero ~45%, repeated ~99% |
| v0.3.4 | LEFT + ESP32-S3 SD timing delay | invalid; pattern ไม่เปลี่ยน |
| v0.4.1 | ESP-IDF channel API, 32 kHz, LEFT mono | register ตรง Golden แต่ PCM ยังอ่าน clock/data ผิดเพราะ pin role สลับ |
| v0.4.2–v0.5.1 | ทดลอง width, slot, timing และ pinned runtime พร้อม raw probe | ตัดสมมติฐาน bit shift/runtime; พบ zero ~48% และ repeated ~99% เหมือนเดิม |
| v0.5.2 | เทียบ live GPIO matrix กับ Golden แล้วแก้ `DATA=11`, `BCLK=12`, `WS=13` | PCM กลับมาปกติทันที; zero 0%, change ~98.7%, error 0 |
| v0.5.3-debug | A-weighting 32 kHz + QA gate + DSP/debug telemetry ครบ | Production live; 3 packet ตรวจผ่าน, Sensor ทั้งสาม live |

ข้อสรุป: SPH0645 ไม่เสีย ต้นเหตุคือเอกสารเดิมระบุเพียงชุด GPIO `11/12/13`
แต่ผูกบทบาทสัญญาณผิด การอ่าน live GPIO matrix จาก Golden Firmware พิสูจน์ mapping
จริงเป็น `DATA=11`, `BCLK=12`, `WS=13` เมื่อแก้ mapping โดยไม่เพิ่ม timing hack
สัญญาณกลับมามีสุขภาพเทียบ Golden และ DSP tap ทำงานแบบ additive ได้
