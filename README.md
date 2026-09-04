# ZEEP Pod — Pi5 Local Dashboard

จอควบคุมภายในตู้ ZEEP Pod สำหรับ Raspberry Pi 5 — ธีม J.A.R.V.I.S. HUD
ใช้งานผ่านแท็บเล็ต/เบราว์เซอร์บน Wi-Fi hotspot ของ Pi ได้โดย**ไม่ต้องมีอินเทอร์เน็ต**
การเปลี่ยนแปลง production ใช้ branch `develop` และต้องผ่าน regression tests
เพื่อให้ประวัติการเปลี่ยนแปลงและเหตุผลอยู่ใน git ครบ

## โครงสร้างของระบบ (System Structure)

```
pi5/
├── app.py                  # Composition root: FastAPI, lifecycle, hardware orchestration
├── api_models.py           # Pydantic request contracts ของ HTTP API
├── control_protocol.py     # ตรวจคำสั่ง Aircon/Bed และแปลง temperature bias
├── access_control.py       # Browser session, User/Admin RBAC, CSRF, offline ticket
├── pod_occupancy.py        # Lease ป้องกัน login ซ้ำ และ coordinator สำหรับหลายตู้
├── api_history.py          # Raw history/export API สำหรับ Admin เท่านั้น
├── static/index.html       # Runtime bundle ไฟล์เดียว (สร้างจาก template + Control partials)
├── static/index.template.html
├── static/partials/control # Source ของการ์ดควบคุม 6 ส่วน
├── ui_composer.py          # Build/check bundle โดยไม่เพิ่ม browser-side fetch
├── sensor_contracts.py     # Datasheet/as-built/telemetry contract กลาง
├── sensor_calibration.py   # Calibration spec, validation และ atomic persistence
├── sensor_runtime.py       # Normalize/validate/compose Sensor Hub + Sound Leq
├── smart_response.py       # Shadow recommendations แบบ pure/read-only
├── api_v1.py               # Versioned read API envelope
├── sleep_signal_features.py# BCG/movement/arousal/HR-RR engineering proxies
├── sleep_stage_scoring.py  # Evidence scorer ร่วมของ Live และ Replay
├── sleep_system_policy.py  # Version/gate/transition/score policy source of truth
├── personal.py             # Adaptive baseline รายบุคคลจาก Session ที่หลับจริง
├── sleep_session_report.py # Mode-aware Sleep/Rest score และ final report
├── maintenance_registry.py # Write boundary/guard ของเครื่องมือข้อมูลย้อนหลัง
├── {reclassify,rescore,recalibrate,cleanup,trim,reset,annotate}_*.py
│                            # Offline maintenance; dry-run/guard/audit ตาม registry
├── TESTING.md               # กลุ่ม Regression/Safety และ Definition of done
├── generate_brainwaves.py  # สร้างเสียง brainwave 5 แบบ (Python stdlib ล้วน)
├── brainwave_audio.py      # Admin Sound Lab: render Preview แบบ versioned ไปยังลำโพง Pi
├── run.sh / run.bat        # bootstrap คำสั่งเดียว: venv + deps + เสียง + รัน
├── requirements.txt        # fastapi · uvicorn · pyserial · gpiozero
├── REMOTE-ACCESS.md        # แผนเปิดใช้ผ่าน URL (Tailscale / Cloudflare Tunnel)
├── music/     (gitignored) # ไฟล์เสียง — สร้างจากสคริปต์ หรือทีมวางไฟล์เพิ่มเอง
└── data/      (gitignored) # ข้อมูลส่วนบุคคล เก็บบนเครื่องเท่านั้น:
    ├── sessions.db         #   Session, Timeline, Event และ derived report
    ├── bcg.db              #   Raw BCG packet/epoch แยกจาก derived decision
    ├── auth.db             #   Browser auth session/CSRF/revocation
    ├── profiles.json       #   Profile และข้อมูลอ้างอิงสุขภาพที่ผู้ใช้อนุญาต
    ├── baselines.json      #   Adaptive baseline รายบุคคลที่มี version
    ├── calibration.json    #   Bias/calibration และ provenance ของอุปกรณ์
    └── active_session_checkpoint.json # Session continuity หลัง restart/ไฟดับ
```

หลักการแบ่ง module และ dependency/data flow ฉบับสำหรับทีมพัฒนาอยู่ที่
[Pi5 Software Architecture](docs/pi5-software-architecture.md) โดย `app.py`
ทำหน้าที่ประกอบระบบและ side effects เท่านั้น ส่วนกฎที่คำนวณได้ต้องอยู่ใน pure
module ที่ import และทดสอบได้โดยไม่เปิด GPIO, Serial, MQTT หรือเว็บเซิร์ฟเวอร์

### ขอบเขตความรับผิดชอบของ Backend

