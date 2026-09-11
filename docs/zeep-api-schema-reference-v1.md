# ZEEP Usage Session API และ Restore Summary

**Schema reference:** `zeep.api.response` / `api_version = "1.0"`

**สถานะ:** Integration contract v1 (read-only, raw-free)

**ปรับปรุงล่าสุด:** 2026-09-11
**ฐานข้อมูล:** ผล Session ที่ Finalize แล้วเท่านั้น

เอกสารนี้เป็นคู่มืออ้างอิงสำหรับทีม Backend, Mobile, Web และ QA ของ
`Usage Session API` โดยระบุเส้นทาง, การยืนยันตัวตน, response envelope,
ชนิดข้อมูล, enum, nullable rules และกฎการแสดงผล `restore_summary` อย่างเป็น
ทางการ หาก implementation และเอกสารขัดกัน ให้ยึด Pydantic models ใน
[`restore_response_models.py`](../zeep_pod/sessions/restore_response_models.py)
และ [`usage_response_models.py`](../zeep_pod/sessions/usage_response_models.py)
ร่วมกับ OpenAPI ของ API ที่ deploy จริงเป็น source of truth แล้วแก้เอกสารนี้
ตามโมเดลใน release เดียวกัน

## 1. ขอบเขตและความหมาย

API นี้เป็นชั้นอ่านผล Session ที่ผ่านการปิด Session แล้ว ไม่ใช่ API ควบคุม
อุปกรณ์ ไม่รับ raw BCG, Sensor Timeline, packet, Profile answer หรือ token
และไม่คำนวณคะแนนใหม่ใน adapter

มีคะแนนหลักเพียงชนิดเดียวต่อ Session:

| Session mode | `score.type` | ชื่อแสดง | คำถามที่ตอบ |
|---|---|---|---|
| `sleep` | `sleep_score` | Sleep Score | การนอนครั้งนี้สนับสนุนการฟื้นตัวได้ดีเพียงใด |
| `nap_recovery` | `recovery_score` | Recovery Score | ช่วงพักนี้ร่างกายสงบและพักได้ตามเป้าหมายเพียงใด |
| `unknown` / metadata ขัดกัน | `unresolved_score` | Session Score | ยังสรุปชนิดคะแนนไม่ได้ |

`restore_summary` เป็น presentation layer ที่อธิบายคะแนนหลักเดิม จึงมี
`creates_independent_score = false` เสมอ และไม่ใช่คะแนนที่สาม ไม่เขียนกลับ
Sleep State หรือสั่ง Hardware

## 2. Endpoint และ HTTP contract

Base path คือ `/api/v1/usage-sessions` และทุก endpoint ใช้ `GET`:

| Method และ path | ใช้สำหรับ | `kind` ใน envelope |
|---|---|---|
| `GET /api/v1/usage-sessions` | รายการประวัติแบบแบ่งหน้า | `usage_session_list` |
| `GET /api/v1/usage-sessions/{session_id}/summary` | สรุปหนึ่ง Session สำหรับหน้าแรก | `usage_session_summary` |
| `GET /api/v1/usage-sessions/{session_id}` | รายงานหนึ่ง Session แบบละเอียดแต่ไม่มี raw | `usage_session_detail` |

`session_id` เป็น path string ความยาว 1–160 ตัวอักษร และต้อง URL-encode
เมื่อมีอักขระพิเศษ เป็น Immutable Pi external Session ID ไม่ใช่ username
หรือ email ใน path

Response สำเร็จทุก endpoint ส่ง header:

```http
Cache-Control: private, no-store
Content-Type: application/json
```

ห้าม client, proxy หรือ shared cache เก็บ payload นี้แบบสาธารณะ เพราะมีข้อมูล
สุขภาพ/พฤติกรรมรายบุคคล

### 2.1 Query parameters ของรายการ

ใช้กับ `GET /api/v1/usage-sessions` เท่านั้น

| Parameter | Type | Nullable/ค่าเริ่มต้น | ข้อจำกัดและความหมาย |
|---|---|---|---|
| `date_from` | `string` | nullable; ไม่มีค่าเริ่มต้น | รูปแบบ `YYYY-MM-DD`, inclusive, วันที่ท้องถิ่นของ Pod |
| `date_to` | `string` | nullable; ไม่มีค่าเริ่มต้น | รูปแบบ `YYYY-MM-DD`, inclusive, วันที่ท้องถิ่นของ Pod |
| `time_from` | `string` | non-null; `00:00` | รูปแบบ `HH:MM`, inclusive |
| `time_to` | `string` | non-null; `23:59` | รูปแบบ `HH:MM`, นาทีสุดท้าย inclusive |
| `account_key` | `string` | nullable; ไม่มีค่าเริ่มต้น | exact canonical email/account key; Admin เท่านั้น |
| `query` | `string` | nullable; ไม่มีค่าเริ่มต้น | ค้นหา email หรือ display name; Admin เท่านั้น; สูงสุด 160 ตัวอักษร |
| `limit` | `integer` | non-null; `50` | ช่วง 1–200 |
| `offset` | `integer` | non-null; `0` | ต้อง `>= 0` |

ต้องระบุ `date_from` หรือ `date_to` อย่างน้อยหนึ่งค่าเมื่อส่งเวลาไม่ใช่ค่า
เริ่มต้น หากไม่ส่งช่วงวันที่เลย ระบบใช้ประวัติที่อยู่ใน retention/history
window ของบริการ วันที่ Overnight จัดเข้าวันที่ Session จบตาม timezone ของ Pod
ช่วงวันที่เป็น inclusive และจำกัดตาม policy ของ history service (ปัจจุบันไม่เกิน
366 วัน)

ตัวอย่าง:

```http
GET /api/v1/usage-sessions?date_from=2026-09-01&date_to=2026-09-11&limit=50&offset=0
GET /api/v1/usage-sessions?account_key=tester%40example.com
GET /api/v1/usage-sessions?query=Tester&date_from=2026-09-01
```

User ทั่วไปถูกบังคับให้เห็นเฉพาะ account ของตนเอง การส่ง `account_key` ของคนอื่น
หรือส่ง `query` จะได้ `403`; Admin จึงจะกรองหลายบัญชีได้

## 3. Authentication, authorization และ privacy

ทุก endpoint เรียกผ่าน `require_user` และต้องมี Browser Login Session ที่ยังไม่หมดอายุ
โดยปกติ cookie มีชื่อ `zeep_auth` (HttpOnly, SameSite=Strict และอาจ Secure ตาม
environment) การส่ง cookie เป็นหน้าที่ของ browser/client ที่ผ่านการ login แล้ว

| Principal | สิทธิ์ |
|---|---|
| User cookie | อ่านรายการและรายละเอียดของ `principal.account_key` เท่านั้น |
| Admin cookie | อ่านทุกบัญชีและใช้ `account_key`/`query` filter ได้ |
| `X-API-Token` รุ่นเดิม (`auth_source=api_token`) | ถูกปฏิเสธด้วย `403` โดยตั้งใจ |
| ไม่มี Login หรือ cookie หมดอายุ | `401` |

แม้ endpoint เป็น `GET` และไม่ต้องส่ง CSRF header ในเส้นทางนี้ แต่ห้ามฝัง
credential ใน Mobile app, JavaScript bundle, URL, query string, log หรือไฟล์
ที่ส่งให้ลูกค้า การเชื่อม Backend-to-Backend รุ่นต่อไปต้องใช้ credential แบบ
account/Pod-scoped อายุสั้น พร้อม read audit; ห้ามนำ broad legacy token มาใช้แทน

การขอ Session ID ของบัญชีอื่นคืน `404` เหมือน ID ที่ไม่มีอยู่ เพื่อไม่เปิดเผย
การมีอยู่ของข้อมูลบุคคลอื่น

Payload สาธารณะเป็น positive allowlist โดยเฉพาะ `report.quality`; field ที่เพิ่ม
ในแหล่งข้อมูลจะไม่ถูกเผยแพร่จนกว่าจะเพิ่มใน Pydantic/OpenAPI response models
และผ่าน privacy review

## 4. Response envelope

ทุก HTTP 200 ใช้โครงสร้างเดียวกัน ตัวอย่างด้านล่างเป็น List response ที่ไม่มี
Session เพื่อให้เป็น payload ที่ตรวจสอบกับ schema ได้จริง:

```json
{
  "schema": "zeep.api.response",
  "api_version": "1.0",
  "kind": "usage_session_list",
  "generated_at": "2026-09-11T03:00:00.000+00:00",
  "request_id": "96be6449-b4d9-4ee7-b803-c5b269dbd533",
  "data": {
    "contract_version": "zeep.usage-session.v1",
    "history_name": "usage_history",
    "items": [],
    "summary": {
      "people_count": 0,
      "session_count": 0,
      "sleep_score_count": 0,
      "recovery_score_count": 0,
      "awaiting_score_count": 0,
      "average_sleep_score": null,
      "average_recovery_score": null
    },
    "pagination": {
      "limit": 50,
      "offset": 0,
      "returned": 0,
      "total": 0,
      "has_more": false
    },
    "range": null,
    "history_start_utc": "2026-09-01T00:00:00+00:00"
  }
}
```

| Field | Type | Nullable | ค่า/กฎ |
|---|---|---|---|
| `schema` | `string` | ไม่ได้ | ต้องเป็น `zeep.api.response` |
| `api_version` | `string` | ไม่ได้ | ปัจจุบัน `1.0` |
| `kind` | `enum<string>` | ไม่ได้ | `usage_session_list`, `usage_session_summary`, `usage_session_detail` |
| `generated_at` | `string` (RFC 3339 timestamp) | ไม่ได้ | เวลา server สร้าง response; มี timezone/offset |
| `request_id` | `string` (UUID) | ไม่ได้ | ใช้อ้างอิงใน log/support ticket; ไม่ใช่ Session ID |
| `data` | `object` | ไม่ได้ | รูปตาม `kind` |

Client ต้องตรวจ `schema`, `api_version`, `kind` และ `data.contract_version`
ก่อน parse field เฉพาะรุ่น และควรเก็บ `request_id` ไว้สำหรับ debug โดยไม่ log
ข้อมูลส่วนตัวทั้งก้อน

## 5. List data schema (`usage_session_list`)

```json
{
  "contract_version": "zeep.usage-session.v1",
  "history_name": "usage_history",
  "items": [],
  "summary": {
    "people_count": 0,
    "session_count": 0,
    "sleep_score_count": 0,
    "recovery_score_count": 0,
    "awaiting_score_count": 0,
    "average_sleep_score": null,
    "average_recovery_score": null
  },
  "pagination": {
    "limit": 50,
    "offset": 0,
    "returned": 0,
    "total": 0,
    "has_more": false
  },
  "range": null,
  "history_start_utc": "2026-09-01T00:00:00+00:00"
}
```

| Field | Type | Nullable | ค่า/กฎ |
|---|---|---|---|
| `contract_version` | `string` | ไม่ได้ | `zeep.usage-session.v1` |
| `history_name` | `string` | ไม่ได้ | `usage_history` |
| `items` | `array<SessionItem>` | ไม่ได้ | อาจว่าง; เรียงล่าสุดก่อนตาม history service |
| `summary` | `UsageHistorySummary` | ไม่ได้ | aggregate 7 field ตาม schema ได้แก่จำนวนคน/Session/คะแนนแต่ละประเภท/คะแนนที่ยังไม่พร้อม และค่าเฉลี่ยแยกประเภท |
| `pagination` | `Pagination` | ไม่ได้ | ข้อมูลแบ่งหน้า |
| `range` | `UsageHistoryRange` | nullable | ช่วงเวลาที่ service resolve: `start_utc`, `end_utc`, `start_local`, `end_local`, `timezone`, `day_assignment=session_end_local_date`; field อื่นไม่อนุญาต |
| `history_start_utc` | `string` (RFC 3339) | ไม่ได้ | จุดเริ่มประวัติที่ค้นได้ |

### 5.1 Pagination

| Field | Type | Nullable | กฎ |
|---|---|---|---|
| `limit` | `integer` | ไม่ได้ | 1–200; สะท้อน request ที่ validate แล้ว |
| `offset` | `integer` | ไม่ได้ | `>= 0` |
| `returned` | `integer` | ไม่ได้ | จำนวน item ในหน้านี้; `0..limit` |
| `total` | `integer` | ไม่ได้ | จำนวนทั้งหมดใน scope/filter |
| `has_more` | `boolean` | ไม่ได้ | `offset + returned < total` |

เมื่อ `has_more=true` ให้เรียกหน้าถัดไปด้วย `offset + returned` ไม่ควรเดาจาก
`limit` เพราะจำนวนผลอาจเปลี่ยนเมื่อ Session ใหม่ถูก Finalize

## 6. Session item schema

`items[]` และ `data` ของ summary/detail ใช้ shape เดียวกันเป็นหลัก โดย detail
เพิ่ม `report` และ version metadata ของ estimator/policy

| Field | Type | Nullable | ค่า/กฎ |
|---|---|---|---|
| `contract_version` | `string` | ไม่ได้ | `zeep.usage-session.v1` |
| `session_id` | `string` | ไม่ได้ | ID ที่ใช้เรียก detail; ต้องยาว 1–160 ตัวอักษร และ legacy row ที่ไม่มี ID ไม่อยู่ใน public contract นี้ |
| `user` | `UserIdentity` | ไม่ได้ | email-first; ไม่มี username ใน public contract |
| `started_at_utc` | `string` (RFC 3339) | nullable | เวลาเริ่มบันทึก |
| `ended_at_utc` | `string` (RFC 3339) | nullable | เวลา Finalize; รายการ API ควรเป็น Session ปิดแล้ว |
| `duration_s` | `number` | nullable | วินาที; ไม่ติดลบเมื่อมีค่า |
| `end_reason` | `string` | nullable | เหตุผลปิด Session จาก lifecycle |
| `sample_count` | `integer` | nullable | จำนวน sample ที่จัดเก็บ; ไม่ใช่คะแนน |
| `mode` | `Mode` | ไม่ได้ | โหมด canonical จาก session/released quality |
| `score` | `Score` | ไม่ได้ | คะแนนหลักที่ release แล้วหรือ unavailable |
| `restore_summary` | `RestoreSummary` | ไม่ได้ | อธิบาย `score` เดิม |
| `data_quality` | `DataQuality` | ไม่ได้ | coverage/confidence ที่เปิดเผยได้ |
| `versions` | `Versions` | ไม่ได้ | version สำหรับ audit |
| `result_provenance` | `ResultProvenance` | ไม่ได้ | แหล่งผลและนโยบายการคำนวณ |
| `session_closed` | `boolean` | ไม่ได้ | true เมื่อมี `ended_at_utc` |
| `score_revision_policy` | `string` | ไม่ได้ | ปัจจุบัน `versioned_recalculation_with_audit` |
| `report` | `Report` | มีเฉพาะ detail; อาจเป็น `{}` ในข้อมูล legacy | report แบบ compact, raw-free |
| `sleep_policy_versions` | `SleepPolicyVersions` | มีเฉพาะ detail; อาจว่าง | field คงที่ `evidence`, `baseline`, `transition`, `g2_ontology`, `terminal_wake`; แต่ละค่าเป็น `string|null` |
| `sleep_estimator_versions` | `object<string, integer>` | มีเฉพาะ detail; อาจว่าง | key เป็นชื่อ/version ของ estimator และ value เป็นจำนวน sample ที่ไม่ติดลบ |

`sleep_policy_versions` ไม่ใช่ map ที่เพิ่ม key ได้อิสระ ส่วน
`sleep_estimator_versions` เป็น map แบบ dynamic เพื่อรองรับหลาย estimator ใน
Session เดียว โดยทุก key ต้องไม่ว่างและทุกจำนวนต้อง `>= 0`

### 6.1 UserIdentity

| Field | Type | Nullable | ค่า/กฎ |
|---|---|---|---|
| `email` | `string` | nullable | email ที่ normalize แล้ว; ค่าแนะนำสำหรับ UI/account scope |
| `display_name` | `string` | nullableได้ใน legacy; ปกติ fallback เป็น email | ชื่อแสดง ไม่ใช่ตัวระบุสิทธิ์ |
| `canonical_identifier` | `string` | nullable | email หรือ legacy account key ที่ normalized |
| `identity_type` | `enum<string>` | ไม่ได้ | `email` หรือ `legacy_account_key` |

ห้ามใช้ `display_name` เป็น key และห้ามแสดง account ของผู้อื่นแม้ response จาก
Admin จะมีหลายรายการ

## 7. Core result types

### 7.1 Mode

