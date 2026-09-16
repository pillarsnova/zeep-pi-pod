# ZEEP Pi 5 Operations Runbook

สถานะ: **Current operations**

ขอบเขต: Pod 1 · `/home/pod1/pi5` · `origin/develop`

## กฎก่อนแก้และ Deploy

1. ตรวจว่าไม่มีผู้ใช้งานและไม่มี Session กำลังบันทึกก่อน restart เสมอ
2. ใช้ Git จาก Mac ด้วยบัญชี `PillarsMan` และดึง Pi จาก `origin/develop` เท่านั้น
3. ห้ามแก้ Raw BCG หรือ Timeline เพื่อให้ผล Derived ดูดีขึ้น
4. ต้องผ่าน risk-based focused tests ตามส่วนที่แก้ และ CI/Full gate ตาม trigger ใน
   `TESTING.md`; รัน Full local เมื่อข้ามระบบ ผลไม่แน่นอน migration หรือก่อน Freeze
5. ใช้ `git pull --ff-only origin develop` เพื่อไม่สร้าง merge โดยไม่ตั้งใจ
6. ทุก workstation ต้องเป็นเครื่องทีมที่อนุมัติแล้วและเปิด disk encryption ก่อน Sync

## การเข้าถึง

- ต่อเครือข่าย Pod โดยตรง: `http://192.168.1.100:8000/`
- ผ่าน Tailscale: `http://pod1.starling-altered.ts.net:8000/`
- SSH: `ssh pod1@pod1.starling-altered.ts.net`

HTTP ใช้ได้เฉพาะ LAN ที่ควบคุมหรือ Tailscale encrypted overlay เท่านั้น
หากเปิดผ่าน public reverse proxy ต้องใช้ HTTPS และตั้ง
`AUTH_SECURE_COOKIE=true`

## ตรวจและทดสอบบนเครื่องทีม

เริ่มงานบนเครื่องทีมที่ได้รับอนุญาตด้วยคำสั่งเดียว:

```bash
./start_work.sh
```

คำสั่งนี้ fetch และ fast-forward `origin/develop` เท่านั้น แล้วสร้าง snapshotล่าสุดจาก
Pod ผ่าน Tailscale/SSH ถ้า Tailscale ใช้ไม่ได้จึงลอง LAN `192.168.1.100` ต่อ
Snapshot เก็บที่ `private-data/pod-sync/<pod>/` และไม่ถูกนำไปใช้เป็นฐานข้อมูลของ
แอปโดยอัตโนมัติ

ก่อนใช้ครั้งแรก ผู้ดูแลต้องเปิด disk encryption และจำกัดบัญชีผู้ใช้ก่อน จากนั้น
ผู้มีอำนาจอนุมัติเครื่องจึงลงทะเบียนด้วยคำสั่ง:

```bash
sudo python3 approve_workstation.py --approved-by "ชื่อผู้อนุมัติ"
```

ระบบตรวจ FileVault บน macOS หรือ LUKS/dm-crypt บน Linux จากสถานะจริงก่อนสร้าง
marker และตรวจซ้ำทั้ง volume ปลายทางกับ directory ของ Pod ทุกครั้งก่อน Sync
การอนุมัติผูกทั้ง hostname และ stable machine ID มีอายุสูงสุด 365 วัน Marker อยู่ที่
`/Library/Application Support/ZEEP/team-workstation-approval.json` บน macOS หรือ
`/etc/zeep/team-workstation-approval.json` บน Linux ต้องเป็นของ `root` และใช้สิทธิ์
`0644` เพื่อให้ทีมอ่านตรวจได้ แต่ผู้ใช้ทั่วไปแก้ไขไม่ได้ จึงไม่สามารถสร้าง Marker เอง
หรือคัดลอก Marker ไปใช้กับเครื่องอื่นได้ หากตรวจสถานะไม่ได้ การเข้ารหัสปิดอยู่ หรือ
เจ้าของ/สิทธิ์ไฟล์ไม่ตรง ระบบจะหยุดก่อนดาวน์โหลดข้อมูลแบบ fail closed

รุ่นนี้รองรับเฉพาะ macOS ที่เปิด FileVault และ Linux ที่ใช้ LUKS/dm-crypt เท่านั้น
Windows ยังถูกปิดจนกว่าจะมี BitLocker + ACL + transport tests ครบ ห้ามอนุมัติ
ข้อยกเว้นด้วยการสร้าง Marker เอง

Marker เป็น operational approval record บนเครื่อง ไม่ใช่ลายเซ็นจากศูนย์กลาง
บัญชี OS administrator (`root`) คือ trust boundary ของรุ่นนี้ ส่วน `approved_by`
เป็น audit label เพื่อระบุผู้อนุมัติ ไม่ใช่ cryptographic identity ผู้อนุมัติต้องเป็นผู้ที่
ทีมกำหนดและต้องรันคำสั่งบนเครื่องจริง สำหรับการขยายหลายเครื่องต้องเพิ่ม signed
device registry หรือ MDM เป็น control กลางก่อน Production rollout