| ส่วน | หน้าที่ |
|---|---|
| `GPIOManager` | คุมขา GPIO ทั้ง 12 (door×2, ไฟเพดาน, ไฟดาว, aroma×4, steam, แสงแดง×3) · **ไม่มี mock** — เชื่อมต่อไม่ได้ = ปุ่มถูกปิด คำสั่งตอบ `503` พร้อมสาเหตุ |
| `AudioPlayer` | เล่นเสียง: `mpv` (บน Pi, ครบทุกฟีเจอร์) → `afplay` (macOS) → `ffplay` (เครื่องอื่น) |
| Brainwave Sound Lab | Admin-only A/B preview แบบ speaker-compatible AM · สร้างใน `data/brainwave_audio/` · มี consent guard ขณะตู้มีผู้ใช้งาน; ดู `docs/brainwave-sound-lab-v1.md` |
| `esp32_reader` (thread) | อ่าน JSON ทีละบรรทัดจาก USB serial → temperature / humidity / lux / sound |
| `bcg_reader` (thread) | แกะ frame 66-byte ของ LSM-800-T → waveform / HR / RR / bed status · แยก "ช่วงเงียบปกติ" ออกจาก "หลุดจริง" |
| `session_sampler` (thread) | เก็บ snapshot สิ่งแวดล้อม + ชีวสัญญาณทุก 10 วินาทีระหว่างมี Recording Session |
| `estimate_sleep_state` | exploratory 5-state Wake/N1/N2/N3/REM ทุก 10 วินาที จาก rolling 6 ชุด · BCG/HR/RR/movement เป็นหลัก · environment 7 ปัจจัยเป็น context · pre-G2 · ไม่ใช้ควบคุมอุปกรณ์ |
| Profile/Session store | login/logout รายบุคคล · ประวัติย้อนหลัง · รายงาน · ลบข้อมูล (PDPA) |

## User / Admin และ Pod Session

ระบบแยกสถานะ 2 ชนิดออกจากกันอย่างชัดเจน:

- **Auth Session** เป็นสิทธิ์ของแต่ละ Browser (`user` หรือ `admin`) เก็บด้วย
  opaque HttpOnly cookie และตรวจ CSRF สำหรับคำสั่งที่เปลี่ยนสถานะ
- **Pod Session** เป็นการครอบครองตู้นอนจริง มีได้ครั้งละหนึ่งคนต่อตู้

User เห็น Dashboard, Control และประวัติของบัญชีตนเองเท่านั้น ส่วน Admin เข้าถึง
Monitor, Safety, ผู้ใช้ทั้งหมด, Raw BCG, Export, Calibration และ Shutdown ได้
การซ่อนเมนูเป็นเพียง UX; Backend ตรวจสิทธิ์ซ้ำทุก API และ WebSocket

ข้อมูลผู้ใช้ ZEEP ผูกด้วย **Email ที่ normalize เป็นตัวพิมพ์เล็ก** เป็นหลัก:
Profile, Session history และ Adaptive Baseline ใช้ Account Key เดียวกันนี้
ทุกตู้ ส่วน `displayName` และ `username` เป็นข้อมูลสำหรับแสดงผลซึ่งอัปเดตจาก
แอปได้โดยไม่สร้างประวัติคนใหม่ ระบบยังใช้ `publicId` เป็น subject ภายในสำหรับ
ตรวจสิทธิ์/ป้องกันครอบครองหลายตู้ และจะย้ายข้อมูลรุ่นเก่าจาก username key ไปยัง
email key อัตโนมัติเมื่อเริ่มบริการ

การ Restart, ไฟดับ หรืออัปเดตโค้ด **ไม่ใช่ Logout**: Browser Login คงอยู่ใน
`auth.db` และ physical Session link คงอยู่ใน atomic
`data/active_session_checkpoint.json` ทั้งช่วง `waiting_bed` และ `recording`.
ไฟล์ checkpoint ไม่เก็บ password/access token/refresh token และจะถูกลบหลัง
ผู้ใช้กดจบ Session/ออกจากระบบ หรือ Admin ยืนยัน End/Kick เท่านั้น เมื่อบริการ
กลับมา UI จะต่อ WebSocket ใหม่และใช้ Session ID/ผู้ใช้/Rest Mode เดิมต่อทันที

Local fallback เปิดได้เฉพาะหลัง Pi ติดต่อ ZEEP API ไม่ได้จริง โดยต้องใช้ one-time
offline ticket อายุ 5 นาที การเรียก `/api/session/login` ตรง ๆ จะถูกปฏิเสธ

## รองรับหลายตู้และป้องกัน Login ซ้ำ

แต่ละตู้กำหนด `POD_ID` ไม่ซ้ำกัน เมื่อมีหลายตู้ ทุกตู้ต้องชี้
`OCCUPANCY_COORDINATOR_URL` ไปยัง coordinator เดียวกันและใช้
`OCCUPANCY_COORDINATOR_TOKEN` เดียวกัน ระบบจะจอง lease พร้อมกันสองเงื่อนไข:

1. หนึ่ง `ZEEP publicId` ครอบครองได้ครั้งละหนึ่งตู้
2. หนึ่ง `POD_ID` มีผู้ใช้งานได้ครั้งละหนึ่งบัญชี

