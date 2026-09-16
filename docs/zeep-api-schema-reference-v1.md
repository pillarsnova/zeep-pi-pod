# ZEEP Usage Session API และ Restore Summary

**Schema reference:** `zeep.api.response` / `api_version = "1.0"`

**สถานะ:** Integration contract v1 (read-only, raw-free)

**ปรับปรุงล่าสุด:** 2026-09-16
**ฐานข้อมูล:** ผล Session ที่ Finalize แล้วเท่านั้น

เอกสารนี้เป็นคู่มืออ้างอิงสำหรับทีม Backend, Mobile, Web และ QA ของ
`Usage Session API` โดยระบุเส้นทาง, การยืนยันตัวตน, response envelope,
ชนิดข้อมูล, enum, nullable rules และกฎการแสดงผล `restore_summary` อย่างเป็น
ทางการ หาก implementation และเอกสารขัดกัน ให้ยึด Pydantic models ใน
[`restore_response_models.py`](../sessions/restore_response_models.py),
[`usage_response_models.py`](../sessions/usage_response_models.py),
[`presentation_response_models.py`](../sessions/presentation_response_models.py) และ
[`user_profile_response_models.py`](../sessions/user_profile_response_models.py)
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
| `GET /api/v1/usage-sessions/users` | รายงานรวมหนึ่งแถวต่อผู้ใช้สำหรับ Admin | `usage_user_directory` |
| `GET /api/v1/usage-sessions/longitudinal` | ภาพรวมสะสมของผู้ใช้ แยก Overnight/Nap | `user_learning_profile` |
| `GET /api/v1/usage-sessions/longitudinal/ai-context` | Context แบบ allowlist สำหรับ advisory AI | `user_ai_context` |
| `GET /api/v1/usage-sessions/{session_id}/summary` | สรุปหนึ่ง Session สำหรับหน้าแรก | `usage_session_summary` |
| `GET /api/v1/usage-sessions/{session_id}/presentation` | ลำดับผลแบบไม่ซ้ำสำหรับ User/App | `usage_session_presentation` |
| `GET /api/v1/usage-sessions/{session_id}/development` | QA aggregate สำหรับ Admin เท่านั้น | `usage_session_development` |
| `GET /api/v1/usage-sessions/{session_id}` | รายงานหนึ่ง Session แบบละเอียดแต่ไม่มี raw | `usage_session_detail` |

สำหรับสอง endpoint `longitudinal` ผู้ใช้ไม่ส่ง account selector ส่วน Admin ส่ง
`X-Zeep-Account-Key: normalized@example.com` ใน header เท่านั้น ไม่ใช่ query string
เพื่อไม่ให้อีเมลถูกบันทึกใน URL access log

รายละเอียดสัญญาภาพรวมสะสมและข้อจำกัดของ AI อยู่ที่
[ZEEP User Learning Profile v1](zeep-user-learning-profile-v1.md) โดย User
อ่านได้เฉพาะบัญชีตนเอง ส่วน Admin ต้องระบุบัญชีด้วย header
`X-Zeep-Account-Key` AI Context ใช้สิทธิ์เดียวกันแต่ตัด direct identifiers,
Session ID, exact Session timestamp, demographic value และคำตอบแบบสอบถามออก
ข้อมูลยังเป็น linkable Personal Wellness Data ไม่ใช่ anonymous data และยังไม่
อนุญาต external AI egress ในรุ่นนี้

`session_id` เป็น path string ความยาว 1–160 ตัวอักษร และต้อง URL-encode
เมื่อมีอักขระพิเศษ เป็น Immutable Pi external Session ID ไม่ใช่ username
หรือ email ใน path

