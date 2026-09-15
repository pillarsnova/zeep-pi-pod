# ZEEP v1 — Operations และ First-week Checklist

สถานะ: **ขั้นตอนสำหรับ Internal Pilot**

Runbook หลัก: [Pi 5 Operations Runbook](../pi5-operations-runbook.md)

Release gate หลัก: [TESTING.md](../../TESTING.md)

คำสั่งในหน้านี้เป็นทางลัดสำหรับสมาชิกใหม่ หากต่างจาก runbook, CI หรือ
configuration ของ Pod ที่ deploy ให้หยุดและตรวจแหล่งหลักก่อนดำเนินการ

## กฎก่อนแตะระบบ

1. ห้าม restart, deploy, shutdown หรือ maintenance ขณะมีผู้ใช้งาน/Recording
2. ห้ามใช้ Production data เพื่อทดสอบ; test suite ต้องใช้ temporary data
3. ห้ามแก้ Raw BCG/Timeline หรือรัน data-write tool นอก
   [`maintenance_registry.py`](../../maintenance_registry.py)
4. ห้ามเปิด port 8000 ตรงสู่ Public Internet; remote access ใช้เส้นทางที่อนุมัติ
5. ห้ามวาง `.env`, token, database, snapshot, log ที่มี PII หรือ audio asset
   นอกขอบเขตจัดเก็บที่กำหนด/ใน Git
6. Local/Mock pass ไม่ได้พิสูจน์ Serial, MQTT, GPIO, audio, Safety หรือ resume
   บนเครื่องจริง

## เตรียมสิทธิ์และเครื่องทำงาน

ต้องมี:

- repository access และสิทธิ์ตามบทบาท; Pod/Tailscale/production data ให้เฉพาะคน
  ที่ต้องใช้จริง
- เครื่องทีมที่เปิด FileVault (macOS) หรือ LUKS/dm-crypt (Linux)
- Python environment และ dev dependencies ตาม
  [`requirements-dev.txt`](../../requirements-dev.txt)
- owner/contact สำหรับ Product, Safety, Hardware, Data/Privacy และ Operations
- maintenance window ก่อนทำงานที่กระทบ Pod

Windows/BitLocker ยังไม่ผ่าน ACL + transport tests ใน workflow นี้ จึงไม่รองรับ
workstation snapshot อย่าสร้าง approval marker เองหรือคัดลอกจากเครื่องอื่น

### อนุมัติ workstation ที่ต้องใช้ Pod snapshot

ผู้มีอำนาจต้องรันบนเครื่องจริง:

```bash
sudo python3 approve_workstation.py --approved-by "ชื่อผู้อนุมัติ"
```

Approval ผูก hostname + stable machine ID, ตรวจ disk encryption จริง และมีอายุ
สูงสุด 365 วัน Marker ต้องเป็น root-owned ตามตำแหน่ง/permission ใน runbook
นี่เป็น local operational record ไม่ใช่ central cryptographic approval

ผู้ที่ไม่ต้องวิเคราะห์ข้อมูลผู้ใช้ควรใช้ synthetic/temp data และไม่ Sync snapshot
เพียงเพื่อความสะดวก

## เริ่มงานประจำวัน

บน workstation ที่อนุมัติและมีสิทธิ์ข้อมูล ให้เริ่มจาก branch `develop`:

```bash
./start_work.sh
```

สคริปต์ตรวจ approval/encryption, fetch + fast-forward `origin/develop` และดึง
read-only verified snapshot จาก Pod ผ่าน Tailscale ก่อน fallback ไป LAN

ข้อควรอ่านจากผลคำสั่ง:

- ถ้า origin ติดต่อไม่ได้ สคริปต์อาจทำงานต่อด้วย code ที่ไม่ใช่ล่าสุด
- ถ้า Pod ติดต่อไม่ได้ อาจใช้ verified snapshot ล่าสุดและจะระบุว่าข้อมูลอาจเก่า
- ตำแหน่ง snapshot อ่านจาก JSON output; ห้ามเดา path
- snapshot อยู่ใน `private-data/pod-sync/` โดยค่าเริ่มต้นและ **ไม่ถูกนำเป็น
  application `DATA_DIR` อัตโนมัติ**
