# Sensor Hub 1 pre-install status

Updated: 2026-09-09 (Asia/Bangkok)

| Gate | Status | Evidence |
| --- | --- | --- |
| GPIO contract | PASS | SPH0645 `11/12/13`; I²C `8/9` in `board_config.h` |
| Target identity | PASS | ESP32-S3 rev 0.2, Flash 16 MB, OPI PSRAM 8 MB |
| Golden full-Flash backup | PASS | 16,777,216 bytes; read-back verification passed |
| Golden backup SHA-256 | PASS | `e05a7f648d5873467d55f88518824db8baa9eb86f0e862d1e13c8085604c68a1` |
| Release compile | PASS | PlatformIO `release`, ESP32-S3 N16R8 |
| DSP/contract/calibration unit tests | PASS | 7 tests |
| Artifact checksum | PASS | 4/4 Flash artifacts verified |
| CEM DT-8852 physical multi-level test | **PENDING** | ต้องเก็บ 35/45/55/65 dBA จริง |
| Production Flash/install | **BLOCKED** | ปลด gate เมื่อ CEM result เป็น PASS เท่านั้น |

Golden backup อยู่บน Pod ที่:

```text
/home/pod1/firmware-backups/sensorhub1/20260909-pre-sph0645-laeq/
```

`zeep-pod.service` ถูกเปิดคืนและตรวจว่า active หลังสำรองเรียบร้อยแล้ว
Firmware candidate ยังไม่ถูกติดตั้งบน Sensor Hub Production
