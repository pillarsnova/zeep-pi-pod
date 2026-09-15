# ZEEP Pi 5 Regression / Safety Tests

รันจาก root ของ repository โดย activate environment ก่อน (`source
pi5/.venv/bin/activate` บน Mac workspace หรือ `source .venv/bin/activate`
บน Pi) ชุดเร็วใช้ตรวจระหว่างแก้ module ส่วนชุดเต็มเป็น release gate ก่อน
push/deploy

ตัวเลข `1,027 tests` เป็น pushed baseline ของ commit `d2c7af7` และหมายถึง **Pi
application suite ที่ root repository เท่านั้น** จำนวนจริงอาจเพิ่มเมื่อมี
regression ใหม่ และต้องรายงานจากผลรันแต่ละครั้ง ตัวเลขนี้ไม่รวมการประกอบ UI,
Evidence registry check หรือ Ruff จึงห้ามใช้เพียงอย่างเดียวเพื่อประกาศว่า Full
Product Gate ผ่าน

Working candidate วันที่ 16 กันยายน 2026 เพิ่ม regression 33 เคส และรันล่าสุด
ผ่าน `1,060 tests`; ตัวเลขนี้เป็นหลักฐานของ candidate ไม่ใช่ Production smoke

## Fast focused suites

```bash
# Hardware และขอบเขต module
python -m unittest -q \
  test_modular_architecture.py test_sensor_contract.py \
  test_sensor_services.py test_api_state_projection.py \
  test_bcg_reader.py test_sensor_frame_sampler.py \
  test_control_protocol.py test_audio_api.py \
  test_session_lifecycle.py test_session_finalization_commit.py

# Sleep State, Baseline และคะแนน
python -m unittest -q \
  test_sleep_signal_features.py test_sleep_system_consistency.py \
  test_sleep_baseline_policy.py test_personal_baseline_policy.py \
  test_sleep_session_report.py test_recovery_policy_guardrails.py

# API, สิทธิ์ และ Privacy
python -m unittest -q \
  test_rbac_api.py test_access_and_occupancy.py \
  test_usage_session_api.py test_user_ai_context.py
```

เมื่อแก้ UI ให้รันเพิ่ม:

```bash
python -m unittest -q test_ui_composer.py
python ui_composer.py check
```

เมื่อแก้การดึง snapshot จาก Pod ให้รันเพิ่ม (ใช้ข้อมูลจำลองใน temporary directory
และไม่เชื่อมต่อ Production):

```bash
python -m unittest -q \
  test_pod_data_sync.py test_workstation_approval.py \
  test_pod_snapshot_export_limits.py
```

## Application release gate

Pi application suite เก็บไฟล์ `test_*.py` ที่ root โดย pushed baseline มี 1,027 tests
ที่ commit `d2c7af7` และต้องผ่านโดยไม่มี failure/error ก่อน push หรือ deploy ส่วน
JSON Schema test ต้องมี `jsonschema` จาก `requirements-dev.txt`; เป้าหมาย Code
Freeze คือ `skipped=0`

```bash
python -m unittest discover -q
python ui_composer.py check
ruff check zeep_pod
ruff format --check zeep_pod
python -m py_compile app.py *.py
git diff --check
```

## Production Pi smoke gate

หลัง Mac ผ่าน Application release gate แล้ว ให้ Pi รัน smoke tests ก่อน restart:

```bash
python -m unittest -q \
  test_modular_architecture.py test_sensor_services.py test_control_protocol.py
```

ชุดนี้ตรวจขอบเขต module, Sensor services และ Control protocol เท่านั้น จำนวนจริง
เพิ่มได้ตาม regression ใหม่และต้องรายงานจากผลรัน ไม่ใช่ Full Product Gate หากแก้
Sleep, Session, Auth หรือ API ต้องเพิ่ม focused suite ของส่วนนั้นก่อน restart

## v1 Code Freeze / Full Product Gate

Code Freeze ต้องผ่าน Application release gate ด้านบนและ Evidence gate:

```bash
# Evidence JSON/Markdown, HTTPS, path containment และ checksum policy
python research/evidence-library/update_research_library.py check
```

`firmware/sensorhub1-esp32s3/` เป็น replacement candidate ที่ยกเลิกและระบุ
`ARCHIVED / DO NOT FLASH` ตั้งแต่ 10 กันยายน 2569 จึงไม่ใช่ v1 Production
runtime หรือ Code-Freeze gate การรับ `sound_dba` และความเป็นอิสระของ Sensor Hub 1
ถูกตรวจใน root suite ที่ `test_sensor_contract.py`, `test_sensor_services.py` และ
`test_sensorhub1_reader.py` อยู่แล้ว ห้ามนำ archived image ไป Flash เพียงเพราะ
historical DSP tests หรือ PlatformIO build ผ่าน

บน GitHub ต้องยืนยันว่า workflows ต่อไปนี้ผ่าน:

- `Python architecture and style`
- `Evidence library integrity`

## ขอบเขตที่ห้ามลด Coverage

- Auth/RBAC, CSRF, QR Login, Account erasure และข้อมูลผู้ใช้ไม่รั่วออกนอก Pod
- Sensor contract/calibration, physical-control guard และ local safety supervisor
- Sleep State/Baseline, Sleep Score, Recovery Score, report และ historical audit
- SQLite integrity, backup/restore และ maintenance tool แบบ dry-run/guarded apply
- API/OpenAPI, Pydantic compatibility และ legacy stored-session compatibility
- Evidence registry: schema, Markdown↔JSON, HTTPS, path containment และ checksum

`testing_support.py` ต้องย้าย data, backup, music และ event log ไปยัง temporary
directory เสมอ Tests จึงห้ามอ่าน เขียน หรือล้าง Production DB/log จริง

Test ที่ซ้ำสามารถรวม assertion หรือ fixture ได้ แต่จะลบได้ต่อเมื่อ route/code/data
format นั้นถูก retire ทั้งชุด หรือมี behavioral regression test ทดแทนแล้วเท่านั้น

## Definition of done

1. Live/Replay/Report ใช้ version จาก `sleep_system_policy.py`
2. Sensor alias/range มาจาก `sensor_contracts.py`
3. Offline tool ทุกตัวอยู่ใน `maintenance_registry.py` และประกาศ write/preserve/guard
4. `static/index.html` ต้องตรงกับ template + Control partials
5. Tests ต้องผ่านโดยใช้ temp data; ห้ามอ่าน/ล้าง production DB
6. Evidence JSON Schema, Markdown↔JSON consistency, HTTPS/path containment และ checksum quarantine ต้องผ่าน CI
7. Archived Firmware tests ไม่ใช่หลักฐานว่า Production Firmware ผ่าน
8. Code Freeze ต้องไม่มี skipped test ใน environment ที่ติดตั้ง dev dependenciesครบ