- ห้ามส่งต่อ snapshot หรือใช้บนเครื่องส่วนตัว/ดิสก์ไม่เข้ารหัส

ก่อนสร้าง branch งาน:

```bash
git status --short --branch
git branch --show-current
```

`start_work.sh` ต้องเริ่มบน `develop` เมื่อ sync เสร็จจึงสร้าง branch ตาม
convention ของทีม งานหนึ่ง branch ควรมีขอบเขต function/feature เดียวและไม่ปน
refactor, formula change, hardware behavior และ data migration โดยไม่มีเหตุผลที่
review แยกไม่ได้

### Source-only / local bootstrap

สำหรับงานที่ไม่ต้องใช้ Pod data ให้ใช้ข้อมูลจำลองและ bootstrap ตาม
[README หัวข้อเริ่มใช้เร็วสุด](../../README.md) `./run.sh`
สร้าง `.venv`, ติดตั้ง runtime dependency และรัน local app Hardware ที่ไม่มีต้อง
แสดง Disconnected/disabled ตามจริง อย่าใช้ mock pass เป็น Production evidence

เพื่อรัน release gate ต้องติดตั้ง dev dependencies และ activate environment ของ
workspace นั้นก่อน ตัวอย่าง environment ที่ทีมปัจจุบันใช้บน Mac คือ:

```bash
source pi5/.venv/bin/activate
```

หาก environment/layout ต่างไป ให้ยึด runbook และบันทึก Python/dependency version
กับผล test

## เลือก test ตามสิ่งที่แก้

เริ่มด้วย focused suite แล้วจึงรัน full gate ก่อน push/deploy อย่าใช้จำนวน test
คงที่เป็นเกณฑ์ เพราะ suite เพิ่มได้ ให้บันทึกผลจริง, failure/error/skip และ Git SHA

| ขอบเขต | Focused regression เริ่มต้น |
|---|---|
| Hardware/module boundary | `test_modular_architecture.py test_sensor_contract.py test_sensor_services.py test_api_state_projection.py test_bcg_reader.py test_control_protocol.py test_audio_api.py test_session_lifecycle.py` |
| Sleep/score/baseline | `test_sleep_signal_features.py test_sleep_system_consistency.py test_sleep_baseline_policy.py test_personal_baseline_policy.py test_sleep_session_report.py test_recovery_policy_guardrails.py` |
| API/access/privacy | `test_rbac_api.py test_access_and_occupancy.py test_usage_session_api.py test_user_ai_context.py test_account_erasure_api.py` |
| UI/Product copy | `test_ui_composer.py test_product_language.py` และ `python ui_composer.py check` |
| Pod snapshot sync | `test_pod_data_sync.py test_workstation_approval.py test_pod_snapshot_export_limits.py` |

รูปแบบคำสั่ง:

```bash
python -m unittest -q test_modular_architecture.py test_sensor_services.py
```

### Full application/release gate

ก่อน push หรือ deploy:

```bash
python -m unittest discover -q
python ui_composer.py check
ruff check zeep_pod
ruff format --check zeep_pod
python -m py_compile app.py *.py
git diff --check
```

ก่อน v1 Code Freeze ให้เพิ่ม Evidence gate:

```bash
python research/evidence-library/update_research_library.py check
```

บน GitHub ต้องยืนยัน workflow `Python architecture and style` และ
`Evidence library integrity` ด้วย Full Product Gate ต้องไม่มี skipped test ใน
environment ที่ลง dev dependencies ครบ

### UI rule

แก้ source ที่ `static/index.template.html` หรือ `static/partials/{control,app}`
แล้ว build/check ด้วย [`ui_composer.py`](../../ui_composer.py) ห้ามแก้เฉพาะ
generated `static/index.html` เพราะ runtime bundle จะไม่ตรง source

### Data maintenance rule

Reclassify, rescore, recalibrate, cleanup, trim, reset และ annotation เป็น offline
maintenance boundary:

- ตรวจ declaration/guard ที่ `maintenance_registry.py`
- เริ่มด้วย dry-run ทุกครั้ง
- เก็บ policy/model version, immutable-Raw hash, before/after และ audit trail
- หยุดเมื่อ integrity, staging parity หรือ provenance ไม่ครบ
- ห้ามเรียก destructive maintenance ผ่าน Browser API

อ่าน [Sleep History Promotion Policy](../sleep-history-promotion-policy-v2.md)
ก่อนงานย้อนหลังทุกครั้ง

## Pull request / handoff ที่ review ได้

ทุก change ควรตอบได้:

- เปลี่ยน behavior ใด และไม่เปลี่ยนอะไร
- function/feature owner และ module boundary อยู่ที่ไหน
- invariant, safety, privacy, API และ backward-compatibility ใดได้รับผล
- focused/full tests อะไรผ่านบน Git SHA ใด; มี skip หรือไม่
- ต้องใช้ hardware smoke, data migration, config หรือ restart หรือไม่
- rollback/recovery อาศัย approved Git ref และข้อมูลสำรองใด
- เอกสาร contract/version ใดต้องแก้ใน release เดียวกัน

งาน refactor ใช้ characterization test ก่อนย้าย, รักษา compatibility facade จน
caller ย้ายครบ และไม่เปลี่ยน threshold/score/device behavior แฝงไปพร้อมกัน
โครงสร้างเป้าหมายอยู่ที่ [Pi 5 Software Architecture](../pi5-software-architecture.md)

## Deploy ไป Pod 1

เฉพาะ operator ที่ได้รับมอบหมาย ใน maintenance window ที่ยืนยันว่าไม่มีผู้ใช้และ
ไม่มี Recording:

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

สาม focused suites บน Pi เป็น smoke gate ของ module/Sensor/Control เท่านั้น
ไม่แทน full application gate หากแก้ Sleep, Session, Auth, API หรือ Privacy ต้องรัน
focused suite ของส่วนนั้นก่อน restart ด้วย

### ตรวจหลัง restart

- `zeep-pod.service` เป็น active และไม่มี restart loop/watchdog failure
- `/api/public/status` และ `/api/v1/public/health` ตรงกับ release/pod ที่คาด
- Sensor Hub 1/2, BCG, Control Hub และ audio/GPIO ที่อยู่ใน scope เชื่อมต่อจริง
- ไม่มี Safety fault ที่ยังไม่ acknowledge/ไม่มีเหตุให้เข้า safe mode
- Dashboard, Monitor/Control ตาม role และ Sessions page เปิดได้
- ถ้ามี checkpoint ที่ได้รับอนุมัติให้ทดสอบ ต้องพบ event
  `SESSION resumed_after_restart` และ identity/mode/target/State เดิม

ถ้าตรวจไม่ผ่าน อย่าแก้ Production data หรือใช้ `git reset --hard` เพื่อให้ระบบ
“ดูปกติ” เก็บ service status/log, Git SHA, policy snapshot และเวลาที่เกิดเหตุ
จากนั้นใช้ recovery/rollback ที่ owner อนุมัติ

## Backup, shutdown และ remote access

- Daily backup รวม SQLite, Profile, Personal Baseline และ manifest; Production
  config เก็บ 3 daily archives ตาม runbook
- `POST /api/system/shutdown` ใช้ได้เมื่อ `ENABLE_SYSTEM_POWEROFF=1`; จะ checkpoint,
  flush, close storage และ sync ก่อน poweroff โดย **ไม่ finalize Session**
- การดึงปลั๊กเสี่ยงทำ checkpoint/ข้อมูลท้ายช่วงไม่ครบ
- LAN HTTP ใช้ได้เฉพาะ network ควบคุม; Tailscale เป็นทางเข้าทีม
- Public reverse proxy ต้อง HTTPS + `AUTH_SECURE_COOKIE=true` + Access policy และ
  privacy review ตาม [REMOTE-ACCESS.md](../../REMOTE-ACCESS.md)