| Field | Type | Nullable | ค่า/กฎ |
|---|---|---|---|
| `key` | `enum<string>` | ไม่ได้ | `sleep`, `nap_recovery`, `unknown` |
| `label` | `string` | ไม่ได้ | `Overnight Recovery`, `Nap & Refresh` หรือ `ยังไม่ทราบรูปแบบการพัก` |
| `requested` | `enum<string>` | ไม่ได้ | mode canonical ที่ request/session ระบุ: `sleep`, `nap_recovery` หรือ `unknown`; ต้องตรงกับ `key` |
| `resolved` | `string` | nullable | mode ที่ quality policy ยืนยัน; อาจไม่มี |
| `sleep_required` | `boolean` | ไม่ได้ | Overnight=true; Nap=false |
| `target` | `Target` | nullable | เป้าหมาย duration; Overnight อาจไม่มี |
| `review_required` | `boolean` | ไม่ได้ | true เมื่อ mode unresolved หรือ metadata conflict |
| `validation_status` | `enum<string>` | ไม่ได้ | `mode_confirmed`, `mode_unresolved`, `mode_metadata_conflict` |
| `conflicts` | `array<ModeConflict>` | ไม่ได้ | ปกติว่าง; รายละเอียดแหล่งที่ขัดกัน |

### 7.2 Target

| Field | Type | Nullable | ค่า/กฎ |
|---|---|---|---|
| `key` | `string` | nullable | key ของ target policy |
| `label` | `string` | nullable | label สำหรับ UI |
| `seconds` | `number` | nullable | target วินาที |
| `minutes` | `number` | nullable | target นาที; อาจ derive จาก seconds |
| `recommended_range_minutes` | `array<number>` (length 2) | nullable | lower/upper นาที |
| `completion_pct` | `number` | nullable | เปอร์เซ็นต์ทำได้ตามเป้าหมาย |
| `protocol_status` | `object` | ไม่ได้ | metadata สถานะ protocol; อาจว่าง `{}` |

### 7.3 Score

| Field | Type | Nullable | ค่า/กฎ |
|---|---|---|---|
| `type` | `enum<string>` | ไม่ได้ | `sleep_score`, `recovery_score`, `unresolved_score` |
| `title` | `string` | ไม่ได้ | ชื่อคู่กับ type |
| `value` | `number` | nullable | 0–100 เมื่อ `available=true`; ต้องเป็น `null` เมื่อ unavailable |
| `available` | `boolean` | ไม่ได้ | true เมื่อ released score ผ่าน validation |
| `level` | `string` | nullable | ระดับจาก quality model |
| `formula_version` | `string` | nullable | สูตรที่ปล่อยจริง; legacy บางรายการอาจไม่มี; ไม่ใช่ shadow formula |
| `quality_model_version` | `string` | nullable | version ของ quality model |
| `validation_status` | `string` | nullable | เช่น `preliminary_wellness_estimate` หรือ conflict status |
| `clinical_validated` | `boolean` | ไม่ได้ | ปัจจุบันโดยทั่วไป false; ไม่ใช่ใบรับรองทางการแพทย์ |
| `reason` | `string` | nullable | เหตุผลที่ unavailable/ข้อจำกัด |
| `review_required` | `boolean` | ไม่ได้ | ต้องตรวจ metadata/release หรือไม่ |

Invariant สำคัญ: `available=false` ⇒ `value=null`, UI ต้องไม่ fallback ไปใช้
`engineering_shadow_score`, `score_unrounded` หรือค่าเดิมจาก report

### 7.4 DataQuality

| Field | Type | Nullable | ค่า/กฎ |
|---|---|---|---|
| `level` | `string` | nullable | ระดับคุณภาพของข้อมูล |
| `label` | `string` | nullable | label ภาษาไทย |
| `coverage` | `object` | ไม่ได้ | ค่า coverage ที่เปิดเผยได้; key ย่อยอาจ nullable |
| `confidence` | `object` | ไม่ได้ | score confidence; อาจว่าง `{}` |
| `confidence_distribution` | `object` | nullable | distribution สำหรับ QA |
| `coverage_contributes_points` | `boolean` | ไม่ได้ | coverage ถูกคิดในสูตรหรือไม่ |
| `coverage_points` | `number` | nullable | คะแนนส่วน coverage ที่ release |
| `coverage_max_points` | `number` | nullable | คะแนนเต็มส่วน coverage |
| `coverage_can_hide_score` | `boolean` | ไม่ได้ | ปัจจุบัน false; ห้ามใช้ hidden veto |

`coverage`, `confidence` และ `confidence_distribution` ใช้ positive allowlist;
field อื่นจากข้อมูลต้นทางจะไม่ถูกเผยแพร่ผ่าน API นี้:

- `coverage`: `recording_pct`, `bcg_pct`, `sleep_stage_pct`,
  `environment_pct`, `ratio`, `pct`, `points`, `max_points`, `score_component`
- `confidence`: `level`, `label`, `session_coverage_pct`,
  `paired_hr_rr_coverage_pct`, `coverage_is_admin_qa_context`,
  `coverage_can_hide_score`
- `confidence_distribution`: `high`, `medium`, `low`

Client ต้องรองรับ subkey ที่อนุมัติแต่ไม่มีข้อมูลในบาง Session โดยไม่เดาค่าแทน
และห้ามใช้ field นอก allowlist เป็นเงื่อนไขความปลอดภัย

### 7.5 Versions และ provenance

`versions`:

| Field | Type | Nullable |
|---|---|---|
| `result_contract` | `string` | ไม่ได้ |
| `session_report` | `string` | nullable |
| `score_formula` | `string` | nullable |
| `score_quality_model` | `string` | nullable |
| `restore_summary` | `string` | ไม่ได้ |

`result_provenance`:

| Field | Type | Nullable | ค่า/กฎ |
|---|---|---|---|
| `source` | `enum<string>` | ไม่ได้ | `persisted_final_summary` หรือ `display_recomputed_report` |
| `display_recomputed` | `boolean` | ไม่ได้ | recompute เพื่อ display หรือไม่ |
| `display_recomputed_from_version` | `string` | nullable | report version ต้นทาง |
| `persisted_record_unchanged` | `boolean` | ไม่ได้ | ต้อง true เมื่อ adapter ไม่เขียน raw ทับ |
| `score_recalculated_by_adapter` | `boolean` | ไม่ได้ | ต้อง false สำหรับ API นี้ |

## 8. Restore Summary schema

โครงสร้างหลัก:

```json
{
  "version": "zeep-restore-summary-v1.0",
  "available": true,
  "name": "ZEEP Restore Summary",
  "creates_independent_score": false,
  "source_score": {},
  "status": {},
  "session_scope": {},
  "drivers": {},
  "personal_baseline": {},
  "trend": {},
  "recommendation": {},
  "confidence": {},
  "subjective_outcome": {},
  "claim_boundary": {},
  "whole_day_readiness_available": false,
  "provenance": {}
}
```

| Field | Type | Nullable | ค่า/กฎ |
|---|---|---|---|
| `version` | `string` | ไม่ได้ | `zeep-restore-summary-v1.0` |
| `available` | `boolean` | ไม่ได้ | ตรงกับ availability ของ source score |
| `name` | `string` | ไม่ได้ | `ZEEP Restore Summary` |
| `creates_independent_score` | `boolean` | ไม่ได้ | false เสมอ |
| `source_score` | `ScoreReference` | ไม่ได้ | สำเนา canonical ของคะแนนหลัก |
| `status` | `Status` | ไม่ได้ | unavailable ได้เมื่อคะแนนไม่พร้อม |
| `session_scope` | `SessionScope` | ไม่ได้ | ขอบเขต Overnight/Nap |
| `drivers` | `Drivers` | ไม่ได้ | positive/attention ได้สูงสุด 2 รายการต่อกลุ่ม |
| `personal_baseline` | `PersonalBaseline` | ไม่ได้ | แยกตาม user และ mode |
| `trend` | `Trend` | ไม่ได้ | แนวโน้มเป็นจำนวน Session ไม่ใช่วัน |
| `recommendation` | `Recommendation` | ไม่ได้ | คำแนะนำหลัก 1 ข้อ |
| `confidence` | `Confidence` | ไม่ได้ | หลักฐานของ score |
| `subjective_outcome` | `SubjectiveOutcome` | ไม่ได้ | ต้องมาจาก questionnaire จริง |
| `claim_boundary` | `ClaimBoundary` | ไม่ได้ | ขอบเขตการตีความ |
| `whole_day_readiness_available` | `boolean` | ไม่ได้ | false เสมอใน v1 |
| `provenance` | `SummaryProvenance` | ไม่ได้ | ที่มาของ context/explanation |

### 8.1 SourceScore และ Status

`source_score` ใช้ field ชุดเดียวกับ Score หลัก แต่ public Restore Summary
รับประกันอย่างน้อย:

| Field | Type | Nullable |
|---|---|---|
| `type` | `enum<string>` | ไม่ได้ |
| `title` | `string` | ไม่ได้ |
| `value` | `number` | nullable; 0–100 หรือ null |
| `available` | `boolean` | ไม่ได้ |
| `formula_version` | `string` | nullable |
| `copied_without_recalculation` | `boolean` | ไม่ได้; true เสมอ |

