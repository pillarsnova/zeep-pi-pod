# ZEEP v1 — Hardware และ Hub Map

สถานะ: **Current implementation map · Internal Pilot / freeze candidate**
ตรวจจาก branch `develop`, pushed baseline
`d2c7af76e23942df9a778a20342e766c8a8bc6d9` และ working candidate ปัจจุบัน
เมื่อ 16 กันยายน 2026
ขอบเขต: Pi 5 runtime, Sensor Hub 1/2, BCG, Control Hub 1/2, Audio และ GPIO

การสกัด live-device freshness ไป `zeep_pod/api_state_projection.py` ในงานรอบนี้
เป็น behavior-preserving composition refactor เหนือ baseline ดังกล่าว และไม่เปลี่ยน
transport, command, threshold หรือ physical-device contract ที่สรุปในหน้านี้

เอกสารนี้ตอบสี่คำถามสำหรับสมาชิกใหม่:

1. อุปกรณ์ใดส่งหรือรับข้อมูลอะไร ผ่าน transport ใด
2. ส่วนใดเป็นเจ้าของ Raw value, canonical value, command state และข้อมูลถาวร
3. ระบบทำอะไรเมื่อ packet, transport หรืออุปกรณ์ล้มเหลว
4. ควร refactor ต่ออย่างไรโดยไม่เปลี่ยนพฤติกรรม v1

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
| Sensor Hub 1 | SHT3x-DIS: temperature/humidity; OPT3001: lux; SPH0645LM4H-B: `sound_dba`/diagnostic dBFS | `/dev/ttyACM0`, 115200, JSON หนึ่ง object ต่อบรรทัด | `state["sensor"]["esp32"]` | `zeep_pod/hardware/sensorhub1.py` + `sensor_contracts.py` + `sensor_runtime.py` |
| Sensor Hub 2 | MH-Z19C: CO2; PMS7003: PM1/2.5/10; SGP40: raw/VOC Index | MQTT `127.0.0.1:1883`, telemetry/status topics | `state["sensor"]["sensorhub2"]` | `zeep_pod/hardware/sensorhub2.py` |
| BCG | LSM-800-T waveform 25 samples, bed status, HR, RR | `/dev/ttyUSB_HRB`, 115200, binary frame 66 bytes | `state["sensor"]["bcg"]`; raw Session epochs in `bcg.db` | `zeep_pod/hardware/bcg.py`; parser `sensor_contracts.py`; storage `bcg_storage.py` |
| Control Hub 1 | ESP32-S3 bridge ส่งคำสั่ง IR ไปเครื่องปรับอากาศ | MQTT command/status/event | `state["aircon"]` | `zeep_pod/hardware/controlhub1.py`; route/sequence policy ยังอยู่ใน `app.py` |
| Control Hub 2 | ESP32 bridge ใช้ servo 4 ตัวกดรีโมตเตียงปรับระดับ | MQTT command/status/event | `state["bed_control"]` | `zeep_pod/hardware/controlhub2.py`; auto-stop policy ยังอยู่ใน `app.py` |
| Audio | เพลง local และ Brainwave preview ออกลำโพงของ Pi | MPV IPC ผ่าน Unix socket; `afplay`/`ffplay` เป็น development fallback | `state["music"]`, `state["system"]["player"]` | `zeep_pod/hardware/audio.py`, `audio_api.py`, `brainwave_audio.py` |
| GPIO | ประตู 2 ทิศ, ไฟเพดาน/ดาว, Aroma 4, Steam, Red light 3 zone | Pi BCM GPIO ผ่าน `gpiozero` + `lgpio` chip 0 | `state["gpio"]` เป็น commanded state | `zeep_pod/hardware/gpio.py`; pulse/route policy ยังอยู่ใน `app.py` |

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
อ่านด้วย `readline()` ต่อเนื่อง

### Data ownership

- `SensorHub1Reader` เป็นเจ้าของ framing, UTF-8/JSON parse, packet classification,
  reconnect และ timestamp ตอนรับ packet.
- `sensor_contracts.decode_hub_payload()` เป็นเจ้าของ wire-to-flat adaptation และ
  nested field ownership.
