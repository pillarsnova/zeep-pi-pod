# Contributing to ZEEP Pi 5

สถานะ: **มาตรฐานการพัฒนา v1 · Internal Pilot**

เอกสารนี้เป็นจุดเริ่มสำหรับการแก้โค้ด ทุกคนต้องอ่าน
[Team Onboarding](docs/onboarding/README.md),
[Software Architecture](docs/pi5-software-architecture.md) และเอกสารของ domain
ที่จะเปลี่ยนก่อนเริ่มงาน

## หลักการสำคัญ

1. หนึ่ง change มีหนึ่งความรับผิดชอบ: Refactor, behavior, formula, firmware และ
   data migration ต้องแยก review ได้
2. Refactor ต้องรักษา behavior และเพิ่ม characterization test ก่อนย้าย boundary
3. Raw Sensor/BCG เป็น immutable; Derived result ต้องมี version และ audit
4. ห้าม restart/deploy/flash ขณะมีผู้ใช้งานหรือ Session กำลังบันทึก
5. ZEEP v1 เป็น Wellness ไม่ใช่เครื่องมือวินิจฉัย

## โครงสร้างและ Dependency

- `app.py` เป็น legacy composition root และต้องลดลงเท่านั้น
- Feature service อยู่ตาม domain เช่น `sessions/`
- Hardware I/O อยู่ใน `hardware/`
- HTTP router ตรวจ Auth/RBAC/CSRF และแปลง request/response เท่านั้น
- Pure policy ห้ามเปิดไฟล์, database, network, Serial, MQTT, GPIO หรือ subprocess
  ตอน import
- Dependency ไหลจาก composition → service → adapter → pure contract; module ใน
  top-level domain packages ห้าม import `app.py`
- ห้ามสร้าง `hub.py`, `utils.py` หรือ `helpers.py` ขนาดใหญ่ที่รวมหลาย failure domain

## Python Standard

- Python 3.11+, PEP 8, Ruff line length 88
- โมดูลใหม่ใน top-level domain packages ไม่เกิน 500 บรรทัด
- Function/method ใหม่ไม่เกิน 90 บรรทัด และควรทำหน้าที่เดียว
- Public boundary, safety decision และ data contract ต้องมี type hints และ docstring
- ใช้ `dataclass`/Protocol หรือ typed model เมื่อช่วยทำ dependency ให้ชัด
- Inject clock, sleeper, transport, storage และ state port แทนการผูก global ใน
  logic ที่ต้องทดสอบ
- แยก domain error ออกจาก HTTP error; adapter ไม่ควรรู้จัก FastAPI
- ห้าม catch `Exception` แล้วเงียบ ต้องรักษา failure state และ log แบบไม่เปิดเผย PII
- เขียน comment เพื่ออธิบายเหตุผล/invariant ไม่ใช่ทวนสิ่งที่โค้ดทำ

ไฟล์ Legacy ที่ยังเกินขนาดไม่ใช่ข้อยกเว้นสำหรับโค้ดใหม่ ทุก extraction ต้องลด
เพดานใน `test_modular_architecture.py` เพื่อไม่ให้ complexity โตกลับ

## Hardware และ Concurrent Code

- Reader/adapter ต้องรับ config และ dependency จากภายนอก
- Loop ใหม่ต้องมี stop token และปิด Serial/MQTT/process ได้แบบ deterministic
- Timeout, reconnect, stale, ACK scope และ safe state ต้องเขียนเป็น contract
- ACK ที่ยืนยันเพียงการส่งคำสั่ง ห้ามนำเสนอว่าเป็น physical feedback
- Shared state ทุกจุดต้องใช้ lock เดิมหรือ encapsulated state port ที่ทดสอบ race ได้

## Test ก่อนส่ง Review

เริ่มด้วย risk-based gate และให้ [TESTING.md](TESTING.md) เป็นเจ้าของ trigger ของ
Focused, CI และ Full gate:

```bash
python quality_gate.py changed
git diff --check
```

ใช้ `python quality_gate.py full` เมื่อแก้ข้ามระบบ ผลไม่แน่นอน เปลี่ยน migration/
test infrastructure, CI ของ Git SHA นั้นใช้ไม่ได้ หรือก่อน Release/Code Freeze
งาน UI และ Evidence ต้องรัน gate เฉพาะที่ TESTING ระบุ ไม่รันทุกชุดซ้ำโดยไม่มีเหตุผล

Test ต้องใช้ temporary/synthetic data ผ่าน `testing_support.py` ห้ามอ่าน เขียน
หรือล้าง Production data รายละเอียดกลุ่มทดสอบอยู่ใน [TESTING.md](TESTING.md)

## Checklist ก่อน Commit/Push

- [ ] Working tree เริ่มจาก `origin/develop` ล่าสุดและไม่มี change ของคนอื่นปะปน
- [ ] ระบุ behavior ที่คงเดิมและ behavior ที่ตั้งใจเปลี่ยน
- [ ] ไม่มี secret, credential, PII, database, backup หรือ Raw export ใน Git
- [ ] Public API/state key และ backward compatibility มี test
- [ ] Formula/threshold/version เปลี่ยนเฉพาะใน change ที่ได้รับอนุมัติ
- [ ] Focused gate และ CI/Full gate ที่เข้าเงื่อนไขใน `TESTING.md` ผ่าน พร้อมรายงาน
      จำนวน test/skip จริง
- [ ] ระบุ Hardware smoke, migration, restart และ rollback ที่ยังต้องทำ
- [ ] อัปเดตเอกสาร source of truth ใน release เดียวกัน

ห้าม Push หรือ Deploy หาก reviewer ยังไม่สามารถอธิบาย ownership, failure behavior,
test evidence และผลกระทบต่อผู้ใช้งานได้ครบ
