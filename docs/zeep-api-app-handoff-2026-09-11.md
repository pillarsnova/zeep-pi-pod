# ZEEP API & App Handoff — 2026-09-11

> **Purpose:** สรุปการเปลี่ยนแปลง การ Deploy และผล Rerun ประจำวันที่
> 11 กันยายน 2569 เพื่อให้ทีม Pod, API และ App ใช้ Contract เดียวกัน
>
> **Product position:** ZEEP Wellness & Longevity · ผลทั้งหมดเป็นการประเมิน
> เชิงสุขภาพจาก Sensor ไม่ใช่การวินิจฉัยหรือผล AASM/PSG
>
> **Runtime release commit:** `f8f70c39e32eb5a2c1053cbd22e10adf4c191082`
> (commit หลังจากนี้ในวันเดียวกันเป็นเอกสาร Handoff เท่านั้น)
>
> **Machine-readable contract:** `GET /openapi.json`

## TL;DR

- Production Pi ใช้ `origin/develop` ที่ commit `f8f70c3` และ Service ทำงานปกติ
- Overnight Recovery ใช้ **Sleep Score** ส่วน Nap & Refresh ใช้
  **Recovery Score**; ห้ามรวมคะแนนหรือเปลี่ยนชื่อข้ามโหมด
- เพิ่ม ZEEP Restore Summary เพื่ออธิบายคะแนนเดิม ไม่สร้างคะแนนที่สาม
- เพิ่ม Pull API แบบมี Auth/RBAC สำหรับรายการ ผลสรุป และรายละเอียด Usage Session
- Response ถูกตรวจด้วย Pydantic และเผยแพร่ Type/Enum/Nullable ผ่าน OpenAPI
- Rerun เฉพาะ Session ล่าสุดที่จบแล้วด้วย Raw replay รุ่นปัจจุบัน;
  คะแนนเปลี่ยน `74 → 69` พร้อม Audit และ Backup
- Raw BCG และ Timeline ไม่เปลี่ยน; SQLite integrity ผ่าน
- API/App กลางยังมี P0 integration gaps ซึ่งสรุปไว้ในหัวข้อ 8

## 1. Source of truth

เรียงลำดับอำนาจเมื่อข้อมูลขัดกัน:

1. Pydantic response models ที่อยู่ใน Production commit
2. `/openapi.json` จาก Service ที่ Deploy อยู่จริง
3. [Usage Session Schema Reference v1](zeep-api-schema-reference-v1.md)
4. [ZEEP Pod API v1](zeep-api-v1.md)
5. [ZEEP Restore Summary v1](zeep-restore-summary-v1.md)
6. เอกสาร Handoff ฉบับนี้

ไฟล์ Runtime สำคัญ:

- `zeep_pod/sessions/usage_api.py`
- `zeep_pod/sessions/usage_service.py`
- `zeep_pod/sessions/usage_response_models.py`
- `zeep_pod/sessions/restore_response_models.py`
- `zeep_pod/sessions/result_contract.py`
- `sleep_session_report.py`
- `sleep_system_policy.py`

## 2. การเปลี่ยนแปลงวันนี้

ช่วง commit `685b41e..f8f70c3` มี 10 commits, 66 files,
เพิ่ม 12,871 บรรทัดและลด 709 บรรทัด

### 2.1 Sleep replay และความต่อเนื่อง

- รักษา estimator context เมื่อ Sensor ขาดช่วงชั่วคราว ไม่ reset การหลับโดยไม่มี
  หลักฐานเพียงพอ
- เพิ่ม explicit Session allowlist สำหรับ Targeted replay
- แยก WAIT, NO DATA และ OFF BED ออกจาก W/N1/N2/N3/REM
- Historical promotion ทำงานเฉพาะ Derived evidence/state/report และตรวจ Hash
  ของ Raw input ก่อน Apply

### 2.2 สองโหมดและคะแนน