- `sensor_runtime.normalize_hub1_sensor()` เป็นเจ้าของ alias/range/finite validation;
  `compose_environment_snapshot()` เป็นเจ้าของ canonical environment view.
- `SensorHub1StateStore` เขียน latest raw-normalized payload ที่ legacy key
  `state["sensor"]["esp32"]`. ชื่อนี้คือ compatibility debt; อย่า rename เป็น
  `sensorhub1` โดยตรงเพราะ API/UI/tests ยังอ่าน key เดิม.
- ทุก valid sound packetถูกเพิ่มใน `sound_level_history` แบบ bounded in-memory และ
  ถูกสรุป energy-average ใน Sensor frame; ไม่มี raw Hub 1 stream database แยก.

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

`firmware/sensorhub1-esp32s3/` ระบุชัดว่า **ARCHIVED / DO NOT FLASH** และเป็น
replacement candidate ที่ยกเลิกแล้ว จึงไม่ใช่หลักฐานว่า pin map, binary หรือ
processing pipeline ภายในนั้นตรงกับ Production firmware ปัจจุบัน ห้ามใช้ source
ชุดนี้ deploy หรือเติมรายละเอียด production ที่ runtime contract ไม่ได้ยืนยัน

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

- `sensor_contracts.parse_lsm800t_frame()` เป็นเจ้าของ byte map แบบ deterministic.
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
  canonical environment ผ่าน `zeep_pod/sessions/sensor_frame_sampler.py`; BCG
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

HTTP/service policy ที่ยังอยู่ใน `app.py`:

- movement ทุกตัวเป็น bounded one-shot; หลัง default `BED_MOVE_SECONDS=2` Pi
  สร้าง timer ส่ง `bed_stop` แบบ best effort แม้ browser หลุด.
- generation token ยกเลิก timer เก่าเมื่อ movement ใหม่เริ่ม เพื่อไม่ให้ stop ของ
  command A ไปตัด command B ก่อนเวลา.
- explicit `bed_stop` ยกเลิก auto-stop timer.
- movement ต้องผ่าน safety guard; `bed_stop` และ `status` ไม่ต้องผ่าน.
- Safety safe profile เรียก `publish_stop_best_effort()` โดยไม่รอ ACKและไม่โยน error.

### State/ACK/failure behavior

- Status/event update `state["bed_control"]`; snapshot ทำ stale หลัง default 70 วินาที.
- State ไม่ connected หรือไม่สด: 503; lock busy: 429; publish fail: 503;
  ACK timeout default 3 วินาที: 504; hub reject: 502.
- Disconnect ระหว่าง command ปลุก condition waiter แต่ request ยังสิ้นสุดตาม
  ACK deadline; pending state ถูก clear ใน `finally`.
- Auto-stop publish fail จะ log `auto_stop_publish_failed` และไม่ raise กลับ browser
  เพราะ browser request จบไปแล้ว.
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
| Canonical environment | `sensor_runtime.compose_environment_snapshot` + 10 s frame sampler | Session sample/derived frame ตาม lifecycle; ไม่ rewrite raw | Dashboard, Session, Safety, Shadow advice |
| BCG latest/raw windows | `LSM800TReader` + `BCGPacketPublisher` | bounded memory; byte-exact `bcg.db` เฉพาะ Recording ผ่าน `BCGStorage` | Recording gate, Sensor frame, Sleep evidence, Admin raw |
| Aircon | Control Hub 1 adapter + route service policy | live state memory; fan intent/reference JSON เท่านั้น | Control UI, Session activity, Safety guard |
| Bed control | Control Hub 2 adapter + auto-stop policy | live state memory; Session activity log | Control UI, Safety stop |
| GPIO | `GPIOManager` commanded state | memory; labels แยกเป็น JSON | Control UI, Safe profile |
| Audio | `AudioPlayer` | state memory; track/preview filesบน disk | Control UI, Session activity, Safe profile |

Consumer API รับ detached snapshot และตัด engineering telemetry ออกผ่าน
`zeep_pod/api_state_projection.py`/`sound_observability.py`; Admin จึงเห็น diagnostic
มากกว่า User โดยตั้งใจ ห้ามส่ง raw state dictionary ตรงไป public endpoint

