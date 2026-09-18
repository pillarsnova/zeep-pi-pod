# ZEEP v1 — Hardware และ Hub Map

สถานะ: **Current implementation map · Internal Pilot / freeze candidate**
ตรวจจาก source ใน branch `develop` เมื่อ 17 กันยายน 2026; Git SHA ที่ deploy จริง
ต้องตรวจจาก health/version response และ closure record ของ release นั้น
ขอบเขต: Pi 5 runtime, Sensor Hub 1/2, BCG, Control Hub 1/2, Audio และ GPIO

การสกัด BCG reader, 10-second Sensor-frame sampler และ live-device projection
เข้า module เฉพาะถูก push อยู่ใน baseline นี้แล้ว เป็น behavior-preserving refactor
ที่ไม่เปลี่ยน transport, command, threshold หรือ physical-device contract

เอกสารนี้ตอบสี่คำถามสำหรับสมาชิกใหม่:

1. อุปกรณ์ใดส่งหรือรับข้อมูลอะไร ผ่าน transport ใด
2. ส่วนใดเป็นเจ้าของ Raw value, canonical value, command state และข้อมูลถาวร
3. ระบบทำอะไรเมื่อ packet, transport หรืออุปกรณ์ล้มเหลว
4. ข้อมูลใด runtime ยืนยันแล้วและ unknown ใดต้องส่งต่อ Hardware owner

ค่าพอร์ต, topic, timeout และ GPIO ด้านล่างคือ **ค่า default ใน source** ซึ่งอาจถูก
override ด้วย environment ของแต่ละ Pod ก่อนตรวจเครื่องจริงให้ดู EnvironmentFile
ของ service บนเครื่องนั้นโดยไม่คัดลอก secret ลง Git หรือ ticket

## ภาพรวมเส้นทางข้อมูลและคำสั่ง

```text
SHT3x-DIS ─┐
OPT3001 ───┼─> Sensor Hub 1 ── USB JSONL ─> SensorHub1Reader ─> state.sensor.esp32 ─┐
SPH0645 ───┘                                                                        │
                                                                                     ├─> canonical
MH-Z19C ──┐                                                                          │   environment
PMS7003 ──┼─> Sensor Hub 2 ── MQTT ─────> sensorhub2 reader ─> state.sensor.sensorhub2┘   snapshot
SGP40 ────┘                                                                                 │
                                                                                             ├─> API/UI
LSM-800-T ── USB binary ─> bcg_reader ─> state.sensor.bcg + in-memory windows                ├─> Session
                                      └─> BCGStorage ─> bcg.db (Recording only)              ├─> Safety
                                                                                             └─> Shadow advice

Browser command ─> Auth/RBAC/CSRF ─> command/service policy ─┬─> Control Hub 1 MQTT ─> Aircon IR
                                                             ├─> Control Hub 2 MQTT ─> Bed remote servos
                                                             ├─> GPIOManager ─> relay/driver outputs
                                                             └─> AudioPlayer ─> MPV/fallback ─> speaker
```

`state` เป็นเจ้าของ **สถานะใน process** ไม่ใช่หลักฐานว่าโหลดจริงเปลี่ยนแล้ว เช่น
GPIO HIGH/LOW คือค่าที่ Pi สั่ง, ระดับพัดลมแอร์คือ intent/reference และ ACK ของ
Control Hub 1 ยืนยันเพียงว่า ESP32 เรียกส่ง IR แล้ว ไม่ได้ยืนยันสถานะกายภาพของแอร์

## Inventory ฉบับย่อ