| Canonical mode | ชื่อผู้ใช้ | คะแนนหลัก | เป้าหมาย |
|---|---|---|---|
| `sleep` | Overnight Recovery | Sleep Score | อย่างน้อย 5 ชั่วโมง; เป้าคะแนนเวลา 7 ชั่วโมง |
| `nap_recovery` | Nap & Refresh | Recovery Score | 30 หรือ 90 นาที |

- Persist `rest_mode` และ `target_duration_s` แยกจากระยะเวลาที่เกิดขึ้นจริง
- ห้าม fallback `auto` หรือข้อมูลเก่าที่ไม่ชัดเจนเป็น Nap จาก Duration
- Nap ไม่จำเป็นต้องมี N2/N3/REM จึงยังคำนวณ Recovery Score ได้เมื่อไม่หลับ
  หาก HR/RR และหลักฐานขั้นต่ำครบ
- Overnight ที่สั้นกว่า 5 ชั่วโมงยังเป็น Overnight แต่ระบุ
  `protocol_status=too_short`; ห้ามเปลี่ยนเป็น Nap

น้ำหนักคะแนนที่ใช้จริง:

| Sleep Score | คะแนนเต็ม | Recovery Score | คะแนนเต็ม |
|---|---:|---|---:|
| เวลาและการเข้าสู่การนอน | 20 | เวลาพักตามเป้าหมาย | 25 |
| ความต่อเนื่องของการนอน | 30 | การตอบสนอง HR/RR | 35 |
| โครงสร้าง N2/N3/REM | 30 | ความต่อเนื่อง/ความนิ่ง | 30 |
| รอบการนอน | 15 | สภาพแวดล้อมสนับสนุน | 10 |
| ความครบของข้อมูล | 5 | — | — |

### 2.3 ZEEP Restore Summary

Restore Summary เป็น Explanation layer ของ released score เดิม:

- `creates_independent_score=false`
- `source_score.copied_without_recalculation=true`
- `whole_day_readiness_available=false`
- อธิบายสถานะ จุดแข็ง จุดที่ควรปรับ Personal Baseline ความมั่นใจ
  และคำแนะนำหนึ่งข้อ
- ไม่เขียนกลับ Sleep State และไม่สั่งอุปกรณ์
- ไม่มีแบบประเมินหลัง Session ต้องส่ง
  `subjective_outcome.status=not_measured`; ห้ามแต่งค่า “สดชื่นขึ้น” หรือ
  “พร้อมทำกิจกรรม” จาก Sensor

### 2.4 Usage Session API

| Method/Path | วัตถุประสงค์ |
|---|---|
| `GET /api/v1/usage-sessions` | รายการประวัติการใช้งานแบบแบ่งหน้า |
| `GET /api/v1/usage-sessions/{session_id}/summary` | ผลสรุปสำหรับหน้าแรกของ App |
| `GET /api/v1/usage-sessions/{session_id}` | รายละเอียดแบบ Allowlist ไม่มี Raw Sensor |

Success response ใช้ envelope:

```json
{
  "schema": "zeep.api.response",
  "api_version": "1.0",
  "kind": "usage_session_summary",
  "generated_at": "2026-09-11T05:30:00+07:00",
  "request_id": "uuid",
  "data": {
    "contract_version": "zeep.usage-session.v1"
  }
}
```

ข้อกำหนดสำคัญ:

- Auth ใช้ `zeep_auth` cookie
- User อ่านเฉพาะ Session ของตนเอง
- Admin ใช้ `account_key` และ `query` ได้
- Session ของผู้อื่นตอบ `404` เพื่อป้องกัน ID enumeration
- `X-API-Token` รุ่นเดิมใช้ดึงผลสุขภาพไม่ได้และตอบ `403`
- Success response มี `Cache-Control: private, no-store`
- Error ใช้ FastAPI `detail` ซึ่งเป็นได้ทั้ง string และ object
- API นี้เป็น Pull API ภายใน Pod; ไม่ได้เปลี่ยน legacy push contract
  `POST /v1/sleep-sessions/ingest`

