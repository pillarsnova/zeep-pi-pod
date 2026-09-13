# ZEEP Pi API v1 — Usage Session Results

สถานะ: **Integration contract v1 · Internal Wellness API**

เจ้าของข้อมูล: ZEEP Platform + Pi Team
เส้นทางหลัก: `/api/v1/usage-sessions`

เอกสารชนิดข้อมูล, enum, nullable rule และตัวอย่าง canonical payload ฉบับเต็ม:
[ZEEP Usage Session API Schema Reference v1](zeep-api-schema-reference-v1.md)
โดย schema ที่เครื่องอ่านได้เผยแพร่ผ่าน `/openapi.json`

## TL;DR

API ชุดนี้ใช้ส่งผลสรุปจาก Pi ไปให้แอป ZEEP หรือระบบภายในอ่าน โดยไม่ส่ง
Raw BCG, Sensor Timeline หรือคำตอบ Profile ผู้ใช้

- Overnight Recovery ใช้ `sleep_score` / **Sleep Score**
- Nap & Refresh ใช้ `recovery_score` / **Recovery Score**
- `restore_summary` อธิบายคะแนนเดิม ไม่สร้างคะแนนที่สาม
- User เห็นเฉพาะ Session ของอีเมลตนเองโดยไม่รับชื่อผู้ใช้ใน path
- Admin ที่ Login แล้วเห็นหลายบัญชีและกรองด้วยอีเมลได้
- Session ที่ปิดแล้วถือว่า closed; read adapter ไม่คำนวณคะแนนใหม่ ส่วนคะแนน
  อาจปรับย้อนหลังได้เฉพาะแบบมีเวอร์ชันและ Audit trail โดย Raw ไม่เปลี่ยน

## Authentication และขอบเขต

| ผู้เรียก | วิธี Authentication | ขอบเขต |
|---|---|---|
| แอป/หน้า User | Cookie `zeep_auth` | เฉพาะ `principal.account_key` ของตนเอง |
| หน้า Admin | Cookie ผู้ดูแล | ทุกบัญชี; ใช้ `account_key`/`query` ได้ |

Usage API v1 **ปฏิเสธ `X-API-Token` รุ่นเดิมโดยตั้งใจ** เพราะเป็น credential
สิทธิ์กว้างที่ใช้กับระบบควบคุมและไม่เหมาะกับผลสุขภาพรายบุคคล รุ่นนี้รองรับเฉพาะ
บัญชี User/Admin ผ่าน Cookie เท่านั้น การเชื่อม Backend-to-Backend รุ่นถัดไปต้องใช้
OAuth/HMAC ที่มีอายุสั้นและผูกขอบเขตบัญชีหรือ Pod พร้อม immutable read audit
ห้ามฝัง service credential ใน Mobile app, JavaScript, URL/query string, Browser,
Tablet image หรือไฟล์ที่ส่งให้ลูกค้า

คำขอที่ไม่มีสิทธิ์อ่าน Session ของบุคคลอื่นจะได้ `404` เช่นเดียวกับ ID
ที่ไม่มีอยู่ เพื่อไม่เปิดเผยว่า Session ของบุคคลอื่นมีอยู่หรือไม่

### รูปแบบเชื่อมต่อที่แนะนำ

Mobile app ไม่ควรต่อ Pi โดยตรงด้วย credential ระดับผู้ดูแล ใน Usage API v1
ผู้ใช้และผู้ดูแลอ่านผลผ่าน Browser Session ที่ Login แล้วเท่านั้น การเชื่อม
ZEEP Backend แบบอัตโนมัติยังไม่เปิดจนกว่าจะมี account-scoped/short-lived
credential พร้อม read audit; ห้ามนำ `X-API-Token` เดิมมาใช้ทดแทน

การเปลี่ยนแปลงรุ่นนี้เพิ่ม **Pull API ภายใน Pod** และไม่ได้ขยาย payload ของ
legacy `POST /v1/sleep-sessions/ingest` ไปยัง `api.zeep.world`; หากทีมต้องการ
ให้ Backend รับ field ชุดใหม่ผ่าน Push ต้องอนุมัติ schema, data minimisation
และ retention ของปลายทางร่วมกันก่อน