Freshness ของ Hub 1/2, BCG และ Control Hub 1/2 ถูก project บน detached response
ด้วย `LiveDeviceProjectionPolicy`/`project_live_device_statuses()` ใน module เดียวกัน;
ฟังก์ชันนี้ไม่ mutate live reader state

## `app.py` wiring และ lifecycle ปัจจุบัน

### Import/construction

`app.py` เป็น composition root และ import adapter ทุกตัวโดยตรง จากนั้น:

1. สร้าง `GPIOManager`, `AudioPlayer`, `DatabaseManager`, `BCGStorage` ใน module scope.
2. Inject MQTT/config/state/logger เข้า Control Hub 1/2 ด้วย `configure_*()` แล้ว
   สร้าง adapter instance.
3. สร้าง `AudioControlService` และ include audio router.
4. FastAPI lifespan initialize/migrate database, restore Session/Sensor frame,
   start backup และเริ่ม daemon threads.

เมื่อสร้าง response, `snapshot()` ส่ง detached state กับ stale thresholds เข้า
`project_live_device_statuses()` แล้วจึง compose canonical environment ต่อ ไม่ได้
คำนวณ freshness ซ้ำราย Hub ใน route

Hardware threads ที่ lifespan start แยกกันคือ Sensor Hub 1, Sensor Hub 2,
Control Hub 1, Control Hub 2, BCG รวมถึง Sensor-frame/Session/Safety supervisors.
การล้มของ loop หนึ่งจึงไม่ควรทำให้ peer loop หยุด

### Shutdown

Lifespan save active checkpoint/frame, stop player, shutdown GPIO, flush BCG,
stop backup และ drain database. Serial/MQTT loops ปัจจุบันเป็น daemon thread แบบ
`run_forever`/`loop_forever`. BCG adapter รับ stop event ได้แล้ว แต่ `app.py`
ยังไม่ได้ส่ง lifecycle signal ให้; Hub อื่นยังไม่มี explicit disconnect. Process exit
จึงยังเป็นผู้ยุติ thread เหล่านี้ นี่คือ lifecycle debt ที่ควรแก้แบบ
characterization-first ไม่ใช่เปลี่ยนพร้อม hardware behavior

## Dead, duplicate และ compatibility audit

ตรวจด้วย `rg` ที่ baseline ข้างต้นได้ข้อสรุปดังนี้

### ไม่มี dead runtime adapter ในกลุ่ม Hardware ปัจจุบัน

`app.py` import `audio`, `audio_api`, `bcg`, `controlhub1`, `controlhub2`, `gpio`,
`sensorhub1`, `sensorhub2` และ `BCGStorage`; lifespan start reader/control threads
ครบทุก Hub ส่วน audio/GPIO ถูก route/safety/shutdown เรียกจริง ดังนั้น **ห้ามลบ
module ใดในกลุ่มนี้โดยอ้างว่าไม่ถูกใช้**

คำสั่งยืนยัน:

```bash
rg -n 'from zeep_pod\.hardware|from bcg_storage' app.py
rg -n 'Thread\(target=(esp32_reader|sensorhub2_mqtt_reader|controlhub1_mqtt\.run|controlhub2_bed_mqtt\.run|bcg_reader)' app.py
rg -n 'gpio\.|player\.|bcg_storage\.|controlhub[12]' app.py
```

`zeep_pod/hardware/__init__.py` เป็น package marker หนึ่ง docstring ไม่มี runtime
implementation จึงไม่ใช่ duplicate adapter

### Code ที่ดูซ้ำแต่ยังเป็น compatibility facade

