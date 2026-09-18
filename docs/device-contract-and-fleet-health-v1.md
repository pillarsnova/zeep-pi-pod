# ZEEP Device Contract และ Fleet Health v1

สถานะ: **Admin observability contract · ไม่มีสิทธิ์สั่งอุปกรณ์**  
API: `GET /api/v1/admin/fleet/health`

## เป้าหมาย

ทำให้อุปกรณ์ ESP/BCG ทุกชุดรายงานสุขภาพด้วยโครงเดียวกัน เพื่อให้ Admin เปรียบเทียบ
หลาย Pod ได้โดยไม่ผูกหน้าจอกับ payload เฉพาะ Firmware รุ่นใดรุ่นหนึ่ง

```json
{
  "schema_version": "zeep.device-health.v1",
  "pod_id": "zeep-pod-01",
  "device_id": "sensorhub2-pod1",
  "device_type": "sensor_hub",
  "board": {"model": null, "revision": null},
  "firmware": {
    "version": "zeep-sensorhub2-1.0.0",
    "sha256": null,
    "config_sha256": null
  },
  "runtime": {
    "boot_id": null,
    "sequence": 56007,
    "uptime_ms": 286260284,
    "rssi_dbm": -50,
    "free_heap": 262676
  },
  "transport": {
    "kind": "mqtt",
    "connected": true,
    "data_age_s": 4.8,
    "stale_after_s": 15
  },
  "quality": {
    "valid": true,
    "state": "live",
    "reason": "ok",
    "error": null,
    "reset_count": null,
    "packet_loss_count": null
  }
}
```

ค่า `null` หมายถึง Firmware ยังไม่ส่งหลักฐานนั้น ห้าม UI เดาหรือเติมค่าจากชื่อรุ่น
เมื่อ Firmware แต่ละ Hub เพิ่ม `board_revision`, SHA, `boot_id`, sequence และ error
counter แล้ว API เดิมจะแสดงค่าได้โดยไม่เปลี่ยน schema

## อุปกรณ์ใน Local Fleet v1

- Sensor Hub 1 — USB Serial JSONL
- Sensor Hub 2 — MQTT
- Control Hub 1 — MQTT/IR bridge
- Control Hub 2 — MQTT/bed remote bridge
- BCG LSM-800-T — USB Serial binary

Fleet response ใช้ `zeep.fleet-health.v1` และคืน `pods[]` ตั้งแต่รุ่นแรก แม้มีหนึ่ง
Pod เพื่อให้ระบบกลางรวมหลาย Pod ด้วย schema เดิมในอนาคต

## Quality semantics

- `live` — transport connected, ข้อมูลไม่ stale และไม่มี adapter error
- `unavailable/disconnected` — transport ไม่เชื่อมต่อ
- `unavailable/stale` — เคยมีข้อมูลแต่เกิน freshness limit
- `unavailable/device_error` — adapter หรือ Firmware รายงาน error

`quality.valid` เป็น health ของข้อมูล ไม่ใช่ physical confirmation ของ actuator
ACK จาก IR/servo bridge ยังไม่พิสูจน์ว่าแอร์หรือเตียงเปลี่ยนจริง

## Adaptive AI boundary

Adaptive output ทุกชิ้นผ่าน `zeep.adaptive-control-policy.v1`:

- `automatic_actuation=false`
- `recommendation_only=true`
- `executable=false`
- ลบ `command` และ `command_endpoint` ที่ generator อาจใส่มา
- ต้องมีการตัดสินใจจาก User/Admin
- Safety Supervisor มีอำนาจสูงสุดเสมอ

ดังนั้น AI อ่าน Fleet/Sensor/Baseline เพื่อเสนอคำแนะนำได้ แต่ไม่มีเส้นทางเรียก
GPIO, MQTT หรือ Audio controller โดยตรง

## งาน Firmware ต่อไป

ทุก ESP ควรเพิ่มฟิลด์ต่อไปนี้แบบ additive โดยไม่ทำให้ payload เดิมหาย:

1. `pod_id`, `device_id`, `device_type`
2. `board_model`, `board_revision`
3. `firmware_version`, `firmware_sha256`, `config_sha256`
4. `boot_id`, `sequence`, `uptime_ms`
5. `quality.valid`, `quality.reason`, reset/error counter
6. RSSI, heap และ sensor-specific diagnostics

Topic รุ่นถัดไปควรเป็น
`zeep/v1/{pod_id}/{device_id}/{telemetry|status|event|command}` พร้อม LWT, ACL,
command ID, expiry และ idempotency