Lease ต่ออายุอัตโนมัติ หาก coordinator หลุด ระบบจะ **ไม่รับ Login ใหม่** แต่จะไม่
ตัด Session ของคนที่กำลังนอนอยู่ และ Admin จะเห็นสถานะ degraded จนระบบกลับมา

กรณีติดตั้งตู้เดียวและไม่กำหนด URL ระบบใช้ SQLite lease ในเครื่อง (`local` mode)
ซึ่งป้องกันซ้ำได้เฉพาะตู้เดียว ไม่ถือว่าเป็น multi-pod deployment

### Data flow

```
ESP32 (USB, JSON/line) ──┐                                   ┌─▶ WebSocket /ws (ทุก 0.5s) ─▶ Browser
BCG (USB, 66-byte) ──────┼─▶ state (in-memory + lock) ─▶ snapshot() ─┤
   └─▶ bcg_history (5 นาที) ─▶ sleep estimator ─┘            └─▶ REST GET /api/state
Browser ─▶ POST /api/{door,pulse,output,music,labels,session} ─▶ GPIO / player / data files
```

เวอร์ชัน runtime, Rest Mode, สูตรคะแนนและ closure checklist ดูที่
[ZEEP Sleep System Current](../docs/zeep-sleep-system-current.md) และหลักฐานของ
ตัวประมาณดูที่ [ZEEP Sleep-State Baseline v1.5](../docs/zeep-sleep-state-baseline-v1.0.md):
Session/cycle เริ่มที่ Wake, ต้องผ่าน N1 ก่อน N2/N3/REM; N3 ไป REM ได้หลัง
dwell/hysteresis แต่ REM ไป N3 ต้องผ่าน N2 กติกานี้เป็น ZEEP continuity guard ไม่ใช่ AASM scoring rule;
G2 primary ontology แก้เป็น `W / N1 / N2 / N3 / REM` แบบ one-to-one กับ PSG;
การยุบเป็น `Wake / NREM / REM` ใช้เป็น secondary robustness analysis เท่านั้น.

### API ทั้งหมด

สัญญาใหม่ดู [ZEEP Pod API v1](../docs/zeep-api-v1.md): `GET /api/v1/state`
และ Admin contracts ใช้ envelope ที่มี schema/version/request-id ส่วน endpoint
เดิมด้านล่างยังคงรองรับ Tablet ที่ติดตั้งอยู่

| กลุ่ม | Endpoint |
|---|---|
| สถานะ | `GET /api/state` · `WS /ws` |
| ควบคุม | `POST /api/door/{open,close}` · `/api/pulse/{aroma1..4,steam}` · `/api/output/{led,star_light}` |
| เสียง | `GET /api/music` · `POST /api/music/{play,stop,pause,volume}` |
| ป้ายชื่อ | `POST /api/labels/{aroma1..4}` |
| Session | `POST /api/session/{login,logout}` · `GET /api/users` · `GET /api/history/{user}[/{id}]` · `DELETE /api/users/{user}` |

ทุก API ส่วนบุคคล/ควบคุมตรวจ Auth Session และ RBAC ที่ Backend ส่วน `POST`/`DELETE`
ตรวจ CSRF เพิ่มอีกชั้น คำสั่ง door/pulse มี lock + cooldown และดึงขากลับ LOW เสมอ
แม้คำสั่งถูกยกเลิกกลางทาง `API_TOKEN` สงวนไว้สำหรับ service automation เท่านั้น

---

## เริ่มใช้เร็วสุด — เครื่องไหนก็ได้ คำสั่งเดียว

```bash
./run.sh                     # macOS / Linux / Raspberry Pi
```

```bat
run.bat                      :: Windows
```

สคริปต์จะสร้าง `.venv`, ติดตั้ง dependencies, สร้างไฟล์เสียง brainwave (ครั้งแรก
ครั้งเดียว) แล้วรัน server ให้เอง · ต้องมีแค่ **Python 3.9+** ในเครื่อง

ตัวเลือกผ่าน environment: `PORT=8080 ./run.sh` · `SKIP_MUSIC=1` ·
`BRAINWAVE_MINUTES=30` · `API_TOKEN=xxx`

นโยบาย **ไม่มี mock ในระบบ**: เครื่องที่ไม่มี GPIO (เช่นโน้ตบุ๊กทีม) ปุ่มควบคุม
door/ไฟ/aroma จะถูก**ปิดจริง**และการ์ดระบบแจ้ง "เชื่อมต่อไม่ได้" พร้อมสาเหตุ —
sensors/เพลง/session ใช้ได้ปกติ · เครื่องเล่นเสียงเลือกอัตโนมัติ `mpv` →
`afplay` → `ffplay` (ตัว fallback เล่น/หยุด/วนซ้ำได้ แต่ pause ไม่ได้)

## ติดตั้งบน Raspberry Pi (เครื่องเป้าหมายจริง)

```bash
sudo apt update
sudo apt install -y python3-venv python3-lgpio mpv
cd ~/pi5_local_webapp
./run.sh
```

เปิดจากแท็บเล็ต: `http://<IP-ของ-Pi>:8000`

## ขา GPIO (BCM numbering)