| Symbol | Evidence การใช้ | สถานะ/ทางออก |
|---|---|---|
| `app.build_environment_snapshot()` | runtime, Safety, sampler และ tests เรียก | facade ไป pure `compose_environment_snapshot`; เก็บจนย้าย caller/tests ครบ |
| `app.normalize_esp32_sensor()` | Inject เข้า SensorHub1Reader และ tests เรียก | ไม่ dead; เปลี่ยนชื่อ/ลบหลังสร้าง stable service interface |
| `app.hold_last_valid_sound()` | Inject เข้า SensorHub1Reader และ tests เรียก | ไม่ dead; เป็น config-binding facade |
| `app._normalize_aircon_command()`, `_normalize_bed_command()`, `_resolve_aircon_temperature_command()` | HTTP routes เรียก | แปลง domain `ValueError` เป็น HTTP 422; ควรย้ายไป router/service ไม่ลบตรง ๆ |
| `analysis_frame` response key และ `app._publish_analysis_frame()` | key เก่าเป็น API compatibility; function ถูก legacy test เรียก | ย้าย test/caller ก่อนแล้วค่อยประกาศ deprecation |

### Runtime-unreachable/test-only ที่เป็น cleanup candidate

- `app.sound_energy_average_db()` พบเฉพาะ definition และ
  `test_sensor_contract.py`; runtime ใช้ `summarize_sound_window()`/
  `sensor_runtime.energy_average_db()` โดยตรง. ย้าย test ไป pure moduleแล้วจึงลบ facade ได้.
- `app._publish_analysis_frame()` พบ caller เฉพาะ legacy regression test;
  production samplerเรียก `_publish_sensor_frame()`. เก็บไว้จน test ใช้ public
  Sensor-frame service ที่เสถียร.
- `ControlHub2BedMQTT._prepare_command(..., toggle_repeat=true)` ถูก exercise ใน
  unit test แต่ production routeส่ง `toggle_repeat=false` คงที่. ต้องให้ Product
  ตัดสิน behavior ก่อนลบหรือเปิดใช้; ห้ามเปิดเพียงเพราะมี code อยู่.
- `firmware/sensorhub1-esp32s3/` และ CEM tools ไม่ถูก import จาก Pi runtime และ
  มีป้าย archive ชัดเจน. จัดเป็น audit artifact ไม่ใช่ dead code ที่นำกลับมา deploy.

### Naming/ownership duplication ที่ต้องรักษาชั่วคราว

- Sensor Hub 1 ใช้ชื่อ transport/module `sensorhub1` แต่ public/internal state key
  ยังชื่อ `esp32`.
- `analysis_frame` และ `sensor_frame` เป็น metadata aliases ชุดเดียวกันเพื่อรองรับ
  client เก่า.
- MH-Z19C/PMS7003/SGP40 มี physical catalog owner เป็น Hub 2 แต่ composer ยัง
  allow Hub 1 fallback.
- `audio_api.py` อยู่ใน package `hardware` ทั้งที่มี product/HTTP policy มากกว่า
  device I/O; เป็น placement debt ไม่ใช่ implementation ซ้ำ.

กติกาลบ code: ต้องมี `rg` ยืนยันว่าไม่มี production caller, migration/deprecation
ของ public key เสร็จ, focused/full regression ผ่าน และ smoke test เครื่องจริงผ่าน

## Target boundary หลัง refactor

อย่าสร้าง “hub.py” ขนาดใหญ่ที่รวมทุกอุปกรณ์ เป้าหมายคือแยกตาม **physical
failure domain** และแยก transport ออกจาก feature policy:

```text
FastAPI router       แปลง HTTP/auth/error เท่านั้น
       │
Feature service      safety, command sequence, pulse/timer, activity audit
       │
Device adapter       USB/MQTT/GPIO/audio wire I/O + reconnect/ACK
       │
Pure contract        parse/normalize/range/state projection; ไม่มี hardware side effect

app.py               สร้าง config/dependencies + start/stop lifecycle เท่านั้น
```

Dependency ต้องไหลลงทางเดียว: adapter/service ห้าม import `app.py`; device adapter
ไม่ควรรู้ FastAPI `HTTPException`; service/router map domain error เป็น status code

## Staged refactor map

ทุก stage ต้องเป็น behavior-preserving commit แยกจาก threshold, firmware,
hardware wiring, Sleep formula หรือ product behavior change

### Stage 0 — Freeze characterization และเติมหลักฐานเครื่องจริง

- บันทึก Git SHA, Pod ID, effective non-secret ports/topics/timeouts, USB identity
  (`/dev/serial/by-id`), broker/service health และ firmware version ที่ telemetry ส่ง.