### 2.5 Typed response และ Privacy

- กำหนด Type, Enum, Required-nullable และ Cross-field invariant ครบ
- ใช้ positive allowlist ใน nested report/quality/protocol objects
- ไม่เผยแพร่ Raw BCG, Raw packet, Timeline samples, Token, Profile answers,
  Health reference หรือ `engineering_shadow_score`
- Mode, score type/title, report, baseline และ versions ต้องสอดคล้องกัน
- Unavailable result ต้องส่ง `available=false`, `value=null` และ `reason`;
  ห้ามแทนด้วยคะแนนจำลอง

## 3. Contract versions ที่ Deploy

| Layer | Version |
|---|---|
| Sleep estimator | `bcg-audio-bed-5state-v1.27-gated-n2-progression` |
| Evidence | `zeep-sleep-state-evidence-v3.5-gated-n2-progression` |
| Transition policy | `zeep-semimarkov-30s-v1.16-n2-progression` |
| Personal/population baseline | `zeep-sleep-state-baseline-v1.8-sep1-cutover` |
| Historical replay | `zeep-sleep-history-reclass-v26-gated-n2-progression` |
| Session report | `zeep-session-report-v10.5-restore-summary` |
| Quality | `zeep-rest-quality-v8.4-recovery-target-guardrails` |
| Sleep Score formula | `zeep-sleep-score-v1.0-20-30-30-15-5` |
| Recovery Score formula | `zeep-recovery-score-v2.0-targeted-25-35-30-10` |
| Restore Summary | `zeep-restore-summary-v1.0` |

Client ต้องเก็บ version strings เพื่อใช้ Bug report แต่ไม่ควร hard-code ว่า
รู้จักได้เพียงเวอร์ชันเดียว ให้ยึด response schema และ ignore optional field ใหม่
ที่ยังไม่ใช้

## 4. Login contract ที่ทีม App ต้องส่ง

กระทบ `POST /api/auth/login`, `POST /api/session/login` และ
`POST /api/auth/qr/poll`:

```text
rest_mode: "sleep" | "nap_recovery"
target_duration_minutes: 30 | 90 | null
```

กติกา:

- Overnight: ส่ง `rest_mode="sleep"`; target ที่ Persist คือ 25,200 วินาที
- Nap 30: ส่ง `rest_mode="nap_recovery"`, target 30; Persist 1,800 วินาที
- Nap 90: ส่ง `rest_mode="nap_recovery"`, target 90; Persist 5,400 วินาที
- Nap ที่ไม่ส่ง target จะ default 30 นาทีเมื่อเริ่ม Session
- ค่า legacy เช่น `auto`, `relax`, `meditation`, `cycle_nap` ไม่อยู่ใน
  request enum ใหม่ การเปลี่ยนนี้อาจ Breaking สำหรับ Client เก่า

## 5. Rerun Session ล่าสุด

### 5.1 Scope และวิธีดำเนินการ

- ยืนยัน `occupied=false`, Safety ready และ Session จบแล้วก่อนหยุด Service
- Target เฉพาะ coded Session `s-20260910T134533Z-45c127`
- ระยะเวลา 464.1 นาที; Mode `sleep/overnight`
- สร้าง read-only replay manifest จาก `sessions.db`, `bcg.db` และ
  `profiles.json`
- ตรวจ explicit allowlist, input/code hash, quality tier และ per-Session blocker
- Dry-run promotion ก่อน Apply
- Apply ผ่าน private staging DB, exact report parity, SQLite integrity และ
  Raw hash guard
- เปิด Service กลับหลัง Apply สำเร็จ

ไม่ใช้ `reclassify_sleep_history.py --apply` เพราะเป็น Legacy audit-only และไม่ใช้
`rescore_session_reports.py --apply` เป็นตัวแทน Model rerun เพราะเครื่องมือนั้น
คำนวณ Report จาก State เดิมเท่านั้น

