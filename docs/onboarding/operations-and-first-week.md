# ZEEP v1 — Operations และ First-week Checklist

สถานะ: **ขั้นตอนสำหรับ Internal Pilot**

Runbook หลัก: [Pi 5 Operations Runbook](../pi5-operations-runbook.md)

Release gate หลัก: [TESTING.md](../../TESTING.md)

หน้านี้เป็นเส้นทางเริ่มงานและ checklist เท่านั้น คำสั่ง, ชุดทดสอบ และลำดับ deploy
เปลี่ยนได้ตาม release จึงต้องอ่านจาก Runbook และ TESTING โดยตรง ไม่คัดลอกมาไว้ซ้ำ

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

- ใช้ repository access และสิทธิ์ Pod/data ตามบทบาทและหลัก least privilege
- ใช้เครื่องทีมที่อนุมัติและเปิด FileVault หรือ LUKS/dm-crypt ก่อน Sync snapshot
- เตรียม environment ตาม repository และระบุ owner ของ Product, Safety, Hardware,
  Data/Privacy และ Operations
- งานที่กระทบ Pod ต้องมี maintenance window และยืนยันว่าไม่มีผู้ใช้/Recording
- ผู้ที่ไม่ต้องวิเคราะห์ข้อมูลจริงให้ใช้ synthetic/temp data และไม่ Sync snapshot

ขั้นตอนอนุมัติเครื่อง ตำแหน่ง marker, ระบบปฏิบัติการที่รองรับ และคำสั่งล่าสุดอยู่ใน
[Pi 5 Operations Runbook](../pi5-operations-runbook.md) เท่านั้น ห้ามสร้าง approval
marker เองหรือคัดลอกจากเครื่องอื่น

## เริ่มงานประจำวัน

- เริ่มจาก `develop`, ตรวจสถานะ Git แล้ว Sync ด้วย workflow ที่ Runbook ระบุ
- อ่านผล Sync ทุกครั้ง: code หรือ snapshot ที่ใช้ต้องบอก source, Git SHA, เวลาและ
  สถานะ freshness; ห้ามเดาตำแหน่งไฟล์
- Snapshot เป็น read-only analysis input และ **ไม่ใช่ application `DATA_DIR`**
- สร้าง branch หลัง Sync สำเร็จ งานหนึ่ง branch ควรมีขอบเขต function/feature เดียว
- งาน source-only ใช้ synthetic/temp data; hardware ที่ไม่มีต้องแสดง unavailable จริง

คำสั่งเริ่มงาน, fallback, local bootstrap และ snapshot workflow ล่าสุดอยู่ใน
[Pi 5 Operations Runbook](../pi5-operations-runbook.md)

## เลือก test ตามสิ่งที่แก้

ใช้ `python quality_gate.py changed` เป็นค่าเริ่มต้น แล้วตรวจ CI gate ที่เกี่ยวข้อง
กับไฟล์บน Git SHA เดียวกัน Python change ต้องผ่าน Full Application suite ส่วน
UI/docs/evidence ใช้ gate เฉพาะของตนตาม TESTING ไม่ต้องรันชุดเต็มซ้ำก่อนทุก
push/deploy ยกเว้นงานข้ามระบบ ผลไม่แน่นอน หรือ Code Freeze ให้บันทึก Git SHA,
environment, passed/failed/error/skipped และ hardware ที่ได้หรือไม่ได้ทดสอบ

รายการคำสั่งและชุดทดสอบปัจจุบันอยู่ที่ [TESTING.md](../../TESTING.md) เท่านั้น
หลักที่ต้องรักษาคือ:

- UI แก้ source template/partial แล้วตรวจ generated bundle ตาม TESTING
- งานย้อนหลังต้องผ่าน [`maintenance_registry.py`](../../maintenance_registry.py),
  เริ่ม dry-run และเก็บ immutable-Raw provenance กับ before/after audit
- อ่าน [Sleep History Promotion Policy](../sleep-history-promotion-policy-v2.md)
  ก่อน reclassify/rescore/recalibrate/cleanup/trim/reset/annotation
- Local/Mock pass ไม่แทนเครื่องจริง และ Hardware smoke ไม่แทน Full Product Gate

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
ไม่มี Recording ให้ทำตาม [Pi 5 Operations Runbook](../pi5-operations-runbook.md)
และ release gate ใน [TESTING.md](../../TESTING.md) โดยใช้ approved Git ref เท่านั้น
คำสั่ง host/path/service ไม่ทำสำเนาไว้ใน Onboarding เพราะอาจเปลี่ยนตาม deployment

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

## Backup, shutdown และ network boundary

- Daily backup รวม SQLite, Profile, Personal Baseline และ manifest; Production
  config เก็บ 3 daily archives ตาม runbook
- `POST /api/system/shutdown` ใช้ได้เมื่อ `ENABLE_SYSTEM_POWEROFF=1`; จะ checkpoint,
  flush, close storage และ sync ก่อน poweroff โดย **ไม่ finalize Session**
- การดึงปลั๊กเสี่ยงทำ checkpoint/ข้อมูลท้ายช่วงไม่ครบ
- LAN HTTP ใช้ได้เฉพาะ network ควบคุม เส้นทางนอก LAN ต้องใช้ช่องทางและ access
  policy ที่ Operations/Data owner อนุมัติ
- Public reverse proxy ต้องใช้ HTTPS, secure cookie, access policy และ privacy review
- physical control ระยะไกลต้องมีผู้ยืนยันหน้างานตาม policy; ห้ามสันนิษฐานว่ารางว่าง

ค่าการสำรอง ขั้นตอน shutdown, recovery และ network access ล่าสุดอยู่ใน
[Pi 5 Operations Runbook](../pi5-operations-runbook.md)

## First-week plan

### Day 1 — Product, safety และ data boundary

- [ ] อ่าน [Onboarding index](README.md) และ [Product/lifecycle](product-and-lifecycle.md)
- [ ] อ่าน [Technology Stack, Data และเครื่องมือ](technology-stack-and-tools.md)
- [ ] อธิบายความต่าง Sleep Score / Recovery Score / Restore Summary ได้
- [ ] อธิบาย `waiting_bed`, Recording, OFF BED และ restart continuity ได้
- [ ] อ่าน [API/Data/Privacy](api-data-and-privacy.md) และรู้ว่าอะไรออกจาก Pod ได้
- [ ] ยืนยัน workstation/access ตาม least privilege

### Day 2 — Architecture และ Hardware trace

- [ ] อ่าน [Hardware และ Hub map](hardware-hub-map.md)
- [ ] หากรับผิดชอบเสียง/Monitor ให้อ่าน [หูอัจฉริยะ · DSP Plan](smart-ear-dsp-plan.md) และอธิบาย Current/Shadow boundary ได้
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
