# ZEEP Pod 01 — Pi 5 และ ESP System Audit

วันที่ตรวจ: 19 กันยายน 2026 (Asia/Bangkok)  
Git: `develop` · `f570a68`  
ขอบเขต: ตรวจแบบ read-only จาก source, service, USB, MQTT, GPIO, network และ telemetry จริง

## สรุปสำหรับทีม

ระบบหลักทำงานครบและแยก failure ของ Sensor ได้ดี: Pi 5 รับ Sensor Hub 1 และ BCG
ผ่าน USB, รับ Sensor Hub 2 และ Control Hub สองชุดผ่าน MQTT, ควบคุม GPIO 12 จุด
และเล่นเสียงผ่าน USB Audio + MPV ได้ ขณะตรวจ Sensor สิ่งแวดล้อมทั้ง 6 รายการเป็น
`live`, service ทำงานปกติ และ Pi ไม่มี thermal throttling

อย่างไรก็ตาม สถานะปัจจุบันยังเป็น **Pilot ที่พร้อมพัฒนาต่อ** ไม่ใช่ industrial
hardware acceptance เพราะ actuator ส่วนใหญ่ยืนยันเพียงว่า “สั่งแล้ว” ไม่ได้ยืนยันผล
กายภาพ, MQTT เปิดแบบ anonymous บนทุก interface, Firmware/BOM ของ Hub 2 และ Control
Hub ยังไม่อยู่ในทะเบียนกลาง และ application composition root ยังใหญ่ประมาณ 8,000 บรรทัด

## 1. Pi 5 ที่ยืนยันจากเครื่องจริง

| รายการ | ค่าที่ตรวจพบ |
|---|---|
| Board | Raspberry Pi 5 Model B Rev 1.1 |
| CPU/RAM | Cortex-A76 4 core · RAM 8 GB |
| OS | Debian 13 (trixie), aarch64 |
| Kernel | `6.12.47+rpt-rpi-2712` |
| Storage | microSD 29 GB · ใช้ 12 GB (44%) · ว่าง 16 GB |
| Temperature | 44.4 °C |
| Throttling | `0x0` — ไม่พบ throttling |
| Python | 3.13.5 ใน `.venv` |
| Runtime | `zeep-pod.service` · `/home/pod1/pi5/app.py` |
| Broker | Mosquitto local service |
| Audio | C-Media USB Audio + MPV 0.40.0 |

Network แบ่งเป็นสามทาง:

- `wlan0` — LAN หลัก `192.168.1.100/24`
- `wlan1` — network สำหรับ Hub `192.168.50.1/24`
- `tailscale0` — remote administration

Service หลักเปิดที่ TCP 8000, MQTT ที่ 1883 และ SSH ที่ 22

## 2. Hardware inventory และเส้นทางข้อมูล

```text
SHT3x + OPT3001 + SPH0645
        │ I2C / I2S
        v
Sensor Hub 1 ESP32-S3 -- USB JSONL --> Pi canonical environment

MH-Z19C + PMS7003 + SGP40
        │ UART / I2C (ต้องยืนยัน BOM/pin map)
        v
Sensor Hub 2 ESP ------ Wi-Fi MQTT --> Pi canonical environment

LSM-800-T BCG -------- USB binary --> Pi BCG parser --> Session raw/derived data

Pi -- MQTT command --> Control Hub 1 --> IR --> Air conditioner
Pi -- MQTT command --> Control Hub 2 --> Servo --> Bed remote
Pi -- BCM GPIO -------> Door/light/aroma/steam/red-light drivers
Pi -- MPV/USB Audio --> Speaker
```

### 2.1 Sensor Hub 1 — ยืนยันระดับ Hardware สูงสุดในระบบปัจจุบัน