| กลุ่ม | อุปกรณ์/หน้าที่ที่ source ระบุ | Pi transport default | Live state owner | Module ปัจจุบัน |
|---|---|---|---|---|
| Sensor Hub 1 | SHT3x-DIS: temperature/humidity; OPT3001: lux; SPH0645LM4H-B: `sound_dba`/diagnostic dBFS | `/dev/ttyACM0`, 115200, JSON หนึ่ง object ต่อบรรทัด | `state["sensor"]["esp32"]` | `hardware/sensorhub1.py` + `sensors/contracts.py` + `sensors/runtime.py` |
| Sensor Hub 2 | MH-Z19C: CO2; PMS7003: PM1/2.5/10; SGP40: raw/VOC Index | MQTT `127.0.0.1:1883`, telemetry/status topics | `state["sensor"]["sensorhub2"]` | `hardware/sensorhub2.py` |
| BCG | LSM-800-T waveform 25 samples, bed status, HR, RR | `/dev/ttyUSB_HRB`, 115200, binary frame 66 bytes | `state["sensor"]["bcg"]`; raw Session epochs in `bcg.db` | `hardware/bcg.py`; parser `sensors/bcg.py`; storage `bcg_storage.py` |
| Control Hub 1 | ESP32-S3 bridge ส่งคำสั่ง IR ไปเครื่องปรับอากาศ | MQTT command/status/event | `state["aircon"]` | `hardware/controlhub1.py`; HTTP wiring อยู่ `api/control_routes.py`; sequence policy ยังอยู่ใน `app.py` |
| Control Hub 2 | ESP32 bridge ใช้ servo 4 ตัวกดรีโมตเตียงปรับระดับ | MQTT command/status/event | `state["bed_control"]` | `hardware/controlhub2.py`; HTTP wiring อยู่ `api/control_routes.py`; auto-stop policy ยังอยู่ใน `app.py` |
| Audio | เพลง local และ Brainwave preview ออกลำโพงของ Pi | MPV IPC ผ่าน Unix socket; `afplay`/`ffplay` เป็น development fallback | `state["music"]`, `state["system"]["player"]` | `hardware/audio.py`, `audio_api.py`, `brainwave_audio.py` |
| GPIO | ประตู 2 ทิศ, ไฟเพดาน/ดาว, Aroma 4, Steam, Red light 3 zone | Pi BCM GPIO ผ่าน `gpiozero` + `lgpio` chip 0 | `state["gpio"]` เป็น commanded state | `hardware/gpio.py`; lock/cooldown อยู่ `hardware/pulse_control.py`; HTTP อยู่ `api/legacy_control_routes.py` |

## 1. Sensor Hub 1 — USB Serial JSONL

### Physical/data contract ที่ runtime รู้จริง

- Hub ID ที่ canonical packet ต้องส่งคือ `sensorhub1` และ measurement event คือ
  `environment`.
- SHT3x-DIS เป็นเจ้าของ `temperature_c`, `humidity_rh`; OPT3001 เป็นเจ้าของ
  `lux`; SPH0645LM4H-B เป็นเจ้าของ `sound_dba`, `sound_dbfs` ใน nested schema.
- `sound_dba` ถูกประมวลผลโดย firmware ของ Sensor Hub 1. Pi คัดลอกตรงไป
  `sound_dba_est` โดยไม่ทำ `abs`, bias, offset หรือคำนวณ dBA ใหม่ ค่าใช้ได้เมื่อ
  เป็น finite number ในช่วงรวมขอบ 30–130 dBA.
- `sound_dbfs` เป็น engineering diagnostic แบบ signed; ไม่ใช่ fallback ของ dBA.
- Canonical nested schema คือ `zeep.sensor.telemetry` version `1.0`; decoder
  allowlist field ตาม physical sensor owner เพื่อกัน sensor block หนึ่งทับค่าของอีกตัว.
- Rollback bridge ยังรับ flat Hub 1 packet ที่มี temperature/humidity/lux allowlist.
  ความเข้มงวดเรื่อง owner ของ flat legacy packet ต่ำกว่า nested schema จึงต้องไม่ขยาย
  allowlist นี้โดยไม่มี migration plan.

ค่า transport มาจาก `ESP32_PORT` และ `ESP32_BAUD`; default คือ
`/dev/ttyACM0` และ `115200`. Adapter ใช้ `serial.Serial(..., timeout=1)` และ
รับ telemetry แบบ JSONL หนึ่ง object ต่อบรรทัด บรรทัด CR/LF ว่างหลังเชื่อมต่อใหม่
จะถูกมองเป็นตัวคั่นของ Serial ไม่ใช่ packet เสีย ส่วนข้อความสถานะจาก ESP ROM/driver
จะถูกแยกเป็น `serial_diagnostic_ignored` แบบรวมเหตุการณ์ซ้ำ โดยไม่แทนค่าจาก Sensor
ล่าสุด หากบรรทัดเริ่มเป็น JSON แต่ parse ไม่สำเร็จจึงบันทึกเป็น
`payload_rejected: invalid_json` เพื่อให้ความเสียหายของ telemetry จริงยังตรวจพบได้
อ่านด้วย `readline()` ต่อเนื่อง

### Data ownership

- `SensorHub1Reader` เป็นเจ้าของ framing, UTF-8/JSON parse, packet classification,
  reconnect และ timestamp ตอนรับ packet.
- `sensors.contracts.decode_hub_payload()` เป็นเจ้าของ wire-to-flat adaptation และ
  nested field ownership.