เอกสาร Wiring/Software contract ฉบับเต็ม:
[ZEEP Pod GPIO Datasheet v1.0](../docs/zeep-pod-gpio-datasheet-v1.0.md) ·
[GPIO Pinout CSV](../docs/zeep-pod-gpio-pinout-v1.0.csv)

Door Open 17 · Door Close 27 · Lighting Room (LED) 22 · Star Light 4 ·
Aroma1 5 · Aroma2 6 · Aroma3 13 · Aroma4 19 · Steam 26 · Red Light 23/24/25
— เปลี่ยนได้ผ่านตัวแปร `GPIO_*`

⚠️ GPIO ของ Pi เป็นลอจิก 3.3 V เท่านั้น — โหลด 12 V ต้องผ่าน optocoupler /
MOSFET driver / relay เสมอ ห้ามต่อตรงเด็ดขาด

## Serial / รูปแบบข้อมูล ESP32

Datasheet, physical range, field alias, JSON envelope v1 และ byte map BCG ดูที่
[Sensor Interface Contract v1.0](../docs/zeep-sensor-interface-contract-v1.0.md)

- BCG: `/dev/ttyUSB_HRB` @ 115200
- ESP32 hub: `/dev/ttyACM0` @ 115200 — ส่ง JSON บรรทัดละ 1 object เช่น
  `{"lux":26.1,"temperature_c":24.1,"humidity_rh":56.0,"sound_dbfs":-29.5}`

ชื่อ field ที่รับได้ (ตัวแรกที่เป็นตัวเลขชนะ) — temperature:
`temperature_c|temperature|temp|temp_c` · humidity: `humidity|hum|rh|humidity_rh` ·
lux: `lux|light|illuminance` · sound: `sound_dbfs` เท่านั้น

ถ้า ESP32 เงียบเกิน `ESP32_STALE_SECONDS` (ค่าเริ่มต้น 5 วิ) ทั้งที่พอร์ตยังเปิดอยู่
จอจะแสดงเป็น stale/disconnected แทนการโชว์ค่าเก่าค้างเหมือนเป็นค่าจริง

## การแสดงค่าเสียง SPH0645

`magnitude = round(abs(sound_dbfs), 1)` และ
`dBA_est = magnitude × (1 - error_percent / 100)` — รุ่นปัจจุบันใช้
`error_percent = 0.0` จึงเท่ากับ `dBA_est = magnitude` โดยไม่ลด 3% และเก็บค่าใน
`calibration.json` ข้าง `app.py`:

```json
{"sound_dbfs_error_percent": 0.0,
 "calibrated_at": "2026-09-03T00:31:40+07:00",
 "method": "round(abs(raw sound_dbfs), 1), no percentage reduction",
 "operator": "super"}
```

ลำดับความสำคัญ: env `SOUND_DBFS_ERROR_PERCENT` >
`calibration.json` > ค่าเริ่มต้น `0.0` ค่าที่ใช้จริงและที่มาดูได้ใน
`/api/state → system.sound_transform`

ตัวอย่าง: raw `-39.69 dBFS` → magnitude `39.7` →
`39.7 dBA est.`

**นี่คือค่าประเมินสำหรับ Field Trial ไม่ใช่ค่า SPL/dBA ที่สอบเทียบแบบ
traceable ด้วยเครื่อง Class 1/2** ค่า `sound_dbfs` ดิบยังคงถูกเก็บโดยไม่แก้ไข
เพื่อใช้ตรวจสอบและสอบเทียบใหม่

หน้าจอผู้ใช้แสดงค่าประเมินช่วง `0–120 dBA est.` และไม่แสดงค่า dBFS ติดลบ
ถ้าค่าประเมินที่คำนวณได้ต่ำกว่า 0 ระบบจะคงค่าที่ valid ก่อนหน้า; ถ้าเกิน 120
จะแสดง 120 พร้อมคำเตือน โดย API เก็บ `sound_dba_est_unbounded` ไว้วิเคราะห์
การจำกัดช่วงแสดงผลไม่ใช่การสอบเทียบและไม่ทำให้ค่าที่วัดแม่นยำขึ้น

ค่าที่เผยแพร่ไปทุกหน้าจอในรอบวิเคราะห์ 10 วินาทีเป็น **energy average
(Leq)** ของตัวอย่าง dBA est. ที่เข้ามาในรอบนั้น ไม่ใช่ค่าตัวอย่างสุดท้ายและไม่ใช่
ค่าเฉลี่ยเลขคณิตของเดซิเบล ค่า raw/latest และสรุป `min/max/span/sample_count`
อยู่ใน Admin `/api/state → system.sound_analysis` เพื่อ Debug เท่านั้น

เวลาสอบเทียบ CEM DT-8852 ให้ใช้ A-weighting + SLOW และเลือกช่วงที่ครอบคลุม
ค่าจริง (`LO 30–80 dBA` สำหรับสภาพแวดล้อมนอน) ห้ามใช้แถวที่หน้ามิเตอร์ขึ้น
`UNDER`/`OVER` และต้องเทียบค่าเฉลี่ยช่วงเวลาเดียวกัน รายละเอียด field test ล่าสุด:
`../docs/sph0645-cem-dt8852-field-calibration-2026-08-26.md`