## Response envelope

ทุก endpoint ใหม่ใช้ envelope เดียวกัน:

```json
{
  "schema": "zeep.api.response",
  "api_version": "1.0",
  "kind": "usage_session_summary",
  "generated_at": "2026-09-11T03:00:00.000+00:00",
  "request_id": "96be6449-b4d9-4ee7-b803-c5b269dbd533",
  "data": {}
}
```

ทีมแอปควรบันทึก `request_id` เมื่อรายงานปัญหา และตรวจ
`data.contract_version` ก่อนอ่าน field เฉพาะรุ่น

ทุก response สำเร็จส่ง `Cache-Control: private, no-store` เพื่อไม่ให้ Browser,
proxy หรือ shared cache เก็บผลสุขภาพของ Session

## 1. รายการประวัติการใช้งาน

`GET /api/v1/usage-sessions`

Query parameters:

| Field | รูปแบบ | Default | หมายเหตุ |
|---|---|---|---|
| `date_from` | `YYYY-MM-DD` | ไม่มี | วันที่ท้องถิ่นของตู้; inclusive |
| `date_to` | `YYYY-MM-DD` | ไม่มี | วันที่ท้องถิ่นของตู้; inclusive |
| `time_from` | `HH:MM` | `00:00` | เวลาเริ่มท้องถิ่น |
| `time_to` | `HH:MM` | `23:59` | นาทีสิ้นสุดเป็น inclusive |
| `limit` | `1..200` | `50` | จำนวนรายการต่อหน้า |
| `offset` | จำนวนเต็ม `>=0` | `0` | ตำแหน่งเริ่มต้น |
| `account_key` | อีเมลเต็ม | ไม่มี | Admin ที่ Login แล้วเท่านั้น |
| `query` | อีเมล/ชื่อแสดง | ไม่มี | Admin ที่ Login แล้วเท่านั้น |

ถ้าไม่ส่งวันที่ ระบบคืน Session ตั้งแต่ Product history cutover เป็นต้นมา
โดยเรียง Session ล่าสุดก่อน วันที่ของ Overnight ยึดวันท้องถิ่นที่ Session จบ
เพื่อให้ผลอยู่ในเช้าที่ผู้ใช้เปิดดู การส่ง `time_from`/`time_to` โดยไม่ระบุ
`date_from` หรือ `date_to` จะได้ `422`; ช่วงวันที่หนึ่งคำขอจำกัดไม่เกิน 366 วัน

```json
{
  "data": {
    "contract_version": "zeep.usage-session.v1",
    "history_name": "usage_history",
    "items": [
      {
        "session_id": "s-20260911-abc123",
        "user": {
          "email": "tester@example.com",
          "display_name": "Tester",
          "canonical_identifier": "tester@example.com",
          "identity_type": "email"
        },
        "mode": {
          "key": "sleep",
          "label": "Overnight Recovery",
          "target": {"seconds": 25200, "minutes": 420.0}
        },
        "score": {
          "type": "sleep_score",
          "title": "Sleep Score",
          "value": 82,
          "available": true,
          "formula_version": "zeep-sleep-score-v..."
        },
        "restore_summary": {
          "name": "ZEEP Restore Summary",
          "creates_independent_score": false,
          "whole_day_readiness_available": false
        },
        "session_closed": true,
        "score_revision_policy": "versioned_recalculation_with_audit"
      }
    ],
    "pagination": {
      "limit": 50,
      "offset": 0,
      "returned": 1,
      "total": 1,
      "has_more": false
    }
  }
}
```

หน้าถัดไปใช้ `offset + returned` เมื่อ `has_more=true` ห้ามเดาจากจำนวน
รายการอย่างเดียว เพราะจำนวนจริงอาจเปลี่ยนเมื่อ Session ใหม่ปิด

## 2. ผลสรุป Session

`GET /api/v1/usage-sessions/{session_id}/summary`

