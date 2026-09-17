# ZEEP Pi 5 Regression / Safety Tests

รันจาก root ของ repository โดย activate environment ก่อน (`source
pi5/.venv/bin/activate` บน Mac workspace หรือ `source .venv/bin/activate`
บน Pi) ค่าเริ่มต้นคือทดสอบเฉพาะส่วนที่เปลี่ยน ไม่รัน Full suite ซ้ำบน Mac, CI และ
Pi โดยไม่มีเหตุผล

จำนวน Test เปลี่ยนตาม Revision จึงต้องรายงานจากผลรันจริงพร้อม Git SHA ทุกครั้ง
และห้ามใช้จำนวน Test เพียงอย่างเดียวประกาศว่า Full Product Gate ผ่าน เพราะการประกอบ
UI, Evidence registry, Ruff และ Production smoke เป็นคนละ Gate

## คำสั่งที่ใช้เป็นค่าเริ่มต้น

```bash
# ตรวจไฟล์ที่ต่างจาก origin/develop แล้วเลือกเฉพาะ domain ที่เกี่ยวข้อง
python quality_gate.py changed

# เลือกเองได้หนึ่งหรือหลาย domain
python quality_gate.py sensor
python quality_gate.py ui control

# ดูแผนโดยยังไม่รัน
python quality_gate.py changed --dry-run

# ใช้เมื่อไม่มั่นใจ งานข้ามระบบ หรือก่อน Freeze
python quality_gate.py full
```

Domain ที่รองรับ: `core`, `ui`, `sensor`, `control`, `sleep`, `score`, `session`,
`auth`, `history`, `data`, `sync` และ `evidence` การแก้ไฟล์ Test/Infrastructure
จะยกระดับตามความเสี่ยงโดยอัตโนมัติ

## Focused suites

ใช้ `quality_gate.py` เป็นทางหลัก รายการด้านล่างเป็นคำสั่งอ้างอิงเมื่อต้องการ
ควบคุม Test module ด้วยตนเอง

```bash
# Hardware และขอบเขต module
python -m unittest -q \
  test_modular_architecture.py test_sensor_contract.py \
  test_sensor_services.py test_api_state_projection.py \
  test_bcg_reader.py test_sensor_frame_sampler.py \
  test_gpio_lifecycle.py test_occupancy_lifecycle.py \
  test_control_protocol.py test_audio_api.py test_audio_lifecycle.py \
  test_session_lifecycle.py test_session_finalization_commit.py

# Sleep State, Baseline และคะแนน
python -m unittest -q \
  test_sleep_signal_features.py test_sleep_system_consistency.py \
  test_sleep_baseline_policy.py test_personal_baseline_policy.py \
  test_personal_baseline_lifecycle.py \
  test_historical_replay_runtime.py test_historical_replay_storage.py \
  test_reclassify_sleep_history.py \
  test_sleep_session_report.py test_recovery_policy_guardrails.py

# API, สิทธิ์ และ Privacy
python -m unittest -q \
  test_rbac_api.py test_access_and_occupancy.py \
  test_auth_session_lifecycle.py \
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

## นโยบายก่อน Push และ Deploy

### งานปกติ

1. รัน `python quality_gate.py changed`
2. Push แล้วตรวจ workflow ที่ path ของ change นั้น trigger; Python change ต้องให้
   GitHub CI รัน Full Application suite หนึ่งครั้ง ส่วน UI/docs ใช้ gate ที่ระบุด้านล่าง
3. หาก CI/gate ที่เกี่ยวข้องผ่านบน Git SHA เดียวกัน ไม่ต้องรัน Full suite ซ้ำบน Mac
   หรือ Pi
4. ก่อน Restart Pi รันเฉพาะ Production smoke ของ domain ที่เปลี่ยน

### กรณีที่ต้องรัน Full

- แก้หลาย domain หรือแก้ contract กลางแล้วผลกระทบไม่ชัด
- เปลี่ยน test infrastructure, dependency, CI หรือ fixture กลาง
- Focused test ให้ผลแปลก, flaky หรือมีข้อสงสัย
- CI ใช้งานไม่ได้แต่ต้อง Deploy โดยตรง
- Release candidate, Code Freeze, migration ข้อมูล หรือก่อนลบ legacy behavior
- Product Owner/Reviewer ขอ Full Gate

การแก้เอกสารทั่วไปเพียงอย่างเดียวใช้ `git diff --check` และ
`python3 -m unittest -q test_documentation_alignment.py`; หากแก้ข้อความผลิตภัณฑ์
ให้เพิ่ม `test_product_language.py` ส่วน Evidence library ใช้ profile `evidence`
และไม่ต้องรัน Sleep/Sensor suite ปัจจุบัน `quality_gate.py changed` ยังไม่เลือก
docs-only profile จึงต้องรันคำสั่งเอกสารนี้ตรง ๆ จนกว่าจะเพิ่ม automated gate

## Application Full Gate

Pi application suite เก็บไฟล์ `test_*.py` ที่ root ชุดเต็มใช้ตามเงื่อนไขด้านบน
และยังเป็น CI gate ของทุก Python push ส่วน JSON Schema test ต้องมี `jsonschema`
จาก `requirements-dev.txt`; Skip ต้องมีเหตุผลและ Owner และ Freeze candidate ต้อง
บันทึกจำนวน Passed/Failed/Error/Skipped ตามผลจริง

```bash
python quality_gate.py full
```

## Production Pi smoke gate

หลัง Focused gate หรือ CI ผ่านแล้ว ให้ Pi รัน smoke tests ก่อน restart:

```bash
python -m unittest -q \
  test_modular_architecture.py test_sensor_services.py test_control_protocol.py
```

ชุดนี้ตรวจขอบเขต module, Sensor services และ Control protocol เท่านั้น ไม่ต้องรัน
Full suite ซ้ำบน Pi หาก CI ของ Git SHA เดียวกันผ่านแล้ว หากแก้ Sleep, Session,
Auth หรือ API ให้เพิ่ม focused profile ของส่วนนั้นก่อน restart

## v1 Code Freeze / Full Product Gate

Code Freeze ต้องผ่าน Application release gate ด้านบนและ Evidence gate:

```bash
# Evidence JSON/Markdown, HTTPS, path containment และ checksum policy
python research/evidence-library/update_research_library.py check
```

`firmware/sensorhub1-esp32s3/` เป็น Production test candidate แยกจาก Pi v1
application gate การ Flash เพื่อเก็บหลักฐาน Hardware ทำได้เมื่อเจ้าของอนุมัติ,
Pod ว่าง, มี Full-Flash backup และตรวจ identity/verify/rollback ครบ การ build ผ่าน
เพียงอย่างเดียวยังไม่ใช่การรับรองให้ใช้งานถาวร

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
7. Firmware unit tests เป็นหลักฐานระดับ source; ผล Hardware/CEM เป็นหลักฐานคนละชั้น
8. Code Freeze ต้องอธิบายทุก skipped test ใน environment ที่ติดตั้ง dev dependencies ครบ