`status`:

| Field | Type | Nullable | ค่า/กฎ |
|---|---|---|---|
| `key` | `enum<string>` | ไม่ได้ | Overnight: `sleep_restore_very_good`, `sleep_restore_good`, `pace_morning`, `prioritise_rest`; Nap: `rest_goal_full`, `rest_good`, `rest_partial`, `rest_more`; unavailable: `unavailable` |
| `label` | `string` | ไม่ได้ | ข้อความสำหรับ UI; ห้ามใช้แทน key ใน logic |
| `min_score` | `number` | nullable | null เมื่อ unavailable |
| `max_score` | `number` | nullable | null เมื่อ unavailable |
| `meaning` | `string` | ไม่ได้ | คำอธิบายความหมายสำหรับผู้ใช้ |
| `version` | `string` | ไม่ได้ | action-band policy version |

ช่วง status คือ 85–100, 70–84, 50–69 และ 0–49 ตามลำดับของแต่ละโหมด
หาก score unavailable หรือ mode unknown ต้องใช้ `key=unavailable` และห้าม
แสดงข้อความที่สื่อว่าฟื้นตัวดี

### 8.2 SessionScope

| Field | Type | Nullable | ค่า/กฎ |
|---|---|---|---|
| `mode` | `enum<string>` | ไม่ได้ | `sleep`, `nap_recovery`, `unknown` |
| `label` | `string` | ไม่ได้ | Overnight Recovery / Nap & Refresh / unresolved |
| `question` | `string` | ไม่ได้ | คำถามเฉพาะโหมด |
| `whole_day_readiness` | `boolean` | ไม่ได้ | false |
| `clinical_readiness` | `boolean` | ไม่ได้ | false |
| `updates_during_day` | `boolean` | ไม่ได้ | false |

### 8.3 Drivers และ Driver item

`drivers`:

| Field | Type | Nullable |
|---|---|---|
| `positive` | `array<Driver>` | ไม่ได้; อาจว่าง |
| `attention` | `array<Driver>` | ไม่ได้; อาจว่าง |
| `explainability_available` | `boolean` | ไม่ได้ |
| `selection` | `string` | nullable |
| `policy_version` | `string` | nullable |
| `environment_never_determines_sleep_state` | `boolean` | ไม่ได้; true |
| `events_are_associations_not_proven_causes` | `boolean` | ไม่ได้; true |
| `reason` | `string` | nullable; ใช้เมื่อ unavailable |

`Driver` เป็น union ตาม `category`:

| Field | Type | Nullable | ค่า/กฎ |
|---|---|---|---|
| `key` | `string` | ไม่ได้ | เช่น `sleep_stability`, `goal_duration`, `environment_sound` |
| `category` | `enum<string>` | ไม่ได้ | `score_component`, `environment` |
| `label` | `string` | ไม่ได้ | label สำหรับ UI |
| `message` | `string` | ไม่ได้ | คำอธิบายที่ไม่อ้างเหตุเป็นสาเหตุเด็ดขาด |
| `direction` | `enum<string>` | ไม่ได้ | `positive`, `attention` |
| `earned_points` | `number` | nullable | มีเมื่อ score component |
| `max_points` | `number` | nullable | มีเมื่อ score component |
| `attainment_pct` | `number` | nullable | 0–100; มีเมื่อ score component |
| `severity` | `enum<string>` | nullable | environment: `excellent`, `good`, `fair`, `poor`, `critical`, `unavailable` |
| `action` | `string` | nullable | การกระทำที่แนะนำ |
| `affects_source_score` | `boolean` | ไม่ได้ |
| `relationship` | `enum<string>` | nullable | `session_context_only`, `recovery_score_component_and_session_context` |
| `causal_claim` | `boolean` | ไม่ได้; false |
| `priority` | `string` | nullable | เช่น `safety_review` |

องค์ประกอบ score ที่รองรับ: Overnight (`sleep_opportunity`,
`sleep_stability`, `restorative_architecture`, `cycle_expression`) และ Nap
(`goal_duration`, `physiological_response`, `rest_continuity`,
`environment_support`) แต่ UI ต้อง render จาก array ไม่ hard-code รายการ

Environment ใน Overnight มีความสัมพันธ์ `session_context_only`; ใน Nap อาจมี
`recovery_score_component_and_session_context` ตามสูตรที่ release แล้ว
Environment ไม่ได้กำหนด Sleep State และ event เป็น association ไม่ใช่ causation

### 8.4 Personal Baseline และ Trend

`personal_baseline`:

| Field | Type | Nullable | ค่า/กฎ |
|---|---|---|---|
| `version` | `string` | ไม่ได้ |
| `mode` | `enum<string>` | ไม่ได้ | `sleep`, `nap_recovery`, `unknown` |
| `maturity` | `BaselineMaturity` | ไม่ได้ |
| `comparison` | `BaselineComparison` | ไม่ได้ |
| `affects_source_score` | `boolean` | ไม่ได้; false |
| `population_prior_is_cold_start_only` | `boolean` | ไม่ได้; true |
| `must_not_mix_sleep_and_nap_sessions` | `boolean` | ไม่ได้; true |

`maturity.key` คือ `learning` (0–2 sessions), `early` (3–6), `active` (7–13)
หรือ `stable` (>=14) และมี `confidence` เป็น `insufficient|low|medium|high`.
การเปรียบเทียบเริ่มใช้งานเมื่อมีอย่างน้อย 7 Session ใน mode เดียวกัน

`comparison` เมื่อมีข้อมูล:

| Field | Type | Nullable | ค่า/กฎ |
|---|---|---|---|
| `available` | `boolean` | ไม่ได้ |
| `key` | `enum<string>` | nullable | `below_typical`, `near_typical`, `within_typical`, `above_typical` |
| `label` | `string` | nullable |
| `current_score` | `number` | nullable |
| `baseline_median` | `number` | nullable |
| `delta_points` | `number` | nullable |
| `typical_range` | `array<number>` length 2 | nullable |
| `mode_specific` | `boolean` | nullable; true เมื่อมี comparison |
| `reason` | `string` | nullable | มักใช้เมื่อ `available=false` |

`trend` ใช้ field `available:boolean`, `unit:"sessions"`, `windows:object`,
`mode_specific:boolean`, `whole_day_readiness_trend:boolean` โดย window ที่
รองรับคือ `7`, `14`, `30`; แต่ละ window มี `session_count:integer`,
`average:number`, `latest:number` หากข้อมูลไม่ถึง 3 Session ให้ `available=false`
และ `windows={}`

### 8.5 Recommendation, Confidence และ subjective outcome

`recommendation`:

| Field | Type | Nullable | ค่า/กฎ |
|---|---|---|---|
| `primary` | `string` | ไม่ได้ |
| `source_driver_key` | `string` | nullable |
| `version` | `string` | ไม่ได้ |
| `one_action_only` | `boolean` | ไม่ได้; true |
| `automatic_actuation` | `boolean` | ไม่ได้; false |
| `medical_advice` | `boolean` | ไม่ได้; false |

`confidence` มี `level: high|medium|low|unknown`, `label:string` และ
`session_coverage_pct:number|null`, `paired_hr_rr_coverage_pct:number|null`,
`changes_source_score:boolean` (false), `admin_qa_context:boolean` (true)

`subjective_outcome`:

| Field | Type | Nullable | ค่า/กฎ |
|---|---|---|---|
| `status` | `enum<string>` | ไม่ได้ | `measured`, `not_measured` |
| `label` | `string` | ไม่ได้ |
| `freshness_delta` | `number` | nullable | มีเฉพาะ questionnaire จริง |
| `activity_readiness` | `number` | nullable | มีเฉพาะ questionnaire จริง; โดยปกติ 0–10 |
| `source` | `string` | nullable | เช่น `session_questionnaire` |
| `sensor_inferred` | `boolean` | ไม่ได้; false |

ห้ามอนุมาน `freshness_delta` หรือ `activity_readiness` จาก HR/RR, BCG หรือ
คะแนนหลัก หากไม่มีคำตอบจริงให้ส่ง `status=not_measured` และค่าเป็น null

`claim_boundary` เป็น boolean map ที่ต้องมีอย่างน้อย:
`wellness_estimate=true`, `medical_diagnosis=false`,
`whole_day_readiness=false`, `training_load_included=false`,
`daytime_activity_included=false`, `freshness_not_inferred_from_sensor=true`,
`environment_association_is_not_causation=true`

## 9. Report ใน detail endpoint