เหมาะกับหน้าแรกของผลลัพธ์บนแอป ประกอบด้วย:

- `mode` และเป้าหมาย 30/90 นาทีหรือ Overnight
- `score.type/title/value/formula_version`
- `restore_summary` พร้อมสถานะ ตัวขับผล และคำแนะนำหนึ่งข้อ
- `data_quality.coverage/confidence`
- `versions` สำหรับ Audit
- `result_provenance` เพื่อแยก Persisted result กับ Display-only recompute

`whole_day_readiness_available=false` หมายความว่าผลนี้อธิบายเฉพาะการฟื้นตัว
จาก Session ใน ZEEP ไม่ได้รวม Training load, กิจกรรมทั้งวัน หรือวินิจฉัยความพร้อม
ในการขับรถ/แข่งขัน

## 3. รายงาน Session แบบละเอียดแต่ไม่มี Raw

`GET /api/v1/usage-sessions/{session_id}`

เพิ่ม `report`, เวอร์ชัน Sleep estimator และนโยบาย Sleep State สำหรับหน้ารายละเอียด
ของแอป แต่ยังไม่คืน:

- `samples`
- Raw BCG/packet/base64
- Sensor Timeline รายจุด
- Profile สุขภาพหรือคำตอบแบบสอบถาม
- Access/refresh token
- ค่า Engineering ภายใน เช่น `engineering_shadow_score`, `score_unrounded`
  และ release gate ที่ไม่อยู่ใน Public Quality DTO

ผลรุ่น Continuity ส่งบัญชีเวลาที่ `report.sleep.classification_accounting`
เพื่อแยกเวลายืนยันตรง, เวลาคง State ก่อนหน้า, provisional, WAIT, NO DATA,
OFF BED, restart hold, sensor gap และ `score_eligible_s` พร้อม
`arithmetic_invariant` ส่วน `report.stages[]` มี
`score_eligible_samples`, `score_eligible_duration_s`,
`pct_score_eligible` และ `pct_score_eligible_sleep` แยกจากค่าที่ใช้แสดง
Timeline โดยชัดเจน App ต้องใช้ค่าชุดนี้จาก Server และห้ามคำนวณฐานคะแนนใหม่เอง
รายละเอียด field และสมการดูหัวข้อ 9.1 ใน
[Usage Session Schema Reference](zeep-api-schema-reference-v1.md)

`report.quality` เป็น Positive allowlist: ระบบคืนเฉพาะ field ที่อนุมัติสำหรับ
Application contract เท่านั้น ไม่ได้คัดออกเพียงตามชื่อ field ต้องห้าม ดังนั้น field
ใหม่จาก Model จะไม่ออก API จนกว่าจะผ่านการทบทวนและเพิ่มใน Public Quality DTO
โดยตั้งใจ แม้ `score.available=false` ระบบก็จะไม่คืนคะแนนเงาเพื่อใช้แทนคะแนนจริง
ค่า `report.quality.available/score/score_title/formula_version/validation_status`,
`clinical_validated` และ `level` ถูกบังคับให้ตรงกับ `data.score` ซึ่งเป็นผลที่
อนุมัติให้เผยแพร่เสมอ เพื่อตัดกรณีรายงานเก่ามีค่าซ้ำหรือค่าภายในไม่ตรงกับคะแนนหลัก

ชนิดคะแนนยึด `Session.rest_mode` และผล Quality ที่ผ่าน release policy ไม่ยอมให้
`session_report.rest_mode` รุ่นเก่าสลับ Overnight เป็น Nap หรือกลับกัน หาก Metadata
เหล่านี้ขัดกัน ระบบคงโหมดหลักไว้เพื่อ Audit แต่ส่ง `score.available=false`,
`mode.review_required=true` และ `mode.validation_status=mode_metadata_conflict`
พร้อมระงับข้อความเชิงบวก/คำแนะนำที่อิงคะแนน จนกว่าทีมจะตรวจแก้ข้อมูลต้นทาง

Raw research data ยังอยู่ใน route Admin เดิมและไม่ใช่ Application contract นี้

