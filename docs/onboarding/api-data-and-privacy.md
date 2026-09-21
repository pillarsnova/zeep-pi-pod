# ZEEP v1 — API, Data และ Privacy

สถานะ: **Internal Wellness API / Internal Pilot** · ทบทวน 19 กันยายน 2026

Contract หลัก: [ZEEP API v1](../zeep-api-v1.md) และ
[API Schema Reference v1](../zeep-api-schema-reference-v1.md)

หน้านี้อธิบาย trust boundary และช่วยเลือก API ที่ถูกต้อง ไม่ใช่ field reference
ก่อนเขียน client ให้ตรวจ Pydantic models, `/openapi.json` และ release ที่ deploy จริง

## Trust boundaries

```text
User/Admin browser
    │ cookie + RBAC (+ CSRF เมื่อ mutate)
    ▼
Pi API ──> local active store ──> finalized Usage API (raw-free allowlist)
  │               │
  │               ├──> daily backup
  │               └──> approved workstation snapshot [Internal Pilot only]
  │
  ├──> ZEEP account ingest [optional, durable allowlisted outbox]
  ├──> temporary report image/share [optional]
  └──> tunnel/access provider metadata [เมื่อเปิด remote access]
```

ข้อมูล “อยู่บน Pi” ไม่ได้แปลว่าไม่มีข้อมูลออกจาก Pi เมื่อเปิด login/account API,
ingest, report share, snapshot sync หรือ tunnel ต้องระบุ flow, processor, retention
และสิทธิ์ผู้ดูแลตาม configuration ที่ใช้งานจริง

## เลือก API ให้ถูกกลุ่ม

### Versioned control-plane read

| Endpoint | ผู้เรียก | ใช้สำหรับ |
|---|---|---|
| `GET /api/v1/public/health` | Public network boundary ที่อนุญาต | health envelope; ไม่ใช่ข้อมูล Session |
| `GET /api/v1/state` | Pod operator | canonical live state ที่กรองตาม principal |
| `GET /api/v1/admin/contracts/sensors` | Admin | sensor contract snapshot |
| `GET /api/v1/admin/contracts/sleep` | Admin | policy/version snapshot |
| `GET /api/v1/admin/maintenance` | Admin | maintenance contract |
| `GET /api/v1/admin/adaptive/live` | Admin | Shadow observability; `automatic_actuation=false` |
| `GET /api/v1/admin/contracts/acoustics` | Admin | Smart Ear capability registry, candidate labels และ validation gates |
| `GET /api/v1/admin/acoustics/live` | Admin | Level + optional DSP shadow label; ไม่มี feature แล้วเป็น `not_evaluated` |
| `GET /api/v1/admin/acoustics/timeline` | Admin | Timeline ระดับเสียง, review event และ provisional DSP marker ของ Active Session; ไม่มี Raw audio |

### Usage Session API — เส้นทางใหม่สำหรับ App

Base path คือ `/api/v1/usage-sessions` และอ่านเฉพาะ Session ที่ finalize แล้ว

คำแนะนำหลังพักรุ่น v1.2 อยู่ใน `restore_summary.recommendation` ของ summary/detail
มีหนึ่ง action พร้อมหัวข้อและเหตุผล ส่วน presentation ยังคงข้อความ string เดิม
ดู [API Schema](../zeep-api-schema-reference-v1.md) ไม่สร้างคำแนะนำอีกชุดจากคะแนน

| Endpoint | ข้อมูลที่ได้ | สิทธิ์ |
|---|---|---|
| `GET /api/v1/usage-sessions` | รายการแบบแบ่งหน้า | User: ของตนเอง; Admin: กรองบัญชีได้ |
| `GET /api/v1/usage-sessions/users` | รายงานรวมรายบุคคล จำนวนครั้งและโหมดที่ใช้ | Admin เท่านั้น |
| `GET /longitudinal` | ภาพรวมสะสมแยก Overnight/Nap | User: ของตนเอง; Admin: เลือกบัญชีด้วย `X-Zeep-Account-Key` |
| `GET /longitudinal/ai-context` | positive allowlist สำหรับ advisory AI | สิทธิ์เดียวกัน; ยังห้าม external AI egress ใน v1 |
| `GET /{session_id}/summary` | mode, score, Restore Summary, quality และ version | เจ้าของ Session หรือ Admin |
| `GET /{session_id}/presentation` | ลำดับข้อมูลสำหรับหน้า User/App | เจ้าของ Session หรือ Admin |
| `GET /{session_id}` | รายงานละเอียดแบบ raw-free | เจ้าของ Session หรือ Admin |
| `GET /{session_id}/development` | aggregate QA/provenance | Admin เท่านั้น |