`report` เป็น compact application-safe report เฉพาะ `GET /{session_id}`
เท่านั้น ไม่ใช่ raw export ฟิลด์ top-level ที่อาจปรากฏ (ฟิลด์ที่ไม่มีข้อมูลอาจ
ถูกละเว้น ไม่ได้แปลว่าเป็น null) ได้แก่:

| Field | Type | Nullable/การปรากฏ |
|---|---|---|
| `available` | `boolean` | nullable/อาจถูกละเว้นใน legacy report |
| `reason` | `string` | nullable/อาจถูกละเว้น |
| `version` | `string` | nullable |
| `product_positioning` | `string` | nullable |
| `intended_use` | `string` | nullable |
| `timeline_schema_version` | `integer\|string` | nullable | รองรับทั้งเลข schema และ legacy string |
| `estimator_version` | `string` | nullable |
| `headline` | `string` | nullable; unavailable จะถูกแทนด้วย “ยังสรุปคะแนนไม่ได้” |
| `insight` | `string` | nullable |
| `quality` | `PublicQuality` | nullable/อาจถูกละเว้น; ใช้ nested positive allowlist |
| `rest_mode` | `Mode` | canonical report เป็น non-null; legacy report ที่ไม่ผ่าน release policy อาจไม่มี |
| `sleep` | `object` | nullable/อาจถูกละเว้นตาม mode/data |
| `stages` | `array<PublicStageSummary>` | nullable/อาจถูกละเว้น |
| `environment` | `array<PublicEnvironmentMetric>` | nullable/อาจถูกละเว้น |
| `environment_assessment` | `object` | nullable/อาจถูกละเว้น; unavailable ถูกระงับ |
| `findings` | `array<PublicFinding>` | nullable/อาจถูกละเว้น; เมื่อ score unavailable จะเป็น `[]` |
| `post_session_guidance` | `object` | nullable; unavailable มี `available=false` |
| `restore_summary` | `RestoreSummary` | nullable/อาจถูกละเว้นใน legacy report |
| `data_quality` | `PublicReportDataQuality` | nullable/อาจถูกละเว้น |
| `disclaimer` | `string` | nullable |

เมื่อ `score.available=false` ระบบจะ override รายงานเพื่อความปลอดภัย:
`headline="ยังสรุปคะแนนไม่ได้"`, `findings=[]`, ละเว้น
`environment_assessment`, และ `post_session_guidance.available=false` พร้อม
`score_derived_claims_suppressed=true` ห้าม client แสดงข้อความเชิงบวกจาก
report เก่าหรือ field ภายใน

### 9.1 Continuity accounting และเวลาที่เข้าคะแนน

Detail endpoint เผยแพร่บัญชีเวลาที่ผ่าน positive allowlist ที่
`report.sleep.classification_accounting` เพื่อให้ App อธิบายได้ว่าทุกวินาที
ของ Session อยู่ที่ใด โดยไม่ต้องอ่าน Raw Timeline หรือคำนวณคะแนนซ้ำ

| Field | Type | ความหมาย |
|---|---|---|
| `direct_confirmed_s` | `number >= 0` | เวลาที่ estimator ยืนยัน State จากหลักฐานของ epoch นั้นโดยตรง |
| `continuity_carried_forward_s` | `number >= 0` | เวลาที่คง State ก่อนหน้าขณะ State ผู้ท้าชิงยังไม่ชัด |
| `provisional_hold_s` | `number >= 0` | ส่วนย่อยของ carry 1–2 epoch แรก; แสดงได้แต่ไม่เข้าคะแนน |
| `display_attributed_s` | `number >= 0` | เวลาที่ผูกกับ W/N1/N2/N3/REM สำหรับแสดง Timeline |
| `score_eligible_s` | `number >= 0` | เวลาที่ Server อนุญาตให้ใช้คำนวณคะแนน |
| `initial_wait_s` | `number >= 0` | WAIT ช่วงยืนยัน State แรก 60/120 วินาที |
| `no_data_s` | `number >= 0` | หลักฐานชีพจร/การหายใจ/BCG ไม่พอ |
| `off_bed_s` | `number >= 0` | ยืนยันว่าไม่มีผู้ใช้งานบนเตียง |
| `restart_display_hold_s` | `number >= 0` | State เดิมที่แสดงชั่วคราวหลัง service restart; ไม่เข้าคะแนน |
| `sensor_gap_s` | `number >= 0` | ช่องว่าง acquisition หรือเศษท้ายที่ไม่ครบ epoch |
| `excluded_from_score_s` | `number >= 0` | เวลาบันทึกทั้งหมดที่ไม่มีสิทธิ์เข้าคะแนน |
| `arithmetic_invariant` | `object` | `left_s`, `right_s`, `delta_s`, `holds` สำหรับตรวจว่ายอดเวลาครบ |

`provisional_hold_s` เป็นส่วนย่อยของ `continuity_carried_forward_s` จึงห้าม
นำมาบวกซ้ำในยอดเวลารวม สมการบัญชีหลักคือ:

```text
direct_confirmed_s + continuity_carried_forward_s + initial_wait_s +
no_data_s + off_bed_s + restart_display_hold_s + sensor_gap_s = recording_s
```

`report.sleep.actual_scored_s` เท่ากับ `classification_accounting.score_eligible_s`
ใน report รุ่นปัจจุบัน ส่วน `report.stages[]` ส่งทั้งค่าที่ใช้แสดงและค่าที่ใช้
คิดคะแนนแยกกัน:

| Field | Type | ใช้สำหรับ |
|---|---|---|
| `duration_s`, `pct_scored`, `pct_sleep` | `number` | การแสดงสัดส่วน State ที่ผูกกับ Timeline |
| `score_eligible_samples` | `integer >= 0` | จำนวน epoch ของ State นี้ที่มีสิทธิ์เข้าคะแนน |
| `score_eligible_duration_s` | `number >= 0` | เวลาของ State นี้ที่มีสิทธิ์เข้าคะแนน |
| `pct_score_eligible` | `number 0..100` | สัดส่วน State จากเวลาที่มีสิทธิ์เข้าคะแนนทั้งหมด |
| `pct_score_eligible_sleep` | `number 0..100` หรือ `null` | สัดส่วน N1/N2/N3/REM จากเวลาหลับที่มีสิทธิ์เข้าคะแนน |

Client ต้องใช้ค่าชุด `score_eligible_*` เมื่อต้องอธิบายฐานของคะแนน และใช้
`duration_s`/`pct_scored` เมื่อต้องแสดง Timeline เท่านั้น ห้ามอนุมานว่า
provisional, WAIT, NO DATA หรือ OFF BED เข้าคะแนน และห้ามสร้าง bucket
`Unclassified`

`report.quality` เป็น allowlist ของ application fields เช่น
`available`, `score`, `score_title`, `score_scope`, `validation_status`,
`clinical_validated`, `quality_type`, `session_character`, `sleep_detected`,
`level`, `estimated_sleep_s`, `actual_scored_s`, `wake_s`,
`wake_pct_recorded`, `sleep_efficiency_pct`, `awakenings`, `wake_entries`,
`deep_pct`, `rem_pct`, `stage_pct_of_sleep`, `rest_mode`, `duration_target`,
`physiology`, `body_response`, `environment_support`, `data_coverage`,
`cycles`, `component_points`, `component_max_points`, `component_order`,
`score_confidence`, `formula_version`, `version`, `outcome_interpretation`,
`disclaimer` และ field ที่อนุมัติใน response model รุ่นนั้น

ห้ามพึ่งพา field ที่ไม่อยู่ใน allowlist เช่น `engineering_shadow_score`,
`score_unrounded`, `release_requirements`, `samples`, `raw_samples`,
`bcg_base64`, `answers`, `profile`, `access_token`, `refresh_token` หรือ
`wellness_context`

## 10. ตัวอย่าง canonical payloads

### 10.1 Overnight Recovery (Sleep Score)