| รายการ | รายละเอียด |
|---|---|
| MCU | ESP32-S3, USB JTAG/Serial, MAC `44:1B:F6:8C:0C:54` |
| Pi device | `/dev/ttyACM0`, 115200 baud |
| USB identity | Espressif USB JTAG/serial debug unit |
| Firmware ที่เอกสารระบุ | `sensorhub1-smart-ear-v0.5.3-debug` |
| Transport | JSON Lines, measurement 1 วินาที; Pi สรุป canonical frame 10 วินาที |
| SHT3x-DIS | I2C address `0x44`; temperature/humidity; live |
| OPT3001 | I2C address `0x45`; lux; live |
| SPH0645LM4H-B | DATA GPIO 11, BCLK 12, WS 13; 32 kHz LEFT mono, 32-bit slot |

SPH0645 ประมวลผล dBA และ DSP ที่ ESP32 แล้ว Pi รับผลโดยตรง ไม่ทำ `abs()` หรือ
คำนวณเสียงซ้ำ DSP shadow ส่ง spectral centroid/flatness/flux, band ratios,
syllabic modulation, periodicity และ provisional class โดยไม่ส่ง PCM และยังไม่มี
สิทธิ์เปลี่ยน Sleep State/Score/Control

ค่าขณะตรวจ: temperature 23.11 °C, humidity 57.39 %RH, lux 0.05,
sound 39.27 dBA est. Sensor ทั้งสาม `live`; SPH0645 ไม่มี clip/read/alignment error
ใน frame ที่ตรวจ

ข้อสังเกต: OPT3001 มี cumulative failure 6,358 และ recovery 9 แต่ consecutive
failure เป็น 0 จึงทำงานอยู่ ควรแสดง failure **rate ต่อ uptime/ช่วงล่าสุด** แทน
cumulative count เพื่อแยกปัญหาอดีตออกจากปัญหาปัจจุบัน

### 2.2 Sensor Hub 2 — Environment ผ่าน MQTT

| รายการ | รายละเอียดที่ยืนยันได้ |
|---|---|
| Device/Firmware | `sensorhub2-pod1` · `zeep-sensorhub2-1.0.0` |
| IP/RSSI | `192.168.50.226` · -53 dBm |
| MQTT | `zeep/pod1/sensorhub2/telemetry` และ `/status` |
| Sensors | MH-Z19C CO2, PMS7003 PM1/2.5/10, SGP40 raw/VOC Index |
| Live sample | CO2 479 ppm, PM2.5 0–1 µg/m³, VOC Index 62 ใน packet ที่ตรวจ |

ยังไม่ยืนยัน exact ESP model, board revision, internal GPIO/UART/I2C map, schematic,
BOM, firmware repository, telemetry cadence contract, retained/LWT policy และ
firmware checksum จึงต้องเก็บจากทีม Hardware ก่อน freeze

### 2.3 BCG LSM-800-T

| รายการ | รายละเอียด |
|---|---|
| USB bridge | Silicon Labs CP2102 serial `0001` |
| Stable alias | `/dev/ttyUSB_HRB` -> `/dev/ttyUSB0` |
| Transport | 115200 baud, binary 66 bytes |
| Payload | waveform 25 samples, bed status, HR, RR, packet/status code |
| Persistence | raw byte-exact เก็บใน `bcg.db` เฉพาะ Recording Session |

BCG เป็นแหล่งหลักของ bed status, HR, RR และ sleep evidence เมื่อไม่มีผู้ใช้งาน
ล่าสุดระบบเห็น `Get out of bed`, HR/RR เป็น null ถูกต้องตาม contract

### 2.4 Control Hub 1 — Air conditioner

| รายการ | รายละเอียด |
|---|---|
| Device/Firmware | `controlhub1-pod1` · `3.0.0-controlhub1-mqtt` |
| IP/RSSI | `192.168.50.243` · -27 dBm |
| Function | รับ MQTT แล้วส่ง IR ไปแอร์ |
| Live state | online, MQTT connected, logical power on, setpoint 25 °C |

