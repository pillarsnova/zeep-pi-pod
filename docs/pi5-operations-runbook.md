# ZEEP Pi 5 Operations Runbook

สถานะ: **Current operations**

ขอบเขต: Pod 1 · `/home/pod1/pi5` · `origin/develop`

## กฎก่อนแก้และ Deploy

1. ตรวจว่าไม่มีผู้ใช้งานและไม่มี Session กำลังบันทึกก่อน restart เสมอ
2. ใช้ Git จาก Mac ด้วยบัญชี `PillarsMan` และดึง Pi จาก `origin/develop` เท่านั้น
3. ห้ามแก้ Raw BCG หรือ Timeline เพื่อให้ผล Derived ดูดีขึ้น
4. ต้องผ่าน focused tests ตามส่วนที่แก้และ full regression ก่อน push
5. ใช้ `git pull --ff-only origin develop` เพื่อไม่สร้าง merge โดยไม่ตั้งใจ

## การเข้าถึง

- ต่อเครือข่าย Pod โดยตรง: `http://192.168.1.100:8000/`
- ผ่าน Tailscale: `http://pod1.starling-altered.ts.net:8000/`
- SSH: `ssh pod1@pod1.starling-altered.ts.net`

HTTP ใช้ได้เฉพาะ LAN ที่ควบคุมหรือ Tailscale encrypted overlay เท่านั้น
หากเปิดผ่าน public reverse proxy ต้องใช้ HTTPS และตั้ง
`AUTH_SECURE_COOKIE=true`

## ตรวจและทดสอบบน Mac

```bash
git status --short
git branch --show-current
git pull --ff-only origin develop
source pi5/.venv/bin/activate
python -m unittest discover -p 'test_*.py'
python ui_composer.py check
git diff --check
```

รายละเอียดชุดทดสอบแบบเร็วและแบบเต็มอยู่ใน [`TESTING.md`](../TESTING.md)

## Deploy ไป Pi

```bash
ssh pod1@pod1.starling-altered.ts.net
cd /home/pod1/pi5
git pull --ff-only origin develop
.venv/bin/python -m unittest -q \
  test_modular_architecture.py test_sensor_services.py test_control_protocol.py
sudo systemctl restart zeep-pod.service
systemctl is-active zeep-pod.service
curl -f http://127.0.0.1:8000/api/v1/public/health
```

หลัง restart ให้ตรวจ `/api/public/status`, Sensor Hub 1/2, BCG, Safety faults
และ event `SESSION resumed_after_restart` หากมี Session ที่ checkpoint ไว้

## Backup และ Retention

ระบบเขียน backup ที่ `backup/YYYYMMDD.zip` โดยรวม SQLite, Profile,
Personal Baseline และ manifest ไว้ด้วยกัน กำหนดตำแหน่งด้วย `BACKUP_DIR` และ
เก็บตาม `BACKUP_RETENTION_COUNT` ซึ่ง Production ใช้ 3 วัน

การ Reset หรือตัดข้อมูลต้องใช้เครื่องมือใน `maintenance_registry.py`
และเริ่มจาก dry-run ทุกครั้ง ห้ามเรียกเครื่องมือทำลายข้อมูลผ่าน Browser API

## Legacy JSONL Migration

รองรับเฉพาะ field unit เก่าที่ยังมี `data/sessions.jsonl` เมื่อเริ่มระบบ
`migration.py` จะนำเข้า SQLite ใน transaction เดียว และเปลี่ยนชื่อไฟล์ต้นทาง
หลังสำเร็จเท่านั้น Raw BCG ที่ไม่เคยบันทึกในระบบเก่าไม่สามารถสร้างย้อนหลังได้

## Shutdown

เมื่อเปิด `ENABLE_SYSTEM_POWEROFF=1`, `POST /api/system/shutdown` จะ finalize
Session, flush BCG/writer queue, ปิด storage, sync filesystem แล้วจึงเรียก
`systemctl poweroff` การปิดไฟตรงโดยไม่ผ่านขั้นตอนนี้เสี่ยงต่อข้อมูลไม่ครบ