- `sensors.normalization.normalize_hub1_sensor()` เป็นเจ้าของ
  alias/range/finite validation; `sensors.environment.compose_environment_snapshot()`
  เป็นเจ้าของ canonical environment view.
- `SensorHub1StateStore` เขียน latest raw-normalized payload ที่ legacy key
  `state["sensor"]["esp32"]`. ชื่อนี้คือ compatibility debt; อย่า rename เป็น
  `sensorhub1` โดยตรงเพราะ API/UI/tests ยังอ่าน key เดิม.
- ทุก valid sound packet ถูกเพิ่มใน `sound_level_history` แบบ bounded in-memory และ
  ถูกสรุป energy-average ใน Sensor frame; ไม่มี raw Hub 1 stream database แยก.

### ขอบเขตเสียงปัจจุบัน

- ค่าเฉลี่ยใน Sensor frame เป็นการรวมเชิงพลังงานของ valid packet-level
  `sound_dba` observations ไม่ใช่ DSP บน PCM และยังไม่ควรอ้างว่าเป็น certified
  LAeq(A) จน Production firmware contract ยืนยัน weighting, window และ calibration.
- Pi ไม่รับ PCM แต่ contract รองรับ band energy และ spectral/temporal feature
  scalars จาก Firmware DSP shadow candidate เพื่อวางป้ายชั่วคราวบน Admin Timeline.
- `state.system.sound_analysis` มี sample count, average, min/max/span และธง
  large step สำหรับ Admin observability เท่านั้น ไม่ใช่ source classifier.
- แผนและ implementation boundary อยู่ที่
  [หูอัจฉริยะ · Acoustic Intelligence DSP Plan](smart-ear-dsp-plan.md) และมีสถานะ
  **P1 ADMIN SHADOW**: Pi/API/UI พร้อมรับ marker แล้ว ส่วน Firmware candidate ยัง
  ไม่ถือว่า Production จนผ่าน physical gate; ทุกส่วนต้องไม่กระทบ Sleep State,
  Score หรือ Control.

### Failure behavior

- UTF-8/JSON เสีย, hub ผิด, schema/version ผิด หรือค่าผิด contract: ปฏิเสธเฉพาะ
  packet, log event และอ่านบรรทัดถัดไปโดยไม่ reconnect.
- `boot`, `INFO`, calibration response หรือ event อื่น: ignore เป็น control-plane;
  ไม่ทับ live sensor state.
- SPH0645 invalid: ตัดเฉพาะ sound; temperature/humidity/lux ของ packet เดียวกันยัง
  publish ได้ และค่าดังกล่าวไม่ถูกเพิ่มใน sound history.
- Serial open/read exception: เก็บ payload ก่อนหน้าไว้, ตั้ง `connected=false` กับ
  `error`, รอ 2 วินาทีแล้ว reconnect; log ซ้ำเฉพาะเมื่อข้อความ error เปลี่ยน.
- พอร์ตยังเปิดแต่ไม่มี packet: snapshot projection ทำเป็น stale หลัง default 25 วินาที.
  ค่าเก่ายังคงอยู่เพื่อ diagnostic พร้อมอายุข้อมูล แต่ consumer ห้ามถือเป็น live.

### ขอบเขต Firmware

`firmware/sensorhub1-esp32s3/` เป็น Production test candidate สำหรับเรียนรู้
Hardware จริง ไม่ใช่ source of truth ของ Firmware ที่ติดตั้งอยู่ การ Flash ทดสอบ
ทำได้เมื่อ owner อนุมัติและมี backup/rollback ส่วนข้อสรุป pin map, binary และ
processing pipeline ต้องมาจาก telemetry/การวัดจริงและบันทึก version ทุกครั้ง

## 2. Sensor Hub 2 — MQTT Environment Telemetry

### Physical/data contract ที่ runtime รู้จริง

| Sensor | Canonical fields | Runtime range ที่ composer ยอมรับ |
|---|---|---|
| MH-Z19C | `co2_ppm` | 400–5000 ppm |
| PMS7003 | `pm1_0_ug_m3`, `pm2_5_ug_m3`, `pm10_ug_m3` | 0–1000 µg/m3 ต่อ field |
| SGP40 | `sgp40_raw`, `voc_index` | raw 0–65535; index 1–500 |

Pi ใช้ broker เดียวกันแต่ client แยกจาก Control Hub:

- host `MQTT_HOST=127.0.0.1`, port `1883`, keepalive `30`
- telemetry `zeep/pod1/sensorhub2/telemetry`
- status `zeep/pod1/sensorhub2/status`
- subscribe QoS 0; client ID `zeep-pi5-dashboard-<hostname>`

Source ไม่มี username/password/TLS parameter ใน MQTT client. Default จึงสมมติ
broker เฉพาะใน Pi; ห้าม expose broker นี้สู่วง network ที่ไม่เชื่อถือ

### Data ownership และ fallback ที่ต้องรู้

- Telemetry topic ผ่าน `decode_hub_payload(..., expected_hub="sensorhub2")`, เติม
  `transport=mqtt`, topic, `last_update`, `connected=true` แล้วแทนค่า
  `state["sensor"]["sensorhub2"]`.
- Status topic เก็บ object ที่ `mqtt_status`; `online=false` ทำให้ hub disconnected.
- Nested decoder บังคับ device field ownership เหมือน Hub 1.
- `ENVIRONMENT_DEVICE_SPECS` กำหนด Hub 2 เป็น primary ของ MH-Z19C/PMS7003/SGP40
  แต่ยังอนุญาต Hub 1 เป็น secondary source. นี่คือ legacy cross-hub fallback ใน
  current code ไม่ใช่หลักฐานว่าอุปกรณ์สามตัวต่ออยู่กับ Hub 1 จริง ห้ามลบหรือขยาย
  ก่อนตรวจ payload ภาคสนามและ rollback requirement.
- Canonical composer เลือก source ที่ live + valid ก่อน; ถ้าไม่มี live source อาจ
  เก็บ valid historical source เป็นสถานะ `stale` เพื่อ diagnostic แต่ downstream
  Sensor frame ใช้ค่าเป็น evidence เฉพาะ device status `live`.

### Failure behavior

- ไม่มี `paho-mqtt`: ตั้ง error เฉพาะ Sensor Hub 2, log
  `mqtt_library_missing` และ reader thread จบ; Hub 1/BCG ยังทำงาน แต่ต้อง restart
  process หลังติดตั้ง dependency.
- Connect/loop exception: ตั้ง connected false/error, รอ 5 วินาทีแล้วสร้าง client ใหม่.
- MQTT disconnect callback: เก็บ payload เดิม, ตั้ง connected false/error.
- JSON ไม่ใช่ object, decode/schema/hub error: log `invalid_mqtt_payload`; ไม่ทับ
  state ก่อนหน้าและไม่ทำให้ peer reader หยุด.
- ไม่มี telemetry ใหม่เกิน default 15 วินาที: snapshot ทำเป็น stale และ
  `fallback_reason=mqtt_disconnected` หรือ `stale` ตามเหตุ.

Repo ยังไม่มี authoritative firmware, internal pin/UART/I2C map, publish cadence,
LWT/retain policy หรือ board revision ของ Sensor Hub 2 ต้องเก็บข้อมูลเหล่านี้จาก
BOM/firmware repository ของ hardware team แยกต่างหาก

## 3. BCG — LSM-800-T USB Binary

### Wire contract

- Port `BCG_PORT=/dev/ttyUSB_HRB`, baud `115200`, serial timeout 1 วินาที.
- Frame 66 bytes: `Odata` ที่ bytes 0–4, waveform 25 ค่า signed int16
  little-endian ที่ bytes 5–54, `Bdata` ที่ bytes 57–61, packet ID byte 62,
  status byte 63, HR byte 64 และ respiration raw byte 65 (`raw / 10`).
- Status map: 0 On bed, 1 Get out of bed, 2 Moving, 3 Weak breathing,
  4 Heavy object on bed, 5 Snoring.
- Current sanity bounds ของ analysis/start gate คือ HR 25–220 bpm และ RR 2–60/min.
  ค่า 0 จาก firmware map เป็น `None`.

### Data ownership

- `sensors.bcg.parse_lsm800t_frame()` เป็นเจ้าของ byte map แบบ deterministic.
- `LSM800TReader` เป็นเจ้าของ serial sync/reconnect; `BCGPacketPublisher` เป็น
  เจ้าของ live vital hold, in-memory histories และการส่ง packet เข้า storage.
- `app.py::bcg_reader()` เหลือ compatibility facade สำหรับประกอบ config/dependency
  แล้วเรียก adapter; ไม่มี byte-framing loop อยู่ใน `app.py` แล้ว.
- `state["sensor"]["bcg"]` เก็บ latest display state และ packet counters.
- `bcg_history` เป็น bounded feature window; `bcg_raw_history` เป็น bounded Admin
  inspector. ทั้งคู่หายเมื่อ process จบ.