- physical control ระยะไกลต้องมีผู้ยืนยันหน้างานตาม policy; ห้ามสันนิษฐานว่ารางว่าง

## First-week plan

### Day 1 — Product, safety และ data boundary

- [ ] อ่าน [Onboarding index](README.md) และ [Product/lifecycle](product-and-lifecycle.md)
- [ ] อธิบายความต่าง Sleep Score / Recovery Score / Restore Summary ได้
- [ ] อธิบาย `waiting_bed`, Recording, OFF BED และ restart continuity ได้
- [ ] อ่าน [API/Data/Privacy](api-data-and-privacy.md) และรู้ว่าอะไรออกจาก Pod ได้
- [ ] ยืนยัน workstation/access ตาม least privilege

### Day 2 — Architecture และ Hardware trace

- [ ] อ่าน [Hardware และ Hub map](hardware-hub-map.md)
- [ ] trace อย่างน้อยหนึ่ง flow: transport → canonical state → API/UI/report
- [ ] trace หนึ่ง control: browser → RBAC/CSRF → protocol → adapter → ACK/audit
- [ ] หา pure policy, side-effect adapter และ composition wiring ของ domain ตนเอง
- [ ] อ่าน regression ที่ปกป้อง failure mode อย่างน้อยสองเคส

### Day 3 — Test และ local operation

- [ ] รัน focused suite ของ domain ด้วย temp/synthetic data
- [ ] รัน `ui_composer.py check` หากแตะ UI หรือ Product copy
- [ ] เปิด local app และยืนยันว่า hardware ที่ไม่มีแสดง unavailable ตามจริง
- [ ] ทดลองอ่าน `/openapi.json` และ response envelope/request ID
- [ ] รู้ความต่าง application gate, Pi smoke และ Full Product Gate

### Day 4 — First safe contribution

- [ ] เลือก change ขนาดเล็กใน function/feature เดียว
- [ ] เพิ่ม/ปรับ characterization หรือ regression ก่อนเปลี่ยน boundary
- [ ] รักษา public route/key, Raw immutability, role และ fail-safe behavior
- [ ] รัน focused suite + `git diff --check`
- [ ] เขียน handoff ที่บอก scope, evidence, risk และ deploy impact

### Day 5 — Review และ operations shadowing

- [ ] ให้ domain owner review และแก้ข้อสังเกต
- [ ] รัน full application gate; บันทึก SHA และผลจริง
- [ ] shadow operator ตรวจ preflight/post-restart โดยไม่ restart ระบบที่มีผู้ใช้
- [ ] ทบทวน P0/P1/Production gaps ใน [v1 Handover](../zeep-v1-system-handover-and-freeze-readiness.md)
- [ ] ระบุ owner/next step ของช่องว่างที่เกี่ยวข้องกับงานตนเอง

สัปดาห์แรกถือว่าเสร็จเมื่อสมาชิกใหม่ส่งมอบ change ที่ review ได้และอธิบายได้ว่า
local tests ครอบคลุมอะไร, hardware/production ยังไม่ได้พิสูจน์อะไร และเหตุใด change
จึงไม่ทำลาย product, safety หรือ privacy invariant

## ช่องว่างก่อนขยายจาก Internal Pilot

- workstation snapshot ยังต้องมี signed device registry/MDM, central audit และ
  erasure acknowledgement; local marker อย่างเดียวไม่พอสำหรับ Production
- ต้อง provision บัญชี `zeep-sync` แบบ forced-command และ Tailscale ACL ก่อนแจก
  สิทธิ์ Sync หลายเครื่อง
- Production smoke, Safety-start policy, continuity trade-off และ Product/Safety
  sign-off ยังต้องบันทึกใน closure record
- Windows workstation, public remote access และ multi-Pod coordinator ต้องผ่าน
  control/test ของ deployment จริงก่อนเปิดใช้
- v1 ไม่มี smoke/CO input หรือ alarm output ใน software contract; ห้ามอ้าง coverage
- archived replacement firmware ไม่อยู่ใน v1 gate และห้าม Flash
