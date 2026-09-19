# ZEEP หูอัจฉริยะ — Acoustic Intelligence DSP Plan

สถานะ: **P1 SHADOW PIPELINE IMPLEMENTED · FIRMWARE CANDIDATE NOT INSTALLED**

ขอบเขต: จำแนกลักษณะและบริบทของเสียงเพื่อช่วยทีมดูแล Pod

ข้อบังคับ: `clinical_validated=false` · `automatic_actuation=false` ·
ไม่กระทบ Sleep State, Sleep Score หรือ Recovery Score ในระยะแรก

ปรับปรุงล่าสุด: 17 กันยายน 2026

## คำแสดงผลใน Monitor — ปรับปรุง 20 กันยายน 2026

ชื่อด้านล่างใช้ร่วมกันในผลสดและประวัติเสียงจาก API ส่วนรหัสข้อมูลเดิมคงไว้
การปรับข้อความรอบนี้ไม่เปลี่ยนสูตรตรวจจับ Firmware คะแนน หรือข้อมูลดิบ
สถานะการติดตั้งในส่วนแผนเดิมด้านล่างเป็นบันทึก ณ 17 กันยายน ไม่ใช่การรับรอง
Firmware ปัจจุบัน ต้องตรวจ version จากอุปกรณ์ที่เชื่อมต่อ

| รหัส | ข้อความแสดงผล | คำอธิบายสั้น |
| --- | --- | --- |
| `quiet` | ค่อนข้างเงียบ | เสียงเบาในช่วงที่วัด ไม่ได้หมายถึงไม่มีเสียง |
| `steady_equipment_like` | เสียงต่อเนื่องคล้ายอุปกรณ์ | เสียงต่อเนื่อง เช่น พัดลมหรือแอร์ |
| `speech_like` | คล้ายเสียงพูด | จังหวะเสียงคล้ายคำพูด ไม่ถอดคำหรือระบุผู้พูด |
| `snore_like` | คล้ายเสียงกรน | จังหวะเสียงคล้ายการกรน ไม่ใช่ผลวินิจฉัย |
| `impact_like` | คล้ายเสียงกระแทก | เสียงฉับพลัน เช่น ประตูหรือวัตถุกระทบ |

เมื่อข้อมูลไม่พอให้ใช้ “ยังจำแนกเสียงไม่ได้” ไม่แสดงว่าเงียบ ระบบจำแนกได้เพียง
ลักษณะเสียงเบื้องต้น ไม่ยืนยันต้นเสียงหรือการตื่นของผู้พัก ตัวเลข
“ความมั่นใจของระบบ” ไม่ใช่อัตราความแม่นยำที่ผ่านการทดสอบภาคสนาม
คำเฉพาะ DSP และเลขรุ่นคงไว้ในส่วนข้อมูลวิศวกรรม ส่วนหน้าหลักใช้ภาษาไทย
นอก Session แสดงผลสดโดยไม่บันทึกไฟล์เสียงหรือสร้างประวัติใหม่ตามนโยบายเดิม

## คำตัดสินด้านผลิตภัณฑ์และ UX

ตำแหน่งหลักที่เหมาะสมคือ **หน้า Monitor สำหรับ Admin** ไม่ใช่หน้า Control และยัง
ไม่ควรแสดงผลจำแนกละเอียดบน User Dashboard เพราะผลเป็นการอนุมานที่ต้องมี
confidence, provenance และทางเลือก `unknown`

แยกการแสดงผลเป็นสองระดับ:

1. **Monitor · SMART EAR** — แสดงกราฟระดับเสียงตลอด Session, ค่าเฉลี่ย/สูงสุด,
   Coverage และช่วงที่ตรวจสอบย้อนกลับได้ เช่น ค่าระดับเปลี่ยนระหว่างจุดวัด
   ค่าสูงหลายจุดติดกัน
   หรือข้อมูลขาดช่วง
2. **ข้อมูลวิศวกรรมแบบพับเก็บ** — แสดง Version, Source และขอบเขตความสามารถ
   เท่าที่จำเป็น Candidate Registry, Release Gates และ Missing-feature list ไม่อยู่
   ในหน้าหลักเพราะยังไม่ใช่ผลตรวจของ Session

Packet Inspector ยังคงทำหน้าที่ตรวจค่าดิบและ Sensor contract ส่วน Smart Ear
ตีความ feature ที่ผ่าน contract แล้ว จึงไม่ควรรวมสองหน้าที่ไว้ในการ์ดเดียวกัน