## Audio output

บน Pi โปรแกรม `mpv` จะเลือก USB ALSA card id ที่เสถียร
`alsa/plughw:CARD=Device,DEV=0` อัตโนมัติเมื่อพบ `/proc/asound/Device`
หากเปลี่ยนลำโพงสามารถกำหนด `MPV_AUDIO_DEVICE` ใน `.env` ได้

## Sensor และ network fallback

- เมื่อข้อมูล ESP32 เก่ากว่า `ESP32_STALE_SECONDS` ระบบจะทำเครื่องหมาย stale
  และคงค่าล่าสุดพร้อม `fallback_active=true` กับ `data_age_s` โดยไม่แสดงว่าเป็น
  ค่าปัจจุบัน
- หาก WebSocket หลุด Dashboard จะอ่าน `/api/state` ทุก 2 วินาทีและ reconnect
  อัตโนมัติ หากทั้งสองช่องทางล้มเหลวจะคงหน้าจอล่าสุดพร้อมบอกอายุข้อมูล และ
  ป้องกันการส่งคำสั่งควบคุมจนกว่า server จะกลับมาเชื่อมต่อ

## การส่งคำสั่งแอร์ผ่าน IR

- Pi จัดคำสั่ง Control Hub 1 เป็นคิวเดียวเพื่อไม่ให้ IR สองคำสั่งยิงชนกัน
- เว้นอย่างน้อย `CONTROLHUB1_MIN_IR_GAP_SECONDS` ระหว่างเฟรม (เริ่มต้น 1.2 วินาที)
- เมื่อเปิดแอร์ ระบบส่ง `on` แล้วรอ `CONTROLHUB1_POWER_ON_SETTLE_SECONDS`
  (เริ่มต้น 2.0 วินาที) ก่อนส่งอุณหภูมิเริ่มต้น
- เมื่อปรับแรงลม ระบบส่ง `status` และรอ ACK เพื่อปลุก ESP ก่อน จากนั้นรอ
  `CONTROLHUB1_FAN_WAKE_SETTLE_SECONDS` (เริ่มต้น 0.25 วินาที) แล้วจึงส่ง `fan`
  โดยทั้งคู่ทำงานภายใต้ command lock เดียวกัน; ถ้า `status` ไม่สำเร็จ ระบบจะ
  ไม่ส่ง `fan` และจะไม่ขยับเลขระดับอ้างอิงบน Pi
- ACK จาก ESP32 ยืนยันเพียงว่าโค้ดส่ง IR ทำงานแล้ว ไม่ได้ยืนยันว่าแอร์รับคำสั่ง
  เพราะยังไม่มี feedback จากตัวแอร์ จึงใช้สถานะ `ir_transmitted_unverified`
- ไม่ retry เฟรม IR อัตโนมัติจนกว่าจะยืนยันว่า Power code เป็น discrete ON/OFF
  ไม่ใช่ toggle มิฉะนั้นการยิงซ้ำอาจทำให้แอร์กลับไปอยู่สถานะเดิม

## Pi-local Safety Supervisor

Dashboard มี Supervisor บน Pi ที่ตรวจ GPIO, ความสดของข้อมูล ESP32, ค่า CO₂
แบบ NDIR, BCG และ Wi-Fi ทุก 1 วินาที ระบบเริ่มใน Monitor mode และไม่ยอม Arm
เมื่อมี blocking/critical fault เมื่อเข้า Safe Mode แบบ latch จะหยุดเพลง,
ปิด Aroma/Steam, ปลด GPIO drive ประตูทั้งสองทิศ และเปิดไฟในตู้ โดยยังไม่เปิด
ประตูอัตโนมัติหรือสั่ง ventilation จนกว่าจะมี hardware interface และตาราง
fault response ที่ทดสอบแล้ว