คำสั่งถูก serialize, มี minimum IR gap และรอ ACK แต่ ACK ยืนยันเพียงว่า bridge ส่ง
IR แล้ว ไม่ได้พิสูจน์ว่าแอร์รับคำสั่งหรือเปลี่ยนอุณหภูมิ/พัดลมจริง

### 2.5 Control Hub 2 — Adjustable bed

| รายการ | รายละเอียด |
|---|---|
| Device/Firmware | `controlhub2-bed-pod1` · `1.0.0-controlhub2-bed` |
| IP/RSSI | `192.168.50.114` · -21 dBm |
| Function | Servo 4 ตัวกด remote: head/foot/flat/center/stop |
| Protection | command serialize, ACK, auto-stop default 2 วินาที |

ยังไม่มี position sensor, limit feedback หรือแรง/กระแส feedback จึงห้ามตีความ ACK
เป็นตำแหน่งเตียงจริง

### 2.6 GPIO outputs บน Pi

ทุกขาเป็น BCM, active-high, initial LOW และขณะตรวจเป็น output LOW ครบ 12 จุด

| Function | BCM | ลักษณะคำสั่ง |
|---|---:|---|
| Door open / close | 17 / 27 | pulse 0.7 s |
| Ceiling / star light | 22 / 4 | persistent |
| Aroma 1–4 | 5 / 6 / 13 / 19 | pulse 5 s |
| Steam | 26 | pulse 5 s |
| Red light face/body/leg | 23 / 24 / 25 | persistent |

GPIO state คือ commanded state เท่านั้น ไม่มี door position, obstruction, relay
current หรือ load feedback และ manager เป็น all-or-nothing: ขาเดียว init ไม่ได้จะปิด
การควบคุม GPIO ทั้งชุด

### 2.7 Audio

- USB C-Media Audio เป็น ALSA card `Device`, playback device 0
- Production backend คือ MPV ผ่าน Unix IPC
- เพลงเริ่มต้นหยุด, volume 60%, repeat-one
- Logical volume update ยังไม่ใช่หลักฐานว่า acoustic output เปลี่ยนจริง

## 3. Data ownership และ timing

| ชั้น | เจ้าของ | Timing/หน้าที่ |
|---|---|---|
| Raw acquisition | ESP/BCG adapters | ต่อเนื่องตาม hardware cadence |
| Canonical sensor frame | Pi sampler | ทุก 10 วินาที |
| Sleep evidence | scoring pipeline | epoch 30 วินาที |
| State confirmation | transition policy | โดยทั่วไป 60 วินาที |
| Safety | local supervisor | ทำงานอิสระจาก scoring/session |
| Session storage | SQLite + raw BCG DB | local-first; ไม่แก้ raw ตอน rerun |
| Public/Admin API | FastAPI/WebSocket | detached projection; Admin เห็น diagnostic มากกว่า User |

หลักการสำคัญ: Sensor ที่เสียหนึ่งตัวต้องไม่หยุด Sensor ตัวอื่น, stale data ต้องเก็บไว้
เพื่อ diagnostic แต่ห้ามใช้เป็น live evidence, และ AI/adaptive recommendation ไม่มีสิทธิ์
เรียก GPIO/MQTT/control โดยตรง

## 4. สิ่งที่ผ่านการตรวจ

- `zeep-pod.service`, Mosquitto, Tailscale และ SSH active
- Sensor Hub 1, Sensor Hub 2, BCG, Control Hub 1/2 connected
- Canonical environment: 6/6 devices live
- GPIO initialize ครบ 12 outputs
- Pi: temperature ปกติ, ไม่มี throttling, disk/RAM ยังเพียงพอ
- Hardware/transport/control/acoustic regression: 104 tests ผ่าน
- Sensor Hub 1 Firmware contract/A-weighting/CEM tooling: 23 tests ผ่าน
- Golden full-flash backup ของ Sensor Hub 1 มี checksum และ verify log