```json
{
  "schema": "zeep.api.response",
  "api_version": "1.0",
  "kind": "usage_session_summary",
  "generated_at": "2026-09-11T03:00:00.000+00:00",
  "request_id": "96be6449-b4d9-4ee7-b803-c5b269dbd533",
  "data": {
    "contract_version": "zeep.usage-session.v1",
    "session_id": "overnight-20260911-a1",
    "user": {
      "email": "tester@example.com",
      "display_name": "Tester",
      "canonical_identifier": "tester@example.com",
      "identity_type": "email"
    },
    "started_at_utc": "2026-09-10T18:00:00+00:00",
    "ended_at_utc": "2026-09-11T01:00:00+00:00",
    "duration_s": 25200,
    "end_reason": "normal_wake",
    "sample_count": 2520,
    "mode": {
      "key": "sleep",
      "label": "Overnight Recovery",
      "requested": "sleep",
      "resolved": "sleep",
      "sleep_required": true,
      "target": null,
      "review_required": false,
      "validation_status": "mode_confirmed",
      "conflicts": []
    },
    "score": {
      "type": "sleep_score",
      "title": "Sleep Score",
      "value": 76,
      "available": true,
      "level": "ดี",
      "formula_version": "zeep-sleep-score-v1.0-20-30-30-15-5",
      "quality_model_version": "zeep-sleep-quality-v1",
      "validation_status": "preliminary_wellness_estimate",
      "clinical_validated": false,
      "reason": null,
      "review_required": false
    },
    "restore_summary": {
      "version": "zeep-restore-summary-v1.0",
      "available": true,
      "name": "ZEEP Restore Summary",
      "creates_independent_score": false,
      "source_score": {
        "type": "sleep_score",
        "title": "Sleep Score",
        "value": 76,
        "available": true,
        "formula_version": "zeep-sleep-score-v1.0-20-30-30-15-5",
        "copied_without_recalculation": true
      },
      "status": {
        "key": "sleep_restore_good",
        "label": "ฟื้นตัวจากการนอนดี",
        "min_score": 70,
        "max_score": 84,
        "meaning": "ข้อมูลของ Session นี้สนับสนุนการฟื้นตัวจากการนอนในระดับดี",
        "version": "zeep-restore-action-bands-v1.0"
      },
      "session_scope": {
        "mode": "sleep",
        "label": "Overnight Recovery",
        "question": "การนอนครั้งนี้สนับสนุนการฟื้นตัวได้ดีเพียงใด",
        "whole_day_readiness": false,
        "clinical_readiness": false,
        "updates_during_day": false
      },
      "drivers": {
        "positive": [],
        "attention": [],
        "explainability_available": false,
        "selection": "highest_two_strengths_and_highest_two_attention_items",
        "policy_version": "zeep-restore-drivers-v1.0",
        "environment_never_determines_sleep_state": true,
        "events_are_associations_not_proven_causes": true
      },
      "personal_baseline": {
        "version": "zeep-restore-personal-baseline-v1.0",
        "mode": "sleep",
        "maturity": {
          "key": "stable",
          "label": "Baseline ส่วนบุคคลเสถียร",
          "confidence": "high",
          "sessions_used": 16,
          "comparison_minimum_sessions": 7,
          "stable_from_sessions": 14
        },
        "comparison": {
          "available": true,
          "key": "within_typical",
          "label": "อยู่ในช่วงปกติส่วนบุคคล",
          "current_score": 76,
          "baseline_median": 75,
          "delta_points": 1,
          "typical_range": [71, 80],
          "mode_specific": true
        },
        "affects_source_score": false,
        "population_prior_is_cold_start_only": true,
        "must_not_mix_sleep_and_nap_sessions": true
      },
      "trend": {
        "available": true,
        "unit": "sessions",
        "windows": {
          "7": {"session_count": 7, "average": 77.1, "latest": 76},
          "14": {"session_count": 14, "average": 75.8, "latest": 76},
          "30": {"session_count": 16, "average": 74.9, "latest": 76}
        },
        "mode_specific": true,
        "whole_day_readiness_trend": false
      },
      "recommendation": {
        "primary": "รักษารูปแบบที่ได้ผลและติดตามแนวโน้มจากหลายคืน",
        "source_driver_key": null,
        "version": "zeep-restore-recommendation-v1.0",
        "one_action_only": true,
        "automatic_actuation": false,
        "medical_advice": false
      },
      "confidence": {
        "level": "high",
        "label": "หลักฐานสูง",
        "session_coverage_pct": 96.2,
        "paired_hr_rr_coverage_pct": 94,
        "changes_source_score": false,
        "admin_qa_context": true
      },
      "subjective_outcome": {
        "status": "not_measured",
        "label": "ความรู้สึกหลังพัก · ไม่ได้วัด",
        "freshness_delta": null,
        "activity_readiness": null,
        "sensor_inferred": false
      },
      "claim_boundary": {
        "wellness_estimate": true,
        "medical_diagnosis": false,
        "whole_day_readiness": false,
        "training_load_included": false,
        "daytime_activity_included": false,
        "freshness_not_inferred_from_sensor": true,
        "environment_association_is_not_causation": true
      },
      "whole_day_readiness_available": false,
      "provenance": {
        "source": "persisted_context_with_canonical_explanation",
        "score_changed": false,
        "persisted_source_score_matched": true,
        "causal_claims": false
      }
    },
    "data_quality": {
      "level": "high",
      "label": "ข้อมูลครบ",
      "coverage": {"recording_pct": 100, "bcg_pct": 95},
      "confidence": {
        "level": "high",
        "session_coverage_pct": 96.2,
        "paired_hr_rr_coverage_pct": 94
      },
      "confidence_distribution": null,
      "coverage_contributes_points": true,
      "coverage_points": 5,
      "coverage_max_points": 5,
      "coverage_can_hide_score": false
    },
    "versions": {
      "result_contract": "zeep.session-result.v1",
      "session_report": "report-v-test",
      "score_formula": "zeep-sleep-score-v1.0-20-30-30-15-5",
      "score_quality_model": "zeep-sleep-quality-v1",
      "restore_summary": "zeep-restore-summary-v1.0"
    },
    "result_provenance": {
      "source": "persisted_final_summary",
      "display_recomputed": false,
      "display_recomputed_from_version": null,
      "persisted_record_unchanged": true,
      "score_recalculated_by_adapter": false
    },
    "session_closed": true,
    "score_revision_policy": "versioned_recalculation_with_audit"
  }
}
```

### 10.2 Nap & Refresh (Recovery Score)

Nap ไม่บังคับให้หลับและไม่ควรแสดง N2/N3/REM เป็นเงื่อนไขสำเร็จของโหมด:

```json
{
  "schema": "zeep.api.response",
  "api_version": "1.0",
  "kind": "usage_session_summary",
  "generated_at": "2026-09-11T10:00:00.000+00:00",
  "request_id": "2b6ad0e8-1c6a-4c8f-8ba7-8b08f7d44102",
  "data": {
    "contract_version": "zeep.usage-session.v1",
    "session_id": "nap-20260911-b2",
    "user": {
      "email": "tester@example.com",
      "display_name": "Tester",
      "canonical_identifier": "tester@example.com",
      "identity_type": "email"
    },
    "started_at_utc": "2026-09-11T09:00:00+00:00",
    "ended_at_utc": "2026-09-11T09:30:00+00:00",
    "duration_s": 1800,
    "end_reason": "target_reached",
    "sample_count": 1800,
    "mode": {
      "key": "nap_recovery",
      "label": "Nap & Refresh",
      "requested": "nap_recovery",
      "resolved": "nap_recovery",
      "sleep_required": false,
      "target": {
        "key": "short_rest",
        "label": "30 นาที",
        "seconds": 1800,
        "minutes": 30,
        "recommended_range_minutes": [20, 40],
        "completion_pct": 100,
        "protocol_status": {}
      },
      "review_required": false,
      "validation_status": "mode_confirmed",
      "conflicts": []
    },
    "score": {
      "type": "recovery_score",
      "title": "Recovery Score",
      "value": 74,
      "available": true,
      "level": "พักได้ดี",
      "formula_version": "zeep-recovery-score-v2.0-targeted-25-35-30-10",
      "quality_model_version": "zeep-recovery-quality-v2",
      "validation_status": "preliminary_wellness_estimate",
      "clinical_validated": false,
      "reason": null,
      "review_required": false
    },
    "restore_summary": {
      "version": "zeep-restore-summary-v1.0",
      "available": true,
      "name": "ZEEP Restore Summary",
      "creates_independent_score": false,
      "source_score": {
        "type": "recovery_score",
        "title": "Recovery Score",
        "value": 74,
        "available": true,
        "formula_version": "zeep-recovery-score-v2.0-targeted-25-35-30-10",
        "copied_without_recalculation": true
      },
      "status": {
        "key": "rest_good",
        "label": "พักได้ดี",
        "min_score": 70,
        "max_score": 84,
        "meaning": "ช่วงพักสนับสนุนการฟื้นตัวได้ดี",
        "version": "zeep-restore-action-bands-v1.0"
      },
      "session_scope": {
        "mode": "nap_recovery",
        "label": "Nap & Refresh",
        "question": "ช่วงพักนี้ร่างกายสงบและพักได้ตามเป้าหมายเพียงใด",
        "whole_day_readiness": false,
        "clinical_readiness": false,
        "updates_during_day": false
      },
      "drivers": {
        "positive": [],
        "attention": [],
        "explainability_available": false,
        "selection": "highest_two_strengths_and_highest_two_attention_items",
        "policy_version": "zeep-restore-drivers-v1.0",
        "environment_never_determines_sleep_state": true,
        "events_are_associations_not_proven_causes": true
      },
      "personal_baseline": {
        "version": "zeep-restore-personal-baseline-v1.0",
        "mode": "nap_recovery",
        "maturity": {
          "key": "active",
          "label": "Personal Baseline พร้อมใช้",
          "confidence": "medium",
          "sessions_used": 8,
          "comparison_minimum_sessions": 7,
          "stable_from_sessions": 14
        },
        "comparison": {
          "available": true,
          "key": "near_typical",
          "label": "ใกล้ค่ากลางส่วนบุคคล",
          "current_score": 74,
          "baseline_median": 73,
          "delta_points": 1,
          "typical_range": null,
          "mode_specific": true
        },
        "affects_source_score": false,
        "population_prior_is_cold_start_only": true,
        "must_not_mix_sleep_and_nap_sessions": true
      },
      "trend": {
        "available": true,
        "unit": "sessions",
        "windows": {
          "7": {"session_count": 7, "average": 72.4, "latest": 74}
        },
        "mode_specific": true,
        "whole_day_readiness_trend": false
      },
      "recommendation": {
        "primary": "รักษารูปแบบการพักที่ได้ผลและบันทึกความรู้สึกหลังพัก",
        "source_driver_key": null,
        "version": "zeep-restore-recommendation-v1.0",
        "one_action_only": true,
        "automatic_actuation": false,
        "medical_advice": false
      },
      "confidence": {
        "level": "medium",
        "label": "หลักฐานปานกลาง",
        "session_coverage_pct": 91.5,
        "paired_hr_rr_coverage_pct": 88.2,
        "changes_source_score": false,
        "admin_qa_context": true
      },
      "subjective_outcome": {
        "status": "measured",
        "label": "มีแบบประเมินก่อน–หลัง Session",
        "freshness_delta": 2,
        "activity_readiness": 8,
        "source": "session_questionnaire",
        "sensor_inferred": false
      },
      "claim_boundary": {
        "wellness_estimate": true,
        "medical_diagnosis": false,
        "whole_day_readiness": false,
        "training_load_included": false,
        "daytime_activity_included": false,
        "freshness_not_inferred_from_sensor": true,
        "environment_association_is_not_causation": true
      },
      "whole_day_readiness_available": false,
      "provenance": {
        "source": "persisted_context_with_canonical_explanation",
        "score_changed": false,
        "persisted_source_score_matched": true,
        "causal_claims": false
      }
    },
    "data_quality": {
      "level": "medium",
      "label": "หลักฐานปานกลาง",
      "coverage": {"recording_pct": 91.5, "bcg_pct": 88.2},
      "confidence": {
        "level": "medium",
        "session_coverage_pct": 91.5,
        "paired_hr_rr_coverage_pct": 88.2
      },
      "confidence_distribution": null,
      "coverage_contributes_points": false,
      "coverage_points": null,
      "coverage_max_points": null,
      "coverage_can_hide_score": false
    },
    "versions": {
      "result_contract": "zeep.session-result.v1",
      "session_report": "report-v-test",
      "score_formula": "zeep-recovery-score-v2.0-targeted-25-35-30-10",
      "score_quality_model": "zeep-recovery-quality-v2",
      "restore_summary": "zeep-restore-summary-v1.0"
    },
    "result_provenance": {
      "source": "persisted_final_summary",
      "display_recomputed": false,
      "display_recomputed_from_version": null,
      "persisted_record_unchanged": true,
      "score_recalculated_by_adapter": false
    },
    "session_closed": true,
    "score_revision_policy": "versioned_recalculation_with_audit"
  }
}
```

### 10.3 Unavailable / unresolved

ใช้เมื่อ mode ยังไม่ชัด, metadata conflict หรือ release gate ของ score ไม่ผ่าน:

```json
{
  "schema": "zeep.api.response",
  "api_version": "1.0",
  "kind": "usage_session_summary",
  "generated_at": "2026-09-11T03:00:00.000+00:00",
  "request_id": "d3e8e4c8-2c7c-44a0-9dd1-4bb4f84de990",
  "data": {
    "contract_version": "zeep.usage-session.v1",
    "session_id": "legacy-unknown-01",
    "user": {
      "email": null,
      "display_name": null,
      "canonical_identifier": null,
      "identity_type": "legacy_account_key"
    },
    "started_at_utc": "2026-09-10T18:00:00+00:00",
    "ended_at_utc": "2026-09-10T18:10:00+00:00",
    "duration_s": 600,
    "end_reason": "completed",
    "sample_count": 60,
    "mode": {
      "key": "unknown",
      "label": "ยังไม่ทราบรูปแบบการพัก",
      "requested": "unknown",
      "resolved": null,
      "sleep_required": false,
      "target": null,
      "review_required": true,
      "validation_status": "mode_unresolved",
      "conflicts": []
    },
    "score": {
      "type": "unresolved_score",
      "title": "Session Score",
      "value": null,
      "available": false,
      "level": null,
      "formula_version": null,
      "quality_model_version": null,
      "validation_status": "mode_unresolved",
      "clinical_validated": false,
      "reason": "ยังไม่ทราบรูปแบบการพัก จึงไม่อนุมานชนิดคะแนน",
      "review_required": true
    },
    "restore_summary": {
      "version": "zeep-restore-summary-v1.0",
      "available": false,
      "name": "ZEEP Restore Summary",
      "creates_independent_score": false,
      "source_score": {
        "type": "unresolved_score",
        "title": "Session Score",
        "value": null,
        "available": false,
        "formula_version": null,
        "copied_without_recalculation": true
      },
      "status": {
        "key": "unavailable",
        "label": "ยังสรุปไม่ได้",
        "min_score": null,
        "max_score": null,
        "meaning": "ยังไม่ทราบรูปแบบการพัก จึงไม่อนุมานชนิดคะแนน",
        "version": "zeep-restore-action-bands-v1.0"
      },
      "session_scope": {
        "mode": "unknown",
        "label": "ยังไม่ทราบรูปแบบการพัก",
        "question": "ต้องระบุรูปแบบการพักก่อนจึงสรุปผลได้",
        "whole_day_readiness": false,
        "clinical_readiness": false,
        "updates_during_day": false
      },
      "drivers": {
        "positive": [],
        "attention": [],
        "explainability_available": false,
        "reason": "คะแนนหลักยังไม่พร้อม จึงไม่แสดงตัวขับคะแนน"
      },
      "personal_baseline": {
        "version": "zeep-restore-personal-baseline-v1.0",
        "mode": "unknown",
        "maturity": {
          "key": "learning",
          "label": "กำลังเรียนรู้",
          "confidence": "insufficient",
          "sessions_used": 0,
          "comparison_minimum_sessions": 7,
          "stable_from_sessions": 14
        },
        "comparison": {
          "available": false,
          "reason": "ต้องระบุรูปแบบการพักก่อนจึงเปรียบเทียบ Baseline ได้"
        },
        "affects_source_score": false,
        "population_prior_is_cold_start_only": true,
        "must_not_mix_sleep_and_nap_sessions": true
      },
      "trend": {"available": false, "reason": "คะแนนหลักยังไม่พร้อม", "windows": {}},
      "recommendation": {
        "primary": "ระบุรูปแบบการพักและตรวจความพร้อมของ Sensor ก่อนครั้งถัดไป",
        "source_driver_key": null,
        "version": "zeep-restore-recommendation-v1.0",
        "one_action_only": true,
        "automatic_actuation": false,
        "medical_advice": false
      },
      "confidence": {
        "level": "unknown",
        "label": "ยังไม่ระบุความครบของหลักฐาน",
        "session_coverage_pct": null,
        "paired_hr_rr_coverage_pct": null,
        "changes_source_score": false,
        "admin_qa_context": true
      },
      "subjective_outcome": {
        "status": "not_measured",
        "label": "ความรู้สึกหลังพัก · ไม่ได้วัด",
        "freshness_delta": null,
        "activity_readiness": null,
        "sensor_inferred": false
      },
      "claim_boundary": {
        "wellness_estimate": true,
        "medical_diagnosis": false,
        "whole_day_readiness": false,
        "training_load_included": false,
        "daytime_activity_included": false,
        "freshness_not_inferred_from_sensor": true,
        "environment_association_is_not_causation": true
      },
      "whole_day_readiness_available": false,
      "provenance": {
        "source": "derived_from_persisted_report_without_rescoring",
        "score_changed": false,
        "persisted_source_score_matched": false,
        "causal_claims": false
      }
    },
    "data_quality": {
      "level": null,
      "label": null,
      "coverage": {},
      "confidence": {},
      "confidence_distribution": null,
      "coverage_contributes_points": false,
      "coverage_points": null,
      "coverage_max_points": null,
      "coverage_can_hide_score": false
    },
    "versions": {
      "result_contract": "zeep.session-result.v1",
      "session_report": null,
      "score_formula": null,
      "score_quality_model": null,
      "restore_summary": "zeep-restore-summary-v1.0"
    },
    "result_provenance": {
      "source": "persisted_final_summary",
      "display_recomputed": false,
      "display_recomputed_from_version": null,
      "persisted_record_unchanged": true,
      "score_recalculated_by_adapter": false
    },
    "session_closed": true,
    "score_revision_policy": "versioned_recalculation_with_audit"
  }
}
```