## Score และ Restore Summary

```json
{
  "score": {
    "type": "recovery_score",
    "title": "Recovery Score",
    "value": 78,
    "available": true,
    "formula_version": "zeep-recovery-score-v...",
    "clinical_validated": false
  },
  "restore_summary": {
    "version": "zeep-restore-summary-v...",
    "creates_independent_score": false,
    "source_score": {"type": "recovery_score", "value": 78},
    "status": {"key": "rest_good", "label": "ช่วงพักนี้เป็นไปได้ดี"},
    "session_scope": {
      "mode": "nap_recovery",
      "whole_day_readiness": false
    },
    "drivers": {"positive": [], "attention": []},
    "personal_baseline": {},
    "trend": {},
    "recommendation": {},
    "subjective_outcome": {"status": "not_measured"},
    "whole_day_readiness_available": false
  }
}
```

ห้ามแสดง `freshness_delta` หรือ `activity_readiness` จาก Sensor หากไม่มี
แบบประเมินก่อน–หลังจริง ค่าในกรณีนี้ต้องเป็น `not_measured`

## Finalization และ Audit

- API รายการนี้คืนเฉพาะ Session ที่จบและมี Timeline อย่างน้อยหนึ่งรายการ
- ค่า Score มาจาก Final Summary ที่บันทึกไว้ ไม่ถูกคำนวณใน API adapter
- Raw Sensor คงเดิม แต่เจ้าของระบบอาจอนุมัติการคำนวณคะแนนย้อนหลังด้วย
  Model version ใหม่ โดยต้องเก็บค่าเดิมและ Audit trail
- หากหน้า Legacy ต้องสร้างรายงานรุ่นใหม่เพื่อแสดงผลเท่านั้น จะมี
  `result_provenance.display_recomputed=true` และ
  `persisted_record_unchanged=true`
- การคำนวณย้อนหลังต้องผ่าน workflow ที่มี Audit trail และ formula version
  แยกจากการอ่าน API นี้

## Error contract

FastAPI error ใช้โครงมาตรฐาน `{"detail": ...}`:

| HTTP | ความหมาย |
|---:|---|
| `401` | ยังไม่ได้ Login หรือ Browser Session หมดอายุ |
| `403` | User พยายามใช้ตัวกรอง Admin หรือใช้ `X-API-Token` รุ่นเดิม |
| `404` | ไม่พบ Session ในขอบเขตที่มีสิทธิ์ |
| `422` | วันที่ เวลา limit หรือ offset ไม่ถูกต้อง |

## Legacy compatibility

Route ต่อไปนี้ยังทำงานเพื่อรองรับ Tablet/เครื่องมือรุ่นเดิม:

- `/api/history/{username}`
- `/api/history/{username}/{session_id}`
- `/api/admin/history`

โค้ดใหม่ไม่ควรเริ่มผูกกับ path ที่มี username ให้ใช้
`/api/v1/usage-sessions` แทน คำว่า “ประวัติการนอน” ใน UI เปลี่ยนเป็น
“ประวัติการใช้งาน” เพราะรายการเดียวกันรองรับทั้ง Overnight Recovery และ
Nap & Refresh

## Verification สำหรับทีม Integration

1. Login เป็น User A แล้วเรียกรายการ ต้องไม่พบ User B
2. ใช้ Session ID ของ User B ผ่าน User A ต้องได้ `404`
3. Login Admin จึงใช้ `account_key`/`query` ได้; `X-API-Token` ต้องได้ `403`
4. ตรวจว่า response ไม่มี `samples`, `bcg_base64`, token หรือ Profile answers
   รวมทั้งรูปแบบ camelCase เช่น `rawSamples`, `bcgBase64`, `accessToken`,
   `xApiKey`, `clientApiKey` หรือ `privateKey`
5. Overnight ต้องเป็น `sleep_score`; Nap ต้องเป็น `recovery_score`
6. `restore_summary.creates_independent_score` ต้องเป็น `false`
7. ใช้ `formula_version`, `session_report` และ `request_id` ใน Bug report