Snapshot Sync รุ่นนี้จำกัดขอบเขตไว้ที่ **เครื่องทีมสำหรับ Internal Pilot** เท่านั้น
เพราะยังไม่มีระบบกลางกระจายคำสั่งลบข้อมูลไปยังเครื่องที่ Offline เมื่อได้รับคำขอ
ลบข้อมูล ผู้ดูแลข้อมูลต้องใช้ทะเบียนเครื่องเพื่อลบ Snapshot ของ Pod นั้นจากทุกเครื่อง
ก่อนอนุญาตให้กลับมาวิเคราะห์อีกครั้ง การเปิดใช้ Production ต้องมี signed device
registry/MDM, erasure acknowledgement จากทุกเครื่อง และ audit log ส่วนกลางก่อน

สิ่งที่ Sync คือ `sessions.db`, `bcg.db`, Profile/Baseline และ derived report ที่
ใช้วิเคราะห์ย้อนหลัง ระบบใช้ SQLite online backup, SHA-256, path allowlist และ
`PRAGMA quick_check` ก่อนติดตั้งแบบ atomic โดยเก็บล่าสุด 3 snapshot ต่อ Pod
สำเนาที่ตรวจไม่ผ่านอาจถูกกักไว้เพื่อ Audit ได้ไม่เกิน 3 ชุดและไม่เกิน 24 ชั่วโมง
จากนั้นระบบลบในการ Sync ครั้งถัดไป
รหัสผ่าน Admin, auth session, occupancy/runtime state และ active-session
checkpoint จะไม่ถูกคัดลอก หาก Sync ไม่สำเร็จต้องคง snapshot ล่าสุดไว้และไม่แตะ
ระบบที่กำลังทำงานบน Pod

Snapshot ผูกกับ `pod_id` และ Git commit; ค่า `--pod-id` ต้องตรงกับเครื่องจริง
ระบบยืนยัน checksum/SQLite ของ response ก่อนเลือก fallback host และจำกัดขนาดข้อมูล
ตั้งแต่การ stream เพื่อไม่ให้ response ผิดปกติเติมพื้นที่ดิสก์ แต่ละ SQLite backup
มีความสอดคล้องภายในตัวเอง ส่วน `capture_window` ใน manifest ระบุชัดว่า DB หลายก้อน
ถูกสำรองต่อเนื่องและไม่ใช่ transaction เดียวกันข้ามไฟล์

ก่อนเปิดใช้กับหลายเครื่อง ให้สร้างบัญชี `zeep-sync`/SSH key แยกที่บังคับ forced
command ให้เรียก exporter นี้ได้อย่างเดียว และจำกัดด้วย Tailscale ACL; บัญชี `pod1`
ทั่วไปยังเป็นสิทธิ์ดูแลระบบและไม่ใช่ least-privilege credential สำหรับแจกทีม

ห้ามส่งต่อ snapshot, ห้ามตั้ง snapshot เป็น `DATA_DIR` และห้ามสร้าง marker บน
เครื่องส่วนตัวหรือเครื่องที่ไม่ได้เข้ารหัสดิสก์ การลบข้อมูลผู้ใช้ต้องครอบคลุมสำเนา
บน workstation ตามขอบเขต PDPA ด้วย

สำหรับ Pod อื่นให้ระบุทั้ง identity และ host ชัดเจน เช่น:

```bash
./start_work.sh --pod-id pod2 --host pod2@pod2.example.ts.net
```

หากเก็บ Snapshot บน volume เข้ารหัสอื่น ให้ใช้ `--destination` เดียวกันทั้งตอน
อนุมัติและเริ่มงาน โดยอ่านตำแหน่ง Snapshot จริงจากผล JSON ของคำสั่ง Sync:

```bash
sudo python3 approve_workstation.py \
  --approved-by "ชื่อผู้อนุมัติ" \
  --destination /Volumes/ZEEP-Encrypted/pod-sync
./start_work.sh --destination /Volumes/ZEEP-Encrypted/pod-sync
```

จากนั้นจึงตรวจและทดสอบ:

```bash
git status --short
git branch --show-current
source pi5/.venv/bin/activate
python quality_gate.py changed
git diff --check
```

หาก CI ของ Git SHA เดียวกันผ่านแล้ว ไม่ต้องรัน Full suite ซ้ำบน Pi รายละเอียด
เงื่อนไขที่ต้องใช้ `python quality_gate.py full` อยู่ใน
[`TESTING.md`](../TESTING.md)

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

เมื่อเปิด `ENABLE_SYSTEM_POWEROFF=1`, `POST /api/system/shutdown` จะบันทึก
active-session checkpoint และ `service_pause`, flush BCG/writer queue, ปิด storage,
sync filesystem แล้วจึงเรียก `systemctl poweroff` คำสั่งนี้ **ไม่ finalize Session**;
เมื่อเปิดเครื่องระบบต้อง resume Session เดิม การปิดไฟตรงโดยไม่ผ่านขั้นตอนนี้เสี่ยง
ต่อ checkpoint และข้อมูลช่วงท้ายไม่ครบ