รุ่น P0.6 เพิ่ม Admin-only Level Timeline จากข้อมูลจริงทุก 10 วินาที โดย API
`GET /api/v1/admin/acoustics/timeline` ส่งข้อมูลแบบย่อ ไม่ส่งกราฟทั้งคืนซ้ำผ่าน
WebSocket และไม่แก้ Raw timeline ผลจำแนกแหล่ง/ชนิดเสียงยังเป็น `not_evaluated`
จนมี feature telemetry และ classifier ที่ผ่าน Gate

รุ่น P1-shadow เพิ่มเส้นทางรองรับ `sound_class`, confidence, classifier version,
window sequence และ DSP features ตั้งแต่ Sensor contract → Session Timeline → API
→ สัญลักษณ์บน Monitor แล้ว พร้อม migration ฐานข้อมูลแบบ additive อย่างไรก็ตาม
Firmware ที่ build ได้ยังเป็น **validation candidate และยังไม่ได้ Flash ลงอุปกรณ์**
หน้า Monitor จึง fail-soft กลับเป็น Level Timeline เดิมจนได้รับ packet รุ่นใหม่จริง

SMART EAR ตรวจและแสดงค่าปัจจุบันได้ตลอดเวลาที่ Sensor พร้อม แม้ไม่มีผู้ใช้หรือ
Session แต่ข้อมูลนอก Session เป็น **ephemeral live observation** เท่านั้น: ไม่เพิ่ม
Timeline row, ไม่สร้างประวัติ และไม่ persist ลงฐานข้อมูล การบันทึกระดับเสียงและ
marker ตามเวลาจะเริ่มเมื่อ Session อยู่ใน phase `recording` เท่านั้น

## 1. ปัจจุบันระบบรู้อะไร

### LIVE · Telemetry ที่ Runtime รับและตรวจได้

- Sensor Hub 1 ส่ง `sound_dba` จาก SPH0645LM4H-B มาให้ Pi โดยตรง
- Production packet ที่ตรวจจริงเมื่อ 17 ก.ย. 2026 ส่ง window summary เพิ่ม ได้แก่
  `sound_dbfs`, `sound_dbfs_a`, `sound_rms`, `sound_rms_a`, `sound_peak`,
  `sound_peak_a`, `sound_laeq_dba`, `sound_sample_rate_hz`, `sound_samples` และ
  `sound_window_ms`; Pi รับเฉพาะ finite number และแสดงใน Admin engineering view
- ตัวอย่างที่ตรวจบน Pod: 32 kHz, 32,000 samples, window 1,000 ms,
  RMS 0.0027727, Peak 0.009334 และ Crest factor ที่ Pi คำนวณได้ประมาณ 3.37
- Pi ตรวจ finite/range/freshness และไม่ทำ `abs`, bias หรือ recalibration ซ้ำ
- ระบบสรุป valid dBA observations ในแต่ละ Sensor frame ด้วยค่าเฉลี่ยเชิงพลังงาน,
  min, max, span, sample count และธงการเปลี่ยนระดับมาก
- Timeline บันทึกระดับเสียงตาม cadence ของ Session; ฝั่ง Pi/runtime ใน repository
  ปัจจุบันไม่มีฐาน Raw audio/PCM
- Level Timeline ตรวจได้เฉพาะ `ระดับเปลี่ยนระหว่างจุดวัด`, `ค่าสูงหลายจุด` และ
  `ข้อมูลขาดช่วง` พร้อมเวลา/ระยะเวลา/ระดับเสียง โดยไม่ตั้งชื่อแหล่งเสียง
- Sleep model ใช้เสียงเป็นเพียง bounded corroboration เมื่อ BCG/movement สนับสนุน
  ไม่สร้าง Sleep State จากเสียงเพียงอย่างเดียว

### UNKNOWN · ยังสรุปไม่ได้

- แหล่งกำเนิดจริงของเสียงจาก microphone เดียว
- ตำแหน่ง ทิศทาง ผู้พูด หรือเนื้อหาคำพูด
- Production firmware ที่ติดตั้งอยู่ยังไม่มี DSP class/version ตาม contract ใหม่
- Production firmware ยังไม่ส่ง spectral centroid/flatness/flux, band ratios,
  syllabic modulation หรือ breathing periodicity จึงยังแยก `snore_like` กับ
  `speech_like` ไม่ได้อย่างรับผิดชอบ
- ค่าปัจจุบันเป็น certified LAeq(A) หรือผ่านมาตรฐานเครื่องวัด Class 1/2 หรือไม่
- ACK ของแอร์/พัดลมหมายความว่าอุปกรณ์กายภาพกำลังสร้างเสียงจริงหรือไม่

### สิ่งที่ยังไม่มีใน Production