- `BCGStorage` เก็บ byte-exact frame/base64 เฉพาะเมื่อ Recording Session เปิดแล้ว,
  batch default 60 packet เป็นหนึ่ง epoch/transaction label และ enqueue ไป `bcg.db`.
  ตอน end/restart/shutdown จะ flush partial epoch.
- `sensor_frame_sampler()` รวม BCG packets ที่มาจริงใน bucket 10 วินาทีกับ
  canonical environment ผ่าน `sessions/sensor_frame_sampler.py`; BCG
  summary ต้องมี paired HR+RR ใน packet เดียวกัน.

### Failure behavior

- ไม่มี byte ระหว่าง frame: ถือว่าเป็น quiet gap ปกติและคง serial port เปิดไว้.
- เจอ partial frame แล้ว timeout: ทิ้ง frame นั้น, clear sync และหา `Odata` ใหม่.
- marker `Bdata` ผิด: ทิ้ง frame และ resync; ไม่บันทึก packet.
- Port/read/parse exception อื่น: ตั้ง BCG disconnected/error, รอ 2 วินาทีแล้ว reconnect.
- Snapshot ทำ BCG stale หลัง default 60 วินาที; live-held HR/RR อยู่ได้ไม่เกิน
  default 15 วินาทีและเฉพาะ status ที่ถือว่า on-bed.
- Recording start ไม่ได้ใช้ display-held vital: ต้องมี BCG packet ใหม่ที่ on-bed
  และ HR+RR valid ต่อเนื่องตาม `SESSION_VITAL_START_PACKETS` (default 3).

หมายเหตุสำหรับ audit: comment บางจุดอธิบาย cadence ว่า “ประมาณหนึ่ง packet/วินาที”
ขณะที่ operational comment ระบุว่าตอนมีคนอยู่บนเตียงอาจห่าง 2–4 วินาที. Storage
ใช้ **จำนวน packet** ไม่ใช่นาฬิกาหนึ่งนาทีจริง ดังนั้นอย่าเรียก 60-packet epoch ว่า
60 วินาทีจนกว่าจะยืนยัน cadence จาก hardware log.

## 4. Control Hub 1 — Air-conditioner IR

### Transport/command contract

- ESP32-S3 bridge เชื่อม Pi ผ่าน MQTT แล้วส่ง IR ไปแอร์.
- command `zeep/pod1/controlhub1/command`; status
  `zeep/pod1/controlhub1/status`; event `zeep/pod1/controlhub1/event`.
- Client แยกจาก Sensor Hub 2, subscribe status/event QoS 0, publish command
  QoS 0 และ `retain=false` เพื่อกันคำสั่งเก่า replay และกัน QoS retry ยิง IR ซ้ำ.
- Allowlist: `on`, `off`, `temp 15` ถึง `temp 28`, `fan`, `swing_on/off`,
  `light_on/off`, `status`.
- ทุก command serialize ด้วย lock เพราะ event schema ปัจจุบันไม่มี unique
  `command_id`.

HTTP policy ที่ `app.py` เพิ่มเหนือ transport:

- `on` ส่ง sequence `on` -> รอ default 2.0 s -> `temp 18` -> รอ IR gap ->
  `swing_on` ภายใต้ lock เดียว.
- `fan` ส่ง `status` preflight -> รอ default 0.25 s -> `fan`; preflight fail แล้ว
  ไม่ส่ง fan.
- IR command เว้นอย่างน้อย default 1.2 s หลัง ACK ล่าสุด.
- `off` และ `status` ใช้ได้ระหว่าง safety latch; command อื่นต้องผ่าน safety guard.
- Transport ตรวจ safety ซ้ำหลัง IR delay ก่อน publish ทุก step; หาก latch ระหว่าง
  `on` → `temp 18` จะไม่ส่ง step ถัดไป ไม่ใช่ตรวจเฉพาะตอนรับ HTTP request.
- ค่า fan 1–5 เป็น acknowledged cycle/reference ที่ Pi persist ไว้ใน
  `data/aircon_control_state.json`; ไม่ใช่ค่าที่วัดจากแอร์.

### State/ACK/failure behavior

- Status/event update `state["aircon"]`; snapshot ทำ stale หลัง default 70 วินาที.
- ก่อน publish ต้องมี MQTT client connected และ aircon state สด มิฉะนั้น 503.
- มี command อื่นถือ lock: 429; publish fail: 503; ไม่มี matching ACK ภายใน
  default 3 วินาที: 504; event `ok!=true`: 502.