อย่าเริ่ม integration ใหม่กับ `/api/history/{username}` หรือ
`/api/history/{username}/{session_id}` เพราะ email/account key อาจอยู่ใน URL,
browser history และ access log Legacy routes ต้องคงไว้จน Tablet migrate และผ่าน
parity check แล้วเท่านั้น

### Adaptive Journey — Timeline, feedback และคำแนะนำ

เพิ่มใน `eaccf32` บน Git; ตรวจ SHA/OpenAPI ของ Pod ก่อนใช้จริง เพราะรอบนี้ยังไม่ Deploy

| Endpoint | หน้าที่ |
| --- | --- |
| `GET /api/v1/adaptive/sessions/{session_id}` | Timeline, ก่อน–หลัง, ความสบายอ้างอิง และคำแนะนำ |
| `POST /api/v1/adaptive/sessions/{session_id}/comfort` | ความเห็นที่เลือกตอบ พร้อมยินยอมให้ใช้ปรับคำแนะนำ |
| `POST /api/v1/adaptive/sessions/{session_id}/decisions` | บันทึกรับ/ปฏิเสธ/เลื่อนคำแนะนำ ไม่ส่งคำสั่งอุปกรณ์ |

ใช้ Browser Auth/CSRF เดิม User เฉพาะของตน Admin ตามบทบาท ไม่รับ broad API token
account key ว่างไม่ใช่หลักฐานยืนยันเจ้าของ และไม่ใช้รวมความชอบข้ามบุคคล
ผลเป็น `private, no-store`; mutation มี UUID สำหรับ retry
Smart Ear labels/features ยังคง Admin-only ส่วนค่าที่เปิดเผยต้องผ่านการตรวจสิทธิ์

ใช้ `events` เดิมเก็บ `adaptive_comfort`/`adaptive_decision` แยกจาก Raw และคะแนน
ไม่มี external AI egress, schema migration หรือ Auto Control
รายละเอียด request/response และลำดับใช้งานดู
[สรุป Adaptive Journey](adaptive-journey-and-sensor-expansion.md)
และ [contract หลัก](../zeep-adaptive-journey-v1.md)

### Control และ raw/research boundary

- Control mutation (`/api/aircon/*`, `/api/bed/*`, `/api/door/*`, output/audio)
  ไม่ใช่ Usage API ต้องผ่าน role, validation, CSRF, timeout/safe state และ event audit
- Raw/research routes เช่น `/api/sessions`, `/api/session/{id}/timeline`,
  `/api/session/{id}/bcg` และ download ถูกป้องกันที่ router ด้วย Admin dependency
- การซ่อนเมนูใน UI ไม่ใช่ authorization; Backend ต้องตรวจทุก HTTP/WebSocket path
- Development view เป็น aggregate QA และยังไม่ใช่ raw export

## Authentication และ response contract

| Principal | Credential | ขอบเขต |
|---|---|---|
| User | HttpOnly cookie `zeep_auth` | เฉพาะ `principal.account_key` ของตนเอง |
| Admin | Admin browser cookie | หลายบัญชี, Admin/Development/raw routes ตาม role |
| Legacy `X-API-Token` | broad service token | Usage API v1 ปฏิเสธ `403` โดยตั้งใจ |
| ไม่มี/หมดอายุ | — | `401` |

- Cookie เป็น bearer credential: Production traffic ต้องใช้ HTTPS และ
  `AUTH_SECURE_COOKIE=true` หรืออยู่ภายใน Tailscale encrypted overlay
- HTTP บน Pod LAN ใช้ได้เฉพาะ test network ที่ควบคุม; ห้ามเปิด port 8000 ตรงสู่
  Public Internet
- Usage response สำเร็จส่ง `Cache-Control: private, no-store`
- ขอ Session ของผู้อื่นคืน `404` เหมือน ID ไม่มีอยู่ เพื่อลดการเปิดเผยข้อมูล
- ทุก versioned response มี schema, API version, kind, generated time และ
  `request_id`; bug report ต้องแนบ request ID และ version โดย redact PII/token
- Client ใช้ stable key/enum ไม่ตัดสิน logic จาก label ภาษาไทย และห้ามคำนวณ score,
  continuity หรือ coverage ใหม่จากข้อมูลแสดงผล