`GET /users` ใช้ Cookie ผู้ดูแลเท่านั้น และรวมตาม `canonical_identifier`
ซึ่งใช้อีเมลเป็นหลัก ชื่อที่เปลี่ยนได้เป็นเพียงข้อมูลแสดงผล จำนวนครั้งนับเฉพาะ
Session ที่จบตั้งแต่ `history_start_utc`; Profile ที่ยังไม่เคยใช้ยังแสดงด้วยค่า 0
เพื่อให้จำนวนบัญชีกับจำนวนผู้ใช้งานจริงไม่ถูกตีความปะปนกัน

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
| User cookie | อ่านรายการ รายละเอียด และ Presentation ของ `principal.account_key` เท่านั้น |
| Admin cookie | อ่านทุกบัญชี ใช้ `account_key`/`query` filter และอ่าน Development view ได้ |
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
    "history_start_utc": "2026-08-31T17:00:00+00:00"
  }
}
```

| Field | Type | Nullable | ค่า/กฎ |
|---|---|---|---|
| `schema` | `string` | ไม่ได้ | ต้องเป็น `zeep.api.response` |
| `api_version` | `string` | ไม่ได้ | ปัจจุบัน `1.0` |
| `kind` | `enum<string>` | ไม่ได้ | `usage_session_list`, `user_learning_profile`, `user_ai_context`, `usage_session_summary`, `usage_session_detail`, `usage_session_presentation`, `usage_session_development` |
| `generated_at` | `string` (RFC 3339 timestamp) | ไม่ได้ | เวลา server สร้าง response; มี timezone/offset |
| `request_id` | `string` (UUID) | ไม่ได้ | ใช้อ้างอิงใน log/support ticket; ไม่ใช่ Session ID |
| `data` | `object` | ไม่ได้ | รูปตาม `kind` |

Client ต้องตรวจ `schema`, `api_version`, `kind` และ `data.contract_version`
ก่อน parse field เฉพาะรุ่น และควรเก็บ `request_id` ไว้สำหรับ debug โดยไม่ log
ข้อมูลส่วนตัวทั้งก้อน

### 4.1 Longitudinal personal rest window

`GET /api/v1/usage-sessions/longitudinal` ส่ง `best_rest_window` ภายใต้
`data.modes.sleep.baseline` และแต่ละรายการใน
`data.modes.nap_recovery.targets[].baseline` เป็น observation จาก completed
Session ก่อนหน้าเท่านั้น โดยต้องเป็น Mode เดียวกัน ใช้สูตรคะแนนปัจจุบัน และสำหรับ
Nap ต้องเป็น target เดียวกัน จึงเริ่ม `available=true` ได้ตั้งแต่ครั้งที่ผู้ใช้มาใช้
ครั้งที่ 2 หลังมี Session ที่เข้าเกณฑ์แล้ว 1 ครั้ง (`first_visible_visit=2` และ
`current_session_excluded=true`)

เมื่อ Profile เก่าถูกเปิดผ่าน endpoint นี้ ระบบจะตรวจ version และ rebuild derived
Baseline ของบัญชีนั้นแบบ lazy หนึ่งครั้ง จึงไม่ต้องรอเริ่ม Session ใหม่และไม่แก้
Raw data, Sleep State หรือคะแนนเดิม

ถ้า observation มี evidence ต่ำ ระบบยังแสดงเวลาเป็น “ช่วงเวลาจากครั้งก่อน” ได้
แต่ต้องคง `outcome_supported=false`, ไม่ส่ง environment reference และไม่สร้าง
คำแนะนำปรับอุปกรณ์จากรายการนั้น

การเลือกรายการอ้างอิงเป็น deterministic ไม่ใช้ AI: เลือกคะแนนสูตรปัจจุบันสูงสุด
ก่อน จากนั้นเลือก evidence confidence สูงกว่า และ input ที่ใหม่กว่าตามลำดับ
(`method=highest_current_formula_score_then_evidence_then_most_recent`)
ผลนี้บอกเพียงว่า “ช่วงเวลานี้เคยให้ผลที่รองรับได้” ไม่พิสูจน์ว่าเป็นเวลาที่ผู้ใช้ชอบ
ไม่พิสูจน์เหตุและผล และ `outcome_supported=true` เป็นเพียง eligibility ของ
observation ต้นทาง ไม่ใช่คำรับรองผลลัพธ์ครั้งถัดไป

| Field | Type | Nullable | ค่า/กฎ |
|---|---|---|---|
| `version` | `literal<string>` | ไม่ได้ | `zeep-personal-rest-window-v1.2-bounded-partitioned-finite` |
| `available` | `boolean` | ไม่ได้ | `true` เมื่อมี prior completed same-mode/current-formula observation; Nap ต้อง same-target ด้วย |
| `status` | `enum<string>` | ไม่ได้ | `no_data`, `observed_once`, `learning`, `early`, `active`, `stable` |
| `maturity_confidence` | `enum<string>` | ไม่ได้ | `none`, `low`, `medium`, `high`; 1 Session เป็น `low` |
| `sessions_compared` | `integer >= 0` | ไม่ได้ | จำนวน prior eligible Session ที่นำมาเลือก |
| `first_visible_visit` | `literal<2>` | ไม่ได้ | observation แรกแสดงได้ใน visit 2 |
| `method` | `literal<string>` | ไม่ได้ | `highest_current_formula_score_then_evidence_then_most_recent` |
| `same_mode_only` | `literal<true>` | ไม่ได้ | ห้ามเทียบข้าม Overnight/Nap |
| `same_target_only` | `boolean` | ไม่ได้ | `true` สำหรับ Nap target-specific |
| `mode_group` | `enum<string>` | ไม่ได้ | `sleep`, `nap_recovery`; cold start อาจเป็น `unknown` |
| `target_key` | `enum<string>` | ได้ | `overnight_7h`, `nap_30`, `nap_90` หรือ `null` |
| `timezone` | `literal<string>` | ไม่ได้ | `Asia/Bangkok` |
| `start_local_minute` | `number 0..<1440` | ได้ | นาทีของวันท้องถิ่น; `null` เมื่อ unavailable |
| `end_local_minute` | `number 0..<1440` | ได้ | นาทีของวันท้องถิ่น; `null` เมื่อ unavailable |
| `duration_minutes` | `number >= 0` | ได้ | ระยะเวลาที่สังเกต; `null` เมื่อ unavailable |
| `crosses_midnight` | `boolean` | ไม่ได้ | ช่วงเวลาข้ามเที่ยงคืนหรือไม่ |
| `start_tolerance_minutes` | `15\|30` | ได้ | tolerance การแสดงช่วงเริ่ม; `null` เมื่อ unavailable |
| `score_type` | `enum<string>` | ได้ | `sleep_score`, `recovery_score` หรือ `null` |
| `score_title` | `enum<string>` | ได้ | `Sleep Score`, `Recovery Score` หรือ `null` |
| `score_value` | `number 0..100` | ได้ | คะแนนของ observation ที่เลือก; ไม่คำนวณหรือแก้คะแนนใด |
| `score_formula_version` | `enum<string>` | ได้ | สูตรปัจจุบันของ Score ที่เลือก หรือ `null` |
| `evidence_quality` | `enum<string>` | ไม่ได้ | `unknown`, `low`, `medium`, `high` |
| `outcome_supported` | `boolean` | ไม่ได้ | observation ต้นทางผ่าน eligibility; ไม่ใช่ preference/causal claim |
| `environment_reference_available` | `boolean` | ไม่ได้ | มี environment observation ที่อนุญาตให้แสดงหรือไม่ |
| `environment` | `BestRestWindowEnvironment` | ไม่ได้ | object แบบ strict; อาจว่างเมื่อไม่มีข้อมูล |
| `environment_role` | `literal<string>` | ไม่ได้ | `observed_successful_session_not_confirmed_preference` |
| `affects_score` | `literal<false>` | ไม่ได้ | ห้ามเปลี่ยน Sleep Score/Recovery Score |
| `affects_sleep_state` | `literal<false>` | ไม่ได้ | ห้ามเปลี่ยน W/N1/N2/N3/REM |
| `current_session_excluded` | `literal<true>` | ไม่ได้ | ไม่ใช้ Session ที่กำลังแสดง/กำลังทำเป็น reference |
| `automatic_device_control` | `literal<false>` | ไม่ได้ | ห้ามสั่งอุปกรณ์อัตโนมัติ |
| `requires_user_confirmation` | `literal<true>` | ไม่ได้ | ผู้ใช้ต้องยืนยันก่อนนำช่วงนี้ไปใช้ |

`BestRestWindowEnvironment` เป็น object แบบ strict ดังนี้:

| Field | Type | Nullable | ความหมาย |
|---|---|---|---|
| `temp_median` | `number` | ได้ | ค่ากลางอุณหภูมิที่สังเกต |
| `humidity_median` | `number` | ได้ | ค่ากลางความชื้นที่สังเกต |
| `co2_median` | `number` | ได้ | ค่ากลาง CO₂ ที่สังเกต |
| `lux_median` | `number` | ได้ | ค่ากลางแสงที่สังเกต |
| `sound_median` | `number` | ได้ | ค่ากลางเสียงที่สังเกต |

ทุก field อาจไม่มีใน object เมื่อไม่มี observation และ key อื่นถูกปฏิเสธโดย
strict response model

ภายใน `best_rest_window` จะไม่ส่ง Session ID, source Session ID หรือ exact source
timestamp โดยส่งเพียงนาทีของวันท้องถิ่นและ timezone ที่จำเป็นต่อการแสดงผล
อย่างไรก็ตาม response longitudinal ทั้งก้อนยังเป็น linkable Personal Wellness Data
ตามบัญชีผู้ใช้ ไม่ใช่ข้อมูล anonymous
นอกจากนี้ `best_rest_window` ไม่ถูกส่งใน
`GET /api/v1/usage-sessions/longitudinal/ai-context` ตราบใดที่ยังไม่มี
purpose-specific inference consent จึงห้ามใช้กับ AI inference, การควบคุมอัตโนมัติ,
คะแนน หรือ Sleep State

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
  "history_start_utc": "2026-08-31T17:00:00+00:00"
}
```