- Matching ใช้ command string + event sequence/time ภายใน Pi เพราะยังไม่มี
  command ID.
- ACK หมายถึง bridge รายงานว่า IR transmit routine ทำงานเท่านั้น. API ตอบ
  `delivery_status=ir_transmitted_unverified`, `physical_confirmation=false`.
- ไม่มี `paho-mqtt`: adapter ตั้ง error แล้ว thread จบ; MQTT loop exception รอ
  5 วินาทีแล้ว reconnect.

Repo ไม่มี production firmware, IR code provenance, discrete-vs-toggle proof หรือ
feedback wire จากแอร์ จึงห้ามเพิ่ม automatic retry หรืออ้างว่า physical state เปลี่ยน

## 5. Control Hub 2 — Adjustable Bed

### Transport/command contract

- Bridge ใช้ servo สี่ตัวกดรีโมตเตียง; source ระบุว่าเป็น ESP32 แต่ไม่ได้ freeze
  board variant/pin map ไว้ใน repo.
- command `zeep/pod1/controlhub2/bed/command`; status
  `zeep/pod1/controlhub2/bed/status`; event `zeep/pod1/controlhub2/bed/event`.
- Client แยกจากทุก Hub, subscribe QoS 0, publish QoS 0 และ `retain=false`.
- Allowlist: `head_up/down`, `foot_up/down`, `bed_stop`, `flat`, `center_all`,
  `status`.
- Command serialize และจับ ACK ด้วย command string + receive time เช่น Hub 1.

HTTP facade อยู่ใน `app.py`; deadline owner อยู่ใน `hardware/bed_motion.py` และ
transport เรียก service ก่อนรอ ACK:

- movement ทุกตัวเป็น bounded one-shot; เริ่ม timer ทันทีที่ MQTT publish สำเร็จ
  และส่ง `bed_stop` หลัง default `BED_MOVE_SECONDS=2` แม้ ACK หายหรือ browser หลุด.
- generation token ยกเลิก timer เก่าเมื่อ movement ใหม่เริ่ม เพื่อไม่ให้ stop ของ
  command A ไปตัด command B ก่อนเวลา.
- movement publish และ timed stop ถือ lock เดียวกันจน publish เสร็จ เพื่อปิด race
  ระหว่างการตรวจ generation กับการส่ง stop; ไม่ถือ lock ตลอดช่วงรอ ACK.
- explicit/safety `bed_stop` ยกเลิก timer เฉพาะเมื่อ publish สำเร็จ; ถ้าส่งไม่สำเร็จ
  deadline เดิมยังอยู่ และถ้าสร้าง timer ไม่ได้ให้พยายาม stop ทันที.
- movement ต้องผ่าน safety guard; `bed_stop` และ `status` ไม่ต้องผ่าน.
- Safety safe profile เรียก `publish_stop_best_effort()` โดยไม่รอ ACKและไม่โยน error.
- Safety Profile ตั้ง latch ก่อนเริ่ม side effects เพื่อปิดช่อง movement แทรกหลัง
  stop; ปล่อย state lock ก่อนสั่ง hardware เพื่อลดความเสี่ยง lock inversion.
- lifespan ปิด timer และพยายาม stop ถ้ายังมี movement ค้าง; idle shutdown ไม่ส่ง
  คำสั่งอุปกรณ์ และ constructor ไม่สร้าง thread/เปิด transport.

### State/ACK/failure behavior

- Status/event update `state["bed_control"]`; snapshot ทำ stale หลัง default 70 วินาที.
- State ไม่ connected หรือไม่สด: 503; lock busy: 429; publish fail: 503;
  ACK timeout default 3 วินาที: 504; hub reject: 502.
- Disconnect ระหว่าง command ปลุก condition waiter แต่ request ยังสิ้นสุดตาม
  ACK deadline; pending state ถูก clear ใน `finally`.
- Auto-stop publish fail จะ log `auto_stop_publish_failed`, ตั้ง
  `auto_stop_error=publish_failed` และไม่ raise กลับ browser เพราะ request จบแล้ว;
  ไม่ถือว่ามี physical confirmation และไม่ retry movement อัตโนมัติ.
- Event มี `active_command`, `active_servo`, `command_count` ได้ แต่ repo ไม่ได้
  ระบุ feedback จากกลไกเตียงจริง จึงควรตีความ ACK เป็น bridge acknowledgement
  เท่านั้นจน hardware contract ระบุอย่างอื่น.