### 5.2 ผลก่อนและหลัง

| ค่า | ก่อน Rerun | หลัง Rerun | เปลี่ยนแปลง |
|---|---:|---:|---:|
| Sleep Score | 74.2 → แสดง 74 | 68.7 → แสดง 69 | −5 คะแนนที่แสดง |
| ระดับ | ดี | ปานกลาง | เปลี่ยน band |
| เวลาหลับโดยประมาณ | 196 นาที 20 วินาที | 198 นาที 30 วินาที | +2 นาที 10 วินาที |
| เวลาที่จัด Stage ได้ | 221 นาที 50 วินาที | 252 นาที 30 วินาที | +30 นาที 40 วินาที |
| W ภายในเวลาที่จัด Stage | 25 นาที 30 วินาที | 54 นาที | +28 นาที 30 วินาที |
| Sleep efficiency | 89% | 79% | −10 จุดเปอร์เซ็นต์ |
| Wake entries/awakenings | 1 | 4 | +3 |
| N1 ของเวลาหลับ | 36.7% | 38.5% | +1.8 จุดเปอร์เซ็นต์ |
| N2 ของเวลาหลับ | 47.8% | 41.1% | −6.7 จุดเปอร์เซ็นต์ |
| N3 ของเวลาหลับ | 7.4% | 9.1% | +1.7 จุดเปอร์เซ็นต์ |
| REM ของเวลาหลับ | 8.1% | 11.3% | +3.2 จุดเปอร์เซ็นต์ |
| Confirmed Stage coverage | 47.8% | 54.4% | +6.6 จุดเปอร์เซ็นต์ |

คะแนนย่อย:

| องค์ประกอบ | ก่อน | หลัง | เปลี่ยนแปลง |
|---|---:|---:|---:|
| Sleep opportunity | 11.3/20 | 9.3/20 | −2.0 |
| Sleep stability | 21.3/30 | 15.7/30 | −5.6 |
| Restorative architecture | 24.2/30 | 26.0/30 | +1.8 |
| Cycle expression | 15.0/15 | 15.0/15 | 0 |
| Data coverage | 2.4/5 | 2.7/5 | +0.3 |

คะแนนลดลงหลัก ๆ จาก Wake/fragmentation ที่ Stable 30-second replay ยืนยันได้
มากขึ้น ไม่ได้เกิดจากการลดเวลาหลับทั้งหมด เพราะเวลาหลับโดยประมาณเพิ่มเล็กน้อย
และ N3/REM เพิ่มขึ้น การเปรียบเทียบจำนวนแถวเดิมกับใหม่โดยตรงไม่ถูกต้องเนื่องจาก
Derived cadence เดิมและใหม่ต่างกัน จึงต้องเทียบ Duration และ Percentage ตามตาราง

### 5.3 Quality และข้อจำกัด

- Raw quality tier: `A`
- Paired HR/RR coverage: `97.6%`
- BCG coverage: `98%`
- Environment coverage: `100%`
- Confirmed Stage coverage: `54.4%`
- Evidence confidence: High `28.9%`, Medium `68.9%`, Low `2.2%`
- Review warnings:
  - `overnight_N1_over_30_percent`
  - `overnight_confirmed_stage_coverage_below_80_percent`
- Promotion blockers: ไม่มี

Tier และ coverage เป็น QA context สำหรับ Admin ไม่ใช่ตัวลบหรือซ่อนคะแนนที่ผ่าน
release gate แล้ว ผลยังเป็น preliminary ZEEP Wellness estimate ไม่ใช่การยืนยัน
Sleep Stage แบบ PSG

### 5.4 Audit และ Rollback

- Analysis run: `e9b33ba94ae4c4c9`
- Derived events ใหม่: 1,822
- Reviewed report parity: 1/1
- Rebuild Personal Baseline: 17 account profiles จาก Report ที่เข้าเกณฑ์
  โดยไม่ได้เขียน Raw หรือ Profile answers ใหม่