| Field | Type | Nullable | ค่า/กฎ |
|---|---|---|---|
| `contract_version` | `string` | ไม่ได้ | `zeep.usage-session.v1` |
| `history_name` | `string` | ไม่ได้ | `usage_history` |
| `items` | `array<SessionItem>` | ไม่ได้ | อาจว่าง; เรียงล่าสุดก่อนตาม history service |
| `summary` | `UsageHistorySummary` | ไม่ได้ | aggregate จำนวนคน/Session/คะแนนแต่ละประเภท/Session ที่ยังสรุปคะแนนไม่ได้ และค่าเฉลี่ยแยกประเภท; ค่าเฉลี่ยเป็น `null` เมื่อพบคะแนนต่าง formula version หรือไม่มี provenance; `awaiting_score_count` คงเป็น alias เดิมของ `without_score_count` ชั่วคราว |
| `pagination` | `Pagination` | ไม่ได้ | ข้อมูลแบ่งหน้า |
| `range` | `UsageHistoryRange` | nullable | ช่วงเวลาที่ service resolve: `start_utc`, `end_utc`, `start_local`, `end_local`, `timezone`, `day_assignment=session_end_local_date`; field อื่นไม่อนุญาต |
| `history_start_utc` | `string` (RFC 3339) | ไม่ได้ | จุดเริ่มประวัติที่ค้นได้; Pilot cutover `1 ก.ย. 2569 00:00 Asia/Bangkok` เท่ากับ `2026-08-31T17:00:00+00:00` |

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
| `label` | `string` | ไม่ได้ | `Overnight Recovery`, `Nap & Refresh` หรือ `กำลังระบุรูปแบบการพัก` |
| `requested` | `enum<string>` | ไม่ได้ | mode canonical ที่ request/session ระบุ: `sleep`, `nap_recovery` หรือ `unknown`; ต้องตรงกับ `key` |
| `resolved` | `string` | nullable | mode ที่ quality policy ยืนยัน; อาจไม่มี |
| `sleep_required` | `boolean` | ไม่ได้ | Overnight=true; Nap=false |
| `target` | `Target` | nullable | สูตรปัจจุบันต้องมี `overnight_7h`, `nap_30` หรือ `nap_90`; `null` ได้เฉพาะโหมด unresolved/ข้อมูล legacy ที่ยังยืนยันไม่ได้ |
| `review_required` | `boolean` | ไม่ได้ | true เมื่อ mode unresolved, metadata conflict หรือเวลา Session ต้องตรวจเทียบ Protocol |
| `protocol_review_required` | `boolean` | ไม่ได้ | true เมื่อเวลา/Target ของ Session ต้องให้ Admin ตรวจ โดยไม่ปิดคะแนนเมื่อผ่านเวลาขั้นต่ำของโหมด |
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
| `clinical_validated` | `literal<false>` | ไม่ได้ | Public API v1 บังคับ `false` เสมอ แม้ข้อมูลเก่าหรือต้นทางภายในจะระบุค่าอื่น |
| `reason` | `string` | nullable | เหตุผลที่ unavailable/ข้อจำกัด |
| `review_required` | `boolean` | ไม่ได้ | ต้องตรวจ metadata/release หรือไม่ |

Invariant สำคัญ: `available=false` ⇒ `value=null`, UI ต้องไม่ fallback ไปใช้
`engineering_shadow_score`, `score_unrounded` หรือค่าเดิมจาก report

Invariant ด้านขอบเขตผลิตภัณฑ์: `clinical_validated=false` เสมอใน Public API v1
เพราะผลทั้งหมดเป็นการประเมินเชิง Wellness ไม่ใช่การวินิจฉัยทางการแพทย์
adapter ต้องลดค่าจากข้อมูลเก่าที่เป็น `true` ให้เป็น `false` ก่อนเผยแพร่

นโยบาย v10.12/v8.10 ใช้เวลา Session ขั้นต่ำเป็น score-release gate เพียงข้อเดียว
หลังยืนยันโหมด: Overnight Recovery ≥5 ชั่วโมง และ Nap & Refresh ≥10 นาที
สำหรับ Nap ค่า Target, HR/RR, State/Bed หรือ Environment ที่ขาดใช้ neutral 75%
ในองค์ประกอบนั้นพร้อม confidence ต่ำ สำหรับ Overnight หากไม่มี State evidence เลย
ใช้คะแนนกลางแบบจำกัดไม่เกิน 50; HR/RR หรือ Environment component ที่ขาดใช้
neutral 75% แต่ Timeline ที่มีหลักฐานยืนยันว่าไม่พบช่วงหลับให้ Sleep Score 0
ค่า neutral ทุกกรณีต้องมี availability ตามจริงและห้ามนำเสนอว่า Sensor วัดได้
ระยะเวลา Nap ที่ต่างจากเป้าหมายหรือเกิน 120 นาทีเป็น Admin review เท่านั้น ไม่ใช่
hard maximum และไม่ปิดคะแนน