Production route เรียก `toggle_repeat=false` เสมอ แม้ adapter ยังมี branch ที่แปลง
การกดทิศเดิมซ้ำเป็น `bed_stop`; ดูหัวข้อ dead/duplicate audit ก่อนนำ branch นี้กลับมาใช้

## 6. Audio

### Backend และ ownership

- Backend เลือกตามลำดับ `mpv` -> `afplay` -> `ffplay`; บน Pi ต้องใช้ MPV เพื่อ
  pause/replace/volume ผ่าน IPC ได้ครบ.
- MPV ใช้ Unix socket `${TMPDIR}/pi5_local_mpv.sock`. ถ้าไม่ได้ตั้ง
  `MPV_AUDIO_DEVICE` และพบ `/proc/asound/Device` จะเลือก
  `alsa/plughw:CARD=Device,DEV=0`.
- เพลงอ่านจาก `MUSIC_DIR` (default `music/`) เฉพาะ `.mp3`, `.wav`, `.flac`,
  `.m4a`, `.ogg`, `.aac`; resolved path ต้องอยู่ใต้ directory จริงเพื่อกัน symlink escape.
- `AudioPlayer` เป็นเจ้าของ subprocess/IPC/queue และ `state["music"]`; default
  stopped, volume 60%, repeat-one. เพดาน digital volume ของ music คือ 100%.
- `AudioControlService` เป็นเจ้าของ HTTP policy, stop/restart guard, safety,
  activity log และ Brainwave occupancy confirmation. Brainwave preview จำกัด 0–60%
  และ render ลง `data/brainwave_audio/`.

### Failure behavior

- ไม่มี player backend: app ยัง start และ list music ได้ แต่ play/preview ตอบ 500
  พร้อมข้อความติดตั้ง player.
- Spawn แล้ว process จบก่อนเริ่ม: clear playing state, เก็บ error และตอบ 500.
- MPV pause IPC ไม่พร้อม: 503; fallback backend ไม่มี pause: 501.
- เปลี่ยน volume จะ bound 0–100 และ update logical state แม้ MPV IPC send คืน
  false; current API จึงไม่ยืนยันว่าระดับเสียงกายภาพเปลี่ยนแล้ว.
- Brainwave render กำลังทำอยู่: 429; มีผู้ใช้งานแต่ไม่ confirm: 409; occupant
  เปลี่ยนระหว่าง render: 409 และไม่เล่นเสียง.
- Safety profile และ lifespan shutdown เรียก stop; watcher เคลียร์ state เมื่อ player จบ.

## 7. GPIO

### Default BCM map

| Logical output | BCM | Mode ใน API |
|---|---:|---|
| `door_open` | 17 | pulse default 0.7 s |
| `door_close` | 27 | pulse default 0.7 s |
| `led` | 22 | persistent |
| `star_light` | 4 | persistent |
| `aroma1` / `aroma2` / `aroma3` / `aroma4` | 5 / 6 / 13 / 19 | pulse default 5 s |
| `steam` | 26 | pulse default 5 s |
| `red_light_face` / `body` / `leg` | 23 / 24 / 25 | persistent |

ทุก output ใช้ `OutputDevice(active_high=true, initial_value=false)` ผ่าน
`LGPIOFactory(chip=0)`. GPIO Pi เป็น 3.3 V logic; โหลด 12 V ต้องผ่านวงจร
opto/MOSFET/relay ตาม hardware design ห้ามต่อตรง

### Policy/state/failure behavior

- GPIO เปิดโดย default (`ZEEP_GPIO_ENABLED=1`). ตั้ง `0` เฉพาะ offline replay,
  test หรือ maintenance process ที่ห้ามจับ hardware; runtime จะประกาศ
  `ready=false` และ control route ตอบ 503 โดยไม่สร้าง mock output.
- `GPIOManager` เขียน `state["gpio"][name]` หลังเรียก device สำเร็จ. นี่คือ
  commanded state ไม่มี input feedback ยืนยัน relay/door/light จริง.
- Init ลอง default 10 ครั้งเฉพาะ error ที่มีคำว่า `busy`, หน่วง 0.5 s; error อื่น
  หยุดทันที. ถ้า pin ใดสร้างไม่ได้จะ close ทุก pin และ `ready=false`.
- ไม่มี `gpiozero/lgpio` หรือ init ไม่ครบ: ไม่มี mock และ route ที่เรียก
  `require_ready()` ตอบ 503. เพราะ ready เป็น all-or-nothing ปัญหา pin เดียวปิด
  GPIO control ทั้ง 12 จุด.