Backend-to-backend read ยังไม่เปิดใน v1 การออกแบบครั้งถัดไปต้องใช้ credential
แบบ account/Pod-scoped อายุสั้น (เช่น OAuth/HMAC) พร้อม immutable read audit
ห้ามฝัง service credential ใน Mobile app, JavaScript, URL, log หรือ image

## Data inventory

| ชั้นข้อมูล | ตัวอย่าง/ตำแหน่ง | ผู้มีสิทธิ์/การใช้งาน |
|---|---|---|
| Identity/Profile | `data/profiles.json`, canonical account aliases | User ตามบัญชี; Admin ตาม role; ใช้ profile/baseline context |
| Browser auth | `data/auth.db` | SQLite แบบถาวรข้าม process restart; เก็บ hash ของ cookie token ฝั่ง server และไม่คืน credential ใน result API |
| Short-lived capability | offline, QR, profile-completion และ report-share tickets | อยู่ใน memory, อายุสั้น/ใช้ครั้งเดียวตาม contract และหายเมื่อ process restart; ไม่ใช่ข้อมูลใน `auth.db` |
| Pod occupancy lease | `data/occupancy.db` | SQLite lease มี TTL สำหรับกันบัญชี/Pod ซ้ำ; แยกจาก Browser auth และ Recorded Session |
| Session/Timeline/Event | `data/sessions.db` | User ได้เฉพาะ allowlisted finalized projection; Admin ตรวจเชิงปฏิบัติการได้ |
| Raw BCG | `data/bcg.db` | Admin/research boundary; ไม่ออก Usage API |
| Personal baseline | `data/baselines.json` และ persisted profile data | ใช้เฉพาะ account/mode/target/formula cohort ที่ตรง |
| Runtime continuity | `data/active_session_checkpoint.json` | คืน Recorded Session หลัง restart; แยกจาก `occupancy.db` และไม่อยู่ใน workstation snapshot |
| Pending egress | `data/ingest_outbox/` | server-side durable retry; payload แบบ allowlist |
| Device calibration | `calibration.json`/deployment calibration | provenance ของอุปกรณ์; ห้ามใช้ rewrite Raw |
| Audit/operations | event log, version, request ID, maintenance audit | จำกัดสิทธิ์และ retention; redact PII/health detail ใน support log |

`data/`, `private-data/`, backup และ credential เป็นข้อมูลนอก Git ห้าม commit,
แนบ issue หรือส่งผ่านช่องทางแชตทั่วไป Test ต้องย้าย data/log/backup/music ไป
temporary directory ผ่าน [`testing_support.py`](../../testing_support.py)

### Identity boundary

Usage history เป็น **email-first ไม่ใช่ email-only**: ใช้ email ที่ยืนยันได้เป็น
canonical identifier เมื่อมีข้อมูล แต่ยังรองรับ normalized legacy account key ของ
ประวัติเก่าผ่าน alias ที่ตรวจสอบแล้ว ห้ามรวมบัญชีจาก display name หรือข้อความที่ดูคล้ายกัน

### Raw กับ Derived

- Raw Sensor/BCG และ original Timeline ห้ามถูกแก้เพื่อทำให้ผลดีขึ้น
- Reclassify/rescore/recalibrate เขียน Derived result ใหม่พร้อม policy/formula version,
  provenance, immutable-Raw guard และ audit
- “Raw immutable” เป็นกฎความถูกต้องเชิงวิเคราะห์ ไม่ได้ห้ามการลบอย่างมีอำนาจตาม
  privacy/retention process
- Public/App projection ใช้ positive allowlist: field ใหม่ไม่ออกเองจนผ่าน review
- `clinical_validated=false` ต้องถูกบังคับใน public v1 แม้ข้อมูลเก่าระบุอย่างอื่น

### Acoustic Intelligence / เสียง

Current runtime ไม่มี Raw audio/PCM store; รองรับเฉพาะ provisional DSP label
จาก ESP32 โดยไม่ถอดเนื้อหาคำพูดหรือระบุตัวบุคคล ระบบเก็บระดับ `sound_dba`
และ label/features ที่ผ่าน positive allowlist ตาม Sensor frame ทุก 10 วินาที
โดย persist ลง Timeline เฉพาะขณะ Recording

แผน [หูอัจฉริยะ · Acoustic Intelligence DSP](smart-ear-dsp-plan.md) ต้องใช้
privacy-first boundary ดังนี้:

- ไม่ส่งหรือเก็บ PCM ต่อเนื่องเป็นค่าเริ่มต้น; ESP32 ส่งเฉพาะ versioned features
- Candidate registry, DSP shadow label และ feature diagnostics เป็น Admin-only positive allowlist
- User/App ยังเห็นเพียงระดับเสียงหรือข้อความสรุปที่ Product/Privacy อนุมัติ
- P1-shadow รับ `speech_like`, `snore_like`, `impact_like` และ
  `steady_equipment_like` เป็นป้ายชั่วคราวจาก Firmware ที่ผ่าน allowlist เท่านั้น;
  `cough_like` และ label อื่นยังเป็น Research Candidate ที่ `not_evaluated` ห้าม
  ถอดคำ ระบุตัวบุคคล หรือแสดงเป็นผลสุขภาพ
- การเก็บตัวอย่างเสียงเพื่อสร้าง dataset ต้องเป็น protocol แยก มี consent,
  coded identity, encryption, retention, access log และ erasure owner
- ก่อน persist acoustic features ต้องรวมข้อมูลนั้นใน backup/snapshot/retention/
  account-erasure contract และทดสอบ public redaction

Smart Ear P1-shadow อยู่ใน API v1 แบบ Admin-only แล้ว โดย Pi/API/UI และ
Timeline persistence รองรับ label และมีหลักฐาน Firmware DSP บน Pod 1 แล้ว
ตาม [Current Status](../current-status.md) แต่ยังไม่รับรองความแม่นยำราย class;
user-facing summary ยังเป็น `ROADMAP` Client ต้องตรวจ
`contract_version`, `classification_state` และห้ามเปลี่ยน candidate เป็นผลตรวจ

## Data ที่ออกจาก Pod

| Flow | เปิดเมื่อ | ขอบเขตข้อมูล | ข้อควบคุม |
|---|---|---|---|
| ZEEP account login/profile | ตั้ง `ZEEP_API_BASE_URL` และผู้ใช้ Login | identity/profile response และ short-lived auth material ตาม account flow | token เก็บ server-side/in-memory ตาม contract; ห้าม log/ส่งเข้า browser โดยไม่จำเป็น |
| Finished-session ingest | ตั้งทั้ง `ZEEP_INGEST_API_KEY` และ `ZEEP_DEVICE_ID` | `userPublicId`, device/session/time, mode-specific result และ compact stage/environment result; ไม่มี raw BCG | allowlisted payload, durable/idempotent outbox, retry แยกจาก local finalization |
| Report share | `SESSION_REPORT_SHARE_ENABLED=1` | PNG ที่ browser render จากชื่อและผล Session ไป account backend | single-use ticket; user tokenอยู่ใน process; signed read URL 60 นาที |
| Workstation snapshot | เครื่องทีมที่อนุมัติและเข้ารหัส หรือ Mac เครื่องพัฒนาที่มีข้อยกเว้นเฉพาะเครื่องตาม Runbook | Session/BCG/Profile/Baseline/Derived report ที่กำหนด | **Internal Pilot only**, allowlist/checksum/SQLite check/atomic install; ห้ามใช้เป็น runtime DB หรือขยายข้อยกเว้นไปเครื่องอื่น |
| Remote access tunnel | Tailscale/Cloudflare configuration | application traffic และ provider access metadata | HTTPS/Access policy; review access log, DPA/PDPA, retention และ administrator scope |
| Advisory AI | contract มี endpoint ภายใน | direct identifiers ถูกตัด แต่ข้อมูลยัง linkable กับเจ้าของบัญชี | **ห้าม external egress ใน v1** จนมี purpose-specific consent และ processor/retention approval |

Account ingest ไม่ควรส่ง email เพิ่มเมื่อมี immutable `userPublicId` แล้ว การเพิ่ม field
ใหม่ต้องผ่าน schema, data-minimisation และปลายทาง retention review ร่วมกัน

### สื่อ Pilot ที่เผยแพร่

- ใช้ coded ID เป็นค่าเริ่มต้นและตัด email/ข้อมูลสุขภาพที่ไม่จำเป็น
- การเผยแพร่ชื่อ ภาพ เสียง หรือวิดีโอต้องมี consent ที่ระบุวัตถุประสงค์ ช่องทาง
  ระยะเวลา และวิธีถอนความยินยอม