เมื่อหลักฐาน Sensor หลักไม่มีเลย API ใช้ bounded neutral 50, ตั้ง
`limited_evidence_neutral_score=true` และทำให้ผลรวม
`effective_component_points` ตรงกับ `score_unrounded=50.0`; UI ต้องใช้ข้อความ
หลักฐานจำกัดและไม่สร้างคำแนะนำจาก Sensor ที่ไม่ได้วัด

### 7.4 DataQuality

| Field | Type | Nullable | ค่า/กฎ |
|---|---|---|---|
| `level` | `string` | nullable | ระดับคุณภาพของข้อมูล |
| `label` | `string` | nullable | label ภาษาไทย |
| `coverage` | `object` | ไม่ได้ | ค่า coverage ที่เปิดเผยได้; key ย่อยอาจ nullable |
| `confidence` | `object` | ไม่ได้ | score confidence; อาจว่าง `{}` |
| `confidence_distribution` | `object` | nullable | distribution สำหรับ QA |
| `coverage_contributes_points` | `boolean` | ไม่ได้ | สูตรปัจจุบันเป็น `false`; ผลเก่าบางสูตรอาจเป็น `true` และต้องอ่านคู่ `formula_version` |
| `coverage_points` | `number` | nullable | สูตรปัจจุบันเป็น `0`; ผลเก่าอาจคงคะแนนเดิมเพื่อ Audit |
| `coverage_max_points` | `number` | nullable | สูตรปัจจุบันเป็น `0`; ผลเก่าอาจคงเพดานเดิมเพื่อ Audit |
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

สำหรับสูตรปัจจุบัน `coverage.score_component=false`, `coverage.points=0` และ
`coverage.max_points=0` ทั้ง Sleep Score และ Recovery Score ค่า Coverage ใช้สื่อ
ความมั่นใจและ QA เท่านั้น ไม่เพิ่ม ลด ซ่อน หรือปล่อยคะแนน แต่ API ยังอ่านผล Legacy
ตามสูตรที่บันทึกไว้โดยเปิดเผย `formula_version`; Client ห้ามนำค่าจากคนละสูตรมาเทียบ
โดยไม่แยก Version

### 7.5 Versions และ provenance

`versions`:

| Field | Type | Nullable |
|---|---|---|
| `result_contract` | `string` | ไม่ได้ |
| `session_report` | `string` | nullable |
| `score_formula` | `string` | nullable |
| `score_quality_model` | `string` | nullable |
| `restore_summary` | `string` | ไม่ได้ |
| `product_language` | `string` | ไม่ได้ |

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
`sleep_stability`, `restorative_architecture`, `physiological_response`,
`environment_support`) และ Nap
(`goal_duration`, `physiological_response`, `rest_continuity`,
`environment_support`) แต่ UI ต้อง render จาก array ไม่ hard-code รายการ

Environment เป็นองค์ประกอบแบบจำกัด 10 คะแนนของทั้ง Sleep Score และ Recovery
Score พร้อมทำหน้าที่อธิบายบริบทของ Session; ค่า Environment ไม่ได้กำหนด Sleep
State และ event เป็น association ไม่ใช่ causation Client จึงต้องใช้ driver จาก
องค์ประกอบคะแนนเป็นคำอธิบายผล และไม่เขียนเป็นเหตุทางการแพทย์

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
| `headline` | `string` | nullable; Session ที่ปิดแล้วและ unavailable ใช้ “ครั้งนี้ยังไม่มีคะแนน”; “กำลังเตรียมผลสรุป” ใช้เฉพาะ Session ที่ยังไม่ปิด |
| `insight` | `string` | nullable |
| `quality` | `PublicQuality` | nullable/อาจถูกละเว้น; ใช้ nested positive allowlist |
| `rest_mode` | `Mode` | canonical report เป็น non-null; legacy report ที่ไม่ผ่าน release policy อาจไม่มี |
| `sleep` | `object` | nullable/อาจถูกละเว้นตาม mode/data |
| `stages` | `array<PublicStageSummary>` | nullable/อาจถูกละเว้น |
| `environment` | `array<PublicEnvironmentMetric>` | nullable/อาจถูกละเว้น |
| `environment_assessment` | `object` | nullable/อาจถูกละเว้น; เมื่อคะแนน unavailable จะคงเฉพาะ Safety provenance หากมี |
| `findings` | `array<PublicFinding>` | nullable/อาจถูกละเว้น; เมื่อคะแนน unavailable จะคงเฉพาะ `decision=safety_review` |
| `post_session_guidance` | `object` | nullable; unavailable มี `available=false` |
| `restore_summary` | `RestoreSummary` | nullable/อาจถูกละเว้นใน legacy report |
| `data_quality` | `PublicReportDataQuality` | nullable/อาจถูกละเว้น |
| `disclaimer` | `string` | nullable |

เมื่อ `score.available=false` ระบบจะ override ข้อความและคำแนะนำที่อิงคะแนน:
Session ที่ปิดแล้วใช้ `headline="ครั้งนี้ยังไม่มีคะแนน"` ส่วน Session ที่ยังไม่ปิดใช้
`headline="กำลังเตรียมผลสรุป"` และ
`post_session_guidance.score_derived_claims_suppressed=true` ห้าม client แสดง
ข้อความเชิงบวกจาก report เก่าหรือ field ภายใน อย่างไรก็ตาม Safety evidence
เป็นคนละชั้นกับคะแนน จึงยังคง `safety_review`, directional threshold,
ค่าต่ำสุด/สูงสุด และจำนวนรอบที่พบไว้เสมอ

### 9.1 Environment และ Safety provenance

`PublicEnvironmentMetric` ใช้ stable `key`, `status_key`, `decision` และค่ารวม
ของ Session โดย field ด้าน Safety ที่อาจปรากฏมีดังนี้:

| Field | Type | Nullable | ความหมาย |
|---|---|---|---|
| `safety_threshold` | `number` | nullable | เกณฑ์ด้านเดียว เช่น CO₂; รุ่น legacy นับเหตุเมื่อค่า `>=` เกณฑ์ |
| `critical_below` | `number` | nullable | ขอบล่างแบบ strict; เป็นเหตุเมื่อค่าจริง `< critical_below` |
| `critical_above` | `number` | nullable | ขอบบนแบบ strict; เป็นเหตุเมื่อค่าจริง `> critical_above` |
| `minimum` | `number` | nullable | ค่าต่ำสุดที่บันทึกใน Session |
| `maximum` | `number` | nullable | ค่าสูงสุดที่บันทึกใน Session |
| `safety_excursion_observed` | `boolean` | nullable | พบค่าแตะ/ข้ามเกณฑ์ Safety อย่างน้อยหนึ่งรอบ |
| `safety_excursion_sample_count` | `integer` | nullable | จำนวนรอบที่เข้าเงื่อนไข |
| `safety_excursion_sample_pct` | `number` | nullable | สัดส่วนรอบที่เข้าเงื่อนไข 0–100 |

`environment_assessment.safety_excursions[]` ใช้ DTO
`PublicSafetyExcursion` ซึ่งประกอบด้วย `key`, `label`, `threshold`,
`critical_below`, `critical_above`, `minimum`, `maximum`, `sample_count` และ
`sample_pct` ขอบล่าง/บนเป็น directional และ nullable; client ห้ามเดาขอบที่ไม่มี

`PublicFinding` ที่ `decision="safety_review"` คง `key`, `metric_key`,
`severity`, `decision`, ขอบ/ค่าที่พบ และจำนวนรอบเดียวกัน ข้อความ
`title/detail/action` เป็น Product copy ที่ Server สร้างใหม่ ไม่ใช่ข้อความดิบ
จาก report รุ่นเก่า

### 9.2 Continuity accounting และเวลาที่เข้าคะแนน

Detail endpoint เผยแพร่บัญชีเวลาที่ผ่าน positive allowlist ที่
`report.sleep.classification_accounting` เพื่อให้ App อธิบายได้ว่าทุกวินาที
ของ Session อยู่ที่ใด โดยไม่ต้องอ่าน Raw Timeline หรือคำนวณคะแนนซ้ำ

| Field | Type | ความหมาย |
|---|---|---|
| `direct_confirmed_s` | `number >= 0` | เวลาที่ estimator ยืนยัน State จากหลักฐานของ epoch นั้นโดยตรง |
| `continuity_carried_forward_s` | `number >= 0` | เวลาที่คง State ก่อนหน้าขณะ State ผู้ท้าชิงยังไม่ชัด |
| `provisional_hold_s` | `number >= 0` | Legacy compatibility; รุ่นปัจจุบันไม่หักเวลา provisional และนับรวมใน carry ที่เข้าคะแนน |
| `display_attributed_s` | `number >= 0` | เวลาที่ผูกกับ W/N1/N2/N3/REM สำหรับแสดง Timeline |
| `score_eligible_s` | `number >= 0` | เวลาที่ Server อนุญาตให้ใช้คำนวณคะแนน |
| `initial_wait_s` | `number >= 0` | Legacy compatibility; รุ่นปัจจุบันเริ่ม occupied Recording ด้วย W ทันที |
| `no_data_s` | `number >= 0` | Legacy compatibility/QA; รุ่นปัจจุบันคง State เดิมและเก็บการขาด HR/RR/BCG เป็น evidence-quality metadata |
| `off_bed_s` | `number >= 0` | ยืนยันว่าไม่มีผู้ใช้งานบนเตียง |
| `restart_display_hold_s` | `number >= 0` | Legacy compatibility; รุ่นปัจจุบันคง State ล่าสุดหลัง service restart แบบ low-confidence และเข้าคะแนน แต่ไม่เข้า Personal Baseline |
| `sensor_gap_s` | `number >= 0` | ช่องว่าง acquisition หรือเศษท้ายที่ไม่ครบ epoch |
| `excluded_from_score_s` | `number >= 0` | เวลาบันทึกทั้งหมดที่ไม่มีสิทธิ์เข้าคะแนน |
| `arithmetic_invariant` | `object` | `left_s`, `right_s`, `delta_s`, `holds` สำหรับตรวจว่ายอดเวลาครบ |

`provisional_hold_s`, `no_data_s`, `restart_display_hold_s` และ `sensor_gap_s`
คงไว้เพื่ออ่านรายงานรุ่นเก่า/QA เท่านั้น ใน report รุ่นปัจจุบัน เวลาที่ occupied
แต่หลักฐานก้ำกึ่ง ขาด ไม่สด หรืออยู่ระหว่าง rebuild หลัง restart เป็นส่วนย่อยของ
`continuity_carried_forward_s` และเข้าคะแนน จึงห้ามนำ field compatibility เหล่านี้
มาบวกซ้ำ สมการบัญชีหลักของรุ่นปัจจุบันคือ:

```text
direct_confirmed_s + continuity_carried_forward_s + off_bed_s = recording_s
score_eligible_s = recording_s - off_bed_s
```

`score_eligible_s` หมายถึงเวลาที่ผูกกับ W/N1/N2/N3/REM โดยตรง ไม่ได้หมายความ
ว่า OFF BED ไม่มีผลต่อคะแนน: Sleep Score ใช้ OFF BED หลัง sleep onset ประกอบ
continuity และ Recovery Score ใช้ presence/bed exits ประกอบ rest continuity

`report.sleep.actual_scored_s` เท่ากับ `classification_accounting.score_eligible_s`
ใน report รุ่นปัจจุบัน ส่วน `report.stages[]` ส่งทั้งค่าที่ใช้แสดงและค่าที่ใช้
คิดคะแนนแยกกัน:

API ส่ง Coverage สองความหมายแยกกันทั้งใน `report.data_quality.coverage`
และ `report.quality.data_coverage`: `state_attribution_pct` คือสัดส่วนเวลาที่มี
W/N1/N2/N3/REM (รวม continuity carry) ส่วน `physiological_evidence_pct` คือ
สัดส่วนเวลาที่มี HR/RR คู่จริงจาก BCG ที่ใช้ได้ โดย OFF BED, synthetic gap และ
แถวที่ `bcg_analysis_valid=false` จะไม่ถูกนับเป็นหลักฐานสรีรวิทยา Client ต้องไม่
ใช้ State coverage แทน Sensor evidence coverage