ไม่มี PCM/spectrum บน Pi และจะไม่เพิ่ม PCM บน Pi ค่า RMS/Peak/Crest ที่มีแล้วใช้
ตรวจคุณภาพและรูปทรง amplitude window แต่ไม่เพียงพอระบุแหล่งเสียง รุ่น P0.6 มี
event detector สำหรับ **รูปแบบระดับเสียง** และ event-bout แบบ deterministic แล้ว
แต่ scalar dBA เพียงค่าเดียวยังไม่อาจแยก compressor, airflow, door, music หรือ
external noise ได้อย่างน่าเชื่อถือ ส่วน P1-shadow candidate คำนวณ FFT/features
บน ESP32 และส่งเฉพาะผลย่อ แต่ยังต้องผ่าน controlled physical validation

### กฎ Level Timeline ที่ LIVE

| เหตุการณ์ | หลักฐานที่ใช้ | สิ่งที่ห้ามสรุป |
|---|---|---|
| ระดับเสียงเปลี่ยนระหว่างจุดวัด | ต่างอย่างน้อย 6 dB ระหว่างจุดตาม cadence | ไม่บอกว่าเกิดจากอะไรหรือเกิดเร็วกว่า cadence เพียงใด |
| ค่าระดับเสียงสูงหลายจุดติดกัน | อย่างน้อย 50 dBA และช่วงระหว่างจุดแรกถึงจุดท้ายอย่างน้อย 30 วินาที | ไม่อ้างว่าเป็น continuous LAeq(A) หรือทำให้ผู้ใช้ตื่น |
| ข้อมูลเสียงขาดช่วง | ไม่มีค่าที่ใช้ได้อย่างน้อย 2 รอบ Sensor | ไม่ตีความเป็นความเงียบ |

ค่า threshold เหล่านี้เป็น Engineering review trigger สำหรับทีม ไม่ใช่การวินิจฉัย
หรือเกณฑ์คะแนน และถูก Version ไว้ในโมดูล `acoustics/level_events.py`

BCG vendor status `5` ที่ UI เรียกว่า `Snoring flag` เป็น flag จากอุปกรณ์ BCG
คนละแหล่งกับ microphone และไม่ใช่ Smart Ear classifier หรือการวินิจฉัยการกรน

## 2. เป้าหมายและสิ่งที่ไม่ทำ

### เป้าหมาย

- ช่วยทีมตอบว่าเสียง “คงที่ เปลี่ยนฉับพลัน เป็นโทน หรือเป็นช่วง ๆ” อย่างไร
- เสนอ likely source เพื่อค้นปัญหาแอร์ พัดลม ระบบระบาย ประตู หรือเสียงของ ZEEP
- เชื่อม timeline เสียงกับ device intent, BCG/movement และ feedback โดยใช้คำว่า
  “สัมพันธ์กัน” ไม่กล่าวว่าเป็นสาเหตุโดยอัตโนมัติ
- สร้างข้อมูล versioned สำหรับพัฒนาความเงียบและประสบการณ์พักผ่อนในแต่ละ Pod

### ไม่ทำในรุ่นแรก

- ไม่ฟัง/ถอด/เก็บเนื้อหาคำพูด และไม่ระบุตัวบุคคลด้วยเสียง
- ป้าย `speech_like` และ `snore_like` แสดงเฉพาะ Admin พร้อมคำว่า “ผลทดลอง”
  และ confidence; ห้ามสร้าง label `apnea` หรือแสดงเป็นผลตรวจสุขภาพ
- ไม่เปลี่ยน Sleep State, Sleep Score หรือ Recovery Score
- ไม่สั่งแอร์ เพลง พัดลม ประตู หรืออุปกรณ์ใดอัตโนมัติ
- ใช้ Firmware candidate เพื่อ Flash เก็บหลักฐานจริงได้ แต่ไม่ถือ source ใน Git
  เป็น Production truth จนกว่าจะยืนยันจาก telemetry และผลทดสอบบนบอร์ด

## 3. Taxonomy รุ่นแรก

แยก **ลักษณะสัญญาณ** ออกจาก **แหล่งที่เป็นไปได้** เพื่อไม่ให้ classifier ฟันธง
เกินหลักฐาน

### Acoustic shape

| Key | ความหมายที่แสดงต่อ Admin |
|---|---|
| `quiet_steady` | เงียบและระดับคงที่ |
| `steady` | เสียงต่อเนื่องค่อนข้างคงที่ |
| `tonal` | มีโทนเด่นหรือเสียงหึ่งต่อเนื่อง |
| `impulsive` | มีเสียงกระชาก/กระแทกสั้น |
| `intermittent` | เสียงเกิดและหยุดเป็นช่วง |
| `modulated` | ระดับหรือย่านความถี่เปลี่ยนเป็นจังหวะ |
| `unknown` | หลักฐานไม่พอหรืออยู่นอกชุดที่เรียนรู้ |

