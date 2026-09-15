# ZEEP Pi 5 Regression / Safety Tests

รันจาก root ของ repository โดย activate environment ก่อน (`source
pi5/.venv/bin/activate` บน Mac workspace หรือ `source .venv/bin/activate`
บน Pi) ชุดเร็วใช้ตรวจระหว่างแก้ module ส่วนชุดเต็มเป็น release gate ก่อน
push/deploy:

```bash
# Hardware และขอบเขต module
python -m unittest -q \
  test_modular_architecture.py test_sensor_contract.py \
  test_sensor_services.py test_control_protocol.py test_session_lifecycle.py

# Sleep State, Baseline และคะแนน
python -m unittest -q \
  test_sleep_signal_features.py test_sleep_system_consistency.py \
  test_sleep_baseline_policy.py test_personal_baseline_policy.py \
  test_sleep_session_report.py test_recovery_policy_guardrails.py

# API, สิทธิ์ และ Privacy
python -m unittest -q \
  test_rbac_api.py test_access_and_occupancy.py \
  test_usage_session_api.py test_user_ai_context.py

# Full release gate
python -m unittest discover -q
python ui_composer.py check
```

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