ผู้ใช้สามารถ Login และเริ่ม Session เพื่อบันทึกข้อมูลได้ในทุกสถานะของ Safety
Supervisor โดยไม่ต้อง `READY + ARMED`; การเริ่ม Session ไม่ได้ให้สิทธิ์สั่งอุปกรณ์
หรือเปิด Auto Response. ระหว่าง emergency latch ระบบบล็อกการปิดประตู,
Aroma/Steam, เล่น/ต่อเพลง และปิดไฟ แต่ยังอนุญาตเปิดประตู, หยุดเพลง และเปิดไฟได้
systemd `WatchdogSec=15s` จะ restart service หาก heartbeat ของ
Supervisor หยุด ตั้งค่าเกณฑ์ที่ผ่านการอนุมัติผ่าน `.env` เท่านั้น:
`SAFETY_REQUIRE_CO2`, `SAFETY_CO2_WARN_PPM`, `SAFETY_CO2_CRITICAL_PPM`,
`SAFETY_TEMP_WARN_MIN_C/MAX_C`, `SAFETY_TEMP_CRITICAL_MIN_C/MAX_C` และ
`SAFETY_ARMED_DEFAULT`. ก่อน Arm ต้องกำหนด
`SAFETY_THRESHOLD_BASIS_VERSION` และให้ผู้ทบทวนที่มีคุณสมบัติอนุมัติผ่าน
`SAFETY_THRESHOLD_BASIS_APPROVED=1`. Basis ปัจจุบันคือ
[`ZEEP-ATMOSPHERE-OPS-v1.0`](../docs/zeep-atmosphere-operating-basis-v1.0.md):
CO₂ >1,000 ppm หรืออุณหภูมิออกนอก 17–28°C เป็น Warning; CO₂ ≥1,300 ppm
หรืออุณหภูมิออกนอก 13–32°C เป็น Critical. ทั้งหมดเป็น **ZEEP internal
operating policy** ไม่ใช่เพดานสุขภาพหรือเกณฑ์การแพทย์. Session ที่เริ่ม
ขณะระบบไม่พร้อมยังบันทึกข้อมูลได้ แต่ Auto Response และคำสั่งอุปกรณ์ยังยึด Safety
guard เดิมทุกครั้ง.

## Guard ความปลอดภัยของ door / pulse

- คำสั่งประตูเป็น pulse (ไม่ค้าง HIGH) · มี lock กันคำสั่งซ้อน (ได้ `429`) ·
  ขาถูกดึง LOW เสมอแม้ request ถูกยกเลิกกลางคัน
- Aroma/steam มี lock รายช่อง + cooldown (`PULSE_COOLDOWN_SECONDS` ค่าเริ่มต้น 1 วิ)
- ระบบนี้เป็น **bench software ก่อนผ่าน G1**: ยังห้ามมีคนนอนค้างคืน · เรื่อง
  mechanical egress และ wiring truth table อยู่ใน `governance/` ไม่ใช่ที่นี่

## การเล่นเพลง

- Backend: `mpv` บน Pi (pause / volume สด / loop ผ่าน IPC) · เครื่องที่ไม่มี mpv
  ใช้ `afplay`/`ffplay` — เล่น/หยุด/วนซ้ำได้, pause จะตอบ `501` พร้อมคำอธิบาย
- Volume ถูกจำกัด **0–100** (ไม่มี digital gain เกิน unity — ไม่ใช่ SPL limit
  ระดับเสียงจริงให้คุมที่แอมป์/ลำโพง)
- เพลงจบเอง → state เคลียร์อัตโนมัติ (มี watcher ตาม process)
- checkbox "วนซ้ำ" บนจอ = `loop: true` เล่นต่อเนื่องทั้งคืน

## ชุดเสียงสำหรับการนอน (wellness audio — ออกแบบสำหรับลำโพง)

```bash
python3 generate_brainwaves.py --minutes 30
```

**ทุกเพลงเล่นผ่านลำโพงได้ — ไม่มี binaural, ไม่ต้องใช้หูฟัง** · หลักการ:
เสียงผสมหลายย่าน (multi-band mix) บนพื้น pink noise นุ่ม ๆ โทนต่ำฝังข้างใน
แกว่งช้าตามย่าน delta/theta/alpha → เสียง**สม่ำเสมอ**ตลอดไฟล์ ไม่มีช่วงเงียบ-ดัง
สะดุด (noise ซ้าย/ขวาแยกชุดกันให้เสียงกว้างเป็นธรรมชาติ ส่วนโทนเหมือนกันสองข้าง)

| ไฟล์ | รูปแบบ | ใช้ช่วง |
|---|---|---|
| `Sleep-01-Night-Delta-Mix` | noise + โทน 100/55 Hz แกว่ง 2 Hz | เปิดต่อเนื่องช่วงกลางดึก |
| `Sleep-02-WindDown-Theta-Mix` | noise + โทน 150 Hz แกว่ง 6 Hz + swell คล้ายทะเล | เตรียมเข้านอน |
| `Sleep-03-Nap-ThetaAlpha-Mix` | โทนสว่างขึ้น แกว่ง 8 Hz | งีบกลางวัน 20–30 นาที (ปิดวนซ้ำ) |
| `Sleep-04-Relax-Alpha-Mix` | คู่เสียงประสาน 132+198 Hz แกว่ง 10 Hz | ผ่อนคลายหัวค่ำ |
| `Sleep-05-Rain-Pink-Mix` | noise ล้วนแกว่งช้าสองชั้น (ไม่มีโทน) | กลบเสียงรบกวน |

ขอบเขตการเคลม: เป็น wellness ambience ตั้งชื่อตาม**บริบทการใช้และความถี่
modulation** — **ไม่เคลมผลการนอนหรือผลทางสรีรวิทยา** (ดู `docs/sound-engine.md`)
และระดับเสียงกลางคืนเป้าหมาย ≤ 35 dB(A)

## Session รายบุคคล (profiles & history)