- `noindex`/`nofollow` ลดการค้นพบจาก search engine แต่ไม่ใช่ authentication หรือ
  access control; URL ที่เปิดได้ยังถือเป็นการเปิดเผยต่อสาธารณะ
- สรุปแบบ **PILOT EVIDENCE** ต้องบอกจำนวนผู้ตอบ ตัวหาร ผู้ใช้ซ้ำ และข้อจำกัด;
  ห้ามเปลี่ยนผลสัมภาษณ์หรือ simulation ให้เป็นคำอ้างเชิงประสิทธิผลด้านสุขภาพ

## Retention และ account erasure

### ค่าที่ runtime ระบุได้

| สิ่งจัดเก็บ | ขอบเขตปัจจุบัน |
|---|---|
| Browser auth | default TTL 43,200 วินาที (12 ชั่วโมง); ตรวจ deployment config จริง |
| Temporary report link | 60 นาทีเมื่อ feature เปิด |
| Daily Pod backup | `BACKUP_RETENTION_COUNT`; Production config ใช้ 3 daily archives ตาม runbook |
| Workstation snapshot | ล่าสุด 3 snapshot ต่อ Pod; quarantine ที่ตรวจไม่ผ่านไม่เกิน 3 ชุด/24 ชั่วโมง |
| Backend/tunnel/access log | **ไม่มี policy กลางระบุใน repo**; ต้องมี owner และอนุมัติก่อน Production |

Admin-only `DELETE /api/users/{username}` ลบ local active-store boundary แบบ
retry-safe และปฏิเสธ `409` หากบัญชียังมี active Session ขอบเขตรวม canonical aliases,
Session/BCG, Profile, Baseline, pending ingest, report-share/pending capability,
browser sessions, offline tickets และ checkpoint ที่เกี่ยวข้อง

Response ประกาศขอบเขตอย่างชัดเจนว่า:

- `local_active_store_deleted=true`
- `remote_uploaded_objects_deleted=false`
- `daily_backup_archives_deleted=false`

ดังนั้นคำขอลบข้อมูลยังไม่จบด้วย local endpoint เพียงครั้งเดียว ผู้ดูแลข้อมูลต้อง
ประสานลบ/หมดอายุข้อมูลที่ Backend, report objects, Pod backups และ snapshot บน
workstation ทุกเครื่องตามทะเบียน แล้วบันทึก acknowledgement ตาม PDPA process

## Privacy / integration checklist

- [ ] Login เป็น User A แล้ว list/detail ไม่เห็น User B
- [ ] User A ขอ Session ID ของ User B แล้วได้ `404`
- [ ] User ส่ง `account_key`/`query` หรือ legacy token แล้วได้ `403`
- [ ] Response ไม่มี raw samples, BCG base64, Profile answers, tokens, API/private keys
- [ ] Overnight เป็น `sleep_score`; Nap เป็น `recovery_score`
- [ ] Restore Summary มี `creates_independent_score=false`
- [ ] Response, proxy และ browser cache คง `private, no-store`
- [ ] Bug/audit log เก็บ `request_id`/version แต่ redact email, credential และ health detail
- [ ] Egress ใหม่มี schema, purpose, minimisation, processor, retention และ erasure owner
- [ ] Test ใช้ temporary data เท่านั้น

Focused regression และ Full Product Gate ดูที่ [TESTING.md](../../TESTING.md)

## ช่องว่างก่อน Production

- ต้องมี signed device registry/MDM, central audit log และ erasure acknowledgement
  จาก workstation ทุกเครื่องก่อนขยาย snapshot sync พ้น Internal Pilot
- ต้องใช้บัญชี `zeep-sync` แบบ forced-command + Tailscale ACL; ห้ามแจก credential
  ผู้ดูแล Pod ทั่วไปให้ทีมเพื่อดึงข้อมูล
- ต้องย้าย Legacy Tablet history ออกจาก URL ที่มี account key/email
- ingest contract ต้องเพิ่ม confidence/provisional/exclusion provenance ก่อนให้ปลายทาง
  ตีความความมั่นใจราย Epoch
- external AI ต้องมี purpose-specific consent และ processor/retention policy
- public reverse proxy ต้องผ่าน HTTPS, secure cookie, access-log/DPA/PDPA review และ
  remote physical-control policy; ห้ามอ้างว่า “ไม่มีข้อมูลผ่าน Cloud”
- local erasure ต้องถูกรวมใน end-to-end data-subject workflow ที่ครอบ Backend,
  backup, share object และ offline workstation