- Backup: `backup/sessions-pre-wellness-replay-20260911-052650.db`
- Private audit: `data/wellness-history-promotion-latest.json`
- Replay artifacts: `/home/pod1/zeep-private/replay-audits/20260911/`
  permission 0700;
  files permission 0600
- `sessions.db` integrity: `ok`
- `bcg.db` integrity: `ok`
- Raw Timeline hash: unchanged
- Raw BCG hash: unchanged
- ผลเดิม recover ได้จาก Backup และ Audit trail

## 6. Production verification

- Pi branch: `develop`
- Pi `develop` มี Runtime release `f8f70c3` และตาม `origin/develop`;
  docs-only commits หลัง release ไม่เปลี่ยน Runtime behavior
- Targeted regression บน Pi: `109/109` ผ่าน
- Full suite ของ release: `546` ผ่าน, `1` skipped
- GitHub Actions: ผ่าน
- Service: `active/running`
- `NRestarts=0`, `ExecMainStatus=0`
- Error log หลัง Restart: ไม่พบ error
- Public status: `occupied=false`, Safety `ready=true`
- `/dashboard`, `/sessions`, `/control`: HTTP 200
- Usage API แบบไม่ Login: HTTP 401 ตาม Auth contract
- Production OpenAPI มี Typed Usage Session endpoints ทั้งสามรายการ

## 7. Checklist สำหรับทีม App

### P0 — การแสดงผล

- [ ] ใช้ `score.type`, `score.title`, `score.available` และ `score.value`
  จาก Server; ห้าม hard-code ทุก Session เป็น Sleep Score
- [ ] `sleep_score` แสดงเฉพาะ Overnight; `recovery_score` แสดงเฉพาะ Nap
- [ ] ห้ามรวม Average ของสองคะแนน
- [ ] เมื่อ `available=false` แสดง `—`, “ข้อมูลไม่พอ” และ `reason`
- [ ] ห้าม fallback เป็นเลข 82 หรือข้อมูล Stage/Environment จำลอง
- [ ] ใช้ `level`/`level_key` จาก Server ไม่คำนวณ threshold ซ้ำใน Client
- [ ] แสดง `protocol_status` แยกจาก Score
- [ ] Nap ไม่หลับยังแสดง Recovery Score ได้; ห้ามบังคับวงแหวน N1/N2/N3/REM
- [ ] Restore Summary เป็นคำอธิบาย ไม่ใช่ Restore Score ใหม่
- [ ] ห้ามแสดง Whole-day readiness, ความพร้อมขับรถ หรือ “สดชื่นขึ้น”
  หากไม่มี subjective/pre-post data จริง

### P0 — Security และ networking

- [ ] ส่ง cookie credentials กับ Pull API
- [ ] ห้ามฝัง Admin/API token ใน Mobile app
- [ ] ไม่ cache Response ส่วนบุคคลใน shared storage
- [ ] รองรับ 401/403/404/422 โดยไม่ retry วน
- [ ] เก็บ `request_id`, report/formula versions ใน Bug report

### P1 — UX และ history

- [ ] เปลี่ยนชื่อหน้าเป็น “ประวัติการใช้งาน”
- [ ] ผู้ใช้เห็นเฉพาะตนเอง; Admin กรอง account/date/time ได้
- [ ] ใช้ local end date สำหรับจัด Overnight เข้าเช้าวันที่ดูผล
- [ ] รองรับ Pagination ด้วย `offset + returned`
- [ ] แสดง Confidence และ Data quality เป็นข้อมูลประกอบ ไม่ใช้ซ่อน Score เอง
- [ ] ใช้ component points/labels เป็น “องค์ประกอบคะแนน” ไม่เรียกว่าเหตุสาเหตุ

## 8. Checklist สำหรับทีม API กลาง