## 5. ช่องว่างและความเสี่ยง

### P0 — ก่อนขยายหลาย Pod หรือใช้นอก Pilot

1. **MQTT exposure:** broker ฟัง `0.0.0.0:1883`, `allow_anonymous true` และ firewall
   INPUT เป็น accept ทำให้ network อื่นที่ถึง Pi อาจ publish command ได้
2. **Actuator feedback:** แอร์, เตียง, ประตู, relay และ volume ไม่มี end-to-end physical
   confirmation จึงยังสร้าง closed-loop control ที่ปลอดภัยไม่ได้
3. **Hardware source of truth:** Hub 2 และ Control Hub ไม่มี schematic/BOM/pin map,
   firmware source SHA/binary checksum และ acceptance record ในทะเบียนเดียวกัน

### P1 — ความน่าเชื่อถือและดูแลรักษา

1. ใช้ stable udev alias แยกตาม USB serial สำหรับทั้ง Hub 1 และ BCG; ห้ามพึ่ง
   `/dev/ttyACM0` เมื่อมีหลาย USB device
2. Sensor Hub 1 ที่ติดตั้งยังชื่อ `debug`; ต้องสร้าง release artifact ที่ field/behavior
   เท่าเดิม, ผูก firmware SHA + config checksum และทำ CEM/soak acceptance
3. เพิ่ม `command_id`, idempotency, device boot ID และ matching ACK ใน Control Hub
4. แสดง error rate/window และ reset count แทน cumulative counter อย่างเดียว
5. Restart มี WebSocket `CancelledError` เพราะ graceful window 5 วินาที แม้ shutdown
   สำเร็จ ควรปิด WebSocket อย่างตั้งใจก่อน service teardown เพื่อลด false alarm
6. `app.py` ยังประมาณ 8,024 บรรทัด ควรเหลือ composition/startup แล้วแยก route,
   orchestration และ device policy ต่อ
7. `backup/` บน Pi ใช้ประมาณ 2.5 GB ควรทำ inventory/retention รายชนิดโดยไม่แตะ raw
   Session ที่อยู่ใน retention policy

### P2 — Observability และ Fleet

1. เพิ่ม fleet health endpoint ที่สรุป firmware/config/schema/data age/error/reset ทุก Hub
2. เก็บ device heartbeat แบบ time-series และ alert เฉพาะ actionable change
3. Retained topic `zeep/pod1/controlhub4/status` ยืนยันว่าเป็น legacy state และลบ
   ด้วย retained tombstone แล้วเมื่อ 19 กันยายน 2026; การ subscribe ใหม่ไม่พบค่าเดิม
4. เก็บ network RSSI trend, clock drift, packet loss และ sequence gap ต่อ device

## 6. Target architecture ที่แนะนำ

### 6.1 Device contract เดียวกันทุก ESP

ทุก packet ควรมีอย่างน้อย:

```json
{
  "schema_version": "zeep.device.v1",
  "pod_id": "zeep-pod-01",
  "device_id": "sensorhub2-pod1",
  "device_type": "sensor_hub",
  "board_model": "...",
  "board_revision": "...",
  "firmware_version": "...",
  "firmware_sha256": "...",
  "config_sha256": "...",
  "boot_id": "...",
  "sequence": 123,
  "uptime_ms": 456789,
  "quality": {"valid": true, "reason": "ok"},
  "payload": {}
}
```

ใช้ namespace `zeep/v1/{pod_id}/{device_id}/{telemetry|status|event|command}`;
status ใช้ retained + LWT, telemetry ไม่ retained, command ไม่ retained และทุก command
ต้องมี ID/expiry/idempotency

### 6.2 Network/security