| Field | Type | ใช้สำหรับ |
|---|---|---|
| `duration_s`, `pct_scored`, `pct_sleep` | `number` | การแสดงสัดส่วน State ที่ผูกกับ Timeline |
| `score_eligible_samples` | `integer >= 0` | จำนวน epoch ของ State นี้ที่มีสิทธิ์เข้าคะแนน |
| `score_eligible_duration_s` | `number >= 0` | เวลาของ State นี้ที่มีสิทธิ์เข้าคะแนน |
| `pct_score_eligible` | `number 0..100` | สัดส่วน State จากเวลาที่มีสิทธิ์เข้าคะแนนทั้งหมด |
| `pct_score_eligible_sleep` | `number 0..100` หรือ `null` | สัดส่วน N1/N2/N3/REM จากเวลาหลับที่มีสิทธิ์เข้าคะแนน |

Client ต้องใช้ค่าชุด `score_eligible_*` เมื่อต้องอธิบายฐานของคะแนน และใช้
`duration_s`/`pct_scored` เมื่อต้องแสดง Timeline เท่านั้น `WAIT` ใช้เฉพาะก่อน
Recording, `NO DATA` เป็น QA/legacy label ไม่ใช่ State, และ `OFF BED` เป็นข้อยกเว้น
เดียวที่ไม่เข้า Stage ratio แต่ยังมีผลต่อ continuity/presence ของคะแนน ห้ามสร้าง
bucket `Unclassified`; provisional/missing/stale/
restart carry ต้องยังแสดง State ก่อนหน้าและเข้าคะแนน แต่ต้องมี low-confidence และ
`excluded_from_personal_baseline=true`

`report.quality` เป็น allowlist ของ application fields เช่น
`available`, `score`, `score_title`, `score_scope`, `validation_status`,
`clinical_validated`, `quality_type`, `session_character`, `sleep_detected`,
`level`, `estimated_sleep_s`, `actual_scored_s`, `wake_s`,
`wake_pct_recorded`, `sleep_efficiency_pct`, `awakenings`, `wake_entries`,
`deep_pct`, `rem_pct`, `stage_pct_of_sleep`, `rest_mode`, `duration_target`,
`physiology`, `body_response`, `environment_support`, `data_coverage`,
`cycles`, `component_points`, `component_max_points`,
`effective_component_points`, `imputed_component_points`, `component_order`,
`score_confidence`, `scored_max_points`,
`score_normalized_for_available_components`,
`missing_component_neutral_factor`, `safety_review_required`,
`review_required`, `formula_version`, `version`, `outcome_interpretation`,
`disclaimer` และ field ที่อนุมัติใน response model รุ่นนั้น

ห้ามพึ่งพา field ที่ไม่อยู่ใน allowlist เช่น `engineering_shadow_score`,
`score_unrounded`, `release_requirements`, `samples`, `raw_samples`,
`bcg_base64`, `answers`, `profile`, `access_token`, `refresh_token` หรือ
`wellness_context`

เมื่อ `available=true`, `effective_component_points` คือแต้มที่เข้าสูตรจริง,
`imputed_component_points` ระบุเฉพาะ optional component ที่ใช้ค่า neutral 75%,
`scored_max_points` ต้องเป็น 100 และ
`score_normalized_for_available_components=false` Client ห้ามรวมคะแนนใหม่เอง
เมื่อ `available=false` Server ไม่เผยแพร่ component points ที่อาจใช้ย้อนสร้าง
engineering shadow score