- Door pulses serialize ร่วมกัน, ปิดขาทิศตรงข้ามก่อนเริ่ม และคืน LOW ใน `finally`.
  เปิดประตูไม่ติด safety guard; ปิดประตูถูก guard.
- Aroma/Steam lock แยกต่อ output, ซ้อนกันที่ output เดิมตอบ 429, มี cooldown
  default 1 s และคืน LOW ใน `finally`.
- Persistent output ทุกตัวต้องผ่าน safety guard ยกเว้น `led=true` ซึ่งใช้เป็น
  safe illumination ได้.
- Safe profile ปิด Aroma/Steam/Star/Red/door drives, เปิด LED และ shutdown ทำ
  all-off + close factory แบบ best effort.

Current state ระบุ `ventilation_control_available=false`; แม้ Dashboard มีคำแนะนำ
เรื่องอากาศ แต่ v1 ยังไม่มี actuator interface สำหรับพัดลมเติม/ระบายอากาศ อย่าสร้าง
“Control Hub 3” หรือ map GPIO ให้ ventilation จากชื่อใน UI โดยไม่มี hardware contract

## State, persistence และผู้บริโภค

| Data | เจ้าของค่าปัจจุบัน | Persistence | ผู้บริโภคสำคัญ |
|---|---|---|---|
| Hub 1 latest payload | `SensorHub1StateStore` -> `state.sensor.esp32` | memory; orderly shutdown มี derived last Sensor frame cache | canonical environment, Admin diagnostic |
| Hub 2 latest payload/status | Sensor Hub 2 adapter -> `state.sensor.sensorhub2` | memory; derived frame cache เช่นเดียวกัน | canonical environment, Safety CO2, Admin |
| Canonical environment | `sensors.environment.compose_environment_snapshot` + 10 s frame sampler | Session sample/derived frame ตาม lifecycle; ไม่ rewrite raw | Dashboard, Session, Safety, Shadow advice |
| BCG latest/raw windows | `LSM800TReader` + `BCGPacketPublisher` | bounded memory; byte-exact `bcg.db` เฉพาะ Recording ผ่าน `BCGStorage` | Recording gate, Sensor frame, Sleep evidence, Admin raw |
| Aircon | Control Hub 1 adapter + route service policy | live state memory; fan intent/reference JSON เท่านั้น | Control UI, Session activity, Safety guard |
| Bed control | Control Hub 2 adapter + auto-stop policy | live state memory; Session activity log | Control UI, Safety stop |
| GPIO | `GPIOManager` commanded state | memory; labels แยกเป็น JSON | Control UI, Safe profile |
| Audio | `AudioPlayer` | state memory; track/preview filesบน disk | Control UI, Session activity, Safe profile |

Consumer API รับ detached snapshot และตัด engineering telemetry ออกผ่าน
`api/state_projection.py`/`sensors/observability.py`; Admin จึงเห็น diagnostic
มากกว่า User โดยตั้งใจ ห้ามส่ง raw state dictionary ตรงไป public endpoint

Freshness ของ Hub 1/2, BCG และ Control Hub 1/2 ถูก project บน detached response
ด้วย `LiveDeviceProjectionPolicy`/`project_live_device_statuses()` ใน module เดียวกัน;
ฟังก์ชันนี้ไม่ mutate live reader state

## Unknowns ที่ต้องส่งต่อ Hardware owner

รายการต่อไปนี้ **source ชุดนี้ยังตอบไม่ได้** และห้ามแต่งเติมใน onboarding:

- Production Sensor Hub 1 firmware binary/version/checksum และ production board/pin map
- Sensor Hub 2 board revision, sensor-to-hub pins/UART/I2C, firmware repository,
  cadence, retain/LWT และ broker security contract
- Control Hub 1 IR code source/protocol, toggle/discrete power proof และ appliance feedback
- Control Hub 2 board/pin/servo mapping, mechanical limits และ physical bed feedback
- Relay/MOSFET/opto part numbers, active-level validation, fuse/current/load ratings และ
  door end-stop/interlock feedback
- Speaker/amplifier model, safe acoustic calibration และ proof ว่า logical volume
  ตรงกับ output จริง
- Per-Pod effective environment overrides และ stable USB identities

จนกว่าจะมีหลักฐานเหล่านี้ v1 map นี้อธิบายได้เฉพาะ **software contract และ
as-coded failure behavior** ไม่ใช่ wiring acceptance หรือ production safety case
