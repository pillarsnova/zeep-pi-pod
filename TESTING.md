# ZEEP Pi 5 Regression / Safety Tests

รันทั้งหมดจากโฟลเดอร์ `pi5`:

```bash
python -m unittest discover -p 'test_*.py'
python ui_composer.py check
```

## กลุ่มงาน

| กลุ่ม | ไฟล์ |
|---|---|
| Auth/RBAC/Occupancy/API | `test_access_and_occupancy.py`, `test_rbac_api.py` |
| Sensor/Calibration/Contract | `test_sensor_contract.py`, `test_recalibrate_sound_history.py` |
| Sleep signal/evidence/policy | `test_sleep_signal_features.py`, `test_sleep_baseline_policy.py`, `test_personal_baseline_policy.py`, `test_sleep_system_consistency.py` |
| Session report/annotation/replay | `test_sleep_session_report.py`, `test_sleep_stage_annotations.py`, `test_reclassify_sleep_history.py` |
| Session upload to ZEEP account | `test_session_ingest.py` |
| Data maintenance/safety | `test_backup.py`, `test_cleanup_short_sessions.py`, `test_reset_sleep_dataset.py`, `test_trim_session.py`, `test_maintenance_registry.py` |
| UI composition | `test_ui_composer.py` |

`testing_support.py` เป็น helper ที่ตั้ง environment ชั่วคราว ไม่ใช่ test และจึงไม่ใช้
prefix `test_` อีกต่อไป ไม่มี regression test เดิมถูกลบ เพราะทุกไฟล์ยังครอบคลุม
guard ที่ใช้งานอยู่จริง; การลบ test ต้องแสดงว่าพฤติกรรมนั้นไม่มี route/code/data format
เหลืออยู่และมี test ทดแทนก่อน

## Definition of done

1. Live/Replay/Report ใช้ version จาก `sleep_system_policy.py`
2. Sensor alias/range มาจาก `sensor_contracts.py`
3. Offline tool ทุกตัวอยู่ใน `maintenance_registry.py` และประกาศ write/preserve/guard
4. `static/index.html` ต้องตรงกับ template + Control partials
5. Tests ต้องผ่านโดยใช้ temp data; ห้ามอ่าน/ล้าง production DB