`duration_target` อาจมี `score_factor` และ `score_curve_exponent` เพื่ออธิบาย
เส้นโค้งเวลา Nap ส่วน `environment_support` แยก `channel_coverage_pct`,
`temporal_coverage_pct` และ `evidence_coverage_pct`; การมีครบทุกชื่อ Sensor
ไม่ได้แปลว่ามีหลักฐานเต็ม Session

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
      "target": {
        "key": "overnight_7h",
        "label": "Overnight Recovery · 7 ชั่วโมง",
        "seconds": 25200,
        "minutes": 420,
        "recommended_range_minutes": [420, 540],
        "completion_pct": 100,
        "protocol_status": {
          "available": true,
          "canonical_mode": "sleep",
          "observed_seconds": 25200,
          "minimum_seconds": 18000,
          "recommended_range_seconds": [25200, 32400],
          "within_operational_window": true,
          "within_recommended_range": true,
          "status": "recommended",
          "review_required": false,
          "score_releasable": true,
          "minimum_score_seconds": 18000,
          "target": {
            "available": true,
            "valid": true,
            "group": "sleep",
            "key": "overnight_7h",
            "label": "Overnight Recovery · 7 ชั่วโมง",
            "seconds": 25200,
            "minutes": 420,
            "source": "persisted",
            "review_required": false,
            "supported_seconds": [25200]
          }
        }
      },
      "review_required": false,
      "protocol_review_required": false,
      "validation_status": "mode_confirmed",
      "conflicts": []
    },
    "score": {
      "type": "sleep_score",
      "title": "Sleep Score",
      "value": 76,
      "available": true,
      "level": "ดี",
      "formula_version": "zeep-sleep-score-v2.1-minimum-only-neutral-25-35-20-10-10",
      "quality_model_version": "zeep-rest-quality-v8.10-minimum-only-score-release",
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
        "formula_version": "zeep-sleep-score-v2.1-minimum-only-neutral-25-35-20-10-10",
        "copied_without_recalculation": true
      },
      "status": {
        "key": "sleep_restore_good",
        "label": "ภาพรวมการนอนคืนนี้ดี",
        "min_score": 70,
        "max_score": 84,
        "meaning": "เวลา ความต่อเนื่อง และรูปแบบการนอนที่ประเมินได้อยู่ในระดับดี",
        "version": "zeep-restore-action-bands-v1.1-observational-copy"
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
          "label": "ใกล้รูปแบบที่พบเป็นประจำของคุณ",
          "current_score": 76,
          "baseline_median": 75,
          "delta_points": 1,
          "typical_range": [71, 80],
          "mode_specific": true
        },
        "affects_source_score": false,
        "population_prior_is_cold_start_only": true,
        "must_not_mix_sleep_and_nap_sessions": true,
        "baseline_policy_version": "zeep-personal-behaviour-baseline-v1.3-bounded-partitioned-finite-circular-time",
        "score_formula_version": "zeep-sleep-score-v2.1-minimum-only-neutral-25-35-20-10-10",
        "target_specific": true,
        "target_key": "overnight_7h"
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
        "whole_day_readiness_trend": false,
        "baseline_policy_version": "zeep-personal-behaviour-baseline-v1.3-bounded-partitioned-finite-circular-time",
        "score_formula_version": "zeep-sleep-score-v2.1-minimum-only-neutral-25-35-20-10-10",
        "target_specific": true,
        "target_key": "overnight_7h"
      },
      "recommendation": {
        "primary": "รักษารูปแบบที่ได้ผลและติดตามแนวโน้มจากหลายคืน",
        "source_driver_key": null,
        "version": "zeep-restore-recommendation-v1.1-observational-copy",
        "one_action_only": true,
        "automatic_actuation": false,
        "medical_advice": false
      },
      "confidence": {
        "level": "high",
        "label": "ข้อมูลชัดเจน",
        "session_coverage_pct": 96.2,
        "paired_hr_rr_coverage_pct": 94,
        "changes_source_score": false,
        "admin_qa_context": true
      },
      "subjective_outcome": {
        "status": "not_measured",
        "label": "ยังไม่ได้บันทึกความรู้สึกหลังพัก",
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
      "coverage": {
        "recording_pct": 100,
        "bcg_pct": 95,
        "points": 0,
        "max_points": 0,
        "score_component": false
      },
      "confidence": {
        "level": "high",
        "session_coverage_pct": 96.2,
        "paired_hr_rr_coverage_pct": 94
      },
      "confidence_distribution": null,
      "coverage_contributes_points": false,
      "coverage_points": 0,
      "coverage_max_points": 0,
      "coverage_can_hide_score": false
    },
    "versions": {
      "result_contract": "zeep.session-result.v1",
      "session_report": "zeep-session-report-v10.12-minimum-only-score-release",
      "score_formula": "zeep-sleep-score-v2.1-minimum-only-neutral-25-35-20-10-10",
      "score_quality_model": "zeep-rest-quality-v8.10-minimum-only-score-release",
      "restore_summary": "zeep-restore-summary-v1.0",
      "product_language": "zeep-product-language-v1.1"
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
    "sample_count": 180,
    "mode": {
      "key": "nap_recovery",
      "label": "Nap & Refresh",
      "requested": "nap_recovery",
      "resolved": "nap_recovery",
      "sleep_required": false,
      "target": {
        "key": "nap_30",
        "label": "30 นาที",
        "seconds": 1800,
        "minutes": 30,
        "recommended_range_minutes": [25, 35],
        "completion_pct": 100,
        "protocol_status": {}
      },
      "review_required": false,
      "protocol_review_required": false,
      "validation_status": "mode_confirmed",
      "conflicts": []
    },
    "score": {
      "type": "recovery_score",
      "title": "Recovery Score",
      "value": 74,
      "available": true,
      "level": "ช่วงพักนี้เป็นไปได้ดี",
      "formula_version": "zeep-recovery-score-v3.1-minimum-only-neutral-25-35-30-10",
      "quality_model_version": "zeep-rest-quality-v8.10-minimum-only-score-release",
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
        "formula_version": "zeep-recovery-score-v3.1-minimum-only-neutral-25-35-30-10",
        "copied_without_recalculation": true
      },
      "status": {
        "key": "rest_good",
        "label": "ช่วงพักนี้เป็นไปได้ดี",
        "min_score": 70,
        "max_score": 84,
        "meaning": "ร่างกายได้หยุดพักอย่างต่อเนื่องในระดับดี",
        "version": "zeep-restore-action-bands-v1.1-observational-copy"
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
        "must_not_mix_sleep_and_nap_sessions": true,
        "baseline_policy_version": "zeep-personal-behaviour-baseline-v1.3-bounded-partitioned-finite-circular-time",
        "score_formula_version": "zeep-recovery-score-v3.1-minimum-only-neutral-25-35-30-10",
        "target_specific": true,
        "target_key": "nap_30"
      },
      "trend": {
        "available": true,
        "unit": "sessions",
        "windows": {
          "7": {"session_count": 7, "average": 72.4, "latest": 74}
        },
        "mode_specific": true,
        "whole_day_readiness_trend": false,
        "baseline_policy_version": "zeep-personal-behaviour-baseline-v1.3-bounded-partitioned-finite-circular-time",
        "score_formula_version": "zeep-recovery-score-v3.1-minimum-only-neutral-25-35-30-10",
        "target_specific": true,
        "target_key": "nap_30"
      },
      "recommendation": {
        "primary": "รักษารูปแบบการพักที่ได้ผลและบันทึกความรู้สึกหลังพัก",
        "source_driver_key": null,
        "version": "zeep-restore-recommendation-v1.1-observational-copy",
        "one_action_only": true,
        "automatic_actuation": false,
        "medical_advice": false
      },
      "confidence": {
        "level": "medium",
        "label": "ข้อมูลเพียงพอ",
        "session_coverage_pct": 91.5,
        "paired_hr_rr_coverage_pct": 88.2,
        "changes_source_score": false,
        "admin_qa_context": true
      },
      "subjective_outcome": {
        "status": "measured",
        "label": "บันทึกความรู้สึกก่อน–หลังการพักแล้ว",
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
      "label": "ข้อมูลเพียงพอ",
      "coverage": {
        "recording_pct": 91.5,
        "bcg_pct": 88.2,
        "points": 0,
        "max_points": 0,
        "score_component": false
      },
      "confidence": {
        "level": "medium",
        "label": "ข้อมูลเพียงพอ",
        "session_coverage_pct": 91.5,
        "paired_hr_rr_coverage_pct": 88.2
      },
      "confidence_distribution": null,
      "coverage_contributes_points": false,
      "coverage_points": 0,
      "coverage_max_points": 0,
      "coverage_can_hide_score": false
    },
    "versions": {
      "result_contract": "zeep.session-result.v1",
      "session_report": "zeep-session-report-v10.12-minimum-only-score-release",
      "score_formula": "zeep-recovery-score-v3.1-minimum-only-neutral-25-35-30-10",
      "score_quality_model": "zeep-rest-quality-v8.10-minimum-only-score-release",
      "restore_summary": "zeep-restore-summary-v1.0",
      "product_language": "zeep-product-language-v1.1"
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
      "label": "กำลังระบุรูปแบบการพัก",
      "requested": "unknown",
      "resolved": null,
      "sleep_required": false,
      "target": null,
      "review_required": true,
      "protocol_review_required": false,
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
      "reason": "กำลังระบุรูปแบบการพัก จึงยังไม่เลือกชนิดคะแนน",
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
        "label": "ครั้งนี้ยังไม่มีคะแนน",
        "min_score": null,
        "max_score": null,
        "meaning": "เลือกรูปแบบการพักเพื่อให้ ZEEP แสดงผลได้เหมาะสม",
        "version": "zeep-restore-action-bands-v1.1-observational-copy"
      },
      "session_scope": {
        "mode": "unknown",
        "label": "ผลการพักครั้งนี้",
        "question": "เลือกรูปแบบการพักเพื่อดูผลสรุปที่เหมาะสม",
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
        "must_not_mix_sleep_and_nap_sessions": true,
        "baseline_policy_version": null,
        "score_formula_version": null,
        "target_specific": false,
        "target_key": null
      },
      "trend": {
        "available": false,
        "reason": "คะแนนหลักยังไม่พร้อม",
        "windows": {},
        "baseline_policy_version": null,
        "score_formula_version": null,
        "target_specific": false,
        "target_key": null
      },
      "recommendation": {
        "primary": "ระบุรูปแบบการพักและตรวจความพร้อมของ Sensor ก่อนครั้งถัดไป",
        "source_driver_key": null,
        "version": "zeep-restore-recommendation-v1.1-observational-copy",
        "one_action_only": true,
        "automatic_actuation": false,
        "medical_advice": false
      },
      "confidence": {
        "level": "unknown",
        "label": "ข้อมูลยังไม่พอสรุป",
        "session_coverage_pct": null,
        "paired_hr_rr_coverage_pct": null,
        "changes_source_score": false,
        "admin_qa_context": true
      },
      "subjective_outcome": {
        "status": "not_measured",
        "label": "ยังไม่ได้บันทึกความรู้สึกหลังพัก",
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
      "coverage": {
        "points": 0,
        "max_points": 0,
        "score_component": false
      },
      "confidence": {},
      "confidence_distribution": null,
      "coverage_contributes_points": false,
      "coverage_points": 0,
      "coverage_max_points": 0,
      "coverage_can_hide_score": false
    },
    "versions": {
      "result_contract": "zeep.session-result.v1",
      "session_report": null,
      "score_formula": null,
      "score_quality_model": null,
      "restore_summary": "zeep-restore-summary-v1.0",
      "product_language": "zeep-product-language-v1.1"
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

### 10.4 Presentation และ Development views

`usage_session_presentation` เป็น DTO สำหรับวาดหน้าผลโดยตรง โดยมี
`primary_result` เพียงตำแหน่งเดียว และจัดกลุ่มข้อมูลเป็น `overview_metrics`,
`positive_drivers`, `attention_drivers`, `personal_baseline`, `trend`,
`subjective_outcome`, `environment`, `vital_signals` และ `recommendation`
ตามลำดับที่ผู้ใช้ควรอ่าน สำหรับ Nap ค่า `sleep_stages` ต้องเป็น `null` ส่วน
Overnight จึงจะแสดง W/N1/N2/N3/REM ได้ สำหรับ Nap ใช้ `rest_profile`
สามกลุ่ม ได้แก่ `awake_rest`, `drowsy` และ `estimated_sleep` โดยไม่บังคับ
ว่าผู้ใช้ต้องหลับ และ Driver ไม่มี action แยกแข่งกับ `recommendation`

`usage_session_development` ฝัง `user_summary` ชุดเดียวกันและเพิ่มเฉพาะข้อมูล
Admin ได้แก่ `score_release`, `data_quality`, `score_components`,
`classification_accounting`, `environment_assessment`, Version และ
`review_flags` โดยต้องมี `raw_data_included=false` เสมอ

รายละเอียดลำดับหน้า ถ้อยคำ และเงื่อนไข Rerun ดูที่
[ZEEP Session Result Presentation v1](zeep-session-result-presentation-v1.md)

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
| Score/summary | `zeep-sleep-score-v2.1-minimum-only-neutral-25-35-20-10-10`, `zeep-recovery-score-v3.1-minimum-only-neutral-25-35-30-10`, `zeep-restore-summary-v1.0` |

การเพิ่ม optional field ที่ไม่เปลี่ยนความหมายเดิมเป็น backward-compatible ได้
แต่ client ต้อง ignore unknown fields และรองรับ optional/nullable field เสมอ
การ rename/remove field, เปลี่ยน enum semantics, เปลี่ยนหน่วย หรือเปลี่ยน
availability invariant ต้องออก contract/API version ใหม่พร้อม migration note

การคำนวณคะแนนย้อนหลังทำได้เฉพาะสูตรที่มี version และ Audit trail; raw sensor
record ต้อง immutable และ adapter นี้ต้องไม่ recalculate score (`score_recalculated_by_adapter=false`)
เมื่อเวลาของ Nap ต่างจาก Protocol คะแนนยังสะท้อนคุณภาพการพักจริงได้ แต่
`mode.protocol_review_required=true`, `mode.review_required=true` และ
`score.review_required=true`; แอปต้องแสดงบริบทเวลาแยกจากความหมายของคะแนน

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

- `sessions/restore_response_models.py`
- `sessions/usage_response_models.py`
- `sessions/presentation_response_models.py`
- `sessions/user_profile_response_models.py`
- `sessions/response_models.py` สำหรับ public re-export

FastAPI ผูก model เหล่านี้เป็น `response_model` ของ Usage Session ทั้งเจ็ด
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
- ทดสอบ `best_rest_window` ว่า strict, เริ่มได้จาก prior matching Session 1 ครั้ง,
  ไม่เผย source identity/timestamp และไม่หลุดเข้า AI context
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
- [ ] `best_rest_window` ไม่มี Session ID/exact source timestamp, ไม่ถูกส่งเข้า AI
      context และไม่มีผลต่อ Score, Sleep State หรือ automatic control
- [ ] UI อธิบาย `best_rest_window` เป็น observation ที่ต้องให้ผู้ใช้ยืนยัน
      ไม่ใช่ preference หรือ causal claim
- [ ] response และ log ไม่ถูก cache/shared หรือส่งต่อข้าม account
- [ ] เก็บ `request_id` ได้โดยไม่เก็บ payload สุขภาพทั้งก้อน