### Likely source

| Key | ป้ายที่เสนอ | ขอบเขตคำอธิบาย |
|---|---|---|
| `airflow_like` | คล้ายเสียงลม/พัดลม | ต้องมี spectral/temporal evidence; command state เป็นบริบทเท่านั้น |
| `compressor_transition_like` | คล้ายช่วงคอมเพรสเซอร์เปลี่ยนสถานะ | ใช้ device timing ประกอบ แต่ไม่ถือ ACK เป็น ground truth |
| `ventilation_or_purifier_like` | คล้ายระบบระบาย/กรองอากาศ | ต้องแยกจาก airflow อื่นด้วย controlled test |
| `zeep_audio_likely` | มีแนวโน้มเป็นเสียงที่ ZEEP เล่น | เทียบ playback state/feature โดยไม่บันทึกเนื้อหาเสียง |
| `door_or_mechanical_like` | คล้ายประตูหรือแรงกระแทกเชิงกล | ใช้ command/event timing และ transient shape |
| `other_or_unresolved` | แหล่งอื่นหรือยังแยกไม่ได้ | microphone เดียวไม่ใช้ตัดสินว่าเสียงมาจากภายนอก |
| `unknown` | ยังระบุแหล่งไม่ได้ | เป็นผลลัพธ์ปกติ ไม่ใช่ error |

ห้ามเพิ่ม `speech`, `snore`, `cough` หรือชื่อภาวะสุขภาพใน Production taxonomy
โดยไม่มี purpose-specific consent, validation protocol และ Privacy/Safety approval

### Purpose-gated human-sound research

| Key | ป้าย Candidate สำหรับงานวิจัย | สถานะ |
|---|---|---|
| `speech_like` | คล้ายเสียงพูด · ไม่ถอดคำ | Research Candidate · กำลังพิสูจน์ |
| `snore_like` | คล้ายรูปแบบเสียงกรน · ไม่ใช่การวินิจฉัย | Research Candidate · กำลังพิสูจน์ |
| `cough_like` | คล้ายเสียงไอ · ไม่ใช่การประเมินโรค | Research Candidate · กำลังพิสูจน์ |
| `breathing_pattern_like` | คล้ายรูปแบบการหายใจ · เพื่อวิจัยเท่านั้น | Research Candidate · กำลังพิสูจน์ |

ทะเบียนนี้แจ้งความเป็นไปได้ให้ทีมเห็น ไม่ใช่การอนุมัติให้ classifier ส่งผล ต้องยึด
[ZEEP-ACOUSTIC-SHADOW-001](../../research/evidence-library/ACOUSTIC_INTELLIGENCE_VALIDATION.md)
และผ่าน Gate ราย class ก่อนเลื่อนสถานะ

## 4. Architecture ที่เสนอ

```text
SPH0645 PCM (ESP32 only)
   │
   ├─> level path ─> verified weighting/window/calibration ─> sound_dba
   │
   └─> privacy-first DSP features
          RMS/peak/crest · band energy · spectral shape
          periodicity/modulation · transient count · coverage/clipping
             │ versioned USB telemetry; no continuous PCM
             ▼
Pi acoustics contract validator
   ▼
Interpretable classifier + unknown rejection
   ▼
Temporal event tracker / smoothing
   ├─> Admin live projection
   ├─> derived event aggregate (approved retention only)
   └─> correlation with device intent + BCG/movement [SHADOW]
```

ระดับเสียงที่ต้องเทียบ meter กับ feature สำหรับ classifier ต้องแยก path กัน
A-weighted signal เหมาะกับระดับที่มนุษย์รับรู้ แต่การจำแนก source อาจต้องใช้
spectral features ที่ไม่ถูก weighting จนสูญข้อมูล

### Module boundary ที่เสนอ

```text
acoustics/
  contracts.py          validate schema/version/range/quality
  feature_projection.py map firmware telemetry to typed features
  classifier.py         interpretable rules/model + abstain
  event_tracker.py      smoothing, bout start/end, restart continuity
  privacy.py            redaction/retention/public boundary
  monitor_projection.py Admin-only response
```

ห้ามเพิ่ม logic เหล่านี้ลง `app.py`; composition root ทำเพียง wiring/lifecycle

## 5. Telemetry contract ที่ใช้ใน P1-shadow

### Routing decision

Current reader รับ `event=environment`, schema `zeep.sensor.telemetry` version `1.0`
P1-shadow เลือกขยาย nested `sph0645.values` แบบ **positive allowlist** เพราะ label
เกิดจากหน้าต่างเสียงเดียวกับ `sound_dba` และต้องเดินทางด้วย clock/sequence เดียวกัน
Unknown field ยังถูกตัดทิ้ง และ Legacy flat bridge ไม่ใช่ authority ของ DSP fields