ผู้ทดสอบ login ที่หน้าจอด้วย username + เพศ (ชาย/หญิง/อื่น ๆ/ไม่ระบุ) — ระหว่าง
session ระบบเก็บ Temperature/Humidity/Lux/dBA est./HR/RR/bed status/sleep state ทุก
`SESSION_SAMPLE_SECONDS` (ค่าเริ่มต้น 10 วิ), `SESSION_SAMPLE_LIMIT` (ค่าเริ่มต้น
12,000 จุด ≈ 33 ชั่วโมง 20 นาที; Session เดิม 5 วิยังคงอ่านตาม cadence เดิม) และนับจำนวนคำสั่ง door/pulse/music
กด "ออกจากระบบ" → บันทึกลงเครื่อง + แสดงรายงานอ่านง่าย · ถ้า server ถูกปิด
กลางคัน session ที่ค้างจะถูกบันทึกให้อัตโนมัติ

ข้อมูลทั้งหมดอยู่ **บนเครื่องเท่านั้น** (`data/` ถูก gitignore) — เป็นข้อมูลส่วนบุคคล
(ชื่อ + แนวโน้ม HR/RR): ห้ามส่งต่อโฟลเดอร์ `data/` และลบได้จริงด้วยปุ่ม
"ลบข้อมูลผู้ใช้" (`DELETE /api/users/{username}`) ตามหลัก PDPA
HR/RR เป็นค่า directional จาก sensor (pre-G2) ไม่ใช่ medical measurement

### การอ่านการ์ด Biosignal · BCG LSM-800-T

- กราฟสะสมข้อมูลล่าสุดสูงสุด 300 จุดจากหลาย packet แทนการแสดงเพียง 25 จุดล่าสุด เพื่อให้เห็นรูปแบบต่อเนื่องมากขึ้น
- แกนตั้งเป็นแรงสั่นสะเทือนเชิงกลแบบสัมพัทธ์ (`a.u.`) และใช้ percentile 5–95 ลดผลของ spike; ยังไม่ใช่หน่วยแรงที่ calibrate แล้ว
- เส้นประกลางกราฟคือค่ากึ่งกลางของข้อมูลในหน้าต่างล่าสุด ไม่ใช่เส้น ECG baseline
- ข้อความใต้กราฟแปล status code ของอุปกรณ์และบอกว่าช่วงนั้นควรอ่านค่าได้หรือควรรอ เช่น off-bed, movement หรือ heavy object
- HR/RR เป็นค่าที่ firmware/sensor สรุปให้ ไม่ได้คำนวณจากยอดคลื่นที่ผู้ใช้เห็นโดยตรง และ movement อาจรบกวนค่าได้
- กราฟไม่มีแกนเวลาแบบวินาที เพราะ sampling/configuration ของ hardware record ยังต้องยืนยัน จึงแสดงเป็น “จำนวนจุดล่าสุด” โดยไม่สร้าง time scale ที่ยังไม่มีหลักฐาน
- Sleep state บน Dashboard แสดง Wake/N1/N2/N3/REM เป็น **exploratory estimate**
  พร้อม confidence/data status; G2 เปรียบเทียบ W/N1/N2/N3/REM โดยตรงกับ PSG
  epoch 30 วินาที และรายงาน 3-class collapse เพิ่มเป็น secondary analysis

## Sleep State (est.) — internal telemetry

แถบในการ์ด BCG รับ Sensor frame ทุก 10 วินาที สร้าง evidence ทุก 30 วินาที
จาก rolling 6 ชุด (60 วินาที; `bcg-audio-bed-5state-v1.20-sleep-onset-guard`)
และยืนยัน State เมื่อ candidate เดิมต่อเนื่อง 2 epoch/60 วินาที; EMA เป็น continuity หลัก
ของ W/N1/N2/REM ส่วน N3 ที่ชนะและผ่าน physiology gate ใช้หลักฐานปัจจุบันก่อน EMA
เพื่อไม่ให้การกรองซ้ำกด N3 ที่มีหลักฐานครบจนหายไป ช่วง 5 นาทีแรกคง W เพื่อเก็บ
Awake/settling evidence และจะเข้า N1 ได้เมื่อเตียงนิ่งพร้อม HR/RR ลดลงต่อเนื่อง
ครบเงื่อนไข 2 evidence epochs; เวลาเริ่ม Session หรือความนิ่งเพียงอย่างเดียวสร้าง N1 ไม่ได้:

| หลักฐานเด่น | ผลแบบ exploratory |
|---|---|
| ไม่อยู่บนเตียง/ขยับเด่น หรือ HR/RR ใกล้ awake baseline | **Wake** |
| เพิ่งลดจาก Wake, movement ลด, อยู่ในช่วงเปลี่ยนผ่าน | **N1** |
| HR/RR ลดและค่อนข้างสม่ำเสมอ | **N2** |
| HR/RR อยู่กลุ่มต่ำ, variability ต่ำมาก, movement ต่ำ | **N3 label** |
| ยังอยู่บนเตียงแต่ HR/RR variability สูงขึ้น + time prior | **REM label** |

เกณฑ์ปรับได้: `SLEEP_MOVE_WAKE_RATIO` · `SLEEP_HR_CV_REM` · `SLEEP_HR_CV_DEEP` ·
`SLEEP_MOVE_DEEP_RATIO` · `SLEEP_WINDOW_SECONDS`