## 11. Client rendering rules

1. ตรวจ `schema`, `api_version`, `kind` และ `contract_version` ก่อนอ่านข้อมูล
2. ใช้ enum `key`/`type` เป็น logic key; ใช้ `label`/`message` เป็นข้อความแสดงผลเท่านั้น
3. แสดงชื่อคะแนนตาม `score.type`; ห้ามเปลี่ยน Recovery Score เป็น Sleep Score
4. เมื่อ `available=false` ให้แสดง unavailable state และห้าม fallback ค่าคะแนนใด ๆ
5. แสดง `restore_summary.status`, `drivers`, `personal_baseline`, `trend` และ
   `recommendation` เป็นบริบทของ Session ไม่เรียกว่า Whole-day Readiness
6. Render driver จาก array และรองรับ array ว่าง/field nullable; ไม่สมมติว่ามีครบทุกประเภท
7. `subjective_outcome` จะแสดงความรู้สึกหรือความพร้อมได้ก็ต่อเมื่อ `status=measured`
8. ห้ามใช้ข้อความจาก Sensor เป็นข้ออ้างเหตุเชิงสาเหตุ เช่น “เสียงทำให้ตื่น” ให้ใช้
   ถ้อยคำเชิงความสัมพันธ์ เช่น “พบเสียงเพิ่มใกล้ช่วง W”
9. แยก Baseline ตาม `mode`; ห้ามผสม Overnight กับ Nap และอย่าใช้ Baseline เปลี่ยน score
10. ไม่ render field ที่ไม่รู้จักเป็นข้อมูลสำคัญโดยอัตโนมัติ และไม่ส่งต่อ raw/private field
11. ใช้ `request_id` สำหรับ support/debug แต่ redact email, token และ health detail จาก log
12. เคารพ `Cache-Control: private, no-store`; ไม่ persist payload ลง shared cache

## 12. Versioning และ compatibility

มี version อย่างน้อยสามชั้นและต้องเก็บแยกกัน:

| ชั้น | ตัวอย่าง |
|---|---|
| Transport | `schema=zeep.api.response`, `api_version=1.0` |
| Resource contract | `zeep.usage-session.v1` |
| Score/summary | `zeep-sleep-score-v1.0-20-30-30-15-5`, `zeep-recovery-score-v2.0-targeted-25-35-30-10`, `zeep-restore-summary-v1.0` |

การเพิ่ม optional field ที่ไม่เปลี่ยนความหมายเดิมเป็น backward-compatible ได้
แต่ client ต้อง ignore unknown fields และรองรับ optional/nullable field เสมอ
การ rename/remove field, เปลี่ยน enum semantics, เปลี่ยนหน่วย หรือเปลี่ยน
availability invariant ต้องออก contract/API version ใหม่พร้อม migration note

การคำนวณคะแนนย้อนหลังทำได้เฉพาะสูตรที่มี version และ Audit trail; raw sensor
record ต้อง immutable และ adapter นี้ต้องไม่ recalculate score (`score_recalculated_by_adapter=false`)

## 13. Error contract

ข้อผิดพลาดของ FastAPI ใช้ envelope มาตรฐานของ framework ไม่ใช่
`zeep.api.response`:

```json
{"detail": "กรุณาเข้าสู่ระบบ"}
```

หรือเมื่อเป็น error code:

```json
{
  "detail": {
    "code": "usage_history_scope_forbidden",
    "message": "ผู้ใช้ดูได้เฉพาะประวัติการใช้งานของตนเอง"
  }
}
```

| HTTP | กรณี | code ที่อาจพบ |
|---:|---|---|
| `401` | ไม่มี/หมดอายุ Browser Login Session | `login_required` หรือข้อความมาตรฐาน |
| `403` | ขอ scope ของบัญชีอื่น, ใช้ Admin filter ในฐานะ User, หรือใช้ broad `X-API-Token` | `usage_history_scope_forbidden`, `usage_api_scoped_credential_required`, `admin_required` |
| `404` | ไม่พบ Session หรืออยู่นอก scope | ข้อความ “ไม่พบ Session ในขอบเขตที่เข้าถึงได้” |
| `422` | query/path ไม่ผ่าน validation | วันที่/เวลาไม่ถูกต้อง, เวลาไม่มีวันที่, limit 0/>200, offset ติดลบ, path ยาวเกิน 160 |
| `500` | server/internal failure | ไม่ควรเผยรายละเอียดภายใน; ใช้ `request_id` ติดต่อทีม |

Client ควร parse `detail` ได้ทั้ง `string` และ object, แสดงข้อความที่ปลอดภัย
ต่อผู้ใช้ และไม่ retry `401/403/404/422` แบบวนไม่สิ้นสุด

## 14. Pydantic/OpenAPI models และการตรวจสอบ

ระบบเผยแพร่ Pydantic response models ของ envelope, list, item, score, mode,
Restore Summary และ public report แล้วในโมดูลต่อไปนี้:

- `zeep_pod/sessions/restore_response_models.py`
- `zeep_pod/sessions/usage_response_models.py`
- `zeep_pod/sessions/response_models.py` สำหรับ public re-export

FastAPI ผูก model เหล่านี้เป็น `response_model` ของ Usage Session ทั้งสาม
endpoint และสร้าง machine-readable schema ที่ `/openapi.json` อัตโนมัติ

หลักที่ models บังคับใช้:

- ใช้ `Literal`/enum สำหรับค่าที่เป็น enum และไม่ใช้ข้อความ UI เป็น discriminator
- ระบุ `Optional`/nullable ให้ตรงตารางนี้; โดยเฉพาะ `Score.value`
- กำหนด numeric bounds: score 0–100, pagination ตามช่วง, percentage 0–100
- แยก `SummaryResponse` กับ `DetailResponse` เพื่อบอกการมีอยู่ของ `report`
- ฝั่ง Server ใช้ `extra="forbid"` เพื่อจับ field หลุดจาก public allowlist;
  ฝั่ง Client ควร ignore unknown optional field เพื่อรองรับรุ่นย่อยในอนาคต
- ตัวอย่าง canonical ของ Overnight, Nap และ unavailable อยู่ในหัวข้อ 10;
  ส่วน `/openapi.json` เป็นแหล่ง machine-readable ของ type และ constraint
- ทดสอบ privacy allowlist ว่าไม่มี raw/credential/engineering shadow field
- ทดสอบ mode mismatch ว่า canonical mode คงเดิมแต่ score unavailable
- ทดสอบทุก endpoint ว่าได้ `Cache-Control: private, no-store`

OpenAPI ที่ deploy จริงควรเป็นเอกสาร machine-readable หลัก ส่วนเอกสารนี้เป็น
คำอธิบายการใช้งานและกฎการแสดงผลสำหรับมนุษย์ ทั้งสองต้องเปลี่ยน version พร้อมกัน
เมื่อมี breaking change

## 15. Privacy checklist ก่อน release

- [ ] User อ่านได้เฉพาะ email/account ของตัวเอง; Admin scope มี audit
- [ ] ไม่มี raw BCG, sample, packet, timeline, profile answer หรือ credential
- [ ] `available=false` ไม่มี shadow score และไม่มี positive score-derived claim
- [ ] `freshness_delta`/`activity_readiness` มีเฉพาะ questionnaire ที่วัดจริง
- [ ] ไม่มีคำวินิจฉัยหรือคำรับรอง readiness ทั้งวัน/ขับรถ/แข่งขัน
- [ ] response และ log ไม่ถูก cache/shared หรือส่งต่อข้าม account
- [ ] เก็บ `request_id` ได้โดยไม่เก็บ payload สุขภาพทั้งก้อน