- `sound_dba` ยังคงเป็นค่าระดับเสียงหลักและทำงานได้แม้ DSP ไม่พร้อม
- `sound_class`, state, confidence, classifier version และ feature scalars เป็น optional
- Pi จะรับ label เฉพาะ state `provisional`, class อยู่ใน allowlist, confidence finite
  และ microphone live; เงื่อนไขไม่ครบจะเป็น `insufficient_input`
- ไม่รับ array/blob/base64/PCM หรือข้อความคำพูดผ่าน contract นี้

Clock contract ต้องอาศัย `boot_id`, `sequence` และ monotonic timestamp จาก ESP32
จากนั้น Pi ประทับ `received_at_utc` และเก็บ clock mapping/drift policy การให้ ESP32
ส่ง UTC เองโดยไม่มี synchronization ไม่เพียงพอสำหรับ correlate กับ BCG/device event

ตัวอย่าง wire fields ภายใน `sensors.sph0645.values` (ค่าตัวเลขเป็นตัวอย่าง):

```json
{
  "sound_dba": 43.2,
  "sound_window_sequence": 1842,
  "sound_class": "snore_like",
  "sound_class_state": "provisional",
  "sound_class_confidence": 0.78,
  "sound_event_detected": true,
  "sound_classifier_version": "zeep-dsp-rule-v0.1-shadow",
  "sound_low_band_ratio": 0.61,
  "sound_mid_band_ratio": 0.31,
  "sound_high_band_ratio": 0.08,
  "sound_spectral_centroid_hz": 418.0,
  "sound_spectral_flatness": 0.18,
  "sound_spectral_flux": 0.07,
  "sound_crest_factor": 4.2,
  "sound_syllabic_modulation": 0.05,
  "sound_breathing_periodicity": 0.62,
  "sound_breathing_period_s": 3.6
}
```

ESP32 ไม่มี UTC; Pi ผูก label เข้ากับเวลารับ Sensor frame และ Session sample
โดยใช้ `boot_id`, packet sequence และ `sound_window_sequence` ป้องกันการนับซ้ำ

ใช้ชื่อ `laeq_dba` ได้ต่อเมื่อ contract ยืนยัน A-weighting, integration window,
time behavior และ calibration provenance ชัดเจน ก่อนหน้านั้นให้ใช้ชื่อกลาง เช่น
`sound_dba` และอธิบาย method ตามจริง

ชื่อ current compatibility fields `leq_dba`, `sound_leq_dba` และ method
`energy_average_leq` เป็นหนี้ด้าน naming ของ packet-level energy aggregation
ไม่ใช่หลักฐาน metrology P0 ต้องเลือก rename/version หรือประกาศ alias ชัดก่อนเพิ่ม
DSP contract เพื่อไม่ให้ทีม Data/ML ตีความเป็น certified LAeq(A)

ทุก packet ต้องมี version, timestamp, coverage, clipping/quality และ fail-soft:
feature เสียต้องตัดเฉพาะ acoustic intelligence ไม่ทำให้ temperature/humidity/lux,
Session หรือ Safety pipeline หยุด

Feature schema ต้องนิยามหน่วย, reference, band edges, filter/FFT window/hop,
anti-alias/downsample method, denominator ของ coverage และสูตร periodicity/flatness/
modulation ให้ทำซ้ำได้ ไม่ให้ชื่อ field เดียวมีความหมายเปลี่ยนตาม firmware

Privacy flag ใน packet เป็น provenance ไม่ใช่การบังคับ parser ต้องใช้ positive
allowlist ของ scalar/array ตัวเลขที่มีขนาดจำกัด, จำกัด packet size และ reject
binary/string blob, base64 กับ unknown field พร้อม regression ว่า PCM ไม่เข้า
API, log หรือ database

## 6. API และ Storage

### Admin transport และ API

P1-shadow ใช้ **Admin WebSocket projection** สำหรับค่าปัจจุบัน และ REST แบบ read-only
สำหรับ contract กับ Timeline ของ Session:

- `GET /api/v1/admin/contracts/acoustics`
- `GET /api/v1/admin/acoustics/live`
- `GET /api/v1/admin/acoustics/timeline`

ทุกเส้นทางต้องอ่าน projection service เดียวกัน ใช้ positive allowlist และ
`Cache-Control: private, no-store` สำหรับ HTTP response