**กรอบวินัย:** N1/N2/N3/REM บนหน้าจอเป็น **proxy ไม่ใช่ EEG/EOG/EMG staging** —
คลาสที่บันทึกคือ `wake/n1/n2/n3/rem` พร้อม estimator/evidence version; G2 primary
เปรียบเทียบ W/N1/N2/N3/REM แบบ one-to-one ส่วนการยุบ N1/N2/N3 เป็น NREM เป็น
secondary robustness analysis ตาม [ZEEP Sleep-State Baseline v1.5](../docs/zeep-sleep-state-baseline-v1.0.md)
**ห้ามใช้เป็นเงื่อนไขควบคุมอุปกรณ์** · ทุก record ติด `sleep_estimator` version
เพื่อ provenance · แอปผู้บริโภคยังห้ามแสดง sleep state จนผ่าน G2

## AI Adaptive — Personal Baseline (เรียนรู้ 3–7 คืนแรก)

ระบบไม่ใช้ตัวเลขตายตัวกับทุกคน: หลังผู้ใช้บันทึกการนอนครบ **3 คืน**
(คืนละ ≥20 นาที, ใช้ล่าสุดสูงสุด 7 คืนแบบ rolling) ระบบจะคำนวณค่าเฉพาะบุคคล
จากข้อมูลของเขาเองใน SQLite:

- Awake HR baseline (ช่วงขยับ/ช่วงแรกหลังขึ้นเตียง) · Sleeping median HR/RR ·
  Lowest stable HR/RR (p10) · ความแปรปรวน HR ปกติ (rolling CV p25/median/p75) ·
  Movement baseline · เวลาที่มักเข้านอน/ตื่น
- ค่าเหล่านี้ถูกใช้ **เลื่อนช่วง HR/RR ของ staging engine** (Wake/N1/N2/N3/REM)
  จาก age/gender default มาหาตัวจริงของผู้ใช้ (จำกัดการเลื่อน ±15 bpm / ±4 rr)
- แผง **AI Adaptive** ในการ์ดประวัติแสดงสถานะการเรียนรู้ (n/3 คืน) +
  คำแนะนำจากข้อมูลของเขาเอง · `GET /api/baseline/{username}`
- Baseline อัปเดตอัตโนมัติหลัง logout ทุกครั้ง · เก็บที่ `data/baselines.json`
  (ข้อมูลส่วนบุคคล — gitignored)

🔴 **ขอบเขตตาม KB**: ชั้นนี้ทำได้แค่ *เรียนรู้ / ปรับเกณฑ์การอ่านค่า / แนะนำ*
— **ไม่สั่งอุปกรณ์อัตโนมัติจาก sleep state** จนกว่าจะผ่าน G2
(`docs/closed-loop-spec.md`) และการปลุกใด ๆ ต้องอิงเวลานาฬิกา ไม่ผูก stage

## Auth และ Service automation

```bash
cp .env.example .env
# ตั้ง POD_ID, Local Admin hash และ coordinator ตาม deployment จริง
./run.sh
```

Browser ใช้ HttpOnly cookie และ CSRF โดยอัตโนมัติ ห้ามใส่ token ใน URL หรือ
`localStorage` หากมี automation ภายในระบบจึงค่อยตั้ง `API_TOKEN` และส่ง
`X-Api-Token` จาก service ที่ได้รับอนุญาต ค่าอ่านสถานะ, WebSocket, History และ
Control ไม่เปิดแบบ anonymous แม้ไม่ได้ตั้ง `API_TOKEN`

Local Admin รองรับบัญชี break-glass เดิมจาก `LOCAL_ADMIN_USERNAME` /
`LOCAL_ADMIN_PASSWORD_HASH` และบัญชีเพิ่มเติมจาก `LOCAL_ADMIN_ACCOUNTS_FILE`
(ค่าเริ่มต้น `data/local_admins.json`) รูปแบบไฟล์คือ
`{"version":1,"accounts":[{"username":"operator","password_hash":"scrypt$...","enabled":true}]}`
ไฟล์ต้องมีเฉพาะ scrypt hash, ไม่ใส่ plaintext password, ตั้ง permission `0600`
และไม่ commit เข้า Repository ระบบอ่านไฟล์ตอน service start และ Admin แต่ละคน
จะมี subject/audit identity ของตนเอง

## Wi-Fi hotspot บน Pi (NetworkManager)

```bash
sudo nmcli device wifi hotspot ifname wlan0 con-name PiPrivate ssid Pi5-Control password 'เปลี่ยนรหัสนี้'
ip -4 addr show wlan0
```

## เปิดใช้ผ่าน URL จากภายนอก

ดูแผนเต็มใน [REMOTE-ACCESS.md](REMOTE-ACCESS.md) — Tailscale (ภายในทีม, ~30 นาที)
→ Cloudflare Tunnel + `pod.zeep.world` + Access (อีเมลทีม) · **ห้าม port forward
ตรงจาก router** เด็ดขาด