- แยก Hub VLAN/AP ออกจาก user LAN ต่อไป
- ให้ broker รับเฉพาะ loopback + Hub interface หรือ firewall allow เฉพาะ `lo/wlan1`
- ใช้ per-device username/secret และ topic ACL; TLS เมื่อ hardware budget รองรับ
- Port 8000 ควรเข้าผ่าน HTTPS reverse proxy/Tailscale policy ไม่เปิด trust boundary กว้าง
- แยก user/admin/service authentication และบันทึก audit ของ control command

### 6.3 Physical feedback ที่ควรเพิ่มตามลำดับ

1. ประตู: open/closed reed switch, obstruction/current sensing และ emergency manual path
2. แอร์: power/current sensing + supply/return temperature; IR ACK แยกจาก physical state
3. เตียง: limit/position feedback และ timeout ที่ firmware ไม่พึ่ง Pi เพียงชั้นเดียว
4. GPIO loads: fused driver board, channel current/fault input, active-level label
5. Audio: calibrated output limit และตรวจ actual playback state
6. Ventilation: sensor/actuator contract จริงก่อนเปิด adaptive control

### 6.4 Software boundary

```text
transport adapters
  -> versioned device contracts
  -> canonical state + quality/freshness
  -> session/safety/control services
  -> API projections
```

- `app.py`: ประกอบ dependency และ startup/shutdown เท่านั้น
- `hardware/`: transport และ device adapters; ไม่ใส่ product scoring
- `sensors/`: validation, normalization, catalog, freshness
- `services/`: command orchestration, safety, session lifecycle
- `api/`: auth + request/response mapping
- `sessions/`: immutable raw reference, derived model/version และ audit trail
- Adaptive AI สร้าง recommendation ก่อนเสมอ; actuator command ต้องผ่าน policy และ
  user/admin confirmation จน physical feedback ครบ

## 7. Definition of Done สำหรับ Hardware รุ่นต่อไป

อุปกรณ์หนึ่งตัวถือว่า “ขึ้นทะเบียนพร้อมพัฒนา” เมื่อมีครบ:

1. Datasheet, schematic, BOM, board revision และ connector/pin map
2. Firmware source commit, reproducible binary, SHA-256 และ partition map
3. Versioned telemetry/command/ACK contract + unit/scale/range/null semantics
4. Stable device identity และ udev/MQTT identity
5. Power budget, fuse/driver rating, active level และ safe state เมื่อ boot/reset/disconnect
6. Bench test, fault-injection, soak test และ rollback procedure
7. Physical calibration/acceptance record พร้อมเครื่องมืออ้างอิง
8. Admin health view ที่แยก connected, live, valid, stale และ physically confirmed

## เอกสารหลักที่ควรอ่านต่อ

- [`docs/onboarding/hardware-hub-map.md`](../onboarding/hardware-hub-map.md)
- [`docs/onboarding/technology-stack-and-tools.md`](../onboarding/technology-stack-and-tools.md)
- [`docs/pi5-software-architecture.md`](../pi5-software-architecture.md)
- [`docs/zeep-sensor-interface-contract-v1.2.md`](../zeep-sensor-interface-contract-v1.2.md)
- [`firmware/sensorhub1-esp32s3/README.md`](../../firmware/sensorhub1-esp32s3/README.md)
- [`firmware/sensorhub1-esp32s3/ORIGINAL_FIRMWARE_COMPATIBILITY.md`](../../firmware/sensorhub1-esp32s3/ORIGINAL_FIRMWARE_COMPATIBILITY.md)

## Evidence boundary

ค่าที่ระบุว่า “ยืนยัน” มาจากเครื่อง Pod 01 และ telemetry ณ วันที่ตรวจ ส่วนข้อมูล
ภายใน Hub 2/Control Hub ที่ไม่มี source/schematic ถูกระบุเป็น unknown โดยตั้งใจ
เอกสารนี้ไม่ใช่ electrical safety certification, medical-device validation หรือ
ใบรับรองการสอบเทียบ Sensor