Timeline endpoint รวม level-pattern event จาก Pi กับ provisional DSP event จาก
Firmware โดย persist allowlisted label/confidence/features ใน `timeline` พร้อม
Session เท่านั้น ไม่มี acoustic database แยก Candidate Registry ยังอยู่เฉพาะ
contract endpoint และ label ห้ามถูกตีความเป็นผลตรวจสุขภาพ

ตัวอย่าง classification response:

```json
{
  "version": "zeep-acoustic-intelligence-v1",
  "status": "shadow",
  "observed_at": "2026-09-17T10:00:00Z",
  "mixed_or_unresolved": true,
  "shapes": [
    {"label": "steady", "classifier_score": 0.86},
    {"label": "tonal", "classifier_score": 0.71}
  ],
  "likely_sources": [
    {"label": "compressor_transition_like", "classifier_score": 0.78},
    {"label": "airflow_like", "classifier_score": 0.64}
  ],
  "confidence_band": "medium",
  "reason_codes": ["low_band_tonal", "device_transition_nearby"],
  "evidence": {
    "signal_quality": "usable",
    "bcg_or_movement_corroborated": false,
    "device_context_is_ground_truth": false
  },
  "provenance": {
    "feature_schema_version": "1.0",
    "classifier_version": "shadow-1",
    "firmware_version": "required"
  },
  "privacy": {
    "raw_audio_retained": false
  },
  "clinical_validated": false,
  "automatic_actuation": false
}
```

### Storage decision

P1-shadow เก็บ allowlisted label/confidence/features ลง `timeline` เฉพาะขณะ
Recorded Session เพื่อรักษาเวลาเดียวกับ Sensor อื่นและรองรับ restart เหตุการณ์ตอน
Pod ว่าง/commissioning ไม่ถูกเก็บเป็น Session และห้ามสร้าง Session ปลอม

หากงาน R&D ต้องใช้ feature cadence 10 วินาทีเพื่อทำซ้ำ confusion matrix จึงค่อย
เสนอ `acoustics.db` แยก โดยต้องกำหนด schema, ground-truth link, backup, snapshot,
retention, account erasure และ migration ก่อนเริ่ม P3; การเก็บเฉพาะ summary จะไม่พอ
สำหรับ reproduce หรือฝึก classifier

Raw PCM ต้องไม่ถูกส่งหรือเก็บเป็นค่าเริ่มต้น การเก็บตัวอย่างเสียงเพื่อสร้าง dataset
เป็นโครงการวิจัยแยก ต้องมี consent, coded identity, encrypted storage, retention,
access log และ erasure owner โดยไม่ปะปนกับ Production Session store

Derived acoustic feature ที่ผูกเวลา/Session ยังเป็นข้อมูลส่วนบุคคลที่ link กลับได้
Shadow Pilot จึงต้องมี user notice/lawful-basis review ด้วย ไม่ใช่รอเฉพาะเมื่อเก็บ
Raw PCM ส่วน operator annotation ใช้ controlled vocabulary และ audit trail แทน
free text เพื่อลด PII และ label drift

## 7. รูปแบบหน้า Monitor

### Section 01 · Sensor integrity

คงการ์ด SPH0645 เดิมและเพิ่มเฉพาะข้อมูลความพร้อมของ pipeline:

- microphone validity/freshness
- firmware/DSP schema version
- feature coverage และ clipping
- สถานะ `LIVE / STALE / INVALID / LEVEL-ONLY`

### Section 03 · Sound Intelligence (SHADOW)

```text
┌ หูอัจฉริยะ · SOUND INTELLIGENCE                 SHADOW ┐
│ 43.2 dBA       เสียงต่อเนื่องค่อนข้างคงที่              │
│ มีแนวโน้ม: เสียงลม/พัดลม · ความมั่นใจระดับกลาง          │
│ ─── trend 10 นาที + event markers ──────────────────    │
│ ล่าสุด 02:14 · เสียงกระชากสั้น · ไม่พบ Movement ร่วม     │
│ วิเคราะห์รูปแบบสัญญาณ · ไม่บันทึกเสียงพูด               │
└─────────────────────────────────────────────────────────┘
```

ใช้ภาษาว่า “คล้าย”, “มีแนวโน้ม” และแสดง `unknown` อย่างสงบ ไม่ใช้สีแดงเมื่อ
classifier ไม่มั่นใจ สีเตือนด้านความปลอดภัยต้องมาจากระดับเสียง/ระบบ Safety ที่มี
contract แยกเท่านั้น

ค่า `classifier_score` ไม่ใช่ probability ห้ามแสดงเป็นเปอร์เซ็นต์จนผ่านการสอบเทียบ
ความน่าจะเป็นและรายงาน reliability/ECE/Brier แล้ว คะแนนของหลาย label เป็นอิสระ
ต่อกันและไม่ต้องรวมเป็น 1 ช่วงแรก UI ใช้ `low/medium/high`