- ขอ authoritative BOM/pin/protocol/checksum ของ Sensor Hub 2 และ Control Hub 1/2;
  ทำเครื่องหมาย unknown จนได้หลักฐาน ห้ามคัดจาก archived firmware.
- เพิ่ม snapshot parity fixtures ของ state, canonical frame และ error responses
  ก่อนย้าย code.
- ยืนยัน legacy Hub 1 flat packet และ Hub 1 fallback ของ Hub 2 devicesว่ายังพบใน
  field หรือถอดได้หลัง migration.

Exit: อธิบาย port/topic/device/owner/ACK ได้ครบโดยไม่พึ่งความจำของคนติดตั้ง

### Stage 1 — แยก LSM-800-T reader ออกจาก `app.py`

สถานะ: **เสร็จใน working candidate นี้** — มี `LSM800TReader`,
`BCGPacketPublisher`, injected serial/parser/storage/state/clock/sleeper/stop event,
fake-serial regression และ compatibility facade บางใน `app.py` แล้ว งานที่เหลือคือ
USB smoke หลัง deploy และการ wire stop event เข้ากับ lifespan ใน Stage 2

สร้าง `zeep_pod/hardware/bcg.py` หรือ `lsm800t.py` ให้มี reader ที่ inject:
serial factory, parser, state publisher, packet sink, event logger, clock, sleeper
และ stop event. คง `parse_lsm800t_frame()` และ `BCGStorage` แยก pure/storage ตามเดิม
ก่อนเพื่อให้ diff เล็ก

Characterization ต้องครอบคลุม quiet gap, partial frame, wrong marker, reconnect,
status mapping, vital hold, no-session packet และ partial epoch flush. ระหว่างย้ายให้
`app.bcg_reader()` เป็น facade ชั่วคราว

Exit: `app.py` ไม่มี byte-framing loop แต่ live state/DB bytes/timing เหมือนเดิม

### Stage 2 — ทำ Sensor Hub lifecycle ให้เป็น object ที่หยุดได้

- Sensor Hub 1: คง `SensorHub1Reader`/state store แต่รวม port/baud/stale config
  เป็น immutable config และ inject stop event; รักษา packet-local failure.
- Sensor Hub 2: เปลี่ยน free function + nested callbacks เป็น `SensorHub2MQTT`
  instance ที่มี `start/run/stop`, config และ state port ชัดเจน.
- ห้ามรวม MQTT client กับ Control Hub เพราะ isolation ปัจจุบันตั้งใจแยก failure.
- คง `state.sensor.esp32` และ public JSON key จนมี versioned API migration.

Exit: lifespan ปิด serial/MQTT ได้ deterministic โดยไม่รอ process kill

### Stage 3 — แยก Control transport ออกจาก Aircon/Bed feature policy

- เลิก module-global `configure_controlhub1/2`; constructor รับ config, state port,
  logger และ safety callback.
- Transport class เป็นเจ้าของ MQTT/ACK เท่านั้นและคืน domain result/error.
- `AirconControlService` เป็นเจ้าของ ON/temp/swing sequence, fan preflight, IR gap,
  fan reference persistence และ ACK scope.
- `BedControlService` เป็นเจ้าของ bounded motion, generation token, auto-stop และ
  best-effort safety stop.
- Router แปลง busy/unavailable/timeout/rejected เป็น 429/503/504/502 เหมือนเดิม.

Exit: adapter ไม่ import FastAPI; route ไม่มี MQTT/timer internals; client ยังแยกกัน
และ command ยัง QoS 0/retain false

### Stage 4 — แยก GPIO feature service/router

คง `GPIOManager` เป็น primitive adapter แล้วสร้าง service สำหรับ persistent output,
door interlock pulse, accessory lock/cooldown, safety exceptions และ activity log.
สร้าง router แยกจาก `app.py`; config รวม logical name, BCM, mode และ pulse duration
แต่ต้องคง all-or-nothing readiness ใน behavior-preserving stage

Exit: `app.py` ไม่มี `asyncio.sleep()` สำหรับ physical output และทุก `finally LOW`
มี fake-device regression

### Stage 5 — จัด Audio ตาม feature boundary