การตรวจ checkout `/Users/gm/Sites/zeep` รอบนี้พบช่องว่างที่ต้องยืนยันกับ
Deployment กลางอีกครั้ง:

### P0 — Data model และ ingest

- [ ] ยืนยันหรือเพิ่ม `POST /v1/sleep-sessions/ingest` ใน Source และ Deployment
- [ ] เปลี่ยน entity จากหนึ่ง User/หนึ่ง Night เป็น Usage Session
- [ ] ใช้ `external_session_id` เป็น unique key เพื่อรองรับ Nap หลายครั้งต่อวัน
- [ ] Persist `mode`, `quality_type`, `score_title`, nullable `score`,
  `available`, `reason`, `validation_status`, versions, confidence,
  `session_character`, `sleep_detected`, target/protocol status,
  components, findings และ guidance
- [ ] ห้ามส่ง Recovery Score ผ่าน field ที่มีความหมายเป็น `sleep_score`
  โดยไม่มี score type
- [ ] แยก aggregate และ Personal Baseline ตาม Mode
- [ ] รักษา data minimisation: ไม่ ingest Raw Timeline, Raw BCG,
  Health reference หรือ Progressive answers โดยปริยาย

### P0 — API contract

- [ ] รองรับ List/Summary/Detail และ Date/Time filters ตาม Usage API v1
- [ ] รองรับ Multiple Sessions ต่อวัน
- [ ] คง nullable และ unavailable semantics; ห้าม coalesce เป็นเลขจำลอง
- [ ] Publish OpenAPI จาก build เดียวกับ Production
- [ ] เพิ่ม backend-to-backend credential แบบ short-lived, scoped ต่อ Pod/account
  ก่อนเปิด Sync ระหว่าง Pod กับ Cloud
- [ ] เพิ่ม Session-level Pre/Post questionnaire contract ก่อนทำ readiness UX

### P1 — Migration

- [ ] Backfill mode/target เฉพาะรายการที่มีหลักฐานชัดเจน
- [ ] รายการ legacy ที่ไม่ทราบ mode/target ต้องเป็น unresolved/review required
- [ ] ห้ามอนุมาน Nap target 30/90 จากระยะเวลาที่เกิดขึ้นจริง
- [ ] เก็บ formula/report/quality versions เพื่อรองรับการคำนวณย้อนหลังแบบ Audit

## 9. Minimum QA matrix ก่อน App release

1. User A มองไม่เห็นรายการของ User B
2. User A ขอ Session ID ของ B ได้ 404
3. Admin เท่านั้นที่ใช้ `account_key`/`query`
4. Legacy `X-API-Token` ได้ 403
5. Response ไม่มี Raw BCG, samples, token หรือ profile answers
6. Overnight เป็น `sleep_score`
7. Nap เป็น `recovery_score`
8. Nap ที่ไม่หลับไม่ถูกบังคับให้มี Sleep Stage
9. Unavailable score คง `null` และมี reason
10. Restore Summary มี `creates_independent_score=false`
11. Mode conflict ทำให้ score unavailable/review required
12. Target 30/90 ถูก persist เป็น 1,800/5,400 วินาที
13. Legacy missing target ไม่ถูกเดาจาก duration
14. Success response เป็น `private, no-store`
15. App ไม่มี demo fallback ใน Production
16. OpenAPI มี Typed response ของทั้งสาม endpoints

## 10. สิ่งที่ไม่เปลี่ยนในรอบนี้

- ไม่แก้ Raw BCG หรือ Timeline
- ไม่แก้ข้อมูลผู้ใช้งาน/Profile answers
- ไม่สร้าง Whole-day Readiness score
- ไม่เปลี่ยน Stage จาก Sensor อากาศ
- ไม่แก้ Cloud ingest contract เดิม
- ไม่ Rerun Session อื่นนอกจาก coded Session ที่ระบุในหัวข้อ 5
- ไม่ถือผลว่า Clinical/AASM validated