### Section 04 · Acoustic DSP Inspector

- feature/band timeline และ transient markers
- window coverage, dropped/invalid/clipping count
- top alternatives และ reason codes
- firmware/feature/classifier version
- nearby device intent/ACK และ BCG/movement correlation
- แสดง operator annotation ที่มาจาก Commissioning audit แบบ read-only

### Control Debug · Acoustic Commissioning

การใส่ ground-truth label เป็น write action จึงอยู่ที่ `/control-debug` หรือ dedicated
commissioning surface ไม่อยู่ใน Monitor ต้องใช้ Admin RBAC, CSRF, controlled
vocabulary, timestamp/actor audit และปิดใช้งานระหว่าง Session ของผู้ทดสอบ

### หน้าอื่น

| หน้า | ระยะเริ่มต้น | หลังผ่าน validation |
|---|---|---|
| Dashboard | คง dBA และสถานะ Sensor | แสดงได้เพียง “สภาพเสียงนิ่ง/มีเสียงเปลี่ยน” |
| Control | คง dBA, audio และ device control | ไม่เพิ่ม DSP diagnostics |
| Sessions | ไม่ใช้ผล classifier | แสดง aggregate เช่น “พบเสียงเปลี่ยน 3 ช่วง” พร้อม confidence/correlation |
| App/Public API | ไม่ส่ง classifier | เปิดเฉพาะ allowlisted summary หลัง Product/Privacy approval |

## 8. Validation plan

### Controlled dataset

ทดสอบแยกและผสมอย่างน้อย:

- ทุกอุปกรณ์ปิด / ambient หลายช่วงเวลา
- แอร์ fan 1–5, compressor start/run/stop และ setpoint ต่างกัน
- พัดลมระบาย, เครื่องกรอง/ดูดกลิ่น และ aroma/steam ตามสภาพใช้งานจริง
- เพลงหลาย track ที่ 20/40/60% และช่วงเริ่ม/หยุด
- ประตู เตียง การกระแทกเบา และเสียงภายนอกที่ควบคุมได้
- หลายรอบ หลาย Pod และตำแหน่งเครื่องนอนที่ต่างกัน

ใช้ timestamp ที่ sync, CEM DT-8852 สำหรับระดับเสียง, device event log และ operator
ground-truth แยกจาก classifier output ห้ามใช้ command ACK เพียงอย่างเดียวเป็น label

CEM DT-8852 ตรวจ path ระดับเสียงเท่านั้น ไม่ได้ยืนยัน band, tonality หรือ source
ความถูกต้องของ DSP feature ต้องมี golden PCM/synthetic vectors ที่ทราบ frequency,
amplitude, impulse และ modulation โดยไม่ใช้ข้อมูลผู้ใช้จริง

### Metric ที่ต้องรายงาน

- coverage/packet loss, latency และ CPU/RAM
- precision, recall และ F1 **ราย class**; ไม่ใช้ accuracy รวมเพียงค่าเดียว
- false alert ต่อชั่วโมงในช่วง quiet/stable
- unknown/rejection rate และ performance เมื่อเจอ source นอกชุดฝึก
- event onset/end timing error และผลหลัง restart/packet gap
- ความต่างระหว่าง Pod/ตำแหน่ง/อุณหภูมิ/ระดับอุปกรณ์
- privacy, retention, erasure และ public-redaction tests
- แยก train/validation/test ตาม Pod, run, date และ participant; ไม่สุ่ม 10-second
  window จาก Session เดียวกันข้ามชุด และต้อง hold out unseen Pod/source/mixed case
- macro-F1/PR, rejection calibration และ reliability เมื่อจะใช้ confidence เป็นตัวเลข

เกณฑ์เริ่มต้นที่เสนอคือ valid-feature coverage อย่างน้อย 95%, ไม่มี Raw PCM หลุด
ออกจาก boundary และทุกผลมี confidence band/unknown/provenance ส่วน latency แยกเป็น
feature publication หลัง window ปิด, provisional inference และ confirmed bout หลัง
smoothing เพราะ event tracker อาจใช้ 2–3 windows เกณฑ์ precision/recall/latency
ราย class ต้องกำหนดจากความเสี่ยงและจำนวนตัวอย่างก่อนเริ่ม Pilot ห้ามปรับหลังเห็นผล
เพื่อให้ผ่าน

## 9. ลำดับพัฒนาและ Gate

