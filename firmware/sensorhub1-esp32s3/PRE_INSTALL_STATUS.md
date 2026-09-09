# Sensor Hub 1 pre-install status

Updated: 2026-09-09 (Asia/Bangkok)

| Gate | Status | Evidence |
| --- | --- | --- |
| GPIO/address software contract | PASS | SPH0645 `11/12/13`; I²C `8/9`; SHT `0x45`; OPT `0x44` |
| Target identity | PASS | ESP32-S3 rev 0.2, Flash 16 MB, OPI PSRAM 8 MB |
| Golden full-Flash backup | PASS | 16,777,216 bytes; read-back verification passed |
| Golden backup SHA-256 | PASS | `e05a7f648d5873467d55f88518824db8baa9eb86f0e862d1e13c8085604c68a1` |
| Integrated release compile | PASS | `sensorhub1-integrated-v2.0.0-rc1`; 337,541 B, RAM 19,808 B (6.0%), Flash 5.2% |
| DSP/contract/calibration unit tests | PASS | 10 tests including all 8 three-Sensor fault combinations |
| Pi runtime tests | PASS | Full regression 363 tests passed, 1 hardware-only test skipped; Python compile passed |
| Candidate artifact checksum | PASS | 4/4 artifacts; firmware SHA-256 `265b038d73671e07ee54c2dc29faefbf6ea08d318019a295b32a8985bb116b4d` |
| Physical I²C identity/data | **PENDING** | ต้องยืนยัน SHT CRC + OPT IDs/config/dark-light บนบอร์ดจริง |
| Physical SPH0645 PCM | **BLOCKED** | DOUT/slot/SEL/electrical gate ยังไม่ผ่านบนบอร์ดจริง |
| CEM DT-8852 physical multi-level test | **PENDING** | ต้องเก็บ 35/45/55/65 dBA จริง |
| Integrated burn-in/fault isolation | **PENDING** | 30 นาที + ถอดทีละ Sensor ครบ 8 combination |
| Production Flash/install | **BLOCKED** | ปลดเมื่อ physical, burn-in และ CEM gates ผ่านทั้งหมด |

Golden backup อยู่บน Pod ที่:

```text
/home/pod1/firmware-backups/sensorhub1/20260909-pre-sph0645-laeq/
```

`zeep-pod.service` ถูกเปิดคืนและตรวจว่า active หลังสำรองเรียบร้อยแล้ว
Firmware integrated candidate ยังไม่ถูกติดตั้งบน Sensor Hub Production