คง `AudioPlayer` ใน hardware package. ย้าย `AudioControlService`/router ไป feature
package เช่น `zeep_pod/audio/` พร้อม compatibility import shim; renderer
`brainwave_audio.py` เป็น pure/offline generation dependency ไม่ควรรวมกับ subprocess

แยก policy decision เรื่อง `set_volume()` ที่ logical stateเปลี่ยนแม้ IPC fail เป็น
งานถัดไปต่างหาก เพราะการทำให้ API fail จะเป็น behavior change ไม่ใช่ refactor

Exit: import app ไม่สร้าง/แตะ player process, route parity ครบ และ shutdown ยัง stop

### Stage 6 — แยก Sensor frame/canonical projection

- **เสร็จในรอบนี้:** ย้าย freshness ของ Hub/BCG/Control และ aircon response
  projection ไป pure `api_state_projection` แล้ว `snapshot()` เรียก facade เดียว.
- **เสร็จในรอบนี้:** ย้าย 10-second `sensor_frame_sampler`, bounded windows และ
  frame publication เป็น service ที่รับ snapshots จาก Hub/BCG ports.
- ใช้ `sensor_runtime` เป็น pure source of truth ต่อไป; ห้ามให้ Dashboard/Session/
  Safety compose alias หรือ bias คนละชุด.
- เก็บ `analysis_frame` alias จน client migration เสร็จ.

Exit: `app.py` ไม่คำนวณ canonical frame และ snapshot parity ผ่าน

### Stage 7 — Hardware runtime registry และ composition root บางลง

สร้าง registry/lifecycle owner ที่ถือ adapter instances และ thread handles แบบมีชื่อ,
start ตามลำดับ, stop แบบ bounded, report health โดยไม่ซ่อน state ของแต่ละ Hub.
สร้าง GPIO/Audio/DB ภายใน lifespan หรือ explicit factory แทน module import side effect

Exit: `app.py` เหลือ config, dependency construction, router include และ lifespan;
ไม่มี transport loop, ACK logic, pulse timer หรือ feature formula

### Stage 8 — ลบ shim/dead branch หลัง migration เท่านั้น

- ย้าย tests จาก `app.*` facade ไป public service/pure contract.
- ตัดสิน `toggle_repeat`, cross-hub fallback และ legacy flat packetกับ Product/
  Hardware owner.
- ประกาศ version/deprecation ก่อน rename `esp32` หรือเอา `analysis_frame` ออก.
- เก็บ archived firmwareตาม audit retention; ไม่ปะปนกับ production build/test gate.

Exit: `rg` ไม่พบ caller, API contract versioned, full regression + hardware smoke ผ่าน

## Test และ smoke gate ต่อ failure domain

| Domain | Focused automated gate | เครื่องจริงที่ต้องดูหลัง refactor |
|---|---|---|
| Hub 1 | `test_sensorhub1_reader.py`, `test_sensor_contract.py`, `test_sensor_services.py` | valid/invalid sensor แยกกัน, stale 25 s, reconnect event |
| Hub 2 | `test_sensor_services.py` | telemetry/status topics, offline/LWT behavior, stale 15 s |
| BCG | `test_bcg_reader.py`, `test_sensor_contract.py`, BCG/storage/session gate tests | byte marker, quiet gap, partial-frame resync, fresh HR+RR gate, raw epoch flush |
| Control 1/2 | `test_control_protocol.py`, control/RBAC tests | ACK/timeout/stale โดยใช้ safe test plan; ห้าม actuate ขณะ occupied |
| Audio | `test_audio_defaults.py`, `test_audio_api.py`, `test_brainwave_audio.py` | backend/device, stop/pause/volume, occupied preview guard |
| GPIO | modular/control/RBAC tests + fake output testsที่ต้องเพิ่ม | initial LOW, door interlock, pulse returns LOW, safe profile |
| Architecture | `test_modular_architecture.py` | startup/shutdown logs และไม่มี orphan process/thread |

ก่อน handoff ให้รัน gate กลางจาก [Pi 5 Software Architecture](../pi5-software-architecture.md)
และ [TESTING.md](../../TESTING.md). Test pass บน workstation ไม่แทน Hardware smoke,
Safety approval หรือ Final Code Freeze

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