| Phase | ผลส่งมอบ | Gate ก่อนขยับ |
|---|---|---|
| **P0 · Contract** | หา Production firmware source/version, แยก level/feature path, อนุมัติ routing/clock/taxonomy/schema/privacy/RACI และแก้ข้อความ UI เดิมที่ยังเรียกเสียงว่า estimate จาก dBFS | Firmware + Pi + Product + Privacy ลงนาม; no-score/no-actuation test |
| **P1 · Feature telemetry** | ESP32 ส่ง feature แบบ versioned; Pi validate และแสดง quality | Golden vectors, meter comparison, fail-soft, restart/packet-loss tests |
| **P2 · Controlled labeling** | Dataset จากสถานะอุปกรณ์ที่รู้จริงและหลายรอบ | Pre-register protocol/owner ใน Evidence library, dataset register, label audit และ per-class metric plan |
| **P3 · Shadow classifier** | Admin-only inference + unknown rejection; ไม่ persist เกิน policy | Confusion matrix, false-alert/unknown/latency report |
| **P4 · Pilot Monitor** | Live card, DSP Inspector และ operator feedback | Privacy/UI review, hardware smoke, no regression ต่อ Session/Safety |
| **P5 · Session aggregate** | Derived event summary สำหรับ Admin | Correlation review; ยืนยันว่าไม่เปลี่ยน State/Score |
| **P6 · User summary** | ข้อความสั้นที่ผ่าน Product/Privacy | Evidence เพียงพอ, copy review, positive allowlist |

Adaptive recommendation เป็นแผนหลัง P6 และยังคงให้มนุษย์ยืนยันก่อนปรับอุปกรณ์
Automatic actuation ต้องมี safety proposal และ validation แยก ไม่ได้อนุมัติด้วยแผนนี้

## 10. RACI

| งาน | Responsible | Accountable/Approver |
|---|---|---|
| Production firmware และ DSP feature | Firmware/Hardware | Hardware owner |
| Contract, validation, API/storage | Pi team | Pi lead |
| Taxonomy และข้อความ | Product/UX | Product owner |
| Dataset/classifier/evaluation | Data/ML | Model owner |
| Consent, retention, erasure | Privacy/Data governance | Data controller |
| No-actuation/fail-safe | Safety + QA | Safety owner |
| Deploy, smoke, rollback | Operations | Release owner |

## 11. Workflow การ Flash ทดลองและเกณฑ์รับรองใช้งานถาวร

- [ ] ได้ Production Sensor Hub 1 firmware source, version และ checksum ที่ตรวจได้
- [ ] ระบุ sample rate, bit alignment, weighting, window และ calibration ของ level path
- [x] กำหนด event routing และ strict field allowlist ฝั่ง Pi
- [x] กำหนด feature schema/taxonomy/unknown behavior และ regression tests ฝั่ง Pi
- [ ] อนุมัติ no-raw-audio default, consent, retention, access และ erasure boundary
- [ ] ระบุ test matrix, metric, sample count และ acceptance ก่อนเก็บผล
- [ ] ยืนยัน Admin WebSocket เป็น current-level transport, REST เป็น
      level-timeline/contract transport,
      projection service เดียว และ public positive allowlist
- [ ] ยืนยันว่า Sleep State/Score/Control ไม่อ่าน classifier output
- [ ] มี rollback ที่ปิด Smart Ear ได้โดยไม่ปิด Sensor Hub 1 หรือ Session

การ Flash เป็นขั้นตอนสร้างหลักฐาน Physical Pilot ไม่ต้องรอ checklist ครบทั้งหมด
ก่อนเริ่ม แต่ทุกครั้งต้อง Pod ว่าง, backup, identity, verify และ rollback พร้อม
รายการที่ยังไม่ครบทำให้ label คงสถานะ **P1-shadow candidate** และยังไม่ถือเป็น
ความสามารถที่รับรองแล้ว Meter regression ทำหลัง Flash และใช้ตัดสินว่าจะคงรุ่นนั้น
หรือ rollback

## 12. เอกสารและทะเบียนที่เกี่ยวข้อง

- Current hardware path: [Hardware และ Hub map](hardware-hub-map.md)
- Current Sensor contract: [Sensor Interface Contract v1.2](../zeep-sensor-interface-contract-v1.2.md)
- API/Privacy boundary: [API, Data และ Privacy](api-data-and-privacy.md)
- ตำแหน่งหน้าและ UI standard: [Interface Map & UI Standard](../zeep-interface-map-and-ui-standard-v1.md)
- Audio output ซึ่งเป็นคนละ boundary: [Brainwave Sound Lab](../brainwave-sound-lab-v1.md)
- Protocol governance: [Evidence Protocol Register](../../research/evidence-library/protocol-register.json)
- Proof protocol: [Acoustic Intelligence Validation](../../research/evidence-library/ACOUSTIC_INTELLIGENCE_VALIDATION.md)
